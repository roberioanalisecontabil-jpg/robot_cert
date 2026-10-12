"""Configuração e alertas — Frente 3, leva 9 (12/10/2026).

Saiu de `app/main.py` sem mudar comportamento: `/api/settings` (ler e
gravar), o teste de envio de e-mail, a prévia do e-mail de alerta, o disparo
manual e o do cron, o expurgo diário (o `lifespan` de main.py o chama) e o que
a pessoa vê dos alertas (notificações e enviados).
"""

from __future__ import annotations

import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app import alertas_config, atividade, auth, cert_installer, correio, email_modelo, graph_mail, smtp_service
from app.alert_state import previa_do_resumo, trigger_all_alerts
from app.comum import LISTAGEM_EXPORT_MAX, _settings_dict
from app.notification_service import build_notifications_payload
from app.rotas.usuarios import _EMAIL_PLAUSIVEL, _validar_email
from app.sessao import (
    _limitar,
    _user_id_da_sessao,
    require_admin,
    require_admin_ou_agente_leitura,
    require_auth,
)
from app.settings_state import (
    GravacaoNaoPersistida,
    PastaRecusada,
    PortalSettings,
    get_latest_snapshot,
    load_settings,
    save_settings,
    validar_pasta,
)
from app.smtp_service import encrypt_password, validate_smtp_config

logger = logging.getLogger("app.main")
router = APIRouter()


class SettingsBody(BaseModel):
    source_folder: str = Field(default="", max_length=1024, description="Pasta de certificados no Windows (caminho completo)")
    expired_folder: str = Field(default="", max_length=1024, description="Pasta destino dos vencidos")
    machine_id: str = Field(default="default", max_length=128, description="Identificador lógico da máquina / agente")
    smtp_host: str = Field(default="", max_length=253)
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_user: str = Field(default="", max_length=320)
    smtp_password: Optional[str] = Field(default=None, max_length=1024)
    smtp_use_tls: bool = Field(default=True)
    smtp_use_ssl: bool = Field(default=False)
    smtp_from_email: str = Field(default="", max_length=320)
    smtp_alerts_enabled: bool = Field(default=False)
    # Envio pelo Microsoft 365 / Graph (03/10/2026). `None` = não mexe; o
    # segredo segue a regra da senha SMTP: só grava quando vier preenchido.
    email_transporte: Optional[str] = Field(default=None, max_length=8)
    graph_tenant_id: Optional[str] = Field(default=None, max_length=253)
    graph_client_id: Optional[str] = Field(default=None, max_length=64)
    graph_client_secret: Optional[str] = Field(default=None, max_length=1024)
    graph_remetente: Optional[str] = Field(default=None, max_length=320)
    graph_reply_to: Optional[str] = Field(default=None, max_length=320)
    graph_secret_validade: Optional[str] = Field(default=None, max_length=10)
    # ── Campos que este PUT não "possui" ───────────────────────────────────
    #
    # `None` = NÃO MEXE; qualquer outro valor grava — inclusive vazio, que aqui
    # significa "voltar ao padrão do código". É a mesma semântica que
    # `smtp_password` já usava neste modelo, agora estendida aos campos que
    # nenhum dos formulários desta tela envia.
    #
    # Sem isso, o PUT remonta o `PortalSettings` inteiro a partir do corpo: os
    # dois formulários de /configuracao mandam 11 campos, e os que faltam
    # voltavam ao default. Salvar as PASTAS apagava o template de nome do
    # instalador, o TTL do token e a retenção da trilha — configurados em outra
    # tela, por outra rota, e zerados aqui sem nenhum aviso.
    #
    # O sintoma aparece longe da causa: o instalador volta a gerar o nome
    # padrão, e nada na tela de Configuração sugere que foi ela.
    install_token_ttl_min: Optional[int] = Field(default=None)
    trilha_retencao_dias: Optional[int] = Field(default=None)
    alertas_destinatarios: Optional[str] = Field(default=None)
    alertas_marcos: Optional[str] = Field(default=None)
    alertas_intervalo_horas: Optional[int] = Field(default=None)
    # Editados por um modal só, e ausentes de todos os outros formulários da
    # tela — `None` aqui é o que impede o Salvar das pastas de apagar o texto
    # do e-mail.
    alerta_email_assunto: Optional[str] = Field(default=None)
    alerta_email_titulo: Optional[str] = Field(default=None)
    alerta_email_abertura: Optional[str] = Field(default=None)
    alerta_email_recado: Optional[str] = Field(default=None)
    # Entrada de certificados e aviso de novos (02/10/2026). Mesma regra:
    # `None` preserva; vazio em pasta é "sem entrada"; vazio no modo é o padrão.
    pasta_entrada: Optional[str] = Field(default=None, max_length=1024)
    pasta_pj: Optional[str] = Field(default=None, max_length=1024)
    pasta_pf: Optional[str] = Field(default=None, max_length=1024)
    alertas_novos_enabled: Optional[bool] = Field(default=None)
    alertas_novos_modo: Optional[str] = Field(default=None, max_length=16)


