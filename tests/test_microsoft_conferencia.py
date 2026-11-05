"""Conferência de 5 em 5 minutos: só 'bloqueada' desativa, e nunca em massa nem
quando o erro é do nosso aplicativo. Cada teste guarda uma trava cuja quebra
trancaria gente de fora sem dar sintoma."""
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

import pytest

from app import microsoft_conferencia as mc
from app.microsoft_entra import Renovacao
from app.smtp_service import decrypt_password, encrypt_password
from tests.test_recuperacao_de_senha import _Fake

T0 = datetime(2026, 11, 5, 10, 0, tzinfo=timezone.utc)


class _Ctx:
    def __init__(self, sb: _Fake) -> None:
        self.sb = sb
        self.agora = T0
        self.avisos: List[Dict[str, Any]] = []
        self.saidas: List[str] = []
        self.revogados: List[str] = []

    def user(self, uid: str) -> Dict[str, Any]:
        return next(u for u in self.sb.tabelas["users"] if u["id"] == uid)


def _conta(uid: str, refresh: str = "", **kw: Any) -> Dict[str, Any]:
    return {"id": uid, "email": f"{uid}@x.com", "full_name": uid.upper(), "role": "user", "ativo": True,
            "sessao_versao": 1,
            "microsoft_refresh_cifrado": encrypt_password(refresh) if refresh else None, **kw}


@pytest.fixture
def ctx(monkeypatch: pytest.MonkeyPatch) -> _Ctx:
    sb = _Fake({"users": [_conta("u1"), _conta("adm", role="admin")], "user_activity": [],
                "departamento_lider": [], "carteira_excecao": []})
    c = _Ctx(sb)
    monkeypatch.setattr("app.settings_state._banco", lambda: sb)
    monkeypatch.setattr("app.config.MICROSOFT_CONFERENCIA", "aplicar", raising=False)
    monkeypatch.setattr(mc, "_agora", lambda: c.agora)
    monkeypatch.setattr(mc, "_enviar_ti", lambda assunto, linhas: c.avisos.append({"assunto": assunto, "linhas": linhas}) or True)
    monkeypatch.setattr("app.computadores.sair_de_tudo", lambda uid, motivo: c.saidas.append(uid) or 0)
    monkeypatch.setattr("app.cert_installer.revogar_tokens_pendentes", lambda uid: c.revogados.append(uid) or 0)
    monkeypatch.setattr("app.papeis.rederivar", lambda sb, ids: [])
    mc._avisos_ti.clear()
    mc._simulados.clear()
    return c


def _renovar(**por_conta: Renovacao):
    """Falso por injeção: o refresh antigo diz quem é a conta ('rt-<uid>')."""
    def f(refresh: str, cliente: Any = None) -> Renovacao:
        return por_conta.get(refresh.removeprefix("rt-"), Renovacao("ok", refresh, None))
    return f


def _bloq(codigo: str = "AADSTS50057") -> Renovacao:
    return Renovacao("bloqueada", None, codigo)


def _dar_refresh(ctx: _Ctx, *uids: str) -> None:
    for u in uids:
        ctx.user(u)["microsoft_refresh_cifrado"] = encrypt_password(f"rt-{u}")


def test_bloqueada_desativa_tudo(ctx: _Ctx) -> None:
    _dar_refresh(ctx, "u1")
    r = mc.conferir_todas(ctx.sb, _renovar(u1=_bloq()))
    u = ctx.user("u1")
    assert u["ativo"] is False and u["desativada_pela_microsoft_em"]
    assert u["sessao_versao"] == 2
    assert ctx.saidas == ["u1"] and ctx.revogados == ["u1"]
    assert r["bloqueadas"] == 1 and r["travado"] is False
    assert [a["evento"] for a in ctx.sb.tabelas["user_activity"]] == ["desativada_microsoft"]


