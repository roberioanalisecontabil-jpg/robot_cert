from __future__ import annotations

import logging
import json
import os
import re
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from app import auth, config, nomes, sessao_cookie, taxa
from app.config import ROOT
from app import smtp_service
from app.alert_state import trigger_all_alerts, job_ja_executado_recentemente
from app.novos_certificados import (
    enviar_novos_pendentes,
    notificar_novos,  # noqa: F401 — testes e o modo "imediato" apontam para cá
    segundos_ate_a_proxima_hora_cheia,
)
from app.settings_state import (
    banco_configurado,
)

from app.sessao import (  # noqa: F401 — Frente 3, leva 1: reexportados para rotas e testes
    _ip_do_cliente,
    security,
    ANONYMOUS_IDENTITY_EMAIL,
    SESSAO_ENCERRADA,
    ROTAS_COM_SENHA_PROVISORIA,
    ERRO_SENHA_PROVISORIA,
    ContaIndisponivel,
    ContaInvalida,
    _conta_da_sessao,
    _senha_trocada_depois_do_token,
    _sessao_do_token,
    _sessao_encerrada_por_logout,
    _user_id_da_sessao,
    require_auth,
    PAPEIS_VALIDOS,
    PAPEIS_IMPORTAVEIS,
    require_admin,
    ERRO_ACESSO_MAQUINA,
    require_modulo,
    ERRO_MAQUINA_SEM_IDENTIDADE,
    ERRO_MAQUINA_DIVERGENTE,
    _machine_da_credencial,
    require_agent_or_admin,
    _parse_iso_utc,
    _resolve_user_id,
)
from app.alcance import (  # noqa: F401 — Frente 3, leva 3
    _papel_da_conta,
    ERRO_SEM_ALCANCE,
    _exigir_alcance,
    _papel_do_alvo,
    require_admin_ou_gestor,
    _documentos_ao_alcance,
    _marcar_instalaveis,
    _no_alcance,
    _no_cofre,
    _recortar_pela_carteira,
)
from app.comum import (  # noqa: F401 — Frente 3, leva 4: rotas e testes
    LISTAGEM_EXPORT_MAX,
    ERRO_INTERNO_VEJA_LOG,
    ERRO_LINHAS_DEMAIS,
    ERRO_UPLOAD_GRANDE,
    LIMITE_UPLOAD_BYTES,
    MAX_LINHAS_IMPORT,
    _documento_formatado,
    _ler_upload_limitado,
    _norm_header,
)

# O que se mascara no log (achado #57, lote 9): VALORES, não frases. Até aqui
# qualquer mensagem com "token", "senha" ou "password" virava
# "*** REDACTED ***" inteira — o que apagava o WARNING da X-API-Key
# compartilhada (a lista de estações não migradas) e o log de resgate
# recusado — enquanto o traceback de `exc_info` passava sem máscara nenhuma.
_MASCARA = "***"
_RE_SEGREDOS_POR_FORMA = [
    # JWT: três blocos base64url, o primeiro começando em eyJ.
    re.compile(r"eyJ[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{6,}"),
    # Depois de Bearer / Basic, o que vier.
    re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}"),
    # Cabeçalho ou campo com valor: X-API-Key: xxx, api_key=xxx, token=xxx,
    # senha=xxx, password: xxx. Mantém o nome, troca o valor.
    re.compile(r"(?i)\b(x-api-key|api[_-]?key|authorization|token|senha|password|passwd|secret)\s*[:=]\s*\S+"),
    # Cadeias longas de base64url/hex (token_urlsafe, chaves, hashes).
    re.compile(r"(?<![A-Za-z0-9_/+-])[A-Za-z0-9_-]{32,}(?![A-Za-z0-9_/+-])"),
]
# "token abc.def.ghi rejeitado": palavra-chave seguida de um valor que PARECE
# segredo (tem dígito ou pontuação de codificação). "Token de instalação
# recusado" fica inteiro: "de" e "recusado" não parecem segredo.
_RE_SEGREDO_APOS_PALAVRA = re.compile(
    r"(?i)\b(token|senha|password|chave|key)\s+(?=[A-Za-z0-9._~+/=-]{6,}(?:\s|$|[,;)]))"
    r"((?=[^\s,;)]*[0-9._~+/=-])[A-Za-z0-9._~+/=-]{6,})"
)


