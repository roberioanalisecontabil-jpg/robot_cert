"""
Entrada de certificados: a pasta onde os PFX chegam, antes do acervo.

Os arquivos chegam com o nome que o cliente ou o e-mail lhes deu — resumido,
com "_" ou "-" no lugar de espaço, às vezes sem o CNPJ. O que vale é o que
está DENTRO do certificado: o titular e o documento do CN. Este módulo lê
cada PFX da pasta de entrada e:

  1. renomeia para `TITULAR DOCUMENTO senha VALOR.pfx` (o padrão do acervo,
     em maiúsculas, sem acentos nem caracteres que o Windows recusa);
  2. move para a pasta do acervo: pessoa jurídica (CNPJ) ou pessoa física
     (CPF), na subpasta da primeira letra do titular — `0 a 9` quando o nome
     começa por algarismo —, criando a subpasta se faltar;
  3. resolve colisões pelo DOCUMENTO, não pelo nome do arquivo: mesmo
     fingerprint é cópia (descartada, mas registrada); o anterior vencido vai
     para a pasta de vencidos e o novo toma o lugar; dois vigentes ficam os
     dois, o novo com sufixo e marcado como duplicidade;
  4. manda direto para a pasta de vencidos o que já chegou vencido.

O que não abre (nome fora do padrão, senha errada, PFX corrompido, titular
sem CNPJ/CPF) FICA na entrada e é reportado ao portal como pendente — alguém
precisa olhar, e a pasta de entrada é o lugar onde se procura.

Só depois disto o agente varre o acervo: um certificado novo só entra no
inventário (e só dispara o aviso de "certificado novo") já no lugar e com o
nome certos. A pasta de entrada fica fora da varredura.

Os eventos devolvidos ao portal nunca levam a senha: todo nome de arquivo
passa por `nome_publico_de_arquivo` (SECURITY_AUDIT #2).

Stdlib + `app.cert_scanner` de propósito: o agente Windows importa isto.
"""

from __future__ import annotations

import logging
import re
import shutil
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.cert_scanner import (
    CertInfo,
    CertStatus,
    _load_pfx_info,
    extract_cn_rfc4514,
    parse_nome_cnpj_cpf_from_cn,
    parse_pfx_filename,
    scan_folder,
)
from app.nome_publico import nome_publico_de_arquivo

LOGGER = logging.getLogger("analise_certidigital_agent.entrada")

# A subpasta dos titulares cujo nome começa por algarismo. Nome fixo, acordado
# com a operação em 02/10/2026: as pastas já existem com este nome.
PASTA_NUMEROS = "0 a 9"

RESULTADO_MOVIDO = "movido"
RESULTADO_VENCIDO = "vencido"            # chegou vencido: foi para a pasta de vencidos
RESULTADO_SUBSTITUIU = "substituiu"      # o anterior, vencido, foi para vencidos
RESULTADO_COPIA = "copia_descartada"     # mesmo fingerprint já no acervo
RESULTADO_DUPLICIDADE = "duplicidade"    # dois vigentes do mesmo documento
RESULTADO_PENDENTE = "pendente"          # ficou na entrada
RESULTADOS = (
    RESULTADO_MOVIDO, RESULTADO_VENCIDO, RESULTADO_SUBSTITUIU,
    RESULTADO_COPIA, RESULTADO_DUPLICIDADE, RESULTADO_PENDENTE,
)

# Caracteres que o NTFS recusa num nome de arquivo, mais os de controle.
_PROIBIDOS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_ESPACOS = re.compile(r"\s+")


@dataclass
class ConfigEntrada:
    pasta_entrada: Path
    pasta_pj: Path
    pasta_pf: Path
    pasta_vencidos: Path


@dataclass
class Evento:
    resultado: str
    arquivo_original: str
    arquivo_novo: str = ""
    pasta_destino: str = ""
    motivo: str = ""
    nome: str = ""
    documento_numero: str = ""
    documento_tipo: str = ""
    fingerprint_sha256: str = ""
    not_after: str = ""
    quando: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def como_dict(self) -> Dict[str, Any]:
        return {
            "resultado": self.resultado,
            "arquivo_original": self.arquivo_original,
            "arquivo_novo": self.arquivo_novo,
            "pasta_destino": self.pasta_destino,
            "motivo": self.motivo,
            "nome": self.nome,
            "documento_numero": self.documento_numero,
            "documento_tipo": self.documento_tipo,
            "fingerprint_sha256": self.fingerprint_sha256,
            "not_after": self.not_after,
            "quando": self.quando,
        }


# ── Nome e pasta ──────────────────────────────────────────────────────────

def normalizar_titular(titular: Optional[str]) -> str:
    """`Brasil Exemplo Ltda.` → `BRASIL EXEMPLO LTDA`; sem acento, sem o que o
    Windows recusa, espaços simples, sem ponto final (o Windows o descarta)."""
    t = unicodedata.normalize("NFKD", str(titular or ""))
    t = "".join(ch for ch in t if not unicodedata.combining(ch))
    t = _PROIBIDOS.sub(" ", t)
    t = _ESPACOS.sub(" ", t).strip(" .")
    return t.upper()


