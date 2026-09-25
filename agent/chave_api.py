"""
A X-API-Key compartilhada, guardada como a credencial de máquina — e não em
claro no `agent_config.json` (SECURITY_AUDIT #18, lote 7).

Até o agente 1.3.0 a chave ficava em `cert_robot_api_key` dentro do JSON, na
pasta do programa, legível por qualquer usuário da estação: quem a lesse ganhava
papel `agent` no portal. Ela existe para UM momento — provar posse no
provisionamento da credencial de máquina (`identidade_maquina.provisionar`) —
e para a queda de compatibilidade enquanto a credencial própria não existe.

Onde mora agora: `%ProgramData%\\Analise CertiDigital Agent\\chave_api.dat`,
cifrada com DPAPI de escopo MÁQUINA (só esta estação decifra) e com ACL só para
SYSTEM e Administradores (`identidade_maquina._aplicar_acl`). Mesmo maquinário
de `maquina.dat`, de propósito: dois cofres com regras diferentes divergiriam
num detalhe que só aparece na hora de decifrar.

Como entra: o instalador pede a chave numa página do assistente, grava-a num
arquivo temporário do administrador e chama `AnaliseCertiDigital_Agent.exe
--guardar-chave <arquivo>`; o agente cifra, restringe e apaga o arquivo. A
chave nunca passa pela linha de comando (tabela de processos) nem fica no JSON.

Compatibilidade: um `agent_config.json` antigo com `cert_robot_api_key` é
MIGRADO na primeira subida — a chave vai para o cofre e o JSON é reescrito sem
ela, com WARNING no log. Nada para de funcionar; o arquivo em claro é que
deixa de existir.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional

from agent import identidade_maquina

LOGGER = logging.getLogger(__name__)

ARQUIVO = "chave_api.dat"
CAMPO_LEGADO = "cert_robot_api_key"


def caminho() -> Path:
    """Ao lado de `maquina.dat`, pelas mesmas razões (ver `identidade_maquina.caminho`)."""
    return identidade_maquina.caminho().with_name(ARQUIVO)


def guardar(chave: str, base_url: str) -> Path:
    """Cifra, grava e restringe a ACL. Sem ACL não fica arquivo: apaga e levanta."""
    conteudo = json.dumps(
        {
            "chave": (chave or "").strip(),
            "base_url": (base_url or "").strip().rstrip("/"),
            "gravado_em": time.time(),
        },
        ensure_ascii=False,
    ).encode("utf-8")
    cifrado = identidade_maquina.proteger(conteudo)
    destino = caminho()
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_bytes(cifrado)
    try:
        identidade_maquina._aplicar_acl(destino)
    except Exception:
        with contextlib.suppress(OSError):
            destino.unlink()
        raise
    return destino


def ler() -> Optional[str]:
    """A chave guardada, ou None. Nunca levanta."""
    origem = caminho()
    try:
        if not origem.is_file():
            return None
        dados = json.loads(identidade_maquina.desproteger(origem.read_bytes()).decode("utf-8"))
        return str(dados.get("chave") or "").strip() or None
    except Exception:  # noqa: BLE001
        LOGGER.warning("Chave de API ilegível em %s.", origem)
        return None


def apagar() -> bool:
    origem = caminho()
    try:
        if origem.is_file():
            origem.unlink()
            return True
    except OSError:
        LOGGER.exception("Falha ao apagar a chave de API guardada")
    return False


def migrar_de_config(local_cfg: Dict[str, Any], arquivo_config: Optional[Path]) -> Optional[str]:
    """Tira a chave do JSON em claro e a põe no cofre. Devolve a chave.

    Só reescreve o JSON depois de o cofre confirmar a gravação: falhar no meio
    não pode deixar a estação sem chave em lugar nenhum.
    """
    chave = str(local_cfg.get(CAMPO_LEGADO) or "").strip()
    if not chave:
        return None
    try:
        guardar(chave, str(local_cfg.get("cert_robot_base_url") or ""))
    except Exception:  # noqa: BLE001
        LOGGER.warning(
            "Não foi possível guardar a chave de API no cofre local; ela continua "
            "no agent_config.json por enquanto.", exc_info=True,
        )
        return chave
    if arquivo_config is not None:
        try:
            atual = json.loads(Path(arquivo_config).read_text(encoding="utf-8"))
            if isinstance(atual, dict) and CAMPO_LEGADO in atual:
                atual.pop(CAMPO_LEGADO, None)
                Path(arquivo_config).write_text(
                    json.dumps(atual, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
                )
        except Exception:  # noqa: BLE001
            LOGGER.warning("Chave guardada no cofre, mas não deu para reescrever %s sem ela.",
                           arquivo_config, exc_info=True)
    LOGGER.warning(
        "Chave de API migrada do agent_config.json para o cofre local (%s). "
        "O arquivo em claro foi reescrito sem ela.", caminho(),
    )
    return chave


def resolver(local_cfg: Dict[str, Any], arquivo_config: Optional[Path]) -> str:
    """De onde vem a X-API-Key, nesta ordem: variável de ambiente do serviço,
    cofre local, e por último o JSON antigo — que é migrado ao ser lido."""
    do_ambiente = (os.getenv("CERT_ROBOT_API_KEY") or "").strip()
    if do_ambiente:
        return do_ambiente
    do_cofre = ler()
    if do_cofre:
        return do_cofre
    migrada = migrar_de_config(local_cfg or {}, arquivo_config)
    if migrada:
        return migrada
    return (os.getenv("API_KEY") or "").strip()