def redigir_segredos(texto: str) -> str:
    """Mascara valores que parecem credencial e preserva o resto da frase."""
    if not texto:
        return texto
    saida = texto
    for padrao in _RE_SEGREDOS_POR_FORMA:
        saida = padrao.sub(lambda m: (m.group(1) + " " + _MASCARA) if m.lastindex else _MASCARA, saida)
    saida = _RE_SEGREDO_APOS_PALAVRA.sub(lambda m: m.group(1) + " " + _MASCARA, saida)
    return saida


class SecureJSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        # [OWASP A09] Ocultação de segredos e geração de Log JSON estruturado para prevenir Log Injection
        log_obj = {
            # O replace preserva o sufixo "Z": isoformat() de um datetime aware
            # emite "+00:00", e concatenar "Z" daria "+00:00Z". O formato do log
            # continua byte a byte igual ao de antes.
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "message": redigir_segredos(record.getMessage()),
        }
        if record.exc_info:
            # O traceback carrega os argumentos das exceções — e uma
            # `ValueError(f"senha={senha}")` de biblioteca ia inteira para o log.
            log_obj["exc_info"] = redigir_segredos(self.formatException(record.exc_info))
        return json.dumps(log_obj)

logger = logging.getLogger(__name__)
# Configuração base de logging
_handler = logging.StreamHandler()
_handler.setFormatter(SecureJSONFormatter())
logging.root.handlers = [_handler]
logging.root.setLevel(logging.INFO)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """
    Inicialização e encerramento do portal.

    Substitui `@app.on_event("startup")`, deprecado no FastAPI. A ordem é a
    mesma de antes: criar os diretórios locais e só então subir o job de
    alertas.

    O que muda além da deprecação: o `asyncio.create_task` do laço de alertas
    não tinha contrapartida no shutdown — a task ficava pendurada e, em
    reinícios rápidos, um novo laço subia enquanto o anterior ainda dormia. O
    `finally` agora cancela e aguarda o encerramento.
    """
    import asyncio

    # Antes de qualquer outra coisa: sem a chave de cifragem da senha SMTP o
    # portal não sobe. Deliberadamente fatal — o desenho anterior derivava uma
    # chave da JWT_SECRET_KEY e seguia em frente, e a consequência (senha SMTP
    # indecifrável) só aparecia como "os alertas pararam", desligado no tempo e
    # no espaço da causa.
    #
    # ATENÇÃO AO DEPLOY: defina ENCRYPTION_KEY no painel da plataforma
    # (Vercel/Render) ANTES de publicar esta versão. O .env não sobe no deploy.
    smtp_service.verificar_chave_configurada()

    # As demais críticas, conferidas de uma vez (item 12 da Frente 2 — R9):
    # valor malformado ou faltando em produção derruba o boot AQUI, com a lista
    # inteira na mensagem, em vez de uma por vez no primeiro uso de cada rota.
    fatais, avisos = config.verificar_ambiente()
    for aviso in avisos:
        logger.warning("Ambiente: %s", aviso)
    if fatais:
        raise RuntimeError(
            "Ambiente mal configurado — corrija antes de subir:\n- " + "\n- ".join(fatais)
        )

    try:
        config.CERT_SOURCE_DIR.mkdir(parents=True, exist_ok=True)
        config.CERT_EXPIRED_DIR.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        logger.warning(f"Não foi possível criar diretórios locais (ambiente read-only / Vercel): {e}")

    # Job diário de alertas por e-mail.
    #
    # Dois problemas do desenho anterior:
    #
    # 1. `trigger_all_alerts()` é síncrona e era chamada direto no laço async.
    #    Ela faz a varredura completa dos certificados (2,5-3,3s numa base de
    #    mil) e depois N envios SMTP sequenciais — tudo isso travava o event
    #    loop, ou seja, o portal inteiro parava de responder durante o job.
    #    Agora roda em thread separada via run_in_executor.
    #
    # 2. O laço dormia 86400s, mas o Procfile usa `--max-requests 500`: o worker
    #    recicla várias vezes ao dia e o job redisparava em cada boot+60s.
    #    "Diário" nunca foi diário. O marcador em disco (job_ja_executado_
    #    recentemente) torna a cadência real, independente de reinícios.
    async def daily_alerts_job_loop():
        logger.info("Iniciando loop do job diário de alertas")
        await asyncio.sleep(60)  # Deixa o boot terminar antes do primeiro disparo
        loop = asyncio.get_running_loop()
        while True:
            try:
                if job_ja_executado_recentemente():
                    logger.info("Job de alertas ignorado: já executado nas últimas horas.")
                else:
                    logger.info("Executando job de alertas por e-mail...")
                    stats = await loop.run_in_executor(None, trigger_all_alerts)
                    logger.info(f"Job de alertas concluído: {stats}")
                    expurgo = await loop.run_in_executor(None, _expurgo_diario)
                    logger.info(f"Expurgo diário concluído: {expurgo}")
            except Exception as e:
                logger.error(f"Erro ao executar job de alertas: {e}")
            # Reavalia de hora em hora: com o marcador de última execução, o
            # trabalho real acontece uma vez por dia mesmo com ciclo curto.
            await asyncio.sleep(3600)

    # Aviso de certificados novos por hora cheia (02/10/2026): os novos que
    # cada ingestão registrou ficam guardados e saem num e-mail só na virada
    # da hora. Dorme até a próxima hora cheia, e não 3600 s a partir do boot —
    # senão "10:00" viraria "10:07" depois de um reinício às 09:07.
    async def novos_por_hora_loop():
        logger.info("Iniciando loop do aviso de certificados novos por hora cheia")
        loop = asyncio.get_running_loop()
        while True:
            try:
                await asyncio.sleep(segundos_ate_a_proxima_hora_cheia())
                stats = await loop.run_in_executor(None, enviar_novos_pendentes)
                if stats.get("certificados"):
                    logger.info(f"Aviso de certificados novos da hora: {stats}")
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"Erro no aviso de certificados novos por hora: {e}")
                await asyncio.sleep(60)

    # Carteira sincronizada pelo Acessórias (ADR 0005): 5 min das 7h às 20h,
    # 1 h no resto. Sem token no .env, não roda. A trava contra apagão e a
    # confirmação do Administrador estão em app/acessorias.py.
    async def acessorias_loop():
        if not config.ACESSORIAS_API_TOKEN:
            logger.info("Busca do Acessórias desligada: ACESSORIAS_API_TOKEN ausente.")
            return
        from app import acessorias

        loop = asyncio.get_running_loop()
        await asyncio.sleep(90)  # depois do boot e fora do primeiro disparo dos alertas
        while True:
            try:
                r = await loop.run_in_executor(None, acessorias.buscar)
                if r.get("estado") != "ok" or r.get("resumo", {}).get("entradas") or r.get("resumo", {}).get("saidas"):
                    logger.info(f"Busca do Acessórias: {r.get('estado')} {r.get('resumo') or r.get('erro') or ''}")
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"Erro na busca do Acessórias: {e}")
            await asyncio.sleep(acessorias.proxima_espera(datetime.now()))

    tarefa_alertas = asyncio.create_task(daily_alerts_job_loop())
    tarefa_novos = asyncio.create_task(novos_por_hora_loop())
    tarefa_acessorias = asyncio.create_task(acessorias_loop())
    try:
        yield
    finally:
        tarefa_novos.cancel()
        tarefa_acessorias.cancel()
        # O `await` é limitado no tempo de propósito. Esperar a task sem prazo
        # significa que qualquer falha em encerrá-la (um cancel que não chega,
        # um run_in_executor preso num envio SMTP) trava o shutdown do processo
        # para sempre — o worker não recicla e o deploy não termina. Desistir
        # depois de alguns segundos e registrar é melhor que pendurar.
        # `asyncio.wait` em vez de `wait_for` + `except CancelledError`: aquele
        # except engolia qualquer cancelamento, inclusive um dirigido ao próprio
        # lifespan por quem o encerra — o shutdown virava inignorável e a espera
        # pelo prazo cheio passava despercebida. `asyncio.wait` devolve a task
        # pendente sem levantar, e deixa passar um cancelamento externo.
        tarefa_alertas.cancel()
        _, pendentes = await asyncio.wait({tarefa_alertas, tarefa_novos, tarefa_acessorias}, timeout=5)
        if pendentes:
            logger.warning("Job de alertas não encerrou em 5s; seguindo com o shutdown.")


