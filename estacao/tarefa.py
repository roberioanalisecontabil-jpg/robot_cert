"""A tarefa agendada da atualização automática (1.1.0, 20/10/2026).

  certguard_analise.exe --atualizacao        a tarefa (SYSTEM): na partida do
                                             Windows, a cada 6 h e no fim de
                                             toda instalação
  atualizador.exe --atualizar <pedido.json>  o atualizador, de uma CÓPIA do exe

A lógica mora em `estacao/atualizador.py`; aqui só a ligação com o portal, o
disco do sistema e os processos — o que no Hardlyze ficava no `main.py`.

Uma rodada da tarefa, na ordem:

1. pede o manifesto ao portal. Se o portal não responde, para aqui: a versão
   nova só confirma depois de alcançar o portal, que é o que ela afirma;
2. confirma o pedido, se o atualizador está esperando por esta versão, e
   reabre a bandeja nas sessões (o instalador silencioso fechou todas);
3. com o mesmo manifesto, decide se há versão nova e dispara o atualizador.

As rotas do portal são abertas (ADR 0003): quem garante a versão é a
assinatura, conferida aqui. Só o evento leva a chave da máquina.
"""

from __future__ import annotations

import ctypes
import logging
import os
import shutil
import subprocess
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from estacao import VERSAO, atualizador, caminhos, conta

logger = logging.getLogger("estacao.tarefa")

NOME_TAREFA = "Certguard Analise - atualizacao"
EXE = "certguard_analise.exe"
_MUTEX = None
_SEM_JANELA = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def pastas() -> atualizador.Pastas:
    return atualizador.Pastas(str(caminhos.pasta_maquina() / "atualizacoes"))


def portal() -> str:
    # A tarefa roda como SYSTEM: não há conta da pessoa para dizer o endereço.
    return (os.getenv("CERT_PORTAL_URL") or conta.PORTAL_PADRAO).strip().rstrip("/")