def test_sem_conferencia_so_marca(ctx: _Ctx) -> None:
    _dar_refresh(ctx, "u1")
    r = mc.conferir_todas(ctx.sb, _renovar(u1=Renovacao("sem_conferencia", None, "AADSTS50173")))
    assert ctx.user("u1")["ativo"] is True and ctx.user("u1")["microsoft_sem_conferencia"] is True
    assert r["sem_conferencia"] == 1


def test_ok_grava_refresh_novo(ctx: _Ctx) -> None:
    _dar_refresh(ctx, "u1")
    r = mc.conferir_todas(ctx.sb, _renovar(u1=Renovacao("ok", "rt-novo", None)))
    u = ctx.user("u1")
    assert decrypt_password(u["microsoft_refresh_cifrado"]) == "rt-novo"
    assert u["microsoft_conferido_em"] and u["microsoft_sem_conferencia"] is False
    assert r["ok"] == 1


def test_falha_rede_nao_mexe_e_avisa_uma_vez_por_hora(ctx: _Ctx) -> None:
    _dar_refresh(ctx, "u1")
    antes = ctx.user("u1")["microsoft_refresh_cifrado"]
    falha = _renovar(u1=Renovacao("falha", None, None))
    r = mc.conferir_todas(ctx.sb, falha)
    assert r["falhas"] == 1 and r["travado"] is False
    assert ctx.user("u1")["ativo"] is True and ctx.user("u1")["microsoft_refresh_cifrado"] == antes
    assert len(ctx.avisos) == 1
    ctx.agora = T0 + timedelta(minutes=55)
    mc.conferir_todas(ctx.sb, falha)
    assert len(ctx.avisos) == 1
    ctx.agora = T0 + timedelta(minutes=61)
    mc.conferir_todas(ctx.sb, falha)
    assert len(ctx.avisos) == 2


def test_seis_bloqueadas_trava_e_avisa(ctx: _Ctx) -> None:
    ids = [f"m{i}" for i in range(6)]
    ctx.sb.tabelas["users"] += [_conta(i, f"rt-{i}") for i in ids]
    r = mc.conferir_todas(ctx.sb, _renovar(**{i: _bloq() for i in ids}))
    assert r["travado"] is True and r["bloqueadas"] == 6
    assert all(ctx.user(i)["ativo"] is True for i in ids)
    assert len(ctx.avisos) == 1 and len(ctx.avisos[0]["linhas"]) == 6


def test_cinco_bloqueadas_ainda_desativa(ctx: _Ctx) -> None:
    ids = [f"m{i}" for i in range(5)]
    ctx.sb.tabelas["users"] += [_conta(i, f"rt-{i}") for i in ids]
    r = mc.conferir_todas(ctx.sb, _renovar(**{i: _bloq() for i in ids}))
    assert r["travado"] is False and all(ctx.user(i)["ativo"] is False for i in ids)


@pytest.mark.parametrize("codigo", ["AADSTS7000215", "AADSTS7000222", "AADSTS700016"])
def test_segredo_invalido_trava(ctx: _Ctx, codigo: str) -> None:
    _dar_refresh(ctx, "u1", "adm")
    r = mc.conferir_todas(ctx.sb, _renovar(u1=_bloq(), adm=Renovacao("falha", None, codigo)))
    assert r["travado"] is True and ctx.user("u1")["ativo"] is True
    assert len(ctx.avisos) == 1


def test_travado_ainda_grava_o_ok(ctx: _Ctx) -> None:
    _dar_refresh(ctx, "u1", "adm")
    mc.conferir_todas(ctx.sb, _renovar(u1=Renovacao("ok", "rt-novo", None),
                                       adm=Renovacao("falha", None, "AADSTS7000215")))
    assert decrypt_password(ctx.user("u1")["microsoft_refresh_cifrado"]) == "rt-novo"


