"""Fluxo fim-a-fim do opt-in do cofre, através do contrato HTTP real.

Os testes de `test_instalador_optin_machine_id.py` olham o template: garantem
que a tela manda o machine_id certo. Estes olham a outra ponta — o servidor —
e fecham o circuito que o bug de 08/08 atravessou sem ser notado:

    admin autoriza (machine A)  →  agente da machine A consulta  →  vê
                                →  agente da machine B consulta  →  não vê

Nenhum teste existente cruzava essa fronteira. O opt-in tinha cobertura de
unidade dos dois lados isoladamente, e mesmo assim uma autorização gravada com
machine_id errado passava despercebida: cada lado, sozinho, estava correto.

O Supabase é substituído por um fake em memória que implementa só o subconjunto
de query builder que `cert_installer` usa. Não é mock de asserção — é um banco
de brinquedo, para que o teste exercite a lógica real de filtro em vez de
verificar que uma chamada aconteceu.
"""

from typing import Any, Dict, List, Optional
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app import auth
import app.cert_installer as ci


# ──────────────────────────────────────────────────────────────────────────
# Fake Supabase — subconjunto usado por cert_installer
# ──────────────────────────────────────────────────────────────────────────

class _Resultado:
    def __init__(self, data: List[Dict[str, Any]]) -> None:
        self.data = data


class _Query:
    """Query builder encadeável sobre uma lista de dicts."""

    def __init__(self, tabela: List[Dict[str, Any]], banco: "_FakeSupabase", nome: str) -> None:
        self._tabela = tabela
        self._banco = banco
        self._nome = nome
        self._filtros: List[tuple] = []
        self._operacao = "select"
        self._payload: Optional[Dict[str, Any]] = None
        self._on_conflict: Optional[str] = None

    def select(self, *_cols: str) -> "_Query":
        self._operacao = "select"
        return self

    def upsert(self, row: Dict[str, Any], on_conflict: Optional[str] = None) -> "_Query":
        self._operacao = "upsert"
        self._payload = row
        self._on_conflict = on_conflict
        return self

    def delete(self) -> "_Query":
        self._operacao = "delete"
        return self

    def eq(self, coluna: str, valor: Any) -> "_Query":
        self._filtros.append((coluna, valor))
        return self

    def _casa(self, row: Dict[str, Any]) -> bool:
        return all(row.get(c) == v for c, v in self._filtros)

    def execute(self) -> _Resultado:
        if self._operacao == "select":
            return _Resultado([dict(r) for r in self._tabela if self._casa(r)])

        if self._operacao == "upsert":
            assert self._payload is not None
            if self._on_conflict:
                chave = self._on_conflict
                for i, r in enumerate(self._tabela):
                    if r.get(chave) == self._payload.get(chave):
                        self._tabela[i] = dict(self._payload)
                        return _Resultado([dict(self._payload)])
            self._tabela.append(dict(self._payload))
            return _Resultado([dict(self._payload)])

        if self._operacao == "delete":
            removidos = [r for r in self._tabela if self._casa(r)]
            self._tabela[:] = [r for r in self._tabela if not self._casa(r)]
            return _Resultado(removidos)

        raise AssertionError(f"operacao nao suportada: {self._operacao}")


class _FakeSupabase:
    def __init__(self) -> None:
        self.tabelas: Dict[str, List[Dict[str, Any]]] = {}

    def table(self, nome: str) -> _Query:
        self.tabelas.setdefault(nome, [])
        return _Query(self.tabelas[nome], self, nome)


@pytest.fixture
def banco() -> _FakeSupabase:
    fake = _FakeSupabase()
    with patch.object(ci, "_supabase", lambda: fake):
        yield fake


def _headers_admin() -> dict:
    tok = auth.create_access_token({"sub": "admin@exemplo.com", "role": "admin"})
    return {"Authorization": f"Bearer {tok}"}


