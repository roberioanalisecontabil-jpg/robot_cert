"""
Lote 8 das correções do SECURITY_AUDIT.md — criptografia do cofre.

  #19  a senha do PFX era cifrada sem `key_version`: rotacionar
       CERT_PASSWORD_ENCRYPTION_KEY tornava todas as senhas indecifráveis
  #42  rotação da chave do PFX: `CERT_ENCRYPTION_KEY_V1` inalcançável (a
       versão em vigor era a constante 1), versões antigas aceitas para
       sempre, nada recifrava, e a ajuda do botão prometia correção
  #55  AES-GCM sem dados associados: um ciphertext podia ser trocado de linha
       (outra máquina, outro fingerprint) sem a tag acusar
  #56  código de redefinição de senha em SHA-256 puro, sem sal

Cada teste foi escrito antes da correção e falhava em `c2da1a6` (fim do
lote 7). O que se prova aqui é decifra de verdade, com AES-GCM real e chaves
de teste — o incidente de 15/08/2026 mostrou que contar linhas não prova nada.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Any, Dict, List

import pytest
from fastapi.testclient import TestClient

import app.cert_installer as ci
import app.senha_reset as sr
from app import auth, config
from tests.test_seguranca_lote1 import _Fake

RAIZ = Path(__file__).resolve().parents[1]

CHAVE_PFX_V1 = "11" * 32          # a do conftest
CHAVE_SENHA_V1 = "22" * 32        # a do conftest
CHAVE_PFX_V2 = "aa" * 32
CHAVE_SENHA_V2 = "bb" * 32
FP_A = "a" * 64
FP_B = "b" * 64


@pytest.fixture
def cofre(monkeypatch: pytest.MonkeyPatch) -> _Fake:
    fake = _Fake({"cert_pfx_store": [], "cert_vault_bloqueio": []})
    monkeypatch.setattr(ci, "_banco", lambda: fake)
    monkeypatch.setattr(config, "CERT_ENCRYPTION_KEY_VERSION", 1, raising=False)
    monkeypatch.setattr(config, "CERT_PASSWORD_ENCRYPTION_KEY_VERSION", 1, raising=False)
    monkeypatch.setattr(config, "COFRE_EXIGE_AAD", False, raising=False)
    monkeypatch.delattr(config, "CERT_ENCRYPTION_KEY_V1", raising=False)
    monkeypatch.delattr(config, "CERT_PASSWORD_ENCRYPTION_KEY_V1", raising=False)
    return fake


def _linha_legada(fp: str, maquina: str = "ANALISESRV", senha: str = "s3nha") -> Dict[str, Any]:
    """Linha como o código ANTES do lote 8 gravava: sem AAD, senha sem versão,
    sem as colunas novas (o banco antigo nem as tem)."""
    ct, iv, tag = ci.encrypt_pfx_at_rest(b"pfx-" + fp[:4].encode())
    pct, piv, ptag = ci.encrypt_password_at_rest(senha)
    return {
        "id": "id-" + fp[:4],
        "fingerprint": fp,
        "machine_id": maquina,
        "key_version": 1,
        "encrypted_pfx": ct, "pfx_iv": iv, "pfx_auth_tag": tag,
        "pfx_password_enc": pct, "pfx_password_iv": piv, "pfx_password_tag": ptag,
        "pfx_password": None,
        "updated_at": "2026-09-01T00:00:00Z",
    }


def _rotacionar_para_v2(monkeypatch: pytest.MonkeyPatch) -> None:
    """O procedimento de rotação que o lote 8 define: chave nova em vigor,
    a antiga fica como _V1, e a versão em vigor sobe no ambiente."""
    monkeypatch.setattr(config, "CERT_ENCRYPTION_KEY", CHAVE_PFX_V2)
    monkeypatch.setattr(config, "CERT_ENCRYPTION_KEY_V1", CHAVE_PFX_V1, raising=False)
    monkeypatch.setattr(config, "CERT_ENCRYPTION_KEY_VERSION", 2, raising=False)
    monkeypatch.setattr(config, "CERT_PASSWORD_ENCRYPTION_KEY", CHAVE_SENHA_V2)
    monkeypatch.setattr(config, "CERT_PASSWORD_ENCRYPTION_KEY_V1", CHAVE_SENHA_V1, raising=False)
    monkeypatch.setattr(config, "CERT_PASSWORD_ENCRYPTION_KEY_VERSION", 2, raising=False)


def _admin() -> dict:
    return {"Authorization": f"Bearer {auth.create_access_token({'sub': 'admin@x.com', 'role': 'admin'})}"}


# ──────────────────────────────────────────────────────────────────────────
# #19 — a senha ganha versão de chave
# ──────────────────────────────────────────────────────────────────────────

def test_upsert_grava_versao_da_senha_e_versao_do_envelope(cofre: _Fake) -> None:
    ci.upsert_pfx(FP_A, b"pfx", "ANALISESRV", password="s3nha")
    linha = cofre.tabelas["cert_pfx_store"][0]
    assert linha["key_version"] == 1
    assert linha["password_key_version"] == 1
    assert linha["aad_version"] == ci.AAD_VERSAO_ATUAL


def test_senha_cifrada_na_v1_decifra_depois_da_rotacao_para_v2(cofre: _Fake, monkeypatch) -> None:
    """O 'Como testar' do #19: cifrar com v1, subir com v2 em vigor e v1 em
    `_V1`, decifrar → tem de funcionar. Antes do lote a senha era sempre
    decifrada com a chave corrente, e a rotação quebrava o cofre inteiro."""
    ci.upsert_pfx(FP_A, b"pfx", "ANALISESRV", password="s3nha")
    _rotacionar_para_v2(monkeypatch)
    linha = cofre.tabelas["cert_pfx_store"][0]
    assert ci.decifrar_senha_da_linha(linha) == "s3nha"
    assert ci.decifrar_pfx_da_linha(linha) == b"pfx"


def test_depois_da_rotacao_o_upsert_grava_na_versao_nova(cofre: _Fake, monkeypatch) -> None:
    _rotacionar_para_v2(monkeypatch)
    ci.upsert_pfx(FP_B, b"pfx-b", "ANALISESRV", password="outra")
    linha = cofre.tabelas["cert_pfx_store"][0]
    assert linha["key_version"] == 2 and linha["password_key_version"] == 2
    assert ci.decifrar_senha_da_linha(linha) == "outra"


def test_linha_antiga_sem_versao_da_senha_e_tratada_como_v1(cofre: _Fake, monkeypatch) -> None:
    """Banco anterior à migração: a coluna não existe (None). Vale 1, que era
    a única versão possível."""
    linha = _linha_legada(FP_A)
    _rotacionar_para_v2(monkeypatch)
    assert ci.decifrar_senha_da_linha(linha) == "s3nha"


def test_versao_em_vigor_vem_do_ambiente(monkeypatch) -> None:
    monkeypatch.setattr(config, "CERT_ENCRYPTION_KEY_VERSION", 3, raising=False)
    monkeypatch.setattr(config, "CERT_PASSWORD_ENCRYPTION_KEY_VERSION", 2, raising=False)
    assert ci.versao_corrente() == 3
    assert ci.versao_corrente_senha() == 2


# ──────────────────────────────────────────────────────────────────────────
# #55 — dados associados
# ──────────────────────────────────────────────────────────────────────────

def test_ciphertext_trocado_de_linha_nao_decifra(cofre: _Fake) -> None:
    """O 'Como testar' do #55: trocar o ciphertext entre duas linhas → falha."""
    ci.upsert_pfx(FP_A, b"pfx-a", "ANALISESRV", password="sa")
    ci.upsert_pfx(FP_B, b"pfx-b", "OUTRA", password="sb")
    a, b = cofre.tabelas["cert_pfx_store"]
    trocada = dict(a)
    for c in ("encrypted_pfx", "pfx_iv", "pfx_auth_tag", "pfx_password_enc", "pfx_password_iv", "pfx_password_tag"):
        trocada[c] = b[c]
    with pytest.raises(Exception) as e1:
        ci.decifrar_pfx_da_linha(trocada)
    assert type(e1.value).__name__ == "InvalidTag"
    with pytest.raises(Exception) as e2:
        ci.decifrar_senha_da_linha(trocada)
    assert type(e2.value).__name__ == "InvalidTag"
    # As linhas íntegras continuam decifrando.
    assert ci.decifrar_pfx_da_linha(a) == b"pfx-a" and ci.decifrar_pfx_da_linha(b) == b"pfx-b"


