"""Regrava a senha SMTP cifrada com a ENCRYPTION_KEY atual.

Quando usar
-----------
- ao definir a ENCRYPTION_KEY pela primeira vez, se já havia senha gravada com
  a chave antiga derivada da JWT_SECRET_KEY;
- ao trocar a ENCRYPTION_KEY (rotação de segredo).

A senha SMTP não é recuperável a partir do banco depois que a chave muda: o
ciphertext continua lá, mas nada o decifra. Por isso o caminho é redigitar a
senha, não "migrar" o valor antigo.

Uso:
    python scripts/rotate_smtp_password.py            # pede a senha oculta
    python scripts/rotate_smtp_password.py --dry-run  # só mostra o que faria

O script NÃO imprime a senha nem o ciphertext.
"""

from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    print("python-dotenv não instalado. Rode: pip install -r requirements.txt")
    raise SystemExit(1)

load_dotenv(RAIZ / ".env")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="verifica o ambiente e mostra o que seria feito, sem gravar",
    )
    args = p.parse_args()

    from app import smtp_service
    from app.settings_state import load_settings, save_settings, _supabase

    # 1. A chave precisa existir e ser válida ANTES de pedir a senha — não faz
    #    sentido o usuário digitar para descobrir depois que não dá para cifrar.
    try:
        smtp_service.verificar_chave_configurada()
    except RuntimeError as e:
        print("ERRO: " + str(e))
        return 1
    print("ENCRYPTION_KEY: válida.")

    # 2. Onde a configuração vive. Sem Supabase, grava só no arquivo local — o
    #    que num deploy serverless significa que a gravação não persiste.
    tem_banco = _supabase() is not None
    print(f"Supabase: {'configurado' if tem_banco else 'NÃO configurado (grava só em data/)'}")
    if not tem_banco:
        print(
            "AVISO: sem Supabase a senha vai para data/portal_settings.json. "
            "Em Vercel/Render o filesystem é efêmero ou read-only e isso se perde."
        )

    s = load_settings()
    print(f"smtp_host atual: {s.smtp_host or '(vazio)'}")
    print(f"smtp_user atual: {s.smtp_user or '(vazio)'}")
    print(f"senha cifrada atual: {'presente' if s.smtp_password_encrypted else 'ausente'}")

    if s.smtp_password_encrypted:
        atual = smtp_service.decrypt_password(s.smtp_password_encrypted)
        if atual:
            print("A senha gravada ainda é decifrável com a chave atual.")
            print("Rotacionar mesmo assim é seguro, mas talvez não seja necessário.")
        else:
            print("A senha gravada NÃO é decifrável com a chave atual — rotação necessária.")

    if args.dry_run:
        print("\n--dry-run: nada gravado.")
        return 0

    # 3. Senha nova, digitada duas vezes e nunca ecoada.
    senha = getpass.getpass("Senha SMTP (não aparece): ")
    if not senha:
        print("Senha vazia — nada feito.")
        return 1
    confirma = getpass.getpass("Repita a senha: ")
    if senha != confirma:
        print("As senhas não conferem — nada feito.")
        return 1

    cifrada = smtp_service.encrypt_password(senha)

    # 4. Conferência antes de persistir: cifrar e decifrar tem de dar a volta.
    if smtp_service.decrypt_password(cifrada) != senha:
        print("ERRO: a senha cifrada não decifrou de volta. Nada gravado.")
        return 1

    s.smtp_password_encrypted = cifrada
    save_settings(s)

    # 5. Reler do armazenamento — save_settings engole falhas do Supabase e só
    #    loga, então "não levantou" não é prova de que gravou.
    depois = load_settings()
    if smtp_service.decrypt_password(depois.smtp_password_encrypted) != senha:
        print(
            "ERRO: a senha não voltou corretamente do armazenamento. "
            "Verifique se a tabela portal_settings tem as colunas SMTP "
            "(migration 20260620_add_smtp_settings.sql)."
        )
        return 1

    print("Senha SMTP regravada e conferida com sucesso.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
