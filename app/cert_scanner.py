from __future__ import annotations

import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import logging
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

logger = logging.getLogger(__name__)

from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import ExtensionOID, NameOID

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
    # Campos lido(s) do X.509 (para duplicidade / auditoria)
    issuer: Optional[str] = None
    serial_number_hex: Optional[str] = None
    # Fingerprint SHA-256 (hex) do certificado = hash do DER (cryptography: cert.fingerprint(SHA256)).
    fingerprint_sha256: Optional[str] = None
    # Extraído do CN quando no formato "NOME:CPF" ou "NOME:CNPJ"
    nome_titular: Optional[str] = None
    documento_numero: Optional[str] = None
    documento_tipo: Optional[str] = None  # "cnpj" | "cpf" | None
    error_message: Optional[str] = None
    password_from_name: Optional[str] = field(default=None, repr=False)
    # Campos ICP-Brasil (06/10/2026, modal de detalhes): ver `campos_icp`.
    # Dados pessoais do responsável — o portal só os mostra a quem pode
    # instalar o certificado; a lista do Início não os devolve.
    icp: dict = field(default_factory=dict)


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


def _abrir_pfx(file_path: Path, password: str) -> x509.Certificate:
    _key, cert, _more = pkcs12.load_key_and_certificates(
        file_path.read_bytes(),
        password.encode("utf-8"),
    )
    if cert is None:
        raise ValueError("PKCS#12 sem certificado (apenas chave).")
    return cert


# ── Campos ICP-Brasil (DOC-ICP-04) ────────────────────────────────────────
#
# No SubjectAltName, como otherName:
#   2.16.76.1.3.1  e-CPF: nascimento DDMMAAAA + CPF + NIS + RG + órgão/UF
#   2.16.76.1.3.2  e-CNPJ: nome do responsável
#   2.16.76.1.3.4  e-CNPJ: dados do responsável, mesmo leiaute do 3.1
# Campo não informado vem preenchido com zeros.
OID_PF_DADOS = "2.16.76.1.3.1"
OID_PJ_RESPONSAVEL_NOME = "2.16.76.1.3.2"
OID_PJ_RESPONSAVEL_DADOS = "2.16.76.1.3.4"


def _texto_do_der(valor: bytes) -> Optional[str]:
    """Conteúdo de um TLV DER de string (OCTET, Printable, UTF8, IA5...)."""
    try:
        if len(valor) < 2:
            return None
        n = valor[1]
        ini = 2
        if n & 0x80:
            k = n & 0x7F
            if k == 0 or k > 4 or len(valor) < 2 + k:
                return None
            n = int.from_bytes(valor[2:2 + k], "big")
            ini = 2 + k
        bruto = valor[ini:ini + n]
        if len(bruto) != n:
            return None
        try:
            return bruto.decode("utf-8").strip()
        except UnicodeDecodeError:
            return bruto.decode("latin-1").strip()
    except Exception:  # noqa: BLE001 — campo torto não derruba a leitura
        return None


def _so_digitos(t: Optional[str]) -> str:
    return "".join(c for c in (t or "") if c.isdigit())


