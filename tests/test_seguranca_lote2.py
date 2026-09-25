"""
Lote 2 das correções do SECURITY_AUDIT.md — identidade da MÁQUINA.

O ponto cego era um só: a credencial de máquina era autenticada, mas o
`machine_id` que decidia fila, custódia e cofre vinha do chamador. Cada teste
aqui foi escrito antes da correção e falhava em `6b8c286` (fim do lote 1).

  #3   /api/agent/next só entrega a fila da máquina que provou ser
  #21  /claim confere a máquina-alvo do token (por flag, credencial de máquina)
  #4   /upload-pfx e /api/ingest: machine_id da credencial; metadados do PFX
  #30  /instalabilidade e /vault-optin restritos à estação vinculada
  #22  desativar/excluir usuário queima os tokens de instalação pendentes
  #62  `enqueue_install_command` (caminho morto que enfileirava token) removido
  flag ACEITAR_API_KEY_COMPARTILHADA: a chave compartilhada nunca resgata token
"""

from __future__ import annotations

from typing import Any, Dict

import pytest
from fastapi.testclient import TestClient

import app.cert_installer as ci
import app.command_queue as cq
import app.main as m
from app import auth, config, machine_credentials
from tests.test_seguranca_lote1 import _Fake, _usuario

SEGREDO_A = "segredo-da-maquina-a-0123456789"
SEGREDO_B = "segredo-da-maquina-b-0123456789"
MAQ_A, MAQ_B = "maq-a", "maq-b"
ADMIN = ("admin@x.com", "admin")


def _h(email: str, papel: str) -> dict:
    return {"Authorization": "Bearer " + auth.create_access_token({"sub": email, "role": papel})}


def _credencial(machine_id: str, segredo: str, n: int) -> Dict[str, Any]:
    return {"id": f"mc-{n}", "machine_id": machine_id,
            "segredo_hash": machine_credentials._hash(segredo),
            "revogado_em": None, "criado_em": "2026-09-01T00:00:00+00:00"}


@pytest.fixture
def banco(monkeypatch: pytest.MonkeyPatch, tmp_path) -> _Fake:
    fake = _Fake({
        "users": [_usuario("u-adm", "admin@x.com", "admin"), _usuario("u-ana", "ana@x.com", "user")],
        "user_activity": [],
        machine_credentials.TABELA: [_credencial(MAQ_A, SEGREDO_A, 1), _credencial(MAQ_B, SEGREDO_B, 2)],
        "install_token": [],
        "cert_snapshots": [],
        "cert_history": [],
        "cert_vault_bloqueio": [],
        "cert_pfx_store": [],
        "carteira": [],
    })
    monkeypatch.setattr("app.settings_state._banco", lambda: fake)
    monkeypatch.setattr(ci, "_banco", lambda: fake)
    # Fila em arquivo temporário: o pop atômico é RPC do Postgres, fora do fake.
    monkeypatch.setattr(cq, "QUEUE_FILE", tmp_path / "fila.json")
    monkeypatch.setattr(cq, "_banco", lambda: None)
    monkeypatch.setattr(m, "trigger_all_alerts", lambda: None)
    monkeypatch.setattr(ci, "ttl_do_token", lambda: 5)
    monkeypatch.setattr(config, "ACEITAR_API_KEY_COMPARTILHADA", True, raising=False)
    monkeypatch.setattr(config, "CLAIM_EXIGE_CREDENCIAL_DE_MAQUINA", False, raising=False)
    return fake


# ──────────────────────────────────────────────────────────────────────────
# #3 — fila da própria máquina
# ──────────────────────────────────────────────────────────────────────────

def _next(client: TestClient, maquina: str, chave: str):
    return client.get(f"/api/agent/next?machine_id={maquina}", headers={"X-API-Key": chave})


def test_maquina_nao_puxa_a_fila_de_outra(client_com_chave: TestClient, banco: _Fake) -> None:
    cq.enqueue(MAQ_B, "instalar_certificados", payload="tok-secreto")
    r = _next(client_com_chave, MAQ_B, SEGREDO_A)
    assert r.status_code == 403, r.text
    assert "tok-secreto" not in r.text
    assert any(c["machine_id"] == MAQ_B for c in cq.list_pending()), "o comando tem de continuar na fila do dono"


def test_maquina_puxa_a_propria_fila(client_com_chave: TestClient, banco: _Fake) -> None:
    cq.enqueue(MAQ_A, "rescan")
    r = _next(client_com_chave, MAQ_A, SEGREDO_A)
    assert r.status_code == 200, r.text
    assert r.json()["command"] == "rescan"


