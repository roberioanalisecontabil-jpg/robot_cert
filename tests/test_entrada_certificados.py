"""
Entrada de certificados e aviso de novos por hora cheia (02/10/2026).

Decisões com o usuário (F1–F6, G1–G4):
  F1  Pasta de entrada separada do acervo; configurável no portal.
  F2  Nome pelo que está DENTRO do PFX: `TITULAR DOCUMENTO senha VALOR.pfx`,
      maiúsculas, sem acento, só dígitos no documento.
  F3  O que não abre fica na entrada; o portal lista como pendente e avisa os
      administradores por e-mail (uma vez por arquivo).
  F4  Pasta da letra sob pessoa jurídica (CNPJ) ou física (CPF); `0 a 9` para
      algarismo; o agente cria a que faltar.
  F5  Colisão pelo documento: mesmo fingerprint = cópia descartada; anterior
      vencido vai para vencidos e o novo toma o lugar; dois vigentes ficam,
      o novo com sufixo e marcado como duplicidade.
  F6  Processa ao chegar (observador) e antes da varredura; registro em
      Instalador › Entrada.
  G3  Chegou vencido → direto para vencidos.
  G4  Chave "Avisar quando chegar certificado novo"; o aviso sai só depois do
      renomear+mover (a entrada fica fora da varredura); por hora cheia
      (padrão) ou imediato.

Segunda rodada (02/10/2026, agente 1.6.0), Q1–Q8:
  Q1  A varredura continua tirando vencidos das pastas das letras, e GARANTE:
      confere, tenta de novo, e o que ficar vira pendência "vencido_preso"
      com e-mail aos administradores.
  Q2  Pasta de vencidos continua plana.
  Q3  A aba vira "Movimentos" e registra também o vencido movido pela
      varredura, com a pasta de origem.
  Q5  Ilegíveis nas pastas das letras ficam como estão (visíveis no Início).
  Q6  Sufixo de colisão unificado em `(2)`, `(3)`… (sai o `_dup_<carimbo>`).
  Q7  Instalador: apagar → renomear → trocar no reinício; EventMessageFile
      numa cópia estável fora de _internal (causa confirmada no servidor).
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

import pytest
from fastapi.testclient import TestClient

import app.main as m
import app.novos_certificados as nc
import app.settings_state as ss
from agent import entrada as ag
from app import alertas_config
from app import entrada as pe
from app.cert_scanner import scan_folder
from tests.test_seguranca_lote1 import _Fake, _usuario
from tests.test_seguranca_lote4 import ADMIN, GESTOR, _h
from tests.test_seguranca_lote4 import banco as banco_base  # noqa: F401

RAIZ = Path(__file__).resolve().parents[1]
CNPJ = "12345678000199"
CNPJ_2 = "98765432000188"
CPF = "12345678909"


# ══════════════════════════════════════════════════════════════════════════
# 1. Nome e pasta (F2, F4)
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("titular, doc, senha, esperado", [
    ("Brasil Exemplo Ltda.", "12.345.678/0001-99", "123", "BRASIL EXEMPLO LTDA 12345678000199 senha 123.pfx"),
    ("Água & Luz   S/A", CNPJ, "ab c", "AGUA & LUZ S A 12345678000199 senha ab c.pfx"),
    ("JOSÉ DA SILVA", CPF, "x1", "JOSE DA SILVA 12345678909 senha x1.pfx"),
    ("Nome: com <tudo> \"isto\" | ?", "1", "s", "NOME COM TUDO ISTO 1 senha s.pfx"),
])
def test_nome_canonico(titular: str, doc: str, senha: str, esperado: str) -> None:
    assert ag.nome_canonico(titular, doc, senha) == esperado


@pytest.mark.parametrize("titular, letra", [
    ("Brasil Exemplo", "B"), ("água azul", "A"), ("3M do Brasil", "0 a 9"),
    ("  - 7 Belo", "0 a 9"), ("Ñandu Ltda", "N"), ("", "0 a 9"), ("***", "0 a 9"),
])
def test_letra_da_pasta(titular: str, letra: str) -> None:
    assert ag.letra_da_pasta(titular) == letra


# ══════════════════════════════════════════════════════════════════════════
# 2. O processamento, com PFX de verdade (F2–F5, G3)
# ══════════════════════════════════════════════════════════════════════════

@pytest.fixture
def pastas(tmp_path: Path) -> ag.ConfigEntrada:
    cfg = ag.ConfigEntrada(
        pasta_entrada=tmp_path / "Entrada",
        pasta_pj=tmp_path / "02.PESSOA JURIDICA",
        pasta_pf=tmp_path / "01.PESSOA FISICA",
        pasta_vencidos=tmp_path / "Vencidos",
    )
    cfg.pasta_entrada.mkdir()
    cfg.pasta_pj.mkdir()
    cfg.pasta_pf.mkdir()
    return cfg


def gerar_pfx(cnpj: str = CNPJ, senha: str = "abc123", nome: str = "EMPRESA TESTE LTDA", dias: int = 365) -> Dict[str, Any]:
    """Como `tests.pfx_de_teste.gerar_pfx`, mas SEM cache (cada chamada é um
    certificado distinto, com fingerprint próprio — é disso que a colisão
    por documento precisa) e aceitando `dias` negativo (já vencido)."""
    from datetime import timedelta
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives.serialization import pkcs12
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    sujeito = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, f"{nome}:{cnpj}"), x509.NameAttribute(NameOID.COUNTRY_NAME, "BR")])
    agora = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder().subject_name(sujeito).issuer_name(sujeito).public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(agora - timedelta(days=max(1, -dias + 1) if dias < 0 else 1))
        .not_valid_after(agora + timedelta(days=dias))
        .sign(key, hashes.SHA256())
    )
    pfx = pkcs12.serialize_key_and_certificates(b"teste", key, cert, None, serialization.BestAvailableEncryption(senha.encode()))
    return {"bytes": pfx, "fingerprint": cert.fingerprint(hashes.SHA256()).hex(), "not_after": cert.not_valid_after_utc}


def _pfx(pasta: Path, nome_arquivo: str, **kw: Any) -> Dict[str, Any]:
    d = gerar_pfx(**kw)
    (pasta / nome_arquivo).write_bytes(d["bytes"])
    return d


def _nomes(pasta: Path) -> List[str]:
    return sorted(p.name for p in pasta.iterdir()) if pasta.is_dir() else []


def test_renomeia_pelo_titular_e_move_para_a_letra(pastas: ag.ConfigEntrada) -> None:
    _pfx(pastas.pasta_entrada, "brasil_ex senha 123.pfx", cnpj=CNPJ, senha="123", nome="BRASIL EXEMPLO LTDA")
    r = ag.processar_entrada(pastas)
    assert _nomes(pastas.pasta_entrada) == []
    assert _nomes(pastas.pasta_pj / "B") == ["BRASIL EXEMPLO LTDA 12345678000199 senha 123.pfx"], "F2 + F4"
    assert r["pendentes"] == []
    (ev,) = r["eventos"]
    assert ev["resultado"] == "movido" and ev["documento_numero"] == CNPJ and ev["nome"] == "BRASIL EXEMPLO LTDA"
    assert ev["pasta_destino"] == str(pastas.pasta_pj / "B")
    # Nunca a senha (SECURITY_AUDIT #2): nem no nome original, nem no novo.
    assert "123" not in ev["arquivo_original"] and "senha" not in ev["arquivo_novo"].lower()


def test_cpf_vai_para_pessoa_fisica_e_algarismo_para_0_a_9(pastas: ag.ConfigEntrada) -> None:
    _pfx(pastas.pasta_entrada, "jose senha a.pfx", cnpj=CPF, senha="a", nome="JOSE DA SILVA")
    _pfx(pastas.pasta_entrada, "3m senha b.pfx", cnpj=CNPJ_2, senha="b", nome="3M DO BRASIL")
    ag.processar_entrada(pastas)
    assert _nomes(pastas.pasta_pf / "J") == ["JOSE DA SILVA 12345678909 senha a.pfx"]
    assert _nomes(pastas.pasta_pj / ag.PASTA_NUMEROS) == ["3M DO BRASIL 98765432000188 senha b.pfx"]


def test_chegou_vencido_vai_direto_para_vencidos(pastas: ag.ConfigEntrada) -> None:
    _pfx(pastas.pasta_entrada, "velho senha 1.pfx", cnpj=CNPJ, senha="1", nome="VELHO LTDA", dias=-3)
    r = ag.processar_entrada(pastas)
    assert _nomes(pastas.pasta_vencidos) == ["VELHO LTDA 12345678000199 senha 1.pfx"], "G3"
    assert not (pastas.pasta_pj / "V").exists()
    assert r["eventos"][0]["resultado"] == "vencido"


def test_mesmo_fingerprint_e_copia_descartada(pastas: ag.ConfigEntrada) -> None:
    d = gerar_pfx(cnpj=CNPJ, senha="1", nome="ALFA LTDA")
    (pastas.pasta_pj / "A").mkdir()
    (pastas.pasta_pj / "A" / "ALFA LTDA 12345678000199 senha 1.pfx").write_bytes(d["bytes"])
    (pastas.pasta_entrada / "alfa (copia) senha 1.pfx").write_bytes(d["bytes"])
    r = ag.processar_entrada(pastas)
    assert _nomes(pastas.pasta_entrada) == [], "a cópia não fica na entrada"
    assert _nomes(pastas.pasta_pj / "A") == ["ALFA LTDA 12345678000199 senha 1.pfx"]
    (ev,) = r["eventos"]
    assert ev["resultado"] == "copia_descartada" and ev["fingerprint_sha256"] == d["fingerprint"]


def test_anterior_vencido_vai_para_vencidos_e_o_novo_toma_o_lugar(pastas: ag.ConfigEntrada) -> None:
    (pastas.pasta_pj / "A").mkdir()
    _pfx(pastas.pasta_pj / "A", "ALFA LTDA 12345678000199 senha 1.pfx", cnpj=CNPJ, senha="1", nome="ALFA LTDA", dias=-10)
    _pfx(pastas.pasta_entrada, "alfa novo senha 2.pfx", cnpj=CNPJ, senha="2", nome="ALFA LTDA")
    r = ag.processar_entrada(pastas)
    assert _nomes(pastas.pasta_pj / "A") == ["ALFA LTDA 12345678000199 senha 2.pfx"]
    assert _nomes(pastas.pasta_vencidos) == ["ALFA LTDA 12345678000199 senha 1.pfx"]
    resultados = sorted(e["resultado"] for e in r["eventos"])
    assert resultados == ["substituiu", "vencido"], "F5: dois eventos, um por arquivo"


def test_dois_vigentes_ficam_e_o_novo_e_duplicidade_com_sufixo(pastas: ag.ConfigEntrada) -> None:
    (pastas.pasta_pj / "A").mkdir()
    _pfx(pastas.pasta_pj / "A", "ALFA LTDA 12345678000199 senha 1.pfx", cnpj=CNPJ, senha="1", nome="ALFA LTDA")
    _pfx(pastas.pasta_entrada, "alfa senha 1.pfx", cnpj=CNPJ, senha="1", nome="ALFA LTDA")
    r = ag.processar_entrada(pastas)
    assert _nomes(pastas.pasta_pj / "A") == [
        "ALFA LTDA 12345678000199 (2) senha 1.pfx",
        "ALFA LTDA 12345678000199 senha 1.pfx",
    ]
    (ev,) = r["eventos"]
    assert ev["resultado"] == "duplicidade" and "vigente" in ev["motivo"]
    # O sufixo não quebra o padrão do nome: a varredura ainda lê a senha.
    lidos = scan_folder(pastas.pasta_pj / "A", recursive=False)
    assert {c.status.value for c in lidos} == {"ok"}, [c.error_message for c in lidos]


def test_o_que_nao_abre_fica_na_entrada_como_pendente(pastas: ag.ConfigEntrada) -> None:
    _pfx(pastas.pasta_entrada, "nome_sem_padrao.pfx", cnpj=CNPJ, senha="1")
    _pfx(pastas.pasta_entrada, "errada senha 999.pfx", cnpj=CNPJ_2, senha="1")
    (pastas.pasta_entrada / "lixo senha 1.pfx").write_bytes(b"nao e um pfx")
    r = ag.processar_entrada(pastas)
    assert len(_nomes(pastas.pasta_entrada)) == 3, "F3: ficam na pasta"
    assert r["eventos"] == []
    # `arquivo_original` é o nome PÚBLICO (sem extensão, cortado em "senha").
    motivos = {p["arquivo_original"]: p["motivo"] for p in r["pendentes"]}
    assert "fora do padrão" in motivos["nome_sem_padrao"], motivos
    assert "Senha incorreta" in motivos["errada"], motivos
    assert "não abriu" in motivos["lixo"], motivos
    assert all(p["resultado"] == "pendente" for p in r["pendentes"])
    assert not any("999" in p["arquivo_original"] for p in r["pendentes"]), "a senha não sai no nome"


def test_titular_sem_documento_fica_pendente(pastas: ag.ConfigEntrada) -> None:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives.serialization import pkcs12
    from cryptography.x509.oid import NameOID
    from datetime import timedelta

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    nome = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "SEM DOCUMENTO LTDA")])
    agora = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(nome).issuer_name(nome).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(agora - timedelta(days=1))
            .not_valid_after(agora + timedelta(days=90)).sign(key, hashes.SHA256()))
    pfx = pkcs12.serialize_key_and_certificates(b"t", key, cert, None, serialization.BestAvailableEncryption(b"1"))
    (pastas.pasta_entrada / "semdoc senha 1.pfx").write_bytes(pfx)
    r = ag.processar_entrada(pastas)
    assert _nomes(pastas.pasta_entrada) == ["semdoc senha 1.pfx"]
    assert "CNPJ nem CPF" in r["pendentes"][0]["motivo"]


def test_pasta_de_entrada_inexistente_nao_derruba_nada(pastas: ag.ConfigEntrada) -> None:
    pastas.pasta_entrada.rmdir()
    assert ag.processar_entrada(pastas) == {"eventos": [], "pendentes": []}


def test_config_de_exige_as_tres_pastas(tmp_path: Path) -> None:
    assert ag.config_de({}, {}, tmp_path) is None, "sem entrada, sem passo"
    assert ag.config_de({"pasta_entrada": "E:/In"}, {}, tmp_path) is None, "falta PJ/PF"
    cfg = ag.config_de({"pasta_entrada": "E:/In"}, {"pasta_pj": "E:/PJ", "pasta_pf": "E:/PF"}, tmp_path)
    assert cfg and cfg.pasta_pj == Path("E:/PJ") and cfg.pasta_vencidos == tmp_path, "portal primeiro, local depois"
    cfg2 = ag.config_de({"pasta_entrada": "", "pasta_pj": "P:/x"}, {"pasta_entrada": "L:/In", "pasta_pf": "L:/PF"}, tmp_path)
    assert cfg2 and cfg2.pasta_entrada == Path("L:/In") and cfg2.pasta_pj == Path("P:/x")


def test_agente_processa_a_entrada_antes_da_varredura_e_fora_dela() -> None:
    """F6/G4: o novo entra no inventário já no lugar; pendente nunca entra."""
    fonte = (RAIZ / "agent" / "run_agent.py").read_text(encoding="utf-8")
    i_proc = fonte.index("entrada_certificados.processar_entrada(cfg_entrada)")
    i_scan = fonte.index("itens = scan_folder(src, recursive=True, exclude_dirs=exclude_dirs)")
    assert i_proc < i_scan
    assert "exclude_dirs.append(cfg_entrada.pasta_entrada)" in fonte
    assert "/api/agent/entrada" in fonte and "observer_entrada" in fonte
    import agent
    from app import config
    assert agent.__version__ == "1.6.0" == config.VERSAO_AGENTE_ESPERADA
    exemplo = (RAIZ / "agent" / "agent_config.example.json").read_text(encoding="utf-8")
    assert "pasta_entrada" in exemplo


# ══════════════════════════════════════════════════════════════════════════
# 3. O portal: relatório do agente, pendentes, e-mail, tela (F3, F6)
# ══════════════════════════════════════════════════════════════════════════

class _Smtp:
    smtp_alerts_enabled = True
    smtp_host = "smtp.x.test"
    smtp_port = 587
    smtp_user = "u"
    smtp_password_encrypted = "x"
    smtp_use_tls = True
    smtp_use_ssl = False
    smtp_from_email = "portal@x.test"
    alertas_destinatarios = ""
    pasta_entrada = "D:/Certs/Entrada"
    alertas_novos_enabled = True
    alertas_novos_modo = ""


@pytest.fixture
def banco(banco_base: _Fake, monkeypatch: pytest.MonkeyPatch) -> _Fake:
    banco_base.tabelas["carteira_excecao"] = []
    banco_base.tabelas["entrada_eventos"] = []
    banco_base.tabelas["novos_pendentes"] = []
    banco_base.tabelas["portal_settings"] = []
    monkeypatch.setattr(pe, "_banco", lambda: banco_base)
    monkeypatch.setattr(nc, "_banco", lambda: banco_base)
    return banco_base


@pytest.fixture
def correio(monkeypatch: pytest.MonkeyPatch) -> List[Dict[str, Any]]:
    enviados: List[Dict[str, Any]] = []
    monkeypatch.setattr(pe, "load_settings", lambda: _Smtp())
    monkeypatch.setattr(pe, "send_smtp_email", lambda **kw: enviados.append(kw))
    return enviados


def _ev(resultado: str, original: str, **extra: Any) -> Dict[str, Any]:
    return {"resultado": resultado, "arquivo_original": original, "arquivo_novo": extra.pop("novo", ""),
            "pasta_destino": "D:/PJ/A", "motivo": extra.pop("motivo", ""), "nome": "ALFA LTDA",
            "documento_numero": CNPJ, "documento_tipo": "cnpj", "fingerprint_sha256": "f" * 64,
            "not_after": "2027-01-01T00:00:00+00:00", "quando": "2026-10-02T12:00:00+00:00", **extra}


def test_relatorio_grava_eventos_e_avisa_so_dos_pendentes_novos(client: TestClient, banco: _Fake, correio) -> None:
    corpo = {"machine_id": "srv", "eventos": [_ev("movido", "alfa.pfx", novo="ALFA LTDA 12345678000199.pfx")],
             "pendentes": [_ev("pendente", "lixo.pfx", motivo="Senha incorreta")]}
    r = client.post("/api/agent/entrada", headers=_h(*ADMIN), json=corpo)
    assert r.status_code == 200, r.text
    assert r.json()["eventos"] == 1 and r.json()["novos_pendentes"] == 1
    assert len(correio) == 1 and correio[0]["to_email"] == "admin@x.com", "F3: administradores"
    assert "lixo.pfx" in correio[0]["html_content"] and "Senha incorreta" in correio[0]["html_content"]
    assert "pendente" in correio[0]["subject"]

    # Mesmo pendente no ciclo seguinte: nada de novo, nenhum e-mail.
    r = client.post("/api/agent/entrada", headers=_h(*ADMIN), json={**corpo, "eventos": []})
    assert r.json()["novos_pendentes"] == 0 and len(correio) == 1
    assert len([x for x in banco.tabelas["entrada_eventos"] if x["resultado"] == "pendente"]) == 1

    # O arquivo saiu da pasta: o pendente fecha.
    r = client.post("/api/agent/entrada", headers=_h(*ADMIN), json={"machine_id": "srv", "eventos": [], "pendentes": []})
    assert r.json()["resolvidos"] == 1
    pend = [x for x in banco.tabelas["entrada_eventos"] if x["resultado"] == "pendente"]
    assert pend[0]["resolvido_em"]

    lista = client.get("/api/cert-installer/entrada", headers=_h(*ADMIN)).json()
    assert lista["pendentes"] == [] and len(lista["eventos"]) == 1
    assert lista["eventos"][0]["resultado_rotulo"] == "Renomeado e movido"


def test_relatorio_recusa_resultado_desconhecido_e_a_tela_e_so_do_administrador(client: TestClient, banco: _Fake, correio) -> None:
    r = client.post("/api/agent/entrada", headers=_h(*ADMIN), json={"machine_id": "srv", "eventos": [_ev("apagado", "x.pfx")], "pendentes": []})
    assert r.status_code == 200 and r.json()["eventos"] == 0
    assert client.get("/api/cert-installer/entrada", headers=_h(*GESTOR)).status_code == 403
    assert client.post("/api/agent/entrada", headers=_h(*GESTOR), json={"eventos": [], "pendentes": []}).status_code == 403


def test_sem_smtp_o_pendente_fica_registrado_mas_nao_sai_email(client: TestClient, banco: _Fake, monkeypatch: pytest.MonkeyPatch) -> None:
    desligado = _Smtp()
    desligado.smtp_alerts_enabled = False
    monkeypatch.setattr(pe, "load_settings", lambda: desligado)
    enviados: list = []
    monkeypatch.setattr(pe, "send_smtp_email", lambda **kw: enviados.append(kw))
    r = client.post("/api/agent/entrada", headers=_h(*ADMIN), json={"machine_id": "srv", "eventos": [], "pendentes": [_ev("pendente", "x.pfx")]})
    assert r.json()["novos_pendentes"] == 1 and r.json()["email"]["alerts_disabled"] is True
    assert enviados == []


def test_lista_fixa_de_destinatarios_substitui_os_administradores(client: TestClient, banco: _Fake, monkeypatch: pytest.MonkeyPatch) -> None:
    fixo = _Smtp()
    fixo.alertas_destinatarios = "ti@x.com, chefe@x.com"
    monkeypatch.setattr(pe, "load_settings", lambda: fixo)
    enviados: list = []
    monkeypatch.setattr(pe, "send_smtp_email", lambda **kw: enviados.append(kw))
    client.post("/api/agent/entrada", headers=_h(*ADMIN), json={"machine_id": "srv", "eventos": [], "pendentes": [_ev("pendente", "x.pfx")]})
    assert sorted(e["to_email"] for e in enviados) == ["chefe@x.com", "ti@x.com"]


def test_tela_do_instalador_tem_a_aba_movimentos(client: TestClient, banco: _Fake) -> None:
    html = (RAIZ / "templates" / "instalador.html").read_text(encoding="utf-8")
    assert 'id="tab-movimentos"' in html and 'id="aba-movimentos"' in html
    assert 'id="tab-entrada"' not in html, "Q3: a aba Entrada virou Movimentos"
    assert '"movimentos"' in html[html.index("const ABAS"):html.index("const ABAS") + 120]
    assert "/api/cert-installer/entrada" in html and "loadEntrada()" in html
    assert "entradaPendentesAviso" in html, "pendências em destaque"
    assert "vencido_preso" in html and "pasta_origem" in html
    fonte = (RAIZ / "app" / "main.py").read_text(encoding="utf-8")
    assert '"custodia", "movimentos", "trilha"' in fonte
    # O link antigo continua abrindo a aba.
    r = client.get("/instalador?aba=entrada", headers=_h(*ADMIN))
    assert r.status_code == 200 and 'id="tab-movimentos" href="?aba=movimentos" aria-controls="aba-movimentos" data-aba="movimentos"\n         aria-selected="true"' in r.text


def test_tela_de_configuracao_tem_as_pastas_e_a_chave_do_aviso() -> None:
    html = (RAIZ / "templates" / "configuracao.html").read_text(encoding="utf-8")
    for campo in ("inp-entrada", "inp-pasta-pj", "inp-pasta-pf", "chk-alertas-novos", "sel-alertas-novos-modo"):
        assert f'id="{campo}"' in html, campo
    assert "Avisar quando chegar certificado novo" in html, "G4"
    assert "A cada hora cheia (padrão)" in html
    assert "...corpoEntrada()" in html and "corpoEntrada() {" in html
    assert "poll_commands: true, ...corpoEntrada()" in html, "o agent_config.json baixado leva as pastas"


# ══════════════════════════════════════════════════════════════════════════
# 4. Configuração: campos, validação, preservação (G1, G2, G4)
# ══════════════════════════════════════════════════════════════════════════

def test_settings_devolve_e_valida_as_pastas_da_entrada(client: TestClient, banco: _Fake, tmp_path: Path) -> None:
    base = m.SettingsBody().model_dump()
    s = client.get("/api/settings", headers=_h(*ADMIN)).json()
    assert s["pasta_entrada"] == "" and s["alertas_novos_enabled"] is True and s["alertas_novos_modo_efetivo"] == "hora"

    r = client.put("/api/settings", headers=_h(*ADMIN), json={**base, "pasta_entrada": str(tmp_path / "In")})
    assert r.status_code == 422 and "pessoa jurídica" in r.json()["detail"], r.text

    r = client.put("/api/settings", headers=_h(*ADMIN), json={**base, "pasta_entrada": r"\\servidor\share", "pasta_pj": str(tmp_path / "PJ"), "pasta_pf": str(tmp_path / "PF")})
    assert r.status_code == 422 and "UNC" in r.json()["detail"]

    r = client.put("/api/settings", headers=_h(*ADMIN), json={**base, "pasta_entrada": str(tmp_path / "PJ"), "pasta_pj": str(tmp_path / "PJ"), "pasta_pf": str(tmp_path / "PF")})
    assert r.status_code == 422 and "mesma pasta" in r.json()["detail"]

    r = client.put("/api/settings", headers=_h(*ADMIN), json={**base, "alertas_novos_modo": "semanal"})
    assert r.status_code == 422

    r = client.put("/api/settings", headers=_h(*ADMIN), json={
        **base, "pasta_entrada": str(tmp_path / "In"), "pasta_pj": str(tmp_path / "PJ"), "pasta_pf": str(tmp_path / "PF"),
        "alertas_novos_enabled": False, "alertas_novos_modo": "imediato",
    })
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["pasta_entrada"].endswith("In") and j["alertas_novos_enabled"] is False and j["alertas_novos_modo"] == "imediato"

    # Outro formulário salva sem mandar os campos: `None` preserva.
    r = client.put("/api/settings", headers=_h(*ADMIN), json=base)
    assert r.status_code == 200
    j = r.json()
    assert j["pasta_entrada"].endswith("In") and j["alertas_novos_enabled"] is False and j["alertas_novos_modo"] == "imediato"


def test_migration_da_entrada_existe() -> None:
    sql = (RAIZ / "supabase" / "migrations" / "20261002120000_entrada_de_certificados.sql").read_text(encoding="utf-8")
    for coluna in ("pasta_entrada", "pasta_pj", "pasta_pf", "alertas_novos_enabled", "alertas_novos_modo"):
        assert re.search(rf"ADD COLUMN IF NOT EXISTS {coluna}\b", sql), coluna
    assert "CREATE TABLE IF NOT EXISTS public.entrada_eventos" in sql
    assert "CREATE TABLE IF NOT EXISTS public.novos_pendentes" in sql
    assert "resolvido_em" in sql


# ══════════════════════════════════════════════════════════════════════════
# 5. Aviso de certificado novo por hora cheia (G4)
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("agora, segundos", [
    (datetime(2026, 10, 2, 9, 7, 0, tzinfo=timezone.utc), 53 * 60),
    (datetime(2026, 10, 2, 9, 59, 59, tzinfo=timezone.utc), 1),
    (datetime(2026, 10, 2, 10, 0, 0, tzinfo=timezone.utc), 3600),
])
def test_dorme_ate_a_proxima_hora_cheia(agora: datetime, segundos: int) -> None:
    assert nc.segundos_ate_a_proxima_hora_cheia(agora) == segundos


def _item(nome: str, fp: str) -> Dict[str, Any]:
    return {"nome": nome, "fingerprint_sha256": fp, "documento_numero": CNPJ, "not_after": "2027-01-01T00:00:00+00:00"}


@pytest.fixture
def fila(banco: _Fake, monkeypatch: pytest.MonkeyPatch):
    avisados: List[List[Dict[str, Any]]] = []
    cfg = _Smtp()
    monkeypatch.setattr(nc, "load_settings", lambda: cfg)
    monkeypatch.setattr(nc, "notificar_novos", lambda itens: (avisados.append(list(itens)), {"certificados": len(itens)})[1])
    return avisados, cfg, banco


def test_por_hora_os_novos_esperam_e_saem_juntos(fila) -> None:
    avisados, cfg, banco = fila
    r1 = nc.agendar_ou_notificar([_item("A", "fa")])
    r2 = nc.agendar_ou_notificar([_item("B", "fb"), _item("A", "fa")])
    assert r1["guardados"] == 1 and r2["guardados"] == 2
    assert avisados == [], "nada sai antes da hora"
    assert len(banco.tabelas["novos_pendentes"]) == 2, "o mesmo certificado duas vezes é uma linha"

    stats = nc.enviar_novos_pendentes()
    assert stats["certificados"] == 2
    assert sorted(it["nome"] for it in avisados[0]) == ["A", "B"], "um lote só"
    assert banco.tabelas["novos_pendentes"] == [], "a fila esvazia"
    assert nc.enviar_novos_pendentes() == {"certificados": 0} and len(avisados) == 1


def test_imediato_avisa_na_hora_e_desligado_nao_avisa(fila) -> None:
    avisados, cfg, banco = fila
    cfg.alertas_novos_modo = "imediato"
    nc.agendar_ou_notificar([_item("A", "fa")])
    assert len(avisados) == 1 and banco.tabelas["novos_pendentes"] == []

    cfg.alertas_novos_enabled = False
    r = nc.agendar_ou_notificar([_item("B", "fb")])
    assert r["alerts_disabled"] is True and len(avisados) == 1 and banco.tabelas["novos_pendentes"] == []


def test_sem_a_tabela_da_fila_o_aviso_sai_de_imediato(fila) -> None:
    avisados, cfg, banco = fila
    banco.quebrado["novos_pendentes"] = True
    r = nc.agendar_ou_notificar([_item("A", "fa")])
    assert r["guardados"] == 0 and len(avisados) == 1, "migration por rodar não pode engolir o aviso"


def test_sem_banco_a_fila_vive_em_memoria(monkeypatch: pytest.MonkeyPatch) -> None:
    avisados: list = []
    monkeypatch.setattr(nc, "_banco", lambda: None)
    monkeypatch.setattr(nc, "load_settings", lambda: _Smtp())
    monkeypatch.setattr(nc, "notificar_novos", lambda itens: (avisados.append(list(itens)), {"certificados": len(itens)})[1])
    nc._pendentes_memoria.clear()
    nc.agendar_ou_notificar([_item("A", "fa")])
    assert avisados == [] and len(nc._pendentes_memoria) == 1
    nc.enviar_novos_pendentes()
    assert len(avisados) == 1 and nc._pendentes_memoria == []


def test_ingest_usa_o_agendamento_e_o_lifespan_tem_o_laco_da_hora() -> None:
    fonte = (RAIZ / "app" / "main.py").read_text(encoding="utf-8")
    assert "background_tasks.add_task(agendar_ou_notificar, novos)" in fonte
    assert "background_tasks.add_task(notificar_novos, novos)" not in fonte
    assert "segundos_ate_a_proxima_hora_cheia()" in fonte and "enviar_novos_pendentes" in fonte
    assert alertas_config.modo_novos_efetivo("") == "hora" and alertas_config.modo_novos_efetivo("IMEDIATO") == "imediato"


# ══════════════════════════════════════════════════════════════════════════
# 6. Segunda rodada: vencidos do acervo, Movimentos, sufixo, instalador
# ══════════════════════════════════════════════════════════════════════════

def test_sufixo_de_colisao_e_o_mesmo_em_todo_lugar(tmp_path: Path) -> None:
    """Q6: `(2)`, `(3)`… no lugar de `_dup_<carimbo>`; o nome continua abrindo."""
    from app import cert_scanner as cs
    venc = tmp_path / "Vencidos"
    venc.mkdir()
    (venc / "ALFA 1 senha x.pfx").write_bytes(b"a")
    (venc / "ALFA 1 (2) senha x.pfx").write_bytes(b"b")
    (venc / "sem padrao.p12").write_bytes(b"c")
    assert cs.destino_livre(venc, "ALFA 1 senha x.pfx").name == "ALFA 1 (3) senha x.pfx"
    assert cs.destino_livre(venc, "NOVO senha y.pfx").name == "NOVO senha y.pfx"
    assert cs.destino_livre(venc, "sem padrao.p12").name == "sem padrao (2).p12"
    fonte = (RAIZ / "app" / "cert_scanner.py").read_text(encoding="utf-8")
    assert "_dup_{" not in fonte, "o carimbo saiu do código; só a docstring o cita"

    origem = tmp_path / "B"
    origem.mkdir()
    _pfx(origem, "ALFA 1 senha x.pfx", cnpj=CNPJ, senha="x", nome="ALFA", dias=-1)
    (c,) = scan_folder(origem, recursive=False)
    dest = cs.move_to_expired(c, venc)
    assert dest.name == "ALFA 1 (3) senha x.pfx" and not (origem / "ALFA 1 senha x.pfx").exists()


def test_varredura_tira_os_vencidos_das_letras_e_registra_a_origem(tmp_path: Path) -> None:
    """Q1/Q3: o vencido na pasta da letra vai para Vencidos (plana, Q2) e vira
    evento `vencido` com `pasta_origem`; o vigente fica."""
    src = tmp_path / "CERTIFICADOS"
    pj_b = src / "02.PESSOA JURIDICA" / "B"
    pj_b.mkdir(parents=True)
    venc = src / "VENCIDOS"
    _pfx(pj_b, "BETA VENCIDO 1 senha a.pfx", cnpj=CNPJ, senha="a", nome="BETA", dias=-5)
    _pfx(pj_b, "BETA VIGENTE 2 senha b.pfx", cnpj=CNPJ_2, senha="b", nome="BETA 2")
    r = ag.mover_vencidos_do_acervo(src, venc, [venc])
    assert _nomes(pj_b) == ["BETA VIGENTE 2 senha b.pfx"]
    assert _nomes(venc) == ["BETA VENCIDO 1 senha a.pfx"], "Q2: plana, sem letra"
    (ev,) = r["eventos"]
    assert ev["resultado"] == "vencido" and ev["pasta_origem"] == str(pj_b) and ev["pasta_destino"] == str(venc)
    assert ev["nome"] == "BETA" and ev["documento_numero"] == CNPJ
    assert r["pendentes"] == []
    # Nada vencido: nada a reportar, e a função não cria a pasta de vencidos à toa.
    assert ag.mover_vencidos_do_acervo(src, venc, [venc]) == {"eventos": [], "pendentes": []}


def test_vencido_que_nao_sai_vira_pendencia_depois_de_duas_tentativas(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Q1 (garantia) e Q4: nova tentativa no mesmo ciclo; se ficar, `vencido_preso` com motivo."""
    src = tmp_path / "CERTIFICADOS"
    pj_a = src / "02.PESSOA JURIDICA" / "A"
    pj_a.mkdir(parents=True)
    venc = src / "VENCIDOS"
    _pfx(pj_a, "ALFA 1 senha a.pfx", cnpj=CNPJ, senha="a", nome="ALFA", dias=-5)
    tentativas: List[str] = []

    def preso(cert, exp):
        tentativas.append(cert.file_name)
        raise OSError(32, "O arquivo está sendo usado por outro processo")

    monkeypatch.setattr(ag, "move_to_expired", preso)
    monkeypatch.setattr(ag.time, "sleep", lambda s: None)
    r = ag.mover_vencidos_do_acervo(src, venc, [venc])
    assert tentativas == ["ALFA 1 senha a.pfx"] * 2, "duas tentativas no mesmo ciclo"
    assert r["eventos"] == []
    (p,) = r["pendentes"]
    assert p["resultado"] == "vencido_preso" and p["pasta_origem"] == str(pj_a)
    assert "sendo usado" in p["motivo"] and "senha" not in p["arquivo_original"].lower()
    assert _nomes(pj_a) == ["ALFA 1 senha a.pfx"], "o arquivo fica onde está, nada se perde"