# Mao dupla: a tela de Configuracao le daqui, e o agente tambem — e o que diz
# a ele quais pastas varrer. `permitir_agente` mantem o robo funcionando enquanto
# o modulo passa a governar as pessoas.
@router.get("/api/settings", dependencies=[Depends(require_admin_ou_agente_leitura)])
def get_settings() -> dict:
    s = load_settings()
    return _settings_dict(s)


@router.put("/api/settings", dependencies=[Depends(require_admin)])
def put_settings(body: SettingsBody) -> dict:
    # Lido ANTES de validar: campo omitido é validado a partir do que já está
    # gravado, e não do default. Validar o default e gravar o valor antigo
    # deixaria os dois em desacordo.
    old = load_settings()

    try:
        validate_smtp_config(
            body.smtp_use_tls, body.smtp_use_ssl,
            host=(body.smtp_host or old.smtp_host),
            port=body.smtp_port,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    # As pastas passam por `validar_pasta` (achado #16): UNC nunca, e fora de
    # PASTAS_PERMITIDAS nunca quando a lista existe. O mesmo filtro roda na
    # leitura (`effective_source`), para um valor antigo no banco não abrir o
    # que a tela recusaria.
    try:
        pasta_origem = validar_pasta(body.source_folder, "Pasta de origem")
        pasta_vencidos = validar_pasta(body.expired_folder, "Pasta de vencidos")
        # Entrada: as três passam pela MESMA cerca (UNC recusado, raízes
        # permitidas). `None` preserva o que está gravado.
        pasta_entrada = validar_pasta(
            old.pasta_entrada if body.pasta_entrada is None else body.pasta_entrada, "Pasta de entrada"
        )
        pasta_pj = validar_pasta(old.pasta_pj if body.pasta_pj is None else body.pasta_pj, "Pasta de pessoa jurídica")
        pasta_pf = validar_pasta(old.pasta_pf if body.pasta_pf is None else body.pasta_pf, "Pasta de pessoa física")
    except PastaRecusada as e:
        raise HTTPException(status_code=422, detail=str(e))
    if pasta_entrada and not (pasta_pj and pasta_pf):
        raise HTTPException(
            status_code=422,
            detail="Pasta de entrada: informe também as pastas de pessoa jurídica e de pessoa física, senão o agente não sabe para onde mover.",
        )
    if pasta_entrada and pasta_entrada in (pasta_pj, pasta_pf, pasta_vencidos):
        raise HTTPException(status_code=422, detail="Pasta de entrada: não pode ser a mesma pasta do acervo ou dos vencidos.")
    try:
        modo_novos = alertas_config.validar_modo_novos(
            old.alertas_novos_modo if body.alertas_novos_modo is None else body.alertas_novos_modo
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    novos_ligado = old.alertas_novos_enabled if body.alertas_novos_enabled is None else bool(body.alertas_novos_enabled)

    ttl = int(
        (old.install_token_ttl_min if body.install_token_ttl_min is None
         else body.install_token_ttl_min) or 0
    )
    if ttl and not (cert_installer.TTL_TOKEN_MIN <= ttl <= cert_installer.TTL_TOKEN_MAX):
        raise HTTPException(
            status_code=422,
            detail=(
                f"Validade do token: use entre {cert_installer.TTL_TOKEN_MIN} e "
                f"{cert_installer.TTL_TOKEN_MAX} minutos, ou 0 para o padrão."
            ),
        )

    retencao = int(
        (old.trilha_retencao_dias if body.trilha_retencao_dias is None
         else body.trilha_retencao_dias) or 0
    )
    if retencao < 0:
        raise HTTPException(status_code=422, detail="Retenção não pode ser negativa.")

    # Alertas: recusar aqui é a única defesa. O job roda sem ninguém olhando e
    # trata valor ilegível caindo no padrão — o que é a decisão certa PARA O
    # JOB e péssima como resposta à tela, porque a pessoa salvaria "30,15,cinco"
    # e receberia "salvo" enquanto o portal seguisse com 30,15,7,1.
    try:
        marcos = alertas_config.formatar_marcos(
            alertas_config.parse_marcos(
                old.alertas_marcos if body.alertas_marcos is None else body.alertas_marcos
            )
        )
        destinatarios = alertas_config.formatar_destinatarios(
            alertas_config.parse_destinatarios(
                old.alertas_destinatarios
                if body.alertas_destinatarios is None
                else body.alertas_destinatarios
            )
        )
        intervalo = alertas_config.validar_intervalo(
            old.alertas_intervalo_horas
            if body.alertas_intervalo_horas is None
            else body.alertas_intervalo_horas
        )
    except alertas_config.ConfiguracaoInvalida as e:
        raise HTTPException(status_code=422, detail=str(e))

    # Texto do e-mail: mesma assimetria dos marcos, e pelo mesmo motivo. O job
    # cai no padrão diante de um marcador que não existe, porque alerta que não
    # sai é pior que alerta com um `{tota}` literal no meio. Só que "cai no
    # padrão" como resposta à tela seria a pessoa salvar `{tota}`, ler "salvo" e
    # nunca ver o texto que escreveu.
    try:
        modelo = {
            campo: email_modelo.validar_campo(
                campo,
                getattr(old, coluna, "") if getattr(body, coluna) is None
                else getattr(body, coluna),
            )
            for campo, coluna in email_modelo.CAMPO_COLUNA.items()
        }
    except email_modelo.ModeloInvalido as e:
        raise HTTPException(status_code=422, detail=str(e))

    enc_password = old.smtp_password_encrypted
    # A senha guardada foi digitada para AQUELE servidor e usuário. Trocar o
    # destino sem redigitá-la a mandaria para o servidor novo no próximo envio
    # ou teste (auditoria de 10/10/2026): sem senha nova, ela é descartada.
    destino_mudou = (
        (body.smtp_host or "").strip().lower() != (old.smtp_host or "").strip().lower()
        or (body.smtp_user or "").strip().lower() != (old.smtp_user or "").strip().lower()
        or int(body.smtp_port or 0) != int(old.smtp_port or 0)
    )
    if destino_mudou:
        enc_password = ""
    if body.smtp_password is not None and body.smtp_password.strip() != "":
        try:
            enc_password = encrypt_password(body.smtp_password.strip())
        except Exception as e:
            raise HTTPException(status_code=500, detail="Erro ao criptografar senha SMTP")
            
    # Remetente vazio usa o usuário SMTP; preenchido, precisa parecer e-mail
    # (revisão de 01/10/2026: só o destino do teste era conferido).
    remetente = (body.smtp_from_email or "").strip()
    if remetente and not _EMAIL_PLAUSIVEL.match(remetente):
        raise HTTPException(status_code=422, detail=f"E-mail do remetente inválido: {remetente!r}")

    # Microsoft 365 / Graph (03/10/2026): `None` preserva; o segredo só grava
    # quando vier preenchido, como a senha SMTP. Com a forma "graph" os
    # quatro campos obrigatórios são validados aqui — recusar é a única
    # defesa, porque o job de alertas só descobriria na hora de enviar.
    transporte_novo = (old.email_transporte if body.email_transporte is None else body.email_transporte or "").strip().lower()
    if transporte_novo and transporte_novo not in correio.TRANSPORTES:
        raise HTTPException(status_code=422, detail="Forma de envio desconhecida. Use 'smtp' ou 'graph'.")
    g_tenant = (old.graph_tenant_id if body.graph_tenant_id is None else body.graph_tenant_id).strip()
    g_client = (old.graph_client_id if body.graph_client_id is None else body.graph_client_id).strip()
    g_remetente = (old.graph_remetente if body.graph_remetente is None else body.graph_remetente).strip()
    g_reply_to = (old.graph_reply_to if body.graph_reply_to is None else body.graph_reply_to).strip()
    g_validade = (old.graph_secret_validade if body.graph_secret_validade is None else body.graph_secret_validade).strip()
    if g_validade and graph_mail.dias_para_vencer_segredo(g_validade) is None:
        raise HTTPException(status_code=422, detail="Validade do segredo: use a data no formato AAAA-MM-DD, ou deixe vazio.")
    g_secret_enc = old.graph_client_secret_encrypted
    if body.graph_client_secret is not None and body.graph_client_secret.strip() != "":
        try:
            g_secret_enc = encrypt_password(body.graph_client_secret.strip())
        except Exception:
            raise HTTPException(status_code=500, detail="Erro ao criptografar o segredo do aplicativo")
    if transporte_novo == correio.TRANSPORTE_GRAPH:
        try:
            graph_mail.validar_config(g_tenant, g_client, g_remetente, g_reply_to)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))
        if not g_secret_enc:
            raise HTTPException(status_code=422, detail="Informe o segredo do aplicativo para usar o Microsoft 365.")
    s = PortalSettings(
        source_folder=pasta_origem,
        expired_folder=pasta_vencidos,
        machine_id=body.machine_id.strip() or "default",
        smtp_host=body.smtp_host.strip(),
        smtp_port=body.smtp_port,
        smtp_user=body.smtp_user.strip(),
        smtp_password_encrypted=enc_password,
        smtp_use_tls=body.smtp_use_tls,
        smtp_use_ssl=body.smtp_use_ssl,
        smtp_from_email=remetente,
        smtp_alerts_enabled=body.smtp_alerts_enabled,
        email_transporte=transporte_novo,
        graph_tenant_id=g_tenant,
        graph_client_id=g_client,
        graph_client_secret_encrypted=g_secret_enc,
        graph_remetente=g_remetente,
        graph_reply_to=g_reply_to,
        graph_secret_validade=g_validade,
        # O SIEG tem tela e rota próprias (PUT /api/sieg/configuracao): aqui
        # só atravessa, senão salvar Alertas apagaria as credenciais.
        sieg_client_id=old.sieg_client_id,
        sieg_secret_key_encrypted=old.sieg_secret_key_encrypted,
        sieg_api_key_encrypted=old.sieg_api_key_encrypted,
        sieg_padroes=old.sieg_padroes,
        install_token_ttl_min=ttl,
        trilha_retencao_dias=retencao,
        alertas_destinatarios=destinatarios,
        alertas_marcos=marcos,
        alertas_intervalo_horas=intervalo,
        pasta_entrada=pasta_entrada,
        pasta_pj=pasta_pj,
        pasta_pf=pasta_pf,
        alertas_novos_enabled=novos_ligado,
        alertas_novos_modo=modo_novos,
        **{coluna: modelo[campo] for campo, coluna in email_modelo.CAMPO_COLUNA.items()},
    )
    # 503, e não 200: o valor foi para o arquivo local, mas `load_settings`
    # prefere o banco — a próxima leitura devolveria o valor antigo. Dizer
    # "salvo" aqui seria a tela mentindo sobre um dado que ela mesma vai
    # recarregar diferente.
    try:
        save_settings(s, exigir_banco=True)
    except GravacaoNaoPersistida as e:
        # O motivo (código do banco, coluna que falta) vai para o log, onde
        # quem vai consertar o lê; a resposta diz só o que aconteceu (#35).
        logger.error("Gravação da configuração não persistida: %s", e)
        raise HTTPException(
            status_code=503,
            detail=(
                "Não foi possível gravar no banco; nada foi alterado para o portal. "
                "A cópia local ficou guardada. Veja o log do servidor."
            ),
        )
    return _settings_dict(s)



