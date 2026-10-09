"""Certificados novos na pasta: sino, filtro, navegação e e-mail (30/09/2026).

O sino só falava de vencimento. O pedido: mostrar também o que foi ADICIONADO
há pouco, com um filtro "Todos / Novos / Expirando / Vencidos"; o cartão do
vencido leva a /vencidos já filtrado; o do novo leva ao Início filtrado; e um
e-mail avisa quem tem o certificado na carteira (e os administradores) que
ele apareceu na pasta.

"Novo" é o certificado cujo `arquivo_chave` nunca esteve em `cert_history`
antes desta ingestão. A data em que apareceu fica em
`cert_history.primeira_data_registrada` (supabase/migrations/20260930140000), coluna
que o upsert NUNCA envia: o banco a preenche na inserção e a preserva na
atualização. Linhas anteriores à migration ficam com NULL — "não sei quando
apareceu" não é "apareceu agora".
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List

import pytest
from fastapi.testclient import TestClient

import app.cert_installer as ci
import app.main as m
import app.notification_service as ns
import app.novos_certificados as nc
import app.settings_state as ss
from app import config
from app.nome_publico import chave_de_arquivo
from tests.test_seguranca_lote1 import _Fake, _usuario
from tests.test_seguranca_lote3 import ADMIN, _h

ROOT = Path(__file__).resolve().parent.parent
UI = (ROOT / "static" / "ui-common.js").read_text(encoding="utf-8")
CSS = (ROOT / "static" / "style.css").read_text(encoding="utf-8")
INDEX = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")

DOC_A = "12345678000199"
DOC_B = "98765432000188"


def _item(nome: str, fp: str, doc: str = "", dias: int = 200) -> Dict[str, Any]:
    """Item já sanitizado, como o `/api/ingest` entrega ao histórico.

    Sem `doc`, cada fingerprint vira um Cliente diferente: desde A1
    (01/10/2026) o sino avisa um certificado por Cliente, o vigente, e itens
    do mesmo documento se agrupariam — o que estes testes não querem medir.
    """
    import zlib
    doc = doc or str(zlib.crc32(fp.encode("utf-8"))).rjust(14, "7")[:14]
    venc = datetime.now(timezone.utc) + timedelta(days=dias)
    return {
        "nome": nome,
        "display_name": nome,
        "nome_publico": f"{nome}_{doc}.pfx",
        # A mesma chave que o sanitizador calcula: o histórico a recalcula.
        "arquivo_chave": chave_de_arquivo(f"{nome}_{doc}.pfx", fp),
        "fingerprint_sha256": fp,
        "documento_numero": doc,
        "documento_formatado": doc,
        "not_after": venc.isoformat(),
        "status": "valido",
    }


# ══════════════════════════════════════════════════════════════════════════
# 1. O histórico diz o que é novo
# ══════════════════════════════════════════════════════════════════════════


@pytest.fixture
def historico(monkeypatch: pytest.MonkeyPatch) -> _Fake:
    fake = _Fake({"cert_history": []})
    monkeypatch.setattr(ss, "_banco", lambda: fake)
    return fake


def test_upsert_devolve_so_os_que_nao_estavam_no_historico(historico: _Fake) -> None:
    antigo = _item("ALFA", "fp-a")
    historico.tabelas["cert_history"].append({"arquivo_chave": antigo["arquivo_chave"], "nome_publico": "x"})
    novo = _item("BETA", "fp-b", DOC_B)

    novos = ss.upsert_cert_history("srv", "2026-09-30T10:00:00+00:00", [antigo, novo])

    assert [n["arquivo_chave"] for n in novos] == [novo["arquivo_chave"]]
    assert len(historico.tabelas["cert_history"]) == 2


def test_upsert_nao_envia_a_primeira_data_o_banco_e_quem_preenche(historico: _Fake) -> None:
    """Se o upsert mandasse a coluna, cada ingestão diária a sobrescreveria e
    todo certificado seria "novo" para sempre."""
    ss.upsert_cert_history("srv", "2026-09-30T10:00:00+00:00", [_item("ALFA", "fp-a")])
    gravadas = [linha for tabela, linha in historico.gravados if tabela == "cert_history"]
    assert gravadas and all("primeira_data_registrada" not in linha for linha in gravadas)


def test_reingestao_do_mesmo_item_nao_e_novo(historico: _Fake) -> None:
    it = _item("ALFA", "fp-a")
    assert ss.upsert_cert_history("srv", "2026-09-30T10:00:00+00:00", [it])
    assert ss.upsert_cert_history("srv", "2026-10-01T10:00:00+00:00", [it]) == []


def test_carga_inicial_nao_vira_avalanche_de_novos(historico: _Fake) -> None:
    """Histórico vazio recebendo a pasta inteira: é a primeira carga (ou o
    histórico foi recriado), não 500 certificados novos num dia."""
    itens = [_item(f"C{i}", f"fp-{i}") for i in range(ss.NOVOS_LIMIAR_CARGA_INICIAL + 1)]
    assert ss.upsert_cert_history("srv", "2026-09-30T10:00:00+00:00", itens) == []
    assert len(historico.tabelas["cert_history"]) == len(itens)


def test_sem_banco_nao_ha_novos(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ss, "_banco", lambda: None)
    assert ss.upsert_cert_history("srv", "2026-09-30T10:00:00+00:00", [_item("ALFA", "fp-a")]) == []


def test_chaves_recentes_ignoram_a_coluna_ausente(monkeypatch: pytest.MonkeyPatch) -> None:
    """Antes da migration a consulta falha; o sino continua funcionando sem a
    seção Novos, em vez de derrubar o painel inteiro."""
    fake = _Fake({"cert_history": []})
    fake.quebrado["cert_history"] = True
    monkeypatch.setattr(ss, "_banco", lambda: fake)
    assert ss.chaves_registradas_recentemente(7) == {}


def test_chaves_recentes_devolve_a_data_por_chave(historico: _Fake) -> None:
    agora = datetime.now(timezone.utc)
    historico.tabelas["cert_history"].extend([
        {"arquivo_chave": "recente", "primeira_data_registrada": (agora - timedelta(days=1)).isoformat()},
        {"arquivo_chave": "velho", "primeira_data_registrada": (agora - timedelta(days=40)).isoformat()},
        {"arquivo_chave": "anterior-a-migration", "primeira_data_registrada": None},
    ])
    recentes = ss.chaves_registradas_recentemente(7)
    assert set(recentes) == {"recente"}


def test_chaves_recentes_comparam_instantes_e_nao_texto(historico: _Fake) -> None:
    """O banco devolve o horário no fuso da sessão (-03:00) e o limite está em
    UTC. Um registro de 6 dias e 23 h atrás, escrito em -03:00, fica com o
    texto "menor" que o limite e sumia da janela na comparação de strings."""
    agora = datetime.now(timezone.utc)
    dentro = (agora - timedelta(days=6, hours=23)).astimezone(timezone(timedelta(hours=-3)))
    fora = (agora - timedelta(days=7, hours=1)).astimezone(timezone(timedelta(hours=-3)))
    linhas = [
        {"arquivo_chave": "dentro", "primeira_data_registrada": dentro},
        {"arquivo_chave": "fora", "primeira_data_registrada": fora},
        {"arquivo_chave": "texto-z", "primeira_data_registrada": (agora - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")},
    ]

    # O Postgres compara instantes e devolve as linhas com datetime no fuso da
    # sessão; a base falsa compara texto (o defeito), então aqui o cliente é
    # mínimo e devolve tudo — quem tem de filtrar certo é o código.
    class _Q:
        def select(self, *_a, **_k): return self
        def gte(self, *_a, **_k): return self
        def execute(self):
            return type("R", (), {"data": [dict(l) for l in linhas]})()

    class _C:
        def table(self, _n): return _Q()

    import app.settings_state as ss_mod
    original = ss_mod._banco
    ss_mod._banco = lambda: _C()
    try:
        assert set(ss.chaves_registradas_recentemente(7)) == {"dentro", "texto-z"}
    finally:
        ss_mod._banco = original


def test_copia_ou_renomeacao_nao_e_certificado_novo() -> None:
    """A chave do histórico é nome do arquivo + fingerprint: copiar o PFX
    para a pasta Copias cria chave nova para o mesmo certificado."""
    copia = _item("ALFA", "fp-a")
    copia["nome_publico"] = "ALFA (2).pfx"
    inedito = _item("BETA", "fp-b", DOC_B)
    ilegivel = {"nome_publico": "x.pfx", "arquivo_chave": "k", "fingerprint_sha256": ""}
    conhecidos = nc.fingerprints_do_snapshot({"items": [_item("ALFA", "FP-A")]})
    assert conhecidos == {"fp-a"}
    assert [n["nome"] for n in nc.filtrar_ineditos([copia, inedito], conhecidos)] == ["BETA"]
    assert nc.filtrar_ineditos([ilegivel], conhecidos) == [ilegivel], "sem fingerprint não há como saber: passa"
    assert nc.fingerprints_do_snapshot(None) == set()


# ══════════════════════════════════════════════════════════════════════════
# 2. O sino mostra os novos, com filtro e totais
# ══════════════════════════════════════════════════════════════════════════


class _Settings:
    alertas_marcos = ""


@pytest.fixture
def sino(monkeypatch: pytest.MonkeyPatch):
    """Sino com o snapshot e as datas de primeiro registro injetáveis."""
    recentes: Dict[str, str] = {}
    lidas: set = set()
    alcance: Dict[str, Any] = {"docs": None}

    monkeypatch.setattr(ns, "load_settings", lambda: _Settings())
    monkeypatch.setattr(ns, "get_latest_snapshot", lambda *a, **k: None)
    monkeypatch.setattr(ns, "carregar_notificacoes_lidas", lambda uid: set(lidas))
    monkeypatch.setattr(ns, "chaves_registradas_recentemente", lambda dias: dict(recentes))
    monkeypatch.setattr(ns, "load_colaborador_selecao", lambda email, uid=None: [])
    monkeypatch.setattr(ns, "documentos_ao_alcance", lambda uid, role: alcance["docs"])

    def _montar(itens: List[Dict[str, Any]], email="admin@x.com", papel="admin", uid="u-1"):
        monkeypatch.setattr("app.main._list_certificados_payload", lambda *a, **k: {"itens": itens})
        return ns.build_notifications_payload(email, papel, uid)

    return _montar, recentes, lidas, alcance


def _recente(recentes: Dict[str, str], it: Dict[str, Any], dias_atras: int = 1) -> None:
    recentes[it["arquivo_chave"]] = (datetime.now(timezone.utc) - timedelta(days=dias_atras)).isoformat()


def test_certificado_registrado_ha_pouco_vira_aviso_novo(sino) -> None:
    montar, recentes, _, _ = sino
    novo = _item("BETA", "fp-b", DOC_B)
    _recente(recentes, novo, 2)
    p = montar([_item("ALFA", "fp-a"), novo])

    novos = [a for a in p["itens"] if a["tipo"] == "novo"]
    assert [a["nome"] for a in novos] == ["BETA"]
    assert novos[0]["chave"] == "fp-b|novo"
    assert novos[0]["acionavel"] is True
    assert novos[0]["registrado_em"]
    assert p["total_novos"] == 1
    assert p["total_acionavel"] == 1, "o badge conta o novo"
    assert p["janela_novos_dias"] == ns.JANELA_NOVOS_DIAS


def test_novo_e_vencendo_sao_dois_avisos_do_mesmo_certificado(sino) -> None:
    """Chegou na pasta já com 10 dias de validade: é novo E está expirando.
    Marcar um como lido não pode esconder o outro."""
    montar, recentes, lidas, _ = sino
    it = _item("GAMA", "fp-g", dias=10)
    _recente(recentes, it)
    p = montar([it])
    tipos = sorted(a["tipo"] for a in p["itens"])
    assert tipos == ["expiring", "novo"]

    lidas.add("fp-g|novo")
    p = montar([it])
    assert [a["tipo"] for a in p["itens"]] == ["expiring"]


def test_novos_vem_antes_dos_vencimentos_e_do_mais_recente(sino) -> None:
    montar, recentes, _, _ = sino
    a = _item("ANTEONTEM", "fp-1")
    b = _item("ONTEM", "fp-2", DOC_B)
    _recente(recentes, a, 2)
    _recente(recentes, b, 1)
    p = montar([_item("VENCE LOGO", "fp-3", dias=5), a, b])
    assert [x["nome"] for x in p["itens"]] == ["ONTEM", "ANTEONTEM", "VENCE LOGO"]


def test_novo_em_dois_arquivos_e_um_aviso(sino) -> None:
    montar, recentes, _, _ = sino
    a = _item("ALFA", "fp-a")
    b = dict(a, nome_publico="ALFA (2).pfx", arquivo_chave=chave_de_arquivo("ALFA (2).pfx", "fp-a"))
    _recente(recentes, a)
    _recente(recentes, b)
    p = montar([a, b])
    assert p["total_novos"] == 1
    assert p["itens"][0]["ocorrencias"] == 2


def test_copia_de_certificado_antigo_nao_aparece_como_novo_no_sino(sino) -> None:
    montar, recentes, _, _ = sino
    antigo = _item("ALFA", "fp-a")
    copia = dict(antigo, nome_publico="ALFA (2).pfx", arquivo_chave=chave_de_arquivo("ALFA (2).pfx", "fp-a"))
    inedito = _item("BETA", "fp-b", DOC_B)
    _recente(recentes, copia)
    _recente(recentes, inedito)
    p = montar([antigo, copia, inedito])
    assert [a["nome"] for a in p["itens"] if a["tipo"] == "novo"] == ["BETA"]


def test_operador_so_ve_os_novos_da_sua_carteira(sino) -> None:
    montar, recentes, _, alcance = sino
    a = _item("ALFA", "fp-a", DOC_A)
    b = _item("BETA", "fp-b", DOC_B)
    _recente(recentes, a)
    _recente(recentes, b)
    alcance["docs"] = {DOC_B}
    p = montar([a, b], email="ana@x.com", papel="user", uid="u-ana")
    assert [x["nome"] for x in p["itens"]] == ["BETA"]


def test_operador_sem_carteira_legivel_nao_ve_novos_mas_o_sino_nao_cai(sino, monkeypatch) -> None:
    montar, recentes, _, _ = sino
    a = _item("ALFA", "fp-a")
    _recente(recentes, a)

    def _quebra(uid, role):
        raise ci.CarteiraIndisponivel("fora do ar")

    monkeypatch.setattr(ns, "documentos_ao_alcance", _quebra)
    p = montar([a], email="ana@x.com", papel="user", uid="u-ana")
    assert p["total_novos"] == 0


def test_filtro_por_tipo_recorta_a_lista_mas_nao_os_totais(sino) -> None:
    """O teto de 50 é sobre a lista devolvida: sem o recorte no servidor, o
    chip "Vencidos 72" abria vazio quando os 50 primeiros eram novos e
    expirando (achado da sonda de 30/09)."""
    montar, recentes, _, _ = sino
    novos = [_item(f"N{i}", f"fp-n{i}") for i in range(3)]
    for it in novos:
        _recente(recentes, it)
    expirando = [_item(f"E{i}", f"fp-e{i}", dias=5) for i in range(ns.NOTIF_MAX_ITENS)]
    vencidos = [_item(f"V{i}", f"fp-v{i}", dias=-3) for i in range(4)]
    itens = novos + expirando + vencidos

    p = montar(itens)
    assert p["total_vencidos"] == 4 and not [a for a in p["itens"] if a["tipo"] == "expired"]

    monkeypatch_payload = ns.build_notifications_payload("admin@x.com", "admin", "u-1", tipo="expired")
    assert [a["tipo"] for a in monkeypatch_payload["itens"]] == ["expired"] * 4
    assert monkeypatch_payload["tipo"] == "expired"
    assert monkeypatch_payload["truncado"] is False
    assert monkeypatch_payload["total_vencidos"] == 4 and monkeypatch_payload["total_novos"] == 3

    so_novos = ns.build_notifications_payload("admin@x.com", "admin", "u-1", tipo="novo")
    assert [a["tipo"] for a in so_novos["itens"]] == ["novo"] * 3

    invalido = ns.build_notifications_payload("admin@x.com", "admin", "u-1", tipo="qualquer")
    assert invalido["tipo"] is None and len(invalido["itens"]) == ns.NOTIF_MAX_ITENS


def test_rota_aceita_tipo_e_recusa_valor_estranho(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    visto: Dict[str, Any] = {}

    def _payload(email, papel, uid, tipo=None):
        visto["tipo"] = tipo
        return {"itens": [], "tipo": tipo}

    monkeypatch.setattr(m, "build_notifications_payload", _payload)
    assert client.get("/api/colaborador/notificacoes?tipo=expired", headers=_h(*ADMIN)).status_code == 200
    assert visto["tipo"] == "expired"
    assert client.get("/api/colaborador/notificacoes", headers=_h(*ADMIN)).status_code == 200
    assert visto["tipo"] is None
    assert client.get("/api/colaborador/notificacoes?tipo=xyz", headers=_h(*ADMIN)).status_code == 422


def test_li_todos_marca_o_novo_tambem(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    gravado: List[str] = []
    monkeypatch.setattr(m, "get_active_alerts", lambda *a, **k: [
        {"chave": "fp-b|novo", "tipo": "novo", "acionavel": True},
        {"chave": "fp-a|expired", "tipo": "expired", "acionavel": True},
    ])
    monkeypatch.setattr(m, "marcar_notificacoes_lidas", lambda uid, chaves: gravado.extend(chaves) or len(chaves))
    r = client.post("/api/colaborador/notificacoes/lidas", headers=_h(*ADMIN))
    assert r.status_code == 200, r.text
    assert "fp-b|novo" in gravado


# ══════════════════════════════════════════════════════════════════════════
# 3. O e-mail de certificado novo
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


@pytest.fixture
def correio(monkeypatch: pytest.MonkeyPatch):
    """SMTP falso, antispam em memória, usuários e carteiras controláveis."""
    enviados: List[Dict[str, Any]] = []
    ja: set = set()
    fake = _Fake({
        "users": [
            _usuario("u-adm", "admin@x.com", "admin"),
            _usuario("u-ana", "ana@x.com", "user"),
            _usuario("u-ges", "gestor@x.com", "gestor"),
            _usuario("u-off", "fora@x.com", "user", ativo=False),
        ],
        "carteira": [
            {"user_id": "u-ana", "documento": DOC_A},
            {"user_id": "u-off", "documento": DOC_A},
        ],
    })
    alcance: Dict[str, Any] = {"u-ges": {DOC_B}}
    monkeypatch.setattr(nc, "load_settings", lambda: _Smtp())
    monkeypatch.setattr(nc, "_banco", lambda: fake)
    monkeypatch.setattr(nc, "send_smtp_email", lambda **kw: enviados.append(kw))
    monkeypatch.setattr(nc, "_is_alert_already_sent", lambda fp, tipo, dest, val: (fp, tipo, dest) in ja)
    monkeypatch.setattr(nc, "_record_sent_alert", lambda fp, tipo, dest, val: ja.add((fp, tipo, dest)))
    monkeypatch.setattr(ci, "_banco", lambda: fake)
    monkeypatch.setattr(
        nc, "documentos_ao_alcance",
        lambda uid, role: None if role == "admin" else alcance.get(uid, ci.listar_carteira(uid)),
    )
    return enviados, ja, fake


def _para(enviados: List[Dict[str, Any]], email: str) -> List[Dict[str, Any]]:
    return [e for e in enviados if e["to_email"] == email]


def test_admin_recebe_todos_e_o_operador_so_o_da_sua_carteira(correio) -> None:
    enviados, _, _ = correio
    a = _item("ALFA LTDA", "fp-a", DOC_A)
    b = _item("BETA ME", "fp-b", DOC_B)

    out = nc.notificar_novos([a, b])

    assert out["enviados"] == 3
    adm = _para(enviados, "admin@x.com")
    assert len(adm) == 1 and "ALFA LTDA" in adm[0]["html_content"] and "BETA ME" in adm[0]["html_content"]
    assert "2" in adm[0]["subject"]
    ana = _para(enviados, "ana@x.com")
    assert len(ana) == 1 and "ALFA LTDA" in ana[0]["html_content"] and "BETA ME" not in ana[0]["html_content"]
    ges = _para(enviados, "gestor@x.com")
    assert len(ges) == 1 and "BETA ME" in ges[0]["html_content"] and "ALFA LTDA" not in ges[0]["html_content"]
    assert not _para(enviados, "fora@x.com"), "conta desativada não recebe"


def test_o_nome_do_arquivo_nao_entra_no_email(correio) -> None:
    """O nome do arquivo carrega a senha do PFX (SECURITY_AUDIT #2)."""
    enviados, _, _ = correio
    it = _item("ALFA LTDA", "fp-a", DOC_A)
    it["file_name"] = "ALFA LTDA_12345678000199 senha123.pfx"
    nc.notificar_novos([it])
    assert enviados and all("senha123" not in e["html_content"] for e in enviados)


def test_antispam_nao_repete_o_mesmo_certificado_para_a_mesma_pessoa(correio) -> None:
    enviados, _, _ = correio
    a = _item("ALFA LTDA", "fp-a", DOC_A)
    nc.notificar_novos([a])
    out = nc.notificar_novos([a])
    assert out["enviados"] == 0 and out["ignorados_ja_enviados"] >= 1
    assert len(_para(enviados, "admin@x.com")) == 1


def test_lista_fixa_de_destinatarios_substitui_os_admins(correio, monkeypatch) -> None:
    enviados, _, _ = correio
    s = _Smtp()
    s.alertas_destinatarios = "ti@x.test"
    monkeypatch.setattr(nc, "load_settings", lambda: s)
    nc.notificar_novos([_item("ALFA LTDA", "fp-a", DOC_A)])
    assert _para(enviados, "ti@x.test") and not _para(enviados, "admin@x.com")


def test_sem_smtp_ou_alertas_desligados_nada_sai(correio, monkeypatch) -> None:
    enviados, _, _ = correio
    s = _Smtp()
    s.smtp_alerts_enabled = False
    monkeypatch.setattr(nc, "load_settings", lambda: s)
    out = nc.notificar_novos([_item("ALFA LTDA", "fp-a", DOC_A)])
    assert out["enviados"] == 0 and out["alerts_disabled"] is True
    assert not enviados


def test_lista_vazia_nao_faz_nada(correio) -> None:
    enviados, _, _ = correio
    assert nc.notificar_novos([])["enviados"] == 0
    assert not enviados


def test_falha_de_smtp_num_destinatario_nao_impede_os_outros(correio, monkeypatch) -> None:
    enviados, _, _ = correio

    def _envia(**kw):
        if kw["to_email"] == "admin@x.com":
            raise RuntimeError("smtp caiu")
        enviados.append(kw)

    monkeypatch.setattr(nc, "send_smtp_email", _envia)
    out = nc.notificar_novos([_item("ALFA LTDA", "fp-a", DOC_A)])
    assert out["erros"] == 1
    assert _para(enviados, "ana@x.com")


# ══════════════════════════════════════════════════════════════════════════
# 4. A ingestão dispara o e-mail dos novos
# ══════════════════════════════════════════════════════════════════════════


def test_ingest_agenda_o_aviso_dos_novos(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _Fake({
        "users": [_usuario("u-adm", "admin@x.com", "admin")],
        "user_activity": [], "cert_snapshots": [], "cert_history": [], "carteira": [],
        "machine_credentials": [],
    })
    monkeypatch.setattr(ss, "_banco", lambda: fake)
    monkeypatch.setattr(ci, "_banco", lambda: fake)
    monkeypatch.setattr(m, "trigger_all_alerts", lambda: None)
    monkeypatch.setattr(config, "ACEITAR_API_KEY_COMPARTILHADA", True, raising=False)
    recebidos: List[List[Dict[str, Any]]] = []
    # Desde 02/10/2026 o ingest chama `agendar_ou_notificar` (hora cheia ou imediato).
    monkeypatch.setattr(m, "agendar_ou_notificar", lambda novos: recebidos.append(list(novos)))

    corpo = {"machine_id": "srv", "source_folder": "F:/C", "expired_folder": "F:/V",
             "items": [{"file_name": "ALFA_12345678000199.pfx", "nome": "ALFA", "fingerprint_sha256": "fp-a",
                        "documento_numero": DOC_A, "not_after": "2027-01-01T00:00:00+00:00", "status": "valido"}]}
    r = client.post("/api/ingest", headers=_h(*ADMIN), json=corpo)
    assert r.status_code == 200, r.text
    assert len(recebidos) == 1 and recebidos[0][0]["fingerprint_sha256"] == "fp-a"
    assert r.json()["novos"] == 1

    # Segunda ingestão do mesmo item: nada novo, nada agendado.
    r = client.post("/api/ingest", headers=_h(*ADMIN), json=corpo)
    assert r.status_code == 200 and r.json()["novos"] == 0
    assert len(recebidos) == 1

    # O mesmo certificado copiado para outro arquivo: chave nova no histórico,
    # mas o fingerprint já estava no inventário anterior — não é novo.
    corpo["items"].append(dict(corpo["items"][0], file_name="Copias/ALFA_12345678000199 (2).pfx"))
    r = client.post("/api/ingest", headers=_h(*ADMIN), json=corpo)
    assert r.status_code == 200 and r.json()["novos"] == 0
    assert len(recebidos) == 1


# ══════════════════════════════════════════════════════════════════════════
# 5. A tela
# ══════════════════════════════════════════════════════════════════════════


def test_filtro_vazio_volta_para_todos_e_respostas_fora_de_ordem_sao_descartadas() -> None:
    """Com o chip Novos ativo e o último novo marcado como lido, a lista
    daquele tipo chega vazia: o painel voltava a "tudo em dia" com os chips
    escondidos e 47 expirando no selo. E o poll de 60s podia chegar depois
    do clique no chip e sobrescrever o recorte."""
    assert "_seqNotif" in UI and "if (seq !== _seqNotif) return;" in UI
    assert re.search(r'if \(_filtroNotif !== "todos" && !contagens\[_filtroNotif\] && Number\(data && data\.total\) > 0\) \{\s*_filtroNotif = "todos";\s*void fetchNotifications\(\);\s*return;', UI)
    assert "filtros.hidden = !(Number(data && data.total) > 0);" in UI


def test_sino_tem_filtro_todos_novos_expirando_vencidos() -> None:
    assert 'id="notif-filtros"' in UI
    for f in ("todos", "novo", "expiring", "expired"):
        assert f'data-filtro="{f}"' in UI, f
    assert "_criarSecaoNotificacoes(\"Novos\"" in UI


def test_cartao_vencido_vai_para_vencidos_e_novo_vai_para_o_inicio() -> None:
    assert re.search(r'"/vencidos\?busca="\s*\+\s*encodeURIComponent', UI)
    assert re.search(r'"/\?busca="\s*\+\s*encodeURIComponent', UI)
    assert '"?tipo=" + encodeURIComponent(_filtroNotif)' in UI, "o chip pede ao servidor só aquele tipo"
    assert 'role", "link"' in UI or 'role="link"' in UI


def test_inicio_le_a_busca_da_url() -> None:
    assert re.search(r'URLSearchParams\(location\.search\)[\s\S]{0,400}busca-cert', INDEX)


def test_estilo_do_novo_e_busters() -> None:
    assert ".notif-novo" in CSS and ".notif-filtros" in CSS
    for t in (ROOT / "templates").glob("*.html"):
        s = t.read_text(encoding="utf-8")
        if "ui-common.js?v=" in s:
            assert "ui-common.js?v=leva-d-2026-10" in s, t.name  # 10a: Leva B (03/10)
        if "style.css?v=" in s:
            assert "style.css?v=menu-lateral-2026-09d" in s, t.name


def test_migration_da_primeira_data_existe_e_nao_sobrescreve_na_atualizacao() -> None:
    sql = (ROOT / "supabase" / "migrations" / "20260930140000_cert_history_primeira_data_registrada.sql").read_text(encoding="utf-8")
    assert "primeira_data_registrada" in sql and "ADD COLUMN" in sql.upper()
    assert "SET DEFAULT NOW()" in sql.upper()
    assert "NOT NULL" not in sql.upper(), "linhas anteriores ficam NULL: não se sabe quando apareceram"
    # `ADD COLUMN ... DEFAULT now()` preenche as linhas existentes com now()
    # (a cópia local provou: 1031 de 1031 viraram "novas"). O default só pode
    # entrar num ALTER COLUMN separado, depois de a coluna existir.
    linhas = "\n".join(l for l in sql.splitlines() if not l.lstrip().startswith("--"))
    add = re.search(r"ADD COLUMN[^;]*;", linhas, re.I).group(0)
    assert "DEFAULT" not in add.upper(), add
