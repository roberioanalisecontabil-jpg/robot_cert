from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app import auth, config
from app.cert_scanner import CertInfo, CertStatus, cert_to_public_dict, move_to_expired, scan_folder
from app.command_queue import COMMANDS, enqueue, list_pending, pop_next_for_agent
from app.config import ROOT
from app.settings_state import (
    PortalSettings,
    get_latest_snapshot,
    load_settings,
    save_settings,
    save_snapshot,
    supabase_configured,
)

security = HTTPBearer(auto_error=False)

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
        return auth.TokenData(email="anonymous@local", role="agent")

    raise HTTPException(
        status_code=401, 
        detail="Não autorizado. Faça login ou forneça uma chave de API válida.",
        headers={"WWW-Authenticate": "Bearer"},
    )

async def require_admin(token: auth.TokenData = Depends(require_auth)) -> auth.TokenData:
    if token.role != "admin":
        raise HTTPException(status_code=403, detail="Acesso restrito a administradores.")
    return token

logger = logging.getLogger(__name__)

app = FastAPI(title="Monitor de certificados PFX", version="1.2.0")

templates = Jinja2Templates(directory=str(ROOT / "templates"))
app.mount("/static", StaticFiles(directory=str(ROOT / "static")), name="static")


# As funções require_api_key foram removidas em favor do require_auth híbrido.


def _response_from_rows(
    source_dir: str,
    expired_dir: str,
    scanned_at: str,
    items: List[dict],
    data_source: str,
    machine_id: Optional[str] = None,
) -> JSONResponse:
    return JSONResponse(
        {
            "source_dir": source_dir,
            "expired_dir": expired_dir,
            "atualizado_em": scanned_at,
            "itens": items,
            "data_source": data_source,
            "machine_id": machine_id,
            "supabase": supabase_configured(),
        }
    )


def _list_from_snapshot(snap: dict) -> JSONResponse:
    return _response_from_rows(
        source_dir=str(snap.get("source_folder", "") or ""),
        expired_dir=str(snap.get("expired_folder", "") or ""),
        scanned_at=snap.get("scanned_at", datetime.now(timezone.utc).isoformat()),
        items=snap.get("items", []) or [],
        data_source="remoto",
        machine_id=snap.get("machine_id"),
    )


def _list_local(sets: PortalSettings) -> JSONResponse:
    src = sets.effective_source()
    exp = sets.effective_expired()
    itens: List[CertInfo] = scan_folder(src)
    return _response_from_rows(
        source_dir=str(src),
        expired_dir=str(exp),
        scanned_at=datetime.now(timezone.utc).isoformat(),
        items=[cert_to_public_dict(c) for c in itens],
        data_source="local",
        machine_id=sets.machine_id,
    )


class SettingsBody(BaseModel):
    source_folder: str = Field(default="", description="Pasta de certificados no Windows (caminho completo)")
    expired_folder: str = Field(default="", description="Pasta destino dos vencidos")
    machine_id: str = Field(default="default", description="Identificador lógico da máquina / agente")


class IngestBody(BaseModel):
    machine_id: str = "default"
    source_folder: str
    expired_folder: str
    items: List[dict] = Field(default_factory=list)
    scanned_at: Optional[str] = None


class EnqueueCommandBody(BaseModel):
    machine_id: str = "default"
    command: str = Field(..., description="mover_vencidos | rescan | ping")


@app.get("/", response_class=HTMLResponse)
def painel(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request=request, name="index.html")


@app.get("/configuracao", response_class=HTMLResponse)
def pagina_configuracao(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request=request, name="configuracao.html")


@app.get("/login", response_class=HTMLResponse)
def pagina_login(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request=request, name="login.html")


@app.get("/usuarios", response_class=HTMLResponse)
def pagina_usuarios(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request=request, name="usuarios.html")


@app.get("/historico", response_class=HTMLResponse)
def pagina_historico(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request=request, name="historico.html")


@app.get("/vencidos", response_class=HTMLResponse)
def pagina_vencidos(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request=request, name="vencidos.html")


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
    return {
        "ok": True,
        "supabase": supabase_configured(),
        "api_key_required": bool(config.API_KEY),
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
    }


@app.get("/api/settings", dependencies=[Depends(require_auth)])
def get_settings() -> dict:
    s = load_settings()
    return _settings_dict(s)


