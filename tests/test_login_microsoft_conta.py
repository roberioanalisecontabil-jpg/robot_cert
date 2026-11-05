"""Qual conta entra pela Microsoft: ligar, criar ou recusar. Cada teste guarda
uma regra cuja quebra abriria a conta de outra pessoa sem dar sintoma."""
from typing import Any, Dict

import pytest

from app import auth
from app.db_pg import DbError
from app.login_microsoft import Recusa, pode_usar_reserva, resolver_conta
from app.microsoft_entra import Identidade
from app.smtp_service import decrypt_password
from tests.test_recuperacao_de_senha import _Fake

DOM = "analisegroup.cnt.br"


@pytest.fixture(autouse=True)
def dominios(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.config.MICROSOFT_DOMINIOS", [DOM], raising=False)


def _ident(**kw: Any) -> Identidade:
    base = dict(oid="oid-1", tid="t", upn=f"ana@{DOM}", email=f"ana@{DOM}",
                nome="Ana Souza", convidado=False)
    base.update(kw)
    return Identidade(**base)


def _banco(*users: Dict[str, Any]) -> _Fake:
    return _Fake({"users": [{"id": f"u{i}", "role": "user", "ativo": True, **u} for i, u in enumerate(users)]})


def test_liga_conta_existente_pelo_upn_maiusculo() -> None:
    sb = _banco({"email": f"ana@{DOM}"})
    r = resolver_conta(sb, _ident(upn=f"ANA@{DOM.upper()}", email=""), "rt")
    user, criada = r
    assert criada is False and user["id"] == "u0"
    assert sb.tabelas["users"][0]["microsoft_oid"] == "oid-1"
    assert len(sb.tabelas["users"]) == 1


def test_cria_conta_operador_sem_departamento_origem_microsoft() -> None:
    sb = _banco()
    user, criada = resolver_conta(sb, _ident(), "rt")
    assert criada is True
    assert user["role"] == "user" and user["origem"] == "microsoft"
    assert user.get("departamento_id") is None
    assert user["ativo"] is True and user["full_name"] == "Ana Souza"
    assert user["password_hash"] and user["microsoft_oid"] == "oid-1"


def test_segundo_login_acha_pelo_oid_mesmo_com_email_trocado() -> None:
    sb = _banco({"email": "velho@x.com", "microsoft_oid": "oid-1"})
    user, criada = resolver_conta(sb, _ident(upn=f"novo@{DOM}", email=f"novo@{DOM}"), "rt")
    assert criada is False and user["id"] == "u0" and len(sb.tabelas["users"]) == 1


def test_upn_e_email_em_contas_diferentes_recusa_ambiguo() -> None:
    sb = _banco({"email": f"a@{DOM}"}, {"email": f"b@{DOM}"})
    r = resolver_conta(sb, _ident(upn=f"a@{DOM}", email=f"b@{DOM}"), "rt")
    assert r == Recusa("ambiguo")
    assert "microsoft_oid" not in sb.tabelas["users"][0]


def test_email_fora_do_dominio_nao_liga_a_conta_que_tem_esse_email() -> None:
    # Membro do locatário com upn no domínio e `email` pessoal: a conta do
    # CertGuard com o gmail é de outra pessoa (ou de ninguém do locatário).
    sb = _banco({"email": "ana@gmail.com"})
    user, criada = resolver_conta(sb, _ident(email="ana@gmail.com"), "rt")
    assert criada is True and user["email"] == f"ana@{DOM}" and user["id"] != "u0"
    assert "microsoft_oid" not in sb.tabelas["users"][0]


def test_oid_diferente_recusa() -> None:
    sb = _banco({"email": f"ana@{DOM}", "microsoft_oid": "outro"})
    assert resolver_conta(sb, _ident(), "rt") == Recusa("oid_diferente")
    assert sb.tabelas["users"][0]["microsoft_oid"] == "outro"


def test_convidado_recusa() -> None:
    assert resolver_conta(_banco(), _ident(convidado=True), "rt") == Recusa("convidado")


def test_dominio_fora_recusa() -> None:
    sb = _banco()
    r = resolver_conta(sb, _ident(upn="x@varejoconectado.com.br", email="x@varejoconectado.com.br"), "rt")
    assert r == Recusa("dominio") and sb.tabelas["users"] == []


def test_desativada_recusa_sem_gravar() -> None:
    sb = _banco({"email": f"ana@{DOM}", "ativo": False})
    assert resolver_conta(sb, _ident(), "rt") == Recusa("desativada")
    assert "microsoft_oid" not in sb.tabelas["users"][0]
    assert "microsoft_conferido_em" not in sb.tabelas["users"][0]


def test_duas_chamadas_seguidas_criam_uma_conta() -> None:
    sb = _banco()
    resolver_conta(sb, _ident(), "rt")
    user, criada = resolver_conta(sb, _ident(), "rt")
    assert criada is False and len(sb.tabelas["users"]) == 1


def _insert_falha(sb: _Fake, erro: Exception, vencedor: bool) -> None:
    real = sb.table

    def table(nome: str):
        q = real(nome)
        orig = q.execute

        def execute():
            if q._op == "insert":
                if vencedor:
                    sb.tabelas["users"].append({"id": "vencedor", "email": f"ana@{DOM}", "role": "user", "ativo": True})
                raise erro
            return orig()

        q.execute = execute
        return q

    sb.table = table  # type: ignore[assignment]


def test_insert_que_perde_a_corrida_relê_a_conta_do_outro_e_nao_conta_como_criada() -> None:
    sb = _banco()
    _insert_falha(sb, DbError("duplicate key", "23505"), vencedor=True)
    user, criada = resolver_conta(sb, _ident(), "rt")
    assert user["id"] == "vencedor" and len(sb.tabelas["users"]) == 1
    assert criada is False


def test_erro_do_insert_que_nao_e_duplicidade_propaga() -> None:
    sb = _banco()
    _insert_falha(sb, DbError("permission denied", "42501"), vencedor=False)
    with pytest.raises(DbError):
        resolver_conta(sb, _ident(), "rt")


def test_cria_com_o_upn_quando_so_ele_esta_em_dominio_liberado() -> None:
    sb = _banco()
    user, criada = resolver_conta(sb, _ident(email="ana@varejoconectado.com.br"), "rt")
    assert criada is True and user["email"] == f"ana@{DOM}"


def test_refresh_gravado_cifrado() -> None:
    sb = _banco({"email": f"ana@{DOM}"})
    resolver_conta(sb, _ident(), "segredo-rt")
    linha = sb.tabelas["users"][0]
    assert linha["microsoft_refresh_cifrado"] != "segredo-rt"
    assert decrypt_password(linha["microsoft_refresh_cifrado"]) == "segredo-rt"
    assert linha["microsoft_sem_conferencia"] is False and linha["microsoft_conferido_em"]


def test_sem_refresh_nao_toca_o_guardado_e_marca_sem_conferencia() -> None:
    sb = _banco({"email": f"ana@{DOM}", "microsoft_oid": "oid-1", "microsoft_refresh_cifrado": "antigo"})
    resolver_conta(sb, _ident(), "")
    linha = sb.tabelas["users"][0]
    assert linha["microsoft_refresh_cifrado"] == "antigo"
    assert linha["microsoft_sem_conferencia"] is True


def test_pode_usar_reserva() -> None:
    ok = {"role": "admin", "ativo": True, "microsoft_oid": "o", "totp_ativado_em": "2026-01-01"}
    assert pode_usar_reserva(ok)
    assert not pode_usar_reserva({**ok, "role": "user"})
    assert not pode_usar_reserva({**ok, "ativo": False})
    assert not pode_usar_reserva({**ok, "microsoft_oid": None})
    assert not pode_usar_reserva({**ok, "totp_ativado_em": None})
