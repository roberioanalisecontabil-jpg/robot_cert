"""Atualização automática do Certguard Análise, lado da estação (1.1.0).

Vieram do Hardlyze (tests/test_atualizador_do_agente.py); as versões dos
exemplos (2.2.x) ficaram as de lá, só o produto e os nomes mudaram.

O fluxo inteiro, sem Windows nem portal: rede, instalador e relógio entram
por parâmetro. O que este arquivo prende:

  * manifesto que não confere nunca leva a instalar;
  * instalador baixado que não bate com o manifesto é descartado;
  * caminho feliz: baixa, instala, a versão nova confirma, o portal ouve
    "atualizou";
  * a versão nova não confirma em 10 min: volta para a anterior, bloqueia a
    versão (sem laço) e o portal ouve "voltou";
  * o instalador falha: volta também;
  * sem anterior guardada, ou a volta falha: "falhou", e o portal ouve;
  * pedido parado de uma máquina desligada caduca;
  * rebaixamento só com pode_voltar, e aí a versão bloqueada não impede.
"""

from __future__ import annotations

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from estacao import atualizador as at
from estacao import manifesto as mf

CONTEUDO = b"MZ-instalador-2.2.1" * 50


@pytest.fixture
def chave(monkeypatch):
    privada = Ed25519PrivateKey.generate()
    monkeypatch.setattr(mf, "CHAVES_PUBLICAS", {"principal": mf.chave_publica_b64(privada)})
    return privada


@pytest.fixture
def pastas(tmp_path):
    p = at.Pastas(str(tmp_path / "atualizacoes"))
    import os

    os.makedirs(p.raiz)
    with open(p.instalado, "wb") as f:
        f.write(b"MZ-instalador-2.2.0")
    return p


def _pacote(privada, versao="2.2.1", conteudo=CONTEUDO, pode_voltar=False):
    import hashlib

    m = {
        "produto": "certificados",
        "versao": versao,
        "arquivo": f"Instalador_CertguardAnalise_{versao}.exe",
        "sha256": hashlib.sha256(conteudo).hexdigest(),
        "tamanho": len(conteudo),
        "pode_voltar": pode_voltar,
        "publicado_em": "2026-10-11T12:00:00Z",
    }
    return mf.assinar(m, privada, "principal")


def _baixar(conteudo=CONTEUDO):
    def baixar(_sha, destino):
        with open(destino, "wb") as f:
            f.write(conteudo)

    return baixar


def _rodada(pastas, pacote, *, baixar=None, versao="2.2.0", agora=lambda: 1000.0):
    disparos = []
    r = at.verificar_e_disparar(
        pastas=pastas,
        versao_atual=versao,
        buscar_pacote=lambda: pacote,
        baixar=baixar or _baixar(),
        disparar=disparos.append,
        agora=agora,
    )
    return r, disparos


def test_servidor_nao_se_atualiza_sozinho(pastas) -> None:
    baixados = []
    r = at.verificar_e_disparar(
        pastas=pastas,
        versao_atual="2.2.0",
        buscar_pacote=lambda: pytest.fail("servidor nem consulta o portal"),
        baixar=lambda *a: baixados.append(a),
        disparar=lambda _p: pytest.fail("servidor não dispara"),
        estacao=lambda: False,
    )
    assert r == "servidor: atualização manual"
    assert baixados == []


class _Relogio:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def esperar(self, s):
        self.t += s


# ── A tarefa decide e dispara ────────────────────────────────────────────


def test_manifesto_falso_nao_dispara(pastas, chave) -> None:
    intrusa = Ed25519PrivateKey.generate()
    r, disparos = _rodada(pastas, _pacote(intrusa))
    assert r == "manifesto recusado"
    assert disparos == []


def test_download_que_nao_confere_e_descartado(pastas, chave) -> None:
    r, disparos = _rodada(pastas, _pacote(chave), baixar=_baixar(b"MZ-adulterado" * 76))
    assert r == "download não confere"
    assert disparos == []
    assert at.ler_json(pastas.pedido) is None


