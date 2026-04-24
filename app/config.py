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
