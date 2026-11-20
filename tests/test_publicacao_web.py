"""
Publicação na internet (docs/publicacao-na-web.md, situação de 20/11/2026): a
Cloudflare chega ao Caddy pela 8191 do IP público. Cada site do Caddyfile é ou
da internet (só pela Cloudflare, `so_cloudflare`) ou só da rede interna e VPN
(`so_rede_interna`), nunca os dois nem nenhum; os limites por endereço do
portal dependem de o Caddy entregar o IP verdadeiro.
"""

from __future__ import annotations

import re
from pathlib import Path

CADDY = (Path(__file__).resolve().parent.parent / "deploy" / "Caddyfile").read_text(encoding="utf-8")


NA_INTERNET = {
    "certificado.analisegroup.cnt.br, certificado.analisegroup.cnt.br:8191",
    "hardlyze.analisegroup.cnt.br, hardlyze.analisegroup.cnt.br:8191",
    "eficacia.analisegroup.cnt.br, eficacia.analisegroup.cnt.br:8191",
    "intranet.analisegroup.cnt.br:8191",
    "jornada.analisegroup.cnt.br, jornada.analisegroup.cnt.br:8191",
    "crm.analisegroup.cnt.br, crm.analisegroup.cnt.br:8191",
    "eventos.analisegroup.cnt.br, eventos.analisegroup.cnt.br:8191",
}
SO_REDE_INTERNA = {
    "diario.analisegroup.cnt.br, diario.analisegroup.cnt.br:8191",
    "zabbix.analisegroup.cnt.br, zabbix.analisegroup.cnt.br:8198",
    "http://:94",
}


def _sites() -> dict[str, str]:
    # Blocos de site no nível de cima; "(nome)" é snippet e "{" sozinho é o global.
    return {
        m.group(1): m.group(2)
        for m in re.finditer(r"^([^\s#(][^\n{]*?) \{\n(.*?)^\}", CADDY, re.S | re.M)
    }


def test_cada_site_e_da_internet_ou_da_rede_interna() -> None:
    sites = _sites()
    # Site novo sem estar numa das listas falha aqui: decida de que lado ele fica.
    assert set(sites) == NA_INTERNET | SO_REDE_INTERNA
    for nome, corpo in sites.items():
        fora = "import so_cloudflare" in corpo
        dentro = "import so_rede_interna" in corpo
        assert (fora, dentro) == ((True, False) if nome in NA_INTERNET else (False, True)), nome


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
