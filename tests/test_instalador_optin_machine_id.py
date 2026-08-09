"""Invariantes do painel de opt-in do cofre (templates/instalador.html).

O painel gravava a autorização com `machine_id: cert.machine_id || "default"`.
Mas em `fonte=auto` o portal devolve o `machine_id` na RAIZ do payload de
/api/certificados, não em cada item — então `cert.machine_id` era sempre
undefined e toda autorização ia para o literal "default".

Do outro lado da ponte, o agente consulta a lista filtrando pelo machine_id
dele (`agent/installer_client.py`), e `listar_optin_fingerprints` aplica
`.eq("machine_id", ...)`. Em qualquer instalação cujo machine_id não fosse
literalmente "default", o admin clicava "Autorizar", o badge ficava verde, e o
agente nunca recebia o certificado. Nenhum erro em lugar nenhum.

É um defeito que volta fácil: `|| "default"` parece um fallback inofensivo, e o
sintoma é ausência de comportamento — nada quebra, só não acontece.
"""

import re
from pathlib import Path

import pytest

TEMPLATE_PATH = Path(__file__).resolve().parent.parent / "templates" / "instalador.html"


@pytest.fixture(scope="module")
def html() -> str:
    """Template sem comentários — estes explicam o bug e citam os termos buscados."""
    bruto = TEMPLATE_PATH.read_text(encoding="utf-8")
    sem_html = re.sub(r"<!--.*?-->", "", bruto, flags=re.DOTALL)
    # `(?<!:)` preserva "https://" — só comentário de linha é removido.
    return re.sub(r"(?<!:)//[^\n]*", "", sem_html)


def test_autorizacao_nao_fixa_machine_id_em_default(html: str) -> None:
    """O POST não pode cair no literal "default" como machine_id."""
    assert 'machine_id: cert.machine_id || "default"' not in html
    assert "machine_id: cert.machine_id || _optinMachineId" in html


def test_machine_id_vem_da_raiz_do_payload(html: str) -> None:
    """É `dCerts.machine_id`, não `item.machine_id`, que o portal preenche."""
    assert re.search(r"_optinMachineId\s*=\s*dCerts\.machine_id\s*\|\|\s*[\"']default[\"']", html)


def test_consulta_de_optin_filtra_pela_maquina(html: str) -> None:
    """
    Sem o filtro, a tela lista o opt-in de todas as máquinas e o badge
    "Autorizado" aparece para certificado que este agente não vai receber —
    exatamente o que mascarava o bug original.
    """
    assert re.search(
        r"/api/cert-installer/vault-optin\?machine_id=\$\{encodeURIComponent\(_optinMachineId\)\}",
        html,
    )


def test_inventario_e_lido_antes_do_optin(html: str) -> None:
    """
    A ordem importa: o machine_id sai do inventário e entra na consulta de
    autorizações. Um Promise.all entre os dois volta a perder o filtro.
    """
    pos_certs = html.find("/api/certificados?fonte=auto")
    pos_optin = html.find("/api/cert-installer/vault-optin?machine_id=")
    assert pos_certs != -1 and pos_optin != -1
    assert pos_certs < pos_optin, "o inventário precisa ser buscado antes do opt-in"