def test_mudar_a_maquina_da_linha_tambem_falha(cofre: _Fake) -> None:
    ci.upsert_pfx(FP_A, b"pfx-a", "ANALISESRV", password="sa")
    linha = dict(cofre.tabelas["cert_pfx_store"][0], machine_id="ATACANTE")
    with pytest.raises(Exception):
        ci.decifrar_pfx_da_linha(linha)


def test_linha_legada_sem_aad_ainda_decifra_com_aviso(cofre: _Fake, caplog) -> None:
    """Janela de compatibilidade: o cofre real tem ~470 linhas sem AAD. Elas
    continuam decifrando até serem recifradas — e o log diz que faltam."""
    linha = _linha_legada(FP_A)
    ci._avisou_envelope_legado = False
    with caplog.at_level(logging.WARNING):
        assert ci.decifrar_pfx_da_linha(linha) == b"pfx-aaaa"
        assert ci.decifrar_senha_da_linha(linha) == "s3nha"
    assert "recifrar" in caplog.text.lower()


def test_com_cofre_exige_aad_a_linha_legada_e_recusada(cofre: _Fake, monkeypatch) -> None:
    """Depois de recifrar tudo, o admin liga COFRE_EXIGE_AAD e a janela fecha:
    um ciphertext 'rebaixado' para o envelope antigo deixa de ser aceito."""
    linha = _linha_legada(FP_A)
    monkeypatch.setattr(config, "COFRE_EXIGE_AAD", True, raising=False)
    with pytest.raises(ci.EnvelopeLegado):
        ci.decifrar_pfx_da_linha(linha)


