"""Filtro Ativos/Expirados do Histórico segue o selo (revisão de 21/11/2026, P3-3).

O selo da tela diz "Vencido" quando o status é expirado/vencido OU a data de
vencimento já passou; o filtro olhava só `status_ultimo`. Certificado com status
"ok" na última varredura e vencido desde então aparecia em "Ativos"."""

from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from tests.test_seguranca_lote4 import ADMIN, AGORA, DOC_A, DOC_B, GESTOR, _h
from tests.test_seguranca_lote4 import banco  # noqa: F401


@pytest.fixture
def historico(banco):
    banco.tabelas["cert_history"] = [
        {"arquivo_chave": "1" * 64, "nome_publico": "VENCEU_" + DOC_A, "nome": "VENCEU", "documento": DOC_A,
         "status_ultimo": "ok", "vencimento_certificado": (AGORA - timedelta(days=1)).isoformat(),
         "ultima_data_registrada": AGORA.isoformat(), "ausente_desde": None},
        {"arquivo_chave": "2" * 64, "nome_publico": "VALE_" + DOC_B, "nome": "VALE", "documento": DOC_B,
         "status_ultimo": "ok", "vencimento_certificado": (AGORA + timedelta(days=90)).isoformat(),
         "ultima_data_registrada": AGORA.isoformat(), "ausente_desde": None},
    ]
    return banco


def _nomes(client, quem, qs) -> set:
    r = client.get("/api/certificados/historico?" + qs, headers=_h(*quem))
    assert r.status_code == 200, r.text
    return {i["nome"] for i in r.json()["itens"]}


@pytest.mark.parametrize("qs", ["pagina=1&por_pagina=50", "todas_filtradas=true"])
def test_ativos_nao_lista_vencido_pela_data(client: TestClient, historico, qs) -> None:
    assert _nomes(client, ADMIN, qs + "&status=ok") == {"VALE"}
    assert _nomes(client, ADMIN, qs + "&status=expirado") == {"VENCEU"}


def test_mesma_regra_para_quem_tem_alcance(client: TestClient, historico) -> None:
    ativos = _nomes(client, GESTOR, "pagina=1&por_pagina=50&status=ok")
    vencidos = _nomes(client, GESTOR, "pagina=1&por_pagina=50&status=expirado")
    assert "VENCEU" not in ativos and not (ativos & vencidos)
