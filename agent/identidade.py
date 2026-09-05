"""
A credencial do agente na estação: de quem ele age, e onde isso fica guardado.

Par do lado servidor em `app/agent_devices.py`. Aqui vive o que a máquina
guarda: um segredo de dispositivo, trocado por JWT curto quando o agente
precisa falar com o portal.

── Por que no perfil do usuário, e não em ProgramData ────────────────────

O segredo É a pessoa. Um dispositivo emite token com o papel real dela, então
guardá-lo num diretório legível por toda a máquina daria a qualquer conta local
o poder daquela pessoa no portal — inclusive o de resgatar certificado por
`/redeem`.

Isto também é o que prepara a fase 2. Hoje o laço que instala roda no serviço,
como LocalSystem, e `certutil -user … My` põe o certificado no perfil do SYSTEM:
o `certutil` diz OK, a trilha grava INSTALADO, e a pessoa não vê nada no
navegador. A instalação tem de passar para o processo da bandeja, que roda na
sessão dela — e é lá, e só lá, que esta credencial existe.

── ⚠️ A outra face da mesma moeda (24/08/2026; atualizada em 01/09/2026) ──

O que protege esta credencial é o que a impede de servir ao agente.

`run_agent._headers()` **nunca** usa o que está guardado aqui. Isso não é
fiação esquecida: quem faz todas as chamadas autenticadas (`/api/ingest`,
upload de PFX, configurações) é o **serviço**, como LocalSystem, e ele não
decifra um blob DPAPI do perfil de outra conta. A bandeja, que alcançaria este
arquivo, não faz chamada autenticada nenhuma além do registro.

Então **fazer o login hoje grava um segredo que nada lê.** Por isso, desde
04/09/2026, a bandeja NÃO tem mais o item "Entrar no portal…" nem abre a
janela sozinha na primeira execução: a bandeja roda num servidor, e a única
coisa que a janela produzia ali era a pergunta "que conta eu coloco?". Este
módulo e `janela_login` ficam intactos e testados, sem porta de entrada, à
espera da fase 2 (`tests/test_janela_login.py` vigia que a porta não volte
em silêncio).

O outro objeto que essa nota pedia existe desde 01/09/2026: a credencial de
MÁQUINA (`agent/identidade_maquina.py`, ProgramData, DPAPI de escopo máquina),
que `_headers()` passou a preferir no lugar da `X-API-Key` compartilhada. Ela
não muda nada AQUI: máquina e pessoa seguem sendo duas identidades, e esta —
a da pessoa — continua à espera da fase 2.

── DPAPI, e a recusa em degradar ─────────────────────────────────────────

O arquivo é cifrado com DPAPI no escopo do usuário: quem não é ele não decifra,
mesmo com o arquivo em mãos. Se a DPAPI não estiver disponível, `guardar`
**levanta** em vez de gravar em claro. Gravar texto puro "para funcionar
também no Linux" seria a classe de defeito que este repositório vem
documentando: continua funcionando, ninguém percebe, e a garantia sumiu.

── O que este módulo não faz ─────────────────────────────────────────────

Não importa `run_agent`, pelo mesmo motivo que `janela_status` não importa:
quem chama é o menu da bandeja, dentro do `run_agent`, e o import circular
apareceria na primeira vez que alguém mexesse. Recebe tudo por parâmetro.
"""

from __future__ import annotations

import ctypes
import json
import logging
import os
import sys
import time
from ctypes import wintypes
from pathlib import Path
from typing import Any, Dict, Optional

LOGGER = logging.getLogger(__name__)

ARQUIVO = "dispositivo.dat"
PASTA = "Analise CertiDigital Agent"

# Entropia adicional da DPAPI. Não é segredo — está no código, e nem precisa
# ser: ela amarra o blob a ESTE uso, de modo que um arquivo copiado não seja
# decifrável por outro programa que apenas chame CryptUnprotectData no mesmo
# perfil. Defesa em profundidade, não a garantia principal.
_ENTROPIA = b"analise-certidigital-agente-dispositivo-v1"

# Renova com folga em vez de esperar o 401. O 401 chegaria no meio de uma
# instalação, e o custo de renovar cedo é uma chamada barata.
FOLGA_DE_RENOVACAO_SEG = 300


class SemCofreLocal(RuntimeError):
    """DPAPI indisponível. Não gravamos o segredo em claro — ver docstring."""


class NaoRegistrado(RuntimeError):
    """Esta estação ainda não passou pela janela de login."""


# ──────────────────────────────────────────────────────────────────────────
# DPAPI
# ──────────────────────────────────────────────────────────────────────────

