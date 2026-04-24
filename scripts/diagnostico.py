"""
Executar: python scripts/diagnostico.py
Mostra se pastas, .env e API estão coerentes (sem imprimir segredos).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")


def main() -> None:
    print("=== Diagnóstico cert_robot ===\n")
    print("1) API_KEY no .env:", "sim (rotas /api exigem X-API-Key)" if os.getenv("API_KEY", "").strip() else "não (API aberta)")
    print("2) SUPABASE:", "configurado" if os.getenv("SUPABASE_URL", "").strip() else "não (só ficheiros locais)")

    from app.settings_state import DATA_FILE, load_settings

    s = load_settings()
    src = s.effective_source()
    exp = s.effective_expired()
    print("\n3) Config (data/portal_settings.json ou Supabase):")
    print("   origem guardada:", (s.source_folder or "(vazio)"))
    print("   destino guardado:", (s.expired_folder or "(vazio)"))
    print("   origem efetiva:", src)
    print("   pasta origem existe?", "SIM" if src.is_dir() else "NÃO — ajuste em /configuracao")
    print("   destino efetivo:", exp)

    pfx = (list(src.glob("*.pfx")) + list(src.glob("*.p12"))) if src.is_dir() else []
    print("\n4) Ficheiros .pfx/.p12 na origem:", len(pfx))
    if not pfx:
        print("   (nenhum — coloque .pfx/.p12 com nome: «nome» senha «senha».pfx)")

    try:
        from fastapi.testclient import TestClient
        from app.main import app

        c = TestClient(app)
        assert c.get("/api/health").status_code == 200
        print("\n5) GET /api/health: OK")
        key = os.getenv("API_KEY", "").strip()
        if key:
            r = c.get("/api/settings", headers={"X-API-Key": key})
            print("6) GET /api/settings com chave do .env:", r.status_code)
            r2 = c.get("/api/certificados?fonte=local", headers={"X-API-Key": key})
            n = len(r2.json().get("itens", [])) if r2.status_code == 200 else -1
            print("7) GET /api/certificados?fonte=local — itens:", n)
        else:
            r2 = c.get("/api/certificados?fonte=local")
            n = len(r2.json().get("itens", [])) if r2.status_code == 200 else -1
            print("7) GET /api/certificados?fonte=local — itens:", n)
    except Exception as e:
        print("\nErro ao testar API:", e)

    print("\n=== Fim ===")


if __name__ == "__main__":
    main()
