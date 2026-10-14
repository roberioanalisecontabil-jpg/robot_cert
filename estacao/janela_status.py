"""Janela de status da bandeja: quem está logado e o que ela fez.

Veio de `core/janela_status.py` do Hardlyze, sem a linha do portal do
inventário. Responde de um olhar a pergunta que motivou a tela: O CERTIFICADO
FOI INSTALADO? Mostra só as linhas do log que são ação, e não pergunta nada ao
portal — uma tela de diagnóstico que depende da rede mente exatamente quando a
rede é o problema.

`montar_estado` e `acoes_do_log` decidem tudo sem tocar em widget nenhum.
"""

from __future__ import annotations

import logging
import os
import re
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from estacao import NOME

LOGGER = logging.getLogger(__name__)

_COR_FUNDO = "#f0f0f0"
_COR_CAMPO = "#e8f5e9"
_COR_TITULO = "#8b0000"
_COR_SUAVE = "#5f6368"
_COR_ERRO = "#c62828"
_COR_OK = "#2e7d32"

# Ler o arquivo inteiro seria desperdicio: o log roda em 2 MB x 5, e a janela
# abre a cada clique. 300 KB do fim cobrem folgadamente as ultimas horas.
_BYTES_DO_FIM = 300 * 1024

_LINHA = re.compile(
    r"^(?P<data>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+ - (?P<nivel>\w+) - (?P<resto>.*)$"
)

# O que NAO e acao. Cada uma destas se repete o dia inteiro e nao informa nada
# a quem abriu a tela para saber se o certificado entrou.
_RUIDO = (
    "agendamento atualizado",
    "http request:",          # rastro do httpx/requests
    "arquivo .env encontrado",
    "verificando config.json",
    "configuração de ambiente ausente",
    "configuracao de ambiente ausente",
)

# O que merece destaque. A instalacao vem primeiro porque e a razao da tela.
_DESTAQUE = (
    "certificado",
    "instalad",
    "dispositivo registrado",
    "vinculada",
    "comando recebido",
)


@dataclass
class EstadoAgente:
    """O que a janela mostra no cabecalho."""

    logado: bool = False
    email: str = ""
    maquina: str = ""
    portal: str = ""
    versao: str = ""
    caminho_log: str = ""
    acoes: list[dict[str, Any]] = field(default_factory=list)


def acoes_do_log(texto: str, limite: int = 200) -> list[dict[str, Any]]:
    """As linhas que contam alguma coisa, mais recentes por ultimo.

    Devolve dicts com `quando`, `nivel`, `mensagem` e `destaque`. Linha que nao
    casa com o formato do log e ignorada — sao continuacoes de traceback, e
    despeja-las na tela afogaria o que interessa.
    """
    saida: list[dict[str, Any]] = []
    for linha in (texto or "").splitlines():
        m = _LINHA.match(linha.strip())
        if not m:
            continue
        resto = m.group("resto").strip()
        # O prefixo do logger ("[InventAgent] ") nao diz nada a quem le a tela.
        resto = re.sub(r"^\[[^\]]+\]\s*", "", resto)
        baixo = resto.lower()
        if any(r in baixo for r in _RUIDO):
            continue
        if not resto:
            continue
        saida.append({
            "quando": m.group("data")[11:],   # so a hora; a data vai no cabecalho
            "dia": m.group("data")[:10],
            "nivel": m.group("nivel"),
            "mensagem": resto,
            "destaque": any(d in baixo for d in _DESTAQUE),
        })
    return saida[-limite:]


def _decodificar(bruto: bytes) -> str:
    """Decodifica LINHA A LINHA, tentando UTF-8 e caindo em cp1252.

    O arquivo tem as duas codificacoes misturadas: ate 23/08/2026 o agente
    gravava na codificacao local do Windows (cp1252), porque
    `logging.basicConfig` nao recebia `encoding`. Dai em diante grava UTF-8.

    Decodificar o arquivo inteiro de uma vez falharia na primeira linha antiga
    com acento, e `errors="replace"` transformaria "requisicao" em "requisi??o"
    — que foi exatamente o que apareceu na tela. Linha a linha, cada uma e lida
    como foi escrita.
    """
    partes = []
    for linha in bruto.split(b"\n"):
        try:
            partes.append(linha.decode("utf-8"))
        except UnicodeDecodeError:
            partes.append(linha.decode("cp1252", errors="replace"))
    return "\n".join(partes)


def _ler_fim(caminho: Path, bytes_do_fim: int = _BYTES_DO_FIM) -> str:
    try:
        with open(caminho, "rb") as f:
            f.seek(0, os.SEEK_END)
            f.seek(max(0, f.tell() - bytes_do_fim))
            return _decodificar(f.read())
    except OSError:
        return ""


def montar_estado(
    caminho_log: Path,
    portal: str,
    versao: str,
    credencial: dict[str, Any] | None,
) -> EstadoAgente:
    """Junta cabecalho e historico. Nao toca em Tk nem em rede."""
    return EstadoAgente(
        logado=bool(credencial),
        email=(credencial or {}).get("email", "") or "",
        maquina=(credencial or {}).get("machine_id", "") or "",
        portal=portal or "",
        versao=versao or "",
        caminho_log=str(caminho_log),
        acoes=acoes_do_log(_ler_fim(caminho_log)),
    )