class SmtpTestBody(BaseModel):
    target_email: str = Field(max_length=320)


@router.post(
    "/api/settings/smtp/test",
    dependencies=[
        Depends(require_admin),
        # Cinco por hora por identidade (achado #28): era relay autenticado
        # sem teto, um e-mail do remetente corporativo por clique.
        Depends(_limitar("smtp-test", 5, 3600)),
    ],
)
def test_smtp_config(body: SmtpTestBody) -> dict:
    # Endereço plausível e sem CR/LF: o valor ia direto para `msg["To"]`.
    destino = _validar_email(body.target_email)
    s = load_settings()
    if not correio.configurado(s):
        raise HTTPException(status_code=400, detail=(
            "Servidor SMTP não configurado." if correio.transporte(s) == correio.TRANSPORTE_SMTP
            else "Microsoft 365 não configurado: faltam tenant, aplicativo, segredo ou caixa de envio."))
    forma = correio.ROTULOS[correio.transporte(s)]
    try:
        # Pelo despachante (03/10/2026): SMTP ou Microsoft 365, conforme a
        # configuração salva. Qualificado pelo módulo: `send_smtp_email` nunca
        # esteve na lista de imports deste arquivo, e a rota levantava
        # NameError em vez de enviar.
        correio.send_smtp_email(
            host=s.smtp_host,
            port=s.smtp_port,
            user=s.smtp_user,
            password_enc=s.smtp_password_encrypted,
            use_tls=s.smtp_use_tls,
            use_ssl=s.smtp_use_ssl,
            from_email=s.smtp_from_email,
            to_email=destino,
            settings=s,
            subject="Monitor de Certificados - E-mail de Teste",
            html_content=f"<p>Olá! Este é um e-mail de teste enviado a partir do seu <strong>Monitor de Certificados</strong> para validar o envio por {forma}.</p>"
        )
    # Uma mensagem fixa por CLASSE de falha (achado #35; item 91 da spec de
    # telas). O texto do servidor SMTP trazia o usuário, às vezes o endereço
    # do host resolvido, e a máscara por substring era frágil. O detalhe fica
    # no log do `smtp_service`.
    except ValueError as e:
        # Validação nossa (sem TLS para servidor externo, TLS e SSL juntos):
        # texto curado, escrito para a pessoa que está configurando.
        raise HTTPException(status_code=400, detail=str(e))
    except smtp_service.ErroAutenticacaoSmtp:
        raise HTTPException(status_code=400, detail="O servidor SMTP recusou o usuário ou a senha.")
    except smtp_service.ErroTlsSmtp:
        raise HTTPException(status_code=400, detail=(
            "A conexão segura com o servidor SMTP falhou. Confira a opção de segurança e a porta."))
    except smtp_service.ErroConexaoSmtp:
        raise HTTPException(status_code=400, detail=(
            "Não foi possível conectar ao servidor SMTP. Confira o endereço e a porta."))
    except graph_mail.ErroAutenticacaoGraph:
        raise HTTPException(status_code=400, detail=(
            "A Microsoft recusou as credenciais do aplicativo. Confira o ID do tenant, o ID do aplicativo e o segredo (e se ele não venceu)."))
    except graph_mail.ErroPermissaoGraph:
        raise HTTPException(status_code=400, detail=(
            "O aplicativo não tem permissão para enviar por essa caixa: confira o consentimento de Mail.Send e a política de acesso."))
    except graph_mail.ErroConexaoGraph:
        raise HTTPException(status_code=400, detail="Não foi possível falar com a Microsoft. Confira a saída do servidor para a internet.")
    except graph_mail.ErroEnvioGraph:
        raise HTTPException(status_code=400, detail="A Microsoft recusou a mensagem. Confira a caixa de envio e o destinatário.")
    except Exception:
        logger.exception("Falha no e-mail de teste")
        raise HTTPException(status_code=400, detail="Falha ao enviar o e-mail de teste. Veja o log do servidor.")
    return {"ok": True, "message": "E-mail de teste enviado com sucesso!"}