# A documentação só existe onde alguém a ligou (ENABLE_DOCS=1). Em produção o
# /openapi.json descrevia as ~97 rotas — nomes, parâmetros, shapes — para
# qualquer visitante anônimo, e era o único dado que uma visita sem sessão
# levava do portal. O INVENT já nascia assim; isto é a paridade.
app = FastAPI(
    title="Monitor de certificados PFX",
    version="1.2.1",
    lifespan=lifespan,
    docs_url="/docs" if config.ENABLE_DOCS else None,
    redoc_url="/redoc" if config.ENABLE_DOCS else None,
    openapi_url="/openapi.json" if config.ENABLE_DOCS else None,
)

import secrets

@app.middleware("http")
async def paginas_exigem_sessao_middleware(request: Request, call_next):
    """As páginas só abrem com sessão (Leva D, 09/10/2026).

    Registrado ANTES do de cabeçalhos de segurança para ficar por dentro dele:
    o redirecionamento também sai com CSP, HSTS etc.

    Até aqui o HTML ia para qualquer um e a cerca era um `if` no JavaScript
    (o token morava no `localStorage`, que o servidor não vê). Com a sessão no
    cookie, o servidor confere antes de entregar a página e manda ao login,
    com `next`, quem não tem sessão válida. Vale quando o portal está fechado
    (`API_KEY` configurada), a mesma regra que `require_auth` segue na API.
    """
    if (request.method in ("GET", "HEAD") and request.url.path in sessao_cookie.PAGINAS
            and config.API_KEY):
        valida = False
        token = sessao_cookie.token_do_cookie(request)
        dados = auth.decode_access_token(token) if token else None
        if dados:
            try:
                _sessao_do_token(dados)
                valida = True
            except HTTPException:
                valida = False
        if not valida:
            from urllib.parse import quote

            destino = request.url.path + (("?" + request.url.query) if request.url.query else "")
            resposta = RedirectResponse(url="/login?next=" + quote(destino, safe=""), status_code=303)
            if token:
                sessao_cookie.apagar(resposta, request)
            return resposta
    return await call_next(request)


