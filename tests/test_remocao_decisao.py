"""Decisão do portal na remoção de certificados (Frente B): uma regra por teste."""

from datetime import date, datetime, timedelta, timezone

import pytest

import app.agent_devices as ad
import app.cert_installer as ci
import app.computadores as comp
import app.remocao as rem
from tests.test_seguranca_lote1 import _Fake

AGORA = datetime(2026, 11, 14, 12, 0, tzinfo=timezone.utc)
MID = "aa:bb:cc:dd:ee:ff"
ACERVO = {"f1": "111", "f2": "222", "f3": None}

# As verdadeiras, antes de qualquer monkeypatch.
DO_ACERVO, SITUACAO, MOTIVOS = rem.do_acervo, rem.situacao_do_vinculo, rem.motivos_da_saida


def _user(role: str = "user", ativo: bool = True) -> dict:
    return {"id": "u1", "role": role, "ativo": ativo}


@pytest.fixture
def regra(monkeypatch: pytest.MonkeyPatch):
    """Acervo fixo, vínculo em vigor; cada teste ajusta o alcance."""
    monkeypatch.setattr(rem, "do_acervo", lambda fps: {f: d for f, d in ACERVO.items() if f in fps})
    monkeypatch.setattr(rem, "situacao_do_vinculo", lambda u, m, a: ("carteira", None))
    monkeypatch.setattr(rem, "motivos_da_saida", lambda u, ds: {d: f"motivo de {d}" for d in ds})

    def alcance(valor):
        monkeypatch.setattr(ci, "documentos_ao_alcance", lambda uid, role: valor)

    return alcance


def _decidir(user=None, fps=("f1", "f2", "f3", "fx")):
    return rem.decidir_pessoa(user or _user(), MID, list(fps), AGORA)


def test_admin_nao_perde_nada(regra):
    regra(None)
    assert _decidir(_user("admin")) == []


def test_gestor_perde_so_excecao(regra):
    regra(ci.TudoMenos(["222"]))
    assert [(d.fingerprint, d.documento) for d in _decidir(_user("gestor"))] == [("f2", "222")]


def test_operador_perde_fora_da_carteira_com_motivo_do_historico(monkeypatch, regra):
    regra({"111"})
    fake = _Fake({"carteira_historico": [
        {"user_id": "u1", "documento": "222", "movimento": "saida", "origem": "acessorias",
         "feito_por_email": None, "feito_em": "2026-11-01T10:00:00+00:00"},
        {"user_id": "u1", "documento": "222", "movimento": "entrada", "origem": "manual",
         "feito_por_email": "g@x", "feito_em": "2026-11-05T10:00:00+00:00"},
        {"user_id": "u1", "documento": "222", "movimento": "saida", "origem": "manual",
         "feito_por_email": "g@x", "feito_em": "2026-11-10T10:00:00+00:00"},
        {"user_id": "u2", "documento": "222", "movimento": "saida", "origem": "prazo",
         "feito_por_email": None, "feito_em": "2026-11-12T10:00:00+00:00"},
    ]})
    monkeypatch.setattr(ci, "_banco", lambda: fake)
    monkeypatch.setattr(rem, "motivos_da_saida", MOTIVOS)

    def motivo(u, d):
        return MOTIVOS(u, [d])[d]

    [d] = _decidir()
    assert (d.fingerprint, d.regra, d.motivo, d.remover_em) == ("f2", "carteira", "retirado por g@x", None)
    # As outras traduções da última saída.
    for origem, texto in [("prazo", "prazo vencido"), ("bloqueio", "retirado por g@x"),
                          ("acessorias", "saiu no Acessórias"), ("papel", "mudou de papel"),
                          ("desativacao", "conta desativada")]:
        fake.tabelas["carteira_historico"].append({
            "user_id": "u1", "documento": "222", "movimento": "saida", "origem": origem,
            "feito_por_email": "g@x", "feito_em": f"2026-11-1{len(fake.tabelas['carteira_historico'])}T10:00:00+00:00"})
        assert motivo("u1", "222") == texto
    assert motivo("u1", "999") == "fora da carteira"