@app.put("/api/settings", dependencies=[Depends(require_auth)])
def put_settings(body: SettingsBody) -> dict:
    s = PortalSettings(
        source_folder=body.source_folder.strip(),
        expired_folder=body.expired_folder.strip(),
        machine_id=body.machine_id.strip() or "default",
    )
    save_settings(s)
    return _settings_dict(s)


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
    return {"command": q.command, "id": q.id, "machine_id": q.machine_id}


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
) -> JSONResponse:
    """
    * auto: usa o último snapshot ingerido se existir; senão leitura local.
    * remoto: só snapshot (404 se vazio).
    * local: sempre leitura no disco do servidor (pastas efetivas da config).
    """
    try:
        sets = load_settings()
        snap = get_latest_snapshot()

        if fonte == "local":
            return _list_local(sets)

        if fonte == "remoto":
            if not snap:
                raise HTTPException(
                    status_code=404,
                    detail="Nenhum dado remoto. Configure o agente no Windows para enviar leituras.",
                )
            return _list_from_snapshot(snap)

        # auto
        if snap:
            return _list_from_snapshot(snap)
        return _list_local(sets)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Erro em GET /api/certificados (fonte=%s)", fonte)
        raise HTTPException(
            status_code=500,
            detail="Falha ao listar certificados. Veja o terminal do uvicorn. Resumo: " + str(e),
        ) from e


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


@app.get("/api/certificados/historico", dependencies=[Depends(require_auth)])
def historico_certificados(
    limite_snapshots: int = Query(500, ge=1, le=2000, description="Quantidade máxima de snapshots lidos"),
) -> dict:
    """
    Lista certificados já mapeados em algum momento, com a última data registrada.
    """
    from app.settings_state import _supabase

    snapshots: List[dict[str, Any]] = []
    sb = _supabase()
    if sb:
        try:
            r = (
                sb.table("cert_snapshots")
                .select("scanned_at, items")
                .order("scanned_at", desc=True)
                .limit(limite_snapshots)
                .execute()
            )
            snapshots = r.data or []
        except Exception as e:  # noqa: BLE001
            logger.exception("Falha ao ler histórico no Supabase")
            raise HTTPException(status_code=500, detail=f"Falha ao ler histórico: {e}") from e
    else:
        snap = get_latest_snapshot()
        if snap:
            snapshots = [snap]

    agregados: Dict[str, dict] = {}
    for snap in snapshots:
        scanned_at = snap.get("scanned_at") or datetime.now(timezone.utc).isoformat()
        scanned_dt = _parse_iso_utc(scanned_at)
        for it in (snap.get("items") or []):
            file_name = str(it.get("file_name") or "").strip()
            if not file_name:
                continue
            key = file_name.lower()
            atual = agregados.get(key)
            if (not atual) or (scanned_dt > atual["_dt"]):
                agregados[key] = {
                    "_dt": scanned_dt,
                    "file_name": file_name,
                    "nome": it.get("nome") or it.get("display_name") or file_name,
                    "status_ultimo": it.get("status"),
                    "documento": it.get("documento_formatado") or it.get("documento_numero"),
                    "vencimento_certificado": it.get("not_after"),
                    "ultima_data_registrada": scanned_dt.isoformat(),
                }

    itens = sorted(agregados.values(), key=lambda x: x["_dt"], reverse=True)
    for row in itens:
        row.pop("_dt", None)
    return {"itens": itens, "total": len(itens), "snapshots_lidos": len(snapshots)}


@app.get("/api/certificados/vencidos", dependencies=[Depends(require_auth)])
def vencidos_certificados(
    data_inicio: Optional[str] = Query(None, description="Data inicial (YYYY-MM-DD) pelo vencimento"),
    data_fim: Optional[str] = Query(None, description="Data final (YYYY-MM-DD) pelo vencimento"),
    limite_snapshots: int = Query(500, ge=1, le=2000, description="Quantidade máxima de snapshots lidos"),
) -> dict:
    hist = historico_certificados(limite_snapshots=limite_snapshots)
    itens = hist.get("itens", [])
    inicio_dt = _parse_iso_utc(data_inicio + "T00:00:00+00:00") if data_inicio else None
    fim_dt = _parse_iso_utc(data_fim + "T23:59:59+00:00") if data_fim else None

    vencidos: List[dict] = []
    for it in itens:
        if str(it.get("status_ultimo") or "").lower() != "expirado":
            continue
        venc_dt = _parse_iso_utc(it.get("vencimento_certificado"))
        if inicio_dt and venc_dt < inicio_dt:
            continue
        if fim_dt and venc_dt > fim_dt:
            continue
        vencidos.append(it)

    return {
        "itens": vencidos,
        "total": len(vencidos),
        "data_inicio": data_inicio,
        "data_fim": data_fim,
        "snapshots_lidos": hist.get("snapshots_lidos", 0),
    }


@app.post("/api/ingest", dependencies=[Depends(require_auth)])
def ingest(body: IngestBody) -> dict:
    """
    Recebe o resultado de um scan feito no Windows (agente em segundo plano).
    Persiste no Supabase (ou em data/last_ingest.json se o Supabase não estiver configurado).
    """
    save_snapshot(
        machine_id=body.machine_id.strip() or "default",
        source_folder=body.source_folder.strip(),
        expired_folder=body.expired_folder.strip(),
        items=body.items,
    )
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


@app.on_event("startup")
def _startup() -> None:
    config.CERT_SOURCE_DIR.mkdir(parents=True, exist_ok=True)
    config.CERT_EXPIRED_DIR.mkdir(parents=True, exist_ok=True)
