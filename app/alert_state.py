import html
import json
import logging
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import List, Dict, Any, Optional

from app import config
from app.auth import conta_ativa
from app import alertas_config
from app.settings_state import load_settings, _supabase, _load_colaborador_file_dict
from app.cert_scanner import scan_folder, cert_to_public_dict
from app.smtp_service import send_smtp_email

logger = logging.getLogger(__name__)

SENT_ALERTS_FILE = config.ROOT / "data" / "sent_alerts.json"
JOB_STATE_FILE = config.ROOT / "data" / "alerts_job_state.json"

# Marcos de reforço antes do vencimento. Antes existia um único aviso: a chave
# antispam era (certificado, "expiring", destinatário, validade), então um
# certificado entrando na janela de 30 dias recebia UM e-mail no dia 30 e
# silêncio até vencer. Com marcos, cada limiar dispara uma vez.
# Os marcos e o intervalo agora vem da tela (Configuracao > Alertas). Estes
# nomes seguem existindo como o PADRAO — o valor que vale quando ninguem
# configurou nada — e por isso continuam sendo a fonte para os testes que
# afirmam o comportamento de fabrica.
MARCOS_EXPIRACAO = list(alertas_config.MARCOS_PADRAO)

# Intervalo mínimo entre execuções do job. Necessário porque o Procfile usa
# `--max-requests 500`: o worker recicla várias vezes ao dia e o job dispara em
# boot+60s a cada reinício, então "diário" nunca foi diário de fato.
INTERVALO_MINIMO_JOB_HORAS = alertas_config.INTERVALO_PADRAO_HORAS


def _marco_expiracao(dias: int, marcos=None) -> int:
    """Menor marco ainda não ultrapassado — 25 dias -> 30, 12 -> 15, 5 -> 7, 0 -> 1.

    `marcos` omitido usa o padrão, e não a configuração: quem chama sem passar
    nada está perguntando pelo comportamento de fábrica. Deixar o default ler o
    banco tornaria uma função pura dependente de I/O sem que a assinatura
    dissesse isso.
    """
    return alertas_config.marco_de(dias, marcos or MARCOS_EXPIRACAO)

