"""
A credencial da MÁQUINA nesta estação — par de `agent/identidade.py`.

Par do lado servidor em `app/machine_credentials.py`. Aqui vive o que fica no
disco: um segredo por estação, obtido uma vez no provisionamento (primeira
subida do serviço) e apresentado depois no mesmo header `X-API-Key` que o
agente sempre mandou — trocando a chave compartilhada por um valor próprio,
revogável. O desenho é UM só para os dois portais (o INVENT aplicou o mesmo em
01/09/2026); ver `identidade-de-maquina-desenho.md`.

── Por que ProgramData, e não LOCALAPPDATA ───────────────────────────────

`identidade.py` guarda a credencial da PESSOA em `%LOCALAPPDATA%` com DPAPI de
escopo USUÁRIO — e é exatamente por isso que ela ficou dormente: quem faz as
chamadas autenticadas é o serviço, como LocalSystem, que não decifra o blob de
outra conta. Esta aqui é a credencial da MÁQUINA, e quem a apresenta é o
serviço. Então mora em `%ProgramData%\\Analise CertiDigital Agent\\maquina.dat`
(a mesma pasta de `agent_status.json`), cifrada com DPAPI de escopo MÁQUINA
(`CRYPTPROTECT_LOCAL_MACHINE`).

── A ACL é parte da cifra, não um extra ──────────────────────────────────

DPAPI de escopo máquina decifra para QUALQUER processo desta máquina — a
entropia está no código. O que impede uma conta comum de ler o segredo é a ACL
do arquivo: só SYSTEM e Administradores (por SID, `*S-1-5-18` e
`*S-1-5-32-544`, para não quebrar em Windows em português). Por isso `guardar`
LEVANTA quando a ACL não pega, em vez de deixar o arquivo legível "para
funcionar de qualquer jeito" — a mesma recusa em degradar de
`identidade.SemCofreLocal`, pelo mesmo motivo: continua funcionando, ninguém
percebe, e a garantia sumiu.
"""

from __future__ import annotations

import contextlib
import ctypes
import json
import logging
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, Optional

# O maquinário DPAPI (structs, blobs, a recusa em degradar) é um só; o que muda
# aqui é o ESCOPO da cifra e a entropia. Duplicar os ctypes seria convidar os
# dois arquivos a divergir num detalhe que só aparece na hora de decifrar.
from agent.identidade import _BLOB, SemCofreLocal, _blob, _crypt32, _do_blob

LOGGER = logging.getLogger(__name__)

ARQUIVO = "maquina.dat"
PASTA = "Analise CertiDigital Agent"

# Escopo MÁQUINA: decifrável por qualquer processo desta estação, sem depender
# de sessão de usuário — é exatamente o que o serviço LocalSystem precisa.
CRYPTPROTECT_LOCAL_MACHINE = 0x04

# Entropia própria, diferente da de `identidade.py`: amarra o blob a ESTE uso.
# Não é segredo — a garantia de leitura é a ACL, e a de decifra é o DPAPI.
_ENTROPIA = b"analise-certidigital-agente-maquina-v1"

# Par de `app/machine_credentials.py: CABECALHO_CREDENCIAL_INVALIDA`. O portal
# marca com ele o 401 que é da CREDENCIAL, e não da operação — é o sinal para
# descartar o segredo local e cair na X-API-Key, em vez de repetir um valor
# morto para sempre.
CABECALHO_CREDENCIAL_INVALIDA = "X-Credencial-Invalida"


def proteger(dados: bytes) -> bytes:
    entrada, entropia, saida = _blob(dados), _blob(_ENTROPIA), _BLOB()
    ok = _crypt32().CryptProtectData(
        ctypes.byref(entrada), None, ctypes.byref(entropia), None, None,
        CRYPTPROTECT_LOCAL_MACHINE, ctypes.byref(saida),
    )
    if not ok:
        raise SemCofreLocal(f"CryptProtectData falhou ({ctypes.GetLastError()}).")
    try:
        return _do_blob(saida)
    finally:
        ctypes.windll.kernel32.LocalFree(saida.pbData)


