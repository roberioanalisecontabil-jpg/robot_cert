from __future__ import annotations

import logging
import csv
import io
import json
import re
import unicodedata
from collections import defaultdict
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional, Tuple

from fastapi import Depends, FastAPI, File, Header, HTTPException, Query, Request, UploadFile
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
    load_colaborador_selecao,
    load_settings,
    save_colaborador_selecao,
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


@app.get("/duplicidades", response_class=HTMLResponse)
def pagina_duplicidades(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request=request, name="duplicidades.html")


@app.get("/colaborador-certificados", response_class=HTMLResponse)
def pagina_colaborador_certificados(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request=request, name="colaborador_certificados.html")


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
    hist = historico_certificados(limite_snapshots=2000)
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
        status = "vencido" if str(it.get("status_ultimo") or "").lower() == "expirado" else "ativo"
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
    return {"itens": itens, "total": len(itens)}


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
