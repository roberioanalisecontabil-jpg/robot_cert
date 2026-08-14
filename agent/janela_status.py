"""
Janela de status do agente, aberta pelo menu da bandeja.

Existe porque o ícone sozinho responde a uma pergunta ("está ativo?") e o
diagnóstico costuma precisar de outras quatro: qual portal ele usa, sob que
machine_id, quando foi a última leitura e qual foi o último erro. Sem isso, o
caminho para descobrir que o agente falava com o endereço errado passava por
abrir o agent.log num servidor.

Não importa `run_agent`: recebe tudo por parâmetro. Isso evita import circular
(quem abre a janela é o menu da bandeja, dentro do run_agent) e deixa o
conteúdo testável sem Windows, sem serviço e sem Tk.
"""

from __future__ import annotations

import ctypes
import re
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

# Uma linha do agent.log: "2026-08-09 21:32:40,575 [ERROR] mensagem"
_LINHA_LOG = re.compile(
    r"^(?P<data>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+ \[(?P<nivel>\w+)\] (?P<msg>.*)$"
)

# Ler o arquivo inteiro seria desperdício: o agent.log passa de 250 KB com
# facilidade (o do ANALISESRV tinha 288 KB de uma falha só) e a janela abre a
# cada clique. 200 KB do fim cobrem folgadamente as últimas horas.
_BYTES_DO_FIM = 200 * 1024


@dataclass
class EstadoAgente:
    """O que a janela mostra. Montado por `montar_estado`, sem tocar em Tk."""

    servico_ativo: bool
    versao: str
    ultima_consulta: Optional[str]
    portal: str
    machine_id: str
    certificados_lidos: Optional[int]
    ultimo_erro: Optional[str]
    atividade: str  # "ocioso" | "escaneando" | "enviando" | "desconhecido"