@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    # Gera um nonce único por requisição para blindar scripts
    nonce = secrets.token_urlsafe(16)
    request.state.nonce = nonce
    
    response = await call_next(request)
    
    # [Guia Definitivo - A+ / Mozilla Observatory] Headers Críticos
    response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains; preload"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), payment=(), usb=()"
    
    # [Isolamento de Origem Cruzada - Mitigação Spectre]
    response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
    response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    
    # Permissão dev-only para o modo live do Impeccable, cujo picker de variantes
    # é servido em http://localhost:8400. Só existe quando IMPECCABLE_LIVE=1 está
    # no ambiente; a Vercel nunca define essa variável, então o header de produção
    # sai byte a byte igual ao de antes desta linha existir.
    _live = " http://localhost:8400" if os.getenv("IMPECCABLE_LIVE") == "1" else ""

    # CSP Avançado (Removido unsafe-inline/unsafe-eval de script-src e adicionado nonce)
    csp = (
        "default-src 'self'; "
        f"script-src 'self' 'nonce-{nonce}'{_live}; "
        # `connect-src` herdava de `default-src 'self'`. Declarado explicitamente
        # com o mesmo valor para receber a permissão dev acima — com `_live`
        # vazio, herdar e declarar dão exatamente o mesmo resultado.
        f"connect-src 'self'{_live}; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data:; "
        # Sem isto uma tag <base> injetada redirecionaria todos os caminhos
        # relativos (scripts, formulários) para outra origem (achado #49).
        "base-uri 'none'; "
        "object-src 'none'; "
        "form-action 'self'; "
        "frame-ancestors 'none'; "
        "block-all-mixed-content; "
        "upgrade-insecure-requests;"
    )
    response.headers["Content-Security-Policy"] = csp
    
    # Remoção de cabeçalhos de rastreamento/obsoletos
    if "X-XSS-Protection" in response.headers:
        del response.headers["X-XSS-Protection"]
    if "Server" in response.headers:
        del response.headers["Server"]
    if "X-Powered-By" in response.headers:
        del response.headers["X-Powered-By"]

    return response


