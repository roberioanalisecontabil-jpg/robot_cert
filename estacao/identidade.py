"""O `machine_id` desta estação, fixado pela chave da máquina (1.5.3).

Até a 1.5.2 o `machine_id` era recalculado a cada uso: o primeiro MAC em ordem
alfabética. Um adaptador novo (WSL, Hyper-V, VPN, placa trocada) passava à
frente, a máquina virava outra para o portal e ele respondia 403 "Chave da
máquina não confere" (TI-002, 20/11/2026: o `vEthernet (WSL)` 00:15:5d:… na
frente do 00:ff:fd:03:61:24).

A identidade é a chave da máquina (`chave_maquina`): o portal diz a que
`machine_id` ela está fixada (`POST /api/estacao/identidade`), e a resposta fica
em `%ProgramData%\\CertguardAnalise\\machine_id.txt`. O arquivo é só cache:

  portal conhece a chave   a resposta dele vence o arquivo
  portal diz 404 ou fora   vale o arquivo; sem arquivo, o MAC calculado, gravado

Quem grava: o instalador (`--preparar-chave`) e a tarefa SYSTEM. A bandeja só lê.
Um arquivo plantado por quem não é administrador não engana o portal (a chave
é que prova a máquina) e a próxima rodada da tarefa o sobrescreve.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from estacao import caminhos

logger = logging.getLogger("estacao.identidade")

ARQUIVO = "machine_id.txt"
_FORMATO = re.compile(r"[0-9a-f]{2}(:[0-9a-f]{2}){5}")


def caminho() -> Path:
    return caminhos.pasta_maquina() / ARQUIVO


def mac_calculado() -> str:
    """O cálculo de sempre: o primeiro MAC em ordem alfabética, sem o nulo. É o
    mesmo do Hardlyze (`DataCollector._get_mac_addresses()[0]`), e por isso o
    das máquinas já autorizadas antes da 1.5.3."""
    import psutil

    macs = set()
    try:
        for addrs in psutil.net_if_addrs().values():
            for addr in addrs:
                if addr.family == psutil.AF_LINK:
                    mac = addr.address.replace("-", ":").lower()
                    if mac and mac != "00:00:00:00:00:00":
                        macs.add(mac)
    except Exception:
        logger.exception("Erro ao obter MACs")
    return sorted(macs)[0] if macs else "unknown"


def _do_arquivo() -> str | None:
    try:
        texto = caminho().read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return None
    return texto if _FORMATO.fullmatch(texto) else None


def machine_id() -> str:
    return _do_arquivo() or mac_calculado()


def _gravar(mid: str) -> None:
    # Como a chave: temporário de nome aleatório numa subpasta restrita, depois
    # `os.replace` (a bandeja nunca lê pela metade) e a ACL final (Usuários só
    # leem). O SYSTEM não pode seguir um nome que a pessoa criou antes.
    from estacao import chave_maquina

    chave_maquina.gravar_restrito(caminho(), (mid + "\n").encode("utf-8"))


def _do_portal(http, chave: str) -> str | None:
    from estacao.tarefa import portal

    try:
        r = http.post(f"{portal()}/api/estacao/identidade", json={"chave": chave})
        if r.status_code != 200:
            if r.status_code != 404:
                logger.warning("Identidade: o portal respondeu %s.", r.status_code)
            return None
        mid = str(r.json().get("machine_id") or "").strip().lower()
    except Exception as e:
        logger.warning("Identidade: portal indisponível agora: %s", e)
        return None
    if not _FORMATO.fullmatch(mid):
        logger.warning("Identidade: resposta do portal fora do formato.")
        return None
    return mid


def fixar(http) -> str:
    """Pergunta ao portal e grava conforme o docstring do módulo. Devolve o
    `machine_id` em vigor; nunca levanta (falha vai ao log)."""
    try:
        from estacao import chave_maquina

        chave = chave_maquina.ler()
        do_portal = _do_portal(http, chave) if chave else None
        atual = _do_arquivo()
        escolhido = do_portal or atual or mac_calculado()
        if escolhido != atual:
            _gravar(escolhido)
            logger.info("Identidade: machine_id fixado em %s (antes: %s).", escolhido, atual or "nenhum")
        return escolhido
    except Exception:
        logger.exception("Identidade: não foi possível fixar o machine_id")
        return machine_id()
