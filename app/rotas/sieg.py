"""SIEG (07/10/2026) — Frente 3, leva 3 (09/10/2026).

Saiu de `app/main.py` sem mudar comportamento. Regras em `app/sieg.py`,
desenho em docs/modal-detalhes-e-sieg.md.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional, Tuple

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi import Path as PathParam
from pydantic import BaseModel, Field

from app import auth, sieg, texto
from app.alcance import _documentos_ao_alcance, _no_alcance, _no_cofre
from app.sessao import _limitar, require_admin, require_auth
from app.settings_state import GravacaoNaoPersistida, get_latest_snapshot, load_settings, save_settings
from app.sieg_api import SiegErro, so_digitos
from app.smtp_service import encrypt_password

logger = logging.getLogger("app.main")
router = APIRouter()


# ──────────────────────────────────────────────────────────────────────────
# SIEG (07/10/2026) — docs/modal-detalhes-e-sieg.md, regras em app/sieg.py
#
# Ligar: quem tem o certificado no alcance (a regra da instalação, a mesma
# da rota de detalhes). Configurar, testar, sincronizar, reconciliar e a
# aba do Instalador: administrador.
# ──────────────────────────────────────────────────────────────────────────

FP_PARAM = PathParam(..., min_length=64, max_length=64, pattern=r"^[0-9a-fA-F]{64}$")


def _certificado_no_alcance(fp: str, token: auth.TokenData, exigir_carteira: bool = True) -> Tuple[dict, dict]:
    """(item do inventário, snapshot) — 404 se inexistente ou, quando
    `exigir_carteira`, fora da carteira. Ler a situação no SIEG é de todos
    (08/10/2026); ligar o interruptor segue a carteira, como instalar."""
    snap = get_latest_snapshot() or {}
    fp = fp.lower()
    item = next((it for it in (snap.get("items") or []) if (it.get("fingerprint_sha256") or "").lower() == fp), None)
    if item is None or (exigir_carteira and not _no_alcance(item, _documentos_ao_alcance(token))):
        raise HTTPException(status_code=404, detail="Certificado não encontrado.")
    return item, snap


def _quem(token: auth.TokenData) -> str:
    return (token.email or "").strip().lower() or "?"


def _sieg_payload(item: dict, settings) -> dict:
    fp = item["fingerprint_sha256"].lower()
    atual = sieg.estado(fp)
    motivo = None if atual and atual["ligado"] else sieg.motivo_para_nao_ligar(item, _no_cofre(fp), settings)
    return {
        "estado": atual,
        "motivo": motivo,
        "motivo_texto": sieg.MOTIVOS.get(motivo) if motivo else None,
        "configurado": sieg.configurado(settings),
        "trilha": sieg.trilha(fp, limite=10) if atual else [],
    }


@router.get("/api/sieg/certificado/{fingerprint}", dependencies=[Depends(require_auth)])
def sieg_do_certificado(fingerprint: str = FP_PARAM, token: auth.TokenData = Depends(require_auth)) -> dict:
    item, _snap = _certificado_no_alcance(fingerprint, token, exigir_carteira=False)
    return {**_sieg_payload(item, load_settings()), "na_carteira": _no_alcance(item, _documentos_ao_alcance(token))}


@router.post("/api/sieg/certificado/{fingerprint}/incluir", status_code=202,
          dependencies=[Depends(require_auth), Depends(_limitar("sieg-incluir", 60, 3600))])
def sieg_incluir(background: BackgroundTasks, fingerprint: str = FP_PARAM,
                 token: auth.TokenData = Depends(require_auth)) -> dict:
    """Liga o interruptor: grava "incluindo" e faz a chamada em segundo plano."""
    item, snap = _certificado_no_alcance(fingerprint, token)
    settings = load_settings()
    atual = sieg.estado(item["fingerprint_sha256"])
    if atual and atual["estado"] in (sieg.INCLUINDO, sieg.NO_SIEG, sieg.SUBSTITUIDO):
        raise HTTPException(status_code=409, detail="Este certificado já foi ligado ao SIEG.")
    motivo = sieg.motivo_para_nao_ligar(item, _no_cofre(item["fingerprint_sha256"].lower()), settings)
    if motivo:
        raise HTTPException(status_code=409, detail=sieg.MOTIVOS[motivo])
    try:
        sieg.solicitar(item, _quem(token))
    except sieg.SiegIndisponivel:
        raise HTTPException(status_code=503, detail="Não foi possível gravar o pedido. Tente de novo.")
    background.add_task(sieg.executar, item, settings, _quem(token), machine_id=snap.get("machine_id"))
    return _sieg_payload(item, settings)


@router.post("/api/sieg/certificado/{fingerprint}/reconciliar", dependencies=[Depends(require_admin)])
def sieg_reconciliar(fingerprint: str = FP_PARAM, token: auth.TokenData = Depends(require_auth)) -> dict:
    item, _snap = _certificado_no_alcance(fingerprint, token)
    settings = load_settings()
    try:
        sieg.reconciliar(item["fingerprint_sha256"].lower(), settings, _quem(token))
    except LookupError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except SiegErro as e:
        raise HTTPException(status_code=502, detail=f"Não foi possível consultar o SIEG: {e}")
    return _sieg_payload(item, settings)


@router.get("/api/sieg/inclusoes", dependencies=[Depends(require_admin)])
def sieg_inclusoes(estado: Optional[str] = Query(None, max_length=20),
                   limite: int = Query(500, ge=1, le=2000)) -> dict:
    """Aba SIEG do Instalador: um certificado por linha, com a última tentativa."""
    linhas = sorted(sieg.estados(None).values(), key=lambda l: str(l.get("solicitado_em") or ""), reverse=True)
    resumo: Dict[str, int] = {}
    for l in linhas:
        resumo[l["estado"]] = resumo.get(l["estado"], 0) + 1
    if estado:
        linhas = [l for l in linhas if l["estado"] == estado]
    return {"itens": linhas[:limite], "total": len(linhas), "resumo": resumo,
            "rotulos": sieg.ROTULOS, "configurado": sieg.configurado(load_settings())}


@router.get("/api/sieg/trilha", dependencies=[Depends(require_admin)])
def sieg_trilha_rota(fingerprint: Optional[str] = Query(None, min_length=64, max_length=64),
                     limite: int = Query(200, ge=1, le=1000)) -> dict:
    return {"itens": sieg.trilha(fingerprint, limite=limite)}


class SiegConfigBody(BaseModel):
    client_id: Optional[str] = Field(None, max_length=200)
    secret_key: Optional[str] = Field(None, max_length=1024)  # vazio/None = mantém
    api_key: Optional[str] = Field(None, max_length=1024)     # vazio/None = mantém
    padroes: Optional[Dict[str, Any]] = None


def _sieg_config_dict(s) -> dict:
    return {
        "client_id": s.sieg_client_id,
        "secret_key_set": bool(s.sieg_secret_key_encrypted),
        "api_key_set": bool(s.sieg_api_key_encrypted),
        "padroes": sieg.padroes(s),
        "configurado": sieg.configurado(s),
    }


@router.get("/api/sieg/configuracao", dependencies=[Depends(require_admin)])
def sieg_config_get() -> dict:
    return _sieg_config_dict(load_settings())


@router.put("/api/sieg/configuracao", dependencies=[Depends(require_admin)])
def sieg_config_put(body: SiegConfigBody) -> dict:
    from app.sieg_api import CAMPOS_CONSULTA, PADROES

    atual = load_settings()
    if body.client_id is not None:
        atual.sieg_client_id = body.client_id.strip()
    try:
        if body.secret_key and body.secret_key.strip():
            atual.sieg_secret_key_encrypted = encrypt_password(body.secret_key.strip())
        if body.api_key and body.api_key.strip():
            atual.sieg_api_key_encrypted = encrypt_password(body.api_key.strip())
    except Exception:
        raise HTTPException(status_code=500, detail="Erro ao cifrar as credenciais do SIEG.")
    if body.padroes is not None:
        limpos: Dict[str, Any] = {}
        for k, v in body.padroes.items():
            if k not in PADROES:
                continue
            if k in CAMPOS_CONSULTA:
                limpos[k] = bool(v)
            elif k == "DiasRetroativos":
                try:
                    limpos[k] = max(0, min(int(v or 0), 365))
                except (TypeError, ValueError):
                    raise HTTPException(status_code=422, detail="Dias retroativos deve ser um número de 0 a 365.")
            elif k == "UfCertificado":
                uf = so_digitos(v)[:2]
                if len(uf) != 2:
                    raise HTTPException(status_code=422, detail="UF do certificado: use o código IBGE de 2 dígitos (27 = AL).")
                limpos[k] = uf
            else:
                limpos[k] = str(v or "").strip()[:40]
        atual.sieg_padroes = json.dumps(limpos, ensure_ascii=False)
    try:
        save_settings(atual, exigir_banco=True)
    except GravacaoNaoPersistida:
        raise HTTPException(status_code=503, detail="Não foi possível gravar a configuração do SIEG. Veja o log do servidor.")
    return _sieg_config_dict(atual)


@router.post("/api/sieg/testar", dependencies=[Depends(require_admin), Depends(_limitar("sieg-testar", 10, 3600))])
def sieg_testar() -> dict:
    try:
        n = sieg.cliente(load_settings()).testar()
    except SiegErro as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True, "message": f"Conectado ao SIEG. A primeira página da listagem trouxe {texto.plural(n, 'cadastro')}."}


@router.post("/api/sieg/sincronizar", dependencies=[Depends(require_admin), Depends(_limitar("sieg-sincronizar", 6, 3600))])
def sieg_sincronizar(token: auth.TokenData = Depends(require_auth)) -> dict:
    snap = get_latest_snapshot() or {}
    try:
        r = sieg.sincronizar(snap.get("items") or [], load_settings(), _quem(token))
    except SiegErro as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {**r, "message": (f"{texto.plural(r['clientes_no_sieg'], 'cliente')} no SIEG; "
                             f"{texto.plural(r['marcados'], 'certificado marcado', 'certificados marcados')} agora.")}