def nome_canonico(titular: str, documento: str, senha: str) -> str:
    """`TITULAR DOCUMENTO senha VALOR.pfx` — o padrão do acervo."""
    doc = "".join(c for c in str(documento or "") if c.isdigit())
    partes = [p for p in (normalizar_titular(titular), doc) if p]
    return f"{' '.join(partes)} senha {str(senha).strip()}.pfx"


def letra_da_pasta(titular: str) -> str:
    """A subpasta do titular: primeira letra (A–Z) ou `0 a 9` para algarismo.
    Sem letra nem algarismo no nome, cai em `0 a 9` — é a pasta de "não começa
    por letra", e um nome assim é raro o bastante para não merecer outra."""
    t = normalizar_titular(titular)
    for ch in t:
        if ch.isdigit():
            return PASTA_NUMEROS
        if "A" <= ch <= "Z":
            return ch
    return PASTA_NUMEROS


def pasta_destino(cert: CertInfo, cfg: ConfigEntrada) -> Path:
    raiz = cfg.pasta_pf if cert.documento_tipo == "cpf" else cfg.pasta_pj
    return raiz / letra_da_pasta(cert.nome_titular or "")


# ── Leitura ───────────────────────────────────────────────────────────────

def _ler(path: Path) -> Optional[CertInfo]:
    """Um PFX do acervo, legível ou None. Para comparar com o que chega."""
    parsed = parse_pfx_filename(path.name)
    if not parsed:
        return None
    logical, pwd = parsed
    try:
        nb, na, subj, iss, fp, ser = _load_pfx_info(path, pwd)
    except Exception:  # noqa: BLE001 — ilegível não entra na comparação
        return None
    nome, doc, tipo = parse_nome_cnpj_cpf_from_cn(extract_cn_rfc4514(subj))
    return CertInfo(
        path=path, file_name=path.name, display_name=logical,
        status=CertStatus.EXPIRED if na < datetime.now(timezone.utc) else CertStatus.OK,
        not_before=nb, not_after=na, subject=subj, issuer=iss or None,
        fingerprint_sha256=fp, serial_number_hex=ser or None,
        nome_titular=nome, documento_numero=doc, documento_tipo=tipo,
        password_from_name=pwd,
    )


def _mesmo_documento_em(pasta: Path, documento: str) -> List[CertInfo]:
    if not pasta.is_dir():
        return []
    out: List[CertInfo] = []
    for p in sorted(pasta.iterdir()):
        if not p.is_file() or p.suffix.lower() not in (".pfx", ".p12"):
            continue
        c = _ler(p)
        if c and c.documento_numero == documento:
            out.append(c)
    return out


def _destino_livre(pasta: Path, nome: str) -> Path:
    """`X senha 1.pfx` ocupado → `X (2) senha 1.pfx`, `X (3) …`."""
    dest = pasta / nome
    if not dest.exists():
        return dest
    parsed = parse_pfx_filename(nome)
    base, senha = parsed if parsed else (Path(nome).stem, "")
    n = 2
    while True:
        cand = pasta / (f"{base} ({n}) senha {senha}.pfx" if senha else f"{base} ({n}).pfx")
        if not cand.exists():
            return cand
        n += 1


def _mover(origem: Path, destino: Path) -> None:
    destino.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(origem), str(destino))


def _evento(cert: CertInfo, resultado: str, **extra: Any) -> Evento:
    return Evento(
        resultado=resultado,
        arquivo_original=nome_publico_de_arquivo(cert.file_name),
        nome=cert.nome_titular or "",
        documento_numero=cert.documento_numero or "",
        documento_tipo=cert.documento_tipo or "",
        fingerprint_sha256=cert.fingerprint_sha256 or "",
        not_after=cert.not_after.isoformat() if cert.not_after else "",
        **extra,
    )


# ── O processamento ───────────────────────────────────────────────────────

def _pendente(cert: CertInfo, motivo: str) -> Evento:
    return _evento(cert, RESULTADO_PENDENTE, motivo=motivo)


def _motivo_de_pendencia(cert: CertInfo) -> Optional[str]:
    if cert.status == CertStatus.OUT_OF_PATTERN:
        return "Nome fora do padrão «nome» senha «valor».pfx: sem a senha o certificado não abre."
    if cert.status == CertStatus.ERROR:
        return f"O certificado não abriu: {cert.error_message or 'erro desconhecido'}."
    if not cert.documento_numero or not cert.documento_tipo:
        return "O titular do certificado não traz CNPJ nem CPF; não há como escolher a pasta."
    if not cert.nome_titular:
        return "O certificado não traz o nome do titular."
    return None