# ──────────────────────────────────────────────────────────────────────────
# #42 — recifrar o cofre
# ──────────────────────────────────────────────────────────────────────────

def test_recifrar_leva_tudo_para_a_versao_em_vigor_e_com_aad(cofre: _Fake, monkeypatch) -> None:
    """O 'Como testar' do #42: cofre com linhas v1, chave rotacionada para v2
    → depois de recifrar, count(key_version < 2) = 0. E o material continua
    decifrável, agora com AAD e senha versionada."""
    cofre.tabelas["cert_pfx_store"] = [_linha_legada(FP_A), _linha_legada(FP_B, maquina="OUTRA", senha="sb")]
    _rotacionar_para_v2(monkeypatch)

    r = ci.recifrar_cofre()
    assert r["candidatas"] == 2 and r["recifradas"] == 2 and r["falhas"] == [] and r["restantes"] == 0

    for linha in cofre.tabelas["cert_pfx_store"]:
        assert linha["key_version"] == 2
        assert linha["password_key_version"] == 2
        assert linha["aad_version"] == ci.AAD_VERSAO_ATUAL
    a, b = cofre.tabelas["cert_pfx_store"]
    assert ci.decifrar_pfx_da_linha(a) == b"pfx-aaaa" and ci.decifrar_senha_da_linha(a) == "s3nha"
    assert ci.decifrar_pfx_da_linha(b) == b"pfx-bbbb" and ci.decifrar_senha_da_linha(b) == "sb"
    assert sum(1 for l in cofre.tabelas["cert_pfx_store"] if l["key_version"] < 2) == 0

    # Com a chave antiga removida do ambiente, o cofre segue legível: é o
    # critério para o operador poder apagar CERT_ENCRYPTION_KEY_V1.
    monkeypatch.delattr(config, "CERT_ENCRYPTION_KEY_V1")
    monkeypatch.delattr(config, "CERT_PASSWORD_ENCRYPTION_KEY_V1")
    assert ci.decifrar_pfx_da_linha(a) == b"pfx-aaaa"
    assert ci.diagnostico_das_chaves()["versoes_sem_chave"] == []


def test_recifrar_e_idempotente(cofre: _Fake, monkeypatch) -> None:
    cofre.tabelas["cert_pfx_store"] = [_linha_legada(FP_A)]
    _rotacionar_para_v2(monkeypatch)
    assert ci.recifrar_cofre()["recifradas"] == 1
    r = ci.recifrar_cofre()
    assert r["candidatas"] == 0 and r["recifradas"] == 0


def test_recifrar_sem_rotacao_ainda_acrescenta_o_aad(cofre: _Fake) -> None:
    """Mesmo sem trocar chave, recifrar fecha o #55 nas linhas antigas."""
    cofre.tabelas["cert_pfx_store"] = [_linha_legada(FP_A)]
    assert ci.recifrar_cofre()["recifradas"] == 1
    linha = cofre.tabelas["cert_pfx_store"][0]
    assert linha["aad_version"] == ci.AAD_VERSAO_ATUAL and linha["key_version"] == 1
    assert ci.decifrar_pfx_da_linha(linha) == b"pfx-aaaa"


