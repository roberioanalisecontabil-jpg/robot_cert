"""Postman na wiki da API (25/11/2026): as variáveis {{base}} e
{{chave_certguard}} do Postman passam pelo Jinja; sem {% raw %} viram vazio."""
from tests.test_seguranca_lote4 import ADMIN, _h, banco  # noqa: F401


def test_postman_aparece_inteiro_e_na_busca(client, banco) -> None:
    p = client.get("/wiki-certguard?pagina=api-integracoes", headers=_h(*ADMIN))
    assert p.status_code == 200 and 'id="postman"' in p.text
    assert "{{base}}/api/certificados" in p.text and "{{chave_certguard}}" in p.text
    r = client.get("/wiki-certguard?q=postman", headers=_h(*ADMIN))
    assert "pagina=api-integracoes#postman" in r.text


def test_postman_tem_exemplos_com_os_filtros_novos(client, banco) -> None:
    p = client.get("/wiki-certguard?pagina=api-integracoes", headers=_h(*ADMIN)).text
    assert 'id="postman-filtros"' in p
    assert "{{base}}/api/certificados?documento_tipo=cnpj&amp;vence_em_dias=60" in p
    for par in ("vence_de", "vence_ate", "documento", "campos"):
        assert f"<code>{par}</code>" in p, par
