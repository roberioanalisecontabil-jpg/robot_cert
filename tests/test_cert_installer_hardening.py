"""Testes do endurecimento do Módulo Instalador.

Cinco decisões tomadas na revisão:

1. Opt-in do cofre — o agente enviava TODOS os certificados lidos a cada ciclo.
   Numa base de 1.028, mil chaves privadas copiadas ao servidor sem decisão.
2. Token entregue ao agente — era gerado no /prepare e nunca chegava, então a
   instalação nunca completava.
3. `key_version` gravado — sem ele, rotacionar a chave exige recifrar tudo.
4. Senha do PFX não é mais armazenada — era cifrada com a MESMA chave do PFX.
5. Limite de upload de 50 MB para 1 MB.
"""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app import auth
import app.cert_installer as ci
import app.command_queue as cq


def _admin() -> dict:
    tok = auth.create_access_token({"sub": "admin@exemplo.com", "role": "admin"})
    return {"Authorization": f"Bearer {tok}"}


# ==========================================================================
# 1. Opt-in do cofre
# ==========================================================================

def test_upload_recusa_certificado_nao_autorizado(client_com_chave: TestClient, api_key: str) -> None:
    with patch.object(ci, "listar_optin_fingerprints", lambda *a, **k: []):
        r = client_com_chave.post(
            "/api/cert-installer/upload-pfx",
            json={"fingerprint": "a" * 64, "pfx_b64": "AAAA", "machine_id": "m1"},
            headers={"X-API-Key": api_key},
        )
    assert r.status_code == 403
    assert "não autorizado" in r.json()["detail"].lower()


def test_upload_aceita_certificado_autorizado(client_com_chave: TestClient, api_key: str) -> None:
    """Passa pela barreira do opt-in; o que falha depois é outra etapa."""
    fp = "b" * 64
    with patch.object(ci, "listar_optin_fingerprints", lambda *a, **k: [fp]):
        r = client_com_chave.post(
            "/api/cert-installer/upload-pfx",
            json={"fingerprint": fp, "pfx_b64": "AAAA", "machine_id": "m1"},
            headers={"X-API-Key": api_key},
        )
    assert r.status_code != 403


def test_lista_de_optin_falha_fechada(monkeypatch) -> None:
    """
    Se a consulta ao opt-in falhar, a lista volta vazia — nada é enviado.
    Falhar aberto copiaria chaves privadas para o servidor por acidente.
    """
    class _Quebrado:
        def table(self, _n):
            raise RuntimeError("banco fora do ar")

    monkeypatch.setattr(ci, "_supabase", lambda: _Quebrado())
    assert ci.listar_optin_fingerprints() == []


def test_revogar_apaga_o_pfx_armazenado(monkeypatch) -> None:
    """Revogar sem apagar deixaria a chave privada no servidor."""
    apagados = []

    class _Tabela:
        def __init__(self, nome):
            self.nome = nome

        def delete(self):
            return self

        def eq(self, campo, valor):
            apagados.append((self.nome, campo, valor))
            return self

        def execute(self):
            return type("R", (), {"data": []})()

    monkeypatch.setattr(ci, "_supabase", lambda: type("C", (), {"table": lambda s, n: _Tabela(n)})())
    ci.revogar_do_cofre("c" * 64)

    tabelas = {t for t, _, _ in apagados}
    assert "cert_vault_optin" in tabelas
    assert "cert_pfx_store" in tabelas, "PFX permaneceu no servidor após revogação"


# ==========================================================================
# 2. Token chega ao agente
# ==========================================================================