def test_recifrar_nao_toca_no_que_nao_consegue_decifrar(cofre: _Fake, monkeypatch) -> None:
    """A regra do lote: nunca apagar nem sobrescrever material que não se
    provou legível. A linha ilegível fica como está e é reportada."""
    boa = _linha_legada(FP_A)
    ruim = dict(_linha_legada(FP_B), pfx_auth_tag="AAAAAAAAAAAAAAAAAAAAAA==")
    cofre.tabelas["cert_pfx_store"] = [boa, ruim]
    _rotacionar_para_v2(monkeypatch)

    r = ci.recifrar_cofre()
    assert r["recifradas"] == 1
    assert len(r["falhas"]) == 1 and r["falhas"][0]["fingerprint"] == FP_B[:16]
    assert "CERT_ENCRYPTION_KEY" in r["falhas"][0]["motivo"]
    intocada = [l for l in cofre.tabelas["cert_pfx_store"] if l["fingerprint"] == FP_B][0]
    assert intocada["key_version"] == 1 and intocada["encrypted_pfx"] == ruim["encrypted_pfx"]
    assert r["restantes"] == 1


def test_recifrar_respeita_o_limite_por_chamada(cofre: _Fake) -> None:
    cofre.tabelas["cert_pfx_store"] = [_linha_legada(FP_A), _linha_legada(FP_B)]
    r = ci.recifrar_cofre(limite=1)
    assert r["candidatas"] == 2 and r["recifradas"] == 1 and r["restantes"] == 1


def test_diagnostico_conta_o_que_falta_recifrar(cofre: _Fake, monkeypatch) -> None:
    cofre.tabelas["cert_pfx_store"] = [_linha_legada(FP_A)]
    ci.upsert_pfx(FP_B, b"pfx", "ANALISESRV", password="x")
    d = ci.diagnostico_do_cofre()
    assert d["sem_aad"] == 1
    assert d["senhas_por_key_version"] == {"1": 2}
    k = ci.diagnostico_das_chaves()
    assert k["linhas_para_recifrar"] == 1
    assert k["senha"]["versao_corrente"] == 1 and k["senha"]["versoes_no_cofre"] == [1]
    assert k["senha"]["versoes_sem_chave"] == []

    _rotacionar_para_v2(monkeypatch)
    monkeypatch.delattr(config, "CERT_PASSWORD_ENCRYPTION_KEY_V1")
    k = ci.diagnostico_das_chaves()
    assert k["linhas_para_recifrar"] == 2
    assert k["senha"]["versoes_sem_chave"] == [1], "senha v1 sem chave é material indecifrável agora"


def test_revalidar_tambem_prova_a_senha(cofre: _Fake, monkeypatch) -> None:
    cofre.tabelas["cert_pfx_store"] = [_linha_legada(FP_A)]
    r = ci.revalidar_cofre()
    assert r[0]["ok"] is True and r[0]["senha_ok"] is True
    monkeypatch.setattr(config, "CERT_PASSWORD_ENCRYPTION_KEY", "ff" * 32)
    r = ci.revalidar_cofre()
    assert r[0]["ok"] is True and r[0]["senha_ok"] is False
    assert "CERT_PASSWORD_ENCRYPTION_KEY" in r[0]["detalhe"]


def test_v_da_versao_em_vigor_no_ambiente_gera_aviso(monkeypatch) -> None:
    """O caso do #42: `CERT_ENCRYPTION_KEY_V1` definida com a versão em vigor
    igual a 1 nunca é lida. Antes ninguém avisava; agora é aviso no boot."""
    monkeypatch.setattr(config, "DATABASE_URL", "postgresql://x/y")
    monkeypatch.setattr(config, "CERT_ENCRYPTION_KEY", CHAVE_PFX_V1)
    monkeypatch.setattr(config, "CERT_PASSWORD_ENCRYPTION_KEY", CHAVE_SENHA_V1)
    monkeypatch.setattr(config, "CERT_ENCRYPTION_KEY_VERSION", 1, raising=False)
    monkeypatch.setattr(config, "CERT_ENCRYPTION_KEY_V1", "cc" * 32, raising=False)
    _, avisos = config.verificar_ambiente()
    assert any("CERT_ENCRYPTION_KEY_V1" in a and "vigor" in a for a in avisos)


def test_sem_cofre_exige_aad_em_producao_gera_aviso(monkeypatch) -> None:
    monkeypatch.setattr(config, "DATABASE_URL", "postgresql://x/y")
    monkeypatch.setattr(config, "CERT_ENCRYPTION_KEY", CHAVE_PFX_V1)
    monkeypatch.setattr(config, "CERT_PASSWORD_ENCRYPTION_KEY", CHAVE_SENHA_V1)
    monkeypatch.setattr(config, "COFRE_EXIGE_AAD", False, raising=False)
    _, avisos = config.verificar_ambiente()
    assert any("COFRE_EXIGE_AAD" in a for a in avisos)


