"""Cliente que renovou: o Acompanhamento mostra o certificado VÁLIDO.

Relatado em 22/08: o CNPJ 33.706.943/0001-93 aparecia como **vencido** havendo
um certificado válido até 2027. O dano é concreto — sugere renovar o que acabou
de ser renovado.

A causa não estava na regra de escolha, que já preferia válido sobre vencido.
Estava na FONTE: `_lista_base_docs_historico` lia `cert_history`, que faz upsert
por `file_name` — e o fluxo normal do escritório produz dois arquivos com o
mesmo nome, o novo na pasta de trabalho e o antigo movido para
`99.CERTIFICADOS VENCIDOS`. Os dois colidiam numa linha só e sobrava o último
processado. Medido em produção: **7 nomes repetidos, 5 deles com um válido e um
vencido**.

A regra nunca chegava a rodar porque o válido não estava na base.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

import pytest

import app.main as m


def _arquivo(nome: str, doc: str, status: str, dias: int, pasta: str) -> dict:
    """Dois arquivos podem ter o MESMO `file_name` em pastas diferentes — é
    exatamente o que acontece quando um certificado é renovado."""
    venc = datetime.now(timezone.utc) + timedelta(days=dias)
    return {
        "nome": nome,
        "display_name": nome,
        "status": status,
        "not_after": venc.isoformat(),
        "documento_numero": doc,
        "documento_formatado": doc,
        "file_name": f"{nome}_{doc}.pfx",
        "path": f"F:\\\\CERTIFICADOS\\\\{pasta}\\\\{nome}_{doc}.pfx",
        "fingerprint_sha256": f"fp-{pasta}-{doc}",
    }


@pytest.fixture
def inventario(monkeypatch: pytest.MonkeyPatch):
    def _usar(itens: List[Dict[str, Any]]):
        monkeypatch.setattr(m, "load_settings", lambda: object())
        monkeypatch.setattr(m, "get_latest_snapshot", lambda *a, **k: None)
        monkeypatch.setattr(
            m, "_list_certificados_payload", lambda *a, **k: {"itens": list(itens)}
        )
    return _usar


DOC = "33706943000193"


def test_renovado_mostra_o_valido_e_nao_o_vencido(inventario) -> None:
    """O caso relatado, com os dois arquivos de mesmo nome."""
    inventario([
        _arquivo("ANALISE", DOC, "ok", 349, "00.REVISAR"),
        _arquivo("ANALISE", DOC, "expirado", -3, "99.CERTIFICADOS VENCIDOS"),
    ])
    [r] = m._painel_docs_selecionados([DOC])
    assert r["status"] == "ativo", r
    assert r["dias_restantes"] > 0


def test_a_ordem_dos_arquivos_nao_muda_o_resultado(inventario) -> None:
    """O defeito antigo dependia de qual arquivo era processado por último.

    Se a escolha voltar a depender da ordem, este teste falha numa das duas
    montagens — e um teste que só passa numa ordem esconde exatamente isso.
    """
    for ordem in ("valido_primeiro", "vencido_primeiro"):
        itens = [
            _arquivo("ANALISE", DOC, "ok", 349, "00.REVISAR"),
            _arquivo("ANALISE", DOC, "expirado", -3, "99.VENCIDOS"),
        ]
        if ordem == "vencido_primeiro":
            itens.reverse()
        inventario(itens)
        [r] = m._painel_docs_selecionados([DOC])
        assert r["status"] == "ativo", (ordem, r)


def test_entre_dois_validos_vence_a_validade_mais_distante(inventario) -> None:
    """A pergunta que o painel responde é "até quando este cliente está coberto"."""
    inventario([
        _arquivo("ACME", DOC, "ok", 100, "PASTA_A"),
        _arquivo("ACME", DOC, "ok", 400, "PASTA_B"),
    ])
    [r] = m._painel_docs_selecionados([DOC])
    assert 395 <= r["dias_restantes"] <= 401, r


def test_entre_dois_vencidos_vence_o_que_venceu_por_ultimo(inventario) -> None:
    """O mais próximo de ainda valer, e o que a pessoa reconhece."""
    inventario([
        _arquivo("ACME", DOC, "expirado", -400, "ANTIGO"),
        _arquivo("ACME", DOC, "expirado", -5, "RECENTE"),
    ])
    [r] = m._painel_docs_selecionados([DOC])
    assert r["status"] == "vencido"
    assert -8 <= r["dias_restantes"] <= -3, r


def test_ilegivel_perde_para_qualquer_certificado_que_se_leia(inventario) -> None:
    """Um arquivo que o robô não conseguiu ler não descreve a cobertura do
    cliente, e não pode ocultar um que descreve."""
    inventario([
        _arquivo("ACME", DOC, "fora_do_padrao", 0, "REVISAR"),
        _arquivo("ACME", DOC, "expirado", -10, "VENCIDOS"),
    ])
    [r] = m._painel_docs_selecionados([DOC])
    assert r["status"] == "vencido", r


def test_documento_ausente_do_inventario_continua_dizendo_isso(inventario) -> None:
    """"Não encontrado" é diferente de "vencido", e a distinção precisa
    sobreviver à troca de fonte."""
    inventario([])
    [r] = m._painel_docs_selecionados([DOC])
    assert r["status"] == "nao_encontrado"
    assert r["vencimento_certificado"] is None
