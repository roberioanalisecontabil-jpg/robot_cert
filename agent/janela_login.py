"""
Janela de login do agente — onde a estação passa a saber de quem ela é.

Abre uma vez, na primeira execução depois da instalação, e depois só quando o
portal recusa o dispositivo (revogado, ou conta desativada). O que ela produz
não é uma sessão: é o registro do dispositivo, guardado cifrado por
`agent.identidade`. A senha digitada aqui morre com a janela.

Mesmo desenho de `janela_status`: não importa `run_agent` (o import circular
apareceria na primeira vez que alguém mexesse), roda em thread própria porque o
Tk quer o seu próprio laço de eventos e não divide thread com o pystray, e a
parte que decide fica separada da parte que desenha — `validar_campos` é
testável sem Tk, sem Windows e sem rede.
"""

from __future__ import annotations

import logging
import re
import threading
from typing import Any, Callable, Optional, Tuple

LOGGER = logging.getLogger(__name__)

_COR_FUNDO = "#f5f6f8"
_COR_ERRO = "#c62828"
_COR_OK = "#2e7d32"
_COR_SUAVE = "#5f6368"

# Não valida e-mail a sério de propósito: quem decide se a conta existe é o
# portal, e uma expressão esperta aqui recusaria endereços válidos que o
# servidor aceitaria — erro que a pessoa não tem como contornar.
_TEM_FORMA_DE_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+$")


def validar_campos(email: str, senha: str) -> Optional[str]:
    """
    O que dá para dizer antes de gastar uma ida ao portal. `None` = pode enviar.

    Só falta de preenchimento e forma grosseira do e-mail. Senha curta não é
    recusada aqui: a regra de senha é do portal, e duplicá-la faria a janela
    recusar uma senha que o servidor aceita — a pessoa ficaria sem saída, com a
    credencial certa em mãos.
    """
    if not (email or "").strip():
        return "Informe o e-mail do portal."
    if not _TEM_FORMA_DE_EMAIL.match(email.strip()):
        return "Esse e-mail não parece completo."
    if not (senha or ""):
        return "Informe a senha."
    return None


def mensagem_de_falha(erro: BaseException) -> str:
    """
    Traduz a falha para o que a pessoa pode FAZER.

    "O portal recusou o registro (401)" manda ninguém a lugar nenhum. Cada ramo
    aqui termina numa ação: corrigir a senha, trocar a senha, chamar o admin,
    tentar mais tarde.
    """
    texto = str(erro or "").strip()
    baixo = texto.lower()

    if "incorreto" in baixo or "401" in baixo:
        return "E-mail ou senha incorretos."
    if "troque a senha" in baixo:
        return "Sua senha é provisória. Troque-a no portal e volte aqui."
    if "desativado" in baixo:
        return "Esta conta está desativada. Procure um administrador."
    if "dpapi" in baixo or "cryptprotect" in baixo:
        return "O Windows não permitiu guardar a credencial nesta conta."
    if any(p in baixo for p in ("timeout", "connect", "conexão", "conexao", "503")):
        return "Não foi possível falar com o portal. Verifique a rede."
    return texto or "Não foi possível registrar este computador."


def abrir_janela(
    ao_registrar: Callable[[str, str], Any],
    portal: str,
    machine_id: str,
    ao_concluir: Optional[Callable[[], None]] = None,
) -> None:
    """
    Abre o login numa thread própria. Chamada repetida enquanto aberta não faz nada.

    `ao_registrar(email, senha)` é injetada pelo `run_agent` — é ela que fala
    com o portal. Manter a chamada fora daqui é o que permite testar a janela
    sem rede e o registro sem Tk.
    """
    if _janela_aberta.is_set():
        return
    _janela_aberta.set()
    threading.Thread(
        target=_rodar_janela,
        args=(ao_registrar, portal, machine_id, ao_concluir),
        name="AnaliseCertiDigitalJanelaLogin",
        daemon=True,
    ).start()


_janela_aberta = threading.Event()