class PreviaEmailBody(BaseModel):
    """O texto que a pessoa está digitando, ainda não salvo.

    `None` em um campo é "usar o que está gravado" — a mesma semântica do
    `SettingsBody`, para a prévia de um campo em branco mostrar o padrão em vez
    de um buraco.
    """
    alerta_email_assunto: Optional[str] = Field(default=None)
    alerta_email_titulo: Optional[str] = Field(default=None)
    alerta_email_abertura: Optional[str] = Field(default=None)
    alerta_email_recado: Optional[str] = Field(default=None)


@router.post("/api/settings/alerts/preview", dependencies=[Depends(require_admin)])
def preview_email_alerta(body: PreviaEmailBody) -> dict:
    """O e-mail que sairia agora com este texto, sem salvar nada.

    Valida com a MESMA `validar_campo` do PUT e devolve o mesmo 422. Uma prévia
    mais tolerante que o Salvar deixaria a pessoa aprovar na tela um texto que a
    gravação depois recusa.
    """
    old = load_settings()
    try:
        modelo = {
            campo: email_modelo.validar_campo(
                campo,
                getattr(old, coluna, "") if getattr(body, coluna) is None
                else getattr(body, coluna),
            )
            for campo, coluna in email_modelo.CAMPO_COLUNA.items()
        }
    except email_modelo.ModeloInvalido as e:
        raise HTTPException(status_code=422, detail=str(e))
    return {"ok": True, **previa_do_resumo(old, modelo)}