def _load_local_sent_alerts() -> List[Dict[str, Any]]:
    if not SENT_ALERTS_FILE.is_file():
        return []
    try:
        return json.loads(SENT_ALERTS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []

def _save_local_sent_alerts(alerts: List[Dict[str, Any]]) -> None:
    SENT_ALERTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    # Rotação de fallback local: mantém apenas os últimos 1000 registros
    if len(alerts) > 1000:
        alerts = alerts[-1000:]
    try:
        SENT_ALERTS_FILE.write_text(
            json.dumps(alerts, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
    except Exception as e:
        logger.error(f"Erro ao salvar localmente sent_alerts: {e}")

def _is_alert_already_sent(
    fingerprint: str,
    tipo_alerta: str,
    destinatario: str,
    validade_iso: str
) -> bool:
    """Verifica antispam composto: certificado + tipo + validade + destinatário."""
    client = _supabase()
    if client:
        try:
            r = (
                client.table("sent_alerts")
                .select("id")
                .eq("fingerprint_sha256", fingerprint)
                .eq("tipo_alerta", tipo_alerta)
                .eq("destinatario", destinatario.lower().strip())
                .eq("data_validade", validade_iso)
                .limit(1)
                .execute()
            )
            return len(r.data or []) > 0
        except Exception as e:
            logger.warning(f"Falha ao ler sent_alerts no Supabase, usando local: {e}")
            
    # Fallback local
    local_alerts = _load_local_sent_alerts()
    dest_norm = destinatario.lower().strip()
    for al in local_alerts:
        if (
            al.get("fingerprint_sha256") == fingerprint
            and al.get("tipo_alerta") == tipo_alerta
            and str(al.get("destinatario") or "").lower().strip() == dest_norm
            and al.get("data_validade") == validade_iso
        ):
            return True
    return False

def _record_sent_alert(
    fingerprint: str,
    tipo_alerta: str,
    destinatario: str,
    validade_iso: str
) -> None:
    """Registra o envio para fins de antispam."""
    now_iso = datetime.now(timezone.utc).isoformat()
    client = _supabase()
    if client:
        try:
            row = {
                "fingerprint_sha256": fingerprint,
                "tipo_alerta": tipo_alerta,
                "destinatario": destinatario.lower().strip(),
                "data_validade": validade_iso,
                "sent_at": now_iso
            }
            client.table("sent_alerts").insert(row).execute()
            return
        except Exception as e:
            logger.warning(f"Falha ao salvar sent_alert no Supabase, salvando local: {e}")
            
    # Gravação local com rotação
    local_alerts = _load_local_sent_alerts()
    local_alerts.append({
        "fingerprint_sha256": fingerprint,
        "tipo_alerta": tipo_alerta,
        "destinatario": destinatario.lower().strip(),
        "data_validade": validade_iso,
        "sent_at": now_iso
    })
    _save_local_sent_alerts(local_alerts)

def _get_admin_emails() -> List[str]:
    """
    E-mails dos administradores ativos.

    O sino mostra ao admin todos os certificados do sistema, mas o e-mail só ia
    para quem tinha documentos selecionados em `colaborador_cert_selecoes` — um
    admin via 519 alertas na tela e recebia zero e-mails. Aqui os dois canais
    passam a concordar sobre quem deve ser avisado.
    """
    client = _supabase()
    if not client:
        return []
    try:
        # O filtro de ativo saiu da consulta para o Python quando papel e estado
        # se separaram (15/08). Enquanto `disabled` era um papel, `.eq("role",
        # "admin")` já excluía o desativado por acidente; com as colunas
        # separadas, o admin desativado continua com role='admin' e voltaria a
        # receber e-mail. É regressão silenciosa: ninguém reclama de receber.
        r = client.table("users").select("email, role, ativo").eq("role", "admin").execute()
        out = []
        for row in (r.data or []):
            email = str(row.get("email") or "").strip().lower()
            if email and conta_ativa(row):
                out.append(email)
        return sorted(set(out))
    except Exception as e:
        logger.warning(f"Não foi possível listar administradores para o resumo: {e}")
        return []


def _load_job_state() -> Dict[str, Any]:
    if not JOB_STATE_FILE.is_file():
        return {}
    try:
        return json.loads(JOB_STATE_FILE.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def _save_job_state(state: Dict[str, Any]) -> None:
    try:
        JOB_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        JOB_STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        # Sistema de arquivos efêmero (Vercel/containers): sem marcador, o job
        # volta a rodar a cada reinício. É desperdício, não duplicidade — o
        # antispam por certificado continua valendo.
        logger.warning(f"Não foi possível gravar o estado do job de alertas: {e}")


def job_ja_executado_recentemente(horas: Optional[int] = None) -> bool:
    """True se o job rodou há menos que o intervalo configurado.

    `horas` omitido lê a configuração. É I/O dentro de uma função que parece
    barata, e é deliberado: o laço chama isto de hora em hora, e sem ler aqui
    uma mudança de periodicidade só valeria no próximo reinício do worker —
    ou seja, a tela salvaria e nada aconteceria.
    """
    if horas is None:
        try:
            horas = alertas_config.intervalo_efetivo_horas(
                load_settings().alertas_intervalo_horas
            )
        except Exception as e:  # noqa: BLE001
            # Configuração ilegível não pode virar "roda toda hora": cairia em
            # e-mail repetido. O padrão é o comportamento conhecido.
            logger.warning("Intervalo de alertas ilegível (%s); usando o padrão.", e)
            horas = INTERVALO_MINIMO_JOB_HORAS

    ultimo = _load_job_state().get("ultima_execucao")
    if not ultimo:
        return False
    try:
        dt = datetime.fromisoformat(str(ultimo).replace("Z", "+00:00"))
    except Exception:
        return False
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    delta = datetime.now(timezone.utc) - dt
    return delta < timedelta(hours=horas)


def registrar_execucao_job() -> None:
    state = _load_job_state()
    state["ultima_execucao"] = datetime.now(timezone.utc).isoformat()
    _save_job_state(state)


def _linhas_ativas() -> Optional[List[Dict[str, Any]]]:
    """
    Contas que podem receber alerta: existem em `users` e não estão desativadas.

    Devolve None se a lista não puder ser obtida — o chamador interpreta como
    "não sei filtrar" e mantém o comportamento anterior, em vez de silenciar
    todos os alertas por causa de uma falha de leitura.

    Existe para `_get_todos_colaboradores_selecoes` tirar daqui as DUAS visões
    que precisa (por id e por e-mail) com uma leitura só.
    """
    client = _supabase()
    if not client:
        return None
    try:
        r = client.table("users").select("id, email, role, ativo").execute()
        return [
            row
            for row in (r.data or [])
            if str(row.get("email") or "").strip() and conta_ativa(row)
        ]
    except Exception as e:
        logger.warning(f"Não foi possível listar usuários ativos para filtrar alertas: {e}")
        return None


def _por_id(linhas: List[Dict[str, Any]]) -> Dict[str, str]:
    """
    `user_id` -> e-mail ATUAL. É aqui que mora o ganho da fase 2: o endereço
    sai da conta, e não da linha de seleção, então e-mail trocado depois da
    escolha deixa de perder o destinatário.
    """
    return {
        str(row.get("id")): str(row.get("email") or "").strip().lower()
        for row in linhas
        if row.get("id")
    }


def _por_email(linhas: List[Dict[str, Any]]) -> set:
    return {str(row.get("email") or "").strip().lower() for row in linhas}


def _emails_ativos() -> Optional[set]:
    """
    E-mails ativos, para o caminho do arquivo local — que não tem `user_id`
    para cruzar. **Não** exige `id`: em produção ele é a chave primária e
    sempre existe, mas fazer o casamento por e-mail depender dele seria
    inventar um jeito novo de a lista vir vazia, e lista vazia aqui significa
    "ninguém recebe".
    """
    linhas = _linhas_ativas()
    return None if linhas is None else _por_email(linhas)


def _so_de_ativos(selecoes: Dict[str, List[str]]) -> Dict[str, List[str]]:
    """
    Filtro do caminho do arquivo local, que não tem `user_id` para cruzar.

    Extraído sem mudança de comportamento: é a regra que valia para as duas
    origens antes da fase 2, e continua valendo para esta.
    """
    ativos = _emails_ativos()
    if ativos is None:
        return selecoes
    permitidas = {e: d for e, d in selecoes.items() if e in ativos}
    descartadas = sorted(set(selecoes) - set(permitidas))
    if descartadas:
        logger.info(
            "Seleções ignoradas por usuário inativo ou inexistente: %s",
            ", ".join(descartadas),
        )
    return permitidas


def _get_todos_colaboradores_selecoes() -> Dict[str, List[str]]:
    """
    Mapeia user_email -> lista de documentos (dígitos), só de usuários ativos.

    O filtro por usuário ativo é a parte que faltava. Os destinatários dos
    alertas de vencimento saíam desta tabela sem nenhuma consulta a `users`:
    desativar alguém no painel não o tirava dos e-mails, e uma linha órfã —
    de conta apagada ou de identidade de serviço como `agent@internal` —
    continuava recebendo indefinidamente.

    Em 09/08/2026 havia quatro dessas em produção, duas em domínios de
    terceiros (`certguard.com`, `example.com`), recebendo nome de titular,
    CNPJ/CPF e vencimento de certificados de clientes reais. Não era acesso
    indevido a uma tela: era e-mail saindo para fora.
    """
    client = _supabase()
    if not client:
        return _so_de_ativos(_load_colaborador_file_dict())

    try:
        r = (
            client.table("colaborador_cert_selecoes")
            .select("user_id, documentos")
            .execute()
        )
        linhas = r.data or []
    except Exception as e:
        logger.warning(f"Falha ao ler seleções de colaboradores no Supabase, usando local: {e}")
        return _so_de_ativos(_load_colaborador_file_dict())

    ativas = _linhas_ativas()
    if ativas is None:
        # Consequência real do rechaveamento, e não vou escondê-la atrás de um
        # fallback que fingiria funcionar: a linha de seleção não guarda mais
        # endereço nenhum. Sem conseguir ler `users`, não há de onde tirar para
        # quem mandar — não é "não sei filtrar", é "não sei endereçar".
        #
        # Antes da fase 3c o endereço estava duplicado na própria linha, e isto
        # aqui devolvia tudo por ele. Essa redundância era exatamente o defeito
        # (endereço que envelhece junto da linha), então perdê-la é o preço, e
        # é consciente.
        #
        # ERROR, e não warning: uma rodada inteira de alertas deixa de sair. O
        # job roda por cron e tenta de novo no ciclo seguinte, mas ninguém vai
        # notar sozinho que não recebeu.
        logger.error(
            "Alertas de colaboradores não serão enviados nesta rodada: %d seleção(ões) "
            "lidas, mas `users` não respondeu e o endereço de destino só existe lá.",
            len(linhas),
        )
        return {}

    contas = _por_id(ativas)
    permitidas: Dict[str, List[str]] = {}
    descartadas: List[str] = []
    sem_identidade = 0

    for row in linhas:
        docs = row.get("documentos")
        if not isinstance(docs, list):
            continue
        uid = str(row.get("user_id") or "").strip()

        if not uid:
            # Não deveria existir: a produção foi conferida em 17/08 com 0
            # linhas assim antes de a 3c ir ao ar, e a gravação recusa criar
            # linha sem identidade. Contado em vez de ignorado — se voltar a
            # aparecer, é sinal de que algo grava por fora do código.
            sem_identidade += 1
            continue

        # `contas` traz o endereço ATUAL da pessoa. E-mail trocado depois da
        # seleção deixa de perder o destinatário — é o ganho todo.
        destino = contas.get(uid)
        if not destino:
            descartadas.append(uid)
            continue
        permitidas[destino] = [str(x).strip() for x in docs if str(x).strip()]

    if descartadas:
        logger.info(
            "Seleções ignoradas por usuário inativo ou inexistente (user_id): %s",
            ", ".join(sorted(descartadas)),
        )
    if sem_identidade:
        logger.warning(
            "%d seleção(ões) sem user_id foram ignoradas; alguém grava em "
            "colaborador_cert_selecoes por fora do portal.",
            sem_identidade,
        )
    return permitidas

def _linha_resumo(cert: Dict[str, Any], dias: int, cor: str) -> str:
    nome = html.escape(str(cert.get("nome") or cert.get("display_name") or "Sem nome"))
    doc = html.escape(str(cert.get("documento_formatado") or cert.get("documento_numero") or "—"))
    if dias < 0:
        quando = "venceu hoje" if dias == 0 else f"venceu há {abs(dias)} dias"
    elif dias == 0:
        quando = "vence hoje"
    elif dias == 1:
        quando = "vence amanhã"
    else:
        quando = f"vence em {dias} dias"
    return (
        f'<tr><td style="padding:6px 8px;border-bottom:1px solid #e5e5ea;">{nome}</td>'
        f'<td style="padding:6px 8px;border-bottom:1px solid #e5e5ea;">{doc}</td>'
        f'<td style="padding:6px 8px;border-bottom:1px solid #e5e5ea;color:{cor};'
        f'white-space:nowrap;">{quando}</td></tr>'
    )


def _enviar_resumo_admins(settings, itens: List[Dict[str, Any]], now: datetime) -> Dict[str, Any]:
    """
    Um único e-mail consolidado por administrador, por dia.

    Enviar um e-mail por certificado ao admin geraria centenas de mensagens
    (hoje seriam 519 numa base de 1.028 certificados). O resumo entrega o mesmo
    conteúdo do sino: totais, mais a lista do que ainda dá para evitar.
    """
    out = {"admin_resumos_enviados": 0, "admin_resumos_ignorados": 0}

    # Lista fixa da tela quando houver; senão, todo administrador ativo — que é
    # como sempre funcionou.
    #
    # A diferença entre as duas NÃO é cosmética. Um e-mail que pertence a uma
    # conta do portal para de receber quando a conta é desativada; um endereço
    # digitado aqui não para, porque não há conta para desativar. Em 09/08/2026
    # foram encontradas quatro linhas órfãs recebendo nome de titular, CNPJ/CPF
    # e vencimento de certificados de clientes — o mesmo conteúdo deste resumo.
    # A tela avisa disso; este comentário é para quem mexer no código depois.
    fixos = alertas_config.destinatarios_configurados(
        getattr(settings, "alertas_destinatarios", "")
    )
    admins = list(fixos) if fixos else _get_admin_emails()
    if not admins:
        return out

    marcos = alertas_config.marcos_efetivos(getattr(settings, "alertas_marcos", ""))
    janela = alertas_config.janela_dias(marcos)
    lista_fixa = bool(fixos)

    expirando, vencidos_recentes = [], []
    for it in itens:
        venc_iso = it.get("not_after")
        if not venc_iso:
            continue
        try:
            v_dt = datetime.fromisoformat(str(venc_iso).replace("Z", "+00:00"))
        except Exception:
            continue
        dias = (v_dt.date() - now.date()).days
        if v_dt >= now and 0 <= dias <= janela:
            expirando.append((it, dias))
        elif v_dt < now and abs(dias) <= janela:
            vencidos_recentes.append((it, dias))

    # Deduplica pelo mesmo critério do sino: o certificado em N arquivos é 1 item.
    def _dedup(pares):
        vistos, saida = set(), []
        for it, d in pares:
            k = it.get("fingerprint_sha256") or f"{it.get('nome')}|{it.get('not_after')}"
            if k in vistos:
                continue
            vistos.add(k)
            saida.append((it, d))
        return saida

    expirando = sorted(_dedup(expirando), key=lambda p: p[1])
    vencidos_recentes = sorted(_dedup(vencidos_recentes), key=lambda p: -p[1])

    if not expirando and not vencidos_recentes:
        logger.info("Resumo para administradores não enviado: nada dentro da janela de ação.")
        return out

    hoje = now.date().isoformat()
    linhas_venc = "".join(_linha_resumo(c, d, "#ff3b30") for c, d in vencidos_recentes)
    linhas_exp = "".join(_linha_resumo(c, d, "#b35c00") for c, d in expirando)

    def _bloco(titulo: str, linhas: str, total: int) -> str:
        if not linhas:
            return ""
        return f"""
          <h3 style="font-size:15px;margin:22px 0 8px;">{titulo} ({total})</h3>
          <table style="width:100%;border-collapse:collapse;font-size:13px;">
            <tr>
              <th style="text-align:left;padding:6px 8px;border-bottom:2px solid #e5e5ea;">Nome</th>
              <th style="text-align:left;padding:6px 8px;border-bottom:2px solid #e5e5ea;">CNPJ/CPF</th>
              <th style="text-align:left;padding:6px 8px;border-bottom:2px solid #e5e5ea;">Situação</th>
            </tr>
            {linhas}
          </table>"""

    # "Você recebe porque é administrador" vira mentira assim que existe uma
    # lista fixa — e é a única linha do e-mail que diz a quem reclamar de estar
    # recebendo. Quem está numa lista digitada precisa saber que é isso.
    motivo_do_envio = (
        "Você recebe este resumo porque seu endereço está na lista de "
        "destinatários configurada em Configuração &rsaquo; Alertas."
        if lista_fixa
        else "Você recebe este resumo porque tem perfil de administrador no portal."
    )

    html_content = f"""
    <html>
      <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color:#f5f5f7; padding:20px; color:#1d1d1f;">
        <div style="max-width:680px;margin:0 auto;background:#ffffff;border-radius:12px;padding:24px;box-shadow:0 4px 12px rgba(0,0,0,0.05);border:1px solid #e5e5ea;">
          <h2 style="margin-top:0;">Resumo de certificados</h2>
          <p style="color:#6e6e73;margin-top:0;">
            Situação em {now.strftime('%d/%m/%Y')} — {len(vencidos_recentes)} vencido(s) nos últimos
            {janela} dias e {len(expirando)} a vencer nos próximos {janela}.
          </p>
          {_bloco("Vencidos recentemente", linhas_venc, len(vencidos_recentes))}
          {_bloco("A vencer", linhas_exp, len(expirando))}
          <p style="font-size:12px;color:#86868b;margin-top:24px;margin-bottom:0;">
            {motivo_do_envio}
            Certificados vencidos há mais de {janela} dias não entram aqui —
            consulte a página Vencidos para a lista completa.
          </p>
        </div>
      </body>
    </html>
    """
    subject = (
        f"Resumo de certificados — {len(expirando)} a vencer, "
        f"{len(vencidos_recentes)} vencidos recentemente"
    )

    for admin_email in admins:
        # Chave antispam por dia: um resumo por administrador por dia, mesmo que
        # o job dispare várias vezes (reinício de worker, disparo manual).
        if _is_alert_already_sent("__resumo_admin__", f"digest:{hoje}", admin_email, hoje):
            out["admin_resumos_ignorados"] += 1
            continue
        try:
            send_smtp_email(
                host=settings.smtp_host,
                port=settings.smtp_port,
                user=settings.smtp_user,
                password_enc=settings.smtp_password_encrypted,
                use_tls=settings.smtp_use_tls,
                use_ssl=settings.smtp_use_ssl,
                from_email=settings.smtp_from_email,
                to_email=admin_email,
                subject=subject,
                html_content=html_content,
            )
            out["admin_resumos_enviados"] += 1
            _record_sent_alert("__resumo_admin__", f"digest:{hoje}", admin_email, hoje)
        except Exception as e:
            logger.error(f"Falha ao enviar resumo de administrador para {admin_email}: {e}")

    return out


def trigger_all_alerts() -> Dict[str, Any]:
    """
    Executa a varredura completa dos certificados e envia alertas aos colaboradores.
    Retorna estatísticas do processamento.
    """
    settings = load_settings()
    stats = {
        "processed_certs": 0,
        "alerts_sent": 0,
        "skipped_already_sent": 0,
        "skipped_no_recipient_email": 0,
        "errors": 0,
        "alerts_disabled": not settings.smtp_alerts_enabled,
        "smtp_configured": bool(settings.smtp_host and settings.smtp_user)
    }
    
    # 1. Se alertas estão desligados ou SMTP não está configurado, interrompe
    if not settings.smtp_alerts_enabled or not settings.smtp_host:
        logger.info("Envio de alertas ignorado (alertas desligados ou SMTP não configurado).")
        return stats

    # 2. Carrega todos os certificados do sistema
    # Tenta usar o último snapshot ou faz scan local
    from app.settings_state import get_latest_snapshot
    from app.main import _list_certificados_payload
    snap = get_latest_snapshot()
    payload = _list_certificados_payload(settings, snap, "auto")
    itens = payload.get("itens") or []
    
    # 3. Carrega seleções de colaboradores
    selecoes = _get_todos_colaboradores_selecoes()
    
    # 4. Inicia processamento
    now = datetime.now(timezone.utc)
    # Uma leitura só para o laço inteiro: os marcos não mudam no meio de uma
    # execução, e reler por certificado seriam centenas de idas ao banco.
    marcos = alertas_config.marcos_efetivos(getattr(settings, "alertas_marcos", ""))
    janela = alertas_config.janela_dias(marcos)
    for it in itens:
        stats["processed_certs"] += 1
        fingerprint = it.get("fingerprint_sha256")
        if not fingerprint:
            continue
            
        venc_iso = it.get("not_after")
        if not venc_iso:
            continue
            
        try:
            # Parsing data de validade
            v_dt = datetime.fromisoformat(venc_iso.replace("Z", "+00:00"))
        except Exception:
            continue
            
        # Determina tipo de alerta e a chave antispam.
        # Para "expiring" a chave inclui o marco (30/15/7/1), de modo que cada
        # limiar dispara um reforço. Para "expired" continua uma única chave:
        # um certificado vencido há dois anos não deve cobrar todo dia.
        dias = (v_dt.date() - now.date()).days
        tipo_alerta = None
        chave_antispam = None
        if v_dt < now:
            tipo_alerta = "expired"
            chave_antispam = "expired"
        elif 0 <= dias <= janela:
            tipo_alerta = "expiring"
            chave_antispam = f"expiring:{_marco_expiracao(dias, marcos)}"

        if not tipo_alerta:
            continue
            
        # Acha todos os destinatários monitorando este documento
        doc_digitos = "".join(c for c in (it.get("documento_numero") or "") if c.isdigit())
        if not doc_digitos:
            # Caso o CNPJ/CPF não esteja em formato puro
            doc_digitos = "".join(c for c in (it.get("documento_formatado") or "") if c.isdigit())
            
        destinatarios = []
        for email, docs in selecoes.items():
            # Limpa cada documento para comparar apenas os dígitos
            docs_clean = ["".join(c for c in d if c.isdigit()) for d in docs]
            if doc_digitos in docs_clean:
                destinatarios.append(email)
                
        # Se não há destinatários
        if not destinatarios:
            continue
            
        for dest in destinatarios:
            email_dest = dest.strip()
            if not email_dest:
                stats["skipped_no_recipient_email"] += 1
                logger.warning(f"Certificado {it.get('nome')} exige alerta mas o destinatário está sem e-mail.")
                continue
                
            # Verifica antispam
            if _is_alert_already_sent(fingerprint, chave_antispam, email_dest, venc_iso):
                stats["skipped_already_sent"] += 1
                continue

            # Prepara e-mail.
            # `nome`/`documento` vêm do CN do certificado — conteúdo controlado
            # por quem gera o .pfx. Escapado antes de entrar no HTML.
            nome_cert = html.escape(
                str(it.get("nome") or it.get("display_name") or "Certificado Digital")
            )
            doc_fmt = html.escape(
                str(it.get("documento_formatado") or it.get("documento_numero") or "Sem documento")
            )
            subject = ""
            html_content = ""
            
            if tipo_alerta == "expired":
                subject = f"⚠️ ALERTA: Certificado Vencido - {nome_cert}"
                html_content = f"""
                <html>
                  <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #f5f5f7; padding: 20px; color: #1d1d1f;">
                    <div style="max-width: 600px; margin: 0 auto; background: #ffffff; border-radius: 12px; padding: 24px; box-shadow: 0 4px 12px rgba(0,0,0,0.05); border: 1px solid #e5e5ea;">
                      <h2 style="color: #ff3b30; margin-top: 0;">⚠️ Certificado Vencido</h2>
                      <p>Olá,</p>
                      <p>Identificamos que o certificado digital que você está acompanhando venceu.</p>
                      <hr style="border: 0; border-top: 1px solid #e5e5ea; margin: 20px 0;" />
                      <table style="width: 100%; border-collapse: collapse;">
                        <tr><td style="padding: 6px 0; font-weight: 600;">Nome:</td><td>{nome_cert}</td></tr>
                        <tr><td style="padding: 6px 0; font-weight: 600;">CNPJ/CPF:</td><td>{doc_fmt}</td></tr>
                        <tr><td style="padding: 6px 0; font-weight: 600; color: #ff3b30;">Vencimento:</td><td style="color: #ff3b30;">{v_dt.strftime('%d/%m/%Y')}</td></tr>
                      </table>
                      <hr style="border: 0; border-top: 1px solid #e5e5ea; margin: 20px 0;" />
                      <p style="font-size: 13px; color: #86868b; margin-bottom: 0;">Por favor, providencie a renovação do certificado o quanto antes para evitar interrupção nos serviços.</p>
                    </div>
                  </body>
                </html>
                """
            else:
                subject = f"⏳ ALERTA: Certificado Expirando em {dias} dias - {nome_cert}"
                html_content = f"""
                <html>
                  <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #f5f5f7; padding: 20px; color: #1d1d1f;">
                    <div style="max-width: 600px; margin: 0 auto; background: #ffffff; border-radius: 12px; padding: 24px; box-shadow: 0 4px 12px rgba(0,0,0,0.05); border: 1px solid #e5e5ea;">
                      <h2 style="color: #ff9500; margin-top: 0;">⏳ Certificado Próximo ao Vencimento</h2>
                      <p>Olá,</p>
                      <p>O certificado digital que você acompanha está prestes a expirar.</p>
                      <hr style="border: 0; border-top: 1px solid #e5e5ea; margin: 20px 0;" />
                      <table style="width: 100%; border-collapse: collapse;">
                        <tr><td style="padding: 6px 0; font-weight: 600;">Nome:</td><td>{nome_cert}</td></tr>
                        <tr><td style="padding: 6px 0; font-weight: 600;">CNPJ/CPF:</td><td>{doc_fmt}</td></tr>
                        <tr><td style="padding: 6px 0; font-weight: 600; color: #ff9500;">Vencimento:</td><td style="color: #ff9500;">{v_dt.strftime('%d/%m/%Y')} ({dias} dias restantes)</td></tr>
                      </table>
                      <hr style="border: 0; border-top: 1px solid #e5e5ea; margin: 20px 0;" />
                      <p style="font-size: 13px; color: #86868b; margin-bottom: 0;">Recomendamos iniciar o processo de renovação em breve.</p>
                    </div>
                  </body>
                </html>
                """
                
            try:
                send_smtp_email(
                    host=settings.smtp_host,
                    port=settings.smtp_port,
                    user=settings.smtp_user,
                    password_enc=settings.smtp_password_encrypted,
                    use_tls=settings.smtp_use_tls,
                    use_ssl=settings.smtp_use_ssl,
                    from_email=settings.smtp_from_email,
                    to_email=email_dest,
                    subject=subject,
                    html_content=html_content
                )
                stats["alerts_sent"] += 1
                _record_sent_alert(fingerprint, chave_antispam, email_dest, venc_iso)
            except Exception as e:
                stats["errors"] += 1
                logger.error(f"Falha ao enviar e-mail de alerta para {email_dest}: {e}")

    # Resumo consolidado para administradores.
    stats.update(_enviar_resumo_admins(settings, itens, now))

    registrar_execucao_job()
    return stats
