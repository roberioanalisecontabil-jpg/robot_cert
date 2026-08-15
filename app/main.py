from __future__ import annotations

import logging
import csv
import io
import json
import os
import re
import threading
import time
import unicodedata
from collections import defaultdict
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

from fastapi import Depends, FastAPI, File, Header, HTTPException, Query, Request, UploadFile, BackgroundTasks
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app import auth, config
from app.historico_agg_cache import get_or_build as _historico_cache_get_or_build
from app.cert_scanner import CertInfo, CertStatus, cert_to_public_dict, move_to_expired, scan_folder
from app.command_queue import COMMANDS, enqueue, list_pending, pop_next_for_agent
from app.config import ROOT
from app import smtp_service
from app.smtp_service import encrypt_password, validate_smtp_config
from app.alert_state import trigger_all_alerts, job_ja_executado_recentemente
from app.notification_service import build_notifications_payload
from app.settings_state import (
    PortalSettings,
    get_latest_snapshot,
    load_colaborador_selecao,
    load_settings,
    save_colaborador_selecao,
    save_settings,
    save_snapshot,
    supabase_configured,
    upsert_cert_history,
)

security = HTTPBearer(auto_error=False)

# Identidade atribuída quando API_KEY não está configurada (ambiente aberto).
# Rotas sensíveis devem recusá-la — é o oposto de "autenticado".
ANONYMOUS_IDENTITY_EMAIL = "anonymous@local"

async def require_auth(
    auth_creds: Optional[HTTPAuthorizationCredentials] = Depends(security),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
) -> auth.TokenData:
    """
    Dependência híbrida:
    1. Se houver Token JWT (Navegador), valida o usuário.
    2. Se houver X-API-Key (Agente Windows), valida a chave estática.
    """
    # 1. Tentar JWT
    if auth_creds:
        token_data = auth.decode_access_token(auth_creds.credentials)
        if token_data:
            return token_data
    
    # 2. Se API_KEY estiver ativa, aceitar a chave estática para o agente.
    if config.API_KEY:
        if x_api_key and x_api_key == config.API_KEY:
            return auth.TokenData(email="agent@internal", role="agent")
    else:
        # Ambiente aberto (sem API_KEY): mantém compatibilidade para rotas /api/*
        # que usam require_auth, sem elevar privilégios administrativos.
        # ATENÇÃO: esta identidade é anônima. Rotas que manipulam material
        # criptográfico devem recusá-la — ver require_agent_or_admin.
        return auth.TokenData(email=ANONYMOUS_IDENTITY_EMAIL, role="agent")

    raise HTTPException(
        status_code=401, 
        detail="Não autorizado. Faça login ou forneça uma chave de API válida.",
        headers={"WWW-Authenticate": "Bearer"},
    )

async def require_admin(token: auth.TokenData = Depends(require_auth)) -> auth.TokenData:
    if token.role != "admin":
        raise HTTPException(status_code=403, detail="Acesso restrito a administradores.")
    return token


ERRO_ACESSO_MAQUINA = "Acesso restrito ao agente e a administradores."


