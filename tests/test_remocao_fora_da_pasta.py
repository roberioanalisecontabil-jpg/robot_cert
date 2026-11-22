"""Regra "Saiu da pasta" da remoção nas estações (22/11/2026).

O expurgo apagava do cofre o certificado vencido ou removido da pasta, e com
ele a única prova de que aquele certificado era do escritório: as cópias já
instaladas ficavam nas estações para sempre. Agora o expurgo guarda a
impressão digital (sem chave nem senha) em `cert_acervo_saida`, e a regra
própria, começando em "relatório", decide a remoção.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from app import cert_installer, remocao
from tests.test_computadores_rotas import PC_FIS, _bandeja, _entrar
from tests.test_computadores_rotas import banco  # noqa: F401
from tests.test_seguranca_lote1 import _Fake
from tests.test_seguranca_lote4 import ADMIN, AGORA, _h
from tests.test_seguranca_lote4 import banco as banco_base  # noqa: F401

RAIZ = Path(__file__).resolve().parent.parent
FA, FF, FV = "a" * 64, "f" * 64, "9" * 64


def _saida(banco: _Fake, fp: str = FF, motivo: str = "saiu da pasta") -> None:
    banco.tabelas.setdefault("cert_acervo_saida", []).append(
        {"fingerprint": fp, "documento": "55555555000155", "nome_titular": "ZETA", "motivo": motivo,
         "saiu_em": (AGORA - timedelta(days=4)).isoformat()})


def _conferir(client: TestClient, banco: _Fake, certificados):
    seg = _entrar(client, "fis@x.com", PC_FIS)["segredo"]
    return client.post("/api/estacao/conferencia", headers=_bandeja(seg),
                       json={"usuario_windows": "fis", "certificados": certificados})


# ── O expurgo guarda a saída ───────────────────────────────────────────────

def test_expurgo_guarda_o_vencido_e_o_que_saiu_da_pasta(banco_base: _Fake) -> None:  # noqa: F811
    banco_base.tabelas["cert_acervo_saida"] = []
    agora = datetime.now(timezone.utc)
    banco_base.tabelas["cert_pfx_store"] += [
        {"id": "pfx-v", "fingerprint": FV, "machine_id": "srv", "documento": "66666666000166",
         "nome_titular": "VENCIDA", "not_after": (agora - timedelta(days=1)).isoformat()},
        {"id": "pfx-f", "fingerprint": FF, "machine_id": "srv", "documento": "55555555000155",
         "nome_titular": "ZETA", "not_after": (agora + timedelta(days=100)).isoformat(),
         "ausente_desde": (agora - timedelta(days=4)).isoformat()},
    ]
    cert_installer.expurgar_cofre()
    fps = {l["fingerprint"] for l in banco_base.tabelas["cert_pfx_store"]}
    assert FV not in fps and FF not in fps
    saida = {l["fingerprint"]: l for l in banco_base.tabelas["cert_acervo_saida"]}
    assert saida[FV]["motivo"] == "vencido" and saida[FV]["documento"] == "66666666000166"
    assert saida[FF]["motivo"] == "saiu da pasta" and saida[FF]["nome_titular"] == "ZETA"
    for linha in saida.values():
        assert set(linha) - {"id"} <= {"fingerprint", "documento", "nome_titular", "motivo", "saiu_em"}, "sem chave nem senha"


# ── A regra ────────────────────────────────────────────────────────────────

def test_relatorio_registra_e_nao_remove(client: TestClient, banco: _Fake, monkeypatch) -> None:  # noqa: F811
    monkeypatch.setattr(remocao, "modo_carteira", lambda: "relatorio")
    monkeypatch.setattr(remocao, "modo_fora_da_pasta", lambda: "relatorio")
    _saida(banco)
    r = _conferir(client, banco, [FA, FF])
    assert r.status_code == 200, r.text
    assert r.json()["remover"] == [] and r.json()["avisos"] == []
    linha = next(l for l in banco.tabelas["remocao_estacao"] if l["fingerprint"] == FF)
    assert (linha["regra"], linha["estado"], linha["motivo"]) == ("fora_da_pasta", "removeria", "saiu da pasta")


def test_ligado_avisa_sete_dias_mesmo_com_carteira_desligada(client: TestClient, banco: _Fake,  # noqa: F811
                                                            monkeypatch) -> None:
    monkeypatch.setattr(remocao, "modo_carteira", lambda: "desligado")
    monkeypatch.setattr(remocao, "modo_fora_da_pasta", lambda: "ligado")
    _saida(banco)
    j = _conferir(client, banco, [FA, FF]).json()
    assert [(a["fingerprint"], a["dias"], a["nome"]) for a in j["avisos"]] == [(FF, 7, "ZETA")]
    assert j["remover"] == []


def test_de_volta_ao_cofre_nao_sai(client: TestClient, banco: _Fake, monkeypatch) -> None:  # noqa: F811
    monkeypatch.setattr(remocao, "modo_fora_da_pasta", lambda: "ligado")
    _saida(banco, FA)  # saiu um dia, mas voltou: está no cofre
    _conferir(client, banco, [FA])
    assert not [l for l in banco.tabelas["remocao_estacao"] if l["regra"] == "fora_da_pasta"]


def test_desligado_nao_decide(client: TestClient, banco: _Fake, monkeypatch) -> None:  # noqa: F811
    monkeypatch.setattr(remocao, "modo_carteira", lambda: "relatorio")
    monkeypatch.setattr(remocao, "modo_fora_da_pasta", lambda: "desligado")
    _saida(banco)
    _conferir(client, banco, [FF])
    assert not [l for l in banco.tabelas["remocao_estacao"] if l["fingerprint"] == FF]


def test_modo_padrao_e_relatorio(monkeypatch) -> None:
    from app import settings_state

    monkeypatch.setattr(remocao, "load_settings", lambda: settings_state.PortalSettings(source_folder="", expired_folder=""))
    assert remocao.modo_fora_da_pasta() == "relatorio"


# ── Configuração, tela e banco ─────────────────────────────────────────────

def test_configuracao_grava_o_modo(client: TestClient, banco: _Fake) -> None:  # noqa: F811
    import app.rotas.configuracao as cfg

    corpo = {k: v for k, v in cfg.SettingsBody().model_dump().items() if v is not None}
    corpo.update(machine_id="srv", remocao_fora_da_pasta_modo="ligado")
    r = client.put("/api/settings", headers=_h(*ADMIN), json=corpo)
    assert r.status_code == 200, r.text
    assert client.get("/api/settings", headers=_h(*ADMIN)).json()["remocao_fora_da_pasta_modo"] == "ligado"
    corpo["remocao_fora_da_pasta_modo"] = "talvez"
    assert client.put("/api/settings", headers=_h(*ADMIN), json=corpo).status_code == 422


def test_tela_tem_o_seletor_e_o_rotulo() -> None:
    html = (RAIZ / "templates" / "configuracao.html").read_text(encoding="utf-8")
    assert 'id="sel-remocao-fora-da-pasta"' in html
    assert 'remocao_fora_da_pasta_modo: document.getElementById("sel-remocao-fora-da-pasta").value' in html
    js = (RAIZ / "static" / "configuracao-remocao.js").read_text(encoding="utf-8")
    assert 'fora_da_pasta: "Saiu da pasta"' in js


def test_migration() -> None:
    sql = (RAIZ / "supabase" / "migrations" / "20261122100000_remocao_fora_da_pasta.sql").read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS public.cert_acervo_saida" in sql
    assert "'fora_da_pasta'" in sql and "DROP CONSTRAINT IF EXISTS remocao_estacao_regra_check" in sql
    assert "ADD COLUMN IF NOT EXISTS remocao_fora_da_pasta_modo" in sql


def test_nao_toca_certificado_pessoal(client: TestClient, banco: _Fake, monkeypatch) -> None:  # noqa: F811
    """Certificado que nunca esteve no cofre (o e-CPF pessoal) não entra em regra nenhuma."""
    monkeypatch.setattr(remocao, "modo_carteira", lambda: "ligado")
    monkeypatch.setattr(remocao, "modo_fora_da_pasta", lambda: "ligado")
    j = _conferir(client, banco, ["7" * 64]).json()
    assert j["remover"] == [] and j["avisos"] == []