def test_motivos_numa_consulta_so(monkeypatch):
    fake = _Fake({"carteira_historico": [
        {"user_id": "u1", "documento": "111", "movimento": "saida", "origem": "prazo",
         "feito_por_email": None, "feito_em": "2026-11-01T10:00:00+00:00"},
        {"user_id": "u1", "documento": "111", "movimento": "saida", "origem": "acessorias",
         "feito_por_email": None, "feito_em": "2026-11-09T10:00:00+00:00"},
        {"user_id": "u1", "documento": "222", "movimento": "saida", "origem": "manual",
         "feito_por_email": "g@x", "feito_em": "2026-11-05T10:00:00+00:00"},
    ]})
    monkeypatch.setattr(ci, "_banco", lambda: fake)
    assert MOTIVOS("u1", ["111", "222", "333"]) == {
        "111": "saiu no Acessórias", "222": "retirado por g@x", "333": "fora da carteira"}
    assert fake.consultas == ["carteira_historico"]
    assert MOTIVOS("u1", []) == {}


def test_documento_nulo_nunca_sai(regra):
    regra(set())
    assert {d.fingerprint for d in _decidir()} == {"f1", "f2"}
    assert {d.fingerprint for d in _decidir(_user(ativo=False))} == {"f1", "f2"}


def test_fora_do_acervo_nunca_aparece(regra):
    regra(set())
    assert "fx" not in {d.fingerprint for d in _decidir()}
    assert rem.decidir_sem_login(["fx"]) == []


def test_do_acervo_dedup_e_minusculas(monkeypatch):
    fake = _Fake({"cert_pfx_store": [
        {"machine_id": "m1", "fingerprint": "ab", "documento": "11.111"},
        {"machine_id": "m2", "fingerprint": "ab", "documento": "11.111"},
        {"machine_id": "m1", "fingerprint": "cd", "documento": None},
        {"machine_id": "m1", "fingerprint": "ef", "documento": "333"},
    ]})
    monkeypatch.setattr(ci, "_banco", lambda: fake)
    assert rem.do_acervo(["AB", "cd", "zz"]) == {"ab": "11111", "cd": None}


def test_conta_desativada_tira_tudo_ja(monkeypatch, regra):
    regra(None)  # nem o alcance total segura
    monkeypatch.setattr(rem, "situacao_do_vinculo", lambda *a: pytest.fail("não consulta vínculo"))
    ds = _decidir(_user("admin", ativo=False))
    assert {(d.fingerprint, d.regra, d.motivo, d.remover_em) for d in ds} == {
        ("f1", "desativada", "conta desativada", None), ("f2", "desativada", "conta desativada", None)}


def _vinculos(monkeypatch, linhas):
    vistos = []

    def falso(**filtros):
        vistos.append(filtros)
        return [dict(l) for l in linhas]

    monkeypatch.setattr(comp, "_vinculos", falso)
    return vistos


def test_recusado_da_7_dias_contados_da_recusa(monkeypatch, regra):
    recusa = "2026-11-10T08:00:00+00:00"
    _vinculos(monkeypatch, [{"estado": "recusado", "tipo": "principal", "pedido_em": "2026-11-09T08:00:00+00:00",
                             "decidido_em": recusa, "encerrado_em": recusa, "motivo": None}])
    monkeypatch.setattr(rem, "situacao_do_vinculo", SITUACAO)
    regra(None)
    ds = _decidir(_user("admin"))
    fim = datetime(2026, 11, 17, 8, 0, tzinfo=timezone.utc)
    assert {(d.fingerprint, d.regra, d.motivo, d.remover_em) for d in ds} == {
        ("f1", "vinculo", "computador recusado ou desvinculado", fim),
        ("f2", "vinculo", "computador recusado ou desvinculado", fim)}


