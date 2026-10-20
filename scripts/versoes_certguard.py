"""Chaves e publicação da atualização automática do Certguard Análise (1.1.0).

Roda NA MÁQUINA DE BUILD, onde fica a chave principal (decidido em 20/10/2026:
chave própria do Certguard, separada da do Hardlyze).

    python scripts/versoes_certguard.py gerar-chaves
        Cria o par PRINCIPAL e o par RESERVA em %USERPROFILE%\\.certguard-chaves
        (privadas cifradas com a senha que você digitar) e imprime as chaves
        públicas para colar em estacao/manifesto.py (CHAVES_PUBLICAS). A
        reserva tem de SAIR deste computador (pendrive guardado ou gerenciador
        de senhas) e ser apagada daqui.

    python scripts/versoes_certguard.py publicar \\
        --instalador dist_estacao\\Instalador_CertguardAnalise_1.1.0.exe \\
        [--pode-voltar] [--chave reserva]
        Assina o manifesto e monta dist_estacao\\publicar\\certificados com o
        instalador e o vigente.json. Essa pasta vai para o servidor com
        deploy\\publicar-certguard.ps1.

Nada disto vai para o repositório: as chaves ficam fora dele, e o .gitignore
recusa *.key por garantia. O formato do manifesto mora em estacao/manifesto.py.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402

from estacao import manifesto  # noqa: E402

PASTA_PADRAO = Path(os.environ.get("USERPROFILE") or Path.home()) / ".certguard-chaves"
SAIDA_PADRAO = RAIZ / "dist_estacao" / "publicar"
SENHA_MINIMA = 12
_RE_NOME = re.compile(r"_(\d{1,4}\.\d{1,4}\.\d{1,4})\.exe$")


def _pedir_senha(rotulo: str, confirmar: bool) -> bytes:
    senha = os.environ.get("CERTGUARD_SENHA_CHAVE") or getpass.getpass(f"Senha da chave {rotulo}: ")
    if (
        confirmar
        and not os.environ.get("CERTGUARD_SENHA_CHAVE")
        and getpass.getpass(f"Repita a senha da chave {rotulo}: ") != senha
    ):
        sys.exit("As senhas não conferem.")
    if len(senha) < SENHA_MINIMA:
        sys.exit(f"Senha curta demais: use pelo menos {SENHA_MINIMA} caracteres.")
    return senha.encode("utf-8")


def gerar_chaves(pasta: Path) -> dict[str, str]:
    pasta.mkdir(parents=True, exist_ok=True)
    publicas = {}
    for chave_id in ("principal", "reserva"):
        arquivo = pasta / f"{chave_id}.key"
        if arquivo.exists():
            sys.exit(f"{arquivo} já existe: não sobrescrevo chave. Apague à mão se for isso mesmo.")
        privada = Ed25519PrivateKey.generate()
        pem = privada.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.BestAvailableEncryption(_pedir_senha(chave_id, confirmar=True)),
        )
        arquivo.write_bytes(pem)
        publicas[chave_id] = manifesto.chave_publica_b64(privada)
    return publicas


def carregar_privada(arquivo: Path) -> Ed25519PrivateKey:
    if not arquivo.is_file():
        sys.exit(f"Chave não encontrada em {arquivo}.")
    try:
        chave = serialization.load_pem_private_key(
            arquivo.read_bytes(), password=_pedir_senha(arquivo.stem, confirmar=False)
        )
    except ValueError:
        sys.exit("Senha errada ou arquivo de chave danificado.")
    if not isinstance(chave, Ed25519PrivateKey):
        sys.exit("O arquivo não é uma chave Ed25519.")
    return chave


def versao_do_nome(instalador: Path) -> str:
    achado = _RE_NOME.search(instalador.name)
    if not achado:
        sys.exit(f"O nome {instalador.name} não termina em _<versão>.exe.")
    return achado.group(1)


def montar_manifesto(instalador: Path, versao: str, pode_voltar: bool) -> dict:
    return {
        "produto": manifesto.PRODUTO,
        "versao": versao,
        "arquivo": instalador.name,
        "sha256": manifesto.sha256_do_arquivo(str(instalador)),
        "tamanho": instalador.stat().st_size,
        "pode_voltar": pode_voltar,
        "publicado_em": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }


def publicar(instalador: Path, privada: Ed25519PrivateKey, chave_id: str, pode_voltar: bool,
             saida: Path, chaves: dict[str, str] | None = None) -> Path:
    """Monta `saida/certificados` com o instalador e o `vigente.json`.

    Confere o pacote com as chaves EMBUTIDAS nas estações antes de entregar:
    assinado com uma chave que a frota não conhece, ninguém atualizaria, e o
    sintoma seria só o silêncio.
    """
    if not instalador.is_file():
        sys.exit(f"Instalador não encontrado: {instalador}")
    m = montar_manifesto(instalador, versao_do_nome(instalador), pode_voltar)
    pacote = manifesto.assinar(m, privada, chave_id)
    try:
        manifesto.conferir(pacote, chaves)
    except manifesto.ManifestoInvalido as e:
        sys.exit(f"O pacote não confere com as chaves embutidas em estacao/manifesto.py: {e}")
    destino = saida / manifesto.PRODUTO
    if destino.exists():
        shutil.rmtree(destino)
    destino.mkdir(parents=True)
    shutil.copy2(instalador, destino / instalador.name)
    (destino / "vigente.json").write_text(json.dumps(pacote, indent=2, ensure_ascii=False), encoding="utf-8")
    return destino


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("gerar-chaves")
    g.add_argument("--pasta", type=Path, default=PASTA_PADRAO)
    a = sub.add_parser("publicar")
    a.add_argument("--instalador", type=Path, required=True)
    a.add_argument("--chave", default="principal", choices=["principal", "reserva"])
    a.add_argument("--pasta", type=Path, default=PASTA_PADRAO)
    a.add_argument("--saida", type=Path, default=SAIDA_PADRAO)
    a.add_argument("--pode-voltar", action="store_true")
    args = p.parse_args(argv)

    if args.cmd == "gerar-chaves":
        publicas = gerar_chaves(args.pasta)
        print(f"Chaves criadas em {args.pasta}.")
        print("Cole em estacao/manifesto.py:\n")
        print("CHAVES_PUBLICAS: dict[str, str] = {")
        for k, v in publicas.items():
            print(f'    "{k}": "{v}",')
        print("}\n")
        print(f"AGORA: copie {args.pasta / 'reserva.key'} para fora do computador e apague daqui.")
        return

    privada = carregar_privada(args.pasta / f"{args.chave}.key")
    destino = publicar(args.instalador, privada, args.chave, args.pode_voltar, args.saida)
    print(f"Pronto para publicar: {destino}")
    print("No servidor: deploy\\publicar-certguard.ps1 -Origem <essa pasta copiada para lá>")


if __name__ == "__main__":
    main()
