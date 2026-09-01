"""
Credencial de MÁQUINA: o agente do ANALISESRV deixa a X-API-Key compartilhada.

Irmã de `app/agent_devices.py` — aquela é a credencial da PESSOA nesta máquina
(dormente, porque o serviço não a alcança); esta é a credencial da MÁQUINA EM
SI, que o serviço LocalSystem alcança porque mora em ProgramData cifrada com
DPAPI de escopo máquina. É a metade que faltava, anunciada na nota dormente:
"uma credencial de MÁQUINA em ProgramData, que o serviço alcance, substituindo
o X-API-Key". O desenho é UM só para os dois portais — o INVENT aplicou o
mesmo em 01/09/2026 — e está em `identidade-de-maquina-desenho.md`.

── Como o segredo nasce e viaja ──────────────────────────────────────────

Aqui não há fluxo de aprovação (é UM consumidor conhecido): o serviço, na
primeira subida sem credencial, chama `POST /api/agent/maquinas/provisionar`
autenticado pela X-API-Key que já o autentica hoje. A emissão é única por
`machine_id` — linha existente, ATÉ REVOGADA, recusa. Se o provisionamento
pudesse recriar o segredo, revogar não revogaria nada, porque quem tem a
X-API-Key provisiona. O caminho de volta é um admin reemitir (apagar a linha).

O texto claro existe uma única vez, na resposta do provisionamento. O banco
guarda só o hash.

── O risco assumido da transição ─────────────────────────────────────────

Enquanto a X-API-Key for aceita, quem a tiver pode provisionar um machine_id
antes da máquina verdadeira. Com um consumidor só e o seeding na primeira
subida do serviço, a janela é a instalação — e o sintoma aparece: o ANALISESRV
seguiria autenticando pelo legado (WARNING no log) com linha emitida aqui. O
compromisso acaba junto com a X-API-Key.

── Por que sha256, e não bcrypt ──────────────────────────────────────────

As mesmas duas razões documentadas em `agent_devices` (e a segunda não é
preferência): 32 bytes de `token_urlsafe` não têm palpite a encarecer, e o
hash precisa ser DETERMINÍSTICO porque a autenticação acha a linha por
igualdade a cada requisição.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
from typing import Any, Dict, List, Optional

# O critério de "vivo" e o formato do carimbo são UM só, os de agent_devices —
# divergir os dois faria a mesma máquina parecer viva numa tela e parada na
# outra.
from app.agent_devices import SemBanco, _agora, _exigir_banco, esta_vivo

logger = logging.getLogger(__name__)

TABELA = "machine_credentials"

BYTES_DO_SEGREDO = 32

# Diz ao agente que o 401 é da CREDENCIAL, e não da operação — a estação
# descarta o segredo local e cai na X-API-Key, em vez de repetir um valor morto
# para sempre. Protocolo portado do INVENT (`X-Credencial-Invalida` em
# `app/core/security.py` de lá); um cabeçalho, e não o texto do `detail`,
# porque casar string atravessa a fronteira de rede e quebra em silêncio no
# dia em que alguém melhorar a mensagem.
CABECALHO_CREDENCIAL_INVALIDA = "X-Credencial-Invalida"

__all__ = [
    "JaProvisionada",
    "SemBanco",
    "SemTabela",
    "autenticar",
    "gerar_segredo",
    "listar",
    "provisionar",
    "reemitir",
    "revogar",
]


class SemTabela(RuntimeError):
    """A migration 20260901190000 ainda não rodou."""


class JaProvisionada(RuntimeError):
    """Esta máquina já tem (ou teve) credencial; reemitir é ato de admin."""


def _hash(segredo: str) -> str:
    return hashlib.sha256((segredo or "").strip().encode("utf-8")).hexdigest()


def gerar_segredo() -> str:
    return secrets.token_urlsafe(BYTES_DO_SEGREDO)


def _e_tabela_ausente(erro: Exception) -> bool:
    texto = str(erro).lower()
    return "machine_credentials" in texto and (
        "does not exist" in texto or "not find the table" in texto or "pgrst205" in texto
    )


def _sem_segredo(linha: Dict[str, Any]) -> Dict[str, Any]:
    """A linha sem o hash — mesma guarda de `agent_devices._sem_segredo`."""
    return {k: v for k, v in linha.items() if k != "segredo_hash"}


def provisionar(machine_id: str, versao: Optional[str] = None) -> str:
    """
    Emite a credencial desta máquina — uma vez na vida dela.

    Devolve o segredo em claro; é a ÚNICA vez que ele existe fora da estação.
    Levanta `JaProvisionada` quando há linha (até revogada): a emissão não pode
    reabrir o que uma revogação fechou, senão revogar não significa nada para
    quem ainda tem a X-API-Key.
    """
    sb = _exigir_banco()
    mid = (machine_id or "").strip().lower()
    if not mid:
        raise ValueError("machine_id obrigatório")

    try:
        existente = (
            sb.table(TABELA).select("id").eq("machine_id", mid).limit(1).execute()
        ).data
    except SemBanco:
        raise
    except Exception as e:  # noqa: BLE001
        if _e_tabela_ausente(e):
            raise SemTabela("Rode a migration 20260901190000_credencial_de_maquina.sql.") from e
        raise
    if existente:
        raise JaProvisionada(
            "Esta máquina já recebeu credencial. Peça a um admin para reemitir."
        )

    segredo = gerar_segredo()
    linha: Dict[str, Any] = {
        "machine_id": mid,
        "segredo_hash": _hash(segredo),
        "revogado_em": None,
        "criado_em": _agora().isoformat(),
    }
    if (versao or "").strip():
        linha["versao"] = versao.strip()[:40]
    # A corrida de dois provisionamentos simultâneos morre no índice único do
    # banco; o segundo chamador recebe o erro e fica sem segredo — que é o
    # comportamento certo, porque o primeiro já levou o único texto claro.
    sb.table(TABELA).insert(linha).execute()
    logger.info("Credencial de máquina emitida para %s.", mid)
    return segredo


def autenticar(segredo: str) -> Optional[Dict[str, Any]]:
    """
    Devolve a máquina dona deste segredo, ou None. Carimba `visto_em`.

    Mesmo contrato de `agent_devices.autenticar`: carimbo e autenticação no
    mesmo ato, para `visto_em` não conseguir afirmar vida que não houve.
    """
    if not (segredo or "").strip():
        return None
    sb = _exigir_banco()
    alvo = _hash(segredo)
    try:
        r = sb.table(TABELA).select("*").eq("segredo_hash", alvo).limit(1).execute()
    except SemBanco:
        raise
    except Exception as e:  # noqa: BLE001
        if _e_tabela_ausente(e):
            raise SemTabela("Rode a migration 20260901190000_credencial_de_maquina.sql.") from e
        raise
    linhas = r.data or []
    if not linhas:
        return None
    linha = linhas[0]
    if not hmac.compare_digest(str(linha.get("segredo_hash") or ""), alvo):
        return None
    if linha.get("revogado_em"):
        return None

    carimbo = {"visto_em": _agora().isoformat()}
    try:
        sb.table(TABELA).update(carimbo).eq("id", linha["id"]).execute()
        linha.update(carimbo)
    except Exception:  # noqa: BLE001
        # Falhar em carimbar não pode negar acesso a quem apresentou segredo
        # válido — mesma regra de agent_devices.
        logger.exception("Falha ao carimbar visto_em da credencial %s", linha.get("id"))
    return linha


def listar() -> List[Dict[str, Any]]:
    """
    As credenciais, sem hash, com `vivo` calculado.

    Também é o mapa da migração: o ANALISESRV aparecer aqui com `visto_em`
    fresco — e o WARNING de X-API-Key sumir do log — é o sinal de que o legado
    pode ser desligado.
    """
    sb = _exigir_banco()
    try:
        linhas = (sb.table(TABELA).select("*").execute()).data or []
    except SemBanco:
        raise
    except Exception as e:  # noqa: BLE001
        if _e_tabela_ausente(e):
            raise SemTabela("Rode a migration 20260901190000_credencial_de_maquina.sql.") from e
        raise
    agora = _agora()
    saida = []
    for linha in linhas:
        item = _sem_segredo(linha)
        item["vivo"] = esta_vivo(linha, agora)
        saida.append(item)
    saida.sort(key=lambda d: str(d.get("criado_em") or ""), reverse=True)
    return saida


def revogar(machine_id: str) -> bool:
    """
    Invalida o segredo desta máquina. Idempotente; preserva a linha.

    A linha preservada é a própria garantia: enquanto ela existir, o
    provisionamento NÃO emite segredo novo para este machine_id. Devolve False
    quando não há linha.
    """
    sb = _exigir_banco()
    mid = (machine_id or "").strip().lower()
    if not mid:
        return False
    linhas = (
        sb.table(TABELA).select("*").eq("machine_id", mid).limit(1).execute()
    ).data or []
    if not linhas:
        return False
    if linhas[0].get("revogado_em"):
        return True
    sb.table(TABELA).update({"revogado_em": _agora().isoformat()}).eq(
        "id", linhas[0]["id"]
    ).execute()
    return True


def reemitir(machine_id: str) -> bool:
    """
    Apaga a linha para a máquina obter credencial NOVA no próximo provisionar.

    É o único caminho de volta depois de uma revogação (ou de uma emissão
    perdida — o serviço recebeu o segredo e não conseguiu guardar). Ato de
    admin de propósito: é a decisão que o provisionamento não pode tomar
    sozinho. Devolve False quando não havia linha.
    """
    sb = _exigir_banco()
    mid = (machine_id or "").strip().lower()
    if not mid:
        return False
    linhas = (
        sb.table(TABELA).select("id").eq("machine_id", mid).limit(1).execute()
    ).data or []
    if not linhas:
        return False
    sb.table(TABELA).delete().eq("id", linhas[0]["id"]).execute()
    logger.info("Credencial de máquina de %s descartada; a próxima subida reemite.", mid)
    return True
