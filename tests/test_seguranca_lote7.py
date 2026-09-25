"""
Lote 7 das correções do SECURITY_AUDIT.md — o agente Windows.

  #18  a X-API-Key em claro em `agent_config.json`, na pasta do programa,
       legível por qualquer usuário da estação
  #46  a tela de Configuração guardava a X-API-Key no `localStorage` do
       navegador, sob a MESMA chave do JWT, e a embutia no arquivo baixado
  #39  o cliente HTTP do agente seguia redirect para outro host levando a
       X-API-Key; `base_url` aceitava http://
  #43  a senha do PFX ia na linha de comando do certutil, visível na tabela
       de processos
  #44  o agente logava o token de instalação inteiro
  #45  o instalador dava `users-modify` na pasta que guarda `maquina.dat`

Cada teste foi escrito antes da correção e falhava em `7232219` (fim do
lote 6). O DPAPI e o `icacls` são substituídos: a suíte roda em qualquer
máquina, e o que se testa é o fluxo, não o Windows.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List

import httpx
import pytest

import agent
from agent import identidade_maquina, run_agent
from app import config

RAIZ = Path(__file__).resolve().parents[1]


@pytest.fixture
def cofre(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """DPAPI virado identidade e ACL registrada: o fluxo sem o Windows."""
    from agent import chave_api

    acls: List[Path] = []
    monkeypatch.setattr(identidade_maquina, "proteger", lambda b: b"DPAPI:" + b)
    monkeypatch.setattr(identidade_maquina, "desproteger", lambda b: b[len(b"DPAPI:"):])
    monkeypatch.setattr(identidade_maquina, "_aplicar_acl", lambda arquivo: acls.append(Path(arquivo)))
    monkeypatch.setattr(chave_api, "caminho", lambda: tmp_path / "Analise CertiDigital Agent" / "chave_api.dat")
    monkeypatch.delenv("CERT_ROBOT_API_KEY", raising=False)
    monkeypatch.delenv("API_KEY", raising=False)
    return {"acls": acls, "pasta": tmp_path}


# ──────────────────────────────────────────────────────────────────────────
# #18 — a chave sai do JSON em claro e vai para o DPAPI com ACL
# ──────────────────────────────────────────────────────────────────────────

def test_chave_guardada_cifrada_e_com_acl(cofre) -> None:
    from agent import chave_api

    destino = chave_api.guardar("chave-secreta-xyz", "https://portal.exemplo")
    assert destino.is_file()
    assert b"chave-secreta-xyz" not in destino.read_bytes() or destino.read_bytes().startswith(b"DPAPI:")
    assert cofre["acls"] == [destino], "sem ACL o arquivo é legível por qualquer conta local"
    assert chave_api.ler() == "chave-secreta-xyz"


def test_sem_acl_nao_fica_arquivo_legivel(cofre, monkeypatch: pytest.MonkeyPatch) -> None:
    from agent import chave_api

    def _falha(arquivo: Path) -> None:
        raise identidade_maquina.SemCofreLocal("icacls indisponível")

    monkeypatch.setattr(identidade_maquina, "_aplicar_acl", _falha)
    with pytest.raises(identidade_maquina.SemCofreLocal):
        chave_api.guardar("chave", "https://p")
    assert not chave_api.caminho().exists()


def test_config_antiga_migra_a_chave_e_reescreve_o_json_sem_ela(cofre, tmp_path: Path, caplog) -> None:
    from agent import chave_api

    cfg = tmp_path / "agent_config.json"
    cfg.write_text(json.dumps({"cert_robot_base_url": "https://portal.exemplo", "cert_robot_api_key": "chave-antiga",
                               "machine_id": "srv"}), encoding="utf-8")
    chave = chave_api.resolver(json.loads(cfg.read_text(encoding="utf-8")), cfg)
    assert chave == "chave-antiga"
    assert chave_api.ler() == "chave-antiga", "a chave tem de ter ido para o cofre"
    novo = json.loads(cfg.read_text(encoding="utf-8"))
    assert "cert_robot_api_key" not in novo, "o JSON em claro tem de perder a chave"
    assert novo["machine_id"] == "srv"
    assert "migrad" in caplog.text.lower()


def test_ordem_de_resolucao_da_chave(cofre, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from agent import chave_api

    chave_api.guardar("do-cofre", "https://p")
    assert chave_api.resolver({}, None) == "do-cofre"
    monkeypatch.setenv("CERT_ROBOT_API_KEY", "do-ambiente")
    assert chave_api.resolver({}, None) == "do-ambiente", "variável de ambiente ganha (é a do serviço)"


def test_sem_chave_em_lugar_nenhum_devolve_vazio(cofre) -> None:
    from agent import chave_api

    assert chave_api.resolver({}, None) == ""


def test_guardar_chave_de_arquivo_consome_o_arquivo(cofre, tmp_path: Path) -> None:
    """É o que o instalador chama: a chave passa por um arquivo temporário do
    admin, nunca pela linha de comando (que fica na tabela de processos)."""
    from agent import chave_api

    arq = tmp_path / "chave.txt"
    arq.write_text("  chave-do-instalador  \n", encoding="utf-8")
    assert run_agent.guardar_chave_de_arquivo(arq, "https://portal.exemplo") is True
    assert chave_api.ler() == "chave-do-instalador"
    assert not arq.exists(), "o arquivo em claro tem de sumir"


def test_cli_aceita_guardar_chave() -> None:
    fonte = (RAIZ / "agent" / "run_agent.py").read_text(encoding="utf-8")
    assert '"--guardar-chave"' in fonte


def test_run_agent_nao_le_mais_a_chave_direto_do_json() -> None:
    fonte = (RAIZ / "agent" / "run_agent.py").read_text(encoding="utf-8")
    assert 'local_cfg.get("cert_robot_api_key")' not in fonte
    assert "chave_api.resolver(" in fonte


def test_exemplo_de_config_nao_tem_mais_a_chave() -> None:
    exemplo = json.loads((RAIZ / "agent" / "agent_config.example.json").read_text(encoding="utf-8"))
    assert "cert_robot_api_key" not in exemplo


# ──────────────────────────────────────────────────────────────────────────
# #46 — a chave sai do navegador e do arquivo baixado
# ──────────────────────────────────────────────────────────────────────────

def test_tela_nao_guarda_chave_no_navegador_nem_no_arquivo_baixado() -> None:
    html = (RAIZ / "templates" / "configuracao.html").read_text(encoding="utf-8")
    assert "btn-save-key" not in html
    assert 'id="api-key"' not in html
    assert "cert_robot_api_key" not in html, "o agent_config.json baixado não leva a chave"
    assert "localStorage.setItem(KEY_STORAGE" not in html, "só o login grava a chave do JWT"
    assert "guardar-chave" in html, "a tela diz como a chave entra na estação"


# ──────────────────────────────────────────────────────────────────────────
# #39 — redirect e https
# ──────────────────────────────────────────────────────────────────────────

def test_redirect_para_outro_host_nao_leva_a_x_api_key() -> None:
    vistos: List[Dict[str, str]] = []

    def responder(request: httpx.Request) -> httpx.Response:
        vistos.append({"host": request.url.host, "chave": request.headers.get("X-API-Key", "")})
        if request.url.host == "portal.exemplo":
            return httpx.Response(302, headers={"Location": "https://outro.exemplo/api/settings"})
        return httpx.Response(200, json={})

    client = run_agent._novo_http_client("https://portal.exemplo")
    client._transport = httpx.MockTransport(responder)
    client._mounts = {}
    with client:
        r = client.get("https://portal.exemplo/api/settings", headers={"X-API-Key": "segredo"})
    assert r.status_code == 200
    assert vistos[0] == {"host": "portal.exemplo", "chave": "segredo"}
    assert vistos[1] == {"host": "outro.exemplo", "chave": ""}, "a credencial foi entregue a outro host"


def test_redirect_no_mesmo_host_mantem_a_chave() -> None:
    vistos: List[str] = []

    def responder(request: httpx.Request) -> httpx.Response:
        vistos.append(request.headers.get("X-API-Key", ""))
        if request.url.scheme == "http":
            return httpx.Response(308, headers={"Location": str(request.url.copy_with(scheme="https"))})
        return httpx.Response(200, json={})

    client = run_agent._novo_http_client("https://portal.exemplo")
    client._transport = httpx.MockTransport(responder)
    client._mounts = {}
    with client:
        client.get("http://portal.exemplo/api/settings", headers={"X-API-Key": "segredo"})
    assert vistos == ["segredo", "segredo"]


@pytest.mark.parametrize("entrada, esperado", [
    ("http://certificado.exemplo", "https://certificado.exemplo"),
    ("http://certificado.exemplo/", "https://certificado.exemplo"),
    ("https://certificado.exemplo", "https://certificado.exemplo"),
    ("http://127.0.0.1:8020", "http://127.0.0.1:8020"),
    ("http://localhost:8020/", "http://localhost:8020"),
])
def test_base_url_so_https_fora_da_propria_maquina(entrada: str, esperado: str, caplog) -> None:
    assert run_agent.normalizar_base_url(entrada) == esperado
    if entrada.startswith("http://certificado"):
        assert "https" in caplog.text.lower()


# ──────────────────────────────────────────────────────────────────────────
# #43 — senha do PFX fora da linha de comando
# ──────────────────────────────────────────────────────────────────────────

def test_senha_nao_vai_na_linha_de_comando(monkeypatch: pytest.MonkeyPatch) -> None:
    from agent.installer_client import _import_pfx_non_exportable

    chamadas: List[Dict[str, Any]] = []

    def run_falso(cmd, **kw):
        chamadas.append({"cmd": list(cmd), "input": kw.get("input", "")})
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", run_falso)
    ok, _ = _import_pfx_non_exportable(b"\x30\x82pfx", "S3nh@'com'aspas")
    assert ok
    cmd, script = chamadas[0]["cmd"], chamadas[0]["input"]
    assert "certutil" not in " ".join(cmd).lower()
    assert "S3nh@" not in " ".join(cmd), "a senha aparecia em `wmic process get CommandLine`"
    assert "S3nh@''com''aspas" in script, "a senha vai pelo stdin, com as aspas escapadas"
    assert "Cert:\\CurrentUser\\My" in script
    assert "-Exportable" not in script, "sem NoExport/não-exportável a chave sai da estação"


def test_pfx_temporario_some_depois_da_importacao(monkeypatch: pytest.MonkeyPatch) -> None:
    from agent.installer_client import _import_pfx_non_exportable

    vistos: Dict[str, Any] = {}

    def run_falso(cmd, **kw):
        m = re.search(r"-FilePath '([^']+)'", kw.get("input", ""))
        p = Path(m.group(1))
        vistos.update(caminho=p, existia=p.is_file())
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", run_falso)
    ok, _ = _import_pfx_non_exportable(b"\x30\x82pfx", "x")
    assert ok and vistos["existia"] and not vistos["caminho"].exists()


# ──────────────────────────────────────────────────────────────────────────
# #44 — token abreviado no log
# ──────────────────────────────────────────────────────────────────────────

def test_token_de_instalacao_nao_vai_inteiro_para_o_log(caplog) -> None:
    from agent.installer_client import process_install_command

    token = "tok-" + "a" * 40

    class _Resp:
        status_code = 200
        text = "{}"

        def json(self):
            return {"certificates": []}

    class _Client:
        def post(self, *a, **k):
            return _Resp()

    with caplog.at_level("DEBUG"):
        assert process_install_command(_Client(), "https://p", {}, token) is False
    assert token not in caplog.text
    assert token[:8] in caplog.text


# ──────────────────────────────────────────────────────────────────────────
# #45 — instalador sem users-modify na pasta da credencial
# ──────────────────────────────────────────────────────────────────────────

def test_instalador_nao_da_escrita_a_usuarios_na_pasta_da_credencial() -> None:
    iss = (RAIZ / "agent_setup.iss").read_text(encoding="utf-8", errors="replace")
    dirs = iss[iss.index("[Dirs]"): iss.index("[Code]")]
    linhas = [l for l in dirs.splitlines() if l.strip().startswith("Name:")]
    raiz = [l for l in linhas if "pedidos" not in l]
    assert raiz and all("users-modify" not in l for l in raiz), "a pasta de maquina.dat/chave_api.dat não pode ser gravável por Users"
    assert any("pedidos" in l and "users-modify" in l for l in linhas), "o tray precisa de UMA subpasta para deixar o pedido"


def test_pedido_do_tray_vai_para_a_subpasta(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROGRAMDATA", r"C:\ProgramData")
    p = run_agent._command_file_path()
    assert p.parent.name == "pedidos"
    assert p.name == "agent_command.json"


def test_instalador_guarda_a_chave_pelo_agente() -> None:
    iss = (RAIZ / "agent_setup.iss").read_text(encoding="utf-8", errors="replace")
    assert "--guardar-chave" in iss
    assert "agent_config.json" in iss
    assert "cert_robot_api_key" not in iss


def test_versao_do_agente_subiu() -> None:
    """Mudança no agente é versão nova: a frota é atualizada e o portal acusa a atrasada."""
    assert agent.__version__ == "1.4.0"
    assert config.VERSAO_AGENTE_ESPERADA == "1.4.0"
