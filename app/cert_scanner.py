from __future__ import annotations

import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Iterable, List, Optional

from cryptography.hazmat.primitives.serialization import pkcs12

# Padrão: "nome do certificado senha valorDaSenha.pfx" (ou .p12)
# A palavra-chave "senha" (case-insensitive) separa o nome lógico da senha.
# Aceita com ou sem espaço entre "senha" e o valor (ex.: "senha 123" ou "SENHA123").
PFX_NAME_PATTERN = re.compile(
    r"^(.+?)\s+senha\s*(.+?)\.(?:pfx|p12)$",
    re.IGNORECASE | re.DOTALL,
)

# CN= em RFC4514: primeiro atributo CN (caso comum sem vírgula no valor)
CN_VALUE_PATTERN = re.compile(
    r"(?i)CN=([^,]+?)(?=(,[^=+]+=)|$)",
)

# Padrão no CN: "RAZAO SOCIAL:14digitos" (CNPJ) ou "NOME:11digitos" (CPF)
NOME_CNPJ_CPF_IN_CN = re.compile(
    r"^(.+?):\s*(\d{11}|\d{14})$",
    re.DOTALL,
)


class CertStatus(str, Enum):
    OK = "ok"  # Dentro do prazo e arquivo válido
    EXPIRED = "expirado"
    OUT_OF_PATTERN = "fora_do_padrao"  # Nome não segue o padrão
    ERROR = "erro"  # Padrão ok mas não abre (senha errada, arquivo corrompido)


@dataclass
class CertInfo:
    path: Path
    file_name: str
    display_name: str
    status: CertStatus
    not_after: Optional[datetime] = None
    not_before: Optional[datetime] = None
    subject: Optional[str] = None
    # Extraído do CN quando no formato "NOME:CPF" ou "NOME:CNPJ"
    nome_titular: Optional[str] = None
    documento_numero: Optional[str] = None
    documento_tipo: Optional[str] = None  # "cnpj" | "cpf" | None
    error_message: Optional[str] = None
    password_from_name: Optional[str] = field(default=None, repr=False)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def extract_cn_rfc4514(rfc4514: Optional[str]) -> Optional[str]:
    """Devolve o valor do primeiro atributo CN, ou None."""
    if not rfc4514 or not rfc4514.strip():
        return None
    m = CN_VALUE_PATTERN.search(rfc4514.strip())
    if not m:
        return None
    return m.group(1).strip().replace(r"\,", ",")


def parse_nome_cnpj_cpf_from_cn(cn_value: Optional[str]) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """
    Interpreta o valor do CN no formato 'NOME:11 ou 14 dígitos' (ex.: ICP-Brasil e-CPF / e-CNPJ).
    Devolve (nome, só dígitos, 'cnpj'|'cpf'|None).
    """
    if not cn_value:
        return None, None, None
    s = cn_value.strip()
    m = NOME_CNPJ_CPF_IN_CN.match(s)
    if not m:
        return s, None, None
    nome, digits = m.group(1).strip(), m.group(2)
    if len(digits) == 14:
        return nome, digits, "cnpj"
    if len(digits) == 11:
        return nome, digits, "cpf"
    return s, None, None


def formatar_cnpj_cpf(digits: Optional[str], tipo: Optional[str]) -> str:
    if not digits or not tipo:
        return ""
    d = "".join(c for c in digits if c.isdigit())
    if tipo == "cnpj" and len(d) == 14:
        return f"{d[0:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:14]}"
    if tipo == "cpf" and len(d) == 11:
        return f"{d[0:3]}.{d[3:6]}.{d[6:9]}-{d[9:11]}"
    return digits


def parse_pfx_filename(file_name: str) -> Optional[tuple[str, str]]:
    """
    Extrai (nome amigável, senha) de '... senha <senha>.pfx'.
    Retorna None se o nome não segue o padrão.
    """
    m = PFX_NAME_PATTERN.match(file_name.strip())
    if not m:
        return None
    logical_name, password = m.group(1).strip(), m.group(2).strip()
    if not password:
        return None
    return logical_name, password


