"""A conta deste portal nesta estação (ADR 0002), do lado da bandeja.

Veio de `core/conta_certificados.py` do Hardlyze. O segredo do dispositivo vive
em `%LOCALAPPDATA%\\CertguardAnalise\\conta.dat`, cifrado com DPAPI no escopo da
pessoa, junto do endereço do portal que o emitiu. A senha só existe dentro de
`registrar`. As chamadas levam o segredo em `X-Device-Secret`, e só nas rotas
da estação (ADR 0003): o dispositivo não abre sessão do portal.

Até 20/11/2026 a bandeja trazia uma vez a conta do `certificados.dat` do
Hardlyze (adendo de 14/10/2026 ao ADR 0003); essa migração foi retirada.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from pathlib import Path
from typing import Any

from estacao import caminhos
from estacao.dpapi import SemCofreLocal, desproteger, proteger

LOGGER = logging.getLogger(__name__)

ARQUIVO = "conta.dat"
PORTAL_PADRAO = "https://certificado.analisegroup.cnt.br"

_ENTROPIA = b"certguard-analise-conta-v1"


class NaoConectado(RuntimeError):
    """Ninguém entrou com a conta do portal nesta sessão do Windows."""


class SessaoEncerrada(RuntimeError):
    """O portal não reconhece mais este dispositivo (saiu, foi desvinculado,
    a senha foi redefinida ou a pessoa entrou noutra máquina)."""


def caminho() -> Path:
    return caminhos.pasta_pessoa() / ARQUIVO


def _gravar(dados: dict[str, Any]) -> Path:
    conteudo = json.dumps(dados, ensure_ascii=False).encode("utf-8")
    destino = caminho()
    destino.parent.mkdir(parents=True, exist_ok=True)
    # Grava ao lado e troca de uma vez: queda no meio não pode perder o último dono.
    # Nome único: duas gravações juntas não pisam no temporário uma da outra.
    cifrado = proteger(conteudo, _ENTROPIA)
    with tempfile.NamedTemporaryFile(dir=destino.parent, prefix=destino.name + ".", suffix=".tmp",
                                     delete=False) as f:
        temporario = Path(f.name)
    try:
        temporario.write_bytes(cifrado)
        os.replace(temporario, destino)
    except BaseException:
        temporario.unlink(missing_ok=True)
        raise
    return destino


def guardar(segredo: str, portal: str, email: str, machine_id: str) -> Path:
    return _gravar({
        "segredo": segredo,
        "portal": (portal or "").strip().rstrip("/"),
        "email": (email or "").strip().lower(),
        "machine_id": (machine_id or "").strip(),
        "gravado_em": time.time(),
    })


def _ler_de(origem: Path, entropia: bytes) -> dict[str, Any] | None:
    if not origem.is_file():
        return None
    try:
        dados = json.loads(desproteger(origem.read_bytes(), entropia).decode("utf-8"))
    except (SemCofreLocal, json.JSONDecodeError, UnicodeDecodeError, OSError):
        LOGGER.warning("Conta do portal ilegível em %s; é preciso entrar de novo.", origem)
        return None
    return dados if isinstance(dados, dict) and dados.get("segredo") else None


def ler() -> dict[str, Any] | None:
    """A conta ativa; a encerrada não vale (é só o último dono do perfil)."""
    dados = _ler_de(caminho(), _ENTROPIA)
    return None if not dados or dados.get("encerrada") else dados


def ultimo_dono() -> dict[str, Any] | None:
    """A conta encerrada deste perfil, ou None (ativa ou nunca houve)."""
    dados = _ler_de(caminho(), _ENTROPIA)
    return dados if dados and dados.get("encerrada") else None


def encerrar() -> None:
    """A sessão caiu ou a pessoa saiu: a conta deixa de valer, mas fica gravada
    como último dono. Apagar jogaria o perfil na regra do perfil sem login."""
    dados = _ler_de(caminho(), _ENTROPIA)
    if dados and not dados.get("encerrada"):
        _gravar({**dados, "encerrada": True})


def apagar() -> bool:
    try:
        if caminho().is_file():
            caminho().unlink()
            return True
    except OSError:
        LOGGER.exception("Falha ao apagar a conta do portal")
    return False


def esta_conectado() -> bool:
    return ler() is not None


def portal_da_conta() -> str:
    g = ler() or ultimo_dono()
    return ((g or {}).get("portal") or os.getenv("CERT_PORTAL_URL") or PORTAL_PADRAO).strip().rstrip("/")


def cabecalhos(versao: str = "") -> dict[str, str]:
    g = ler()
    if not g:
        raise NaoConectado("Entre na bandeja com sua conta do portal de certificados.")
    cab = {"Content-Type": "application/json", "X-Device-Secret": g["segredo"]}
    if versao:
        cab["X-Agent-Version"] = versao
    return cab


def _detalhe(r) -> str:
    try:
        return str((r.json() or {}).get("detail") or "")
    except Exception:  # noqa: BLE001
        return (getattr(r, "text", "") or "")[:200]


def registrar(sessao, portal: str, email: str, senha: str, machine_id: str, nome: str = "",
              chave_maquina: str | None = None) -> dict[str, Any]:
    """E-mail + senha viram segredo de dispositivo.

    Devolve `{email, autorizacao, mensagem}`; `autorizacao` é "autorizado" ou
    "pendente" (o administrador ainda vai autorizar este computador). Sem a
    chave da máquina, um computador já autorizado volta para a confirmação.
    """
    base = (portal or PORTAL_PADRAO).strip().rstrip("/")
    corpo = {"email": email, "password": senha, "machine_id": machine_id, "nome": nome or machine_id}
    if chave_maquina:
        corpo["chave_maquina"] = chave_maquina
    r = sessao.post(f"{base}/api/agent/dispositivos/registrar", json=corpo, timeout=30)
    return _guardar_resposta(r, base, email, machine_id)


def _guardar_resposta(r, base: str, email: str, machine_id: str) -> dict[str, Any]:
    if r.status_code != 200:
        raise RuntimeError(_detalhe(r) or f"O portal de certificados recusou o login ({r.status_code}).")
    dados = r.json()
    guardar(dados["segredo"], base, dados.get("email") or email, dados.get("machine_id") or machine_id)
    return {"email": dados.get("email"), "autorizacao": dados.get("autorizacao"), "mensagem": dados.get("mensagem")}


def microsoft_ligada(sessao, portal: str) -> bool:
    """O portal oferece a entrada pela Microsoft? Qualquer falha vale não."""
    try:
        base = (portal or PORTAL_PADRAO).strip().rstrip("/")
        r = sessao.get(f"{base}/api/agent/microsoft", timeout=5)
        return r.status_code == 200 and bool((r.json() or {}).get("ligado"))
    except Exception:  # noqa: BLE001
        return False


def registrar_pela_microsoft(sessao, portal: str, codigo: str, verificador: str, machine_id: str,
                             nome: str = "", chave_maquina: str | None = None) -> dict[str, Any]:
    """O código de uso único da Microsoft (com o verificador) vira segredo de dispositivo.
    Mesmo retorno de `registrar`."""
    base = (portal or PORTAL_PADRAO).strip().rstrip("/")
    corpo = {"codigo": codigo, "verificador": verificador, "machine_id": machine_id, "nome": nome or machine_id}
    if chave_maquina:
        corpo["chave_maquina"] = chave_maquina
    r = sessao.post(f"{base}/api/agent/dispositivos/registrar-microsoft", json=corpo, timeout=30)
    return _guardar_resposta(r, base, "", machine_id)


def _get(sessao, rota: str, versao: str) -> dict[str, Any]:
    r = sessao.get(portal_da_conta() + rota, headers=cabecalhos(versao), timeout=20)
    if r.status_code in (401, 403):
        # O portal derrubou esta sessão: a credencial não volta a valer, mas
        # fica como último dono do perfil (spec, "Último dono do perfil").
        encerrar()
        raise SessaoEncerrada(_detalhe(r) or "Sessão encerrada pelo portal de certificados.")
    if r.status_code != 200:
        raise RuntimeError(_detalhe(r) or f"Portal de certificados respondeu {r.status_code}.")
    return r.json() or {}


def situacao(sessao, versao: str = "") -> dict[str, Any]:
    """`{autorizacao, tipo, expira_em, mensagem}` deste computador agora."""
    return _get(sessao, "/api/estacao/situacao", versao)


def instalacoes_pendentes(sessao, versao: str = "") -> list[str]:
    """Tokens de instalação para esta máquina (o portal entrega cada um uma vez)."""
    return list(_get(sessao, "/api/estacao/instalacoes", versao).get("tokens") or [])


def sair(sessao, versao: str = "") -> None:
    """A pessoa saiu da bandeja: avisa o portal e encerra a credencial local
    (ela fica como último dono do perfil)."""
    try:
        if esta_conectado():
            sessao.post(portal_da_conta() + "/api/estacao/sair", headers=cabecalhos(versao), timeout=15)
    except Exception:  # noqa: BLE001 — sair localmente não depende do portal responder
        LOGGER.warning("Não foi possível avisar o portal da saída", exc_info=True)
    finally:
        encerrar()