@app.middleware("http")
async def hosts_permitidos_middleware(request: Request, call_next):
    """Recusa um cabeçalho Host fora de `config.HOSTS_PERMITIDOS` (achado #36).

    Lê a lista a cada requisição, e não na construção do app, para o teste
    poder trocá-la — e porque a lista vazia é a janela de compatibilidade:
    nenhum ambiente tem HOSTS_PERMITIDOS ainda, e sem ela o portal atende
    qualquer Host, como sempre atendeu (`verificar_ambiente` avisa).
    A porta é ignorada de propósito: o mesmo nome chega com e sem `:8020`.
    """
    permitidos = getattr(config, "HOSTS_PERMITIDOS", None) or []
    if permitidos:
        host = (request.headers.get("host") or "").split(":")[0].strip().lower()
        if host not in permitidos:
            return JSONResponse(status_code=400, content={"detail": "Host não atendido por este portal."})
    return await call_next(request)


# Registrado por ÚLTIMO para ser o mais externo: o teto de corpo tem de valer
# antes de qualquer outro middleware ou rota ler a requisição (auditoria de
# 10/10/2026; ver app/limite_corpo.py).
from app.limite_corpo import LimiteDeCorpo  # noqa: E402

app.add_middleware(LimiteDeCorpo)


@app.exception_handler(Exception)
async def _erro_nao_tratado(request: Request, exc: Exception) -> JSONResponse:
    """Erro inesperado sai com uma referência, nunca com o texto (achado #35).

    O texto de uma exceção traz nome de tabela, DSN, caminho de arquivo, às
    vezes o valor que falhou. A referência é o que a pessoa manda para o
    suporte, e o log a liga ao traceback inteiro.
    """
    ref = secrets.token_hex(4)
    logger.error(
        "[%s] Erro não tratado em %s %s", ref, request.method, request.url.path,
        exc_info=exc,
    )
    return JSONResponse(status_code=500, content={"detail": "Erro interno", "ref": ref})

templates = Jinja2Templates(directory=str(ROOT / "templates"))
# `{{ nome | nome_exibicao }}` nos templates: a mesma regra que a API entrega
# em `nome_exibicao`, para tela renderizada no servidor e tela montada por
# JS não divergirem no jeito de escrever um nome.
templates.env.filters["nome_exibicao"] = nomes.nome_exibicao
app.mount("/static", StaticFiles(directory=str(ROOT / "static")), name="static")


# As funções require_api_key foram removidas em favor do require_auth híbrido.


