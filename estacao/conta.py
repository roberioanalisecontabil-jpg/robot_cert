"""A conta deste portal nesta estação (ADR 0002), do lado da bandeja.

Veio de `core/conta_certificados.py` do Hardlyze. O segredo do dispositivo vive
em `%LOCALAPPDATA%\\CertguardAnalise\\conta.dat`, cifrado com DPAPI no escopo da
pessoa, junto do endereço do portal que o emitiu. A senha só existe dentro de
`registrar`. As chamadas levam o segredo em `X-Device-Secret`, e só nas rotas
da estação (ADR 0003): o dispositivo não abre sessão do portal.

── Transição ─────────────────────────────────────────────────────────────

`migrar_do_hardlyze` lê uma vez o `certificados.dat` que a bandeja do Hardlyze
guardava, grava a conta aqui e apaga o original (adendo de 14/10/2026 ao ADR
0003). Quem já estava logado não precisa entrar de novo.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

from estacao import caminhos
from estacao.dpapi import SemCofreLocal, desproteger, proteger

LOGGER = logging.getLogger(__name__)

ARQUIVO = "conta.dat"
PORTAL_PADRAO = "https://certificado.analisegroup.cnt.br"

_ENTROPIA = b"certguard-analise-conta-v1"
# A do Hardlyze: `core/identidade.py` de lá cifrava o certificados.dat com ela.
_ENTROPIA_HARDLYZE = b"invent-agent-dispositivo-v1"


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
    destino.write_bytes(proteger(conteudo, _ENTROPIA))
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
    return _ler_de(caminho(), _ENTROPIA)


def apagar() -> bool:
    try:
        if caminho().is_file():
            caminho().unlink()
            return True
    except OSError:
        LOGGER.exception("Falha ao apagar a conta do portal")
    return False


def migrar_do_hardlyze() -> bool:
    """Traz a conta da bandeja do Hardlyze, uma vez. True se trouxe.

    Já havendo conta aqui, não mexe em nada. O original só é apagado depois de
    a cópia ler de volta igual; ilegível, fica onde está e a pessoa entra de novo.
    """
    if caminho().is_file():
        return False
    origem = caminhos.conta_hardlyze()
    antiga = _ler_de(origem, _ENTROPIA_HARDLYZE)
    if not antiga:
        return False
    _gravar(antiga)
    if (ler() or {}).get("segredo") != antiga["segredo"]:
        apagar()
        LOGGER.error("A conta copiada do Hardlyze não confere; mantido o original em %s.", origem)
        return False
    try:
        origem.unlink()
    except OSError:
        LOGGER.warning("Conta copiada, mas o original em %s não pôde ser apagado.", origem)
    LOGGER.info("Conta do portal trazida do Hardlyze (%s).", antiga.get("email") or "sem e-mail")
    return True


def esta_conectado() -> bool:
    return ler() is not None


def portal_da_conta() -> str:
    g = ler()
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
    if r.status_code != 200:
        raise RuntimeError(_detalhe(r) or f"O portal de certificados recusou o login ({r.status_code}).")
    dados = r.json()
    guardar(dados["segredo"], base, dados.get("email") or email, dados.get("machine_id") or machine_id)
    return {"email": dados.get("email"), "autorizacao": dados.get("autorizacao"), "mensagem": dados.get("mensagem")}


def _get(sessao, rota: str, versao: str) -> dict[str, Any]:
    r = sessao.get(portal_da_conta() + rota, headers=cabecalhos(versao), timeout=20)
    if r.status_code == 401:
        # O portal derrubou esta sessão: a credencial não volta a valer.
        apagar()
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
    """A pessoa saiu da bandeja: avisa o portal e apaga a credencial local."""
    try:
        if esta_conectado():
            sessao.post(portal_da_conta() + "/api/estacao/sair", headers=cabecalhos(versao), timeout=15)
    except Exception:  # noqa: BLE001 — sair localmente não depende do portal responder
        LOGGER.warning("Não foi possível avisar o portal da saída", exc_info=True)
    finally:
        apagar()
