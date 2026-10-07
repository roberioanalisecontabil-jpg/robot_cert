"""Cliente da API do SIEG (app/sieg_api.py) contra um SIEG falso com estado."""

from __future__ import annotations

import pytest

from app.sieg_api import ClienteSieg, Credenciais, SiegErro, uf_normalizada
from tests.sieg_falso import SiegFalso

DOC = "18341154000102"
PFX = b"\x30\x82pfx-bytes"


def _incluir(sieg: SiegFalso, **kw):
    return sieg.cliente().incluir(nome="BARATEIRO ALIMENTOS LTDA", documento=DOC, pfx=PFX, senha="s3nh4", **kw)


def test_cadastro_novo_confere_na_listagem() -> None:
    sieg = SiegFalso()
    r = _incluir(sieg)
    assert r.ok and r.operacao == "cadastrar" and r.certificado_id == f"20929-{DOC}"
    p = sieg.payloads[0]
    assert p["UfCertificado"] == "27" and p["ConsultaNfce"] is False and p["DiasRetroativos"] == 30
    assert p["Nome"] == "BARATEIRO ALIMENTOS LTDA" and p["TipoCertificado"] == "Pfx"
    assert "/api/v1/listar" in sieg.chamadas[sieg.chamadas.index("/api/v1/registrar"):]


def test_falso_sucesso_vira_erro() -> None:
    sieg = SiegFalso()
    sieg.falso_sucesso = True
    r = _incluir(sieg)
    assert not r.ok and "falso sucesso" in r.mensagem


def test_opcao_recusada_e_desligada_e_repetida() -> None:
    sieg = SiegFalso()
    sieg.recusa_nfce = True
    r = _incluir(sieg, padroes={"ConsultaNfce": True})
    assert r.ok and r.opcoes_desabilitadas == ["ConsultaNfce"]
    assert r.avisos and "ConsultaNfce" in r.avisos[0]
    assert [p["ConsultaNfce"] for p in sieg.payloads] == [True, False]


def test_cnpj_ja_cadastrado_atualiza_o_arquivo() -> None:
    sieg = SiegFalso()
    sieg.cadastro(DOC, "BARATEIRO ALIMENTOS LTDA")
    r = _incluir(sieg)
    assert r.ok and r.operacao == "atualizar"
    assert "/api/v1/registrar" not in sieg.chamadas and sieg.payloads[0]["CertificadoId"] == f"20929-{DOC}"


def test_cadastro_inativo_e_atualizado_e_reativado() -> None:
    sieg = SiegFalso()
    sieg.cadastro(DOC, "BARATEIRO", ativo=False)
    r = _incluir(sieg)
    assert r.ok and r.operacao == "atualizar" and "/api/v1/habilitar" in sieg.chamadas
    assert any("reativado" in a for a in r.avisos)


def test_procuracao_perde_para_o_cadastro_principal() -> None:
    sieg = SiegFalso()
    sieg.cadastros.append({"Id": "p-1", "CnpjCpf": DOC, "Nome": "PROCURACAO BARATEIRO", "Ativo": True, "Deletado": False})
    sieg.cadastros.append({"Id": "p-2", "CnpjCpf": DOC, "Nome": "BARATEIRO ALIMENTOS LTDA", "Ativo": True, "Deletado": False})
    r = _incluir(sieg)
    assert r.ok and r.certificado_id == "p-2"


def test_cadastro_excluido_e_recuperado() -> None:
    sieg = SiegFalso()
    sieg.cadastro(DOC, "BARATEIRO", ativo=False, deletado=True)
    r = _incluir(sieg)
    assert r.ok and r.operacao == "recuperar_deletado"
    assert any("recuperado" in a for a in r.avisos)


def test_cadastro_excluido_que_nao_volta_explica_o_que_fazer() -> None:
    sieg = SiegFalso()
    sieg.cadastro(DOC, "BARATEIRO", ativo=False, deletado=True)
    sieg.habilitar_falha = True
    r = _incluir(sieg)
    assert not r.ok and "Restaure no painel do SIEG" in r.mensagem


def test_credenciais_recusadas_e_incompletas() -> None:
    sieg = SiegFalso()
    sieg.jwt_recusa = True
    with pytest.raises(SiegErro, match="Client ID"):
        _incluir(sieg)
    with pytest.raises(SiegErro, match="incompletas"):
        ClienteSieg(Credenciais("a", "", "c"))


def test_situacao_para_a_reconciliacao() -> None:
    sieg = SiegFalso()
    assert sieg.cliente().situacao(DOC)[0] == "ausente"
    sieg.cadastro(DOC, ativo=False)
    assert sieg.cliente().situacao(DOC)[0] == "inativo"
    sieg.cadastros[0]["Ativo"] = True
    estado, item = sieg.cliente().situacao(DOC)
    assert estado == "ativo" and item["Id"] == f"20929-{DOC}"


def test_listagem_paginada_e_testar() -> None:
    sieg = SiegFalso()
    for i in range(150):
        sieg.cadastro(f"{i:014d}")
    assert len(sieg.cliente().cadastros()) == 150
    assert sieg.cliente().testar() == 100


def test_uf() -> None:
    assert uf_normalizada(27) == "27" and uf_normalizada("2704302") == "27" and uf_normalizada("al") == "AL"
