"""
Carregamento do agent_config.json do agente.

Regressão de produção (ANALISESRV, 09-10/08/2026): o arquivo tinha caminhos
Windows sem escape (``"F:\07. CERTIFICADOS"`` → ``\0`` não é escape JSON), o
loader engolia o JSONDecodeError num ``print`` para stderr — invisível num
serviço Windows — e devolvia ``{}``. Sem ``cert_robot_base_url`` o agente caiu
no padrão ``127.0.0.1:8020`` e gerou ~11h de log com WinError 10061 contra um
portal que era remoto. Nada indicava a causa no agent.log.
"""

import json
import logging

import pytest

from agent import run_agent


@pytest.fixture
def config_dir(tmp_path, monkeypatch: pytest.MonkeyPatch):
    """
    Aponta o primeiro candidato do loader (pasta do executável) para tmp_path.

    O loader devolve no primeiro candidato válido, então os demais caminhos
    (pasta do módulo e ROOT) não interferem.
    """
    monkeypatch.setattr(run_agent.sys, "executable", str(tmp_path / "agente.exe"))
    return tmp_path


def _escrever(config_dir, texto: str):
    alvo = config_dir / "agent_config.json"
    alvo.write_text(texto, encoding="utf-8")
    return alvo


def test_le_config_valida(config_dir):
    _escrever(config_dir, json.dumps({"cert_robot_base_url": "http://portal.exemplo"}))

    assert run_agent._load_local_agent_config() == {
        "cert_robot_base_url": "http://portal.exemplo"
    }


def test_recupera_caminhos_windows_sem_escape(config_dir, caplog):
    """O config real de ANALISESRV: barras invertidas cruas nos caminhos."""
    _escrever(
        config_dir,
        """{
  "cert_robot_base_url": "http://certificado.analisegroup.cnt.br",
  "machine_id": "ANALISESRV",
  "source_folder": "F:\\07. CERTIFICADOS\\CERTIFICADOS DIGITAIS - 2024",
  "interval_sec": 86400
}""".replace("\\\\", "\\"),
    )

    with caplog.at_level(logging.WARNING, logger=run_agent.LOGGER.name):
        cfg = run_agent._load_local_agent_config()

    assert cfg["cert_robot_base_url"] == "http://certificado.analisegroup.cnt.br"
    assert cfg["source_folder"] == r"F:\07. CERTIFICADOS\CERTIFICADOS DIGITAIS - 2024"
    assert cfg["interval_sec"] == 86400
    # O usuário precisa saber que o arquivo está errado, mesmo funcionando.
    assert "barras invertidas" in caplog.text


def test_escapes_json_validos_sao_preservados(config_dir):
    """A recuperação não pode estragar \\n, \\" ou \\uXXXX legítimos."""
    _escrever(
        config_dir,
        r'{"a": "linha\nquebra", "b": "aspas\"dentro", "c": "\u00e7edilha", "d": "C:\pasta"}',
    )

    cfg = run_agent._load_local_agent_config()

    assert cfg == {
        "a": "linha\nquebra",
        "b": 'aspas"dentro',
        "c": "çedilha",
        "d": r"C:\pasta",
    }


def test_json_irrecuperavel_loga_erro_e_nao_explode(config_dir, caplog):
    _escrever(config_dir, '{"cert_robot_base_url": "http://portal",,,}')

    with caplog.at_level(logging.ERROR, logger=run_agent.LOGGER.name):
        cfg = run_agent._load_local_agent_config()

    assert cfg == {}
    # Antes isto ia para stderr e sumia no serviço Windows.
    assert "agent_config.json inválido" in caplog.text


def test_json_que_nao_e_objeto_loga_erro(config_dir, caplog):
    _escrever(config_dir, '["nao", "e", "objeto"]')

    with caplog.at_level(logging.ERROR, logger=run_agent.LOGGER.name):
        cfg = run_agent._load_local_agent_config()

    assert cfg == {}
    assert "não contém um objeto JSON" in caplog.text


def test_sem_arquivo_devolve_vazio(config_dir):
    assert run_agent._load_local_agent_config() == {}