# ── Desenho ──────────────────────────────────────────────────────────────

_aberta = threading.Event()


def abrir_janela(
    obter_estado: Callable[[], EstadoAgente],
    ao_entrar: Callable[[], None] | None = None,
    ao_sair_da_conta: Callable[[], None] | None = None,
) -> None:
    """Abre numa thread propria; chamada repetida enquanto aberta nao faz nada."""
    if _aberta.is_set():
        return
    _aberta.set()
    threading.Thread(
        target=_rodar,
        args=(obter_estado, ao_entrar, ao_sair_da_conta),
        name="CertguardJanelaStatus",
        daemon=True,
    ).start()


def _rodar(obter_estado, ao_entrar, ao_sair_da_conta) -> None:
    import tkinter as tk
    from tkinter import scrolledtext

    try:
        raiz = tk.Tk()
    except Exception:
        _aberta.clear()
        LOGGER.warning("Sem interface grafica para a janela de status.")
        return

    raiz.title(f"{NOME} — Status")
    raiz.configure(bg=_COR_FUNDO)
    raiz.geometry("940x680")
    raiz.minsize(700, 480)

    # ── menu ──
    menu = tk.Menu(raiz)
    arquivo = tk.Menu(menu, tearoff=0)
    arquivo.add_command(label="Fechar", command=lambda: _fechar(raiz))
    menu.add_cascade(label="Arquivo", menu=arquivo)

    conta = tk.Menu(menu, tearoff=0)
    if ao_entrar:
        conta.add_command(label="Entrar no portal…", command=ao_entrar)
    if ao_sair_da_conta:
        conta.add_command(label="Sair da conta nesta máquina", command=ao_sair_da_conta)
    menu.add_cascade(label="Conta", menu=conta)
    raiz.config(menu=menu)

    # ── cabecalho ──
    topo = tk.Frame(raiz, bg=_COR_FUNDO)
    topo.pack(fill="x", padx=18, pady=(14, 4))

    campos: dict[str, tk.Label] = {}
    for i, rotulo in enumerate(
        ["Usuário", "Máquina", "Portal", "Versão"]
    ):
        tk.Label(
            topo, text=f"{rotulo}:", bg=_COR_FUNDO, font=("Segoe UI", 9, "bold"),
            anchor="e", width=12,
        ).grid(row=i, column=0, sticky="e", pady=2)
        valor = tk.Label(
            topo, text="—", bg=_COR_FUNDO, font=("Segoe UI", 9), anchor="w",
            justify="left",
        )
        valor.grid(row=i, column=1, sticky="w", padx=(8, 0), pady=2)
        campos[rotulo] = valor

    tk.Label(
        raiz, text="Histórico das ações realizadas:", bg=_COR_FUNDO,
        fg=_COR_TITULO, font=("Segoe UI", 10, "bold"),
    ).pack(pady=(10, 4))

    historico = scrolledtext.ScrolledText(
        raiz, font=("Consolas", 9), wrap="word", state="disabled",
        bg="#ffffff", relief="solid", borderwidth=1,
    )
    historico.pack(fill="both", expand=True, padx=12, pady=(0, 10))
    historico.tag_configure("destaque", foreground=_COR_OK, font=("Consolas", 9, "bold"))
    historico.tag_configure("erro", foreground=_COR_ERRO)
    historico.tag_configure("hora", foreground=_COR_SUAVE)

    rodape = tk.Label(raiz, text="", bg=_COR_FUNDO, fg=_COR_SUAVE, font=("Segoe UI", 8))
    rodape.pack(fill="x", padx=12, pady=(0, 8))

    def _pintar(estado: EstadoAgente) -> None:
        campos["Usuário"].configure(
            text=estado.email if estado.logado else "não conectado — use Conta ▸ Entrar",
            fg="#000000" if estado.logado else _COR_ERRO,
        )
        campos["Máquina"].configure(text=estado.maquina or "—")
        campos["Portal"].configure(text=estado.portal or "—", bg=_COR_CAMPO)
        campos["Versão"].configure(text=estado.versao or "—")

        historico.configure(state="normal")
        historico.delete("1.0", "end")
        if not estado.acoes:
            historico.insert("end", "Nenhuma ação registrada ainda.\n")
        for a in estado.acoes:
            historico.insert("end", f"{a['quando']}  ", "hora")
            tag = "erro" if a["nivel"] in ("ERROR", "CRITICAL") else (
                "destaque" if a["destaque"] else ""
            )
            historico.insert("end", a["mensagem"] + "\n", tag)
        historico.see("end")
        historico.configure(state="disabled")
        rodape.configure(text=f"Log completo: {estado.caminho_log}")

    def _atualizar() -> None:
        try:
            _pintar(obter_estado())
        except Exception:
            LOGGER.exception("Falha ao atualizar a janela de status")
        # 3s: rapido o bastante para ver a instalacao acontecer, devagar o
        # bastante para nao reler 300 KB sem parar.
        raiz.after(3000, _atualizar)

    raiz.protocol("WM_DELETE_WINDOW", lambda: _fechar(raiz))
    _atualizar()
    try:
        raiz.mainloop()
    finally:
        _aberta.clear()


def _fechar(raiz) -> None:
    _aberta.clear()
    raiz.destroy()
