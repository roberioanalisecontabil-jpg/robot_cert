import logging
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any

from app.settings_state import load_settings, load_colaborador_selecao, get_latest_snapshot

logger = logging.getLogger(__name__)

def get_active_alerts(user_email: str, user_role: str) -> List[Dict[str, Any]]:
    """
    Retorna a lista de alertas ativos (expiring ou expired) para exibição no sino do portal.
    - Admins: veem alertas de todos os certificados do sistema.
    - Users: veem alertas apenas dos certificados que selecionaram para acompanhar.
    """
    from app.main import _list_certificados_payload, _parse_iso_utc
    settings = load_settings()
    now = datetime.now(timezone.utc)
    thirty_days_from_now = now + timedelta(days=30)
    
    # 1. Carrega todos os certificados do sistema
    snap = get_latest_snapshot()
    payload = _list_certificados_payload(settings, snap, "auto")
    itens = payload.get("itens") or []
    
    # 2. Carrega seleção de documentos se não for administrador
    user_email_clean = (user_email or "").strip().lower()
    is_admin = (user_role or "").strip().lower() == "admin"
    
    selected_docs = []
    if not is_admin:
        selected_docs = load_colaborador_selecao(user_email_clean)
        # Limpa os documentos selecionados para conter apenas dígitos para comparação robusta
        selected_docs = ["".join(c for c in d if c.isdigit()) for d in selected_docs]
        
    alerts = []
    
    for it in itens:
        venc_iso = it.get("not_after")
        if not venc_iso:
            continue
            
        try:
            v_dt = _parse_iso_utc(venc_iso)
        except Exception:
            continue
            
        # Filtra por perfil: se for usuário regular, verifica se o documento do certificado está selecionado
        if not is_admin:
            doc_digitos = "".join(c for c in (it.get("documento_numero") or "") if c.isdigit())
            if not doc_digitos:
                doc_digitos = "".join(c for c in (it.get("documento_formatado") or "") if c.isdigit())
            if doc_digitos not in selected_docs:
                continue
                
        # Verifica se o certificado está vencido ou expirando
        dias = (v_dt.date() - now.date()).days
        tipo = None
        mensagem = ""
        
        if v_dt < now:
            tipo = "expired"
            mensagem = f"O certificado '{it.get('nome')}' está vencido!"
        elif 0 <= dias <= 30:
            tipo = "expiring"
            mensagem = f"O certificado '{it.get('nome')}' vence em {dias} dias!"
            
        if tipo:
            alerts.append({
                "fingerprint_sha256": it.get("fingerprint_sha256"),
                "nome": it.get("nome") or it.get("display_name"),
                "documento": it.get("documento_formatado") or it.get("documento_numero") or "Sem documento",
                "tipo": tipo,
                "vencimento": venc_iso,
                "dias_restantes": dias,
                "mensagem": mensagem
            })
            
    # Ordena: Vencidos primeiro, depois Expirando por menor quantidade de dias restantes
    alerts.sort(
        key=lambda x: (
            0 if x.get("tipo") == "expired" else 1,
            x.get("dias_restantes") if x.get("dias_restantes") is not None else 10**9
        )
    )
    
    return alerts
