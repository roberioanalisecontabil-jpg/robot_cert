"""Um PFX de verdade para os testes do cofre.

Desde o lote 2 da auditoria (#4) o servidor LÊ o PFX enviado em /upload-pfx:
o fingerprint declarado tem de ser o do certificado dentro dele, e os
metadados gravados são os do certificado. Quatro bytes em base64 deixaram de
servir como PFX; este módulo gera um autoassinado, com CN no padrão
ICP-Brasil "NOME:CNPJ", uma vez por processo.
"""

from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Any, Dict

DOC_PADRAO = "12345678000195"
SENHA_PADRAO = "abc123"


@lru_cache(maxsize=None)
def gerar_pfx(cnpj: str = DOC_PADRAO, senha: str = SENHA_PADRAO,
              nome: str = "EMPRESA TESTE LTDA", dias: int = 365) -> Dict[str, Any]:
    """Devolve {"b64", "bytes", "fingerprint", "not_after", "senha", "documento"}."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives.serialization import pkcs12
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    sujeito = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, f"{nome}:{cnpj}"),
        x509.NameAttribute(NameOID.COUNTRY_NAME, "BR"),
    ])
    agora = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(sujeito).issuer_name(sujeito).public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(agora - timedelta(days=1))
        .not_valid_after(agora + timedelta(days=dias))
        .sign(key, hashes.SHA256())
    )
    pfx = pkcs12.serialize_key_and_certificates(
        b"teste", key, cert, None, serialization.BestAvailableEncryption(senha.encode()),
    )
    return {
        "b64": base64.b64encode(pfx).decode(),
        "bytes": pfx,
        "fingerprint": cert.fingerprint(hashes.SHA256()).hex(),
        "not_after": cert.not_valid_after_utc,
        "senha": senha,
        "documento": cnpj,
    }
