"""
Regras do vínculo pessoa–computador (ADR 0002, 07/10/2026).

Cada teste é um cenário dito pelo usuário no grill: primeira máquina, troca de
máquina, máquina emprestada do colega, volta para a própria, prazo do
empréstimo, recusa e desvínculo.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app import agent_devices, computadores as cp
from tests.test_seguranca_lote1 import _Fake
from tests.test_seguranca_lote4 import banco as banco_base  # noqa: F401

FIS, SOL = "u-fis", "u-sol"          # dois operadores
PC_FIS, PC_SOL, PC_CEDIDO = "aa:aa:aa:aa:aa:01", "aa:aa:aa:aa:aa:02", "aa:aa:aa:aa:aa:09"
ADMIN = "admin@x.com"


@pytest.fixture
def banco(banco_base: _Fake) -> _Fake:
    banco_base.tabelas["computador_vinculo"] = []
    banco_base.tabelas["fila_instalacao"] = []
    banco_base.tabelas["agent_devices"] = []
    return banco_base


def entrar(user: str, maquina: str) -> dict:
    """O que a rota de registro faz: dispositivo + regras."""
    agent_devices.registrar(user, maquina, nome=maquina)
    return cp.ao_entrar(user, maquina, maquina)


def pendente(user: str, maquina: str) -> dict:
    return cp.pendente_do_par(user, maquina)


def sessoes(banco: _Fake, user: str) -> list:
    return sorted(d["machine_id"] for d in banco.tabelas["agent_devices"] if d["user_id"] == user and not d.get("revogado_em"))


def test_primeira_maquina_fica_pendente_como_principal(banco: _Fake) -> None:
    s = entrar(FIS, PC_FIS)
    assert s["autorizacao"] == "pendente" and s["tipo"] == "principal"
    cp.autorizar(pendente(FIS, PC_FIS)["id"], "principal", ADMIN)
    assert cp.situacao(FIS, PC_FIS)["autorizacao"] == "autorizado"
    # Reconectar (reinício, novo login) na mesma máquina não pede de novo.
    assert entrar(FIS, PC_FIS)["autorizacao"] == "autorizado"
    assert len(banco.tabelas["computador_vinculo"]) == 1


def test_um_acesso_por_vez_e_emprestimo_que_termina_ao_voltar(banco: _Fake) -> None:
    entrar(FIS, PC_FIS)
    cp.autorizar(pendente(FIS, PC_FIS)["id"], "principal", ADMIN)
    # Equipamento com problema: entra na máquina cedida.
    s = entrar(FIS, PC_CEDIDO)
    assert s["autorizacao"] == "pendente" and s["tipo"] == "emprestimo"
    assert sessoes(banco, FIS) == [PC_CEDIDO], "a principal sai na hora"
    assert cp.principal_da_pessoa(FIS)["machine_id"] == PC_FIS, "a principal continua principal"
    cp.autorizar(pendente(FIS, PC_CEDIDO)["id"], "emprestimo", ADMIN, prazo="3_dias")
    assert cp.situacao(FIS, PC_CEDIDO)["autorizacao"] == "autorizado"
    # Volta para a própria: autorizada na hora, e o empréstimo termina.
    assert entrar(FIS, PC_FIS)["autorizacao"] == "autorizado"
    assert sessoes(banco, FIS) == [PC_FIS]
    assert cp.situacao(FIS, PC_CEDIDO)["autorizacao"] == "sem_pedido"


def test_maquina_do_colega_e_o_dono_retoma(banco: _Fake) -> None:
    for u, pc in ((FIS, PC_FIS), (SOL, PC_SOL)):
        entrar(u, pc)
        cp.autorizar(pendente(u, pc)["id"], "principal", ADMIN)
    # SOL usa a máquina do FIS: o FIS sai dela, SOL fica pendente.
    entrar(SOL, PC_FIS)
    assert sessoes(banco, FIS) == [] and sessoes(banco, SOL) == [PC_FIS]
    cp.autorizar(pendente(SOL, PC_FIS)["id"], "emprestimo", ADMIN)
    assert cp.situacao(SOL, PC_FIS)["autorizacao"] == "autorizado"
    assert cp.principal_da_maquina(PC_FIS)["user_id"] == FIS, "o Hardlyze não vê mudança"
    # FIS volta: retoma sem autorização e o empréstimo do SOL termina.
    assert entrar(FIS, PC_FIS)["autorizacao"] == "autorizado"
    assert sessoes(banco, SOL) == []
    assert cp.situacao(SOL, PC_FIS)["autorizacao"] == "sem_pedido"


def test_troca_de_verdade_manda_a_antiga_ao_historico(banco: _Fake) -> None:
    entrar(FIS, PC_FIS)
    cp.autorizar(pendente(FIS, PC_FIS)["id"], "principal", ADMIN)
    entrar(FIS, PC_CEDIDO)
    cp.autorizar(pendente(FIS, PC_CEDIDO)["id"], "principal", ADMIN)
    assert cp.principal_da_pessoa(FIS)["machine_id"] == PC_CEDIDO
    antigo = next(v for v in banco.tabelas["computador_vinculo"] if v["machine_id"] == PC_FIS)
    assert antigo["estado"] == "encerrado" and "Substituída" in antigo["motivo"]
    assert cp.principal_da_maquina(PC_FIS) is None


def test_emprestimo_vencido_nao_autoriza(banco: _Fake) -> None:
    entrar(FIS, PC_CEDIDO)
    v = cp.autorizar(pendente(FIS, PC_CEDIDO)["id"], "emprestimo", ADMIN)
    for linha in banco.tabelas["computador_vinculo"]:
        if linha["id"] == v["id"]:
            linha["expira_em"] = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    assert cp.situacao(FIS, PC_CEDIDO)["autorizacao"] == "sem_pedido"
    assert next(l for l in banco.tabelas["computador_vinculo"] if l["id"] == v["id"])["estado"] == "encerrado"


def test_recusar_e_desvincular_derrubam_a_sessao(banco: _Fake) -> None:
    entrar(SOL, PC_SOL)
    cp.recusar(pendente(SOL, PC_SOL)["id"], ADMIN)
    assert sessoes(banco, SOL) == []
    entrar(FIS, PC_FIS)
    v = cp.autorizar(pendente(FIS, PC_FIS)["id"], "principal", ADMIN)
    cp.desvincular(v["id"], ADMIN)
    assert sessoes(banco, FIS) == [] and cp.principal_da_pessoa(FIS) is None
    with pytest.raises(cp.VinculoInvalido):
        cp.autorizar(v["id"], "principal", ADMIN)


def test_fim_do_dia_e_23h59_de_alagoas() -> None:
    meio_dia = datetime(2026, 10, 7, 15, 0, tzinfo=timezone.utc)  # 12h em Maceió
    assert cp.fim_do_prazo("fim_do_dia", meio_dia) == datetime(2026, 10, 8, 2, 59, 59, tzinfo=timezone.utc)
    assert cp.fim_do_prazo("7_dias", meio_dia) == meio_dia + timedelta(days=7)
    with pytest.raises(cp.VinculoInvalido):
        cp.fim_do_prazo("sempre", meio_dia)


def test_fila_entrega_uma_vez_e_ignora_vencido(banco: _Fake) -> None:
    agora = datetime.now(timezone.utc)
    cp.enfileirar(PC_FIS.upper(), "token-1", "t1", agora + timedelta(minutes=10))
    cp.enfileirar(PC_FIS, "token-velho", "t0", agora - timedelta(minutes=1))
    assert "token-1" not in str(banco.tabelas["fila_instalacao"]), "o token fica cifrado"
    assert cp.entregar(PC_FIS) == ["token-1"]
    assert cp.entregar(PC_FIS) == []


def test_principais_para_o_hardlyze(banco: _Fake) -> None:
    entrar(FIS, PC_FIS)
    cp.autorizar(pendente(FIS, PC_FIS)["id"], "principal", ADMIN)
    entrar(SOL, PC_CEDIDO)
    cp.autorizar(pendente(SOL, PC_CEDIDO)["id"], "emprestimo", ADMIN)
    assert [(p["machine_id"], p["user_id"]) for p in cp.principais()] == [(PC_FIS, FIS)]