def _dados_pf(texto: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """(nascimento ISO, CPF) do bloco "DDMMAAAA + CPF + ..."; zeros → None."""
    t = (texto or "").strip()
    nasc, cpf = t[:8], t[8:19]
    data_iso = None
    if len(nasc) == 8 and nasc.isdigit() and nasc != "0" * 8:
        try:
            data_iso = datetime.strptime(nasc, "%d%m%Y").date().isoformat()
        except ValueError:
            data_iso = None
    cpf_ok = cpf if (len(cpf) == 11 and cpf.isdigit() and cpf != "0" * 11) else None
    return data_iso, cpf_ok


def _primeiro_atributo(nome: Optional[x509.Name], oid) -> Optional[str]:
    if nome is None:
        return None
    attrs = nome.get_attributes_for_oid(oid)
    return str(attrs[0].value).strip() if attrs else None


def campos_icp(cert: x509.Certificate) -> dict:
    """Campos do modal de detalhes, lidos do certificado. Ausente = None."""
    cn = _primeiro_atributo(cert.subject, NameOID.COMMON_NAME)
    titular, _doc, tipo = parse_nome_cnpj_cpf_from_cn(cn)
    outros: dict = {}
    emails: List[str] = []
    try:
        san = cert.extensions.get_extension_for_oid(ExtensionOID.SUBJECT_ALTERNATIVE_NAME).value
        for o in san.get_values_for_type(x509.OtherName):
            outros.setdefault(o.type_id.dotted_string, _texto_do_der(o.value))
        emails = [e.strip() for e in san.get_values_for_type(x509.RFC822Name) if e and e.strip()]
    except x509.ExtensionNotFound:
        pass
    except Exception:  # noqa: BLE001 — SAN torto: segue com o que o sujeito dá
        logger.warning("SubjectAltName ilegível em %s", cn)

    if tipo == "cpf":
        nasc, cpf = _dados_pf(outros.get(OID_PF_DADOS))
        resp_nome = titular
    else:
        nasc, cpf = _dados_pf(outros.get(OID_PJ_RESPONSAVEL_DADOS))
        resp_nome = (outros.get(OID_PJ_RESPONSAVEL_NOME) or "").strip() or None
    return {
        "tipo_icp": "e-CPF" if tipo == "cpf" else "e-CNPJ" if tipo == "cnpj" else None,
        "organizacao": _primeiro_atributo(cert.subject, NameOID.ORGANIZATION_NAME),
        "emissor": _primeiro_atributo(cert.issuer, NameOID.COMMON_NAME),
        "responsavel_nome": resp_nome,
        "responsavel_cpf": cpf,
        "responsavel_nascimento": nasc,
        "email": emails[0] if emails else None,
    }


def _load_pfx_info(file_path: Path, password: str) -> Tuple[datetime, datetime, str, str, str, str]:
    return _info_do_certificado(_abrir_pfx(file_path, password))


def _info_do_certificado(cert: x509.Certificate) -> Tuple[datetime, datetime, str, str, str, str]:
    subj = cert.subject.rfc4514_string() if cert.subject else None
    iss = cert.issuer.rfc4514_string() if cert.issuer else ""
    nb = cert.not_valid_before_utc
    na = cert.not_valid_after_utc
    # Fingerprint padrão (SHA-256 do DER) — mesmo critério que openssl x509 -fingerprint -sha256
    fp = cert.fingerprint(hashes.SHA256()).hex()
    serial_hex = f"{cert.serial_number:X}".lower() if cert.serial_number is not None else ""
    return nb, na, subj, iss, fp, serial_hex


def _is_under(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


# Tetos da varredura (SECURITY_AUDIT #16): apontar a origem para `C:\` fazia
# um `rglob` do disco inteiro. A pasta real tem ~1.000 arquivos em 3 níveis.
LIMITE_ARQUIVOS_VARREDURA = 20000
PROFUNDIDADE_MAX_VARREDURA = 8


def _candidatos(
    source_dir: Path,
    recursive: bool,
    excludes: List[Path],
    limite_arquivos: int,
    profundidade_max: int,
) -> List[Path]:
    """Os .pfx/.p12 sob `source_dir`, até o teto de arquivos e de profundidade.

    `os.walk` em vez de `rglob`: dá para PODAR a descida (profundidade,
    pastas excluídas) em vez de enumerar tudo e filtrar depois.
    """
    import os

    achados: List[Path] = []
    base = len(source_dir.parts)
    for raiz, dirs, arquivos in os.walk(source_dir):
        raiz_p = Path(raiz)
        profundidade = len(raiz_p.parts) - base
        if not recursive or profundidade >= profundidade_max:
            dirs[:] = []
        else:
            dirs[:] = [d for d in dirs if not any(_is_under(raiz_p / d, ex) for ex in excludes)]
        for nome in arquivos:
            p = raiz_p / nome
            if p.suffix.lower() not in (".pfx", ".p12"):
                continue
            if any(_is_under(p, ex) for ex in excludes):
                continue
            achados.append(p)
            if len(achados) >= limite_arquivos:
                logger.warning(
                    "Varredura de %s parou no teto de %d arquivos; o restante fica de fora.",
                    source_dir, limite_arquivos,
                )
                return sorted(achados)
    return sorted(achados)


def scan_folder(
    source_dir: Path,
    recursive: bool = True,
    exclude_dirs: Optional[Iterable[Path]] = None,
    limite_arquivos: int = LIMITE_ARQUIVOS_VARREDURA,
    profundidade_max: int = PROFUNDIDADE_MAX_VARREDURA,
) -> List[CertInfo]:
    source_dir = Path(source_dir)
    if not source_dir.is_dir():
        return []

    results: List[CertInfo] = []
    now = _now_utc()
    excludes = [Path(p).resolve() for p in (exclude_dirs or [])]

    for p in _candidatos(source_dir, recursive, excludes, limite_arquivos, profundidade_max):
        if not p.is_file():
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
            cert = _abrir_pfx(p, pwd)
            not_before, not_after, subj, iss, fp_hex, ser_hex = _info_do_certificado(cert)
            info.icp = campos_icp(cert)
            info.not_before = not_before
            info.not_after = not_after
            info.subject = subj
            info.issuer = iss or None
            info.fingerprint_sha256 = fp_hex
            info.serial_number_hex = ser_hex or None
            cn = extract_cn_rfc4514(subj)
            nome, doc, tipo = parse_nome_cnpj_cpf_from_cn(cn)
            info.nome_titular = nome
            info.documento_numero = doc
            info.documento_tipo = tipo
            if not_after < now:
                info.status = CertStatus.EXPIRED
        except Exception as e:  # noqa: BLE001 — queremos exibir qualquer falha
            msg = str(e)
            if "invalid password" in msg.lower():
                msg = "Senha incorreta"
            info.status = CertStatus.ERROR
            info.error_message = msg or repr(e)

        results.append(info)

    return results


def destino_livre(pasta: Path, nome: str) -> Path:
    """`X senha 1.pfx` ocupado → `X (2) senha 1.pfx`, `X (3) …`.

    Um só formato de sufixo para todo movimento de arquivo (02/10/2026): até
    aqui a varredura usava `_dup_<carimbo>`, que escondia o nome e quebrava a
    leitura do número. O `(n)` antes de `senha` mantém o padrão do nome, então
    o arquivo continua abrindo pela varredura.
    """
    pasta = Path(pasta)
    dest = pasta / nome
    if not dest.exists():
        return dest
    parsed = parse_pfx_filename(nome)
    base, senha = parsed if parsed else (Path(nome).stem, "")
    n = 2
    while True:
        cand = pasta / (f"{base} ({n}) senha {senha}.pfx" if senha else f"{base} ({n}){Path(nome).suffix}")
        if not cand.exists():
            return cand
        n += 1


def move_to_expired(
    cert: CertInfo,
    expired_dir: Path,
) -> Path:
    """Move o arquivo PFX para a pasta de vencidos. Retorna o novo caminho."""
    expired_dir = Path(expired_dir)
    expired_dir.mkdir(parents=True, exist_ok=True)
    dest = destino_livre(expired_dir, cert.file_name)
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
    if c.status in (CertStatus.OUT_OF_PATTERN, CertStatus.ERROR):
        # Veio do nome do arquivo, não do X.509: pode carregar a senha.
        from app.nome_publico import nome_publico_de_arquivo as _limpar

        nome_exibir = _limpar(nome_exibir) or nome_exibir
    if tipo == "cnpj":
        tipo_label = "CNPJ"
    elif tipo == "cpf":
        tipo_label = "CPF"
    else:
        tipo_label = None
    # Sem `file_name` nem `path` (SECURITY_AUDIT #2): o nome do arquivo carrega
    # a senha do PFX, e este dicionário é o que o agente manda ao portal e o
    # que o portal devolve. O que sai é o nome público, a pasta e uma chave de
    # deduplicação sem segredo — ver `app/nome_publico.py`.
    from app.nome_publico import chave_de_arquivo, nome_publico_de_arquivo, pasta_de

    nome_pub = nome_publico_de_arquivo(c.file_name) or nome_publico_de_arquivo(c.display_name)
    return {
        "nome_publico": nome_pub,
        "pasta": pasta_de(str(c.path)),
        "arquivo_chave": chave_de_arquivo(nome_pub, c.fingerprint_sha256),
        "display_name": nome_publico_de_arquivo(c.display_name) or nome_pub,
        "status": c.status.value,
        "not_before": not_before.isoformat() if not_before else None,
        "not_after": not_after.isoformat() if not_after else None,
        "nome": nome_exibir,
        "documento_tipo": tipo,
        "documento_tipo_label": tipo_label,
        "documento_formatado": doc_fmt,
        "documento_numero": c.documento_numero,
        "subject": c.subject,
        "issuer": c.issuer,
        "serial_number": c.serial_number_hex,
        "fingerprint_sha256": c.fingerprint_sha256,
        "error_message": c.error_message,
        # Campos ICP-Brasil (agente 1.7.0). Os quatro do responsável são dado
        # pessoal: `app.main.CAMPOS_PESSOAIS` os tira da lista do Início.
        "tipo_icp": c.icp.get("tipo_icp"),
        "organizacao": c.icp.get("organizacao"),
        "emissor": c.icp.get("emissor"),
        "responsavel_nome": c.icp.get("responsavel_nome"),
        "responsavel_cpf": c.icp.get("responsavel_cpf"),
        "responsavel_nascimento": c.icp.get("responsavel_nascimento"),
        "email": c.icp.get("email"),
    }
