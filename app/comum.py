"""Utilidades das rotas — Frente 3, leva 4 (09/10/2026).

Saíram de `app/main.py` sem mudar comportamento, porque mais de um router
usa: leitura de planilha com teto (lote 5 da auditoria: o que não tem teto
derruba o portal inteiro, que roda num worker só), a mensagem de erro que
manda ao log, e a máscara de CNPJ/CPF.
"""

from __future__ import annotations

import unicodedata
from typing import Any, List

from fastapi import HTTPException, Request

from app import alertas_config, cert_installer, correio, email_modelo, graph_mail
from app.cert_scanner import formatar_cnpj_cpf
from app.settings_state import PortalSettings, banco_configurado


def _norm_header(v: str) -> str:
    s = unicodedata.normalize("NFD", str(v or "").strip().lower())
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
    return s


LIMITE_UPLOAD_BYTES = 5 * 1024 * 1024


MAX_LINHAS_IMPORT = 2000


ERRO_UPLOAD_GRANDE = f"Arquivo muito grande (limite de {LIMITE_UPLOAD_BYTES // (1024 * 1024)} MB)."


ERRO_LINHAS_DEMAIS = f"Planilha com mais de {MAX_LINHAS_IMPORT} linhas. Divida o arquivo."


async def _ler_upload_limitado(request: Request, file: Any) -> bytes:
    """Lê o arquivo enviado sem receber mais do que o teto (achado #11).

    Antes: `await file.read()` bufferizava o corpo inteiro (o Starlette manda
    para disco) e só DEPOIS o tamanho era conferido — um POST de 2 GB era
    recebido até o fim para responder 413. Aqui a recusa vem em dois tempos:
    pelo `Content-Length` declarado, antes de ler qualquer byte; e de novo
    durante a leitura, porque o cabeçalho é declaração do cliente.
    """
    try:
        declarado = int(request.headers.get("content-length") or 0)
    except ValueError:
        declarado = 0
    if declarado > LIMITE_UPLOAD_BYTES + 4096:
        raise HTTPException(status_code=413, detail=ERRO_UPLOAD_GRANDE)
    partes: List[bytes] = []
    total = 0
    while True:
        pedaco = await file.read(64 * 1024)
        if not pedaco:
            break
        total += len(pedaco)
        if total > LIMITE_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail=ERRO_UPLOAD_GRANDE)
        partes.append(pedaco)
    return b"".join(partes)


ERRO_INTERNO_VEJA_LOG = "A operação falhou no servidor. Veja o log para o detalhe."


def _documento_formatado(digitos: str) -> str:
    """CNPJ (14) ou CPF (11) com máscara; qualquer outro tamanho volta como veio."""
    tipo = "cnpj" if len(digitos or "") == 14 else "cpf" if len(digitos or "") == 11 else None
    return formatar_cnpj_cpf(digitos, tipo) or (digitos or "")


# A configuração como a tela e o agente a leem (Frente 3, leva 7: saiu de
# main.py porque a Configuração e o Instalador a devolvem).
def _settings_dict(s: PortalSettings) -> dict:
    return {
        "source_folder": s.source_folder,
        "expired_folder": s.expired_folder,
        "machine_id": s.machine_id,
        "effective_source": str(s.effective_source()),
        "effective_expired": str(s.effective_expired()),
        "banco": banco_configurado(),
        "persistence": (
            "banco+data/portal_settings.json"
            if banco_configurado()
            else "data/portal_settings.json"
        ),
        "smtp_host": s.smtp_host,
        "smtp_port": s.smtp_port,
        "smtp_user": s.smtp_user,
        "smtp_password_set": bool(s.smtp_password_encrypted),
        "smtp_use_tls": s.smtp_use_tls,
        "smtp_use_ssl": s.smtp_use_ssl,
        # `efetivo` é o que realmente vale agora, com o padrão já resolvido —
        # a tela precisa mostrar isso, não o campo em branco.
        "install_token_ttl_min": s.install_token_ttl_min,
        "install_token_ttl_efetivo": cert_installer.ttl_do_token(),
        "trilha_retencao_dias": s.trilha_retencao_dias,
        "smtp_from_email": s.smtp_from_email,
        "smtp_alerts_enabled": s.smtp_alerts_enabled,
        # Microsoft 365 / Graph: o segredo nunca volta, só "está guardado".
        "email_transporte": correio.transporte(s),
        "graph_tenant_id": s.graph_tenant_id,
        "graph_client_id": s.graph_client_id,
        "graph_client_secret_set": bool(s.graph_client_secret_encrypted),
        "graph_remetente": s.graph_remetente,
        "graph_reply_to": s.graph_reply_to,
        "graph_secret_validade": s.graph_secret_validade,
        "graph_secret_dias_restantes": graph_mail.dias_para_vencer_segredo(s.graph_secret_validade),
        "envio_configurado": correio.configurado(s),
        "remetente_efetivo": correio.remetente_efetivo(s),
        # Alertas. O par `campo` + `campo_efetivo` segue o que o instalador já
        # fazia acima: a tela mostra o campo em branco E o que vale de fato,
        # senão "vazio" pareceria "desligado".
        "alertas_destinatarios": s.alertas_destinatarios,
        "alertas_marcos": s.alertas_marcos,
        "alertas_marcos_efetivos": list(
            alertas_config.marcos_efetivos(s.alertas_marcos)
        ),
        "alertas_intervalo_horas": s.alertas_intervalo_horas,
        "alertas_intervalo_efetivo": alertas_config.intervalo_efetivo_horas(
            s.alertas_intervalo_horas
        ),
        # "lista" ou "admins" em vez da lista de admins resolvida: montá-la
        # aqui custaria uma consulta ao banco numa rota que o agente também
        # chama, e que precisa responder mesmo com o banco ruim.
        "alertas_destinatarios_origem": (
            "lista"
            if alertas_config.destinatarios_configurados(s.alertas_destinatarios)
            else "admins"
        ),
        # Texto do e-mail. Mesmo par `campo` + `campo_efetivo`: o modal precisa
        # abrir com o campo EM BRANCO (senão a pessoa não distingue "eu escrevi
        # isto" de "é o padrão") e mostrar o padrão como placeholder.
        "alerta_email": {
            campo: getattr(s, coluna, "")
            for campo, coluna in email_modelo.CAMPO_COLUNA.items()
        },
        "alerta_email_padrao": dict(email_modelo.PADROES),
        "alerta_email_marcadores": list(email_modelo.MARCADORES),
        "alerta_email_limites": dict(email_modelo.LIMITES),
        # Entrada de certificados (02/10/2026): o agente lê daqui as três
        # pastas; vazio em `pasta_entrada` desliga o passo.
        "pasta_entrada": s.pasta_entrada,
        "pasta_pj": s.pasta_pj,
        "pasta_pf": s.pasta_pf,
        "alertas_novos_enabled": s.alertas_novos_enabled,
        "alertas_novos_modo": s.alertas_novos_modo,
        "alertas_novos_modo_efetivo": alertas_config.modo_novos_efetivo(s.alertas_novos_modo),
    }