def _rodar_janela(ao_registrar, portal, machine_id, ao_concluir) -> None:
    import tkinter as tk

    try:
        raiz = tk.Tk()
    except Exception:  # noqa: BLE001
        # Sessão sem desktop (serviço, ou logon remoto sem interface). Não é
        # erro: o serviço não faz login, quem faz é a bandeja.
        _janela_aberta.clear()
        LOGGER.warning("Sem interface gráfica disponível para a janela de login.")
        return

    raiz.title("Analise CertiDigital Agent — Entrar")
    raiz.configure(bg=_COR_FUNDO)
    raiz.resizable(False, False)
    raiz.geometry("440x330")

    tk.Label(
        raiz, text="Entrar no portal", bg=_COR_FUNDO,
        font=("Segoe UI", 13, "bold"), anchor="w",
    ).pack(fill="x", padx=22, pady=(20, 2))

    tk.Label(
        raiz,
        text=(
            "Use o mesmo e-mail e senha do portal. Este computador fica\n"
            "vinculado à sua conta, e a senha não é guardada aqui."
        ),
        bg=_COR_FUNDO, fg=_COR_SUAVE, font=("Segoe UI", 9),
        anchor="w", justify="left",
    ).pack(fill="x", padx=22, pady=(0, 12))

    corpo = tk.Frame(raiz, bg=_COR_FUNDO)
    corpo.pack(fill="x", padx=22)

    tk.Label(corpo, text="E-mail", bg=_COR_FUNDO, fg=_COR_SUAVE,
             font=("Segoe UI", 9), anchor="w").pack(fill="x")
    campo_email = tk.Entry(corpo, font=("Segoe UI", 10))
    campo_email.pack(fill="x", pady=(2, 10), ipady=3)

    tk.Label(corpo, text="Senha", bg=_COR_FUNDO, fg=_COR_SUAVE,
             font=("Segoe UI", 9), anchor="w").pack(fill="x")
    campo_senha = tk.Entry(corpo, show="●", font=("Segoe UI", 10))
    campo_senha.pack(fill="x", pady=(2, 6), ipady=3)

    aviso = tk.Label(raiz, text="", bg=_COR_FUNDO, fg=_COR_ERRO,
                     font=("Segoe UI", 9), anchor="w", justify="left", wraplength=396)
    aviso.pack(fill="x", padx=22, pady=(4, 0))

    rodape = tk.Frame(raiz, bg=_COR_FUNDO)
    rodape.pack(fill="x", padx=22, pady=(10, 6))

    tk.Label(
        rodape, text=f"{portal}\n{machine_id}", bg=_COR_FUNDO, fg=_COR_SUAVE,
        font=("Segoe UI", 8), anchor="w", justify="left",
    ).pack(side="left")

    botao = tk.Button(rodape, text="Entrar", font=("Segoe UI", 10), width=12)
    botao.pack(side="right")

    def _fechar() -> None:
        # A senha sai da memória do Tk junto com o widget. Explícito porque
        # `destroy` sozinho não zera a variável do Entry de imediato.
        try:
            campo_senha.delete(0, "end")
        except Exception:  # noqa: BLE001
            pass
        _janela_aberta.clear()
        raiz.destroy()

    def _enviar(*_a: Any) -> None:
        email = campo_email.get().strip()
        senha = campo_senha.get()

        problema = validar_campos(email, senha)
        if problema:
            aviso.configure(text=problema, fg=_COR_ERRO)
            return

        botao.configure(state="disabled", text="Entrando…")
        aviso.configure(text="", fg=_COR_ERRO)
        raiz.update_idletasks()

        def _trabalho() -> None:
            try:
                ao_registrar(email, senha)
            except BaseException as e:  # noqa: BLE001
                LOGGER.warning("Registro do dispositivo recusado: %s", e)
                raiz.after(0, _falhou, mensagem_de_falha(e))
                return
            finally:
                # Não fica pendurada em variável de fecho depois do envio.
                del senha
            raiz.after(0, _conseguiu)

        # Fora da thread do Tk: a chamada ao portal pode levar segundos, e
        # congelar a janela faria a pessoa clicar de novo.
        threading.Thread(target=_trabalho, daemon=True).start()

    def _falhou(texto: str) -> None:
        aviso.configure(text=texto, fg=_COR_ERRO)
        botao.configure(state="normal", text="Entrar")
        campo_senha.delete(0, "end")
        campo_senha.focus_set()

    def _conseguiu() -> None:
        aviso.configure(text="Computador vinculado à sua conta.", fg=_COR_OK)
        botao.configure(text="Pronto")
        if ao_concluir:
            try:
                ao_concluir()
            except Exception:  # noqa: BLE001
                LOGGER.exception("Falha no aviso de conclusão do login")
        raiz.after(1200, _fechar)

    botao.configure(command=_enviar)
    raiz.bind("<Return>", _enviar)
    raiz.protocol("WM_DELETE_WINDOW", _fechar)
    campo_email.focus_set()

    try:
        raiz.mainloop()
    finally:
        _janela_aberta.clear()
