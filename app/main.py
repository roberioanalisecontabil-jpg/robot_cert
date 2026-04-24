from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel, Field

from app import config
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
    _supabase
)
from app.auth import (
    Token, UserCreate, verify_password, get_password_hash, create_access_token,
    get_user_from_db, create_user_in_db, SECRET_KEY, ALGORITHM
)
from jose import jwt, JWTError

logger = logging.getLogger(__name__)

app = FastAPI(title="Monitor de certificados PFX", version="1.2.0")

templates = Jinja2Templates(directory=str(ROOT / "templates"))
app.mount("/static", StaticFiles(directory=str(ROOT / "static")), name="static")


oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/login", auto_error=False)

async def get_current_user(token: Optional[str] = Depends(oauth2_scheme)) -> Optional[dict]:
    if not token:
        return None
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email: str = payload.get("email")
        role: str = payload.get("role")
        if email is None:
            return None
        return {"email": email, "role": role}
    except JWTError:
        return None

async def require_api_key(
    request: Request,
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    current_user: Optional[dict] = Depends(get_current_user)
) -> None:
    # 1. Tenta validar se há uma sessão JWT válida
    if current_user is not None:
        return

    # 2. Se não houver JWT, valida se há API_KEY e se confere com o arquivo .env
    if config.API_KEY and x_api_key == config.API_KEY:
        return
        
    # Se ambos falharem, ou se API_KEY não for enviada e não tiver JWT:
    if config.API_KEY:
         raise HTTPException(status_code=401, detail="X-API-Key ou Token ausente/inválida.")

def require_admin(current_user: Optional[dict] = Depends(get_current_user)):
    if not current_user or current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Apenas administradores podem realizar esta ação.")
    return current_user


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

@app.get("/login", response_class=HTMLResponse)
def pagina_login(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request=request, name="login.html")

@app.get("/usuarios", response_class=HTMLResponse)
def pagina_usuarios(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request=request, name="usuarios.html")

@app.get("/configuracao", response_class=HTMLResponse)
def pagina_configuracao(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request=request, name="configuracao.html")


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


@app.get("/api/settings", dependencies=[Depends(require_api_key)])
def get_settings() -> dict:
    s = load_settings()
    return _settings_dict(s)


@app.put("/api/settings", dependencies=[Depends(require_api_key)])
def put_settings(body: SettingsBody) -> dict:
    s = PortalSettings(
        source_folder=body.source_folder.strip(),
        expired_folder=body.expired_folder.strip(),
        machine_id=body.machine_id.strip() or "default",
    )
    save_settings(s)
    return _settings_dict(s)


@app.post("/api/agent/commands", dependencies=[Depends(require_api_key)])
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


@app.get("/api/agent/next", dependencies=[Depends(require_api_key)])
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


@app.get("/api/agent/queue", dependencies=[Depends(require_api_key)])
def agent_queue_list() -> dict:
    """Lista comandos ainda pendentes (monitorização no portal)."""
    return {"pendentes": list_pending(), "comandos_validos": sorted(COMMANDS)}


@app.get("/api/certificados", dependencies=[Depends(require_api_key)])
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


@app.post("/api/ingest", dependencies=[Depends(require_api_key)])
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

# ----------------- ROTAS DE USUÁRIO -----------------

@app.post("/api/login", response_model=Token)
def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends()):
    client = _supabase()
    if not client:
        raise HTTPException(status_code=500, detail="Supabase não configurado.")
    user = get_user_from_db(client, form_data.username) # OAuth2 form usa "username" que para nós será o e-mail
    if not user or not verify_password(form_data.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Email ou senha incorretos", headers={"WWW-Authenticate": "Bearer"})
    access_token = create_access_token(data={"email": user["email"], "role": user["role"]})
    return {"access_token": access_token, "token_type": "bearer"}

@app.get("/api/users", dependencies=[Depends(require_api_key), Depends(require_admin)])
def list_users():
    client = _supabase()
    if not client:
        raise HTTPException(status_code=500, detail="Supabase não configurado.")
    r = client.table("users").select("id, email, role, created_at").execute()
    return r.data

@app.post("/api/users", dependencies=[Depends(require_api_key), Depends(require_admin)])
def create_user(user: UserCreate):
    client = _supabase()
    if not client:
        raise HTTPException(status_code=500, detail="Supabase não configurado.")
    # Verifica se já existe
    exist = get_user_from_db(client, user.email)
    if exist:
        raise HTTPException(status_code=400, detail="Email já cadastrado.")
    novo = create_user_in_db(client, user)
    if not novo:
        raise HTTPException(status_code=500, detail="Falha ao criar usuário no banco.")
    return {"message": "Usuário criado com sucesso", "email": novo["email"]}

@app.delete("/api/users/{user_id}", dependencies=[Depends(require_api_key), Depends(require_admin)])
def delete_user(user_id: str):
    client = _supabase()
    if not client:
        raise HTTPException(status_code=500, detail="Supabase não configurado.")
    try:
        client.table("users").delete().eq("id", user_id).execute()
        return {"ok": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/mover-vencidos", dependencies=[Depends(require_api_key)])
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