def ultimo_erro_do_log(caminho: Path, agora: Optional[datetime] = None) -> Optional[str]:
    """
    Última linha [ERROR] do log, formatada como "há X — mensagem".

    Devolve None quando não há erro algum — que é o caso saudável e precisa ser
    distinguível de "não consegui ler o log".
    """
    try:
        tamanho = caminho.stat().st_size
        with caminho.open("rb") as fh:
            if tamanho > _BYTES_DO_FIM:
                fh.seek(tamanho - _BYTES_DO_FIM)
                fh.readline()  # descarta a linha partida ao meio pelo seek
            bruto = fh.read().decode("utf-8", errors="replace")
    except OSError:
        return None

    for linha in reversed(bruto.splitlines()):
        m = _LINHA_LOG.match(linha.strip())
        if not m or m.group("nivel") != "ERROR":
            continue
        msg = m.group("msg")
        try:
            quando = datetime.strptime(m.group("data"), "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return msg
        return f"{_ha_quanto_tempo(quando, agora or datetime.now())} — {msg}"
    return None


def _ha_quanto_tempo(quando: datetime, agora: datetime) -> str:
    segundos = max(0, int((agora - quando).total_seconds()))
    if segundos < 60:
        return "agora há pouco"
    if segundos < 3600:
        return f"há {segundos // 60} min"
    if segundos < 86400:
        return f"há {segundos // 3600} h"
    return quando.strftime("%d/%m/%Y %H:%M")


def montar_estado(
    *,
    servico_ativo: bool,
    status: Optional[dict],
    versao: str,
    portal: str,
    machine_id: str,
    caminho_log: Path,
    agora: Optional[datetime] = None,
) -> EstadoAgente:
    """Reúne os dados exibidos. Sem I/O de rede e sem Tk — daí ser testável."""
    status = status or {}
    agora = agora or datetime.now()

    ultima = None
    ts = status.get("last_scan_time")
    if ts:
        try:
            ultima = _ha_quanto_tempo(datetime.fromtimestamp(float(ts)), agora)
        except (ValueError, OSError, OverflowError):
            ultima = None

    estado_bruto = str(status.get("state") or "")
    atividade = {
        "scanning": "escaneando",
        "sending": "enviando",
        "idle": "ocioso",
    }.get(estado_bruto, "desconhecido")
    # "stale" é o que `_read_agent_status` escreve quando o estado passou de 5
    # min sem atualização. Com intervalo de 24 h isso é o normal, não um
    # problema — mostrar "desconhecido" assustaria à toa.
    if estado_bruto == "stale":
        atividade = "ocioso"

    lidos = status.get("items_count")
    try:
        lidos = int(lidos) if lidos not in (None, "") else None
    except (TypeError, ValueError):
        lidos = None

    return EstadoAgente(
        servico_ativo=servico_ativo,
        versao=versao,
        ultima_consulta=ultima,
        portal=portal or "(não configurado)",
        machine_id=machine_id or "(não configurado)",
        certificados_lidos=lidos,
        ultimo_erro=ultimo_erro_do_log(caminho_log, agora),
        atividade=atividade,
    )


def _executar_elevado(argumentos: str) -> bool:
    """
    Executa `sc.exe <argumentos>` pedindo elevação (UAC).

    Parar e iniciar serviço exigem privilégio que a bandeja não tem: ela roda na
    sessão do usuário. Sem o "runas" o botão falharia com acesso negado, e o
    usuário não teria como saber que faltava elevação.
    """
    try:
        rc = ctypes.windll.shell32.ShellExecuteW(
            None, "runas", "sc.exe", argumentos, None, 0  # SW_HIDE
        )
        # ShellExecuteW devolve > 32 em sucesso. 5 (SE_ERR_ACCESSDENIED) é o
        # usuário clicando "Não" no diálogo do UAC.
        return int(rc) > 32
    except Exception:
        return False


def parar_servico(nome_servico: str) -> bool:
    return _executar_elevado(f'stop "{nome_servico}"')


def iniciar_servico(nome_servico: str) -> bool:
    return _executar_elevado(f'start "{nome_servico}"')


def abrir_janela(
    *,
    obter_estado: Callable[[], EstadoAgente],
    nome_servico: str,
    ao_parar: Optional[Callable[[], bool]] = None,
    ao_iniciar: Optional[Callable[[], bool]] = None,
) -> None:
    """
    Abre a janela numa thread própria.

    O Tk precisa do seu próprio laço de eventos e não pode dividir thread com o
    pystray. Só esta thread toca nos widgets.
    """
    if _janela_aberta.is_set():
        return
    _janela_aberta.set()
    threading.Thread(
        target=_rodar_janela,
        args=(obter_estado, nome_servico, ao_parar, ao_iniciar),
        name="AnaliseCertiDigitalJanelaStatus",
        daemon=True,
    ).start()


_janela_aberta = threading.Event()

_COR_FUNDO = "#f5f6f8"
_COR_ATIVO = "#2e7d32"
_COR_PARADO = "#9e9e9e"
_COR_ERRO = "#c62828"


def _rodar_janela(obter_estado, nome_servico, ao_parar, ao_iniciar) -> None:
    import tkinter as tk
    from tkinter import ttk

    try:
        raiz = tk.Tk()
    except Exception:
        _janela_aberta.clear()
        return

    raiz.title("Analise CertiDigital Agent — Status")
    raiz.configure(bg=_COR_FUNDO)
    raiz.resizable(False, False)
    raiz.geometry("520x360")

    cabecalho = tk.Frame(raiz, bg=_COR_FUNDO)
    cabecalho.pack(fill="x", padx=18, pady=(16, 6))

    farol = tk.Canvas(cabecalho, width=16, height=16, bg=_COR_FUNDO, highlightthickness=0)
    farol.pack(side="left")
    bola = farol.create_oval(2, 2, 14, 14, fill=_COR_PARADO, outline="")

    rotulo_estado = tk.Label(cabecalho, text="—", bg=_COR_FUNDO,
                             font=("Segoe UI", 12, "bold"), anchor="w")
    rotulo_estado.pack(side="left", padx=(8, 0))

    corpo = tk.Frame(raiz, bg=_COR_FUNDO)
    corpo.pack(fill="both", expand=True, padx=18, pady=6)

    campos: dict[str, tk.Label] = {}
    for i, titulo in enumerate(
        ["Versão", "Última consulta", "Certificados lidos", "Portal", "Máquina"]
    ):
        tk.Label(corpo, text=titulo, bg=_COR_FUNDO, fg="#5f6368",
                 font=("Segoe UI", 9), anchor="w").grid(row=i, column=0, sticky="w", pady=3)
        valor = tk.Label(corpo, text="—", bg=_COR_FUNDO, font=("Segoe UI", 9),
                         anchor="w", justify="left", wraplength=330)
        valor.grid(row=i, column=1, sticky="w", padx=(14, 0), pady=3)
        campos[titulo] = valor

    tk.Label(corpo, text="Último erro", bg=_COR_FUNDO, fg="#5f6368",
             font=("Segoe UI", 9), anchor="w").grid(row=5, column=0, sticky="nw", pady=(10, 3))
    rotulo_erro = tk.Label(corpo, text="—", bg=_COR_FUNDO, font=("Segoe UI", 9),
                           anchor="w", justify="left", wraplength=330, fg=_COR_ERRO)
    rotulo_erro.grid(row=5, column=1, sticky="w", padx=(14, 0), pady=(10, 3))

    rodape = tk.Frame(raiz, bg=_COR_FUNDO)
    rodape.pack(fill="x", padx=18, pady=(6, 16))

    btn_parar = ttk.Button(rodape, text="Parar serviço")
    btn_iniciar = ttk.Button(rodape, text="Iniciar serviço")
    btn_parar.pack(side="left")
    btn_iniciar.pack(side="left", padx=(8, 0))
    ttk.Button(rodape, text="Fechar", command=raiz.destroy).pack(side="right")

    def atualizar() -> None:
        try:
            e = obter_estado()
        except Exception:
            raiz.after(3000, atualizar)
            return

        if e.servico_ativo:
            texto = {"escaneando": "Verificando certificados...",
                     "enviando": "Enviando ao portal..."}.get(e.atividade, "Ativo")
            farol.itemconfig(bola, fill=_COR_ATIVO)
        else:
            texto = "Parado"
            farol.itemconfig(bola, fill=_COR_PARADO)
        rotulo_estado.config(text=texto)

        campos["Versão"].config(text=e.versao)
        campos["Última consulta"].config(text=e.ultima_consulta or "nunca")
        campos["Certificados lidos"].config(
            text="—" if e.certificados_lidos is None else str(e.certificados_lidos))
        campos["Portal"].config(text=e.portal)
        campos["Máquina"].config(text=e.machine_id)
        rotulo_erro.config(text=e.ultimo_erro or "nenhum")

        btn_parar.state(["!disabled"] if e.servico_ativo else ["disabled"])
        btn_iniciar.state(["disabled"] if e.servico_ativo else ["!disabled"])

        raiz.after(2000, atualizar)

    def _acao(fn):
        def interno():
            if fn:
                fn()
            # O serviço leva um instante para mudar de estado; relê logo depois
            # em vez de esperar o ciclo de 2 s, para o botão parecer responsivo.
            raiz.after(1200, atualizar)
        return interno

    btn_parar.config(command=_acao(ao_parar or (lambda: parar_servico(nome_servico))))
    btn_iniciar.config(command=_acao(ao_iniciar or (lambda: iniciar_servico(nome_servico))))

    def ao_fechar() -> None:
        _janela_aberta.clear()
        raiz.destroy()

    raiz.protocol("WM_DELETE_WINDOW", ao_fechar)
    atualizar()
    try:
        raiz.mainloop()
    finally:
        _janela_aberta.clear()