async def require_agent_or_admin(token: auth.TokenData = Depends(require_auth)) -> auth.TokenData:
    """
    Endpoints da máquina: alimentados pelo agente (X-API-Key -> role 'agent') e
    acessíveis a administradores para diagnóstico.

    Existe porque `require_auth` sozinho é permissivo demais para estas rotas.

    1. Aceita qualquer usuário do portal, inclusive role 'user'. Em /upload-pfx
       isso permitia a um usuário comum enviar um PFX próprio reaproveitando o
       fingerprint de um certificado já armazenado: como `upsert_pfx` usa
       `on_conflict="fingerprint"`, o registro legítimo seria sobrescrito e o
       certificado do atacante acabaria instalado num servidor pelo fluxo
       normal de instalação. `require_admin` não serve como alternativa: o
       agente tem role 'agent', não 'admin'.

    2. Quando API_KEY não está configurada, `require_auth` devolve uma
       identidade ANÔNIMA com role 'agent' para manter compatibilidade. Para as
       rotas antigas isso é aceitável; para estas, que entregam PFX e senhas,
       significaria acesso sem credencial nenhuma. Aqui a identidade anônima é
       recusada explicitamente.
    """
    if token.role not in ("agent", "admin") or token.email == ANONYMOUS_IDENTITY_EMAIL:
        raise HTTPException(status_code=403, detail=ERRO_ACESSO_MAQUINA)
    return token

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
            "message": record.getMessage(),
        }
        # Filtrar possíveis senhas ou tokens da mensagem bruta
        msg_lower = log_obj["message"].lower()
        if "password" in msg_lower or "token" in msg_lower or "senha" in msg_lower:
            log_obj["message"] = "*** REDACTED SENSITIVE DATA ***"
            
        if record.exc_info:
            log_obj["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(log_obj)

logger = logging.getLogger(__name__)
# Configuração base de logging
_handler = logging.StreamHandler()
_handler.setFormatter(SecureJSONFormatter())
logging.root.handlers = [_handler]
logging.root.setLevel(logging.INFO)

LISTAGEM_EXPORT_MAX = 5000

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
            except Exception as e:
                logger.error(f"Erro ao executar job de alertas: {e}")
            # Reavalia de hora em hora: com o marcador de última execução, o
            # trabalho real acontece uma vez por dia mesmo com ciclo curto.
            await asyncio.sleep(3600)

    tarefa_alertas = asyncio.create_task(daily_alerts_job_loop())
    try:
        yield
    finally:
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
        _, pendentes = await asyncio.wait({tarefa_alertas}, timeout=5)
        if pendentes:
            logger.warning("Job de alertas não encerrou em 5s; seguindo com o shutdown.")


app = FastAPI(title="Monitor de certificados PFX", version="1.2.1", lifespan=lifespan)

import secrets

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
    
    # CSP Avançado (Removido unsafe-inline/unsafe-eval de script-src e adicionado nonce)
    csp = (
        "default-src 'self'; "
        f"script-src 'self' 'nonce-{nonce}'; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data:; "
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

templates = Jinja2Templates(directory=str(ROOT / "templates"))
app.mount("/static", StaticFiles(directory=str(ROOT / "static")), name="static")


# As funções require_api_key foram removidas em favor do require_auth híbrido.


def _painel_busca_normalizada(value: Any) -> str:
    """Mesma ideia que `normalizarTexto` no dashboard (minúsculas, sem acentos)."""
    t = str(value or "").lower()
    t = unicodedata.normalize("NFD", t)
    return "".join(ch for ch in t if unicodedata.category(ch) != "Mn")


def _enrich_cert_item_dashboard_flags(it: dict, now: datetime, thirty_days: datetime) -> dict:
    """Alinha com o painel: vencido pela data `not_after` mesmo que `status` ainda seja ok."""
    row = dict(it)
    expired_by_date = False
    expiring_soon = False
    na = row.get("not_after")
    if na:
        exp = _parse_iso_utc(str(na))
        min_dt = datetime.min.replace(tzinfo=timezone.utc)
        if exp > min_dt:
            if exp < now:
                expired_by_date = True
            elif exp <= thirty_days and exp >= now:
                expiring_soon = True
    row["_isExpiredByDate"] = expired_by_date
    row["_isExpiringSoon"] = expiring_soon
    return row


def _dashboard_filtro_status_match(row: dict, filtro: str) -> bool:
    s = str(row.get("status") or "").lower()
    ed = bool(row.get("_isExpiredByDate"))
    es = bool(row.get("_isExpiringSoon"))
    f = (filtro or "todos").strip().lower()
    if f in ("todos", ""):
        return True
    if f == "validos":
        return s == "ok" and not ed and not es
    if f in ("prestes_vencer", "prestes a vencer"):
        return s == "ok" and es and not ed
    if f == "vencidos":
        return s == "expirado" or ed
    if f in ("erros", "erro"):
        return s == "erro"
    if f in ("sem_padrao", "fora_do_padrao"):
        return s == "fora_do_padrao"
    return True


def _dashboard_busca_match(row: dict, q_raw: str) -> bool:
    if not str(q_raw or "").strip():
        return True
    raw = str(q_raw).strip()
    bt = _painel_busca_normalizada(raw)
    bd = re.sub(r"\D", "", raw)
    nome = _painel_busca_normalizada(row.get("nome") or row.get("display_name") or "")
    doc_f = _painel_busca_normalizada(row.get("documento_formatado") or "")
    doc_n = _painel_busca_normalizada(row.get("documento_numero") or "")
    fn = _painel_busca_normalizada(row.get("file_name") or "")
    na_txt = _painel_busca_normalizada(row.get("not_after") or "")
    dd = _digits_only_doc(row.get("documento_numero") or row.get("documento_formatado"))
    nd = _digits_only_doc(str(row.get("not_after") or ""))
    if bt and bt in nome:
        return True
    if bt and bt in doc_f:
        return True
    if bt and bt in doc_n:
        return True
    if bt and bt in fn:
        return True
    if bt and bt in na_txt:
        return True
    if bd and bd in dd:
        return True
    if bd and bd in nd:
        return True
    return False


def _dashboard_resumo_counts(rows: List[dict]) -> dict[str, int]:
    total = len(rows)
    validos = expirando = erros = vencidos = sem_padrao = 0
    for it in rows:
        s = str(it.get("status") or "").lower()
        ed = bool(it.get("_isExpiredByDate"))
        es = bool(it.get("_isExpiringSoon"))
        if s == "erro":
            erros += 1
        elif s == "fora_do_padrao":
            sem_padrao += 1
        elif s == "expirado" or ed:
            vencidos += 1
        elif s == "ok":
            if es:
                expirando += 1
            else:
                validos += 1
    return {
        "total": total,
        "validos": validos,
        "expirando": expirando,
        "erros": erros,
        "vencidos": vencidos,
        "sem_padrao": sem_padrao,
    }


def _list_certificados_payload(
    sets: PortalSettings,
    snap: Optional[dict],
    fonte: str,
) -> dict[str, Any]:
    """Monta o payload base (sem paginação) para GET /api/certificados."""
    if fonte == "local":
        src = sets.effective_source()
        exp = sets.effective_expired()
        itens: List[CertInfo] = scan_folder(src)
        return {
            "source_dir": str(src),
            "expired_dir": str(exp),
            "atualizado_em": datetime.now(timezone.utc).isoformat(),
            "itens": [cert_to_public_dict(c) for c in itens],
            "data_source": "local",
            "machine_id": sets.machine_id,
        }
    if fonte == "remoto":
        if not snap:
            raise HTTPException(
                status_code=404,
                detail="Nenhum dado remoto. Configure o agente no Windows para enviar leituras.",
            )
        return {
            "source_dir": str(snap.get("source_folder", "") or ""),
            "expired_dir": str(snap.get("expired_folder", "") or ""),
            "atualizado_em": snap.get("scanned_at", datetime.now(timezone.utc).isoformat()),
            "itens": list(snap.get("items", []) or []),
            "data_source": "remoto",
            "machine_id": snap.get("machine_id"),
        }
    # auto
    if snap:
        return {
            "source_dir": str(snap.get("source_folder", "") or ""),
            "expired_dir": str(snap.get("expired_folder", "") or ""),
            "atualizado_em": snap.get("scanned_at", datetime.now(timezone.utc).isoformat()),
            "itens": list(snap.get("items", []) or []),
            "data_source": "remoto",
            "machine_id": snap.get("machine_id"),
        }
    src = sets.effective_source()
    exp = sets.effective_expired()
    itens_scan: List[CertInfo] = scan_folder(src)
    return {
        "source_dir": str(src),
        "expired_dir": str(exp),
        "atualizado_em": datetime.now(timezone.utc).isoformat(),
        "itens": [cert_to_public_dict(c) for c in itens_scan],
        "data_source": "local",
        "machine_id": sets.machine_id,
    }


class SettingsBody(BaseModel):
    source_folder: str = Field(default="", description="Pasta de certificados no Windows (caminho completo)")
    expired_folder: str = Field(default="", description="Pasta destino dos vencidos")
    machine_id: str = Field(default="default", description="Identificador lógico da máquina / agente")
    smtp_host: str = Field(default="")
    smtp_port: int = Field(default=587)
    smtp_user: str = Field(default="")
    smtp_password: Optional[str] = Field(default=None)
    smtp_use_tls: bool = Field(default=True)
    smtp_use_ssl: bool = Field(default=False)
    smtp_from_email: str = Field(default="")
    smtp_alerts_enabled: bool = Field(default=False)


class IngestBody(BaseModel):
    machine_id: str = "default"
    source_folder: str
    expired_folder: str
    items: List[dict] = Field(default_factory=list)
    scanned_at: Optional[str] = None


class EnqueueCommandBody(BaseModel):
    machine_id: str = "default"
    command: str = Field(..., description="mover_vencidos | rescan | ping")


# A `pagina_ativa` acende o item correspondente em templates/_sidebar.html.
# Rota que esquecer de passa-la renderiza o menu sem nenhum item aceso - falha
# silenciosa, por isso `tests/test_sidebar_partial.py` cobre todas elas.
@app.get("/", response_class=HTMLResponse)
def painel(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request, name="index.html", context={"pagina_ativa": "inicio"}
    )


@app.get("/configuracao", response_class=HTMLResponse)
def pagina_configuracao(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request, name="configuracao.html", context={"pagina_ativa": "configuracao"}
    )


@app.get("/login", response_class=HTMLResponse)
def pagina_login(request: Request) -> HTMLResponse:
    # Sem sidebar: quem nao entrou ainda nao tem para onde navegar.
    return templates.TemplateResponse(request=request, name="login.html")


@app.get("/usuarios", response_class=HTMLResponse)
def pagina_usuarios(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request, name="usuarios.html", context={"pagina_ativa": "usuarios"}
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
    return templates.TemplateResponse(
        request=request, name="colaborador_certificados.html", context={"pagina_ativa": "acompanhamento"}
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


class LoginBody(BaseModel):
    email: str
    password: str


@app.post("/api/login")
def login(body: LoginBody) -> dict:
    load_settings()  # trigger client init
    from app.settings_state import _supabase
    sb = _supabase()
    if not sb:
        raise HTTPException(status_code=503, detail="Sistema sem Supabase configurado para login.")

    try:
        r = sb.table("users").select("*").eq("email", body.email).limit(1).execute()
        user = r.data[0] if r.data else None
        if not user or not auth.verify_password(body.password, user["password_hash"]):
            raise HTTPException(status_code=401, detail="E-mail ou senha incorretos.")
        if (user.get("role") or "").strip().lower() == "disabled":
            raise HTTPException(status_code=403, detail="Usuário desativado. Procure um administrador.")
        
        token = auth.create_access_token({"sub": user["email"], "role": user["role"]})
        return {"access_token": token, "token_type": "bearer", "role": user["role"]}
    except Exception as e:
        logger.exception("Erro no login")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/users", dependencies=[Depends(require_admin)])
def list_users() -> List[dict]:
    from app.settings_state import _supabase
    sb = _supabase()
    if not sb: return []
    r = sb.table("users").select("id, email, full_name, role, created_at").execute()
    return r.data


class UserCreateBody(BaseModel):
    email: str
    password: str
    full_name: str
    role: str = "user"


class UserUpdateBody(BaseModel):
    email: str
    full_name: str
    role: str = "user"


class UserResetPasswordBody(BaseModel):
    password: str


def _norm_header(v: str) -> str:
    s = unicodedata.normalize("NFD", str(v or "").strip().lower())
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
    return s


@app.post("/api/users/import", dependencies=[Depends(require_admin)])
async def import_users(file: UploadFile = File(...)) -> dict:
    from app.settings_state import _supabase

    sb = _supabase()
    if not sb:
        raise HTTPException(status_code=503, detail="Sistema sem Supabase configurado.")

    name = (file.filename or "").lower()
    if not name.endswith(".csv"):
        raise HTTPException(
            status_code=422,
            detail="Formato inválido. Exporte a planilha como CSV e envie um arquivo .csv.",
        )

    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=422, detail="Arquivo vazio.")
        
    # [OWASP A08] Validação de Limite de Tamanho
    if len(raw) > 5 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Arquivo muito grande (limite de 5MB).")
        
    # [OWASP A08] Validação de Magic Bytes (Assinatura real do arquivo)
    # Rejeita ativamente se for um binário executável ou arquivo restrito disfarçado de CSV
    if raw.startswith(b'MZ') or raw.startswith(b'\x7fELF') or raw.startswith(b'%PDF') or raw.startswith(b'PK'):
        raise HTTPException(status_code=422, detail="Conteúdo do arquivo suspeito. Apenas texto puro (CSV) é permitido.")

    text = raw.decode("utf-8-sig", errors="replace")
    sniffer = csv.Sniffer()
    try:
        dialect = sniffer.sniff(text[:2048], delimiters=",;")
        delim = dialect.delimiter
    except csv.Error:
        delim = ";"

    reader = csv.DictReader(io.StringIO(text), delimiter=delim)
    if not reader.fieldnames:
        raise HTTPException(status_code=422, detail="CSV sem cabeçalho.")

    map_headers = {_norm_header(h): h for h in reader.fieldnames}

    def pick(*aliases: str) -> Optional[str]:
        for a in aliases:
            key = map_headers.get(_norm_header(a))
            if key:
                return key
        return None

    h_nome = pick("nome", "full_name", "nome completo")
    h_email = pick("email", "e-mail")
    h_senha = pick("senha", "password")
    h_role = pick("role", "nivel", "papel", "perfil")
    if not h_nome or not h_email or not h_senha:
        raise HTTPException(
            status_code=422,
            detail="Cabeçalho obrigatório: nome, email, senha.",
        )
    if not h_role:
        raise HTTPException(
            status_code=422,
            detail="Cabeçalho obrigatório também para nível: use 'nivel' ou 'role' com valores 'admin' ou 'user'.",
        )

    criados = 0
    ignorados = 0
    erros: List[dict[str, Any]] = []
    linha = 1
    for row in reader:
        linha += 1
        nome = str(row.get(h_nome) or "").strip()
        email = str(row.get(h_email) or "").strip().lower()
        senha = str(row.get(h_senha) or "").strip()
        role = str(row.get(h_role) or "").strip().lower()

        if not nome or not email or not senha or not role:
            ignorados += 1
            continue
        if role not in ("admin", "user"):
            erros.append(
                {
                    "linha": linha,
                    "email": email,
                    "erro": "Nível inválido. Use exatamente 'admin' ou 'user'.",
                }
            )
            continue
        if len(senha) < 6:
            erros.append({"linha": linha, "email": email, "erro": "Senha deve ter no mínimo 6 caracteres."})
            continue
        try:
            existe = sb.table("users").select("id").eq("email", email).limit(1).execute()
            if existe.data:
                ignorados += 1
                continue
            sb.table("users").insert(
                {
                    "email": email,
                    "password_hash": auth.get_password_hash(senha),
                    "full_name": nome,
                    "role": role,
                }
            ).execute()
            criados += 1
        except Exception as e:  # noqa: BLE001
            erros.append({"linha": linha, "email": email, "erro": str(e)})

    return {"ok": True, "criados": criados, "ignorados": ignorados, "erros": erros}


@app.post("/api/users", dependencies=[Depends(require_admin)])
def create_user(body: UserCreateBody) -> dict:
    from app.settings_state import _supabase
    sb = _supabase()
    if not sb: raise HTTPException(status_code=503)
    
    hash_pw = auth.get_password_hash(body.password)
    try:
        sb.table("users").insert({
            "email": body.email,
            "password_hash": hash_pw,
            "full_name": body.full_name,
            "role": body.role
        }).execute()
        return {"ok": True}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.put("/api/users/{user_id}", dependencies=[Depends(require_admin)])
def update_user(user_id: str, body: UserUpdateBody) -> dict:
    from app.settings_state import _supabase
    sb = _supabase()
    if not sb:
        raise HTTPException(status_code=503)
    role = (body.role or "user").strip().lower()
    if role not in ("admin", "user", "disabled"):
        raise HTTPException(status_code=422, detail="Nível inválido. Use: admin, user ou disabled.")
    try:
        sb.table("users").update(
            {
                "email": body.email.strip().lower(),
                "full_name": body.full_name.strip(),
                "role": role,
            }
        ).eq("id", user_id).execute()
        return {"ok": True}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/users/{user_id}/reset-password", dependencies=[Depends(require_admin)])
def reset_user_password(user_id: str, body: UserResetPasswordBody) -> dict:
    from app.settings_state import _supabase
    sb = _supabase()
    if not sb:
        raise HTTPException(status_code=503)
    new_pw = (body.password or "").strip()
    if len(new_pw) < 6:
        raise HTTPException(status_code=422, detail="Senha deve ter no mínimo 6 caracteres.")
    hash_pw = auth.get_password_hash(new_pw)
    try:
        sb.table("users").update({"password_hash": hash_pw}).eq("id", user_id).execute()
        return {"ok": True}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/users/{user_id}/deactivate", dependencies=[Depends(require_admin)])
def deactivate_user(user_id: str) -> dict:
    from app.settings_state import _supabase
    sb = _supabase()
    if not sb:
        raise HTTPException(status_code=503)
    try:
        sb.table("users").update({"role": "disabled"}).eq("id", user_id).execute()
        return {"ok": True}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.delete("/api/users/{user_id}", dependencies=[Depends(require_admin)])
def delete_user(user_id: str) -> dict:
    from app.settings_state import _supabase
    sb = _supabase()
    if not sb: raise HTTPException(status_code=503)
    sb.table("users").delete().eq("id", user_id).execute()
    return {"ok": True}


@app.get("/api/health")
def health() -> dict:
    """
    Estado de configuração do ambiente.

    Devolve apenas BOOLEANOS de "está configurado?", nunca valores — a rota é
    pública. Serve para conferir um deploy (Vercel/Render) sem descobrir por
    tentativa e erro: o .env não sobe no deploy, então cada ambiente precisa
    ter suas variáveis definidas no painel da plataforma.
    """
    return {
        "ok": True,
        "supabase": supabase_configured(),
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
    }


def _settings_dict(s: PortalSettings) -> dict:
    return {
        "source_folder": s.source_folder,
        "expired_folder": s.expired_folder,
        "machine_id": s.machine_id,
        "effective_source": str(s.effective_source()),
        "effective_expired": str(s.effective_expired()),
        "supabase": supabase_configured(),
        "persistence": (
            "supabase+data/portal_settings.json"
            if supabase_configured()
            else "data/portal_settings.json"
        ),
        "smtp_host": s.smtp_host,
        "smtp_port": s.smtp_port,
        "smtp_user": s.smtp_user,
        "smtp_password_set": bool(s.smtp_password_encrypted),
        "smtp_use_tls": s.smtp_use_tls,
        "smtp_use_ssl": s.smtp_use_ssl,
        "smtp_from_email": s.smtp_from_email,
        "smtp_alerts_enabled": s.smtp_alerts_enabled,
    }


@app.get("/api/settings", dependencies=[Depends(require_auth)])
def get_settings() -> dict:
    s = load_settings()
    return _settings_dict(s)


@app.put("/api/settings", dependencies=[Depends(require_admin)])
def put_settings(body: SettingsBody) -> dict:
    try:
        validate_smtp_config(body.smtp_use_tls, body.smtp_use_ssl)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
        
    old = load_settings()
    enc_password = old.smtp_password_encrypted
    if body.smtp_password is not None and body.smtp_password.strip() != "":
        try:
            enc_password = encrypt_password(body.smtp_password.strip())
        except Exception as e:
            raise HTTPException(status_code=500, detail="Erro ao criptografar senha SMTP")
            
    s = PortalSettings(
        source_folder=body.source_folder.strip(),
        expired_folder=body.expired_folder.strip(),
        machine_id=body.machine_id.strip() or "default",
        smtp_host=body.smtp_host.strip(),
        smtp_port=body.smtp_port,
        smtp_user=body.smtp_user.strip(),
        smtp_password_encrypted=enc_password,
        smtp_use_tls=body.smtp_use_tls,
        smtp_use_ssl=body.smtp_use_ssl,
        smtp_from_email=body.smtp_from_email.strip(),
        smtp_alerts_enabled=body.smtp_alerts_enabled,
    )
    save_settings(s)
    return _settings_dict(s)


class SmtpTestBody(BaseModel):
    target_email: str


@app.post("/api/settings/smtp/test", dependencies=[Depends(require_admin)])
def test_smtp_config(body: SmtpTestBody) -> dict:
    s = load_settings()
    if not s.smtp_host:
        raise HTTPException(status_code=400, detail="Servidor SMTP não configurado.")
    try:
        # Qualificado pelo módulo: `send_smtp_email` nunca esteve na lista de
        # imports deste arquivo, então a rota levantava NameError em vez de
        # enviar. Só não aparecia porque ninguém clicava em "Enviar Teste".
        smtp_service.send_smtp_email(
            host=s.smtp_host,
            port=s.smtp_port,
            user=s.smtp_user,
            password_enc=s.smtp_password_encrypted,
            use_tls=s.smtp_use_tls,
            use_ssl=s.smtp_use_ssl,
            from_email=s.smtp_from_email,
            to_email=body.target_email.strip(),
            subject="Monitor de Certificados - E-mail de Teste",
            html_content="<p>Olá! Este é um e-mail de teste enviado a partir do seu <strong>Monitor de Certificados</strong> para validar as configurações de SMTP.</p>"
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True, "message": "E-mail de teste enviado com sucesso!"}


@app.post("/api/settings/alerts/trigger", dependencies=[Depends(require_admin)])
def trigger_alerts_manually() -> dict:
    try:
        stats = trigger_all_alerts()
        return {"ok": True, "stats": stats}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/cron/alerts")
def cron_alerts(request: Request) -> dict:
    """
    Disparo agendado dos alertas, chamado pelo Cron do Vercel.

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
        return {"ok": True, "stats": stats}
    except Exception as e:
        logger.exception("Falha no cron de alertas")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/colaborador/notificacoes", dependencies=[Depends(require_auth)])
def get_user_notifications(token: auth.TokenData = Depends(require_auth)) -> dict:
    try:
        # Devolve lista limitada + totais separados: antes eram 519 itens
        # (167 KB) a cada poll de 60s, com os acionáveis no fim da lista.
        return build_notifications_payload(token.email, token.role)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/agent/commands", dependencies=[Depends(require_auth)])
def enqueue_agent_command(body: EnqueueCommandBody) -> dict:
    """
    Enfileira um comando para o agente Windows (poll em GET /api/agent/next).
    Comandos: mover_vencidos, rescan, ping. Use machine_id alinhado ao agente (ou * para qualquer um).
    """
    try:
        cid = enqueue(body.machine_id.strip() or "default", body.command.strip())
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    return {"ok": True, "id": cid, "command": body.command.strip()}


@app.get("/api/agent/next", dependencies=[Depends(require_auth)])
def agent_next_command(
    machine_id: str = Query("default", description="ID da máquina do agente"),
) -> dict:
    """
    O agente chama isto no início de cada ciclo: retira um comando em fila ou null.
    """
    q = pop_next_for_agent(machine_id)
    if not q:
        return {"command": None, "id": None}
    out = {"command": q.command, "id": q.id, "machine_id": q.machine_id}
    # `payload` carrega o token de uso único de instalar_certificados. A linha
    # da fila já foi removida no pop, então o token só trafega uma vez, para o
    # agente autenticado que o solicitou.
    if q.payload:
        out["payload"] = q.payload
    return out


@app.get("/api/agent/queue", dependencies=[Depends(require_auth)])
def agent_queue_list() -> dict:
    """Lista comandos ainda pendentes (monitorização no portal)."""
    return {"pendentes": list_pending(), "comandos_validos": sorted(COMMANDS)}


@app.get("/api/certificados", dependencies=[Depends(require_auth)])
def listar_certificados(
    fonte: str = Query(
        "auto",
        description="auto | remoto | local",
    ),
    pagina: Optional[int] = Query(None, ge=1, description="Com por_pagina, ativa paginação no servidor"),
    por_pagina: Optional[int] = Query(None, ge=1, le=2000),
    filtro_status: str = Query("todos", description="todos | validos | prestes_vencer | vencidos | erros"),
    busca: Optional[str] = Query(None, max_length=400),
    todas_filtradas: bool = Query(False, description="Exportação: todos os itens do filtro (até LISTAGEM_EXPORT_MAX)"),
) -> JSONResponse:
    """
    * auto: usa o último snapshot ingerido se existir; senão leitura local.
    * remoto: só snapshot (404 se vazio).
    * local: sempre leitura no disco do servidor (pastas efetivas da config).

    Com ``pagina`` e ``por_pagina`` na query, devolve ``paginacao`` e ``resumo`` (painel).
    Sem esses parâmetros, mantém o comportamento antigo: lista completa em ``itens``.
    """
    try:
        sets = load_settings()
        snap = get_latest_snapshot()
        base = _list_certificados_payload(sets, snap, fonte)

        paged = pagina is not None and por_pagina is not None
        if not paged and not todas_filtradas:
            return JSONResponse({**base, "supabase": supabase_configured()})

        now = datetime.now(timezone.utc)
        thirty = now + timedelta(days=30)
        enriched = [_enrich_cert_item_dashboard_flags(it, now, thirty) for it in (base.get("itens") or [])]
        filtered = [
            it
            for it in enriched
            if _dashboard_filtro_status_match(it, filtro_status) and _dashboard_busca_match(it, busca or "")
        ]
        resumo = _dashboard_resumo_counts(filtered)

        if todas_filtradas:
            lista_truncada = len(filtered) > LISTAGEM_EXPORT_MAX
            return JSONResponse(
                {
                    **base,
                    "itens": filtered[:LISTAGEM_EXPORT_MAX],
                    "resumo": resumo,
                    "lista_truncada": lista_truncada,
                    "supabase": supabase_configured(),
                }
            )

        pp = int(por_pagina or 20)
        total = len(filtered)
        total_pags = max(1, (total + pp - 1) // pp) if total else 1
        pagina_in = min(max(1, int(pagina or 1)), total_pags)
        off = (pagina_in - 1) * pp
        page_items = filtered[off : off + pp]
        return JSONResponse(
            {
                **base,
                "itens": page_items,
                "resumo": resumo,
                "paginacao": {
                    "pagina": pagina_in,
                    "total_paginas": total_pags,
                    "total_itens": total,
                    "por_pagina": pp,
                    # Permite ao portal avisar sobre truncamento ANTES de exportar,
                    # em vez de só depois que o ficheiro já foi gerado.
                    "export_max": LISTAGEM_EXPORT_MAX,
                },
                "supabase": supabase_configured(),
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Erro em GET /api/certificados (fonte=%s)", fonte)
        raise HTTPException(
            status_code=500,
            detail="Falha ao listar certificados. Veja o terminal do uvicorn. Resumo: " + str(e),
        ) from e


def _escape_ilike_pattern(val: str) -> str:
    """Evita que % e _ do utilizador interfiram com ILIKE."""
    return val.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _parse_iso_utc(iso_value: Optional[str]) -> datetime:
    if not iso_value:
        return datetime.min.replace(tzinfo=timezone.utc)
    s = str(iso_value).strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)


def _normalize_ingest_items_status(items: List[dict], now: datetime) -> List[dict]:
    """
    Alinha gravacao com o criterio do painel: se not_after ja passou (UTC),
    marca status como expirado mesmo quando o agente enviou ok (ex.: relogio local desfasado).
    Nao altera erro, fora_do_padrao nem itens sem not_after valido.
    """
    min_dt = datetime.min.replace(tzinfo=timezone.utc)
    out: List[dict] = []
    for raw in items:
        it = dict(raw)
        s = str(it.get("status") or "").strip().lower()
        if s == CertStatus.OK.value:
            na = it.get("not_after")
            if na:
                exp = _parse_iso_utc(str(na))
                if exp > min_dt and exp < now:
                    it["status"] = CertStatus.EXPIRED.value
        out.append(it)
    return out


def _digits_only_doc(value: Any) -> str:
    return re.sub(r"\D", "", str(value or ""))


def _normalize_name_dup(value: Any) -> str:
    t = str(value or "").strip().lower()
    t = unicodedata.normalize("NFD", t)
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return " ".join(t.split())


def _fingerprint_hex_from_row(row: dict) -> str:
    """SHA-256 (hex) do fingerprint do certificado; aceita chave antiga `cert_sha256` nos snapshots."""
    v = row.get("fingerprint_sha256") or row.get("cert_sha256")
    if v is None or not str(v).strip():
        return ""
    return str(v).strip().lower()


def _item_resumo_duplicidade(it: dict) -> dict[str, Any]:
    fp = it.get("fingerprint_sha256") or it.get("cert_sha256")
    return {
        "file_name": it.get("file_name"),
        "nome": it.get("nome") or it.get("display_name"),
        "documento": it.get("documento_formatado") or it.get("documento_numero"),
        "documento_numero": it.get("documento_numero"),
        "not_after": it.get("not_after"),
        "not_before": it.get("not_before"),
        "status": it.get("status"),
        "path": it.get("path"),
        "subject": it.get("subject"),
        "issuer": it.get("issuer"),
        "serial_number": it.get("serial_number"),
        "fingerprint_sha256": fp,
    }


def _fingerprint_hex_resumo(m: dict) -> str:
    v = m.get("fingerprint_sha256")
    if v is None or not str(v).strip():
        return ""
    return str(v).strip().lower()


def _filtrar_grupo_documento_apos_fingerprint(members: List[dict]) -> List[dict]:
    """
    Remove da lista «mesmo documento» os ficheiros que já entram no agrupamento
    por fingerprint (2+ com o mesmo SHA-256). A duplicidade criptográfica é a
    validação definitiva; o grupo por documento fica para CPF/CNPJ igual sem
    fingerprint ou com certificados distintos (ex.: renovação).
    """
    by_fp: dict[str, List[dict]] = defaultdict(list)
    sem_fp: List[dict] = []
    for m in members:
        fp = _fingerprint_hex_resumo(m)
        if not fp:
            sem_fp.append(m)
        else:
            by_fp[fp].append(m)
    kept: List[dict] = []
    kept.extend(sem_fp)
    for _fp, grupo in by_fp.items():
        if len(grupo) < 2:
            kept.extend(grupo)
    return kept


def _agrupar_duplicidades(
    rows: List[dict],
) -> Tuple[List[dict], List[dict], List[dict]]:
    """
    Deteta duplicidades no mesmo inventário (último snapshot ou scan local):
    - mesmo CNPJ/CPF (11+ dígitos) em mais de um ficheiro (exceto quando a duplicidade
      já é explicada só por fingerprint — aí fica só em certificados idênticos);
    - certificados idênticos: mesmo fingerprint (SHA-256 do DER) em mais de um ficheiro;
    - nomes muito semelhantes (SequenceMatcher) só quando não existe fingerprint
      no inventário (export antigo do agente ou leitura falhou).
    """
    by_doc: dict[str, List[dict]] = defaultdict(list)
    for it in rows:
        d = _digits_only_doc(it.get("documento_numero") or it.get("documento_formatado"))
        if len(d) >= 11:
            by_doc[d].append(_item_resumo_duplicidade(it))

    grupos_documento: List[dict] = []
    for doc_digits, members in by_doc.items():
        if len(members) < 2:
            continue
        filtrados = _filtrar_grupo_documento_apos_fingerprint(members)
        if len(filtrados) < 2:
            continue
        exib = next((m.get("documento") for m in filtrados if m.get("documento")), doc_digits)
        grupos_documento.append(
            {
                "tipo": "documento",
                "documento_digitos": doc_digits,
                "documento_exibicao": exib,
                "itens": filtrados,
            }
        )

    by_fp: dict[str, List[dict]] = defaultdict(list)
    for it in rows:
        fp = _fingerprint_hex_from_row(it)
        if not fp:
            continue
        by_fp[fp].append(_item_resumo_duplicidade(it))

    grupos_cert_igual: List[dict] = []
    for fp_hex, members in by_fp.items():
        if len(members) < 2:
            continue
        grupos_cert_igual.append(
            {
                "tipo": "certificado_igual",
                "fingerprint_sha256": fp_hex,
                "itens": members,
            }
        )

    n = len(rows)
    parent = list(range(n))

    def find(a: int) -> int:
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for i in range(n):
        for j in range(i + 1, n):
            if _fingerprint_hex_from_row(rows[i]) or _fingerprint_hex_from_row(rows[j]):
                continue
            fi = str(rows[i].get("file_name") or "").strip().lower()
            fj = str(rows[j].get("file_name") or "").strip().lower()
            if not fi or fi == fj:
                continue
            di = _digits_only_doc(
                rows[i].get("documento_numero") or rows[i].get("documento_formatado")
            )
            dj = _digits_only_doc(
                rows[j].get("documento_numero") or rows[j].get("documento_formatado")
            )
            if len(di) >= 11 and len(dj) >= 11 and di == dj:
                continue
            ni = _normalize_name_dup(
                rows[i].get("nome") or rows[i].get("display_name") or rows[i].get("file_name")
            )
            nj = _normalize_name_dup(
                rows[j].get("nome") or rows[j].get("display_name") or rows[j].get("file_name")
            )
            if len(ni) < 5 or len(nj) < 5:
                continue
            if SequenceMatcher(None, ni, nj).ratio() >= 0.86:
                union(i, j)

    roots: dict[int, List[int]] = defaultdict(list)
    for i in range(n):
        roots[find(i)].append(i)

    grupos_nome: List[dict] = []
    for _root, idxs in roots.items():
        if len(idxs) < 2:
            continue
        members = [_item_resumo_duplicidade(rows[k]) for k in idxs]
        nomes_cur = [
            _normalize_name_dup(
                rows[k].get("nome") or rows[k].get("display_name") or rows[k].get("file_name")
            )
            for k in idxs
        ]
        rotulo = max(nomes_cur, key=len) if nomes_cur else "—"
        grupos_nome.append({"tipo": "nome_similar", "rotulo": rotulo[:120], "itens": members})

    return grupos_documento, grupos_nome, grupos_cert_igual


def _doc_norm(v: Any) -> str:
    return re.sub(r"\D+", "", str(v or ""))


def _parse_dt_or_min(v: Any) -> datetime:
    return _parse_iso_utc(str(v or ""))


def _status_prioridade(status: str) -> int:
    s = str(status or "").lower()
    if s in ("ok", "valido", "válido"):
        return 3
    if s in ("expirado", "vencido"):
        return 2
    if s in ("erro",):
        return 1
    return 0


def _lista_base_docs_historico() -> List[dict]:
    # Limitamos a 100 snapshots para não sobrecarregar a memória no Render free tier.
    # Para colaboradores, apenas os snapshots recentes são relevantes.
    hist = historico_certificados(limite_snapshots=100)
    rows = hist.get("itens", [])
    grupos: Dict[str, dict] = {}
    for it in rows:
        doc = _doc_norm(it.get("documento"))
        if not doc:
            continue
        atual = grupos.get(doc)
        cand = {
            "documento": it.get("documento") or doc,
            "documento_digitos": doc,
            "nome": it.get("nome") or "—",
            "status_ultimo": str(it.get("status_ultimo") or "").lower(),
            "vencimento_certificado": it.get("vencimento_certificado"),
            "ultima_data_registrada": it.get("ultima_data_registrada"),
        }
        if not atual:
            grupos[doc] = cand
            continue
        pa = _status_prioridade(atual.get("status_ultimo", ""))
        pc = _status_prioridade(cand.get("status_ultimo", ""))
        if pc > pa:
            grupos[doc] = cand
            continue
        if pc == pa:
            da = _parse_dt_or_min(atual.get("ultima_data_registrada"))
            dc = _parse_dt_or_min(cand.get("ultima_data_registrada"))
            if dc > da:
                grupos[doc] = cand
    return sorted(grupos.values(), key=lambda x: (x.get("nome") or "").lower())


def _painel_docs_selecionados(doc_ids: List[str]) -> List[dict]:
    base = _lista_base_docs_historico()
    by_doc = {str(it.get("documento_digitos")): it for it in base}
    now = datetime.now(timezone.utc)
    out: List[dict] = []
    for d in doc_ids:
        it = by_doc.get(d)
        if not it:
            out.append(
                {
                    "documento_digitos": d,
                    "documento": d,
                    "nome": "Não encontrado no inventário atual",
                    "status": "nao_encontrado",
                    "vencimento_certificado": None,
                    "dias_restantes": None,
                }
            )
            continue
        v_iso = it.get("vencimento_certificado")
        v_dt = _parse_iso_utc(v_iso) if v_iso else datetime.min.replace(tzinfo=timezone.utc)
        dias = (v_dt.date() - now.date()).days if v_iso else None
        
        status_ult = str(it.get("status_ultimo") or "").lower()
        if status_ult == "expirado" or (v_iso and v_dt < now):
            status = "vencido"
        elif status_ult == "erro":
            status = "erro"
        elif status_ult == "fora_do_padrao":
            status = "fora_do_padrao"
        elif v_iso and dias is not None and 0 <= dias <= 30:
            status = "expirando"
        else:
            status = "ativo"

        out.append(
            {
                "documento_digitos": d,
                "documento": it.get("documento") or d,
                "nome": it.get("nome") or "—",
                "status": status,
                "vencimento_certificado": v_iso,
                "dias_restantes": dias,
            }
        )
    out.sort(
        key=lambda x: (
            0 if x.get("status") == "vencido" else 1,
            x.get("dias_restantes") if x.get("dias_restantes") is not None else 10**9,
        )
    )
    return out


class ColaboradorSelecaoBody(BaseModel):
    documentos: List[str] = Field(default_factory=list)


@app.get("/api/colaborador/certificados/opcoes", dependencies=[Depends(require_auth)])
def colaborador_opcoes_certificados(_token: auth.TokenData = Depends(require_auth)) -> dict:
    itens = _lista_base_docs_historico()
    now = datetime.now(timezone.utc)
    out = []
    for it in itens:
        v_iso = it.get("vencimento_certificado")
        v_dt = _parse_iso_utc(v_iso) if v_iso else datetime.min.replace(tzinfo=timezone.utc)
        dias = (v_dt.date() - now.date()).days if v_iso else None
        
        status_ult = str(it.get("status_ultimo") or "").lower()
        if status_ult == "expirado" or (v_iso and v_dt < now):
            status = "vencido"
        elif status_ult == "erro":
            status = "erro"
        elif status_ult == "fora_do_padrao":
            status = "fora_do_padrao"
        elif v_iso and dias is not None and 0 <= dias <= 30:
            status = "expirando"
        else:
            status = "ativo"
            
        out.append({
            **it,
            "status": status
        })
    return {"itens": out, "total": len(out)}


@app.get("/api/colaborador/certificados/selecionados", dependencies=[Depends(require_auth)])
def colaborador_get_selecionados(token: auth.TokenData = Depends(require_auth)) -> dict:
    email = (token.email or "").strip().lower()
    docs = load_colaborador_selecao(email)
    return {"documentos": docs, "total": len(docs)}


@app.put("/api/colaborador/certificados/selecionados", dependencies=[Depends(require_auth)])
def colaborador_put_selecionados(
    body: ColaboradorSelecaoBody, token: auth.TokenData = Depends(require_auth)
) -> dict:
    email = (token.email or "").strip().lower()
    docs = sorted({_doc_norm(x) for x in body.documentos if _doc_norm(x)})
    save_colaborador_selecao(email, docs)
    return {"ok": True, "documentos": docs, "total": len(docs)}


@app.get("/api/colaborador/certificados/painel", dependencies=[Depends(require_auth)])
def colaborador_painel_certificados(token: auth.TokenData = Depends(require_auth)) -> dict:
    email = (token.email or "").strip().lower()
    docs = load_colaborador_selecao(email)
    itens = _painel_docs_selecionados(docs)
    return {"itens": itens, "total": len(itens)}


@app.get("/api/certificados/duplicidades", dependencies=[Depends(require_auth)])
def certificados_duplicidades() -> dict[str, Any]:
    """
    Analisa o último snapshot recebido (dados atuais do agente) ou, na ausência,
    o scan local no servidor, e devolve grupos de possíveis duplicados.
    """
    snap = get_latest_snapshot()
    origem = "ultimo_snapshot"
    scanned_at: Optional[str] = None
    if snap and (snap.get("items") or []):
        raw_items: List[dict] = list(snap.get("items") or [])
        scanned_at = str(snap.get("scanned_at") or "") or None
    else:
        sets = load_settings()
        raw_items = [cert_to_public_dict(c) for c in scan_folder(sets.effective_source())]
        origem = "scan_local_servidor"
        scanned_at = datetime.now(timezone.utc).isoformat()

    rows = [it for it in raw_items if str(it.get("file_name") or "").strip()]
    gd, gn, gci = _agrupar_duplicidades(rows)
    return {
        "origem_dados": origem,
        "scanned_at": scanned_at,
        "total_itens_analisados": len(rows),
        "grupos_documento": gd,
        "grupos_nome_similar": gn,
        "grupos_certificado_igual": gci,
        "total_grupos_documento": len(gd),
        "total_grupos_nome_similar": len(gn),
        "total_grupos_certificado_igual": len(gci),
    }


def _historico_merge_snapshot_into_agregados(snap: dict[str, Any], agregados: Dict[str, dict]) -> None:
    """Acumula itens de um snapshot no mapa por file_name (mantém linha do scan mais recente)."""
    scanned_at = snap.get("scanned_at") or datetime.now(timezone.utc).isoformat()
    scanned_dt = _parse_iso_utc(scanned_at)
    for it in (snap.get("items") or []):
        file_name = str(it.get("file_name") or "").strip()
        if not file_name:
            continue
        key = file_name.lower()
        atual = agregados.get(key)
        if (not atual) or (scanned_dt > atual["_dt"]):
            doc_raw = (
                it.get("documento_formatado") or it.get("documento_numero") or it.get("documento")
            )
            agregados[key] = {
                "_dt": scanned_dt,
                "file_name": file_name,
                "nome": it.get("nome") or it.get("display_name") or file_name,
                "status_ultimo": it.get("status"),
                "documento": doc_raw,
                "vencimento_certificado": it.get("not_after"),
                "ultima_data_registrada": scanned_dt.isoformat(),
            }


def _historico_carregar_agregados(limite_snapshots: int) -> Tuple[Dict[str, dict], int]:
    """
    Percorre snapshots (Supabase em lotes ou ficheiro local) e devolve agregação por file_name.
    Resultado pode vir de cache em RAM (TTL configurável) por (Supabase ativo, limite).
    """
    from app.settings_state import _supabase

    sb = _supabase()
    uses_sb = sb is not None

    def _build() -> Tuple[Dict[str, dict], int]:
        agregados: Dict[str, dict] = {}
        snapshots_lidos = 0
        if sb:
            try:
                page_size = 50
                offset = 0
                while snapshots_lidos < limite_snapshots:
                    chunk = min(page_size, limite_snapshots - snapshots_lidos)
                    end = offset + chunk - 1
                    r = (
                        sb.table("cert_snapshots")
                        .select("scanned_at, items")
                        .order("scanned_at", desc=True)
                        .range(offset, end)
                        .execute()
                    )
                    rows = r.data or []
                    if not rows:
                        break
                    for snap in rows:
                        _historico_merge_snapshot_into_agregados(snap, agregados)
                    snapshots_lidos += len(rows)
                    offset += len(rows)
                    if len(rows) < chunk:
                        break
            except Exception as e:  # noqa: BLE001
                logger.exception("Falha ao ler histórico no Supabase")
                raise HTTPException(status_code=500, detail=f"Falha ao ler histórico: {e}") from e
        else:
            snap = get_latest_snapshot()
            if snap:
                _historico_merge_snapshot_into_agregados(snap, agregados)
                snapshots_lidos = 1
        return agregados, snapshots_lidos

    return _historico_cache_get_or_build(uses_sb, limite_snapshots, _build)


def _historico_itens_visualizacao(agregados: Dict[str, dict]) -> List[dict]:
    linhas = sorted(agregados.values(), key=lambda x: x["_dt"], reverse=True)
    return [{k: v for k, v in row.items() if k != "_dt"} for row in linhas]


def _historico_filtrar_busca(itens: List[dict], busca_raw: str) -> List[dict]:
    q = str(busca_raw or "").strip().lower()
    if not q:
        return itens
    out: List[dict] = []
    for it in itens:
        haystack = (
            f"{it.get('file_name') or ''} {it.get('nome') or ''} {it.get('documento') or ''} "
            f"{it.get('ultima_data_registrada') or ''} {it.get('vencimento_certificado') or ''}"
        ).lower()
        if q in haystack:
            out.append(it)
    return out


def _vencidos_filtrar_busca(rows: List[dict], busca_raw: str) -> List[dict]:
    if not str(busca_raw or "").strip():
        return rows
    raw = str(busca_raw).strip()
    bt = _painel_busca_normalizada(raw)
    bd = re.sub(r"\D", "", raw)
    out: List[dict] = []
    for it in rows:
        nome = _painel_busca_normalizada(it.get("nome") or "")
        doc_txt = _painel_busca_normalizada(it.get("documento") or "")
        doc_d = _digits_only_doc(it.get("documento") or "")
        venc_txt = _painel_busca_normalizada(it.get("vencimento_certificado") or "")
        vn = _digits_only_doc(str(it.get("vencimento_certificado") or ""))
        if bt and bt in nome:
            out.append(it)
            continue
        if bt and bt in doc_txt:
            out.append(it)
            continue
        if bt and bt in venc_txt:
            out.append(it)
            continue
        if bd and bd in doc_d:
            out.append(it)
            continue
        if bd and bd in vn:
            out.append(it)
            continue
    return out


def _cert_history_fetch_all(sb: Any) -> List[dict[str, Any]]:
    """Lê todas as linhas de cert_history (PostgREST limita ~1000 por pedido sem range)."""
    cols = (
        "file_name, nome, documento, status_ultimo, "
        "vencimento_certificado, ultima_data_registrada"
    )
    batch = 1000
    out: List[dict[str, Any]] = []
    offset = 0
    while True:
        r = (
            sb.table("cert_history")
            .select(cols)
            .order("ultima_data_registrada", desc=True)
            .range(offset, offset + batch - 1)
            .execute()
        )
        chunk = r.data or []
        out.extend(chunk)
        if len(chunk) < batch:
            break
        offset += batch
    return out


def historico_certificados(
    limite_snapshots: int = 500,
    *,
    offset: Optional[int] = None,
    limit: Optional[int] = None,
    busca: Optional[str] = None,
) -> dict:
    """
    Lista certificados já mapeados em algum momento, com a última data registrada.
    Com ``limit`` definido, lê só uma página de ``cert_history`` (menos carga).

    Chamadas internas devem omitir ``limit`` para obter a lista completa.
    """
    from app.settings_state import _supabase

    pagination = limit is not None
    offset = max(0, int(offset or 0))
    page_limit = int(limit) if pagination else None
    busca_txt = str(busca).strip() if busca else ""

    def _normalize_rows(rows_raw: List[dict[str, Any]]) -> List[dict[str, Any]]:
        return [
            {
                "file_name":              row.get("file_name"),
                "nome":                   row.get("nome"),
                "documento":              row.get("documento"),
                "status_ultimo":          row.get("status_ultimo"),
                "vencimento_certificado": row.get("vencimento_certificado"),
                "ultima_data_registrada": row.get("ultima_data_registrada"),
            }
            for row in rows_raw
        ]

    def _apply_cert_history_or_busca(qb: Any) -> Any:
        if not busca_txt:
            return qb
        pat = "%" + _escape_ilike_pattern(busca_txt) + "%"
        filt = f"nome.ilike.{pat},file_name.ilike.{pat},documento.ilike.{pat}"
        return qb.or_(filt)

    sb = _supabase()
    if sb:
        _use_history_table = True
        rows_non_paginated: List[dict[str, Any]] = []
        try:
            if pagination and page_limit is not None:
                qc = _apply_cert_history_or_busca(
                    sb.table("cert_history").select("file_name", count="exact", head=True)
                )
                c_r = qc.execute()
                total_count = c_r.count if c_r.count is not None else 0

                if total_count > 0 or busca_txt:
                    qp = _apply_cert_history_or_busca(
                        sb.table("cert_history")
                        .select(
                            "file_name, nome, documento, status_ultimo, "
                            "vencimento_certificado, ultima_data_registrada",
                        )
                        .order("ultima_data_registrada", desc=True)
                    )
                    hi = offset + page_limit - 1
                    p_r = qp.range(offset, hi).execute()
                    return {
                        "itens": _normalize_rows(p_r.data or []),
                        "total": total_count,
                        "offset": offset,
                        "limit": page_limit,
                        "snapshots_lidos": 0,
                        "fonte": "cert_history",
                    }

                # total_count == 0 e sem texto de busca → tentar snapshots (dados legados)
            else:
                rows_non_paginated = _cert_history_fetch_all(sb)
        except Exception as e:  # noqa: BLE001
            err_str = str(e)
            if "PGRST205" in err_str or "cert_history" in err_str:
                logger.warning(
                    "Tabela cert_history não encontrada; usando fallback de snapshots. "
                    "Execute supabase/migrations/20260504_cert_history.sql no Supabase."
                )
                _use_history_table = False
                rows_non_paginated = []
            else:
                logger.exception("Falha inesperada ao ler cert_history no Supabase")
                raise HTTPException(status_code=500, detail=f"Falha ao ler histórico: {e}") from e

        if _use_history_table and rows_non_paginated and not pagination:
            itens = _normalize_rows(rows_non_paginated)
            return {
                "itens": itens,
                "total": len(itens),
                "offset": 0,
                "limit": len(itens),
                "snapshots_lidos": 0,
                "fonte": "cert_history",
            }

    agregados, snapshots_lidos = _historico_carregar_agregados(limite_snapshots)
    itens = _historico_itens_visualizacao(agregados)
    itens = _historico_filtrar_busca(itens, busca_txt)

    if pagination and page_limit is not None:
        total_f = len(itens)
        fatia = itens[offset : offset + page_limit]
        return {
            "itens": fatia,
            "total": total_f,
            "offset": offset,
            "limit": page_limit,
            "snapshots_lidos": snapshots_lidos,
            "fonte": "snapshots",
        }

    return {
        "itens": itens,
        "total": len(itens),
        "offset": 0,
        "limit": len(itens),
        "snapshots_lidos": snapshots_lidos,
        "fonte": "snapshots",
    }


@app.get("/api/certificados/historico", dependencies=[Depends(require_auth)])
def historico_certificados_http(
    limite_snapshots: int = Query(
        500,
        ge=1,
        le=2000,
        description="Máximo de snapshots no fallback (quando cert_history está vazio)",
    ),
    pagina: int = Query(1, ge=1, description="Página (1-based)"),
    por_pagina: int = Query(20, ge=1, le=2000, description="Registos por página"),
    todas_filtradas: bool = Query(
        False,
        description="Quando true, devolve toda a lista filtrada (exportação; pode truncar)",
    ),
    busca: Optional[str] = Query(
        None,
        max_length=200,
        description="Filtro parcial em nome, ficheiro ou documento",
    ),
) -> dict:
    b = busca.strip() if busca else None
    if todas_filtradas:
        raw = historico_certificados(limite_snapshots, offset=None, limit=None, busca=b)
        itens = list(raw.get("itens") or [])
        lista_truncada = len(itens) > LISTAGEM_EXPORT_MAX
        return {
            "itens": itens[:LISTAGEM_EXPORT_MAX],
            "total": len(itens),
            "snapshots_lidos": raw.get("snapshots_lidos", 0),
            "fonte": raw.get("fonte"),
            "lista_truncada": lista_truncada,
        }

    off = (pagina - 1) * por_pagina
    raw = historico_certificados(
        limite_snapshots,
        offset=off,
        limit=por_pagina,
        busca=b,
    )
    total = int(raw.get("total") or 0)
    total_pags = max(1, (total + por_pagina - 1) // por_pagina) if total else 1
    pagina_out = min(max(1, pagina), total_pags)
    out = dict(raw)
    out["paginacao"] = {
        "pagina": pagina_out,
        "total_paginas": total_pags,
        "total_itens": total,
        "por_pagina": por_pagina,
        "export_max": LISTAGEM_EXPORT_MAX,
    }
    return out


@app.get("/api/certificados/vencidos", dependencies=[Depends(require_auth)])
def vencidos_certificados(
    data_inicio: Optional[str] = Query(None, description="Data inicial (YYYY-MM-DD) pelo vencimento"),
    data_fim: Optional[str] = Query(None, description="Data final (YYYY-MM-DD) pelo vencimento"),
    pagina: int = Query(1, ge=1),
    por_pagina: int = Query(20, ge=1, le=2000),
    todas_filtradas: bool = Query(False, description="Lista completa filtrada (exportação; pode truncar)"),
    busca: Optional[str] = Query(None, max_length=200),
    limite_snapshots: int = Query(500, ge=1, le=2000, description="Quantidade máxima de snapshots lidos"),
) -> dict:
    # Vencidos precisa de uma agregação tão ampla quanto a do histórico (fallback snapshots).
    lim_hist = max(limite_snapshots, config.HISTORICO_LIMITE_SNAPSHOTS)
    hist = historico_certificados(lim_hist, offset=None, limit=None, busca=None)
    itens_hist = hist.get("itens", [])
    inicio_dt = _parse_iso_utc(data_inicio + "T00:00:00+00:00") if data_inicio else None
    fim_dt = _parse_iso_utc(data_fim + "T23:59:59+00:00") if data_fim else None
    busca_txt = str(busca or "").strip() or None

    now_utc = datetime.now(timezone.utc)
    min_dt = datetime.min.replace(tzinfo=timezone.utc)

    def _conta_como_certificado_vencido(it: dict) -> bool:
        """Inclui `expirado`/`vencido` no status ou data de validade já passada (alinha ao painel)."""
        s = str(it.get("status_ultimo") or "").lower()
        if s in ("expirado", "vencido"):
            return True
        venc_dt = _parse_iso_utc(it.get("vencimento_certificado"))
        if venc_dt <= min_dt:
            return False
        return venc_dt < now_utc

    venc_filtrados: List[dict] = []
    for it in itens_hist:
        if not _conta_como_certificado_vencido(it):
            continue
        venc_dt = _parse_iso_utc(it.get("vencimento_certificado"))
        s_low = str(it.get("status_ultimo") or "").lower()
        if inicio_dt or fim_dt:
            if venc_dt <= min_dt:
                if s_low not in ("expirado", "vencido"):
                    continue
            else:
                if inicio_dt and venc_dt < inicio_dt:
                    continue
                if fim_dt and venc_dt > fim_dt:
                    continue
        venc_filtrados.append(it)

    venc_filtrados = _vencidos_filtrar_busca(venc_filtrados, busca_txt or "")

    anos_cnt: defaultdict[int, int] = defaultdict(int)
    for it in venc_filtrados:
        venc_dt = _parse_iso_utc(it.get("vencimento_certificado"))
        y = int(venc_dt.year)
        if y < 1900:
            continue
        anos_cnt[y] += 1
    resumo_anos = [{"ano": ano, "total": anos_cnt[ano]} for ano in sorted(anos_cnt.keys(), reverse=True)]

    total = len(venc_filtrados)
    if todas_filtradas:
        lista_truncada = total > LISTAGEM_EXPORT_MAX
        return {
            "itens": venc_filtrados[:LISTAGEM_EXPORT_MAX],
            "total": total,
            "data_inicio": data_inicio,
            "data_fim": data_fim,
            "snapshots_lidos": hist.get("snapshots_lidos", 0),
            "lista_truncada": lista_truncada,
            "resumo_anos": resumo_anos,
        }

    total_pags = max(1, (total + por_pagina - 1) // por_pagina) if total else 1
    pagina_out = min(max(1, pagina), total_pags)
    off_pg = (pagina_out - 1) * por_pagina
    pagina_slice = venc_filtrados[off_pg : off_pg + por_pagina]

    return {
        "itens": pagina_slice,
        "total": total,
        "data_inicio": data_inicio,
        "data_fim": data_fim,
        "snapshots_lidos": hist.get("snapshots_lidos", 0),
        "resumo_anos": resumo_anos,
        "paginacao": {
            "pagina": pagina_out,
            "total_paginas": total_pags,
            "total_itens": total,
            "por_pagina": por_pagina,
            "export_max": LISTAGEM_EXPORT_MAX,
        },
    }


@app.post("/api/ingest", dependencies=[Depends(require_auth)])
def ingest(body: IngestBody, background_tasks: BackgroundTasks) -> dict:
    """
    Recebe o resultado de um scan feito no Windows (agente em segundo plano).
    Persiste no Supabase (ou em data/last_ingest.json se o Supabase não estiver configurado).
    Também faz upsert na tabela materializada cert_history para acelerar o histórico.
    """
    machine_id = body.machine_id.strip() or "default"
    scanned = datetime.now(timezone.utc)
    items = _normalize_ingest_items_status(body.items, scanned)
    save_snapshot(
        machine_id=machine_id,
        source_folder=body.source_folder.strip(),
        expired_folder=body.expired_folder.strip(),
        items=items,
    )
    # Atualiza a tabela materializada — operação rápida, não bloqueia o retorno
    upsert_cert_history(
        machine_id=machine_id,
        scanned_iso=scanned.isoformat(),
        items=items,
    )
    # Dispara e-mails de alerta em segundo plano para não bloquear a resposta do agente
    background_tasks.add_task(trigger_all_alerts)
    return {
        "ok": True,
        "itens_recebidos": len(body.items),
        "grava_em": "supabase" if supabase_configured() else "arquivo local (data/last_ingest.json)",
    }


@app.post("/api/mover-vencidos", dependencies=[Depends(require_auth)])
def mover_vencidos() -> JSONResponse:
    """
    Só move arquivos no **mesmo** sistema de ficheiros que corre o API (servidor acessa as pastas).
    Se a interface mostrar dados "remotos" vindos do agente, use o agendador no Windows
    (agente com --mover) para mover aí o disco local.
    """
    sets = load_settings()
    src = sets.effective_source()
    exp = sets.effective_expired()
    itens: List[CertInfo] = scan_folder(src)
    movidos: List[dict] = []
    erros: List[dict] = []

    for c in itens:
        if c.status != CertStatus.EXPIRED:
            continue
        try:
            novo = move_to_expired(c, exp)
            movidos.append({"de": str(c.path), "para": str(novo)})
        except OSError as e:
            erros.append({"arquivo": c.file_name, "erro": str(e)})

    return JSONResponse(
        {
            "movidos": movidos,
            "erros": erros,
            "total_movidos": len(movidos),
        }
    )


# =========================================================================
# LGPD / PRIVACY BY DESIGN - DIREITOS DOS TITULARES
# =========================================================================

@app.get("/api/users/me/export")
def export_my_data(token: auth.TokenData = Depends(require_auth)) -> dict:
    """[LGPD] Portabilidade e Consulta de Dados (Art. 18, incisos II e X)"""
    from app.settings_state import load_colaborador_selecao
    email = token.email
    docs = load_colaborador_selecao(email)
    
    return {
        "titular": email,
        "vinculo_role": token.role,
        "documentos_monitorados_cnpj_cpf": docs,
        "exportado_em": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "aviso_lgpd": "Este arquivo contém seus dados pessoais conforme registro no sistema."
    }

@app.delete("/api/users/me/delete")
def delete_my_data(token: auth.TokenData = Depends(require_auth)) -> dict:
    """[LGPD] Direito ao Esquecimento / Eliminação (Art. 18, inciso VI)"""
    from app.settings_state import _supabase
    email = token.email
    sb = _supabase()
    
    # 1. Apagar seleções (Ações do usuário no app)
    if sb:
        sb.table("colaborador_cert_selecoes").delete().eq("user_email", email.lower()).execute()
    else:
        # Modo arquivo local: limpa a entrada
        from app.settings_state import save_colaborador_selecao
        save_colaborador_selecao(email, [])
        
    return {
        "status": "ok", 
        "message": "Seus dados operacionais associados foram permanentemente removidos."
    }


# ══════════════════════════════════════════════════════════════════════════
# MÓDULO INSTALADOR DE CERTIFICADOS DIGITAIS
# ══════════════════════════════════════════════════════════════════════════

from app import cert_installer


class UploadPfxRequest(BaseModel):
    """Payload enviado pelo agente com o PFX cifrado em trânsito."""
    fingerprint: str
    machine_id: str = "default"
    pfx_b64: str  # PFX em base64 (cifrado em trânsito via TLS)
    password: Optional[str] = None
    nome_titular: Optional[str] = None
    documento: Optional[str] = None
    documento_tipo: Optional[str] = None
    subject: Optional[str] = None
    not_before: Optional[str] = None
    not_after: Optional[str] = None
    friendly_name: Optional[str] = None


@app.post("/api/cert-installer/upload-pfx")
def upload_pfx(
    body: UploadPfxRequest,
    request: Request,
    token: auth.TokenData = Depends(require_agent_or_admin),
):
    """
    Recebe um PFX do agente, cifra com a chave do servidor e armazena.
    Chamado pelo agente durante o ciclo de scan.
    """
    import base64 as b64mod
    try:
        pfx_bytes = b64mod.b64decode(body.pfx_b64)
    except Exception:
        raise HTTPException(status_code=400, detail="pfx_b64 inválido")

    # Um PFX real tem poucos KB. 50 MB era um vetor de DoS via base64 no banco.
    if len(pfx_bytes) > 1 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="PFX excede 1 MB")

    # Barreira de servidor para o opt-in: mesmo que um agente desatualizado
    # (ou adulterado) envie tudo, só entra no cofre o que foi autorizado.
    #
    # O filtro por machine_id é parte da barreira, não detalhe de consulta. Sem
    # ele bastava o fingerprint estar autorizado em QUALQUER máquina para um
    # agente que se declarasse de outra estação gravar o PFX de um certificado
    # que ninguém autorizou ali.
    #
    # A chave composta `(machine_id, fingerprint)` fechou a metade destrutiva do
    # vetor: um upload declarado como outra estação hoje cria uma linha própria
    # em vez de sobrescrever o registro legítimo. O que ela NÃO faz é decidir se
    # aquele PFX podia ser guardado — isso continua sendo trabalho desta barreira.
    autorizados = set(cert_installer.listar_optin_fingerprints(body.machine_id))
    if body.fingerprint not in autorizados:
        raise HTTPException(
            status_code=403,
            detail="Certificado não autorizado para o cofre. Habilite-o em /instalador.",
        )

    try:
        cert_id = cert_installer.upsert_pfx(
            fingerprint=body.fingerprint,
            pfx_bytes=pfx_bytes,
            machine_id=body.machine_id,
            password=body.password,
            nome_titular=body.nome_titular,
            documento=body.documento,
            documento_tipo=body.documento_tipo,
            subject=body.subject,
            not_before=body.not_before,
            not_after=body.not_after,
            friendly_name=body.friendly_name,
        )
        return {"status": "ok", "id": cert_id, "fingerprint": body.fingerprint}
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception:
        logger.exception("Erro ao processar upload de PFX")
        raise HTTPException(status_code=500, detail="Erro interno ao armazenar PFX")


class VaultOptinRequest(BaseModel):
    """Admin autoriza um certificado a ter o PFX guardado no cofre."""
    fingerprint: str
    machine_id: str = "default"
    nome_titular: Optional[str] = None
    documento: Optional[str] = None


@app.get("/api/cert-installer/vault-optin")
def listar_vault_optin(
    machine_id: Optional[str] = Query(None),
    _token: auth.TokenData = Depends(require_agent_or_admin),
):
    """
    Fingerprints autorizados ao cofre.

    O agente consulta antes de cada ciclo de upload; o admin usa para montar a
    tela. Não devolve material criptográfico, só a lista de autorizações.
    """
    return {"fingerprints": cert_installer.listar_optin_fingerprints(machine_id)}


@app.post("/api/cert-installer/vault-optin", dependencies=[Depends(require_admin)])
def autorizar_vault_optin(
    body: VaultOptinRequest,
    token: auth.TokenData = Depends(require_admin),
):
    """Autoriza um certificado a ser copiado para o cofre do servidor."""
    try:
        cert_installer.autorizar_no_cofre(
            fingerprint=body.fingerprint,
            enabled_by=token.email or "desconhecido",
            machine_id=body.machine_id,
            nome_titular=body.nome_titular,
            documento=body.documento,
        )
        return {"status": "ok", "fingerprint": body.fingerprint}
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception:
        logger.exception("Erro ao autorizar certificado no cofre")
        raise HTTPException(status_code=500, detail="Erro interno ao autorizar")


@app.delete("/api/cert-installer/vault-optin/{fingerprint}", dependencies=[Depends(require_admin)])
def revogar_vault_optin(
    fingerprint: str,
    machine_id: str = Query(..., min_length=1),
):
    """
    Revoga a autorização e APAGA o PFX já armazenado — de UMA estação.

    O `machine_id` é obrigatório: desde a chave composta `(machine_id,
    fingerprint)`, o mesmo certificado pode estar autorizado em várias estações,
    e a rota não tem como adivinhar qual delas o admin quer revogar. Sem o
    parâmetro a chamada é recusada, em vez de apagar o material de todas.
    """
    try:
        cert_installer.revogar_do_cofre(fingerprint, machine_id)
        return {
            "status": "ok",
            "fingerprint": fingerprint,
            "machine_id": machine_id,
            "pfx_removido": True,
        }
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception:
        logger.exception("Erro ao revogar certificado do cofre")
        raise HTTPException(status_code=500, detail="Erro interno ao revogar")


class PrepareInstallRequest(BaseModel):
    """Admin seleciona certificados e máquina destino."""
    certificate_ids: List[str]
    target_machine: str


@app.post("/api/cert-installer/prepare")
def prepare_install(
    body: PrepareInstallRequest,
    request: Request,
    token: auth.TokenData = Depends(require_admin),
):
    """
    Gera token de uso único e enfileira comando de instalação na fila do agente.
    Apenas admins podem solicitar instalação.
    """
    if not body.certificate_ids:
        raise HTTPException(status_code=400, detail="Selecione ao menos um certificado")

    # Buscar user_id real (para tokens criados com JWT)
    user_id = _resolve_user_id(token.email)
    if not user_id:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")

    client_ip = request.client.host if request.client else None

    try:
        # 1. Criar token
        token_raw, token_id, expires_at = cert_installer.create_install_token(
            user_id=user_id,
            user_email=token.email,
            target_machine=body.target_machine,
            certificate_ids=body.certificate_ids,
            client_ip=client_ip,
        )

        # 2. Log SOLICITADO para cada certificado
        for cid in body.certificate_ids:
            cert_installer.log_event(
                event="SOLICITADO",
                user_id=user_id,
                user_email=token.email,
                token_id=token_id,
                certificate_id=cid,
                target_machine=body.target_machine,
                client_ip=client_ip,
            )

        # 3. Enfileirar comando na agent_command_queue
        cmd_id = cert_installer.enqueue_install_command(
            target_machine=body.target_machine,
            token_raw=token_raw,
        )

        return {
            "status": "ok",
            "token_id": token_id,
            "command_id": cmd_id,
            "target_machine": body.target_machine,
            "certificates_count": len(body.certificate_ids),
            "expires_at": expires_at.isoformat(),
        }
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception:
        logger.exception("Erro ao preparar instalação")
        raise HTTPException(status_code=500, detail="Erro interno ao preparar instalação")


class RedeemRequest(BaseModel):
    """Payload enviado pelo agente para resgatar o bundle criptografado."""
    token: str
    clientPublicKey: str  # SPKI base64 (ECDH P-256)


@app.post("/api/cert-installer/redeem")
def redeem_install(
    body: RedeemRequest,
    request: Request,
    _token: auth.TokenData = Depends(require_agent_or_admin),
):
    """
    Agente consome o token e recebe o bundle de certificados criptografado via ECDH.
    """
    client_ip = request.client.host if request.client else None

    # 1. Validar e consumir token
    token_data = cert_installer.validate_and_consume_token(body.token)
    if not token_data:
        raise HTTPException(status_code=403, detail="Token inválido, expirado ou já consumido")

    user_id = token_data["user_id"]
    token_id = str(token_data["id"])
    cert_ids = token_data.get("certificate_ids") or []

    # 2. Log REDIMIDO
    cert_installer.log_event(
        event="REDIMIDO",
        user_id=user_id,
        user_email=token_data.get("user_email"),
        token_id=token_id,
        target_machine=token_data.get("target_machine"),
        client_ip=client_ip,
    )

    # 3. Montar bundle criptografado
    try:
        bundle = cert_installer.build_encrypted_bundle(
            certificate_ids=cert_ids,
            client_public_key_b64=body.clientPublicKey,
        )
        return bundle
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception:
        logger.exception("Erro ao montar bundle criptografado")
        raise HTTPException(status_code=500, detail="Erro interno ao montar bundle")


# ── Instalador avulso (modelo Ninite) ─────────────────────────────────────
#
# O agente resgata em /redeem autenticando-se com X-API-Key. O instalador que o
# usuário baixa não pode fazer o mesmo: embutir a API key no executável seria
# distribuí-la a todos que baixassem — e ela abre todas as rotas do agente.
#
# Aqui o próprio token É a credencial, como numa URL de download assinada. Isso
# se sustenta porque ele é de uso único (compare-and-swap em
# validate_and_consume_token), expira em CERT_INSTALL_TOKEN_TTL_MIN minutos, e
# só libera os certificate_ids gravados nele. O que falta a um bearer assim é
# resistência a força bruta, daí o limite por IP abaixo.

_CLAIM_JANELA_SEC = 60
_CLAIM_MAX_POR_JANELA = 10
_claim_tentativas: dict[str, list[float]] = {}
_claim_lock = threading.Lock()


def _claim_rate_limit(ip: str) -> bool:
    """True se o IP ainda pode tentar. Janela deslizante em memória."""
    agora = time.time()
    with _claim_lock:
        tentativas = [t for t in _claim_tentativas.get(ip, []) if agora - t < _CLAIM_JANELA_SEC]
        if len(tentativas) >= _CLAIM_MAX_POR_JANELA:
            _claim_tentativas[ip] = tentativas
            return False
        tentativas.append(agora)
        _claim_tentativas[ip] = tentativas
        # A limpeza oportunista evita o dicionário crescer sem limite com IPs
        # que apareceram uma vez. Barato: só roda quando o mapa já está grande.
        if len(_claim_tentativas) > 1000:
            for k in [k for k, v in _claim_tentativas.items()
                      if not v or agora - v[-1] > _CLAIM_JANELA_SEC]:
                _claim_tentativas.pop(k, None)
        return True


@app.post("/api/cert-installer/claim")
def claim_install(body: RedeemRequest, request: Request):
    """
    Resgate SEM API key, para o instalador avulso. O token é a credencial.

    Deliberadamente não distingue token inválido de expirado ou já consumido:
    a resposta única evita virar oráculo de tokens válidos.
    """
    client_ip = request.client.host if request.client else "desconhecido"

    if not _claim_rate_limit(client_ip):
        raise HTTPException(status_code=429, detail="Muitas tentativas. Aguarde um minuto.")

    token_data = cert_installer.validate_and_consume_token(body.token)
    if not token_data:
        raise HTTPException(status_code=403, detail="Token inválido, expirado ou já utilizado")

    cert_installer.log_event(
        event="REDIMIDO",
        user_id=token_data["user_id"],
        user_email=token_data.get("user_email"),
        token_id=str(token_data["id"]),
        target_machine=token_data.get("target_machine"),
        client_ip=client_ip,
        detail="instalador avulso",
    )

    try:
        return cert_installer.build_encrypted_bundle(
            certificate_ids=token_data.get("certificate_ids") or [],
            client_public_key_b64=body.clientPublicKey,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception:
        logger.exception("Erro ao montar bundle para instalador avulso")
        raise HTTPException(status_code=500, detail="Erro interno ao montar bundle")


class PrepararDownloadRequest(BaseModel):
    """Admin escolhe os certificados e recebe o link do instalador."""
    certificate_ids: List[str]
    nome: Optional[str] = None


@app.post("/api/cert-installer/preparar-download")
def preparar_download(
    body: PrepararDownloadRequest,
    request: Request,
    token: auth.TokenData = Depends(require_admin),
):
    """
    Cria o token e devolve a URL do instalador — sem enfileirar nada.

    Difere de /prepare no destino: lá o alvo é uma máquina que já roda o agente,
    e o comando vai para a fila dela. Aqui o alvo é a máquina de quem clicou,
    que não tem agente nenhum; o "transporte" é o próprio download.
    """
    if not body.certificate_ids:
        raise HTTPException(status_code=400, detail="Selecione ao menos um certificado")

    user_id = _resolve_user_id(token.email)
    if not user_id:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")

    client_ip = request.client.host if request.client else None

    try:
        token_raw, token_id, expires_at = cert_installer.create_install_token(
            user_id=user_id,
            user_email=token.email,
            # Não há máquina alvo conhecida: quem executar o instalador define
            # onde o certificado entra. Fica registrado como tal na auditoria.
            target_machine="download-avulso",
            certificate_ids=body.certificate_ids,
            client_ip=client_ip,
        )
        for cid in body.certificate_ids:
            cert_installer.log_event(
                event="SOLICITADO",
                user_id=user_id,
                user_email=token.email,
                token_id=token_id,
                certificate_id=cid,
                target_machine="download-avulso",
                client_ip=client_ip,
            )
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception:
        logger.exception("Erro ao preparar download do instalador")
        raise HTTPException(status_code=500, detail="Erro interno ao preparar instalador")

    nome = quote((body.nome or "Certificado")[:60])
    return {
        "status": "ok",
        "download_url": f"/instalador/baixar/{token_raw}?nome={nome}",
        "expires_at": expires_at.isoformat(),
        "validade_min": config.CERT_INSTALL_TOKEN_TTL_MIN,
    }


# Onde o build deposita o instalador avulso já compilado.
INSTALADOR_AVULSO_EXE = ROOT / "dist" / "Instalar_Certificado.exe"

# Só o alfabeto de secrets.token_urlsafe. Serve para recusar, antes de tocar o
# disco, qualquer coisa que não tenha forma de token — inclusive travessia de
# caminho, já que o valor vai para o nome do arquivo servido.
_TOKEN_SEGURO = re.compile(r"^[A-Za-z0-9_-]{16,128}$")


@app.get("/instalador/baixar/{token}")
def baixar_instalador(token: str, nome: str = Query("Certificado")):
    """
    Serve o instalador avulso com o token no NOME do arquivo.

    O binário é sempre o mesmo — não é recompilado por download. Isso é o que
    permite assiná-lo uma vez e acumular reputação no SmartScreen; um executável
    gerado a cada clique seria inédito para o Windows em toda instalação, e o
    aviso de "aplicativo não reconhecido" apareceria justamente no fluxo que
    deveria ser de um clique só. O instalador lê o token do próprio argv[0].
    """
    if not _TOKEN_SEGURO.match(token):
        raise HTTPException(status_code=400, detail="Token malformado")

    if not INSTALADOR_AVULSO_EXE.is_file():
        raise HTTPException(
            status_code=503,
            detail="Instalador ainda não compilado no servidor. Rode scripts/build_instalador_avulso.ps1.",
        )

    seguro = re.sub(r"[^A-Za-z0-9 _-]", "", nome)[:60].strip() or "Certificado"
    return FileResponse(
        path=INSTALADOR_AVULSO_EXE,
        media_type="application/vnd.microsoft.portable-executable",
        filename=f"Instalar {seguro} -{token}.exe",
    )


class InstallResultItem(BaseModel):
    certificateId: str
    fingerprint: Optional[str] = None
    thumbprint: Optional[str] = None
    status: str  # "OK" | "FALHA"
    detail: Optional[str] = None


class ReportRequest(BaseModel):
    """Payload enviado pelo agente após instalar os certificados."""
    token: str
    results: List[InstallResultItem]


@app.post("/api/cert-installer/report")
def report_install(
    body: ReportRequest,
    request: Request,
    _token: auth.TokenData = Depends(require_agent_or_admin),
):
    """
    Agente reporta o resultado da instalação de cada certificado.
    """
    return _registrar_relatorio(body, request)


@app.post("/api/cert-installer/report-avulso")
def report_install_avulso(body: ReportRequest, request: Request):
    """
    Mesma gravação, para o instalador avulso — que não tem API key.

    Abrir a rota não afeta o gate real: `_registrar_relatorio` já exigia um
    token conhecido E já redimido, o que a dependência de autenticação apenas
    duplicava. O pior que um token vazado permite aqui é sujar a auditoria da
    própria instalação que ele representa; não devolve material criptográfico.
    """
    ip = request.client.host if request.client else "desconhecido"
    if not _claim_rate_limit(ip):
        raise HTTPException(status_code=429, detail="Muitas tentativas. Aguarde um minuto.")
    return _registrar_relatorio(body, request)


def _registrar_relatorio(body: ReportRequest, request: Request) -> dict:
    client_ip = request.client.host if request.client else None

    # Validar que o token existe e foi redimido (consumed_at != null)
    import hashlib
    token_hash = hashlib.sha256(body.token.encode()).hexdigest()
    from app.settings_state import _supabase
    sb = _supabase()
    if not sb:
        raise HTTPException(status_code=500, detail="Supabase não configurado")

    try:
        r = sb.table("install_token").select("*").eq("token_hash", token_hash).execute()
        rows = r.data or []
        if not rows:
            raise HTTPException(status_code=403, detail="Token desconhecido")
        token_row = rows[0]
        if not token_row.get("consumed_at"):
            raise HTTPException(status_code=403, detail="Token ainda não foi redimido")
    except HTTPException:
        raise
    except Exception:
        logger.exception("Erro ao verificar token no report")
        raise HTTPException(status_code=500, detail="Erro interno")

    user_id = token_row["user_id"]
    token_id = str(token_row["id"])

    # Gravar log para cada resultado
    for result in body.results:
        event = "CONCLUIDO" if result.status.upper() == "OK" else "ERRO"
        cert_installer.log_event(
            event=event,
            user_id=user_id,
            user_email=token_row.get("user_email"),
            token_id=token_id,
            certificate_id=result.certificateId,
            fingerprint=result.fingerprint,
            target_machine=token_row.get("target_machine"),
            status=result.status,
            detail=result.detail,
            client_ip=client_ip,
        )

    return {
        "status": "ok",
        "processed": len(body.results),
    }


# ── Endpoints auxiliares do instalador ────────────────────────────────────

@app.get("/api/cert-installer/available")
def list_available_certificates(
    machine_id: Optional[str] = Query(None),
    token: auth.TokenData = Depends(require_admin),
):
    """Lista certificados PFX disponíveis para instalação (sem dados cifrados)."""
    certs = cert_installer.list_available_pfx(machine_id=machine_id)
    return {
        "certificates": [
            {
                "id": c.id,
                "fingerprint": c.fingerprint,
                "machine_id": c.machine_id,
                "nome_titular": c.nome_titular,
                "documento": c.documento,
                "documento_tipo": c.documento_tipo,
                "subject": c.subject,
                "not_before": c.not_before,
                "not_after": c.not_after,
                "friendly_name": c.friendly_name,
                "uploaded_at": c.uploaded_at,
            }
            for c in certs
        ]
    }


@app.get("/api/cert-installer/logs")
def list_installer_logs(
    limit: int = Query(100, ge=1, le=500),
    token: auth.TokenData = Depends(require_admin),
):
    """Lista logs de auditoria de instalação."""
    logs = cert_installer.list_install_logs(limit=limit)
    return {"logs": logs}


@app.post("/api/cert-installer/cleanup")
def cleanup_tokens(token: auth.TokenData = Depends(require_admin)):
    """Remove tokens de instalação expirados (manutenção)."""
    count = cert_installer.cleanup_expired_tokens()
    return {"status": "ok", "removed": count}


def _resolve_user_id(email: str) -> Optional[str]:
    """Busca o UUID do usuário pelo email."""
    from app.settings_state import _supabase
    sb = _supabase()
    if not sb:
        return None
    try:
        r = sb.table("users").select("id").eq("email", email).limit(1).execute()
        if r.data:
            return str(r.data[0]["id"])
    except Exception:
        logger.exception("Erro ao resolver user_id para email=%s", email)
    return None


# ── Página HTML do Instalador ─────────────────────────────────────────────

@app.get("/instalador", response_class=HTMLResponse)
def page_instalador(request: Request) -> HTMLResponse:
    # Assinatura por keyword, igual às outras 8 rotas de página. A forma
    # posicional antiga — TemplateResponse(name, context) — quebra nesta versão
    # do Starlette com "TypeError: unhashable type: 'dict'", e a página do
    # módulo respondia 500 em toda requisição.
    # O nonce vem de request.state.nonce no template, como nos demais.
    return templates.TemplateResponse(
        request=request, name="instalador.html", context={"pagina_ativa": "instalador"}
    )

