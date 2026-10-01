"""
Certificado vigente por Cliente (decisão A1, revisão de 01/10/2026).

O inventário tem N arquivos por Documento: renovações, cópias, versões
antigas. O painel de Acompanhamento sempre mostrou UM item por Cliente — o
certificado que responde "este cliente está coberto?" —, mas o sino e o
e-mail percorriam todos os arquivos. Um cliente renovado aparecia "Ativo" no
painel e "venceu há 12 dias" no sino, por causa do arquivo antigo.

Aqui mora a regra única: para cada Documento fica o certificado com a maior
validade entre os legíveis e não vencidos; se nenhum valer, o de maior
validade entre os vencidos; por fim, qualquer um. Item sem Documento fica
como está (só o administrador os vê, e não há com quem agrupar).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

_ILEGIVEIS = ("erro", "fora_do_padrao")


def _documento(it: Dict[str, Any]) -> str:
    for k in ("documento_numero", "documento_digitos", "documento_formatado", "documento"):
        d = "".join(c for c in str(it.get(k) or "") if c.isdigit())
        if d:
            return d
    return ""


def _validade(it: Dict[str, Any]) -> Optional[datetime]:
    v = it.get("not_after") or it.get("vencimento_certificado")
    if not v:
        return None
    try:
        dt = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _peso(it: Dict[str, Any], agora: datetime) -> tuple:
    """Maior é melhor: válido > vencido > ilegível; depois a validade."""
    status = str(it.get("status") or "").lower()
    v = _validade(it)
    vencido = status in ("expirado", "vencido") or (v is not None and v < agora)
    if status in _ILEGIVEIS or v is None:
        classe = 0
    elif vencido:
        classe = 1
    else:
        classe = 2
    return (classe, v.timestamp() if v else float("-inf"))


def vigentes_por_documento(itens: Iterable[Dict[str, Any]], agora: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """Um certificado por Documento, o vigente; itens sem Documento passam
    inteiros. Preserva a ordem de primeira aparição de cada Documento.

    As CÓPIAS do vigente (mesmo fingerprint em outro arquivo) ficam: o sino
    conta "encontrado em N arquivos", e essa contagem é o que denuncia a
    duplicidade. O que sai são os OUTROS certificados do mesmo Documento —
    as versões antigas e os ilegíveis.
    """
    agora = agora or datetime.now(timezone.utc)
    por_doc: Dict[str, List[Dict[str, Any]]] = {}
    ordem: List[str] = []
    sem_doc: List[Dict[str, Any]] = []
    for it in itens:
        d = _documento(it)
        if not d:
            sem_doc.append(it)
            continue
        if d not in por_doc:
            ordem.append(d)
        por_doc.setdefault(d, []).append(it)

    saida: List[Dict[str, Any]] = []
    for d in ordem:
        lista = por_doc[d]
        melhor = max(lista, key=lambda it: _peso(it, agora))
        fp = str(melhor.get("fingerprint_sha256") or "").strip().lower()
        if fp:
            saida.extend(it for it in lista if str(it.get("fingerprint_sha256") or "").strip().lower() == fp)
        else:
            saida.append(melhor)
    return saida + sem_doc
