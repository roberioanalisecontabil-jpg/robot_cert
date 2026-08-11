"""
Instalador avulso de certificado — o .exe que o usuário baixa do portal.

Modelo Ninite: o binário é único e estático; o que o personaliza é o NOME do
arquivo, onde o portal grava o token de instalação. Assim o executável pode ser
assinado uma vez e ganhar reputação no SmartScreen, em vez de cada download
produzir um binário inédito que o Windows nunca viu.

Diferenças para `installer_client.process_install_command`, que roda no agente:

* Autentica em /claim com o próprio token, não com X-API-Key — a chave do agente
  não pode ser distribuída dentro de um executável público.
* A senha do PFX vem no bundle (cifrada por ECDH para esta execução). O agente a
  lê do nome do arquivo na pasta de origem; a máquina do usuário não tem pasta.
* Instala no repositório do USUÁRIO que executou, que é o ponto do modelo: o
  certificado precisa existir no perfil de quem vai usá-lo no navegador/e-CAC.
"""

from __future__ import annotations

import base64
import os
import re
import sys
from pathlib import Path

import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ec import SECP256R1, generate_private_key

from agent.installer_client import _decrypt_payload_ecdh, _import_pfx_non_exportable

# Portal de origem. O executável roda na máquina do usuário, onde não há .env
# nem variáveis de ambiente nossas — então o endereço tem de estar dentro do
# binário. `scripts/build_instalador_avulso.ps1` gera `agent/_build_config.py`
# com o valor do build; a variável de ambiente serve para testar sem recompilar.
try:
    from agent._build_config import PORTAL_BASE as _PORTAL_COMPILADO
except ImportError:  # execução direta do .py, sem passar pelo build
    _PORTAL_COMPILADO = "https://certificado.analisegroup.cnt.br"

PORTAL_BASE = os.getenv("CERT_PORTAL_BASE", _PORTAL_COMPILADO)

# O portal nomeia o arquivo como "Instalar <nome> -<token>.exe". O token usa o
# alfabeto de secrets.token_urlsafe (sem espaços), então a última ocorrência de
# " -" separa nome e token mesmo que o nome contenha hífens.
# O sufixo opcional " (1)" cobre o caso de o navegador renomear downloads
# repetidos — sem isso, baixar duas vezes quebraria a leitura do token.
_TOKEN_NO_NOME = re.compile(r" -([A-Za-z0-9_-]{16,128})(?: \(\d+\))?\.exe$", re.IGNORECASE)


def _console_em_utf8() -> None:
    """
    Faz o console aceitar acentos.

    O Windows abre o console na code page legada (850/1252), então "instalação"
    sai como "instala��o" — e as mensagens deste programa são a única coisa que
    o usuário tem quando algo falha. Silencioso de propósito: se não der para
    ajustar (saída redirecionada, terminal exótico), o texto ainda sai legível.
    """
    try:
        import ctypes

        ctypes.windll.kernel32.SetConsoleOutputCP(65001)
    except Exception:
        pass
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def _nome_do_executavel() -> str:
    """Nome do arquivo em execução, tanto congelado (PyInstaller) quanto .py."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).name
    return Path(sys.argv[0]).name


def extrair_token(nome_arquivo: str) -> str | None:
    m = _TOKEN_NO_NOME.search(nome_arquivo)
    return m.group(1) if m else None


def _titulo(texto: str) -> None:
    print(f"\n{texto}\n{'-' * len(texto)}")


def instalar(token: str, base: str) -> int:
    with httpx.Client(timeout=60, follow_redirects=True) as client:
        privada = generate_private_key(SECP256R1())
        pub_b64 = base64.b64encode(
            privada.public_key().public_bytes(
                serialization.Encoding.DER,
                serialization.PublicFormat.SubjectPublicKeyInfo,
            )
        ).decode()

        print("Conectando ao portal...")
        try:
            r = client.post(
                f"{base}/api/cert-installer/claim",
                json={"token": token, "clientPublicKey": pub_b64},
            )
        except Exception as ex:
            print(f"\nERRO: não foi possível falar com o portal.\n  {ex}")
            return 2

        if r.status_code == 403:
            print("\nERRO: este link de instalação já foi usado ou expirou.")
            print("Peça um novo instalador no portal — cada link vale uma instalação.")
            return 3
        if r.status_code == 429:
            print("\nERRO: muitas tentativas seguidas. Aguarde um minuto.")
            return 4
        if r.status_code != 200:
            print(f"\nERRO {r.status_code}: {r.text[:300]}")
            return 5

        certificados = r.json().get("certificates", [])
        if not certificados:
            print("\nERRO: nenhum certificado veio no pacote.")
            return 6

        resultados = []
        for item in certificados:
            nome = item.get("friendlyName") or item.get("fingerprint", "")[:16]
            _titulo(f"Instalando: {nome}")
            try:
                pfx = _decrypt_payload_ecdh(privada, item)

                senha = ""
                if item.get("pfxPassword"):
                    senha = _decrypt_payload_ecdh(privada, item["pfxPassword"]).decode("utf-8")
                if not senha:
                    # Registro anterior à volta da senha ao cofre. O agente
                    # contornaria lendo a pasta local; aqui não há pasta.
                    print("  FALHA: o portal não enviou a senha deste certificado.")
                    resultados.append({
                        "certificateId": item.get("certificateId", ""),
                        "fingerprint": item.get("fingerprint", ""),
                        "status": "FALHA",
                        "detail": "Senha ausente no cofre; reenvie o certificado pelo agente.",
                    })
                    continue

                sucesso, detalhe = _import_pfx_non_exportable(pfx, senha)
                pfx = b"\x00" * len(pfx)

                print(f"  {'OK' if sucesso else 'FALHA'}: {detalhe}")
                resultados.append({
                    "certificateId": item.get("certificateId", ""),
                    "fingerprint": item.get("fingerprint", ""),
                    "status": "OK" if sucesso else "FALHA",
                    "detail": detalhe,
                })
            except Exception as ex:
                print(f"  FALHA: {ex}")
                resultados.append({
                    "certificateId": item.get("certificateId", ""),
                    "fingerprint": item.get("fingerprint", ""),
                    "status": "FALHA",
                    "detail": str(ex),
                })

        try:
            client.post(
                f"{base}/api/cert-installer/report-avulso",
                json={"token": token, "results": resultados},
            )
        except Exception:
            # O relatório é auditoria; perdê-lo não invalida a instalação, e
            # falhar aqui confundiria o usuário sobre um certificado que já está
            # no repositório dele.
            print("\n(aviso: não foi possível enviar o relatório ao portal)")

        return 0 if all(x["status"] == "OK" for x in resultados) else 7


def main() -> int:
    _console_em_utf8()
    print("=" * 60)
    print("  Instalador de Certificado Digital - Analise CertiDigital")
    print("=" * 60)

    nome = _nome_do_executavel()
    token = extrair_token(nome)
    if not token:
        print(
            f"\nERRO: não encontrei o código de instalação no nome do arquivo.\n"
            f"  Arquivo: {nome}\n\n"
            "Não renomeie o instalador: o código baixado do portal faz parte do\n"
            "nome. Baixe novamente e execute sem alterar o nome."
        )
        return 1

    codigo = instalar(token, PORTAL_BASE.rstrip("/"))

    if codigo == 0:
        print("\n" + "=" * 60)
        print("  CONCLUIDO — o certificado ja esta disponivel neste computador.")
        print("=" * 60)
    return codigo


if __name__ == "__main__":
    saida = main()
    try:
        input("\nPressione ENTER para fechar...")
    except EOFError:
        pass
    sys.exit(saida)
