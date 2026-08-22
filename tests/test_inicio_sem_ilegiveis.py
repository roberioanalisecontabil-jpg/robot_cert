"""O Início deixa de listar certificado que o robô não consegue ler.

Pedido do cliente: *"não gostaria de ver os certificados com erro e falha na
página inicial, já que é uma informação mais técnica para o gestor ou admin
tratar"*. A leitura está certa e casa com a arquitetura — `/dashboard` já
apresenta esses arquivos somados sob "ilegíveis", e é tela restrita pela matriz.

Duas invariantes governam a implementação:

1. **A exclusão é OPT-IN.** O mesmo endpoint atende `scripts/diagnostico.py`,
   que existe justamente para achar arquivo ilegível. Mudar o padrão cegaria a
   ferramenta de diagnóstico — e o sintoma seria "o diagnóstico parou de achar
   problema", que é indistinguível de "não há problema".
2. **Excluir antes de contar e paginar.** Se a filtragem acontecesse depois, uma
   página de 100 traria 91 linhas e os cards não bateriam com a tabela.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

import pytest
from fastapi.testclient import TestClient

from app import auth
import app.main as m


def _admin() -> dict:
    return {"Authorization": f"Bearer {auth.create_access_token({'sub': 'admin@x.com', 'role': 'admin'})}"}


def _cert(nome: str, status: str, dias: int = 365) -> dict:
    venc = datetime.now(timezone.utc) + timedelta(days=dias)
    return {
        "nome": nome,
        "display_name": nome,
        "status": status,
        "not_after": venc.isoformat(),
        "fingerprint_sha256": "fp-" + nome,
        "documento_numero": "12345678000199",
        "documento_formatado": "12.345.678/0001-99",
        "file_name": nome + ".pfx",
    }


@pytest.fixture
def acervo(monkeypatch: pytest.MonkeyPatch) -> List[Dict[str, Any]]:
    """6 legíveis e 4 ilegíveis, para as contagens serem verificáveis a olho."""
    itens = (
        [_cert(f"BOM {i}", "ok") for i in range(6)]
        + [_cert(f"ERRO {i}", "erro") for i in range(2)]
        + [_cert(f"FALHA {i}", "fora_do_padrao") for i in range(2)]
    )
    monkeypatch.setattr(
        m, "_list_certificados_payload", lambda *a, **k: {"itens": list(itens)}
    )
    return itens


# ══════════════════════════════════════════════════════════════════════════
# O comportamento novo
# ══════════════════════════════════════════════════════════════════════════

def test_com_o_parametro_os_ilegiveis_somem_da_lista(client: TestClient, acervo) -> None:
    r = client.get(
        "/api/certificados?pagina=1&por_pagina=50&ocultar_ilegiveis=true", headers=_admin()
    )
    assert r.status_code == 200, r.text
    nomes = [it["nome"] for it in r.json()["itens"]]
    assert len(nomes) == 6
    assert not any(n.startswith(("ERRO", "FALHA")) for n in nomes)


def test_a_contagem_dos_cards_acompanha(client: TestClient, acervo) -> None:
    """O card e a tabela precisam contar a mesma coisa.

    Excluir só da listagem deixaria "Total: 10" acima de uma tabela com 6
    linhas — e a divergência pareceria dado faltando, não filtro aplicado.
    """
    r = client.get(
        "/api/certificados?pagina=1&por_pagina=50&ocultar_ilegiveis=true", headers=_admin()
    )
    assert r.json()["resumo"]["total"] == 6


def test_a_paginacao_conta_so_o_que_sobra(client: TestClient, acervo) -> None:
    """Com 4 por página: 6 legíveis são 2 páginas, não 3."""
    r = client.get(
        "/api/certificados?pagina=1&por_pagina=4&ocultar_ilegiveis=true", headers=_admin()
    )
    pag = r.json()["paginacao"]
    assert pag["total_paginas"] == 2, pag
    assert len(r.json()["itens"]) == 4


def test_a_exportacao_leva_o_mesmo_que_a_tela(client: TestClient, acervo) -> None:
    """Planilha com o que a tela não mostra é uma divergência que só aparece
    depois, na mão de quem recebe o arquivo."""
    r = client.get(
        "/api/certificados?todas_filtradas=true&ocultar_ilegiveis=true", headers=_admin()
    )
    nomes = [it["nome"] for it in r.json()["itens"]]
    assert len(nomes) == 6
    assert not any(n.startswith(("ERRO", "FALHA")) for n in nomes)


# ══════════════════════════════════════════════════════════════════════════
# O que não pode quebrar
# ══════════════════════════════════════════════════════════════════════════

def test_sem_o_parametro_nada_muda(client: TestClient, acervo) -> None:
    """A invariante 1, no ponto em que ela protege o diagnóstico."""
    r = client.get("/api/certificados?pagina=1&por_pagina=50", headers=_admin())
    nomes = [it["nome"] for it in r.json()["itens"]]
    assert len(nomes) == 10
    assert sum(1 for n in nomes if n.startswith("ERRO")) == 2
    assert sum(1 for n in nomes if n.startswith("FALHA")) == 2
    assert r.json()["resumo"]["total"] == 10


def test_o_filtro_de_status_continua_valendo_junto(client: TestClient, acervo) -> None:
    """As duas exclusões compõem, e não se atropelam."""
    r = client.get(
        "/api/certificados?pagina=1&por_pagina=50&filtro_status=validos&ocultar_ilegiveis=true",
        headers=_admin(),
    )
    assert r.json()["resumo"]["total"] == 6


def test_pedir_erro_com_a_exclusao_ligada_devolve_vazio(client: TestClient, acervo) -> None:
    """Combinação sem sentido, mas precisa ser coerente em vez de surpreender.

    A tela do Início não oferece mais essa opção; se alguém montar a URL na
    mão, o resultado é uma lista vazia — e não os erros de volta.
    """
    r = client.get(
        "/api/certificados?pagina=1&por_pagina=50&filtro_status=erros&ocultar_ilegiveis=true",
        headers=_admin(),
    )
    assert r.json()["itens"] == []
    assert r.json()["resumo"]["total"] == 0


def test_a_funcao_que_decide_e_a_mesma_para_os_dois_status() -> None:
    """`erro` e `fora_do_padrao` são o mesmo caso: o robô não conseguiu ler."""
    assert m._e_ilegivel({"status": "erro"})
    assert m._e_ilegivel({"status": "fora_do_padrao"})
    assert not m._e_ilegivel({"status": "ok"})
    assert not m._e_ilegivel({"status": "expirado"})
    assert not m._e_ilegivel({})
