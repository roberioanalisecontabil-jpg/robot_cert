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
from app import email_modelo
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


class PreferenciaDeAlerta:
    """O que uma pessoa acompanha e como quer ser avisada.

    Nasce com o comportamento de sempre — recebe, e recebe todos os marcos —
    porque a instalação que nunca abriu a tela precisa continuar igual. Ver
    a migration 20260820200000 para o porquê do default e do "ignorados".
    """

    __slots__ = ("documentos", "notificar", "ignorados")

    def __init__(
        self,
        documentos: List[str],
        notificar: bool = True,
        ignorados: tuple = (),
    ) -> None:
        self.documentos = documentos
        self.notificar = notificar
        self.ignorados = ignorados

    def aceita_marco(self, marco: int) -> bool:
        return self.notificar and marco not in self.ignorados


def _envolver(selecoes: Dict[str, List[str]]) -> Dict[str, "PreferenciaDeAlerta"]:
    """Arquivo local não guarda preferência: tudo com o padrão de fábrica.

    É o caminho de quando não há Supabase — instalação pequena ou banco fora
    do ar. Ninguém deixa de receber por isso.
    """
    return {email: PreferenciaDeAlerta(docs) for email, docs in selecoes.items()}


def _get_selecoes_com_preferencia() -> Dict[str, "PreferenciaDeAlerta"]:
    """
    Mapeia user_email -> o que a pessoa acompanha e como quer ser avisada.

    Uma leitura só: separar a preferência numa segunda consulta dobraria as
    idas ao banco num job que já é o mais pesado do portal.

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
        return _envolver(_so_de_ativos(_load_colaborador_file_dict()))

    try:
        r = (
            client.table("colaborador_cert_selecoes")
            .select("user_id, documentos, notificar_email, alerta_marcos_ignorados")
            .execute()
        )
        linhas = r.data or []
    except Exception as e:
        logger.warning(f"Falha ao ler seleções de colaboradores no Supabase, usando local: {e}")
        return _envolver(_so_de_ativos(_load_colaborador_file_dict()))

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
        permitidas[destino] = PreferenciaDeAlerta(
            documentos=[str(x).strip() for x in docs if str(x).strip()],
            # `.get` com default: a coluna pode não existir ainda (migration
            # pendente), e ausência tem de significar o comportamento antigo.
            notificar=bool(row.get("notificar_email", True)),
            ignorados=alertas_config.marcos_ignorados(
                str(row.get("alerta_marcos_ignorados") or "")
            ),
        )

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


def _get_todos_colaboradores_selecoes() -> Dict[str, List[str]]:
    """Só os documentos, para quem não se importa com a preferência."""
    return {
        email: pref.documentos
        for email, pref in _get_selecoes_com_preferencia().items()
    }


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


def _dedup_por_certificado(pares):
    """O certificado em N arquivos vira 1 item — mesmo critério do sino."""
    vistos, saida = set(), []
    for it, d in pares:
        k = it.get("fingerprint_sha256") or f"{it.get('nome')}|{it.get('not_after')}"
        if k in vistos:
            continue
        vistos.add(k)
        saida.append((it, d))
    return saida


def _separar_por_situacao(itens, now: datetime, janela: int):
    """Divide em (a vencer, vencidos recentes), já deduplicado e ordenado."""
    expirando, vencidos = [], []
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
            vencidos.append((it, dias))
    return (
        sorted(_dedup_por_certificado(expirando), key=lambda p: p[1]),
        sorted(_dedup_por_certificado(vencidos), key=lambda p: -p[1]),
    )


def _montar_resumo(expirando, vencidos, now: datetime, janela: int, motivo: str,
                   modelo: Optional[Dict[str, str]] = None):
    """(assunto, html) do resumo — o mesmo para o admin e para o colaborador.

    Estava dentro de `_enviar_resumo_admins`, e foi de lá que veio a diferença
    de tratamento que aquele commit corrigiu: o admin recebia UM e-mail com tudo,
    e o colaborador recebia UM POR CERTIFICADO. Não por decisão de desenho —
    porque o código que agrupa morava num lugar onde só o admin passava.

    A moldura (assunto, título, abertura, recado) vem de `modelo`, que a tela
    edita. `modelo=None` são os padrões, e os padrões são o texto que estava
    escrito aqui antes — quem nunca abriu o modal recebe o mesmo e-mail.

    O que NÃO vem do modelo: as tabelas, que são o inventário do dia, e o
    `motivo`, que é a única linha dizendo a quem recebeu por que recebeu e onde
    parar de receber.
    """
    modelo = modelo or {}
    valores = {
        "data": now.strftime("%d/%m/%Y"),
        "a_vencer": len(expirando),
        "vencidos": len(vencidos),
        "janela": janela,
    }
    titulo = email_modelo.bloco_html("titulo", modelo.get("titulo"), valores)
    abertura = email_modelo.bloco_html("abertura", modelo.get("abertura"), valores)
    recado = email_modelo.bloco_html("recado", modelo.get("recado"), valores)

    linhas_venc = "".join(_linha_resumo(c, d, "#ff3b30") for c, d in vencidos)
    linhas_exp = "".join(_linha_resumo(c, d, "#b35c00") for c, d in expirando)

    def _bloco(titulo_bloco: str, linhas: str, total: int) -> str:
        if not linhas:
            return ""
        return f"""
          <h3 style="font-size:15px;margin:22px 0 8px;">{titulo_bloco} ({total})</h3>
          <table style="width:100%;border-collapse:collapse;font-size:13px;">
            <tr>
              <th style="text-align:left;padding:6px 8px;border-bottom:2px solid #e5e5ea;">Nome</th>
              <th style="text-align:left;padding:6px 8px;border-bottom:2px solid #e5e5ea;">CNPJ/CPF</th>
              <th style="text-align:left;padding:6px 8px;border-bottom:2px solid #e5e5ea;">Situação</th>
            </tr>
            {linhas}
          </table>"""

    html_content = f"""
    <html>
      <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color:#f5f5f7; padding:20px; color:#1d1d1f;">
        <div style="max-width:680px;margin:0 auto;background:#ffffff;border-radius:12px;padding:24px;box-shadow:0 4px 12px rgba(0,0,0,0.05);border:1px solid #e5e5ea;">
          <h2 style="margin-top:0;">{titulo}</h2>
          <p style="color:#6e6e73;margin-top:0;">{abertura}</p>
          {_bloco("Vencidos recentemente", linhas_venc, len(vencidos))}
          {_bloco("A vencer", linhas_exp, len(expirando))}
          <p style="font-size:12px;color:#86868b;margin-top:24px;margin-bottom:0;">
            {recado}
          </p>
          <p style="font-size:12px;color:#86868b;margin-top:8px;margin-bottom:0;">
            {motivo}
          </p>
        </div>
      </body>
    </html>
    """
    subject = email_modelo.assunto_final(modelo.get("assunto"), valores)
    return subject, html_content


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

    expirando, vencidos_recentes = _separar_por_situacao(itens, now, janela)

    if not expirando and not vencidos_recentes:
        logger.info("Resumo para administradores não enviado: nada dentro da janela de ação.")
        return out

    hoje = now.date().isoformat()

    # "Você recebe porque é administrador" vira mentira assim que existe uma
    # lista fixa — e é a única linha do e-mail que diz a quem reclamar de estar
    # recebendo. Quem está numa lista digitada precisa saber que é isso.
    motivo_do_envio = (
        "Você recebe este resumo porque seu endereço está na lista de "
        "destinatários configurada em Configuração &rsaquo; Alertas."
        if lista_fixa
        else "Você recebe este resumo porque tem perfil de administrador no portal."
    )
    subject, html_content = _montar_resumo(
        expirando, vencidos_recentes, now, janela, motivo_do_envio,
        email_modelo.do_settings(settings)
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
        "skipped_optout": 0,
        "skipped_marco_dispensado": 0,
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
    selecoes = _get_selecoes_com_preferencia()
    
    # 4. Inicia processamento
    now = datetime.now(timezone.utc)
    # Uma leitura só para o laço inteiro: os marcos não mudam no meio de uma
    # execução, e reler por certificado seriam centenas de idas ao banco.
    marcos = alertas_config.marcos_efetivos(getattr(settings, "alertas_marcos", ""))
    janela = alertas_config.janela_dias(marcos)
    # ── O que sai para cada pessoa ─────────────────────────────────────────
    #
    # Antes: um e-mail POR CERTIFICADO. Quem acompanha 12 e via todos cruzarem
    # os 30 dias no mesmo dia recebia 12 mensagens — enquanto o administrador,
    # desde 09/08, recebe UMA com tudo. Não era decisão de desenho: o código
    # que agrupa morava dentro do resumo dos admins, e o colaborador não
    # passava por lá.
    #
    # A chave do antispam continua sendo por (certificado, marco, destinatário):
    # o agrupamento muda quantos e-mails saem, não o que faz um aviso repetir.
    # Um resumo é enviado quando há pelo menos um par ainda não avisado, e
    # TODOS os pares daquele resumo são marcados de uma vez.
    pendentes: Dict[str, List[tuple]] = {}

    for it in itens:
        stats["processed_certs"] += 1
        fingerprint = it.get("fingerprint_sha256")
        if not fingerprint:
            continue

        venc_iso = it.get("not_after")
        if not venc_iso:
            continue

        try:
            v_dt = datetime.fromisoformat(venc_iso.replace("Z", "+00:00"))
        except Exception:
            continue

        # Determina o marco e a chave antispam.
        # Para "expiring" a chave inclui o marco, de modo que cada limiar
        # dispara um reforço. Para "expired" continua uma única chave: um
        # certificado vencido há dois anos não deve cobrar todo dia.
        dias = (v_dt.date() - now.date()).days
        if v_dt < now:
            marco = 0  # "vencido" não é um marco de antecedência
            chave_antispam = "expired"
        elif 0 <= dias <= janela:
            marco = _marco_expiracao(dias, marcos)
            chave_antispam = f"expiring:{marco}"
        else:
            continue

        doc_digitos = "".join(c for c in (it.get("documento_numero") or "") if c.isdigit())
        if not doc_digitos:
            doc_digitos = "".join(c for c in (it.get("documento_formatado") or "") if c.isdigit())

        for email, pref in selecoes.items():
            email_dest = (email or "").strip()
            if not email_dest:
                stats["skipped_no_recipient_email"] += 1
                continue

            docs_clean = ["".join(c for c in d if c.isdigit()) for d in pref.documentos]
            if doc_digitos not in docs_clean:
                continue

            # Preferência da pessoa. O vencido (marco 0) só depende do opt-in:
            # dispensar o aviso de "faltam 15 dias" é razoável, e nunca saber
            # que venceu é outra coisa — quem não quiser nada desliga tudo.
            if not pref.notificar:
                stats["skipped_optout"] += 1
                continue
            if marco and marco in pref.ignorados:
                stats["skipped_marco_dispensado"] += 1
                continue

            if _is_alert_already_sent(fingerprint, chave_antispam, email_dest, venc_iso):
                stats["skipped_already_sent"] += 1
                continue

            pendentes.setdefault(email_dest, []).append(
                (it, dias, fingerprint, chave_antispam, venc_iso)
            )

    # ── Um resumo por pessoa ───────────────────────────────────────────────
    for email_dest, pares in pendentes.items():
        expirando, vencidos = _separar_por_situacao([p[0] for p in pares], now, janela)
        if not expirando and not vencidos:
            continue

        subject, html_content = _montar_resumo(
            expirando,
            vencidos,
            now,
            janela,
            "Você recebe este resumo pelos certificados que escolheu acompanhar. "
            "Para mudar isso, use a página Acompanhamento do portal.",
            email_modelo.do_settings(settings),
        )
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
                html_content=html_content,
            )
            stats["alerts_sent"] += 1
            # Só depois do envio bem-sucedido: marcar antes faria uma falha de
            # SMTP silenciar aquele certificado até o próximo marco.
            for _it, _dias, fp, chave, venc in pares:
                _record_sent_alert(fp, chave, email_dest, venc)
        except Exception as e:
            stats["errors"] += 1
            logger.error(f"Falha ao enviar resumo de alerta para {email_dest}: {e}")

    # Resumo consolidado para administradores.
    stats.update(_enviar_resumo_admins(settings, itens, now))

    registrar_execucao_job()
    return stats


# ══════════════════════════════════════════════════════════════════════════
# Prévia para a tela
# ══════════════════════════════════════════════════════════════════════════

def _linhas_de_exemplo(now: datetime):
    """Três certificados fictícios, para a prévia quando a janela está vazia.

    Sem eles, quem tem a base em dia abre o modal, vê um e-mail sem tabela
    nenhuma e conclui que quebrou alguma coisa. O `exemplo: True` no retorno
    existe para a tela poder dizer que estes nomes não são reais — prévia com
    dado inventado e sem aviso é pior que prévia vazia.
    """
    def _falso(nome: str, doc: str, dias: int) -> Dict[str, Any]:
        return {
            "nome": nome,
            "documento_formatado": doc,
            "not_after": (now + timedelta(days=dias)).isoformat(),
        }

    expirando = [
        (_falso("EMPRESA EXEMPLO LTDA", "12.345.678/0001-90", 3), 3),
        (_falso("COMERCIO MODELO ME", "98.765.432/0001-10", 12), 12),
    ]
    vencidos = [(_falso("SERVICOS ANTIGOS SA", "11.222.333/0001-44", -4), -4)]
    return expirando, vencidos


def previa_do_resumo(settings, modelo: Optional[Dict[str, str]] = None,
                     now: Optional[datetime] = None) -> Dict[str, Any]:
    """O e-mail que sairia AGORA com este texto.

    Monta pela mesma `_montar_resumo` que o job usa, e não por um caminho
    paralelo. Uma prévia com código próprio concorda com o envio no dia em que
    é escrita e diverge na primeira mudança de um lado só — e prévia que diverge
    do que é enviado é pior que nenhuma, porque é acreditada.

    Nunca levanta por causa do inventário: base indisponível vira exemplo, e a
    pessoa continua conseguindo julgar o texto que escreveu.
    """
    now = now or datetime.now(timezone.utc)
    marcos = alertas_config.marcos_efetivos(getattr(settings, "alertas_marcos", ""))
    janela = alertas_config.janela_dias(marcos)

    itens: List[Dict[str, Any]] = []
    try:
        from app.settings_state import get_latest_snapshot
        from app.main import _list_certificados_payload
        payload = _list_certificados_payload(settings, get_latest_snapshot(), "auto")
        itens = list(payload.get("itens") or [])
    except Exception:  # noqa: BLE001
        logger.exception("Prévia do e-mail: inventário indisponível; usando exemplo")

    expirando, vencidos = _separar_por_situacao(itens, now, janela)
    exemplo = not expirando and not vencidos
    if exemplo:
        expirando, vencidos = _linhas_de_exemplo(now)

    assunto, corpo = _montar_resumo(
        expirando, vencidos, now, janela,
        "Você recebe este resumo porque tem perfil de administrador no portal.",
        modelo,
    )
    return {
        "assunto": assunto,
        "html": corpo,
        "exemplo": exemplo,
        "a_vencer": len(expirando),
        "vencidos": len(vencidos),
        "janela": janela,
    }
