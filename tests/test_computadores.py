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
    banco_base.tabelas["maquina_chave"] = []
    return banco_base


def chave(maquina: str) -> str:
    """A chave que a bandeja 2.1.4 gerou na instalação daquela máquina física."""
    return ("chave-da-maquina-" + maquina).ljust(43, "x")


CHAVE_DE_OUTRO_LUGAR = "chave-de-quem-so-tem-a-senha".ljust(43, "z")


def entrar_com(user: str, maquina: str, chave_maquina) -> tuple:
    """O que a rota de registro faz: (segredo ou None, situação)."""
    return cp.entrar(user, maquina, maquina, chave_maquina)


def entrar(user: str, maquina: str) -> dict:
    """A bandeja de verdade, sentada na máquina: manda a chave dela."""
    return entrar_com(user, maquina, chave(maquina))[1]


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


# ──────────────────────────────────────────────────────────────────────────
# Chave da máquina (adendo ao ADR 0002, auditoria de 10/10/2026)
#
# O machine_id é um texto que a bandeja manda. Com a senha de alguém, dava para
# dizer "sou a máquina dele" de qualquer lugar: o par autorizado reconectava sem
# o administrador, o segredo da bandeja verdadeira era sobrescrito e os PFX da
# carteira iam para quem chamou. A primeira aprovação fixa a chave da máquina;
# depois, sem ela, é equipamento novo.
# ──────────────────────────────────────────────────────────────────────────

def _autorizado(user: str, maquina: str, tipo: str = "principal") -> str:
    segredo, _ = entrar_com(user, maquina, chave(maquina))
    cp.autorizar(pendente(user, maquina)["id"], tipo, ADMIN)
    return segredo


def test_aprovacao_fixa_a_chave_da_maquina(banco: _Fake) -> None:
    _autorizado(FIS, PC_FIS)
    assert banco.tabelas["maquina_chave"][0]["machine_id"] == PC_FIS
    assert chave(PC_FIS) not in str(banco.tabelas["maquina_chave"]), "a chave não fica em claro"


def test_reconexao_sem_a_chave_vira_confirmacao_e_nao_derruba_a_bandeja(banco: _Fake) -> None:
    seg = _autorizado(FIS, PC_FIS)
    segredo, s = entrar_com(FIS, PC_FIS, CHAVE_DE_OUTRO_LUGAR)
    assert segredo is None and s["autorizacao"] == "pendente"
    assert agent_devices.autenticar(seg) is not None, "a bandeja verdadeira foi derrubada"
    assert pendente(FIS, PC_FIS)["motivo"] == cp.MOTIVO_CONFIRMACAO, "o admin precisa ver o pedido de confirmação"
    # Tentar de novo com outra chave (ou sem) não troca a chave do pedido aberto.
    with pytest.raises(cp.OutroDispositivo):
        entrar_com(FIS, PC_FIS, None)
    assert agent_devices.autenticar(seg) is not None


def test_reconexao_com_a_chave_entra_na_hora(banco: _Fake) -> None:
    _autorizado(FIS, PC_FIS)
    segredo, s = entrar_com(FIS, PC_FIS, chave(PC_FIS))
    assert segredo and s["autorizacao"] == "autorizado"


def test_registro_remoto_nao_derruba_quem_esta_na_maquina(banco: _Fake) -> None:
    """Achado app/computadores.py:ao_entrar:revoga-bandeja-alheia-por-machine-id:
    qualquer conta derrubava a bandeja de outra pessoa dizendo o machine_id dela."""
    _autorizado(FIS, PC_FIS)
    entrar_com(SOL, PC_FIS, None)
    assert sessoes(banco, FIS) == [PC_FIS]


def test_pedido_pendente_com_chave_nao_aceita_outro_dispositivo(banco: _Fake) -> None:
    entrar_com(FIS, PC_FIS, chave(PC_FIS))
    with pytest.raises(cp.OutroDispositivo):
        entrar_com(FIS, PC_FIS, CHAVE_DE_OUTRO_LUGAR)