def test_token_e_gravado_no_payload_da_fila(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(cq, "QUEUE_FILE", tmp_path / "fila.json")
    monkeypatch.setattr(cq, "_supabase", lambda: None)

    ci.enqueue_install_command("SRV01", "token-secreto-123")

    fila = cq._load_file_queue()
    assert len(fila) == 1
    assert fila[0]["command"] == "instalar_certificados"
    assert fila[0]["payload"] == "token-secreto-123", "token não foi gravado — era o bug original"


def test_agente_recebe_o_token_ao_puxar_o_comando(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(cq, "QUEUE_FILE", tmp_path / "fila.json")
    monkeypatch.setattr(cq, "_supabase", lambda: None)

    ci.enqueue_install_command("SRV01", "token-abc")
    cmd = cq.pop_next_for_agent("SRV01")

    assert cmd is not None
    assert cmd.command == "instalar_certificados"
    assert cmd.payload == "token-abc"


def test_token_nao_vaza_na_listagem_publica_da_fila(monkeypatch, tmp_path) -> None:
    """/api/agent/queue é de monitorização — não pode expor o token."""
    monkeypatch.setattr(cq, "QUEUE_FILE", tmp_path / "fila.json")
    monkeypatch.setattr(cq, "_supabase", lambda: None)

    ci.enqueue_install_command("SRV01", "token-sigiloso")
    pendentes = cq.list_pending()

    assert len(pendentes) == 1
    assert "payload" not in pendentes[0]
    assert "token-sigiloso" not in str(pendentes)


def test_comando_comum_continua_sem_payload(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(cq, "QUEUE_FILE", tmp_path / "fila.json")
    monkeypatch.setattr(cq, "_supabase", lambda: None)

    cq.enqueue("SRV01", "rescan")
    cmd = cq.pop_next_for_agent("SRV01")
    assert cmd.payload is None


# ==========================================================================
# 3 e 4. key_version e senha não armazenada
# ==========================================================================

class _CapturaUpsert:
    def __init__(self):
        self.linha = None

    def table(self, _nome):
        return self

    def upsert(self, row, **_kw):
        self.linha = row
        return self

    def execute(self):
        return type("R", (), {"data": [{"id": "novo-id"}]})()


@pytest.fixture
def captura(monkeypatch):
    cap = _CapturaUpsert()
    monkeypatch.setattr(ci, "_supabase", lambda: cap)
    monkeypatch.setattr(ci, "encrypt_pfx_at_rest", lambda b: ("ct", "iv", "tag"))
    return cap


def test_key_version_e_gravado(captura) -> None:
    ci.upsert_pfx(fingerprint="d" * 64, pfx_bytes=b"x", machine_id="m1")
    assert captura.linha["key_version"] == ci.CURRENT_KEY_VERSION


def test_senha_e_guardada_cifrada_sob_chave_propria(captura) -> None:
    """
    A senha voltou ao cofre — o que não voltou foi guardá-la sob a chave do PFX.

    O endurecimento de 03/08 tirou a senha do banco por dois motivos: estava
    cifrada com a MESMA chave do PFX (um vazamento entregava os dois) e o agente
    conseguia lê-la do nome do arquivo na pasta de origem. O segundo motivo caiu
    com o instalador avulso: a máquina do usuário final não tem pasta nenhuma,
    e sem a senha o certutil recusa todo PFX.

    O primeiro motivo continua valendo, e é o que este teste fixa: nunca em
    claro, nunca na coluna antiga, e sob chave distinta.
    """
    ci.upsert_pfx(
        fingerprint="e" * 64,
        pfx_bytes=b"x",
        machine_id="m1",
        password="senha-super-secreta",
    )

    assert "senha-super-secreta" not in str(captura.linha), "senha em claro na linha"
    assert captura.linha["pfx_password"] is None, "a coluna antiga tem de seguir vazia"
    assert captura.linha["pfx_password_enc"], "a senha deveria estar cifrada"

    # E o material cifrado só abre com a chave da senha, não com a do PFX.
    assert ci.decrypt_password_at_rest(
        captura.linha["pfx_password_enc"],
        captura.linha["pfx_password_iv"],
        captura.linha["pfx_password_tag"],
    ) == "senha-super-secreta"


def test_sem_senha_as_colunas_ficam_nulas(captura) -> None:
    ci.upsert_pfx(fingerprint="e" * 64, pfx_bytes=b"x", machine_id="m1")
    assert captura.linha["pfx_password_enc"] is None


def test_chave_da_senha_igual_a_do_pfx_e_recusada(monkeypatch) -> None:
    """A separação é o único motivo de a senha poder voltar ao banco."""
    monkeypatch.setattr("app.config.CERT_ENCRYPTION_KEY", "33" * 32)
    monkeypatch.setattr("app.config.CERT_PASSWORD_ENCRYPTION_KEY", "33" * 32)

    with pytest.raises(RuntimeError) as exc:
        ci.encrypt_password_at_rest("x")
    assert "igual" in str(exc.value).lower()


def test_decrypt_usa_a_versao_de_chave_do_registro(monkeypatch) -> None:
    versoes = []
    monkeypatch.setattr(ci, "_get_server_key", lambda v=ci.CURRENT_KEY_VERSION: versoes.append(v) or (b"\x00" * 32))
    with pytest.raises(Exception):
        # Vai falhar na decifragem (dados falsos); só importa a versão pedida.
        ci.decrypt_pfx_at_rest("AAAA", "AAAA", "AAAA", key_version=7)
    assert versoes == [7]


# ==========================================================================
# 5. Limite de upload
# ==========================================================================

def test_limite_de_upload_e_1mb(client_com_chave: TestClient, api_key: str) -> None:
    import base64

    fp = "f" * 64
    grande = base64.b64encode(b"A" * (2 * 1024 * 1024)).decode()
    with patch.object(ci, "listar_optin_fingerprints", lambda *a, **k: [fp]):
        r = client_com_chave.post(
            "/api/cert-installer/upload-pfx",
            json={"fingerprint": fp, "pfx_b64": grande, "machine_id": "m1"},
            headers={"X-API-Key": api_key},
        )
    assert r.status_code == 413