def _headers_agente() -> dict:
    tok = auth.create_access_token({"sub": "agente@exemplo.com", "role": "agent"})
    return {"Authorization": f"Bearer {tok}"}


FP = "a" * 64
MAQUINA_A = "PC-CONTABIL-01"
MAQUINA_B = "PC-FISCAL-02"


# ──────────────────────────────────────────────────────────────────────────
# O circuito que o bug atravessou
# ──────────────────────────────────────────────────────────────────────────

def test_agente_da_maquina_autorizada_recebe_o_fingerprint(
    client: TestClient, banco: _FakeSupabase
) -> None:
    """Admin autoriza para a máquina A; o agente da A consulta e encontra."""
    r = client.post(
        "/api/cert-installer/vault-optin",
        json={"fingerprint": FP, "machine_id": MAQUINA_A, "nome_titular": "ACME LTDA"},
        headers=_headers_admin(),
    )
    assert r.status_code == 200, r.text

    r = client.get(
        f"/api/cert-installer/vault-optin?machine_id={MAQUINA_A}",
        headers=_headers_agente(),
    )
    assert r.status_code == 200
    assert r.json()["fingerprints"] == [FP]


def test_agente_de_outra_maquina_nao_recebe_o_fingerprint(
    client: TestClient, banco: _FakeSupabase
) -> None:
    """
    O coração do bug de 08/08 invertido: gravar sob a máquina errada tornava o
    opt-in invisível para o agente. Aqui o isolamento é o comportamento
    desejado — a autorização vale para a máquina em que foi concedida.
    """
    client.post(
        "/api/cert-installer/vault-optin",
        json={"fingerprint": FP, "machine_id": MAQUINA_A},
        headers=_headers_admin(),
    )

    r = client.get(
        f"/api/cert-installer/vault-optin?machine_id={MAQUINA_B}",
        headers=_headers_agente(),
    )
    assert r.status_code == 200
    assert r.json()["fingerprints"] == []


def test_autorizar_com_machine_id_default_some_para_agente_nomeado(
    client: TestClient, banco: _FakeSupabase
) -> None:
    """
    Reprodução literal do bug: a tela gravava "default" enquanto o agente
    consultava com o machine_id real. O resultado era silencioso — 200 na
    autorização, lista vazia para o agente, nenhum PFX enviado, nenhum erro.
    """
    client.post(
        "/api/cert-installer/vault-optin",
        json={"fingerprint": FP, "machine_id": "default"},
        headers=_headers_admin(),
    )

    r = client.get(
        f"/api/cert-installer/vault-optin?machine_id={MAQUINA_A}",
        headers=_headers_agente(),
    )
    assert r.json()["fingerprints"] == [], (
        "autorizacao gravada sob 'default' nao pode aparecer para uma maquina nomeada"
    )


def test_consulta_sem_machine_id_devolve_todas_as_maquinas(
    client: TestClient, banco: _FakeSupabase
) -> None:
    """
    Sem o parâmetro não há filtro — é o que a tela fazia antes da correção, e
    por isso o badge "Autorizado" ficava verde mesmo com o opt-in gravado sob
    outra máquina, escondendo a divergência.
    """
    client.post(
        "/api/cert-installer/vault-optin",
        json={"fingerprint": FP, "machine_id": MAQUINA_A},
        headers=_headers_admin(),
    )
    client.post(
        "/api/cert-installer/vault-optin",
        json={"fingerprint": "b" * 64, "machine_id": MAQUINA_B},
        headers=_headers_admin(),
    )

    r = client.get("/api/cert-installer/vault-optin", headers=_headers_agente())
    assert sorted(r.json()["fingerprints"]) == sorted([FP, "b" * 64])


# ──────────────────────────────────────────────────────────────────────────
# Revogação
# ──────────────────────────────────────────────────────────────────────────