class _BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _blob(dados: bytes) -> _BLOB:
    buf = ctypes.create_string_buffer(dados, len(dados))
    return _BLOB(len(dados), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))


def _do_blob(b: _BLOB) -> bytes:
    return ctypes.string_at(b.pbData, b.cbData)


def dpapi_disponivel() -> bool:
    return sys.platform == "win32" and hasattr(ctypes, "windll")


def _crypt32():
    if not dpapi_disponivel():
        raise SemCofreLocal(
            "DPAPI indisponível nesta plataforma; o segredo do dispositivo não "
            "será gravado em claro."
        )
    return ctypes.windll.crypt32


def proteger(dados: bytes) -> bytes:
    entrada, entropia, saida = _blob(dados), _blob(_ENTROPIA), _BLOB()
    ok = _crypt32().CryptProtectData(
        ctypes.byref(entrada), None, ctypes.byref(entropia), None, None, 0,
        ctypes.byref(saida),
    )
    if not ok:
        raise SemCofreLocal(f"CryptProtectData falhou ({ctypes.GetLastError()}).")
    try:
        return _do_blob(saida)
    finally:
        ctypes.windll.kernel32.LocalFree(saida.pbData)


def desproteger(dados: bytes) -> bytes:
    entrada, entropia, saida = _blob(dados), _blob(_ENTROPIA), _BLOB()
    ok = _crypt32().CryptUnprotectData(
        ctypes.byref(entrada), None, ctypes.byref(entropia), None, None, 0,
        ctypes.byref(saida),
    )
    if not ok:
        raise SemCofreLocal(f"CryptUnprotectData falhou ({ctypes.GetLastError()}).")
    try:
        return _do_blob(saida)
    finally:
        ctypes.windll.kernel32.LocalFree(saida.pbData)


# ──────────────────────────────────────────────────────────────────────────
# Onde o arquivo vive
# ──────────────────────────────────────────────────────────────────────────

def caminho() -> Path:
    """
    `%LOCALAPPDATA%\\Analise CertiDigital Agent\\dispositivo.dat`.

    LOCALAPPDATA e não APPDATA: perfil móvel sincronizaria o arquivo para o
    servidor, e um blob DPAPI de outra máquina não decifra — daria "registre-se
    de novo" a cada logon numa estação diferente, sem explicação visível.
    """
    base = (os.getenv("LOCALAPPDATA") or "").strip()
    if not base:
        base = str(Path.home() / ".config")
    return Path(base) / PASTA / ARQUIVO


# ──────────────────────────────────────────────────────────────────────────
# Guardar e ler
# ──────────────────────────────────────────────────────────────────────────

def guardar(segredo: str, base_url: str, email: str, machine_id: str) -> Path:
    """
    Cifra e grava. Levanta `SemCofreLocal` em vez de gravar em claro.

    `base_url` fica junto de propósito: um segredo emitido por um portal não
    vale noutro, e guardá-los separados permitiria apontar o agente para outro
    endereço mantendo a credencial — que passaria a ser enviada para lá.
    """
    conteudo = json.dumps(
        {
            "segredo": segredo,
            "base_url": (base_url or "").strip().rstrip("/"),
            "email": (email or "").strip().lower(),
            "machine_id": (machine_id or "").strip(),
            "gravado_em": time.time(),
        },
        ensure_ascii=False,
    ).encode("utf-8")

    cifrado = proteger(conteudo)
    destino = caminho()
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_bytes(cifrado)
    return destino


def ler() -> Optional[Dict[str, Any]]:
    """
    O que foi guardado, ou None se não há registro nesta conta.

    Devolve None — e não levanta — quando o blob existe mas não decifra: é o
    caso de perfil restaurado ou máquina trocada, e o caminho certo dali é a
    janela de login, não um erro de aplicação.
    """
    origem = caminho()
    if not origem.is_file():
        return None
    try:
        return json.loads(desproteger(origem.read_bytes()).decode("utf-8"))
    except (SemCofreLocal, json.JSONDecodeError, UnicodeDecodeError, OSError):
        LOGGER.warning(
            "Credencial do dispositivo ilegível em %s; é preciso registrar de novo.",
            origem,
        )
        return None


def apagar() -> bool:
    origem = caminho()
    try:
        if origem.is_file():
            origem.unlink()
            return True
    except OSError:
        LOGGER.exception("Falha ao apagar a credencial do dispositivo")
    return False


def esta_registrado() -> bool:
    return ler() is not None


# ──────────────────────────────────────────────────────────────────────────
# Falar com o portal
# ──────────────────────────────────────────────────────────────────────────