# A `pagina_ativa` acende o item correspondente em templates/_sidebar.html.
# Rota que esquecer de passa-la renderiza o menu sem nenhum item aceso - falha
# silenciosa, por isso `tests/test_sidebar_partial.py` cobre todas elas.
@app.get("/", response_class=HTMLResponse)
def painel(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "pagina_ativa": "inicio",
            # O teto vem do servidor para não existir em dois lugares. Um número
            # digitado na tela divergiria do que a rota aceita, e o sintoma seria
            # o pior dos dois: a tela deixa marcar 60, o download falha com 422.
            "max_certificados": MAX_CERTIFICADOS_POR_TOKEN,
        },
    )


@app.get("/configuracao", response_class=HTMLResponse)
def pagina_configuracao(request: Request) -> HTMLResponse:
    # As abas são links (?aba=…): sem JavaScript a página abre já na aba pedida.
    aba = request.query_params.get("aba") or "chave"
    if aba not in ("chave", "pastas", "alertas", "comandos", "sieg", "acessorias"):
        aba = "chave"
    return templates.TemplateResponse(
        request=request, name="configuracao.html", context={"pagina_ativa": "configuracao", "aba": aba}
    )


@app.get("/login", response_class=HTMLResponse)
def pagina_login(request: Request) -> HTMLResponse:
    # Sem sidebar: quem nao entrou ainda nao tem para onde navegar.
    return templates.TemplateResponse(request=request, name="login.html")


@app.get("/usuarios", response_class=HTMLResponse)
def pagina_usuarios(request: Request) -> HTMLResponse:
    # As abas são links (?aba=…): sem JavaScript a página abre já na aba pedida.
    aba = request.query_params.get("aba") or "usuarios"
    if aba not in ("usuarios", "departamentos", "permissoes", "computadores"):
        aba = "usuarios"
    return templates.TemplateResponse(
        request=request, name="usuarios.html", context={"pagina_ativa": "usuarios", "aba": aba}
    )


@app.get("/historico", response_class=HTMLResponse)
def pagina_historico(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request, name="historico.html", context={"pagina_ativa": "historico"}
    )


@app.get("/vencidos", response_class=HTMLResponse)
def pagina_vencidos(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request, name="vencidos.html", context={"pagina_ativa": "vencidos"}
    )


@app.get("/duplicidades", response_class=HTMLResponse)
def pagina_duplicidades(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request, name="duplicidades.html", context={"pagina_ativa": "duplicidades"}
    )


@app.get("/acompanhamento", response_class=HTMLResponse)
def pagina_colaborador_certificados(request: Request) -> HTMLResponse:
    # As abas são links (?aba=…): sem JavaScript a página recarrega já na
    # aba certa; com JavaScript a troca é local e a URL acompanha.
    aba = request.query_params.get("aba") or "acompanhados"
    if aba not in ("acompanhados", "escolher", "enviados"):
        aba = "acompanhados"
    return templates.TemplateResponse(
        request=request,
        name="colaborador_certificados.html",
        context={"pagina_ativa": "acompanhamento", "aba": aba},
    )


@app.get("/favicon.ico", include_in_schema=False)
def favicon() -> Response:
    """
    Serve o favicon do projeto quando disponível.
    Fallback 204 para evitar ruído de 404 no log em dev.
    """
    icon_path = ROOT / "ico" / "icone.ico"
    if icon_path.is_file():
        return FileResponse(path=icon_path, media_type="image/x-icon")
    return Response(status_code=204)


# Login/logout, Usuários, senha e LGPD: app/rotas/usuarios.py (Frente 3, leva 6).
from app.rotas.usuarios import router as _rotas_usuarios  # noqa: E402

app.include_router(_rotas_usuarios)

# App autenticador da própria conta (login em dois passos, 10/10/2026).
from app.rotas.autenticador import router as _rotas_autenticador  # noqa: E402

app.include_router(_rotas_autenticador)






# Departamentos e Níveis de acesso: app/rotas/departamentos.py (Frente 3, leva 5).
from app.rotas.departamentos import router as _rotas_departamentos  # noqa: E402