def desproteger(dados: bytes) -> bytes:
    # O escopo não viaja no flag de decifra — o blob sabe como foi cifrado.
    entrada, entropia, saida = _blob(dados), _blob(_ENTROPIA), _BLOB()
    ok = _crypt32().CryptUnprotectData(
        ctypes.byref(entrada), None, ctypes.byref(entropia), None, None, 0,
        ctypes.byref(saida),
    )
    if not ok:
        raise SemCofreLocal(f"CryptUnprotectData falhou ({ctypes.GetLastError()}).")
    try:
        return _do_blob(saida)
    finally:
        ctypes.windll.kernel32.LocalFree(saida.pbData)


def caminho() -> Path:
    """`%ProgramData%\\Analise CertiDigital Agent\\maquina.dat`.

    A mesma pasta de `agent_status.json` — é o lugar que o serviço alcança.
    Fallback igual ao de `_status_file_path`: sem PROGRAMDATA, fica ao lado do
    executável (só acontece fora do Windows, onde o DPAPI já recusa de toda
    forma).
    """
    program_data = (os.getenv("PROGRAMDATA") or "").strip()
    if program_data:
        return Path(program_data) / PASTA / ARQUIVO
    return Path(__file__).resolve().parent / ARQUIVO


def _aplicar_acl(arquivo: Path) -> None:
    """Só SYSTEM e Administradores leem o arquivo. Levanta se não conseguir.

    Por SID e não por nome: "Administrators" não existe num Windows em
    português, e o erro seria silencioso no pior lugar possível.
    """
    resultado = subprocess.run(
        [
            "icacls", str(arquivo),
            "/inheritance:r",
            "/grant", "*S-1-5-18:F",       # LocalSystem
            "/grant", "*S-1-5-32-544:F",   # Administradores
        ],
        capture_output=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        timeout=30,
        check=False,  # o returncode é tratado logo abaixo, com o stderr junto
    )
    if resultado.returncode != 0:
        erro = (resultado.stderr or resultado.stdout or b"").decode("utf-8", "replace").strip()
        raise SemCofreLocal(f"icacls falhou ao restringir {arquivo}: {erro or 'sem detalhe'}")


def _restringir_pasta(pasta: Path) -> None:
    """Só SYSTEM e Administradores na pasta, herdando para o que nascer nela."""
    resultado = subprocess.run(
        [
            "icacls", str(pasta),
            "/inheritance:r",
            "/grant", "*S-1-5-18:(OI)(CI)F",
            "/grant", "*S-1-5-32-544:(OI)(CI)F",
        ],
        capture_output=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        timeout=30,
        check=False,
    )
    if resultado.returncode != 0:
        erro = (resultado.stderr or resultado.stdout or b"").decode("utf-8", "replace").strip()
        raise SemCofreLocal(f"icacls falhou ao restringir {pasta}: {erro or 'sem detalhe'}")