def test_agente_junta_entrada_e_vencidos_num_relatorio_so() -> None:
    fonte = (RAIZ / "agent" / "run_agent.py").read_text(encoding="utf-8")
    assert "entrada_certificados.mover_vencidos_do_acervo(src, exp, exclude_dirs)" in fonte
    assert "if cfg_entrada or mover:" in fonte, "o relatório vai sempre que houver o que reconciliar"
    assert "_enviar_relatorio_de_movimentos(" in fonte
    assert "move_to_expired(c, exp)" not in fonte, "o laço antigo saiu; o movimento passa pelo módulo que registra"
    assert ag.juntar({"eventos": [1], "pendentes": []}, None, {"eventos": [2], "pendentes": [3]}) == {"eventos": [1, 2], "pendentes": [3]}


def test_vencido_preso_e_pendencia_no_portal_com_email_e_fecha_quando_sai(client: TestClient, banco: _Fake, correio) -> None:
    preso = _ev("vencido_preso", "ALFA 1", motivo="Vencido e ainda na pasta: em uso.", pasta_origem=r"D:/PJ/A")
    r = client.post("/api/agent/entrada", headers=_h(*ADMIN), json={"machine_id": "srv", "eventos": [], "pendentes": [preso]})
    assert r.status_code == 200 and r.json()["novos_pendentes"] == 1
    assert len(correio) == 1
    assert "Vencido não movido" in correio[0]["html_content"] and "D:/PJ/A" in correio[0]["html_content"]
    assert "Movimentos" in correio[0]["html_content"]

    # O mesmo nome, pendente também na entrada: é OUTRA pendência (pasta diferente).
    na_entrada = _ev("pendente", "ALFA 1", motivo="Senha incorreta", pasta_origem=r"D:/Entrada")
    r = client.post("/api/agent/entrada", headers=_h(*ADMIN), json={"machine_id": "srv", "eventos": [], "pendentes": [preso, na_entrada]})
    assert r.json()["novos_pendentes"] == 1 and len(correio) == 2

    lista = client.get("/api/cert-installer/entrada", headers=_h(*ADMIN)).json()
    assert sorted(p["resultado"] for p in lista["pendentes"]) == ["pendente", "vencido_preso"]
    assert {p["resultado_rotulo"] for p in lista["pendentes"]} == {"Pendente na entrada", "Vencido não movido"}

    # Saiu da pasta da letra (movido na varredura seguinte): a pendência fecha e o movimento entra.
    movido = _ev("vencido", "ALFA 1", novo="ALFA 1", pasta_origem=r"D:/PJ/A", motivo="Vencido; movido na varredura.")
    r = client.post("/api/agent/entrada", headers=_h(*ADMIN), json={"machine_id": "srv", "eventos": [movido], "pendentes": [na_entrada]})
    assert r.json()["resolvidos"] == 1 and r.json()["eventos"] == 1
    lista = client.get("/api/cert-installer/entrada", headers=_h(*ADMIN)).json()
    assert [p["resultado"] for p in lista["pendentes"]] == ["pendente"]
    assert lista["eventos"][0]["resultado"] == "vencido" and lista["eventos"][0]["pasta_origem"] == r"D:/PJ/A"