def configurar_log(nome: str) -> None:
    """`%ProgramData%\\CertguardAnalise\\logs\\<nome>`: a pasta de logs da
    máquina, a mesma do `--preparar-chave`."""
    pasta = caminhos.pasta_maquina() / "logs"
    pasta.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(pasta / nome, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
    raiz = logging.getLogger()
    raiz.setLevel(logging.INFO)
    raiz.addHandler(handler)
    logging.getLogger("httpx").setLevel(logging.WARNING)


def e_estacao() -> bool:
    """False no Windows Server (ProductType diferente de WinNT): servidor não
    se atualiza sozinho. Na dúvida, estação — é o caso comum."""
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\ProductOptions") as k:
            return str(winreg.QueryValueEx(k, "ProductType")[0]).strip().lower() == "winnt"
    except OSError:
        return True


def _unica() -> bool:
    """Uma rodada por vez na máquina: a da partida e a do fim da instalação
    podem coincidir, e duas baixariam o mesmo instalador no mesmo arquivo."""
    global _MUTEX
    try:
        _MUTEX = ctypes.windll.kernel32.CreateMutexW(None, False, "Global\\CertguardAnaliseAtualizacao")
        return ctypes.windll.kernel32.GetLastError() != 183  # ERROR_ALREADY_EXISTS
    except Exception:
        return True


# ── Portal ──────────────────────────────────────────────────────────────


def _cliente():
    import httpx

    return httpx.Client(timeout=30, headers={"X-Agent-Version": f"certguard-{VERSAO}"})


def buscar_pacote(http) -> dict | None:
    r = http.get(f"{portal()}/api/estacao/atualizacao")
    if r.status_code == 204:
        return None
    r.raise_for_status()
    return r.json()


def baixar_instalador(http, sha256: str, destino: str) -> None:
    with http.stream("GET", f"{portal()}/api/estacao/atualizacao/arquivo/{sha256}", timeout=300) as r:
        r.raise_for_status()
        with open(destino, "wb") as f:
            for bloco in r.iter_bytes(1024 * 1024):
                f.write(bloco)


def contar_ao_portal(http, resultado: str, de: str, para: str, detalhe: str) -> None:
    """O evento leva a chave da máquina: é ela que prova ao portal de qual
    computador veio. Falhar aqui não desfaz nada, só fica no log."""
    from estacao import bandeja, chave_maquina

    try:
        r = http.post(f"{portal()}/api/estacao/atualizacao/evento", json={
            "machine_id": bandeja.machine_id(), "chave": chave_maquina.ler() or "",
            "de": de, "para": para, "resultado": resultado, "detalhe": detalhe[:500],
        })
        if r.status_code >= 400:
            logger.warning("Portal recusou o evento de atualização (%s).", r.status_code)
    except Exception:
        logger.warning("Não foi possível contar a atualização ao portal.", exc_info=True)


# ── Processos e disco ───────────────────────────────────────────────────


def proteger_pasta(raiz: str) -> bool:
    return atualizador.proteger_pasta(
        raiz, lambda c: subprocess.run(c, capture_output=True, timeout=60, creationflags=_SEM_JANELA).returncode
    )


def disparar_atualizador(pedido: str) -> None:
    """Sobe o atualizador a partir de uma CÓPIA do executável: o original é
    sobrescrito pela instalação, e o instalador fecha todo `certguard_analise.exe`.
    Desanexado e fora do job da tarefa agendada, para sobreviver ao fim dela."""
    if not getattr(sys, "frozen", False):
        logger.warning("Fora do executável (desenvolvimento): atualizador não disparado.")
        return
    copia = os.path.join(os.path.dirname(pedido), "atualizador.exe")
    shutil.copy2(sys.executable, copia)
    base = 0x00000008 | 0x00000200 | 0x08000000  # DETACHED | NEW_GROUP | NO_WINDOW
    try:
        subprocess.Popen([copia, "--atualizar", pedido], creationflags=base | 0x01000000, close_fds=True)  # BREAKAWAY_FROM_JOB
    except OSError:
        # Job que não deixa sair: sobe dentro dele mesmo.
        subprocess.Popen([copia, "--atualizar", pedido], creationflags=base, close_fds=True)


def instalar(caminho: str, raiz: str, anterior: str) -> int:
    """Roda o instalador em silêncio. A volta grava o log à parte: no mesmo
    arquivo, ela apagava o registro da instalação que falhou (Hardlyze,
    ensaio de 13/10/2026)."""
    volta = os.path.normcase(os.path.abspath(caminho)) == os.path.normcase(os.path.abspath(anterior))
    log_instalacao = os.path.join(raiz, "instalacao-volta.log" if volta else "instalacao.log")
    try:
        r = subprocess.run(
            [caminho, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-", f"/LOG={log_instalacao}"],
            timeout=1800, creationflags=_SEM_JANELA,
        )
        return r.returncode
    except Exception:
        logger.exception("O instalador %s não rodou.", caminho)
        return -1


# ── O passo do instalador ───────────────────────────────────────────────

# Duas tarefas porque o schtasks não põe dois gatilhos numa só sem XML: a da
# partida espera a rede subir; a de 6 h pega a máquina que nunca desliga.
TAREFAS = (
    (NOME_TAREFA, ["/SC", "ONSTART", "/DELAY", "0005:00"]),
    (NOME_TAREFA + " 6h", ["/SC", "HOURLY", "/MO", "6"]),
)


def comandos_das_tarefas(exe: str) -> list[list[str]]:
    return [
        ["schtasks", "/Create", "/F", "/TN", nome, *gatilho, "/RU", "SYSTEM", "/RL", "HIGHEST",
         "/TR", f'"{exe}" --atualizacao']
        for nome, gatilho in TAREFAS
    ]


def preparar_atualizacao(instalador: str, exe: str, executar=None) -> int:
    """Chamado pelo instalador (admin) no fim de toda instalação:

    1. tranca a pasta de atualização (só SYSTEM e Administradores);
    2. guarda o próprio instalador como `instalado.exe` — é ele que vira o
       "anterior" para a volta automática da próxima versão;
    3. cria (ou recria) as tarefas agendadas.

    Devolve 0 se tudo pegou. Falhar aqui não impede a bandeja de funcionar,
    só a atualização automática desta máquina.
    """
    executar = executar or (lambda c: subprocess.run(c, capture_output=True, timeout=60, creationflags=_SEM_JANELA).returncode)
    p = pastas()
    if not atualizador.proteger_pasta(p.raiz, executar):
        logger.error("Pasta de atualização não pôde ser trancada.")
        return 1
    codigo = 0
    origem = os.path.abspath(instalador)
    if os.path.isfile(origem) and os.path.normcase(origem) != os.path.normcase(os.path.abspath(p.instalado)):
        shutil.copyfile(origem, p.instalado)
    else:
        logger.warning("Instalador %s não encontrado; sem cópia para voltar atrás.", instalador)
        codigo = 1
    for comando in comandos_das_tarefas(exe):
        if executar(comando) != 0:
            logger.error("Não foi possível criar a tarefa %s.", comando[4])
            codigo = 1
    return codigo


# ── Os dois modos ───────────────────────────────────────────────────────


def rodar_tarefa() -> int:
    configurar_log("atualizacao.log")
    if not _unica():
        logger.info("Outra rodada da atualização já está em curso; encerrando esta.")
        return 0
    p = pastas()
    with _cliente() as http:
        try:
            pacote = buscar_pacote(http)
        except Exception as e:
            logger.warning("Portal não respondeu à conferência de versão: %s", e)
            return 1
        try:
            r = atualizador.confirmar_na_partida(
                pastas=p, versao_atual=VERSAO,
                contar=lambda res, de, para, det: contar_ao_portal(http, res, de, para, det),
                log=logger.info,
            )
        except Exception:
            logger.exception("Falha ao conferir a atualização na partida.")
            r = ""
        if r in (atualizador.CONFIRMADO, atualizador.VOLTOU):
            from estacao import sessoes

            exe = Path(sys.executable).with_name(EXE)
            if exe.is_file():
                logger.info("Bandeja reaberta em %d sessão(ões).", sessoes.reabrir_bandejas(str(exe)))
        try:
            resultado = atualizador.verificar_e_disparar(
                pastas=p, versao_atual=VERSAO,
                buscar_pacote=lambda: pacote,
                baixar=lambda sha, destino: baixar_instalador(http, sha, destino),
                disparar=disparar_atualizador, proteger=proteger_pasta,
                log=logger.info, estacao=e_estacao,
            )
        except Exception:
            logger.exception("Conferência de atualização falhou; tenta de novo na próxima rodada.")
            return 1
    logger.info("Atualização automática (%s): %s.", VERSAO, resultado)
    return 0


def rodar_atualizador(pedido: str) -> int:
    """Modo `--atualizar`: instala, espera a confirmação e volta se preciso."""
    configurar_log("atualizador.log")
    p = atualizador.Pastas(os.path.dirname(os.path.abspath(pedido)))
    # De novo aqui, como SYSTEM, antes de rodar qualquer coisa da pasta.
    if not proteger_pasta(p.raiz):
        logger.error("Pasta de atualização não pôde ser trancada; nada instalado.")
        return 1
    final = atualizador.executar_pedido(
        pastas=p, instalar=lambda c: instalar(c, p.raiz, p.anterior), log=logger.info
    )
    logger.info("Atualizador terminou: %s.", final)
    return 0
