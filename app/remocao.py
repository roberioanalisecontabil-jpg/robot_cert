"""Remoção de certificados nas estações (Frente B).

Spec: docs/superpowers/specs/2026-11-13-carteira-certificados-remocao-uso-design.md,
seção "Frente B". As duas chaves de modo, ajustadas na Configuração (a regra
da carteira e a regra do "sem login"), e a decisão de quais certificados do
acervo saem de um perfil.
"""

from __future__ import annotations

import logging
import math
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


def modo_fora_da_pasta() -> str:
    return _modo(load_settings().remocao_fora_da_pasta_modo)


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
def motivos_da_saida(user_id: str, documentos: List[str]) -> Dict[str, str]:
    """A última saída do histórico de cada documento, em texto para a trilha.

    Uma consulta só para a lista inteira (antes era uma por documento)."""
    por_digitos = {ci.so_digitos(d): d for d in documentos}
    ultima: Dict[str, Dict[str, Any]] = {}
    if por_digitos:
        linhas = (_cliente().table("carteira_historico")
                  .select("documento, origem, feito_por_email, feito_em")
                  .eq("user_id", str(user_id)).in_("documento", list(por_digitos))
                  .eq("movimento", "saida").order("feito_em", desc=True).execute().data or [])
        for linha in linhas:  # mais nova primeiro: fica a primeira de cada documento
            ultima.setdefault(str(linha.get("documento")), linha)
    return {doc: _texto_da_saida(ultima.get(dig)) for dig, doc in por_digitos.items()}


def _texto_da_saida(linha: Optional[Dict[str, Any]]) -> str:
    if not linha:
        return "fora da carteira"
    origem, email = linha.get("origem"), linha.get("feito_por_email")
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
    # `role` obrigatório: ausente ou vazio viraria Operador e um Admin perderia tudo.
    if not str(user.get("role") or "").strip():
        raise ci.CarteiraIndisponivel("conta sem papel definido")
    alcance = ci.documentos_ao_alcance(str(user["id"]), user["role"])
    if alcance is None:
        return []
    fora = {fp: doc for fp, doc in acervo.items() if doc not in alcance}
    motivos = motivos_da_saida(str(user["id"]), sorted(set(fora.values())))
    return [Decisao(fp, doc, "carteira", motivos[doc], None) for fp, doc in fora.items()]


def decidir_sem_login(fingerprints: List[str]) -> List[Decisao]:
    return _todos(do_acervo(fingerprints), "sem_login", "perfil sem login na bandeja", None)


@_leitura
def decidir_fora_da_pasta(fingerprints: List[str]) -> List[Decisao]:
    """Certificados do escritório que saíram do cofre (vencidos ou apagados da
    pasta) e seguem instalados. O que voltou ao cofre não entra; o que nunca
    esteve no cofre (um e-CPF pessoal) não está em `cert_acervo_saida`."""
    alvo = sorted({str(f).strip().lower() for f in fingerprints if str(f or "").strip()})
    if not alvo:
        return []
    linhas = (_cliente().table("cert_acervo_saida").select("fingerprint, documento, motivo")
              .in_("fingerprint", alvo).execute().data or [])
    no_cofre = do_acervo([str(l.get("fingerprint") or "") for l in linhas])
    return [Decisao(str(l["fingerprint"]).lower(), ci.so_digitos(l.get("documento")) or None, "fora_da_pasta",
                    str(l.get("motivo") or "saiu da pasta"), None)
            for l in linhas if str(l.get("fingerprint") or "").lower() not in no_cofre]


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


# ── Estado por estação ───────────────────────────────────────────────────
#
# Uma linha por (máquina, usuário Windows, certificado). Escrita que falha
# propaga: nunca se manda remover o que não ficou registrado.

_FIM = ("removido", "falhou")
_PENDENTE = ("aviso", "remover")


def _dias(falta: timedelta) -> int:
    return max(1, math.ceil(falta / timedelta(days=1)))


