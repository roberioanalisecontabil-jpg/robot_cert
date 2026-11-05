"""Entrar com a Microsoft, do lado da bandeja.

A bandeja abre o navegador no portal e escuta o retorno em 127.0.0.1, numa
porta aleatória: o portal manda o navegador para `http://127.0.0.1:<porta>/?codigo=`
(ou `?erro=`). O código vale uma vez; só ele, com o verificador que nunca sai
daqui, vira o segredo do dispositivo. A bandeja não importa `app`: o desafio é
reimplementado (igual a `app.bandeja_codigo.desafio_de`, o teste confere).
"""

from __future__ import annotations

import base64
import hashlib
import html
import secrets
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Callable
from urllib.parse import parse_qs, quote, urlparse

from estacao.logo_analise import PNG_BASE64

PRAZO_S = 300

# As quatro do portal (app/rotas/microsoft.py MENSAGENS_ERRO), copiadas.
MENSAGENS = {
    "recusada": "Não foi possível entrar com essa conta da Microsoft. Procure o TI.",
    "desativada": "Sua conta está desativada. Procure o TI.",
    "falha": "Não foi possível entrar com a Microsoft agora. Tente de novo ou procure o TI.",
    "cancelada": "Entrada pela Microsoft cancelada.",
    "prazo": "O navegador não voltou a tempo. Tente de novo.",
}


PRONTO = "Pronto, pode fechar esta página."


def pagina(titulo: str, detalhe: str = "") -> str:
    """A página que o navegador mostra no fim: logo da Análise, título e uma linha.
    Os textos são fixos deste módulo; o escape é só por garantia."""
    sub = f"<p>{html.escape(detalhe)}</p>" if detalhe else ""
    return (
        '<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        "<title>CertGuard Análise</title><style>"
        "body{margin:0;min-height:100vh;display:grid;place-items:center;background:#F3EFE7;"
        "font-family:'Segoe UI',system-ui,sans-serif;color:#212121}"
        "main{background:#fff;border-radius:16px;padding:40px 36px;max-width:380px;margin:16px;"
        "text-align:center;box-shadow:0 8px 30px rgba(154,106,61,.15)}"
        "img{width:72px;height:72px}h1{font-size:20px;margin:16px 0 8px;font-weight:600}"
        "p{margin:0;color:#52504C;font-size:14px;line-height:1.5}"
        "</style></head><body><main>"
        f'<img src="data:image/png;base64,{PNG_BASE64}" alt="Análise Group">'
        f"<h1>{html.escape(titulo)}</h1>{sub}</main></body></html>"
    )


def novo_verificador() -> tuple[str, str]:
    """`(verificador, desafio)`; o desafio é o sha256 do verificador em base64url."""
    verificador = secrets.token_urlsafe(48)
    h = hashlib.sha256(verificador.encode("utf-8")).digest()
    return verificador, base64.urlsafe_b64encode(h).decode("ascii").rstrip("=")


class _Pedido(BaseHTTPRequestHandler):
    # Sem isso uma conexão muda (preconnect do navegador) trava o laço de uma thread só.
    timeout = 5

    def log_message(self, *_a: Any) -> None:  # sem log de acesso
        pass

    def _texto(self, status: int, texto: str, detalhe: str = "") -> None:
        corpo = pagina(texto, detalhe).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(corpo)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(corpo)

    def do_GET(self) -> None:  # noqa: N802
        url = urlparse(self.path)
        q = parse_qs(url.query)
        if url.path == "/" and (q.get("codigo") or q.get("erro")):
            if q.get("codigo"):
                self.server.resultado = {"codigo": q["codigo"][0]}  # type: ignore[attr-defined]
                self._texto(200, PRONTO, "A bandeja do CertGuard Análise termina a conexão sozinha.")
            else:
                chave = q["erro"][0] if q["erro"][0] in MENSAGENS else "falha"
                self.server.resultado = {"erro": chave}  # type: ignore[attr-defined]
                self._texto(200, MENSAGENS[chave], "Volte para a bandeja para tentar de novo.")
        else:
            self._texto(404, "Não encontrado.")  # favicon, pré-carregamento: segue esperando


class Ouvinte:
    def __init__(self, prazo_s: float = PRAZO_S) -> None:
        self.prazo_s = prazo_s
        self._servidor = HTTPServer(("127.0.0.1", 0), _Pedido)
        self._servidor.resultado = None  # type: ignore[attr-defined]
        self._servidor.timeout = 0.25
        self.porta: int = self._servidor.server_address[1]

    def esperar(self) -> dict[str, str]:
        limite = time.monotonic() + self.prazo_s
        try:
            while self._servidor.resultado is None and time.monotonic() < limite:  # type: ignore[attr-defined]
                self._servidor.handle_request()
            return self._servidor.resultado or {"erro": "prazo"}  # type: ignore[attr-defined]
        finally:
            self.fechar()

    def fechar(self) -> None:
        self._servidor.server_close()


def url_de_entrada(portal: str, porta: int, desafio: str) -> str:
    return f"{portal.strip().rstrip('/')}/entrar/microsoft/bandeja?porta={porta}&desafio={quote(desafio)}"


def entrar(portal: str, abrir: Callable[[str], Any] = webbrowser.open,
           prazo_s: float = PRAZO_S) -> tuple[str, str]:
    """Abre o navegador e espera o retorno. Devolve `(codigo, verificador)`."""
    verificador, desafio = novo_verificador()
    ouvinte = Ouvinte(prazo_s)
    try:
        abrir(url_de_entrada(portal, ouvinte.porta, desafio))
    except BaseException:
        ouvinte.fechar()
        raise
    resultado = ouvinte.esperar()
    if "codigo" not in resultado:
        raise RuntimeError(MENSAGENS[resultado["erro"]])
    return resultado["codigo"], verificador