app.include_router(_rotas_departamentos)




@app.get("/api/health")
def health() -> dict:
    """Sinal de vida, e só.

    Até o lote 1 da auditoria (achado #48) esta rota pública devolvia os
    booleanos de postura do deploy — e `api_key_required: false` dizia a um
    anônimo, numa requisição, que todas as rotas /api/* aceitavam identidade
    anônima. Era o sinal mais valioso do portal para quem faz reconhecimento.
    O detalhe continua existindo, em `/api/health/detalhado`, para admin.
    """
    return {"ok": True}


@app.get("/api/health/detalhado", dependencies=[Depends(require_admin)])
def health_detalhado() -> dict:
    """
    Estado de configuração do ambiente.

    Devolve apenas BOOLEANOS de "está configurado?", nunca valores. Serve para
    conferir um deploy sem descobrir por tentativa e erro: o .env não sobe no
    deploy, então cada ambiente precisa ter suas variáveis definidas.
    `scripts/verificar_deploy.py --token` e a tela de Configuração leem daqui.
    """
    return {
        "ok": True,
        "banco": banco_configurado(),
        "api_key_required": bool(config.API_KEY),
        # Sem esta chave o cofre não funciona: /upload-pfx falha no primeiro
        # certificado que o agente tentar enviar.
        "cert_vault_key_configurada": bool(
            config.CERT_ENCRYPTION_KEY and len(config.CERT_ENCRYPTION_KEY) == 64
        ),
        # Chave da SENHA do PFX. Sem ela — ou igual à do PFX, que a aplicação
        # recusa — `upsert_pfx` levanta e /upload-pfx devolve 500. O sintoma
        # aparece longe daqui: o cofre mantém o registro antigo, sem senha, e o
        # instalador avulso falha na máquina do usuário com "o portal não
        # enviou a senha". Sem estes dois campos, descobrir isso exige ler o
        # agent.log de um servidor.
        "cert_senha_key_configurada": bool(
            config.CERT_PASSWORD_ENCRYPTION_KEY
            and len(config.CERT_PASSWORD_ENCRYPTION_KEY) == 64
        ),
        "cert_senha_key_distinta": bool(
            config.CERT_PASSWORD_ENCRYPTION_KEY
            and config.CERT_PASSWORD_ENCRYPTION_KEY != config.CERT_ENCRYPTION_KEY
        ),
        # Ausente, a chave do SMTP é derivada da JWT_SECRET_KEY — o que faz a
        # senha SMTP parar de descriptografar se a JWT diferir entre ambientes.
        "smtp_key_dedicada": bool(os.getenv("ENCRYPTION_KEY")),
        "jwt_configurado": bool(os.getenv("JWT_SECRET_KEY")),
        # O rate limit está usando o banco (vale para todas as instâncias) ou
        # degradou para a memória do processo? None = ainda não foi exercido.
        "rate_limit_persistente": taxa.estado_persistente(),
    }


# `_settings_dict` mora em app/comum.py (Frente 3, leva 7): o Instalador também o usa.


# Configuração e alertas: app/rotas/configuracao.py (Frente 3, leva 9). O
# expurgo diário volta para cá porque o `lifespan` o chama.
from app.rotas.configuracao import _expurgo_diario, router as _rotas_configuracao  # noqa: E402

app.include_router(_rotas_configuracao)


# Comandos, entrada, fila, dispositivos e credenciais de máquina do agente:
# app/rotas/agente.py (Frente 3, leva 8).
from app.rotas.agente import router as _rotas_agente  # noqa: E402

app.include_router(_rotas_agente)


# Certificados (Início, detalhes, duplicidades, histórico, vencidos, inventário
# do agente e mover vencidos): app/rotas/certificados.py (Frente 3, leva 10).
from app.rotas.certificados import router as _rotas_certificados  # noqa: E402

app.include_router(_rotas_certificados)