def registrar(client, base_url: str, email: str, senha: str, machine_id: str,
              nome: str = "") -> Dict[str, Any]:
    """
    Troca e-mail + senha por um segredo de dispositivo, e guarda o segredo.

    A senha existe só dentro desta chamada. Não é gravada, não vai para log e
    não fica em atributo — quem a tem é a janela de login, que a descarta ao
    fechar.

    `client` é injetado (httpx.Client) para o teste não precisar de rede, e
    porque o `run_agent` já tem um configurado com os timeouts certos.
    """
    base = (base_url or "").strip().rstrip("/")
    r = client.post(
        f"{base}/api/agent/dispositivos/registrar",
        json={
            "email": email,
            "password": senha,
            "machine_id": machine_id,
            "nome": nome or machine_id,
        },
    )
    if r.status_code != 200:
        detalhe = ""
        try:
            detalhe = str((r.json() or {}).get("detail") or "")
        except Exception:  # noqa: BLE001
            detalhe = (r.text or "")[:200]
        raise RuntimeError(detalhe or f"O portal recusou o registro ({r.status_code}).")

    dados = r.json()
    guardar(dados["segredo"], base, dados.get("email") or email, machine_id)
    # O segredo não é devolvido: quem precisa dele é o disco, e devolvê-lo
    # convidaria a chamada seguinte a guardá-lo num segundo lugar.
    return {
        "email": dados.get("email"),
        "role": dados.get("role"),
        "machine_id": dados.get("machine_id"),
    }


class Sessao:
    """
    Mantém um JWT válido a partir do segredo guardado.

    Guarda o token em memória e renova antes de expirar. Nunca o escreve em
    disco: o durável é o segredo, que está sob revogação no portal — um token
    em arquivo sobreviveria à revogação até expirar, e sem ninguém saber onde.
    """

    def __init__(self, client, base_url: str) -> None:
        self._client = client
        self._base = (base_url or "").strip().rstrip("/")
        self._token: Optional[str] = None
        self._expira_em: float = 0.0
        self.papel: Optional[str] = None
        self.email: Optional[str] = None

    def _renovar(self) -> None:
        guardado = ler()
        if not guardado:
            raise NaoRegistrado(
                "Esta estação ainda não foi registrada. Abra o agente e faça login."
            )
        # A versão vai junto da renovação, e não num heartbeat próprio: é a
        # única chamada que já acontece de hora em hora, e um segundo endereço
        # só para dizer o número poderia continuar batendo com o segredo já
        # revogado — o portal veria "viva" uma máquina que não consegue mais
        # receber comando.
        from agent import __version__

        r = self._client.post(
            f"{self._base}/api/agent/dispositivos/token",
            json={"segredo": guardado["segredo"], "versao": __version__},
        )
        if r.status_code in (401, 403):
            # Revogado, ou conta sem acesso. Apagar o arquivo é a resposta
            # certa: manter um segredo que o portal já recusa faz o agente
            # tentar para sempre e esconde o motivo de quem olhar a estação.
            apagar()
            raise NaoRegistrado(
                "O portal recusou este dispositivo. Faça login de novo no agente."
            )
        if r.status_code != 200:
            raise RuntimeError(f"Falha ao renovar o acesso ({r.status_code}).")

        dados = r.json()
        self._token = dados["access_token"]
        self.papel = dados.get("role")
        self.email = guardado.get("email")
        minutos = int(dados.get("validade_token_min") or 60)
        self._expira_em = time.time() + max(60, minutos * 60 - FOLGA_DE_RENOVACAO_SEG)

        # Deixa rastro no agent.log quando esta estação está atrás do portal.
        # Não atualiza sozinho: hoje não há canal de distribuição do instalador
        # do agente. O registro é o que permite responder, num diagnóstico, se a
        # correção chegou aqui — antes disso a pergunta não tinha resposta.
        esperada = (dados.get("versao_esperada") or "").strip()
        self.versao_esperada = esperada or None
        if esperada and esperada != __version__:
            LOGGER.warning(
                "Agente na versão %s; o portal espera %s. Atualização pendente "
                "nesta estação.",
                __version__,
                esperada,
            )

    def cabecalhos(self) -> Dict[str, str]:
        """Cabeçalhos prontos para o portal, renovando se preciso."""
        if not self._token or time.time() >= self._expira_em:
            self._renovar()
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._token}",
        }

    def invalidar(self) -> None:
        """Força renovação na próxima chamada (usado ao levar 401 do portal)."""
        self._token = None
        self._expira_em = 0.0