def test_migration_da_pasta_de_origem_existe() -> None:
    sql = (RAIZ / "supabase" / "migrations" / "20261002160000_movimentos_pasta_origem.sql").read_text(encoding="utf-8")
    assert "ADD COLUMN IF NOT EXISTS pasta_origem" in sql
    assert "'vencido_preso'" in sql


def test_instalador_solta_arquivos_presos_e_tira_o_event_log_de_internal() -> None:
    """Q7: causa confirmada no ANALISESRV (EventMessageFile apontava para
    _internal\\win32\\servicemanager.pyd). Apagar → renomear → reinício, e a
    origem de eventos passa a uma cópia estável."""
    iss = (RAIZ / "agent_setup.iss").read_text(encoding="utf-8", errors="replace")
    assert "AppVersion=1.6.0" in iss
    assert "procedure LiberarArquivosPresos" in iss and "RenameFile(Caminho, Caminho + '.old-'" in iss
    assert "LiberarArquivosPresos(ExpandConstant('{app}\\_internal'))" in iss
    assert iss.count("restartreplace") >= 2 and "uninsrestartdelete" in iss
    assert "procedure RegistrarOrigemDeEventos" in iss and "'EventMessageFile', Dest" in iss
    assert "{app}\\eventlog" in iss and "procedure RemoverOrigemDeEventos" in iss
    i_prep = iss.index("LiberarArquivosPresos(ExpandConstant('{app}\\_internal'))")
    i_fn = iss.index("function PrepararAmbienteParaInstalar")
    assert i_fn < i_prep, "a liberação roda dentro do preparo, antes da cópia"
    i_post = iss.index("if CurStep = ssPostInstall then")
    assert iss.index("RegistrarOrigemDeEventos;", i_post) < iss.index("InstallOrUpdateService", i_post), "antes do serviço subir"