def test_em_dia_nao_faz_nada(pastas, chave) -> None:
    r, disparos = _rodada(pastas, _pacote(chave, versao="2.2.0"))
    assert (r, disparos) == ("em dia", [])


def test_sem_versao_publicada(pastas, chave) -> None:
    r, _ = _rodada(pastas, None)
    assert r == "sem versão publicada"


def test_baixa_grava_pedido_e_dispara(pastas, chave) -> None:
    r, disparos = _rodada(pastas, _pacote(chave))
    assert r == "atualizar"
    assert disparos == [pastas.pedido]
    pedido = at.ler_json(pastas.pedido)
    assert (pedido["estado"], pedido["de"], pedido["para"]) == (at.BAIXADO, "2.2.0", "2.2.1")
    with open(pedido["instalador"], "rb") as f:
        assert f.read() == CONTEUDO


def test_pedido_em_andamento_nao_dispara_de_novo(pastas, chave) -> None:
    _rodada(pastas, _pacote(chave))
    r, disparos = _rodada(pastas, _pacote(chave), agora=lambda: 1060.0)
    assert (r, disparos) == ("pedido em andamento", [])


def test_pedido_parado_caduca(pastas, chave) -> None:
    _rodada(pastas, _pacote(chave))
    r, disparos = _rodada(pastas, _pacote(chave), agora=lambda: 1000.0 + at.PEDIDO_CADUCA_SEG + 1)
    assert r == "atualizar"
    assert len(disparos) == 1


# ── O atualizador e a versão nova ────────────────────────────────────────


def _atualizar(pastas, instalar, relogio=None, confirma_em=None, versao_nova="2.2.1"):
    """Roda o atualizador; se `confirma_em` (s), a "versão nova" confirma ali."""
    relogio = relogio or _Relogio()
    contados = []

    def esperar(s):
        relogio.esperar(s)
        if confirma_em is not None and relogio.t >= confirma_em:
            at.confirmar_na_partida(
                pastas=pastas, versao_atual=versao_nova, contar=lambda *a: contados.append(a)
            )

    final = at.executar_pedido(pastas=pastas, instalar=instalar, esperar=esperar, relogio=relogio)
    return final, contados


def test_caminho_feliz(pastas, chave) -> None:
    _rodada(pastas, _pacote(chave))
    instalados = []
    final, contados = _atualizar(pastas, lambda c: instalados.append(c) or 0, confirma_em=60)

    assert final == at.CONFIRMADO
    assert instalados == [pastas.novo("Instalador_CertguardAnalise_2.2.1.exe")]
    assert contados == [("atualizou", "2.2.0", "2.2.1", "")]
    # A anterior foi guardada antes de instalar.
    with open(pastas.anterior, "rb") as f:
        assert f.read() == b"MZ-instalador-2.2.0"
    # A próxima partida limpa o pedido confirmado sem contar de novo.
    contados2 = []
    at.confirmar_na_partida(
        pastas=pastas, versao_atual="2.2.1", contar=lambda *a: contados2.append(a)
    )
    assert contados2 == [] and at.ler_json(pastas.pedido) is None


def test_versao_que_nao_sobe_volta_e_fica_bloqueada(pastas, chave) -> None:
    _rodada(pastas, _pacote(chave))
    instalados = []
    final, _ = _atualizar(pastas, lambda c: instalados.append(c) or 0, confirma_em=None)

    assert final == at.VOLTOU
    assert instalados == [pastas.novo("Instalador_CertguardAnalise_2.2.1.exe"), pastas.anterior]
    assert "2.2.1" in at.versoes_bloqueadas(pastas)

    # A versão antiga, de volta, conta ao portal e limpa o pedido.
    contados = []
    at.confirmar_na_partida(
        pastas=pastas, versao_atual="2.2.0", contar=lambda *a: contados.append(a)
    )
    assert contados[0][:3] == ("voltou", "2.2.1", "2.2.0")
    assert at.ler_json(pastas.pedido) is None

    # E não baixa a mesma versão quebrada de novo (sem laço).
    r, disparos = _rodada(pastas, _pacote(chave))
    assert (r, disparos) == ("versão bloqueada", [])


