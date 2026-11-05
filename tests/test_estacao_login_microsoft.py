"""Tarefa 6: ouvinte loopback da bandeja e as chamadas novas ao portal.

Sem Tk. O "navegador" é um `abrir` falso que faz o pedido ao 127.0.0.1 numa
thread, como o portal faria no redirecionamento.
"""

from __future__ import annotations

import socket
import sys
import threading
import time
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest

from app.bandeja_codigo import desafio_de
from estacao import conta as cc
from estacao import login_microsoft as lm
from tests.test_estacao import MAQUINA, PORTAL, _Resp, estacao  # noqa: F401 (fixture)

so_windows = pytest.mark.skipif(sys.platform != "win32", reason="DPAPI só no Windows.")


def _navegador(*caminhos: str):
    """`abrir` falso: pede cada caminho ao loopback da URL de entrada, em ordem."""
    def abrir(url: str) -> None:
        porta = parse_qs(urlparse(url).query)["porta"][0]

        def _ir() -> None:
            for c in caminhos:
                try:
                    urllib.request.urlopen(f"http://127.0.0.1:{porta}{c}", timeout=3).read()
                except urllib.error.HTTPError:
                    pass

        threading.Thread(target=_ir, daemon=True).start()
    return abrir


def test_desafio_da_bandeja_igual_ao_do_portal() -> None:
    verificador, desafio = lm.novo_verificador()
    assert desafio == desafio_de(verificador)
    assert len(desafio) == 43


def test_ouvinte_so_em_loopback() -> None:
    ouvinte = lm.Ouvinte(prazo_s=0.2)
    try:
        assert ouvinte._servidor.server_address[0] == "127.0.0.1"
    finally:
        ouvinte._servidor.server_close()


def test_entrar_devolve_codigo() -> None:
    vistas: list[str] = []

    def abrir(url: str) -> None:
        vistas.append(url)
        _navegador("/?codigo=abc")(url)

    codigo, verificador = lm.entrar(PORTAL, abrir=abrir, prazo_s=5)
    assert codigo == "abc" and verificador
    q = parse_qs(urlparse(vistas[0]).query)
    assert vistas[0].startswith(PORTAL + "/entrar/microsoft/bandeja?")
    assert q["porta"][0].isdigit() and q["desafio"][0] == desafio_de(verificador)


def test_favicon_nao_encerra() -> None:
    codigo, _ = lm.entrar(PORTAL, abrir=_navegador("/favicon.ico", "/?codigo=abc"), prazo_s=5)
    assert codigo == "abc"


def test_erro_do_portal_vira_mensagem() -> None:
    with pytest.raises(RuntimeError, match="Entrada pela Microsoft cancelada."):
        lm.entrar(PORTAL, abrir=_navegador("/?erro=cancelada"), prazo_s=5)


def test_prazo_esgota_e_fecha_a_porta() -> None:
    portas: list[int] = []

    def abrir(url: str) -> None:
        portas.append(int(parse_qs(urlparse(url).query)["porta"][0]))

    with pytest.raises(RuntimeError, match=lm.MENSAGENS["prazo"]):
        lm.entrar(PORTAL, abrir=abrir, prazo_s=0.5)
    with pytest.raises(OSError):
        socket.create_connection(("127.0.0.1", portas[0]), timeout=1)


def test_conexao_muda_nao_segura_o_prazo() -> None:
    """Um socket que conecta e não envia nada (preconnect, outro processo) não trava a espera."""
    socks: list[socket.socket] = []
    saida: list = []

    def abrir(url: str) -> None:
        porta = int(parse_qs(urlparse(url).query)["porta"][0])
        socks.append(socket.create_connection(("127.0.0.1", porta), timeout=3))

    def _rodar() -> None:
        try:
            lm.entrar(PORTAL, abrir=abrir, prazo_s=1)
        except RuntimeError as e:
            saida.append(str(e))

    t0 = time.monotonic()
    t = threading.Thread(target=_rodar, daemon=True)  # daemon + join: nunca trava a suíte
    t.start()
    try:
        t.join(10)
        assert not t.is_alive(), "a espera travou na conexão muda"
        assert saida == [lm.MENSAGENS["prazo"]]
        assert time.monotonic() - t0 < 10
    finally:
        for s in socks:
            s.close()


class _Sessao:
    def __init__(self, get: Any = None, post: Any = None) -> None:
        self.chamadas: list = []
        self._get, self._post = get, post

    def get(self, url: str, **k: Any):
        self.chamadas.append(("GET", url, k))
        if isinstance(self._get, Exception):
            raise self._get
        return self._get

    def post(self, url: str, json: dict | None = None, **k: Any):
        self.chamadas.append(("POST", url, json))
        return self._post


def test_microsoft_ligada() -> None:
    assert cc.microsoft_ligada(_Sessao(get=_Resp(200, {"ligado": True})), PORTAL + "/") is True
    s = _Sessao(get=_Resp(200, {"ligado": False}))
    assert cc.microsoft_ligada(s, PORTAL) is False
    assert s.chamadas[0][1] == PORTAL + "/api/agent/microsoft" and s.chamadas[0][2]["timeout"] == 5


def test_microsoft_ligada_falha_vira_false() -> None:
    assert cc.microsoft_ligada(_Sessao(get=ConnectionError("fora")), PORTAL) is False
    assert cc.microsoft_ligada(_Sessao(get=_Resp(404)), PORTAL) is False


@so_windows
def test_registrar_pela_microsoft_guarda_a_conta(estacao: list) -> None:  # noqa: F811
    resp = _Resp(200, {"segredo": "seg-ms", "email": "ana@analisegroup.cnt.br", "machine_id": MAQUINA,
                       "autorizacao": "autorizado", "mensagem": "ok"})
    s = _Sessao(post=resp)
    r = cc.registrar_pela_microsoft(s, PORTAL + "/", "cod", "ver", MAQUINA, nome="PC-ANA", chave_maquina="k")
    assert r == {"email": "ana@analisegroup.cnt.br", "autorizacao": "autorizado", "mensagem": "ok"}
    assert s.chamadas[0][1] == PORTAL + "/api/agent/dispositivos/registrar-microsoft"
    assert s.chamadas[0][2] == {"codigo": "cod", "verificador": "ver", "machine_id": MAQUINA,
                                "nome": "PC-ANA", "chave_maquina": "k"}
    assert cc.ler()["segredo"] == "seg-ms" and cc.ler()["portal"] == PORTAL


def test_registrar_pela_microsoft_recusa_vira_erro() -> None:
    s = _Sessao(post=_Resp(401, {"detail": "Código expirado."}))
    with pytest.raises(RuntimeError, match="Código expirado."):
        cc.registrar_pela_microsoft(s, PORTAL, "cod", "ver", MAQUINA)


def test_pagina_final_tem_logo_e_manda_fechar():
    p = lm.pagina(lm.PRONTO, "detalhe")
    assert "Pronto, pode fechar esta página." in p
    # Logo embutido: o portal manda CORP same-origin, e 127.0.0.1 não carregaria o dele.
    assert 'src="data:image/png;base64,' in p and "<script" not in p
