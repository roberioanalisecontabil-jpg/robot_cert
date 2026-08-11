"""
O agente precisa seguir redirects para falar com o portal.

Regressão de produção (ANALISESRV): o `agent_config.json` apontava para
`http://certificado.analisegroup.cnt.br`, e o portal responde 308 para a versão
https. Como o httpx não segue redirects por padrão, o 308 chegava intacto a
`fetch_portal_settings`, era rejeitado pelo `raise_for_status` e virava
"unavailable" — indistinguível de um portal fora do ar.

Este defeito estava escondido atrás de outro: enquanto o config tinha JSON
inválido (ver test_agent_config_loader), o agente nem chegava a usar a URL.
Corrigido o primeiro, este apareceria em seguida.
"""

import httpx
import pytest

from agent import run_agent


def test_client_do_agente_segue_redirect() -> None:
    """O 308 do portal tem de ser seguido, não tratado como falha."""
    saltos = []

    def responder(request: httpx.Request) -> httpx.Response:
        saltos.append(str(request.url))
        if request.url.scheme == "http":
            return httpx.Response(
                308,
                headers={"Location": str(request.url.copy_with(scheme="https"))},
            )
        return httpx.Response(200, json={"source_folder": "F:/certs"})

    client = run_agent._novo_http_client()
    client._transport = httpx.MockTransport(responder)
    # `mounts` tem precedência sobre `_transport`; sem limpar, o MockTransport
    # seria ignorado para http:// e o teste sairia pela rede de verdade.
    client._mounts = {}

    with client:
        r = client.get("http://portal.exemplo/api/settings")

    assert r.status_code == 200, "o redirect não foi seguido"
    assert r.json()["source_folder"] == "F:/certs"
    assert len(saltos) == 2, f"esperado 1 salto, houve {len(saltos) - 1}"
    assert saltos[1].startswith("https://")


def test_sem_follow_redirects_o_308_quebraria() -> None:
    """
    Contraprova: fixa o comportamento que causou o incidente.

    Sem seguir o redirect, o 308 chega a `raise_for_status` — que no httpx
    levanta para 3xx não seguido, e não só para 4xx/5xx.
    """
    def responder(request: httpx.Request) -> httpx.Response:
        return httpx.Response(308, headers={"Location": "https://portal.exemplo/api/settings"})

    with httpx.Client(transport=httpx.MockTransport(responder)) as client:
        r = client.get("http://portal.exemplo/api/settings")
        assert r.status_code == 308
        with pytest.raises(httpx.HTTPStatusError):
            r.raise_for_status()
