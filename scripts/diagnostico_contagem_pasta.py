"""
Contagem igual à do portal/agente sobre uma pasta local (somente .pfx/.p12).

Uso (na raiz do repo, com venv activo):

  python scripts/diagnostico_contagem_pasta.py "D:\\Certs"

Mostra por status — se muitos forem ``fora_do_padrao`` ou ``erro``, esse é o hiato
entre "ficheiros na pasta" e "certificados mapeados com vencimento".
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.cert_scanner import CertStatus, scan_folder


def main() -> None:
    ap = argparse.ArgumentParser(description="Diagnóstico de scan PFX/P12.")
    ap.add_argument("pasta", type=Path, help="Pasta raiz dos certificados")
    ap.add_argument(
        "--no-recursive",
        action="store_true",
        help="Só o primeiro nível (por defeito o scan é recursivo)",
    )
    ns = ap.parse_args()
    src = ns.pasta.resolve()
    if not src.is_dir():
        print(f"ERRO: não é pasta válida: {src}", file=sys.stderr)
        sys.exit(1)

    infos = scan_folder(src, recursive=not ns.no_recursive)
    by_status = Counter(c.status.value for c in infos)
    expired = sum(1 for c in infos if c.status == CertStatus.EXPIRED)

    print(f"Pasta      : {src}")
    print(f"Ficheiros  : {len(infos)} (.pfx ou .p12 encontrados pelo scan)")
    print(f"Vencidos   : {expired} (not_after UTC < agora, ficheiros abertos com sucesso)")
    print("Por status :")
    for k, v in sorted(by_status.items(), key=lambda x: (-x[1], x[0])):
        print(f"  {v:>5}  {k}")

    n_fora = by_status.get("fora_do_padrao", 0)
    n_erro = by_status.get("erro", 0)
    if n_fora or n_erro:
        print()
        print(
            "Dica: «fora_do_padrao» = nome não está no formato "
            "\"NomeExibicao senha ValorSenha.pfx\" (senha obrigatória na filename)."
        )
        print("      «erro» = falha ao abrir (senha errada ao nome, ficheiro corrompido, etc.).")


if __name__ == "__main__":
    main()
