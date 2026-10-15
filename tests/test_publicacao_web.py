"""
Publicação na internet (14/10/2026, docs/publicacao-na-web.md): a 443 do IP
público chega ao Caddy, que atende três sites. Só o de certificados vai para
fora, e só pela Cloudflare; os limites por endereço do portal dependem de o
Caddy entregar o IP verdadeiro.
"""

from __future__ import annotations

import re
from pathlib import Path

CADDY = (Path(__file__).resolve().parent.parent / "deploy" / "Caddyfile").read_text(encoding="utf-8")


def _site(nome: str) -> str:
    m = re.search(r"^" + re.escape(nome) + r" \{\n(.*?)^\}", CADDY, re.S | re.M)
    assert m, nome
    return m.group(1)


def test_so_o_portal_de_certificados_aceita_a_cloudflare() -> None:
    # 443 para a rede interna, 2053 para a Cloudflare (Origin Rule, 15/10/2026).
    assert "import so_cloudflare" in _site("certificado.analisegroup.cnt.br, certificado.analisegroup.cnt.br:2053")
    for interno in ("hardlyze.analisegroup.cnt.br", "eficacia.analisegroup.cnt.br"):
        corpo = _site(interno)
        assert "import so_rede_interna" in corpo and "so_cloudflare" not in corpo, interno


def test_o_portal_recebe_o_ip_verdadeiro_e_um_so() -> None:
    assert "client_ip_headers CF-Connecting-IP" in CADDY
    assert "header_up X-Forwarded-For {client_ip}" in CADDY


def test_cloudflare_e_reconhecida_pela_conexao_nos_dois_lugares() -> None:
    """A lista de trusted_proxies e a do filtro de entrada têm de ser a mesma:
    um IP da Cloudflare que só estivesse numa delas entraria sem ter o IP real
    lido, ou teria o IP real lido e seria recusado."""
    confiaveis = re.search(r"trusted_proxies static (.+)", CADDY).group(1).split()
    filtro = re.search(r"@fora_da_cloudflare not remote_ip private_ranges (.+)", CADDY).group(1).split()
    assert confiaveis == filtro
    assert "173.245.48.0/20" in confiaveis and "2606:4700::/32" in confiaveis