def test_espera_dez_minutos_antes_de_voltar(pastas, chave) -> None:
    _rodada(pastas, _pacote(chave))
    relogio = _Relogio()
    _atualizar(pastas, lambda c: 0, relogio=relogio, confirma_em=None)
    assert at.ESPERA_CONFIRMACAO_SEG <= relogio.t < at.ESPERA_CONFIRMACAO_SEG + 20


def test_confirmacao_no_minuto_nove_nao_volta(pastas, chave) -> None:
    _rodada(pastas, _pacote(chave))
    final, _ = _atualizar(pastas, lambda c: 0, confirma_em=540)
    assert final == at.CONFIRMADO


def test_instalador_que_falha_volta(pastas, chave) -> None:
    _rodada(pastas, _pacote(chave))
    codigos = iter([5, 0])
    final, _ = _atualizar(pastas, lambda c: next(codigos))
    assert final == at.VOLTOU


def test_sem_anterior_guardada_falha_e_conta(pastas, chave) -> None:
    import os

    os.remove(pastas.instalado)
    _rodada(pastas, _pacote(chave))
    final, _ = _atualizar(pastas, lambda c: 0)
    assert final == at.FALHOU
    contados = []
    at.confirmar_na_partida(
        pastas=pastas, versao_atual="2.2.0", contar=lambda *a: contados.append(a)
    )
    assert contados[0][0] == "falhou"


def test_volta_que_falha_conta_falhou(pastas, chave) -> None:
    _rodada(pastas, _pacote(chave))
    codigos = iter([0, 7])
    final, _ = _atualizar(pastas, lambda c: next(codigos))
    assert final == at.FALHOU
    assert "volta também falhou" in at.ler_json(pastas.pedido)["detalhe"]


def test_rebaixamento_assinado_passa_mesmo_bloqueado(pastas, chave) -> None:
    at.bloquear(pastas, "2.1.9")
    r, disparos = _rodada(pastas, _pacote(chave, versao="2.1.9", pode_voltar=True))
    assert r == "voltar"
    assert len(disparos) == 1


def test_rebaixamento_sem_marca_e_recusado(pastas, chave) -> None:
    r, disparos = _rodada(pastas, _pacote(chave, versao="2.1.9"))
    assert (r, disparos) == ("manifesto recusado", [])


def test_atualizador_sem_pedido_nao_instala(pastas) -> None:
    instalados = []
    assert at.executar_pedido(pastas=pastas, instalar=instalados.append) == "sem pedido"
    assert instalados == []


# ── O atualizador roda como SYSTEM: pedido forjado não passa ─────────────


def _forjar(pastas, **muda):
    import json

    pedido = at.ler_json(pastas.pedido)
    pedido.update(muda)
    with open(pastas.pedido, "w", encoding="utf-8") as f:
        json.dump(pedido, f)


def _malicioso(pastas):
    import os

    caminho = os.path.join(pastas.raiz, "malicioso.exe")
    with open(caminho, "wb") as f:
        f.write(b"MZ-de-quem-nao-devia")
    return caminho


@pytest.mark.parametrize(
    "forja",
    [
        lambda p, pacote: {"pacote": None},
        lambda p, pacote: {"pacote": {**pacote, "assinatura": "QQ=="}},
        lambda p, pacote: {"instalador": _malicioso(p)},
        lambda p, pacote: {"instalador": r"C:\Windows\System32\cmd.exe"},
        lambda p, pacote: {"para": "9.9.9"},
    ],
    ids=["sem-pacote", "assinatura-falsa", "outro-exe-na-pasta", "fora-da-pasta", "versao-trocada"],
)
def test_pedido_forjado_nao_instala(pastas, chave, forja) -> None:
    pacote = _pacote(chave)
    _rodada(pastas, pacote)
    _forjar(pastas, **forja(pastas, pacote))
    instalados = []
    assert at.executar_pedido(pastas=pastas, instalar=instalados.append) == "pedido recusado"
    assert instalados == []