@router.post(
    "/api/settings/alerts/trigger",
    dependencies=[
        Depends(require_admin),
        # Varre o acervo inteiro e envia o resumo dos administradores e os
        # e-mails pessoais de quem acompanha, de forma síncrona: três por hora
        # por identidade (achado #28).
        Depends(_limitar("alerts-trigger", 3, 3600)),
    ],
)
def trigger_alerts_manually() -> dict:
    try:
        stats = trigger_all_alerts()
        return {"ok": True, "stats": stats}
    except Exception:
        logger.exception("Falha no disparo manual de alertas")
        raise HTTPException(status_code=500, detail="O disparo falhou. Veja o log do servidor.")


@router.get("/api/cron/alerts")
def cron_alerts(request: Request) -> dict:
    """
    Disparo agendado dos alertas, chamado pelo agendador do servidor (até
    22/09/2026 era o Cron da Vercel; o portal hoje roda no ANALISESRV).

    Existe porque o laço do `lifespan` não roda em serverless: cada requisição
    instancia a função e a encerra, então o `asyncio.create_task` morre antes
    dos 60s do primeiro disparo. No Render, com processo vivo, o laço bastava;
    no Vercel ninguém nunca chamaria `trigger_all_alerts`.

    Autenticação por CRON_SECRET em vez de JWT: o Cron do Vercel não faz login.
    Quando a variável CRON_SECRET existe no projeto, o Vercel envia
    `Authorization: Bearer <CRON_SECRET>` automaticamente em cada chamada.

    Falha FECHADA se a variável não estiver definida: uma rota que dispara
    envio de e-mail em massa não pode ficar aberta a quem descobrir a URL só
    porque alguém esqueceu de configurar o segredo.
    """
    segredo = (os.getenv("CRON_SECRET") or "").strip()
    if not segredo:
        logger.error("CRON_SECRET não configurada — disparo agendado recusado.")
        raise HTTPException(
            status_code=503,
            detail="CRON_SECRET não configurada no ambiente.",
        )

    enviado = (request.headers.get("authorization") or "").strip()
    esperado = f"Bearer {segredo}"
    # compare_digest evita vazar o segredo pelo tempo de resposta.
    if not secrets.compare_digest(enviado, esperado):
        logger.warning("Chamada ao cron de alertas com credencial inválida.")
        raise HTTPException(status_code=401, detail="Não autorizado.")

    try:
        stats = trigger_all_alerts()
        logger.info(f"Cron de alertas concluído: {stats}")
    except Exception:
        logger.exception("Falha no cron de alertas")
        raise HTTPException(status_code=500, detail="O cron de alertas falhou. Veja o log do servidor.")

    # Expurgo do install_log pendurado no mesmo disparo diário, e não num cron
    # próprio: os planos da Vercel limitam o número de crons, e um segundo
    # agendamento poderia simplesmente não ser criado — falha silenciosa numa
    # rotina de LGPD é o pior lugar para tê-la.
    #
    # Try/except próprio de propósito: apagar log é acessório, e não pode
    # derrubar o envio de alertas, que é o motivo de a rota existir. Se falhar,
    # aparece na resposta em vez de sumir.
    expurgo = _expurgo_diario()

    return {"ok": True, "stats": stats, "expurgo": expurgo}