def test_ultimo_admin_nao_desativa(ctx: _Ctx) -> None:
    _dar_refresh(ctx, "adm")
    r = mc.conferir_todas(ctx.sb, _renovar(adm=_bloq()))
    assert ctx.user("adm")["ativo"] is True and r["bloqueadas"] == 1
    assert len(ctx.avisos) == 1 and "administrador" in ctx.avisos[0]["assunto"].lower()
    assert ctx.saidas == []


def test_conta_sem_refresh_ignorada(ctx: _Ctx) -> None:
    chamadas: List[str] = []

    def renovar(refresh: str, cliente: Any = None) -> Renovacao:
        chamadas.append(refresh)
        return Renovacao("ok", refresh, None)

    ctx.sb.tabelas["users"].append(_conta("off", "rt-off", ativo=False))
    r = mc.conferir_todas(ctx.sb, renovar)
    assert chamadas == [] and r["ok"] == 0


def test_chave_ilegivel_conta_como_falha_sem_desativar(ctx: _Ctx) -> None:
    ctx.user("u1")["microsoft_refresh_cifrado"] = "lixo"
    r = mc.conferir_todas(ctx.sb, _renovar())
    assert r["falhas"] == 1 and ctx.user("u1")["ativo"] is True


def test_excecao_de_uma_conta_nao_para_a_rodada(ctx: _Ctx) -> None:
    _dar_refresh(ctx, "u1", "adm")

    def renovar(refresh: str, cliente: Any = None) -> Renovacao:
        if refresh == "rt-u1":
            raise RuntimeError("boom")
        return Renovacao("ok", "rt-novo", None)

    r = mc.conferir_todas(ctx.sb, renovar)
    assert r["falhas"] == 1 and r["ok"] == 1


def test_simular_nao_desativa_e_avisa_com_codigo(ctx: _Ctx, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.config.MICROSOFT_CONFERENCIA", "simular", raising=False)
    _dar_refresh(ctx, "u1")
    r = mc.conferir_todas(ctx.sb, _renovar(u1=_bloq("AADSTS50057")))
    assert r["simulado"] is True and ctx.user("u1")["ativo"] is True and ctx.saidas == []
    assert len(ctx.avisos) == 1
    linha = ctx.avisos[0]["linhas"][0]
    assert "AADSTS50057" in linha and "u1@x.com" in linha and "U1" in linha
    # mesma conta, mesmo dia: não repete; no dia seguinte, repete
    mc.conferir_todas(ctx.sb, _renovar(u1=_bloq()))
    assert len(ctx.avisos) == 1
    ctx.agora = T0 + timedelta(days=1)
    mc.conferir_todas(ctx.sb, _renovar(u1=_bloq()))
    assert len(ctx.avisos) == 2


def test_simular_ainda_grava_refresh(ctx: _Ctx, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.config.MICROSOFT_CONFERENCIA", "simular", raising=False)
    _dar_refresh(ctx, "u1")
    mc.conferir_todas(ctx.sb, _renovar(u1=Renovacao("ok", "rt-novo", None)))
    assert decrypt_password(ctx.user("u1")["microsoft_refresh_cifrado"]) == "rt-novo"


@pytest.mark.parametrize("valor", [None, "", "Aplicar ", "talvez"])
def test_variavel_ausente_ou_invalida_simula(ctx: _Ctx, monkeypatch: pytest.MonkeyPatch, valor: Any) -> None:
    # config.py já aplica strip/lower ao ler o ambiente; aqui só o valor exato aplica.
    monkeypatch.setattr("app.config.MICROSOFT_CONFERENCIA", valor, raising=False)
    _dar_refresh(ctx, "u1")
    r = mc.conferir_todas(ctx.sb, _renovar(u1=_bloq()))
    assert r["simulado"] is True and ctx.user("u1")["ativo"] is True


def test_aplicar_desativa(ctx: _Ctx) -> None:
    _dar_refresh(ctx, "u1")
    r = mc.conferir_todas(ctx.sb, _renovar(u1=_bloq()))
    assert r["simulado"] is False and ctx.user("u1")["ativo"] is False