def processar_um(cert: CertInfo, cfg: ConfigEntrada) -> List[Evento]:
    """Resolve UM arquivo da entrada. Devolve os eventos (um, às vezes dois)."""
    motivo = _motivo_de_pendencia(cert)
    if motivo:
        return [_pendente(cert, motivo)]

    novo_nome = nome_canonico(cert.nome_titular or "", cert.documento_numero or "", cert.password_from_name or "")
    novo_publico = nome_publico_de_arquivo(novo_nome)

    # Chegou vencido: nem passa pelo acervo.
    if cert.status == CertStatus.EXPIRED:
        dest = _destino_livre(cfg.pasta_vencidos, novo_nome)
        _mover(cert.path, dest)
        return [_evento(cert, RESULTADO_VENCIDO, arquivo_novo=novo_publico, pasta_destino=str(dest.parent),
                        motivo="Chegou vencido; foi direto para a pasta de vencidos.")]

    pasta = pasta_destino(cert, cfg)
    eventos: List[Evento] = []
    resultado = RESULTADO_MOVIDO
    motivo = ""
    for existente in _mesmo_documento_em(pasta, cert.documento_numero or ""):
        if existente.fingerprint_sha256 == cert.fingerprint_sha256:
            cert.path.unlink()
            return [_evento(cert, RESULTADO_COPIA, arquivo_novo=nome_publico_de_arquivo(existente.file_name),
                            pasta_destino=str(pasta),
                            motivo="O mesmo certificado já estava no acervo; a cópia foi descartada.")]
        if existente.status == CertStatus.EXPIRED:
            dest_venc = _destino_livre(cfg.pasta_vencidos, existente.file_name)
            _mover(existente.path, dest_venc)
            eventos.append(_evento(existente, RESULTADO_VENCIDO, arquivo_novo=nome_publico_de_arquivo(dest_venc.name),
                                   pasta_destino=str(dest_venc.parent),
                                   motivo="Vencido; deu lugar ao certificado que chegou."))
            resultado = RESULTADO_SUBSTITUIU
            motivo = "Substituiu o certificado vencido do mesmo documento."
        else:
            resultado = RESULTADO_DUPLICIDADE
            motivo = (
                "Já havia um certificado vigente deste documento "
                f"({nome_publico_de_arquivo(existente.file_name)}); os dois ficaram."
            )

    dest = _destino_livre(pasta, novo_nome)
    _mover(cert.path, dest)
    eventos.append(_evento(cert, resultado, arquivo_novo=nome_publico_de_arquivo(dest.name),
                           pasta_destino=str(pasta), motivo=motivo))
    return eventos


def processar_entrada(cfg: ConfigEntrada) -> Dict[str, List[Dict[str, Any]]]:
    """Processa a pasta de entrada inteira (sem descer em subpastas).

    Devolve `{"eventos": [...], "pendentes": [...]}`: o que aconteceu agora e
    o que FICOU na pasta. O portal usa a segunda lista como o estado atual da
    entrada — o que saiu dela deixa de ser pendente.
    """
    eventos: List[Evento] = []
    pendentes: List[Evento] = []
    if not cfg.pasta_entrada.is_dir():
        LOGGER.error("Pasta de entrada inexistente ou inacessível: %s", cfg.pasta_entrada)
        return {"eventos": [], "pendentes": []}
    for cert in scan_folder(cfg.pasta_entrada, recursive=False):
        try:
            for ev in processar_um(cert, cfg):
                if ev.resultado == RESULTADO_PENDENTE:
                    pendentes.append(ev)
                else:
                    eventos.append(ev)
                    LOGGER.info("Entrada: %s → %s (%s)", ev.arquivo_original, ev.arquivo_novo or "-", ev.resultado)
        except OSError as e:
            ev = _pendente(cert, f"Não foi possível mover o arquivo: {e}")
            pendentes.append(ev)
            LOGGER.error("Entrada: %s ficou na pasta: %s", nome_publico_de_arquivo(cert.file_name), e)
    for ev in pendentes:
        LOGGER.warning("Entrada pendente: %s — %s", ev.arquivo_original, ev.motivo)
    return {"eventos": [e.como_dict() for e in eventos], "pendentes": [p.como_dict() for p in pendentes]}


def config_de(settings: dict, local_cfg: dict, pasta_vencidos: Path) -> Optional[ConfigEntrada]:
    """As pastas da entrada: portal primeiro, agent_config.json depois. Sem a
    pasta de entrada configurada a função devolve None e o agente segue sem
    este passo — a tela de Configuração é onde se liga."""
    def _v(chave: str) -> str:
        return str((settings.get(chave) or "") or (local_cfg.get(chave) or "")).strip()

    entrada, pj, pf = _v("pasta_entrada"), _v("pasta_pj"), _v("pasta_pf")
    if not entrada:
        return None
    if not pj or not pf:
        LOGGER.error(
            "Pasta de entrada configurada (%s) mas faltam as pastas de pessoa jurídica/física; entrada ignorada.",
            entrada,
        )
        return None
    return ConfigEntrada(Path(entrada), Path(pj), Path(pf), Path(pasta_vencidos))
