import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent

CERT_SOURCE_DIR = Path(
    os.getenv("CERT_SOURCE_DIR", str(ROOT / "certificados"))
).resolve()

CERT_EXPIRED_DIR = Path(
    os.getenv("CERT_EXPIRED_DIR", str(ROOT / "certificados_vencidos"))
).resolve()

# Supabase (só no servidor; usados para config + snapshots ingeridos pelo agente)
SUPABASE_URL = (os.getenv("SUPABASE_URL") or "").strip()
SUPABASE_SERVICE_KEY = (os.getenv("SUPABASE_SERVICE_KEY") or "").strip()

# Se definida, todas as rotas /api/* exigem o header X-API-Key (exceto se documentado)
API_KEY = (os.getenv("API_KEY") or "").strip()


def _env_int(name: str, default: int, lo: int, hi: int) -> int:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        v = int(raw)
    except ValueError:
        return default
    return max(lo, min(hi, v))


# Máximo de linhas lidas na tabela cert_snapshots ao agregar histórico/vencidos (RAM ~ proporcional ao lote).


HISTORICO_LIMITE_SNAPSHOTS = _env_int(
    "HISTORICO_LIMITE_SNAPSHOTS",
    default=500,
    lo=1,
    hi=2000,
)

# Cache em RAM da agregação histórico/vencidos (segundos). 0 = desativado.


HISTORICO_CACHE_TTL_SEC = _env_int(
    "HISTORICO_CACHE_TTL_SEC",
    default=60,
    lo=0,
    hi=86400,
)

# ── Módulo Instalador de Certificados ──────────────────────────────────
# Chave AES-256 para cifrar/decifrar PFX em repouso no banco (hex, 64 chars = 32 bytes).
# Gere com: python -c "import secrets; print(secrets.token_hex(32))"
CERT_ENCRYPTION_KEY = (os.getenv("CERT_ENCRYPTION_KEY") or "").strip()

# TTL (minutos) dos tokens de instalação. Padrão: 5 min.
CERT_INSTALL_TOKEN_TTL_MIN = _env_int(
    "CERT_INSTALL_TOKEN_TTL_MIN",
    default=5,
    lo=1,
    hi=60,
)