def _expurgo_diario() -> Dict[str, Any]:
    """Os expurgos que acompanham o ciclo diário de alertas.

    Até 03/10/2026 só a rota `/api/cron/alerts` os chamava — e, fora da
    Vercel, nada chama essa rota: no ANALISESRV o laço do `lifespan` disparava
    os alertas e os expurgos simplesmente não rodavam. Agora o laço chama
    isto também.

    Try/except por item: apagar é acessório e um não pode derrubar o outro
    nem o envio de alertas, que é o motivo de o ciclo existir.
    """
    from app import snapshots

    etapas = (
        ("install_log", cert_installer.expurgar_install_log),
        ("user_activity", atividade.expurgar),
        # O cofre entra no mesmo ciclo: chave privada de certificado vencido
        # ou removido da pasta é passivo puro, e o acervo só crescia porque
        # nada a tirava.
        ("cofre", cert_installer.expurgar_cofre),
        # Snapshots: 180 dias, preservando a última varredura de cada máquina.
        ("cert_snapshots", snapshots.expurgar),
    )
    out: Dict[str, Any] = {}
    for nome, fn in etapas:
        try:
            out[nome] = fn()
        except Exception as e:  # noqa: BLE001
            logger.exception("Falha no expurgo de %s", nome)
            out[nome] = {"executado": False, "motivo": str(e)}
    return out