def test_machine_id_compara_sem_caixa(client_com_chave: TestClient, banco: _Fake) -> None:
    """A credencial guarda em minúsculas; o agente declara como configurou."""
    cq.enqueue("MAQ-A", "ping")
    assert _next(client_com_chave, "MAQ-A", SEGREDO_A).status_code == 200


def test_curinga_continua_chegando_a_cada_maquina(client_com_chave: TestClient, banco: _Fake) -> None:
    cq.enqueue("*", "rescan")
    assert _next(client_com_chave, MAQ_A, SEGREDO_A).json()["command"] == "rescan"


def test_chave_compartilhada_nao_puxa_fila_nenhuma(client_com_chave: TestClient, api_key: str, banco: _Fake) -> None:
    """Mesmo com a janela de compatibilidade ligada: sem identidade, sem fila."""
    cq.enqueue(MAQ_A, "rescan")
    r = _next(client_com_chave, MAQ_A, api_key)
    assert r.status_code == 403, r.text
    assert cq.list_pending(), "o comando não pode ter sido consumido"


def test_admin_continua_lendo_qualquer_fila(client_com_chave: TestClient, banco: _Fake) -> None:
    cq.enqueue(MAQ_B, "ping")
    r = client_com_chave.get(f"/api/agent/next?machine_id={MAQ_B}", headers=_h(*ADMIN))
    assert r.status_code == 200 and r.json()["command"] == "ping"


def test_so_admin_enfileira_curinga(client_com_chave: TestClient, banco: _Fake) -> None:
    r = client_com_chave.post("/api/agent/commands", json={"machine_id": "*", "command": "rescan"},
                              headers={"X-API-Key": SEGREDO_A})
    assert r.status_code == 403
    assert not cq.list_pending()


# ──────────────────────────────────────────────────────────────────────────
# Janela: ACEITAR_API_KEY_COMPARTILHADA
# ──────────────────────────────────────────────────────────────────────────

def _ingest(client: TestClient, maquina: str, chave: str):
    return client.post("/api/ingest", headers={"X-API-Key": chave},
                       json={"machine_id": maquina, "source_folder": "C:/c", "expired_folder": "C:/v", "items": []})