def test_desvinculado_da_7_dias(monkeypatch):
    vistos = _vinculos(monkeypatch, [{"estado": "encerrado", "tipo": "principal",
                                      "pedido_em": "2026-10-01T08:00:00+00:00",
                                      "decidido_em": "2026-10-01T09:00:00+00:00",
                                      "encerrado_em": "2026-11-12T08:00:00+00:00",
                                      "motivo": "Desvinculado por adm@x."}])
    assert rem.situacao_do_vinculo("u1", "AA:BB:CC:DD:EE:FF", AGORA) == (
        "vinculo", datetime(2026, 11, 12, 8, 0, tzinfo=timezone.utc))
    assert vistos == [{"user_id": "u1", "machine_id": MID}]


def test_aceito_de_novo_volta_a_carteira(monkeypatch):
    _vinculos(monkeypatch, [
        {"estado": "recusado", "tipo": "principal", "pedido_em": "2026-11-01T08:00:00+00:00",
         "decidido_em": "2026-11-02T08:00:00+00:00", "encerrado_em": "2026-11-02T08:00:00+00:00"},
        {"estado": "ativo", "tipo": "principal", "pedido_em": "2026-11-03T08:00:00+00:00",
         "decidido_em": "2026-11-03T09:00:00+00:00", "encerrado_em": None},
    ])
    assert rem.situacao_do_vinculo("u1", MID, AGORA) == ("carteira", None)
    # Pendente também segura, mesmo mais antigo que a recusa.
    _vinculos(monkeypatch, [
        {"estado": "pendente", "tipo": "principal", "pedido_em": "2026-11-01T08:00:00+00:00"},
        {"estado": "recusado", "tipo": "principal", "decidido_em": "2026-11-12T08:00:00+00:00"},
    ])
    assert rem.situacao_do_vinculo("u1", MID, AGORA) == ("carteira", None)


def test_emprestimo_vencido_conta_do_expira_em(monkeypatch):
    fim = datetime(2026, 11, 11, 23, 59, 59, tzinfo=timezone.utc)
    _vinculos(monkeypatch, [{"estado": "encerrado", "tipo": "emprestimo", "decidido_em": "2026-11-08T08:00:00+00:00",
                             "expira_em": fim.isoformat(), "encerrado_em": "2026-11-13T08:00:00+00:00",
                             "motivo": "Prazo do empréstimo terminou."}])
    assert rem.situacao_do_vinculo("u1", MID, AGORA) == ("emprestimo", fim)
    # Vencido mas ainda não encerrado no banco (o encerramento é preguiçoso).
    _vinculos(monkeypatch, [{"estado": "ativo", "tipo": "emprestimo", "decidido_em": "2026-11-08T08:00:00+00:00",
                             "expira_em": fim.isoformat(), "encerrado_em": None}])
    assert rem.situacao_do_vinculo("u1", MID, AGORA) == ("emprestimo", fim)


def test_outra_maquina_segue_carteira(monkeypatch):
    _vinculos(monkeypatch, [{"estado": "encerrado", "tipo": "principal", "decidido_em": "2026-11-01T08:00:00+00:00",
                             "encerrado_em": "2026-11-12T08:00:00+00:00",
                             "motivo": "A pessoa entrou em outra máquina."}])
    assert rem.situacao_do_vinculo("u1", MID, AGORA) == ("carteira", None)
    _vinculos(monkeypatch, [])
    assert rem.situacao_do_vinculo("u1", MID, AGORA) == ("carteira", None)


def test_carteira_indisponivel_propaga(monkeypatch, regra):
    def cai(uid, role):
        raise ci.CarteiraIndisponivel("banco fora")

    monkeypatch.setattr(ci, "documentos_ao_alcance", cai)
    with pytest.raises(ci.CarteiraIndisponivel):
        _decidir()
    # Erro cru de leitura em qualquer ponto vira CarteiraIndisponivel.
    monkeypatch.setattr(comp, "_vinculos", lambda **f: 1 / 0)
    with pytest.raises(ci.CarteiraIndisponivel):
        SITUACAO("u1", MID, AGORA)
    fake = _Fake({})
    fake.quebrado.update({"cert_pfx_store": True, "carteira_historico": True, "carteira": True})
    monkeypatch.setattr(ci, "_banco", lambda: fake)
    for chamada in (lambda: DO_ACERVO(["f1"]), lambda: MOTIVOS("u1", ["111"]),
                    lambda: rem.vencendo("u1", date(2026, 11, 14))):
        with pytest.raises(ci.CarteiraIndisponivel):
            chamada()
    monkeypatch.setattr(ci, "_banco", lambda: None)
    with pytest.raises(ci.CarteiraIndisponivel):
        DO_ACERVO(["f1"])