# Modulo `acompanhamento` na matriz desde 20/08: os GET pedem `ler`, os dois
# PUT (selecao e preferencia) pedem `editar`. "So ver" acompanha o que ja
# escolheu; "Ver e editar" escolhe. O padrao de gestor e operador e `editar`.
#
# O sino esta em TODA pagina, entao nao depende de modulo nenhum (decisao I5,
# 01/10/2026): ate 30/09 era `require_modulo("acompanhamento")`, e um papel com
# "Nao entra" naquele modulo via o sino quebrar em todas as telas. O conteudo
# continua sendo o da pessoa (selecao de Acompanhamento e Alcance); so a
# PAGINA Acompanhamento segue a matriz.
@router.get("/api/colaborador/notificacoes", dependencies=[Depends(require_auth)])
def get_user_notifications(
    token: auth.TokenData = Depends(require_auth),
    tipo: Optional[str] = Query(None, max_length=16, pattern=r"^(novo|expiring|expired)$"),
) -> dict:
    try:
        # Devolve lista limitada + totais separados: antes eram 519 itens
        # (167 KB) a cada poll de 60s, com os acionáveis no fim da lista.
        # `tipo` é o chip do sino (30/09/2026): a lista vem só daquele tipo,
        # os totais continuam os do conjunto inteiro.
        return build_notifications_payload(
            token.email, token.role, _user_id_da_sessao(token), tipo=tipo
        )
    except Exception:
        logger.exception("Falha ao montar as notificações")
        raise HTTPException(status_code=500, detail="Não foi possível carregar as notificações.")


