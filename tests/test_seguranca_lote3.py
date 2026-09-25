"""
Lote 3 das correções do SECURITY_AUDIT.md — a senha no nome do arquivo (#2, #58).

A convenção operacional põe a senha do PFX no nome do arquivo. O portal usava
esse nome como identidade do certificado: chave primária de `cert_history`,
campo de todo item de snapshot, resposta de três rotas, coluna copiável na
tela Duplicidades e linha de log do agente. O cofre cifrava a senha; o nome ao
lado a entregava em claro.

Cada teste aqui foi escrito antes da correção e falhava em `4bf7c40` (fim do
lote 2). O que fica guardado:

  * o nome público sai do PFX (titular, CNPJ, fingerprint); a limpeza do nome
    é só o fallback do arquivo ilegível, e cobre as variantes REAIS da pasta
  * o nome original não é gravado nem devolvido: snapshots, cert_history e as
    três rotas saem sem `file_name` e sem `path`; a pasta só para admin
  * a chave de deduplicação não carrega segredo
  * o agente loga o nome público
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List

import pytest
from fastapi.testclient import TestClient

import app.cert_installer as ci
import app.main as m
from app import auth, config, nome_publico as np_
from app.cert_scanner import CertInfo, CertStatus, cert_to_public_dict
from tests.test_seguranca_lote1 import _Fake, _usuario

RAIZ = Path(__file__).resolve().parent.parent
ADMIN = ("admin@x.com", "admin")
USER = ("ana@x.com", "user")
SENHA_NO_NOME = "senha 9f3Kz"          # marca que NUNCA pode sair
DOC = "12345678000199"


def _h(email: str, papel: str) -> dict:
    return {"Authorization": "Bearer " + auth.create_access_token({"sub": email, "role": papel})}


# ──────────────────────────────────────────────────────────────────────────
# 1. O nome público de um arquivo — tabela com as formas reais da pasta,
#    anonimizadas (levantamento de 25/09/2026 sobre 1.049 nomes).
# ──────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("arquivo, esperado", [
    # a forma dominante: NOME_CNPJ senha 999999.pfx (e .p12, e 8 dígitos)
    ("EMPRESA ALFA LTDA_12345678000199 senha 123456.pfx", "EMPRESA ALFA LTDA_12345678000199"),
    ("EMPRESA ALFA LTDA_12345678000199 senha 12345678.p12", "EMPRESA ALFA LTDA_12345678000199"),
    ("EMPRESA ALFA LTDA_12345678909 senha 123456.pfx", "EMPRESA ALFA LTDA_12345678909"),
    # sem documento no nome
    ("EMPRESA ALFA LTDA senha 1234.pfx", "EMPRESA ALFA LTDA"),
    # CNPJ colado no nome
    ("EMPRESA ALFA LTDA12345678000199 senha 123456.pfx", "EMPRESA ALFA LTDA12345678000199"),
    # caixa e espaço variam
    ("EMPRESA ALFA_12345678000199 SENHA123456.pfx", "EMPRESA ALFA_12345678000199"),
    ("EMPRESA ALFA_12345678000199 senha123456.pfx", "EMPRESA ALFA_12345678000199"),
    ("EMPRESA ALFA SENHA 1234.pfx", "EMPRESA ALFA"),
    # senha com letras e símbolos, com espaço antes da extensão
    ("EMPRESA ALFA senha Ab12@!.pfx", "EMPRESA ALFA"),
    ("EMPRESA ALFA LTDA senha X9y .pfx", "EMPRESA ALFA LTDA"),
    # sufixos depois da senha: cópia do Windows, anotação, outro número
    ("EMPRESA ALFA_12345678000199 senha 123456 (2).pfx", "EMPRESA ALFA_12345678000199"),
    ("EMPRESA ALFA_12345678000199 senha 123456 - renovado.pfx", "EMPRESA ALFA_12345678000199"),
    ("EMPRESA ALFA_12345678909 senha 123456_x_1234567890.pfx", "EMPRESA ALFA_12345678909"),
    # as variantes do roteiro: "senh" truncado e número solto depois do CNPJ
    ("EMPRESA ALFA senh 123456.pfx", "EMPRESA ALFA"),
    ("EMPRESA ALFA_21640463000198 123456.pfx", "EMPRESA ALFA_21640463000198"),
    # as que sobraram no ensaio da migração (25/09): "senha" colada no CNPJ ou
    # depois de "_", onde `\b` não enxerga fronteira
    ("EMPRESA ALFA LTDA_12345678000199senha 123456.pfx", "EMPRESA ALFA LTDA_12345678000199"),
    ("EMPRESA ALFA LTDA_SENHA 12345678.pfx", "EMPRESA ALFA LTDA"),
    ("EMPRESA ALFA_senha 12345678.pfx", "EMPRESA ALFA"),
    # sem senha no nome: fica como está, sem a extensão
    ("EMPRESA ALFA LTDA_12345678000199.pfx", "EMPRESA ALFA LTDA_12345678000199"),
    ("arquivo.pfx", "arquivo"),
    # "senh" dentro de palavra ou como palavra do nome NÃO é senha
    ("DESENHOS BETA LTDA_12345678000199 senha 1.pfx", "DESENHOS BETA LTDA_12345678000199"),
    ("SENHORA DAS GRACAS ME_12345678000199 senha 55.pfx", "SENHORA DAS GRACAS ME_12345678000199"),
    ("ENGENHARIA GAMA LTDA senha 77.pfx", "ENGENHARIA GAMA LTDA"),
])
def test_nome_publico_cobre_as_formas_reais(arquivo: str, esperado: str) -> None:
    assert np_.nome_publico_de_arquivo(arquivo) == esperado


def test_nome_publico_nunca_devolve_o_que_vem_depois_de_senha() -> None:
    for arquivo in ["X senha 654321.pfx", "X SENHA654321.pfx", "X senha Ab@1.pfx", "X_98765432000188 654321.pfx"]:
        saida = np_.nome_publico_de_arquivo(arquivo)
        assert "654321" not in saida and "Ab@1" not in saida


def test_nome_publico_de_nome_so_com_senha_e_vazio() -> None:
    assert np_.nome_publico_de_arquivo("senha 123.pfx") == ""
    assert np_.nome_publico_de_arquivo("") == ""


@pytest.mark.parametrize("caminho, esperado", [
    (r"F:\CERTIFICADOS\Clientes\X senha 1.pfx", "F:/CERTIFICADOS/Clientes"),
    ("/srv/certs/x senha 1.pfx", "/srv/certs"),
    ("x.pfx", ""),
    ("", ""),
    (None, ""),
])
def test_pasta_e_o_diretorio_sem_o_nome_do_arquivo(caminho, esperado: str) -> None:
    assert np_.pasta_de(caminho) == esperado


def test_chave_de_arquivo_nao_carrega_segredo_e_e_estavel() -> None:
    a = np_.chave_de_arquivo("EMPRESA ALFA_12345678000199", "ab" * 32)
    b = np_.chave_de_arquivo("empresa alfa_12345678000199", "AB" * 32)
    assert a == b and re.fullmatch(r"[0-9a-f]{64}", a)
    assert a != np_.chave_de_arquivo("EMPRESA ALFA_12345678000199", "cd" * 32)
    assert a != np_.chave_de_arquivo("OUTRA", "ab" * 32)


# ──────────────────────────────────────────────────────────────────────────
# 2. Um item de inventário sanitizado
# ──────────────────────────────────────────────────────────────────────────

def _item_bruto(**extra: Any) -> Dict[str, Any]:
    it = {
        "file_name": f"EMPRESA ALFA LTDA_{DOC} {SENHA_NO_NOME}.pfx",
        "path": rf"F:\CERTIFICADOS\Alfa\EMPRESA ALFA LTDA_{DOC} {SENHA_NO_NOME}.pfx",
        "display_name": f"EMPRESA ALFA LTDA_{DOC}",
        "nome": "EMPRESA ALFA LTDA", "documento_numero": DOC, "documento_formatado": "12.345.678/0001-99",
        "status": "ok", "fingerprint_sha256": "ab" * 32, "not_after": "2027-01-01T00:00:00+00:00",
        "password_from_name": "9f3Kz",
    }
    it.update(extra)
    return it


def test_item_sanitizado_nao_tem_nome_bruto_nem_caminho_nem_senha() -> None:
    s = np_.sanitizar_item(_item_bruto())
    for chave in ("file_name", "path", "password_from_name", "password"):
        assert chave not in s
    assert s["nome_publico"] == f"EMPRESA ALFA LTDA_{DOC}"
    assert s["pasta"] == "F:/CERTIFICADOS/Alfa"
    assert s["arquivo_chave"] == np_.chave_de_arquivo(s["nome_publico"], "ab" * 32)
    assert SENHA_NO_NOME not in repr(s)
    # o que não é segredo fica
    assert s["nome"] == "EMPRESA ALFA LTDA" and s["documento_numero"] == DOC


def test_item_ilegivel_tem_o_nome_limpo_do_arquivo() -> None:
    """Sem subject não há titular: o nome vem do arquivo, e vem limpo."""
    s = np_.sanitizar_item(_item_bruto(status="erro", nome=f"EMPRESA ALFA LTDA_{DOC}",
                                       display_name=f"EMPRESA ALFA LTDA_{DOC}", fingerprint_sha256=None))
    assert s["nome"] == f"EMPRESA ALFA LTDA_{DOC}"
    assert SENHA_NO_NOME not in repr(s)


def test_titular_que_contem_senha_como_palavra_nao_e_cortado() -> None:
    """O `nome` de um certificado legível vem do CN, não do arquivo: não se limpa."""
    s = np_.sanitizar_item(_item_bruto(nome="SENHA SERVICOS LTDA"))
    assert s["nome"] == "SENHA SERVICOS LTDA"


def test_sanitizar_e_idempotente_e_aceita_item_ja_publico() -> None:
    uma = np_.sanitizar_item(_item_bruto())
    assert np_.sanitizar_item(dict(uma)) == uma
    novo_agente = {"nome_publico": "EMPRESA ALFA LTDA_" + DOC, "pasta": "F:/x", "nome": "EMPRESA ALFA LTDA",
                   "status": "ok", "fingerprint_sha256": "ab" * 32}
    s = np_.sanitizar_item(novo_agente)
    assert s["nome_publico"] == "EMPRESA ALFA LTDA_" + DOC and s["arquivo_chave"]


def test_cert_to_public_dict_ja_sai_publico() -> None:
    """É o que o agente NOVO manda: nem ele precisa transportar o nome bruto."""
    c = CertInfo(path=Path(rf"F:\CERTIFICADOS\Alfa\EMPRESA ALFA_{DOC} {SENHA_NO_NOME}.pfx"),
                 file_name=f"EMPRESA ALFA_{DOC} {SENHA_NO_NOME}.pfx", display_name=f"EMPRESA ALFA_{DOC}",
                 status=CertStatus.OK, password_from_name="9f3Kz")
    d = cert_to_public_dict(c)
    assert "file_name" not in d and "path" not in d
    assert d["nome_publico"] == f"EMPRESA ALFA_{DOC}" and d["pasta"] == "F:/CERTIFICADOS/Alfa"
    assert SENHA_NO_NOME not in repr(d)


# ──────────────────────────────────────────────────────────────────────────
# 3. Ponta a ponta: um agente ANTIGO manda o nome bruto; nada dele sai
# ──────────────────────────────────────────────────────────────────────────

@pytest.fixture
def banco(monkeypatch: pytest.MonkeyPatch) -> _Fake:
    fake = _Fake({
        "users": [_usuario("u-adm", "admin@x.com", "admin"), _usuario("u-ana", "ana@x.com", "user")],
        "user_activity": [], "cert_snapshots": [], "cert_history": [], "carteira": [],
    })
    monkeypatch.setattr("app.settings_state._banco", lambda: fake)
    monkeypatch.setattr(ci, "_banco", lambda: fake)
    monkeypatch.setattr(m, "trigger_all_alerts", lambda: None)
    monkeypatch.setattr(config, "ACEITAR_API_KEY_COMPARTILHADA", True, raising=False)
    return fake


def _ingerir(client: TestClient, itens: List[dict]) -> None:
    r = client.post("/api/ingest", headers=_h(*ADMIN),
                    json={"machine_id": "srv", "source_folder": "F:/CERTIFICADOS", "expired_folder": "F:/V",
                          "items": itens})
    assert r.status_code == 200, r.text


@pytest.fixture
def inventario_antigo(client: TestClient, banco: _Fake) -> _Fake:
    _ingerir(client, [
        _item_bruto(),
        _item_bruto(file_name=f"EMPRESA ALFA LTDA_{DOC} {SENHA_NO_NOME} (2).pfx",
                    path=rf"F:\CERTIFICADOS\Copias\EMPRESA ALFA LTDA_{DOC} {SENHA_NO_NOME} (2).pfx"),
        _item_bruto(file_name=f"BETA ME_98765432000188 {SENHA_NO_NOME}.pfx", nome="BETA ME",
                    documento_numero="98765432000188", fingerprint_sha256="cd" * 32,
                    path=rf"F:\CERTIFICADOS\Beta\BETA ME_98765432000188 {SENHA_NO_NOME}.pfx"),
        _item_bruto(file_name=f"ILEGIVEL SA_11122233000144 {SENHA_NO_NOME}.pfx", status="erro",
                    nome=f"ILEGIVEL SA_11122233000144", display_name="ILEGIVEL SA_11122233000144",
                    fingerprint_sha256=None, subject=None, not_after=None,
                    path=rf"F:\CERTIFICADOS\ILEGIVEL SA_11122233000144 {SENHA_NO_NOME}.pfx"),
    ])
    return banco


def test_snapshot_gravado_nao_tem_nome_bruto(inventario_antigo: _Fake) -> None:
    snaps = inventario_antigo.tabelas["cert_snapshots"]
    assert snaps, "o ingest tem de gravar o snapshot"
    texto = repr(snaps)
    assert "senh" not in texto.lower()
    for it in snaps[0]["items"]:
        assert "file_name" not in it and "path" not in it
        assert it["nome_publico"] and it["arquivo_chave"]


def test_cert_history_gravado_pela_chave_publica(inventario_antigo: _Fake) -> None:
    hist = inventario_antigo.tabelas["cert_history"]
    assert hist, "o ingest tem de alimentar o histórico"
    assert "senh" not in repr(hist).lower()
    for linha in hist:
        assert "file_name" not in linha
        assert re.fullmatch(r"[0-9a-f]{64}", linha["arquivo_chave"])
        assert linha["nome_publico"]
    # a mesma empresa em duas cópias do MESMO certificado é UMA linha
    chaves = [l["arquivo_chave"] for l in hist]
    assert len(chaves) == len(set(chaves))
    assert len(hist) == 3


@pytest.mark.parametrize("rota", [
    "/api/certificados?fonte=remoto&todas_filtradas=true",
    "/api/certificados/duplicidades",
    "/api/certificados/historico",
])
def test_nenhuma_rota_devolve_senha_nem_nome_bruto(client: TestClient, inventario_antigo: _Fake, rota: str,
                                                   monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(m, "_resolve_user_id", lambda email: "u-ana")
    r = client.get(rota, headers=_h(*USER))
    assert r.status_code == 200, r.text
    corpo = r.text
    assert "senh" not in corpo.lower(), rota
    assert '"file_name"' not in corpo and '"path"' not in corpo, rota


def test_pasta_so_para_admin(client: TestClient, inventario_antigo: _Fake, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(m, "_resolve_user_id", lambda email: "u-ana")
    de_user = client.get("/api/certificados?fonte=remoto&todas_filtradas=true", headers=_h(*USER)).json()
    de_admin = client.get("/api/certificados?fonte=remoto&todas_filtradas=true", headers=_h(*ADMIN)).json()
    assert all("pasta" not in it for it in de_user["itens"])
    assert any(it.get("pasta") == "F:/CERTIFICADOS/Alfa" for it in de_admin["itens"])
    dup_user = client.get("/api/certificados/duplicidades", headers=_h(*USER)).text
    dup_admin = client.get("/api/certificados/duplicidades", headers=_h(*ADMIN)).text
    assert '"pasta"' not in dup_user and '"pasta"' in dup_admin


def test_duplicidades_agrupa_pelo_nome_publico(client: TestClient, inventario_antigo: _Fake) -> None:
    j = client.get("/api/certificados/duplicidades", headers=_h(*ADMIN)).json()
    iguais = j["grupos_certificado_igual"]
    assert len(iguais) == 1 and len(iguais[0]["itens"]) == 2
    assert all(it["nome_publico"] == f"EMPRESA ALFA LTDA_{DOC}" for it in iguais[0]["itens"])
    assert {it["pasta"] for it in iguais[0]["itens"]} == {"F:/CERTIFICADOS/Alfa", "F:/CERTIFICADOS/Copias"}


def test_snapshot_antigo_ainda_no_banco_sai_sanitizado(client: TestClient, banco: _Fake,
                                                        monkeypatch: pytest.MonkeyPatch) -> None:
    """Antes da migração rodar, o banco tem snapshots com o nome bruto. A
    saída da API não pode depender de a migração já ter acontecido."""
    banco.tabelas["cert_snapshots"].append({"id": "s1", "machine_id": "srv", "scanned_at": "2026-09-01T00:00:00+00:00",
                                            "source_folder": "F:/C", "expired_folder": "F:/V",
                                            "items": [_item_bruto()]})
    monkeypatch.setattr(m, "_resolve_user_id", lambda email: "u-ana")
    for rota in ["/api/certificados?fonte=remoto&todas_filtradas=true", "/api/certificados/duplicidades",
                 "/api/certificados/historico"]:
        r = client.get(rota, headers=_h(*USER))
        assert r.status_code == 200, r.text
        assert "senh" not in r.text.lower(), rota


def test_busca_do_historico_procura_no_nome_publico() -> None:
    fonte = (RAIZ / "app" / "main.py").read_text(encoding="utf-8")
    assert "file_name.ilike" not in fonte
    assert "nome_publico.ilike" in fonte


# ──────────────────────────────────────────────────────────────────────────
# 4. Tela, agente e fonte
# ──────────────────────────────────────────────────────────────────────────

def test_tela_duplicidades_mostra_o_nome_publico() -> None:
    html = (RAIZ / "templates" / "duplicidades.html").read_text(encoding="utf-8")
    assert "it.path || it.file_name" not in html
    assert "nome_publico" in html


def test_agente_nao_loga_o_nome_do_arquivo() -> None:
    for arq in ("agent/installer_client.py", "agent/run_agent.py"):
        fonte = (RAIZ / arq).read_text(encoding="utf-8")
        for linha in fonte.splitlines():
            if "LOGGER." in linha and re.search(r"(?<!nome_publico_de_arquivo\()c\.file_name", linha):
                pytest.fail(f"{arq}: log com o nome bruto do arquivo: {linha.strip()}")


def test_mover_vencidos_nao_devolve_o_nome_bruto(client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    from app import settings_state
    from datetime import datetime, timezone

    venc = CertInfo(path=tmp_path / f"VELHA SA_{DOC} {SENHA_NO_NOME}.pfx", file_name=f"VELHA SA_{DOC} {SENHA_NO_NOME}.pfx",
                    display_name=f"VELHA SA_{DOC}", status=CertStatus.EXPIRED,
                    not_after=datetime(2020, 1, 1, tzinfo=timezone.utc))
    venc.path.write_bytes(b"x")
    monkeypatch.setattr(m, "scan_folder", lambda *a, **k: [venc])
    monkeypatch.setattr(m, "load_settings", lambda: type("S", (), {
        "effective_source": lambda self: tmp_path, "effective_expired": lambda self: tmp_path / "venc"})())
    r = client.post("/api/mover-vencidos", headers=_h(*ADMIN))
    assert r.status_code == 200, r.text
    assert "senh" not in r.text.lower()


# ──────────────────────────────────────────────────────────────────────────
# 5. A migração — funções puras do script
# ──────────────────────────────────────────────────────────────────────────

def _script():
    import importlib.util

    caminho = RAIZ / "scripts" / "migracao_lote3_nome_publico.py"
    spec = importlib.util.spec_from_file_location("migracao_lote3", caminho)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def test_migracao_transforma_historico_e_resolve_colisoes() -> None:
    mig = _script()
    linhas = [
        {"file_name": f"EMPRESA ALFA LTDA_{DOC} senha 111111.pfx", "ultima_data_registrada": "2026-01-01T00:00:00+00:00", "nome": "A"},
        {"file_name": f"EMPRESA ALFA LTDA_{DOC} senha 222222.pfx", "ultima_data_registrada": "2026-06-01T00:00:00+00:00", "nome": "A"},
        {"file_name": "BETA ME_98765432000188 senha 3.pfx", "ultima_data_registrada": "2026-03-01T00:00:00+00:00", "nome": "B"},
    ]
    # o mesmo certificado, renomeado com senha nova, aparece nos snapshots com o mesmo fingerprint
    mapa_fp = {linhas[0]["file_name"]: "ab" * 32, linhas[1]["file_name"]: "ab" * 32}
    novas, colisoes = mig.transformar_historico(linhas, mapa_fp)
    assert colisoes == 1
    assert len(novas) == 2
    alfa = next(l for l in novas if l["nome"] == "A")
    assert alfa["ultima_data_registrada"].startswith("2026-06"), "a colisão fica com a linha mais recente"
    assert alfa["nome_publico"] == f"EMPRESA ALFA LTDA_{DOC}"
    assert alfa["arquivo_chave"] == np_.chave_de_arquivo(alfa["nome_publico"], "ab" * 32)
    assert all("file_name" not in l for l in novas)
    assert "senh" not in repr(novas).lower()


def test_migracao_sanitiza_itens_de_snapshot() -> None:
    mig = _script()
    itens, n = mig.sanitizar_itens([_item_bruto(), {"nome_publico": "JA PUBLICO", "status": "ok"}])
    assert n == 1, "conta só os itens que tinham nome bruto"
    assert "senh" not in repr(itens).lower()
    assert all("file_name" not in i and "path" not in i for i in itens)


def test_migracao_tem_ida_e_volta() -> None:
    fonte = (RAIZ / "scripts" / "migracao_lote3_nome_publico.py").read_text(encoding="utf-8")
    for marca in ("--ida", "--volta", "--dry-run", "cert_history_bkp_lote3", "cert_snapshots_bkp_lote3",
                  "ILIKE '%senh%'"):
        assert marca in fonte, marca