def test_revogar_apaga_autorizacao_e_material_armazenado(
    client: TestClient, banco: _FakeSupabase
) -> None:
    """Revogar sem apagar o PFX deixaria a chave privada no servidor."""
    client.post(
        "/api/cert-installer/vault-optin",
        json={"fingerprint": FP, "machine_id": MAQUINA_A},
        headers=_headers_admin(),
    )
    banco.tabelas.setdefault("cert_pfx_store", []).append(
        {"fingerprint": FP, "pfx_cifrado": "material"}
    )

    r = client.delete(
        f"/api/cert-installer/vault-optin/{FP}", headers=_headers_admin()
    )
    assert r.status_code == 200
    assert r.json()["pfx_removido"] is True

    assert banco.tabelas["cert_vault_optin"] == []
    assert banco.tabelas["cert_pfx_store"] == [], "o PFX tem de sair junto"


def test_usuario_comum_nao_autoriza_nem_revoga(
    client: TestClient, banco: _FakeSupabase
) -> None:
    """Autorizar copia chave privada para o servidor — é ação de admin."""
    tok = auth.create_access_token({"sub": "user@exemplo.com", "role": "user"})
    h = {"Authorization": f"Bearer {tok}"}

    r = client.post(
        "/api/cert-installer/vault-optin",
        json={"fingerprint": FP, "machine_id": MAQUINA_A},
        headers=h,
    )
    assert r.status_code == 403

    r = client.delete(f"/api/cert-installer/vault-optin/{FP}", headers=h)
    assert r.status_code == 403


# ──────────────────────────────────────────────────────────────────────────
# Barreira de servidor no upload
# ──────────────────────────────────────────────────────────────────────────

def test_upload_barra_fingerprint_nao_autorizado_em_maquina_nenhuma(
    client: TestClient, banco: _FakeSupabase
) -> None:
    r = client.post(
        "/api/cert-installer/upload-pfx",
        json={"fingerprint": FP, "pfx_b64": "AAAA", "machine_id": MAQUINA_A},
        headers=_headers_agente(),
    )
    assert r.status_code == 403


def test_upload_barra_fingerprint_autorizado_em_OUTRA_maquina(
    client: TestClient, banco: _FakeSupabase
) -> None:
    """
    A barreira do upload confere a máquina, não só o fingerprint.

    Sem o filtro bastava o certificado estar autorizado em QUALQUER estação. O
    agente bem-comportado nunca tentaria — só envia o que a consulta filtrada
    dele devolveu —, mas a barreira existe justamente para o agente
    "desatualizado (ou adulterado)", e contra esse ela precisa olhar a máquina:
    declarando-se da B, ele gravaria o PFX de um certificado autorizado só na A
    e, como `upsert_pfx` usa `on_conflict="fingerprint"`, sobrescreveria o
    registro legítimo.
    """
    client.post(
        "/api/cert-installer/vault-optin",
        json={"fingerprint": FP, "machine_id": MAQUINA_A},
        headers=_headers_admin(),
    )

    with patch.object(ci, "upsert_pfx", lambda **kw: "id-fake"):
        r = client.post(
            "/api/cert-installer/upload-pfx",
            json={"fingerprint": FP, "pfx_b64": "AAAA", "machine_id": MAQUINA_B},
            headers=_headers_agente(),
        )

    assert r.status_code == 403


def test_upload_aceita_na_maquina_em_que_foi_autorizado(
    client: TestClient, banco: _FakeSupabase
) -> None:
    """Contraprova: o endurecimento não pode barrar o caminho legítimo."""
    client.post(
        "/api/cert-installer/vault-optin",
        json={"fingerprint": FP, "machine_id": MAQUINA_A},
        headers=_headers_admin(),
    )

    with patch.object(ci, "upsert_pfx", lambda **kw: "id-fake"):
        r = client.post(
            "/api/cert-installer/upload-pfx",
            json={"fingerprint": FP, "pfx_b64": "AAAA", "machine_id": MAQUINA_A},
            headers=_headers_agente(),
        )

    assert r.status_code != 403, r.text