def test_bandeja_antiga_sem_chave_tem_um_reacesso_depois_de_cada_confirmacao(banco: _Fake) -> None:
    """Até a frota ter a 2.1.4: aprovar sem chave libera UMA reconexão em 1 hora."""
    entrar_com(FIS, PC_FIS, None)
    cp.autorizar(pendente(FIS, PC_FIS)["id"], "principal", ADMIN)
    segredo, s = entrar_com(FIS, PC_FIS, None)
    assert segredo and s["autorizacao"] == "autorizado"
    segredo, s = entrar_com(FIS, PC_FIS, None)
    assert segredo is None and s["autorizacao"] == "pendente", "a janela vale uma vez só"
    cp.autorizar(pendente(FIS, PC_FIS)["id"], "principal", ADMIN)
    assert entrar_com(FIS, PC_FIS, None)[0], "confirmado de novo, reconecta"


# ──────────────────────────────────────────────────────────────────────────
# Auditoria run-2 (12/10/2026): a aprovação confere a chave já fixada, e o
# pedido importado do Hardlyze fica com a chave da primeira bandeja.
# ──────────────────────────────────────────────────────────────────────────

def test_aprovar_pedido_com_chave_diferente_exige_trocar_a_chave(banco: _Fake) -> None:
    seg_fis = _autorizado(FIS, PC_FIS)
    fixada = cp.chave_fixada(PC_FIS)
    entrar_com(SOL, PC_FIS, CHAVE_DE_OUTRO_LUGAR)  # outra conta, de outro lugar, com o nome da máquina
    pedido = pendente(SOL, PC_FIS)
    with pytest.raises(cp.ChaveDiferente):
        cp.autorizar(pedido["id"], "emprestimo", ADMIN, "fim_do_dia")
    assert cp.chave_fixada(PC_FIS) == fixada, "a chave da máquina não pode mudar sem o admin confirmar"
    assert agent_devices.autenticar(seg_fis) is not None, "quem está na máquina continua"
    # Reinstalação de verdade: o admin confirma a troca.
    cp.autorizar(pedido["id"], "emprestimo", ADMIN, "fim_do_dia", trocar_chave=True)
    assert cp.chave_fixada(PC_FIS) == cp.hash_da_chave(CHAVE_DE_OUTRO_LUGAR)


def test_aprovar_sem_chave_em_maquina_com_chave_nao_abre_a_janela(banco: _Fake) -> None:
    _autorizado(FIS, PC_FIS)
    segredo, s = entrar_com(FIS, PC_FIS, None)  # só a senha, sem a chave
    assert segredo is None and s["confirmacao"]
    with pytest.raises(cp.ChaveDiferente):
        cp.autorizar(pendente(FIS, PC_FIS)["id"], "principal", ADMIN)
    assert entrar_com(FIS, PC_FIS, None)[0] is None, "sem a confirmação explícita, nenhuma janela sem chave"
    # Trocar explicitamente: a chave antiga sai e abre a reconexão de uma hora.
    cp.autorizar(pendente(FIS, PC_FIS)["id"], "principal", ADMIN, trocar_chave=True)
    assert cp.chave_fixada(PC_FIS) is None
    assert entrar_com(FIS, PC_FIS, None)[0]


def test_pedido_importado_fica_com_a_chave_da_primeira_bandeja(banco: _Fake) -> None:
    """A importação do Hardlyze saiu em 14/10/2026, mas os pedidos sem chave que
    ela criou podem continuar no banco: a primeira bandeja que entra fixa a dela."""
    cp._banco().table(cp.TABELA).insert({
        "user_id": FIS, "machine_id": PC_FIS, "nome": "PC FIS", "tipo": cp.PRINCIPAL, "estado": cp.PENDENTE,
        "pedido_em": "2026-10-01T00:00:00+00:00", "decidido_por": "",
        "motivo": "Importado do Hardlyze (login da bandeja antiga).",
    }).execute()
    assert pendente(FIS, PC_FIS) and not pendente(FIS, PC_FIS).get("chave_hash")
    entrar_com(FIS, PC_FIS, chave(PC_FIS))
    assert pendente(FIS, PC_FIS)["chave_hash"] == cp.hash_da_chave(chave(PC_FIS))
    with pytest.raises(cp.OutroDispositivo):
        entrar_com(FIS, PC_FIS, CHAVE_DE_OUTRO_LUGAR)
    cp.autorizar(pendente(FIS, PC_FIS)["id"], "principal", ADMIN)
    assert cp.chave_fixada(PC_FIS) == cp.hash_da_chave(chave(PC_FIS)), "a aprovação fixa a chave da bandeja que estava lá"
