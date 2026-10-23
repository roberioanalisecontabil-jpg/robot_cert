"""Atualização automática do CertGuard Análise (1.1.0, 20/10/2026): o portal,
a tarefa agendada e o instalador.

O fluxo do atualizador e o formato do manifesto têm os próprios arquivos
(test_estacao_atualizador.py, test_estacao_manifesto.py). Aqui:

  * as rotas são abertas mesmo com o portal fechado (API_KEY), entregam só o
    vigente e respondem 204 sem publicação; o evento exige a chave da máquina;
  * a bandeja `certguard-*` se compara com a versão publicada, não com o
    agente do servidor (até 20/10 toda bandeja aparecia desatualizada);
  * a tarefa confirma só depois de o portal responder, e não dispara nada
    quando ele não responde;
  * o instalador tranca a pasta, guarda a si mesmo, cria as duas tarefas, não
    abre a bandeja em silêncio e declara a mesma versão do pacote.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

RAIZ = Path(__file__).resolve().parents[1]
CONTEUDO = b"MZ-certguard-1.1.1" * 40
SHA = hashlib.sha256(CONTEUDO).hexdigest()


@pytest.fixture
def publicada(tmp_path, monkeypatch) -> Path:
    monkeypatch.setattr("app.config.ATUALIZACOES_DIR", tmp_path, raising=False)
    pasta = tmp_path / "certificados"
    pasta.mkdir()
    (pasta / "Instalador_CertguardAnalise_1.1.1.exe").write_bytes(CONTEUDO)
    pacote = {"manifesto": {"produto": "certificados", "versao": "1.1.1",
                            "arquivo": "Instalador_CertguardAnalise_1.1.1.exe", "sha256": SHA,
                            "tamanho": len(CONTEUDO), "pode_voltar": False,
                            "publicado_em": "2026-10-20T12:00:00Z"},
              "chave": "principal", "assinatura": "x"}
    (pasta / "vigente.json").write_text(json.dumps(pacote), encoding="utf-8")
    return pasta


# ── Portal ────────────────────────────────────────────────────────────────


def test_sem_publicacao_responde_204(client_com_chave: TestClient, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("app.config.ATUALIZACOES_DIR", tmp_path, raising=False)
    assert client_com_chave.get("/api/estacao/atualizacao").status_code == 204


def test_rotas_abertas_entregam_so_o_vigente(client_com_chave: TestClient, publicada: Path) -> None:
    """Sem X-API-Key nem sessão: quem pede é a tarefa SYSTEM, sem conta."""
    r = client_com_chave.get("/api/estacao/atualizacao")
    assert r.status_code == 200 and r.json()["manifesto"]["versao"] == "1.1.1"
    r = client_com_chave.get(f"/api/estacao/atualizacao/arquivo/{SHA}")
    assert r.status_code == 200 and r.content == CONTEUDO
    assert client_com_chave.get("/api/estacao/atualizacao/arquivo/" + "0" * 64).status_code == 404


def test_vigente_ilegivel_e_503(client_com_chave: TestClient, publicada: Path) -> None:
    (publicada / "vigente.json").write_text("{", encoding="utf-8")
    assert client_com_chave.get("/api/estacao/atualizacao").status_code == 503
    (publicada / "vigente.json").write_text(json.dumps({"manifesto": {
        "arquivo": "../../x.exe", "sha256": SHA, "versao": "1.1.1"}}), encoding="utf-8")
    assert client_com_chave.get("/api/estacao/atualizacao").status_code == 503


def test_teto_por_endereco(client_com_chave: TestClient, publicada: Path, monkeypatch) -> None:
    from app.rotas import atualizacao

    monkeypatch.setattr(atualizacao, "_TETO_ARQUIVO", (2, 3600))
    url = f"/api/estacao/atualizacao/arquivo/{SHA}"
    assert [client_com_chave.get(url).status_code for _ in range(3)] == [200, 200, 429]


def test_evento_exige_a_chave_da_maquina(client_com_chave: TestClient, monkeypatch) -> None:
    from app import computadores

    fixada = computadores.hash_da_chave("k" * 43)
    monkeypatch.setattr(computadores, "chave_fixada", lambda mid: fixada if mid == "aa:bb" else None)
    corpo = {"machine_id": "aa:bb", "chave": "k" * 43, "de": "1.1.0", "para": "1.1.1", "resultado": "atualizou"}
    assert client_com_chave.post("/api/estacao/atualizacao/evento", json=corpo).status_code == 200
    errada = {**corpo, "chave": "z" * 43}
    assert client_com_chave.post("/api/estacao/atualizacao/evento", json=errada).status_code == 403
    outra = {**corpo, "machine_id": "cc:dd"}
    assert client_com_chave.post("/api/estacao/atualizacao/evento", json=outra).status_code == 403


@pytest.mark.parametrize(
    ("instalada", "publicada", "esperado"),
    [
        ("certguard-1.1.0", "1.1.1", True),
        ("certguard-1.1.1", "1.1.1", False),
        ("certguard-1.2.0", "1.1.1", False),  # a estação de teste, à frente
        ("certguard-1.0.1", None, False),     # sem publicação não se afirma nada
        ("", "1.1.1", False),
        ("2.1.4", None, True),                # bandeja do Hardlyze: regra antiga
    ],
)
def test_bandeja_certguard_compara_com_a_publicada(instalada, publicada, esperado) -> None:
    from app import agent_devices

    assert agent_devices._desatualizada(instalada, "1.7.1", publicada) is esperado


# ── A tarefa ─────────────────────────────────────────────────────────────


def test_tarefa_nao_confirma_sem_portal(tmp_path, monkeypatch) -> None:
    """A confirmação afirma que a versão nova alcança o portal."""
    from estacao import atualizador, tarefa

    monkeypatch.setattr(tarefa, "configurar_log", lambda nome: None)
    monkeypatch.setattr(tarefa, "_unica", lambda: True)  # a trava é do processo, e o pytest é um só
    monkeypatch.setattr(tarefa, "pastas", lambda: atualizador.Pastas(str(tmp_path)))
    atualizador.gravar_json(str(tmp_path / "pedido.json"), {"estado": atualizador.INSTALADO, "para": tarefa.VERSAO})

    def sem_portal(http):
        raise ConnectionError("fora do ar")

    monkeypatch.setattr(tarefa, "buscar_pacote", sem_portal)
    assert tarefa.rodar_tarefa() == 1
    assert atualizador.ler_json(str(tmp_path / "pedido.json"))["estado"] == atualizador.INSTALADO


def test_tarefa_confirma_e_confere(tmp_path, monkeypatch) -> None:
    from estacao import atualizador, tarefa

    monkeypatch.setattr(tarefa, "configurar_log", lambda nome: None)
    monkeypatch.setattr(tarefa, "_unica", lambda: True)  # a trava é do processo, e o pytest é um só
    monkeypatch.setattr(tarefa, "pastas", lambda: atualizador.Pastas(str(tmp_path)))
    atualizador.gravar_json(str(tmp_path / "pedido.json"),
                            {"estado": atualizador.INSTALADO, "de": "1.0.1", "para": tarefa.VERSAO})
    contados = []
    monkeypatch.setattr(tarefa, "buscar_pacote", lambda http: None)
    monkeypatch.setattr(tarefa, "contar_ao_portal", lambda http, *a: contados.append(a))
    assert tarefa.rodar_tarefa() == 0
    assert atualizador.ler_json(str(tmp_path / "pedido.json"))["estado"] == atualizador.CONFIRMADO
    assert contados == [("atualizou", "1.0.1", tarefa.VERSAO, "")]


def test_instalador_prepara_pasta_copia_e_tarefas(tmp_path, monkeypatch) -> None:
    from estacao import atualizador, tarefa

    monkeypatch.setattr(tarefa, "pastas", lambda: atualizador.Pastas(str(tmp_path / "atualizacoes")))
    instalador = tmp_path / "Instalador_CertguardAnalise_1.1.0.exe"
    instalador.write_bytes(b"MZ-1.1.0")
    comandos = []
    exe = r"C:\Program Files\Certguard Analise\certguard_analise.exe"
    codigo = tarefa.preparar_atualizacao(str(instalador), exe, executar=lambda c: comandos.append(c) or 0)

    assert codigo == 0
    assert (tmp_path / "atualizacoes" / "instalado.exe").read_bytes() == b"MZ-1.1.0"
    icacls = [c for c in comandos if c[0] == "icacls"]
    assert any("/setowner" in c for c in icacls) and any("/inheritance:r" in c for c in icacls)
    tarefas = [c for c in comandos if c[0] == "schtasks"]
    assert [c[4] for c in tarefas] == [tarefa.NOME_TAREFA, tarefa.NOME_TAREFA + " 6h"]
    for c in tarefas:
        assert c[c.index("/RU") + 1] == "SYSTEM"
        assert c[c.index("/TR") + 1] == f'"{exe}" --atualizacao'


def test_instalador_sem_pasta_trancada_nao_segue(tmp_path, monkeypatch) -> None:
    from estacao import atualizador, tarefa

    monkeypatch.setattr(tarefa, "pastas", lambda: atualizador.Pastas(str(tmp_path / "atualizacoes")))
    comandos = []
    codigo = tarefa.preparar_atualizacao(str(tmp_path / "x.exe"), "c.exe",
                                         executar=lambda c: comandos.append(c) or (1 if c[0] == "icacls" else 0))
    assert codigo == 1 and not any(c[0] == "schtasks" for c in comandos)


# ── O instalador e o build ───────────────────────────────────────────────


def test_instalador_da_atualizacao_automatica() -> None:
    from estacao import VERSAO, tarefa

    iss = (RAIZ / "estacao_setup.iss").read_text(encoding="utf-8-sig")
    assert f'#define MyAppVersion "{VERSAO}"' in iss
    assert "VersionInfoVersion={#MyAppVersion}" in iss
    assert f'#define NomeTarefa "{tarefa.NOME_TAREFA}"' in iss
    assert "--preparar-atualizacao" in iss and "{srcexe}" in iss
    assert "/Run /TN" in iss and '/Delete /F /TN "{#NomeTarefa} 6h"' in iss
    corre = next(linha for linha in iss.splitlines() if linha.startswith('Filename: "{app}\\{#MyAppExeName}"'))
    assert "skipifsilent" in corre, "em silêncio a bandeja abriria na sessão invisível do SYSTEM"


def test_build_leva_os_modulos_da_atualizacao() -> None:
    spec = (RAIZ / "CertguardAnalise.spec").read_text(encoding="utf-8")
    for modulo in ("estacao.manifesto", "estacao.atualizador", "estacao.tarefa", "estacao.sessoes",
                   "win32ts", "cryptography.hazmat.primitives.asymmetric.ed25519"):
        assert f'"{modulo}"' in spec, modulo