def test_chave_compartilhada_recusada_com_a_flag_desligada(
    client_com_chave: TestClient, api_key: str, banco: _Fake, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(config, "ACEITAR_API_KEY_COMPARTILHADA", False, raising=False)
    r = _ingest(client_com_chave, MAQ_A, api_key)
    assert r.status_code == 401, r.text
    # Sem o marcador de credencial inválida: o agente não deve descartar nada.
    assert machine_credentials.CABECALHO_CREDENCIAL_INVALIDA not in r.headers


def test_chave_compartilhada_aceita_com_a_flag_ligada(
    client_com_chave: TestClient, api_key: str, banco: _Fake, caplog: pytest.LogCaptureFixture
) -> None:
    r = _ingest(client_com_chave, MAQ_A, api_key)
    assert r.status_code == 200, r.text
    assert "compartilhada" in caplog.text.lower()


def test_credencial_de_maquina_continua_valendo_com_a_flag_desligada(
    client_com_chave: TestClient, banco: _Fake, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(config, "ACEITAR_API_KEY_COMPARTILHADA", False, raising=False)
    assert _ingest(client_com_chave, MAQ_A, SEGREDO_A).status_code == 200


# ──────────────────────────────────────────────────────────────────────────
# #4 — machine_id da credencial em /api/ingest e /upload-pfx
# ──────────────────────────────────────────────────────────────────────────

def test_ingest_nao_grava_inventario_de_outra_maquina(client_com_chave: TestClient, banco: _Fake) -> None:
    r = _ingest(client_com_chave, MAQ_B, SEGREDO_A)
    assert r.status_code == 403, r.text
    assert not any(s.get("machine_id") == MAQ_B for s in banco.tabelas["cert_snapshots"])


def test_ingest_da_propria_maquina_grava(client_com_chave: TestClient, banco: _Fake) -> None:
    assert _ingest(client_com_chave, MAQ_A, SEGREDO_A).status_code == 200
    assert any(s.get("machine_id") == MAQ_A for s in banco.tabelas["cert_snapshots"])


def test_ingest_sem_machine_id_declarado_usa_o_da_credencial(client_com_chave: TestClient, banco: _Fake) -> None:
    r = client_com_chave.post("/api/ingest", headers={"X-API-Key": SEGREDO_A},
                              json={"machine_id": "", "source_folder": "C:/c", "expired_folder": "C:/v", "items": []})
    assert r.status_code == 200, r.text
    assert any(s.get("machine_id") == MAQ_A for s in banco.tabelas["cert_snapshots"])


DOC_DO_PFX = "12345678000195"
SENHA_PFX = "abc123"


@pytest.fixture(scope="module")
def pfx_real() -> Dict[str, Any]:
    """Um PFX de verdade, autoassinado, com CN no padrão ICP-Brasil NOME:CNPJ."""
    from tests.pfx_de_teste import gerar_pfx

    return gerar_pfx(cnpj=DOC_DO_PFX, senha=SENHA_PFX)


def _snapshot_com(banco: _Fake, maquina: str, fingerprint: str) -> None:
    banco.tabelas["cert_snapshots"].append({
        "machine_id": maquina, "scanned_at": "2026-09-25T10:00:00+00:00",
        "items": [{"fingerprint_sha256": fingerprint, "documento_numero": DOC_DO_PFX, "status": "ok"}],
    })


def _upload(client: TestClient, chave: str, pfx: Dict[str, Any], **extra: Any):
    corpo = {"fingerprint": pfx["fingerprint"], "machine_id": MAQ_A, "pfx_b64": pfx["b64"],
             "password": SENHA_PFX, "documento": "99999999000199", "documento_tipo": "cnpj",
             "subject": "CN=FORJADO", "nome_titular": "FORJADO"}
    corpo.update(extra)
    return client.post("/api/cert-installer/upload-pfx", json=corpo, headers={"X-API-Key": chave})


def test_upload_nao_grava_no_cofre_de_outra_maquina(client_com_chave: TestClient, banco: _Fake, pfx_real) -> None:
    _snapshot_com(banco, MAQ_B, pfx_real["fingerprint"])
    r = _upload(client_com_chave, SEGREDO_A, pfx_real, machine_id=MAQ_B)
    assert r.status_code == 403, r.text
    assert banco.tabelas["cert_pfx_store"] == []


def test_upload_grava_os_metadados_lidos_do_proprio_pfx(client_com_chave: TestClient, banco: _Fake, pfx_real) -> None:
    """`documento`, `subject` e `not_after` declarados pelo agente são ignorados:
    o que vale é o que está dentro do PFX — é isso que `assegurar_carteira` compara."""
    _snapshot_com(banco, MAQ_A, pfx_real["fingerprint"])
    r = _upload(client_com_chave, SEGREDO_A, pfx_real)
    assert r.status_code == 200, r.text
    linha = banco.tabelas["cert_pfx_store"][0]
    assert linha["documento"] == DOC_DO_PFX
    assert linha["documento_tipo"] == "cnpj"
    assert "FORJADO" not in (linha["subject"] or "") and "EMPRESA TESTE" in linha["subject"]
    assert linha["nome_titular"] == "EMPRESA TESTE LTDA"
    assert linha["not_after"][:10] == pfx_real["not_after"].isoformat()[:10]


def test_upload_recusa_fingerprint_que_nao_e_do_pfx(client_com_chave: TestClient, banco: _Fake, pfx_real) -> None:
    """Era o passo 2 do envenenamento: PFX do atacante sob o fingerprint de um
    certificado legítimo, passando na custódia e substituindo o material."""
    fp_legitimo = "a" * 64
    _snapshot_com(banco, MAQ_A, fp_legitimo)
    r = _upload(client_com_chave, SEGREDO_A, pfx_real, fingerprint=fp_legitimo)
    assert r.status_code == 422, r.text
    assert banco.tabelas["cert_pfx_store"] == []


def test_upload_recusa_pfx_ilegivel_com_a_senha(client_com_chave: TestClient, banco: _Fake, pfx_real) -> None:
    _snapshot_com(banco, MAQ_A, pfx_real["fingerprint"])
    r = _upload(client_com_chave, SEGREDO_A, pfx_real, password="errada")
    assert r.status_code == 422, r.text
    assert banco.tabelas["cert_pfx_store"] == []


# ──────────────────────────────────────────────────────────────────────────
# #21 — /claim vinculado à máquina-alvo
# ──────────────────────────────────────────────────────────────────────────

@pytest.fixture
def token_para_b(banco: _Fake, monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setattr(ci, "build_encrypted_bundle",
                        lambda certificate_ids, client_public_key_b64: {"certificates": [{"id": certificate_ids[0]}]})
    token_raw, _tid, _exp = ci.create_install_token(user_id="u-ana", user_email="ana@x.com",
                                                   target_machine=MAQ_B, certificate_ids=["cert-1"])
    return token_raw


def _claim(client: TestClient, token: str, **headers: str):
    return client.post("/api/cert-installer/claim", json={"token": token, "clientPublicKey": "x"}, headers=headers)


def _token_consumido(banco: _Fake) -> bool:
    return banco.tabelas["install_token"][0].get("consumed_at") is not None


def test_claim_com_x_machine_id_de_outra_maquina_e_recusado(client: TestClient, banco: _Fake, token_para_b: str) -> None:
    r = _claim(client, token_para_b, **{"X-Machine-Id": MAQ_A})
    assert r.status_code == 403, r.text
    assert not _token_consumido(banco), "o token tem de sobrar para a máquina certa"


def test_claim_com_x_machine_id_da_maquina_alvo_passa(client: TestClient, banco: _Fake, token_para_b: str) -> None:
    r = _claim(client, token_para_b, **{"X-Machine-Id": MAQ_B.upper()})
    assert r.status_code == 200, r.text
    assert _token_consumido(banco)


def test_claim_sem_identificacao_ainda_passa_na_janela_mas_avisa(
    client: TestClient, banco: _Fake, token_para_b: str, caplog: pytest.LogCaptureFixture
) -> None:
    """O agente do INVENT ainda não manda identificação: bloquear hoje pararia
    toda instalação. A janela é explícita, e cada resgate sem máquina avisa."""
    assert _claim(client, token_para_b).status_code == 200
    assert "sem identifica" in caplog.text.lower()


def test_claim_exige_credencial_de_maquina_quando_a_flag_manda(
    client_com_chave: TestClient, api_key: str, banco: _Fake, token_para_b: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(config, "CLAIM_EXIGE_CREDENCIAL_DE_MAQUINA", True, raising=False)
    assert _claim(client_com_chave, token_para_b).status_code == 403                                  # nada
    assert _claim(client_com_chave, token_para_b, **{"X-API-Key": api_key}).status_code == 403        # compartilhada
    assert _claim(client_com_chave, token_para_b, **{"X-API-Key": SEGREDO_A}).status_code == 403      # outra máquina
    assert not _token_consumido(banco)
    assert _claim(client_com_chave, token_para_b, **{"X-API-Key": SEGREDO_B}).status_code == 200      # a máquina-alvo
    assert _token_consumido(banco)


def test_redeem_nunca_aceita_a_chave_compartilhada(
    client_com_chave: TestClient, api_key: str, banco: _Fake, token_para_b: str
) -> None:
    r = client_com_chave.post("/api/cert-installer/redeem", json={"token": token_para_b, "clientPublicKey": "x"},
                              headers={"X-API-Key": api_key})
    assert r.status_code == 403, r.text
    assert not _token_consumido(banco)


def test_redeem_confere_a_maquina_alvo(client_com_chave: TestClient, banco: _Fake, token_para_b: str) -> None:
    assert client_com_chave.post("/api/cert-installer/redeem", json={"token": token_para_b, "clientPublicKey": "x"},
                                 headers={"X-API-Key": SEGREDO_A}).status_code == 403
    assert not _token_consumido(banco)
    assert client_com_chave.post("/api/cert-installer/redeem", json={"token": token_para_b, "clientPublicKey": "x"},
                                 headers={"X-API-Key": SEGREDO_B}).status_code == 200


# ──────────────────────────────────────────────────────────────────────────
# #30 — instalabilidade e vault-optin restritos à estação
# ──────────────────────────────────────────────────────────────────────────

FP_MEU, FP_ALHEIO = "1" * 64, "2" * 64
DOC_MEU, DOC_ALHEIO = "11111111000191", "22222222000192"


@pytest.fixture
def inventario(banco: _Fake, monkeypatch: pytest.MonkeyPatch) -> _Fake:
    banco.tabelas["cert_snapshots"].append({
        "machine_id": MAQ_A, "scanned_at": "2026-09-25T10:00:00+00:00",
        "items": [{"fingerprint_sha256": FP_MEU, "documento_numero": DOC_MEU, "status": "ok"},
                  {"fingerprint_sha256": FP_ALHEIO, "documento_numero": DOC_ALHEIO, "status": "ok"}],
    })
    banco.tabelas["cert_pfx_store"] += [
        {"id": "id-meu", "fingerprint": FP_MEU, "machine_id": MAQ_A, "documento": DOC_MEU, "uploaded_at": "2026-09-25"},
        {"id": "id-alheio", "fingerprint": FP_ALHEIO, "machine_id": MAQ_A, "documento": DOC_ALHEIO, "uploaded_at": "2026-09-25"},
    ]
    banco.tabelas["carteira"].append({"user_id": "u-ana", "documento": DOC_MEU})
    monkeypatch.setattr(m, "_dispositivos_da_pessoa", lambda email: [{"machine_id": MAQ_A, "nome": "PC-ANA"}])
    return banco


def test_instalabilidade_omite_o_que_esta_fora_da_carteira(client: TestClient, inventario: _Fake) -> None:
    r = client.get(f"/api/cert-installer/instalabilidade?machine_id={MAQ_A}", headers=_h("ana@x.com", "user"))
    assert r.status_code == 200, r.text
    itens = r.json()["itens"]
    assert FP_MEU in itens
    assert FP_ALHEIO not in itens, "fingerprint e id do cofre de cliente fora da carteira vazavam aqui"


def test_instalabilidade_de_estacao_nao_vinculada_e_recusada(client: TestClient, inventario: _Fake) -> None:
    r = client.get(f"/api/cert-installer/instalabilidade?machine_id={MAQ_B}", headers=_h("ana@x.com", "user"))
    assert r.status_code == 403, r.text


def test_admin_continua_vendo_tudo_em_qualquer_estacao(client: TestClient, inventario: _Fake) -> None:
    r = client.get(f"/api/cert-installer/instalabilidade?machine_id={MAQ_B}", headers=_h(*ADMIN))
    assert r.status_code == 200
    r = client.get(f"/api/cert-installer/instalabilidade?machine_id={MAQ_A}", headers=_h(*ADMIN))
    assert set(r.json()["itens"]) == {FP_MEU, FP_ALHEIO}


def test_sem_ponte_com_o_inventario_a_estacao_nao_e_conferida_mas_a_carteira_sim(
    client: TestClient, inventario: _Fake, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Degradar, não quebrar: sem o INVENT o vínculo não é verificável, e o
    Início continua funcionando — o que sai da resposta continua saindo."""
    monkeypatch.setattr(m, "_dispositivos_da_pessoa", lambda email: None)
    r = client.get(f"/api/cert-installer/instalabilidade?machine_id={MAQ_B}", headers=_h("ana@x.com", "user"))
    assert r.status_code == 200
    assert FP_ALHEIO not in r.json()["itens"]
    assert "vínculo" in caplog.text.lower() or "vinculo" in caplog.text.lower()


def test_vault_optin_so_responde_a_propria_maquina(client_com_chave: TestClient, inventario: _Fake) -> None:
    r = client_com_chave.get(f"/api/cert-installer/vault-optin?machine_id={MAQ_A}", headers={"X-API-Key": SEGREDO_B})
    assert r.status_code == 403, r.text
    r = client_com_chave.get(f"/api/cert-installer/vault-optin?machine_id={MAQ_A}", headers={"X-API-Key": SEGREDO_A})
    assert r.status_code == 200 and set(r.json()["fingerprints"]) == {FP_MEU, FP_ALHEIO}


# ──────────────────────────────────────────────────────────────────────────
# #22 — desativar/excluir queima os tokens pendentes
# ──────────────────────────────────────────────────────────────────────────

def test_desativar_usuario_queima_os_tokens_pendentes(client: TestClient, banco: _Fake, token_para_b: str) -> None:
    assert client.post("/api/users/u-ana/deactivate", headers=_h(*ADMIN)).status_code == 200
    assert _token_consumido(banco)
    r = _claim(client, token_para_b, **{"X-Machine-Id": MAQ_B})
    assert r.status_code == 403, "token de conta desativada continuava trocável por chave privada"


def test_excluir_usuario_queima_os_tokens_pendentes(client: TestClient, banco: _Fake, token_para_b: str) -> None:
    assert client.delete("/api/users/u-ana", headers=_h(*ADMIN)).status_code == 200
    assert _token_consumido(banco)


def test_editar_para_inativo_queima_os_tokens_pendentes(client: TestClient, banco: _Fake, token_para_b: str) -> None:
    r = client.put("/api/users/u-ana", headers=_h(*ADMIN),
                   json={"email": "ana@x.com", "full_name": "Ana", "role": "user", "ativo": False})
    assert r.status_code == 200, r.text
    assert _token_consumido(banco)


# ──────────────────────────────────────────────────────────────────────────
# #62 — caminho morto removido
# ──────────────────────────────────────────────────────────────────────────

def test_nao_existe_mais_enfileiramento_de_token_na_fila_local() -> None:
    assert not hasattr(ci, "enqueue_install_command")