def gravar_protegido(destino: Path, dados: bytes) -> None:
    """Grava `dados` em `destino` sem nenhum instante legível por conta comum.

    Até a auditoria de 10/10/2026 o arquivo era escrito e SÓ DEPOIS restrito:
    quem abrisse um handle nesse meio tempo, ou tivesse criado o arquivo antes
    (ficando dono dele), lia o segredo. A pasta do ProgramData deixa conta
    comum criar arquivos.

    Agora o conteúdo nasce numa subpasta temporária já restrita a SYSTEM e
    Administradores — o arquivo herda essa ACL ao ser criado —, com nome
    aleatório e criação exclusiva (O_EXCL), e só então troca de lugar com o
    destino. O que existisse no destino é substituído, não reaproveitado. A
    ACL é reaplicada no destino, protegida da herança da pasta.
    """
    destino.parent.mkdir(parents=True, exist_ok=True)
    temp = Path(tempfile.mkdtemp(prefix=".novo-", dir=str(destino.parent)))
    try:
        _restringir_pasta(temp)
        novo = temp / (secrets.token_hex(16) + ".tmp")
        fd = os.open(str(novo), os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(dados)
        os.replace(str(novo), str(destino))
    finally:
        shutil.rmtree(temp, ignore_errors=True)
    try:
        _aplicar_acl(destino)
    except Exception:
        with contextlib.suppress(OSError):
            destino.unlink()
        raise


def guardar(segredo: str, base_url: str, machine_id: str) -> Path:
    """
    Cifra, grava e restringe a ACL. Levanta em vez de deixar legível.

    `base_url` fica junto pelo mesmo motivo de `identidade.guardar`: um segredo
    emitido por um portal não vale noutro.
    """
    conteudo = json.dumps(
        {
            "segredo": segredo,
            "base_url": (base_url or "").strip().rstrip("/"),
            "machine_id": (machine_id or "").strip().lower(),
            "gravado_em": time.time(),
        },
        ensure_ascii=False,
    ).encode("utf-8")

    cifrado = proteger(conteudo)
    destino = caminho()
    # Sem ACL o arquivo estaria legível para qualquer conta local — pior que
    # arquivo nenhum. `gravar_protegido` apaga e deixa o erro subir: o banco já
    # tem o hash, e o caminho de recuperação é a reemissão pelo admin.
    gravar_protegido(destino, cifrado)
    return destino


def ler() -> Optional[Dict[str, Any]]:
    """O que foi guardado, ou None. Nunca levanta — quem falha cai na X-API-Key."""
    origem = caminho()
    try:
        if not origem.is_file():
            return None
        return json.loads(desproteger(origem.read_bytes()).decode("utf-8"))
    except (SemCofreLocal, json.JSONDecodeError, UnicodeDecodeError, OSError):
        LOGGER.warning(
            "Credencial de máquina ilegível em %s; o serviço cai na X-API-Key.", origem
        )
        return None


def apagar() -> bool:
    origem = caminho()
    try:
        if origem.is_file():
            origem.unlink()
            return True
    except OSError:
        LOGGER.exception("Falha ao apagar a credencial de máquina")
    return False


def pode_guardar() -> bool:
    """
    Se esta estação consegue GUARDAR uma credencial — testado de verdade.

    O provisionamento só é pedido depois deste ensaio. Pedir sem conseguir
    guardar queimaria a emissão única: o portal grava o hash, o agente perde o
    texto claro, e a máquina fica presa na X-API-Key até um admin reemitir.
    O ensaio é completo — DPAPI de escopo máquina ida e volta, e escrita com
    ACL na pasta de verdade — com um arquivo descartável.
    """
    if sys.platform != "win32" or not hasattr(ctypes, "windll"):
        return False
    # Nome aleatório e o mesmo caminho de `gravar_protegido` (auditoria run-2,
    # item 16): o nome fixo `maquina.probe`, numa pasta onde conta comum cria
    # arquivos, deixava alguém plantar um link ali e o `icacls` deste serviço
    # (LocalSystem) trocar a ACL do arquivo para onde o link apontasse.
    ensaio = caminho().with_name(f".ensaio-{secrets.token_hex(16)}.probe")
    try:
        if desproteger(proteger(b"ensaio")) != b"ensaio":
            return False
        gravar_protegido(ensaio, b"ensaio")
        return True
    except Exception:  # noqa: BLE001
        LOGGER.warning(
            "Esta estação não consegue guardar a credencial de máquina; "
            "o serviço permanece na X-API-Key.",
            exc_info=True,
        )
        return False
    finally:
        with contextlib.suppress(OSError):
            if ensaio.is_file():
                ensaio.unlink()


def provisionar(client, base_url: str, machine_id: str, versao: str = "",
                cabecalhos: Optional[Dict[str, str]] = None) -> bool:
    """
    Pede ao portal a credencial desta máquina e a guarda. Uma vez na vida.

    Chamado pelo serviço na subida, quando ainda não há `maquina.dat` e o
    ensaio de `pode_guardar` passou. `cabecalhos` leva a X-API-Key que já
    autentica o agente — é ela que prova posse no seeding. Nunca levanta — a
    leitura de certificados não pode parar por causa do provisionamento; sem
    credencial o agente segue na X-API-Key, que é o que já funcionava.

    Devolve True quando a credencial foi emitida E guardada.
    """
    base = (base_url or "").strip().rstrip("/")
    try:
        r = client.post(
            f"{base}/api/agent/maquinas/provisionar",
            json={"machine_id": machine_id, "versao": versao or None},
            headers=cabecalhos or {},
        )
    except Exception:  # noqa: BLE001
        LOGGER.warning("Falha de rede ao provisionar a credencial de máquina.", exc_info=True)
        return False

    if r.status_code == 409:
        # Já emitida — e este processo não tem o segredo. Ou outra subida levou
        # (e o arquivo aparece), ou a emissão se perdeu e é preciso reemitir.
        LOGGER.warning(
            "O portal diz que esta máquina já tem credencial, mas não há "
            "maquina.dat aqui. Peça a um admin para reemitir "
            "(POST /api/agent/maquinas/%s/reemitir).",
            machine_id,
        )
        return False
    if r.status_code != 200:
        LOGGER.warning(
            "O portal recusou o provisionamento (%s); o serviço segue na X-API-Key.",
            r.status_code,
        )
        return False

    dados = r.json() or {}
    segredo = str(dados.get("segredo") or "")
    if not segredo:
        LOGGER.warning("Provisionamento sem segredo na resposta; nada guardado.")
        return False
    try:
        guardar(segredo, base, str(dados.get("machine_id") or machine_id))
    except Exception:  # noqa: BLE001
        LOGGER.exception(
            "O portal emitiu a credencial de máquina e a gravação FALHOU. "
            "Esta estação segue na X-API-Key; peça a um admin para reemitir."
        )
        return False
    LOGGER.info(
        "Credencial de máquina recebida e guardada; o serviço deixa a "
        "X-API-Key compartilhada a partir da próxima chamada."
    )
    return True


def descartar_se_recusada(resposta) -> bool:
    """
    Hook de resposta do httpx: apaga o segredo que o portal acabou de recusar.

    Sem isto o serviço repetiria um segredo revogado a cada volta do laço e o
    ANALISESRV ficaria mudo para sempre — foi o que aconteceu no INVENT em
    24/08/2026, e o protocolo do cabeçalho existe pelos dois lados por causa
    disso. Só descarta quando as três condições valem juntas: o portal marcou
    a CREDENCIAL como o problema, a requisição levava X-API-Key, e o valor
    levado é o que está guardado aqui — descartar por um 401 qualquer apagaria
    um segredo válido.

    Depois do descarte o agente cai na X-API-Key na próxima chamada (quem lê o
    cofre a cada volta é `_headers`). Não recebe segredo novo sozinho: linha
    revogada bloqueia o provisionamento; o caminho de volta é o admin reemitir.
    """
    try:
        if resposta.headers.get(CABECALHO_CREDENCIAL_INVALIDA) != "1":
            return False
        apresentado = resposta.request.headers.get("X-API-Key") or ""
        if not apresentado:
            return False
        guardado = ler()
        if not guardado or guardado.get("segredo") != apresentado:
            return False
    except Exception:  # noqa: BLE001
        return False

    apagou = apagar()
    LOGGER.warning(
        "O portal recusou a credencial desta máquina; ela foi descartada e o "
        "serviço volta à X-API-Key. Se foi uma revogação, um admin precisa "
        "reemitir a credencial no portal."
    )
    return apagou