def aplicar(machine_id: str, usuario_windows: str, user_id: Optional[str],
            decisoes: List[Decisao], modo: str, agora: datetime,
            modos: Optional[Dict[str, str]] = None) -> Dict[str, List[Dict[str, Any]]]:
    """`modo` vale para as regras sem modo próprio em `modos` (regra -> modo)."""
    saida: Dict[str, List[Dict[str, Any]]] = {"remover": [], "avisos": []}
    agora = comp._quando(agora)  # sem fuso conta como UTC
    mid = comp.mac(machine_id)
    client = _cliente()
    tabela = "remocao_estacao"
    modos = modos or {}

    def modo_de(d: Decisao) -> str:
        return modos.get(d.regra, modo)

    decisoes = [d for d in decisoes if modo_de(d) in ("relatorio", "ligado")]
    if modo not in ("relatorio", "ligado") and not decisoes:
        # Desligado zera o relógio pendente: ao religar, o aviso prometido volta inteiro.
        (client.table(tabela).update({"estado": "removeria", "aviso_desde": None,
                                      "atualizado_em": agora.isoformat()})
         .eq("machine_id", mid).eq("usuario_windows", usuario_windows)
         .in_("estado", list(_PENDENTE)).execute())
        return saida
    # shortcut: lê e grava sem trava; duas chamadas simultâneas podem voltar um
    # `removido` recém-gravado para `remover` (se corrige no ciclo seguinte).
    # Trocar por transação/trava de linha se duas bandejas por perfil virarem realidade.
    existentes = {str(r.get("fingerprint") or "").strip().lower(): r
                  for r in (client.table(tabela).select("*").eq("machine_id", mid)
                            .eq("usuario_windows", usuario_windows).execute().data or [])}
    por_fp = {d.fingerprint.strip().lower(): d for d in decisoes}
    linhas = []
    for fp, d in por_fp.items():
        estado, aviso_desde = "removeria", None
        if modo_de(d) == "ligado":
            antiga = existentes.get(fp) or {}
            # Só `ligado` grava aviso_desde: semanas de relatório não contam como aviso.
            # Só herda de um aviso em curso: o reinstalado após removido/falhou ganha aviso novo.
            herda = antiga.get("regra") == d.regra and antiga.get("estado") in _PENDENTE
            aviso_desde = (herda and comp._quando(antiga.get("aviso_desde"))) or agora
            remover_em = aviso_desde + AVISO if d.regra in ("sem_login", "fora_da_pasta") else d.remover_em
            item = {"fingerprint": fp, "documento": d.documento, "motivo": d.motivo}
            if remover_em is not None and remover_em > agora:
                estado = "aviso"
                saida["avisos"].append({**item, "dias": _dias(remover_em - agora)})
            else:
                estado = "remover"
                saida["remover"].append(item)
        linhas.append({
            "machine_id": mid, "usuario_windows": usuario_windows, "user_id": user_id,
            "fingerprint": fp, "documento": d.documento, "regra": d.regra, "motivo": d.motivo,
            "estado": estado, "aviso_desde": aviso_desde.isoformat() if aviso_desde else None,
            "detalhe": "", "atualizado_em": agora.isoformat(),
        })
    if linhas:
        client.table(tabela).upsert(linhas, on_conflict="machine_id,usuario_windows,fingerprint").execute()
    # A situação se resolveu: o aviso some. O que já foi removido ou falhou fica.
    sobras = [r.get("fingerprint") for fp, r in existentes.items()
              if fp not in por_fp and r.get("estado") not in _FIM]
    if sobras:
        (client.table(tabela).delete().eq("machine_id", mid).eq("usuario_windows", usuario_windows)
         .in_("fingerprint", sobras).execute())
    return saida


def registrar_resultado(machine_id: str, usuario_windows: str, user_id: Optional[str],
                        user_email: Optional[str], resultados: List[Dict[str, Any]]) -> None:
    """O que a bandeja fez. Só vale para linha que estava em `remover`."""
    mid = comp.mac(machine_id)
    client = _cliente()
    agora = datetime.now(timezone.utc).isoformat()
    for r in resultados:
        fp = str(r.get("fingerprint") or "").strip().lower()
        if not fp:
            continue
        ok = bool(r.get("ok"))
        mudou = (client.table("remocao_estacao")
                 .update({"estado": "removido" if ok else "falhou",
                          "detalhe": "" if ok else str(r.get("erro") or ""), "atualizado_em": agora})
                 .eq("machine_id", mid).eq("usuario_windows", usuario_windows)
                 .eq("fingerprint", fp).eq("estado", "remover").execute().data or [])
        if ok and user_id and mudou:
            ci.log_event("REMOVIDO", user_id, user_email, fingerprint=fp, target_machine=mid,
                         status="OK", detail=mudou[0].get("motivo"))
