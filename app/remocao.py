"""Remoção de certificados nas estações (Frente B).

Spec: docs/superpowers/specs/2026-11-13-carteira-certificados-remocao-uso-design.md,
seção "Frente B". As duas chaves de modo, ajustadas na Configuração (a regra
da carteira e a regra do "sem login"), e a decisão de quais certificados do
acervo saem de um perfil.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from functools import wraps
from typing import Any, Dict, List, Optional, Tuple

from app import cert_installer as ci
from app import computadores as comp
from app.auth import conta_ativa
from app.settings_state import load_settings

logger = logging.getLogger(__name__)

MODOS = ("desligado", "relatorio", "ligado")
PADRAO = "relatorio"


def _modo(valor: str) -> str:
    return valor if valor in MODOS else PADRAO


def modo_carteira() -> str:
    return _modo(load_settings().remocao_carteira_modo)


def modo_sem_login() -> str:
    return _modo(load_settings().remocao_sem_login_modo)


# ── Decisão do portal ────────────────────────────────────────────────────
#
# Remover de quem tem direito é a pior falha desta frente. Por isso toda
# leitura que falha vira `CarteiraIndisponivel` (quem chama não remove nada),
# e item sem documento no cofre nunca entra numa Decisao.

AVISO = timedelta(days=7)

_SAIDA = {
    "prazo": "prazo vencido",
    "acessorias": "saiu no Acessórias",
    "papel": "mudou de papel",
    "desativacao": "conta desativada",
}

_POR_SITUACAO = {
    "vinculo": "computador recusado ou desvinculado",
    "emprestimo": "empréstimo do computador vencido",
}


@dataclass
class Decisao:
    fingerprint: str
    documento: Optional[str]
    regra: str
    motivo: str
    # None = remover já; data futura = só aviso até lá.
    remover_em: Optional[datetime]


def _leitura(fn):
    """Qualquer erro de leitura sai como `CarteiraIndisponivel`, nunca como "nada a fazer"."""

    @wraps(fn)
    def envolta(*a, **k):
        try:
            return fn(*a, **k)
        except ci.CarteiraIndisponivel:
            raise
        except Exception as e:  # noqa: BLE001
            logger.exception("Remoção: falha de leitura em %s", fn.__name__)
            raise ci.CarteiraIndisponivel(str(e)) from e

    return envolta


def _cliente():
    client = ci._banco()
    if not client:
        raise ci.CarteiraIndisponivel("Banco não configurado")
    return client


@_leitura
def do_acervo(fingerprints: List[str]) -> Dict[str, Optional[str]]:
    """Fingerprint (minúsculo) -> documento, só os que estão no cofre.

    O mesmo certificado pode estar em várias linhas (uma por máquina que o
    varreu); fica o documento de qualquer uma que o tenha.
    """
    alvo = sorted({str(f).strip().lower() for f in fingerprints if str(f or "").strip()})
    if not alvo:
        return {}
    linhas = (_cliente().table("cert_pfx_store").select("fingerprint, documento")
              .in_("fingerprint", alvo).execute().data or [])
    saida: Dict[str, Optional[str]] = {}
    for r in linhas:
        fp = str(r.get("fingerprint") or "").lower()
        saida[fp] = saida.get(fp) or ci.so_digitos(r.get("documento")) or None
    return saida


def _recencia(v: Dict[str, Any]) -> datetime:
    datas = [comp._quando(v.get(c)) for c in ("decidido_em", "encerrado_em", "pedido_em")]
    return max([d for d in datas if d], default=datetime.min.replace(tzinfo=timezone.utc))


@_leitura
def situacao_do_vinculo(user_id: str, machine_id: str, agora: datetime) -> Tuple[str, Optional[datetime]]:
    """("carteira", None), ("vinculo", desde) ou ("emprestimo", desde).

    Calcula a vigência aqui em vez de `computadores._vigente`, que encerra o
    empréstimo vencido: este caminho só lê.
    """
    agora = comp._quando(agora)  # sem fuso conta como UTC
    vs = comp._vinculos(user_id=str(user_id), machine_id=comp.mac(machine_id))

    def vencido(v: Dict[str, Any]) -> bool:
        fim = comp._quando(v.get("expira_em"))
        return v.get("tipo") == comp.EMPRESTIMO and fim is not None and fim <= agora

    if not vs or any(v.get("estado") == comp.PENDENTE or (v.get("estado") == comp.ATIVO and not vencido(v))
                     for v in vs):
        return "carteira", None
    v = max(vs, key=_recencia)
    estado, motivo = v.get("estado"), str(v.get("motivo") or "")
    # Sem data no banco, conta de agora: o aviso se renova e nada sai antes do tempo.
    if estado == comp.RECUSADO:
        return "vinculo", comp._quando(v.get("decidido_em")) or comp._quando(v.get("encerrado_em")) or agora
    if estado == comp.ENCERRADO and motivo.startswith("Desvinculado por"):
        return "vinculo", comp._quando(v.get("encerrado_em")) or agora
    if (estado == comp.ENCERRADO and motivo == "Prazo do empréstimo terminou.") or (estado == comp.ATIVO and vencido(v)):
        return "emprestimo", comp._quando(v.get("expira_em")) or comp._quando(v.get("encerrado_em")) or agora
    return "carteira", None


@_leitura
def motivo_da_saida(user_id: str, documento: str) -> str:
    """A última saída do histórico para o par, em texto para a trilha."""
    linhas = (_cliente().table("carteira_historico").select("origem, feito_por_email, feito_em")
              .eq("user_id", str(user_id)).eq("documento", ci.so_digitos(documento))
              .eq("movimento", "saida").order("feito_em", desc=True).limit(1).execute().data or [])
    if not linhas:
        return "fora da carteira"
    origem, email = linhas[0].get("origem"), linhas[0].get("feito_por_email")
    if origem in ("manual", "bloqueio"):
        return f"retirado por {email}" if email else "retirado"
    return _SAIDA.get(origem, "fora da carteira")


def _todos(acervo: Dict[str, Optional[str]], regra: str, motivo: str,
           remover_em: Optional[datetime]) -> List[Decisao]:
    return [Decisao(fp, doc, regra, motivo, remover_em) for fp, doc in acervo.items() if doc]


@_leitura
def decidir_pessoa(user: Dict[str, Any], machine_id: str, fingerprints: List[str],
                   agora: datetime) -> List[Decisao]:
    acervo = {fp: doc for fp, doc in do_acervo(fingerprints).items() if doc}
    if not acervo:
        return []
    if not conta_ativa(user):
        return _todos(acervo, "desativada", "conta desativada", None)
    situacao, desde = situacao_do_vinculo(str(user["id"]), machine_id, agora)
    if situacao in _POR_SITUACAO:
        return _todos(acervo, situacao, _POR_SITUACAO[situacao], desde + AVISO)
    # `role` obrigatório: ausente viraria Operador e um Admin perderia tudo.
    alcance = ci.documentos_ao_alcance(str(user["id"]), user["role"])
    if alcance is None:
        return []
    return [Decisao(fp, doc, "carteira", motivo_da_saida(str(user["id"]), doc), None)
            for fp, doc in acervo.items() if doc not in alcance]


def decidir_sem_login(fingerprints: List[str]) -> List[Decisao]:
    return _todos(do_acervo(fingerprints), "sem_login", "perfil sem login na bandeja", None)


@_leitura
def vencendo(user_id: str, hoje: date) -> List[Dict[str, Any]]:
    """Liberações manuais com prazo que termina entre hoje e daqui a 3 dias."""
    linhas = (_cliente().table("carteira").select("documento, origem, valido_ate")
              .eq("user_id", str(user_id)).eq("origem", "manual").execute().data or [])
    saida = []
    for r in linhas:
        ate = ci._como_data(r.get("valido_ate"))
        if ate is not None and hoje <= ate <= hoje + timedelta(days=3):
            saida.append({"documento": r.get("documento"), "vence_em": ate})
    return saida