# SIEG: app/rotas/sieg.py (Frente 3, leva 3).
from app.rotas.sieg import router as _rotas_sieg  # noqa: E402

app.include_router(_rotas_sieg)




# Acompanhamento (seleção, painel, notificações lidas e preferência de
# alerta): app/rotas/acompanhamento.py (Frente 3, leva 11).
from app.rotas.acompanhamento import router as _rotas_acompanhamento  # noqa: E402

app.include_router(_rotas_acompanhamento)


# Instalador de certificados: app/rotas/instalador.py (Frente 3, leva 7).
from app.rotas.instalador import MAX_CERTIFICADOS_POR_TOKEN, router as _rotas_instalador  # noqa: E402

app.include_router(_rotas_instalador)




# Carteiras: app/rotas/carteiras.py (Frente 3, leva 4).
from app.rotas.carteiras import router as _rotas_carteiras  # noqa: E402

app.include_router(_rotas_carteiras)

# Carteira sincronizada pelo Acessórias: app/rotas/acessorias.py (ADR 0005).
from app.rotas.acessorias import router as _rotas_acessorias  # noqa: E402

app.include_router(_rotas_acessorias)






# Dashboard (visão geral e renovações): app/rotas/dashboard.py (Frente 3, leva 12).
from app.rotas.dashboard import router as _rotas_dashboard  # noqa: E402

app.include_router(_rotas_dashboard)

# Wiki do Certguard (tutoriais por módulo): app/rotas/wiki.py, 14/10/2026.
from app.rotas.wiki import router as _rotas_wiki  # noqa: E402

app.include_router(_rotas_wiki)


@app.get("/carteiras", response_class=HTMLResponse)
def pagina_carteiras(request: Request) -> HTMLResponse:
    # O operador selecionado viaja na URL (?operador=<id>): cada item da
    # lista é um link, e no celular a tela vira duas etapas — só a lista
    # sem operador, só o detalhe com ele — por CSS, sem depender de JS.
    operador = (request.query_params.get("operador") or "").strip()[:64]
    # Só muda o texto de abertura (ADR 0005); a regra vale nas rotas.
    try:
        from app import acessorias

        sincronizado = acessorias.sincronizado()
    except Exception:  # noqa: BLE001
        sincronizado = False
    return templates.TemplateResponse(
        request=request,
        name="carteiras.html",
        context={"pagina_ativa": "carteiras", "operador_id": operador, "sincronizado": sincronizado},
    )


@app.get("/dashboard", response_class=HTMLResponse)
def pagina_dashboard(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request, name="dashboard.html", context={"pagina_ativa": "dashboard"}
    )




# Computadores e bandeja (ADR 0002): app/rotas/computadores.py (Frente 3, leva 2).
from app.rotas.computadores import router as _rotas_computadores  # noqa: E402

app.include_router(_rotas_computadores)




# ── Página HTML do Instalador ─────────────────────────────────────────────

@app.get("/instalador", response_class=HTMLResponse)
def page_instalador(request: Request) -> HTMLResponse:
    # Assinatura por keyword, igual às outras 8 rotas de página. A forma
    # posicional antiga — TemplateResponse(name, context) — quebra nesta versão
    # do Starlette com "TypeError: unhashable type: 'dict'", e a página do
    # módulo respondia 500 em toda requisição.
    # O nonce vem de request.state.nonce no template, como nos demais.
    # As abas são links (?aba=…): sem JavaScript a página abre já na aba
    # pedida; com JavaScript a troca é local e a URL acompanha.
    aba = request.query_params.get("aba") or "diagnostico"
    if aba == "entrada":  # nome da aba até 02/10/2026; links antigos continuam valendo
        aba = "movimentos"
    if aba not in ("diagnostico", "custodia", "movimentos", "trilha", "sieg", "configuracao"):
        aba = "diagnostico"
    return templates.TemplateResponse(
        request=request, name="instalador.html", context={"pagina_ativa": "instalador", "aba": aba}
    )