def test_sem_role_levanta_em_vez_de_virar_operador(regra):
    regra(set())
    with pytest.raises(ci.CarteiraIndisponivel):
        _decidir({"id": "u1", "ativo": True})


@pytest.mark.parametrize("role", [None, "", "  "])
def test_role_vazio_levanta_em_vez_de_virar_operador(regra, role):
    regra(set())
    with pytest.raises(ci.CarteiraIndisponivel):
        _decidir({"id": "u1", "role": role, "ativo": True})


def test_agora_sem_fuso_conta_como_utc(monkeypatch):
    fim = datetime(2026, 11, 11, 23, 59, 59, tzinfo=timezone.utc)
    _vinculos(monkeypatch, [{"estado": "ativo", "tipo": "emprestimo", "decidido_em": "2026-11-08T08:00:00+00:00",
                             "expira_em": fim.isoformat(), "encerrado_em": None}])
    assert SITUACAO("u1", MID, AGORA.replace(tzinfo=None)) == ("emprestimo", fim)


def test_sem_login_tira_todo_o_acervo(regra):
    ds = rem.decidir_sem_login(["f1", "f3", "fx"])
    assert [(d.fingerprint, d.regra, d.motivo, d.remover_em) for d in ds] == [
        ("f1", "sem_login", "perfil sem login na bandeja", None)]


def test_vencendo_so_manual_com_prazo_em_3_dias(monkeypatch):
    hoje = date(2026, 11, 14)
    fake = _Fake({"carteira": [
        {"user_id": "u1", "documento": "1", "origem": "manual", "valido_ate": "2026-11-14"},
        {"user_id": "u1", "documento": "2", "origem": "manual", "valido_ate": date(2026, 11, 17)},
        {"user_id": "u1", "documento": "3", "origem": "manual", "valido_ate": "2026-11-18"},
        {"user_id": "u1", "documento": "4", "origem": "manual", "valido_ate": "2026-11-13"},
        {"user_id": "u1", "documento": "5", "origem": "manual", "valido_ate": None},
        {"user_id": "u1", "documento": "6", "origem": "acessorias", "valido_ate": "2026-11-15"},
        {"user_id": "u2", "documento": "7", "origem": "manual", "valido_ate": "2026-11-15"},
    ]})
    monkeypatch.setattr(ci, "_banco", lambda: fake)
    assert sorted(rem.vencendo("u1", hoje), key=lambda x: x["documento"]) == [
        {"documento": "1", "vence_em": date(2026, 11, 14)},
        {"documento": "2", "vence_em": date(2026, 11, 17)},
    ]


def test_dono_do_segredo_acha_revogado(monkeypatch):
    linha = {"id": 1, "user_id": "u1", "machine_id": MID, "segredo_hash": ad._hash("s3gr3do"),
             "revogado_em": "2026-11-10T00:00:00+00:00", "visto_em": "2026-11-01T00:00:00+00:00"}
    fake = _Fake({"agent_devices": [linha]})
    monkeypatch.setattr(ad, "_banco", lambda: fake)
    achada = ad.dono_do_segredo("s3gr3do")
    assert achada["id"] == 1 and achada["revogado_em"]
    assert fake.tabelas["agent_devices"][0]["visto_em"] == "2026-11-01T00:00:00+00:00"
    assert ad.dono_do_segredo("outro") is None
    assert ad.dono_do_segredo("") is None