def _load_pfx_info(file_path: Path, password: str) -> tuple:
    data = file_path.read_bytes()
    _key, cert, _more = pkcs12.load_key_and_certificates(
        data,
        password.encode("utf-8"),
    )
    if cert is None:
        raise ValueError("PKCS#12 sem certificado (apenas chave).")
    subj = cert.subject.rfc4514_string() if cert.subject else None
    nb = cert.not_valid_before_utc
    na = cert.not_valid_after_utc
    return nb, na, subj


def _is_under(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def scan_folder(
    source_dir: Path,
    recursive: bool = True,
    exclude_dirs: Optional[Iterable[Path]] = None,
) -> List[CertInfo]:
    source_dir = Path(source_dir)
    if not source_dir.is_dir():
        return []

    results: List[CertInfo] = []
    now = _now_utc()
    excludes = [Path(p).resolve() for p in (exclude_dirs or [])]

    scan_iter = source_dir.rglob("*") if recursive else source_dir.iterdir()
    for p in sorted(scan_iter):
        if any(_is_under(p, ex) for ex in excludes):
            continue
        if not p.is_file():
            continue
        if p.suffix.lower() not in (".pfx", ".p12"):
            continue

        name = p.name
        parsed = parse_pfx_filename(name)

        if not parsed:
            results.append(
                CertInfo(
                    path=p,
                    file_name=name,
                    display_name=p.stem,
                    status=CertStatus.OUT_OF_PATTERN,
                    error_message="Nome deve seguir: «nome» senha «valor».pfx",
                )
            )
            continue

        logical, pwd = parsed
        info = CertInfo(
            path=p,
            file_name=name,
            display_name=logical,
            status=CertStatus.OK,
            password_from_name=pwd,
        )

        try:
            not_before, not_after, subj = _load_pfx_info(p, pwd)
            info.not_before = not_before
            info.not_after = not_after
            info.subject = subj
            cn = extract_cn_rfc4514(subj)
            nome, doc, tipo = parse_nome_cnpj_cpf_from_cn(cn)
            info.nome_titular = nome
            info.documento_numero = doc
            info.documento_tipo = tipo
            if not_after < now:
                info.status = CertStatus.EXPIRED
        except Exception as e:  # noqa: BLE001 — queremos exibir qualquer falha
            info.status = CertStatus.ERROR
            info.error_message = str(e) or repr(e)

        results.append(info)

    return results


def move_to_expired(
    cert: CertInfo,
    expired_dir: Path,
) -> Path:
    """Move o arquivo PFX para a pasta de vencidos. Retorna o novo caminho."""
    expired_dir = Path(expired_dir)
    expired_dir.mkdir(parents=True, exist_ok=True)
    dest = expired_dir / cert.file_name
    if dest.exists():
        stem = cert.path.stem
        dest = expired_dir / f"{stem}_dup_{int(_now_utc().timestamp())}.pfx"
    shutil.move(str(cert.path), str(dest))
    return dest


def cert_to_public_dict(c: CertInfo) -> dict:
    not_after = c.not_after
    not_before = c.not_before
    tipo = c.documento_tipo
    doc_fmt = formatar_cnpj_cpf(c.documento_numero, tipo) if tipo else None
    nome_exibir = c.nome_titular
    if not nome_exibir and c.status in (CertStatus.OK, CertStatus.EXPIRED, CertStatus.ERROR):
        nome_exibir = c.display_name
    if c.status == CertStatus.OUT_OF_PATTERN:
        nome_exibir = c.display_name
    if not nome_exibir:
        nome_exibir = c.path.stem
    if tipo == "cnpj":
        tipo_label = "CNPJ"
    elif tipo == "cpf":
        tipo_label = "CPF"
    else:
        tipo_label = None
    return {
        "file_name": c.file_name,
        "display_name": c.display_name,
        "path": str(c.path),
        "status": c.status.value,
        "not_before": not_before.isoformat() if not_before else None,
        "not_after": not_after.isoformat() if not_after else None,
        "nome": nome_exibir,
        "documento_tipo": tipo,
        "documento_tipo_label": tipo_label,
        "documento_formatado": doc_fmt,
        "documento_numero": c.documento_numero,
        "subject": c.subject,
        "error_message": c.error_message,
    }