def test_rota_de_recifrar_e_de_admin_e_devolve_contagens(client: TestClient, cofre: _Fake) -> None:
    cofre.tabelas["cert_pfx_store"] = [_linha_legada(FP_A)]
    for papel in ("user", "gestor"):
        h = {"Authorization": f"Bearer {auth.create_access_token({'sub': 'x@x.com', 'role': papel})}"}
        assert client.post("/api/cert-installer/recifrar-cofre", headers=h).status_code == 403
    r = client.post("/api/cert-installer/recifrar-cofre", headers=_admin())
    assert r.status_code == 200, r.text
    assert r.json()["recifradas"] == 1 and r.json()["restantes"] == 0


def test_ajuda_do_revalidar_nao_promete_correcao() -> None:
    """A ajuda dizia 'confere de novo as senhas e chaves de todos os
    certificados' — dava a entender que o botão consertava o cofre. Ele só
    prova; quem corrige é o Recifrar."""
    html = (RAIZ / "templates" / "instalador.html").read_text(encoding="utf-8")
    fonte = (RAIZ / "app" / "main.py").read_text(encoding="utf-8")
    assert "Confere de novo as senhas e chaves de todos" not in html
    assert "Confere de novo as senhas e chaves de todos" not in fonte
    assert "recifrar-cofre" in html, "a tela precisa do botão que recifra"


def test_migration_acrescenta_as_duas_colunas() -> None:
    sqls = list((RAIZ / "supabase" / "migrations").glob("*lote8*.sql")) + list(
        (RAIZ / "supabase" / "migrations").glob("*cofre_versao*.sql")
    )
    assert sqls, "falta a migration do lote 8"
    sql = sqls[0].read_text(encoding="utf-8")
    assert "password_key_version" in sql and "aad_version" in sql
    assert "IF NOT EXISTS" in sql, "a migration tem de ser idempotente"


# ──────────────────────────────────────────────────────────────────────────
# #56 — código de redefinição com sal e HMAC
# ──────────────────────────────────────────────────────────────────────────

@pytest.fixture
def reset(monkeypatch: pytest.MonkeyPatch) -> _Fake:
    fake = _Fake({sr.TABELA: []})
    monkeypatch.setattr(sr, "_banco", lambda: fake)
    monkeypatch.setattr(sr, "gerar_codigo", lambda: "123456")
    return fake


def test_hash_nao_e_mais_sha256_puro_do_codigo(reset: _Fake) -> None:
    sr.criar_codigo("u-1")
    guardado = reset.tabelas[sr.TABELA][0]["codigo_hash"]
    assert guardado != hashlib.sha256(b"123456").hexdigest()
    assert hashlib.sha256(b"123456").hexdigest() not in guardado
    assert guardado.startswith(sr.PREFIXO_HASH)


def test_dois_pedidos_com_o_mesmo_codigo_geram_hashes_diferentes(reset: _Fake) -> None:
    """O 'Como testar' do #56. Sem sal por linha, um dump da tabela e uma
    tabela de 10^6 entradas revelavam todos os códigos pendentes de uma vez."""
    sr.criar_codigo("u-1")
    sr.criar_codigo("u-2")
    h1, h2 = (l["codigo_hash"] for l in reset.tabelas[sr.TABELA])
    assert h1 != h2


def test_codigo_novo_confere_e_errado_nao(reset: _Fake) -> None:
    sr.criar_codigo("u-1")
    assert sr.conferir("u-1", "123456")[0] is True
    assert sr.conferir("u-1", "654321")[0] is False


def test_codigo_legado_em_sha256_puro_ainda_confere(reset: _Fake, caplog) -> None:
    """Janela: um código pedido antes do deploy (vale 15 min) tem o hash
    antigo na tabela e ainda tem de funcionar — com aviso no log."""
    reset.tabelas[sr.TABELA].append({
        "id": "legado", "user_id": "u-9", "codigo_hash": hashlib.sha256(b"123456").hexdigest(),
        "tentativas": 0, "consumed_at": None, "created_at": "2099-01-01T00:00:00+00:00",
        "expires_at": "2099-01-01T00:00:00+00:00",
    })
    with caplog.at_level(logging.WARNING):
        assert sr.conferir("u-9", "123456")[0] is True
    assert "antigo" in caplog.text.lower() or "legad" in caplog.text.lower()
    assert sr.conferir("u-9", "000000")[0] is False