@router.get("/api/colaborador/alertas/enviados", dependencies=[Depends(require_auth)])
def alertas_enviados(
    dias: int = Query(30, ge=1, le=365),
    token: auth.TokenData = Depends(require_auth),
) -> dict:
    """Os avisos que o portal já mandou (aba Enviados do Acompanhamento,
    03/10/2026). Administrador vê tudo; Gestor e Operador só o que foi para
    o próprio e-mail — a mesma regra do sino e do e-mail."""
    from app import texto as _texto
    from app.settings_state import _banco

    sb = _banco()
    if not sb:
        raise HTTPException(status_code=503, detail="Sistema sem banco configurado.")
    desde = (datetime.now(timezone.utc) - timedelta(days=dias)).isoformat()
    so_admin = (token.role or "").lower() == "admin"
    try:
        q = (
            sb.table("sent_alerts")
            .select("fingerprint_sha256, tipo_alerta, destinatario, data_validade, sent_at")
            .gte("sent_at", desde)
        )
        if not so_admin:
            q = q.eq("destinatario", (token.email or "").strip().lower())
        linhas = list(q.order("sent_at", desc=True).limit(LISTAGEM_EXPORT_MAX).execute().data or [])
    except Exception:
        logger.exception("Falha ao listar os avisos enviados")
        raise HTTPException(status_code=500, detail="Não foi possível carregar os avisos enviados.")

    # Nome e documento pelo fingerprint, numa consulta só. O resumo diário dos
    # administradores não tem certificado (fingerprint "__resumo_admin__").
    fps = sorted({str(l.get("fingerprint_sha256") or "") for l in linhas if len(str(l.get("fingerprint_sha256") or "")) == 64})
    nomes: Dict[str, dict] = {}
    for i in range(0, len(fps), 200):
        try:
            r = sb.table("cert_pfx_store").select("fingerprint, nome_titular, documento").in_("fingerprint", fps[i : i + 200]).execute()
        except Exception:  # noqa: BLE001
            logger.warning("Avisos enviados sem os nomes dos certificados (cert_pfx_store indisponível)")
            break
        for c in r.data or []:
            nomes[str(c.get("fingerprint") or "")] = {"nome": c.get("nome_titular"), "documento": c.get("documento")}
    # O que não está no cofre (custódia desligada, arquivo vencido e expurgado)
    # ainda pode estar no inventário atual: um snapshot, lido uma vez.
    faltam = {fp for fp in fps if fp not in nomes}
    if faltam:
        try:
            for it in list((get_latest_snapshot() or {}).get("items") or []):
                fp = str(it.get("fingerprint_sha256") or "").strip().lower()
                if fp in faltam:
                    nomes[fp] = {"nome": it.get("nome"), "documento": it.get("documento") or it.get("documento_numero")}
        except Exception:  # noqa: BLE001
            logger.warning("Avisos enviados: inventário atual indisponível para completar nomes")

    itens = []
    for l in linhas:
        fp = str(l.get("fingerprint_sha256") or "")
        cert = nomes.get(fp) or {}
        itens.append({
            "enviado_em": l.get("sent_at"),
            "tipo": l.get("tipo_alerta"),
            "rotulo": _texto.rotulo_alerta(_texto.chave_alerta(l.get("tipo_alerta"))),
            "destinatario": l.get("destinatario"),
            "nome": cert.get("nome"),
            "documento": cert.get("documento"),
            "data_validade": l.get("data_validade") if fp != "__resumo_admin__" else None,
        })
    return {"dias": dias, "total": len(itens), "itens": itens, "ve_tudo": so_admin}