def test_instalador_trocado_depois_do_download_nao_instala(pastas, chave) -> None:
    _rodada(pastas, _pacote(chave))
    with open(pastas.novo("Instalador_CertguardAnalise_2.2.1.exe"), "wb") as f:
        f.write(b"MZ-trocado" * 95)
    instalados = []
    assert at.executar_pedido(pastas=pastas, instalar=instalados.append) == "pedido recusado"
    assert instalados == []


def test_pasta_que_nao_tranca_nao_baixa(pastas, chave) -> None:
    baixados = []
    r = at.verificar_e_disparar(
        pastas=pastas,
        versao_atual="2.2.0",
        buscar_pacote=lambda: _pacote(chave),
        baixar=lambda sha, d: baixados.append(d),
        disparar=lambda p: None,
        proteger=lambda raiz: False,
    )
    assert r == "pasta desprotegida"
    assert baixados == []


def test_protecao_troca_dono_e_tira_heranca(tmp_path) -> None:
    chamados = []
    assert at.proteger_pasta(str(tmp_path / "x"), lambda c: chamados.append(c) or 0)
    dono, acl = chamados  # pasta vazia: sem o /reset do conteudo
    assert dono[2:4] == ["/setowner", at.SID_ADMINISTRADORES]
    assert "/inheritance:r" in acl
    concessoes = [parte for parte in acl if parte.startswith("*S-")]
    assert concessoes == [f"{at.SID_SYSTEM}:(OI)(CI)F", f"{at.SID_ADMINISTRADORES}:(OI)(CI)F"]
    assert at.proteger_pasta(str(tmp_path / "y"), lambda c: 5) is False


def test_concessao_nao_desce_aos_arquivos(tmp_path) -> None:
    """Ensaio de 12/10/2026: com /T, o /inheritance:r chegava aos arquivos e
    o pedido ficava sem permissao nenhuma, nem para o SYSTEM."""
    pasta = tmp_path / "z"
    pasta.mkdir()
    (pasta / "pedido.json").write_text("{}", encoding="utf-8")
    chamados = []
    assert at.proteger_pasta(str(pasta), lambda c: chamados.append(c) or 0)
    _dono, acl, reset = chamados
    assert "/T" not in acl
    assert reset[1].endswith("*") and "/reset" in reset and "/T" in reset


def test_pedido_ilegivel_nao_vira_sem_pedido(pastas, chave, monkeypatch) -> None:
    _rodada(pastas, _pacote(chave))
    logs = []

    def _negado(_c):
        raise at.ArquivoIlegivel("Acesso negado")

    monkeypatch.setattr(at, "ler_json", _negado)
    r = at.executar_pedido(pastas=pastas, instalar=lambda c: 0, log=logs.append)
    assert r == "pedido ilegível"
    assert any("Acesso negado" in m for m in logs)


def test_ler_json_distingue_inexistente_de_ilegivel(tmp_path, monkeypatch) -> None:
    import builtins

    assert at.ler_json(str(tmp_path / "nao-existe.json")) is None
    alvo = tmp_path / "pedido.json"
    alvo.write_text("{}", encoding="utf-8")
    original = builtins.open

    def _open(caminho, *a, **k):
        if str(caminho) == str(alvo):
            raise PermissionError(13, "Acesso negado")
        return original(caminho, *a, **k)

    monkeypatch.setattr(builtins, "open", _open)
    with pytest.raises(at.ArquivoIlegivel):
        at.ler_json(str(alvo))
