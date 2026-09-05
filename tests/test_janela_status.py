"""
Conteúdo da janela de status do agente.

A janela existe porque o ícone da bandeja responde a uma pergunta só ("está
ativo?"), e o incidente do ANALISESRV precisou de outras quatro: qual portal,
sob que machine_id, quando foi a última leitura, e qual foi o último erro.
Descobrir que o agente falava com o endereço errado exigiu abrir o agent.log
num servidor — é isso que esta tela encurta.

`montar_estado` e `ultimo_erro_do_log` não tocam em Tk nem no Windows de
propósito: é o que permite testá-los aqui.
"""

from datetime import datetime, timedelta

import pytest

from agent.janela_status import EstadoAgente, montar_estado, ultimo_erro_do_log

AGORA = datetime(2026, 8, 13, 12, 0, 0)


def _estado(**kw) -> EstadoAgente:
    base = dict(
        servico_ativo=True,
        status={},
        versao="1.1.0",
        portal="https://portal.exemplo",
        machine_id="ANALISESRV",
        caminho_log=kw.pop("_log"),
        agora=AGORA,
    )
    base.update(kw)
    return montar_estado(**base)


@pytest.fixture
def log_vazio(tmp_path):
    p = tmp_path / "agent.log"
    p.write_text("", encoding="utf-8")
    return p


# ──────────────────────────────────────────────────────────────────────────
# Último erro
# ──────────────────────────────────────────────────────────────────────────

def test_pega_o_erro_mais_recente(tmp_path) -> None:
    log = tmp_path / "agent.log"
    log.write_text(
        "2026-08-13 09:00:00,100 [ERROR] erro antigo\n"
        "2026-08-13 10:00:00,100 [INFO] tudo bem\n"
        "2026-08-13 11:30:00,100 [ERROR] falha ao ler /api/settings\n"
        "2026-08-13 11:45:00,100 [WARNING] aviso qualquer\n",
        encoding="utf-8",
    )

    r = ultimo_erro_do_log(log, AGORA)

    assert "falha ao ler /api/settings" in r
    assert "erro antigo" not in r
    assert "há 30 min" in r


def test_sem_erro_devolve_none(tmp_path) -> None:
    """Distinguir 'nenhum erro' de 'não consegui ler' importa na tela."""
    log = tmp_path / "agent.log"
    log.write_text("2026-08-13 11:00:00,100 [INFO] ciclo concluído\n", encoding="utf-8")

    assert ultimo_erro_do_log(log, AGORA) is None


def test_log_inexistente_nao_explode(tmp_path) -> None:
    assert ultimo_erro_do_log(tmp_path / "nao-existe.log", AGORA) is None


def test_le_apenas_o_fim_de_log_grande(tmp_path) -> None:
    """
    O agent.log do ANALISESRV tinha 288 KB de uma falha só, e a janela relê a
    cada abertura — ler tudo seria desperdício. O corte não pode perder o erro
    recente nem quebrar na linha partida ao meio pelo seek.
    """
    log = tmp_path / "agent.log"
    enchimento = "".join(
        f"2026-08-13 08:00:00,000 [INFO] linha de enchimento {i}\n" for i in range(8000)
    )
    log.write_text(enchimento + "2026-08-13 11:59:00,000 [ERROR] o mais recente\n",
                   encoding="utf-8")
    assert log.stat().st_size > 300 * 1024

    r = ultimo_erro_do_log(log, AGORA)

    assert r is not None and "o mais recente" in r


def test_acentos_no_log_nao_quebram(tmp_path) -> None:
    """O agent.log real tem 'conexão', 'máquina' — e já apareceu mal codificado."""
    log = tmp_path / "agent.log"
    log.write_bytes(
        "2026-08-13 11:00:00,100 [ERROR] Não foi possível obter /api/settings\n".encode("utf-8")
    )

    assert "possível" in ultimo_erro_do_log(log, AGORA)


# ──────────────────────────────────────────────────────────────────────────
# Montagem do estado
# ──────────────────────────────────────────────────────────────────────────

def test_traduz_atividade_do_status(log_vazio) -> None:
    assert _estado(_log=log_vazio, status={"state": "scanning"}).atividade == "escaneando"
    assert _estado(_log=log_vazio, status={"state": "sending"}).atividade == "enviando"
    assert _estado(_log=log_vazio, status={"state": "idle"}).atividade == "ocioso"


def test_estado_vencido_conta_como_ocioso(log_vazio) -> None:
    """
    `_read_agent_status` marca "stale" após 5 min sem atualização. Com intervalo
    de 24 h isso é o normal, não um defeito — mostrar "desconhecido" na tela
    assustaria o usuário sem motivo.
    """
    assert _estado(_log=log_vazio, status={"state": "stale"}).atividade == "ocioso"


def test_ultima_consulta_em_linguagem_humana(log_vazio) -> None:
    ts = (AGORA - timedelta(hours=3)).timestamp()
    assert _estado(_log=log_vazio, status={"last_scan_time": ts}).ultima_consulta == "há 3 h"


def test_sem_consulta_anterior(log_vazio) -> None:
    assert _estado(_log=log_vazio, status={}).ultima_consulta is None


def test_timestamp_corrompido_nao_derruba_a_janela(log_vazio) -> None:
    assert _estado(_log=log_vazio, status={"last_scan_time": "abacaxi"}).ultima_consulta is None


def test_certificados_lidos(log_vazio) -> None:
    assert _estado(_log=log_vazio, status={"items_count": 556}).certificados_lidos == 556
    assert _estado(_log=log_vazio, status={"items_count": ""}).certificados_lidos is None


def test_portal_vazio_e_explicito(log_vazio) -> None:
    """
    Campo em branco na tela é ambíguo — pode ser "não configurado" ou "a janela
    falhou". O incidente começou justamente com uma config que não foi lida.
    """
    e = _estado(_log=log_vazio, portal="", machine_id="")
    assert e.portal == "(não configurado)"
    assert e.machine_id == "(não configurado)"


def test_servico_parado_e_refletido(log_vazio) -> None:
    assert _estado(_log=log_vazio, servico_ativo=False).servico_ativo is False


# ──────────────────────────────────────────────────────────────────────────
# Botões do servidor: reiniciar e abrir o log (04/09/2026)
# ──────────────────────────────────────────────────────────────────────────


def test_reiniciar_e_um_unico_processo_elevado(monkeypatch) -> None:
    """
    `sc stop && sc start` falharia com "stop pending", e dois `sc` elevados
    seriam dois UAC para um clique. Reiniciar tem de ser UM processo, e o
    PowerShell é quem espera a parada antes de subir.
    """
    from agent import janela_status

    chamadas: list[tuple[str, str]] = []

    def _falso(argumentos: str, programa: str = "sc.exe") -> bool:
        chamadas.append((programa, argumentos))
        return True

    monkeypatch.setattr(janela_status, "_executar_elevado", _falso)
    assert janela_status.reiniciar_servico("AnaliseCertiDigitalAgent") is True
    assert len(chamadas) == 1
    programa, argumentos = chamadas[0]
    assert programa == "powershell.exe"
    assert "Restart-Service -Name 'AnaliseCertiDigitalAgent'" in argumentos
    assert "-NonInteractive" in argumentos


def test_parar_e_iniciar_continuam_no_sc(monkeypatch) -> None:
    from agent import janela_status

    chamadas: list[tuple[str, str]] = []
    monkeypatch.setattr(
        janela_status, "_executar_elevado",
        lambda argumentos, programa="sc.exe": chamadas.append((programa, argumentos)) or True,
    )
    janela_status.parar_servico("X")
    janela_status.iniciar_servico("X")
    assert chamadas == [("sc.exe", 'stop "X"'), ("sc.exe", 'start "X"')]


def test_abrir_log_usa_o_programa_associado(monkeypatch, log_vazio) -> None:
    from agent import janela_status

    abertos: list[str] = []
    monkeypatch.setattr(janela_status.os, "startfile", abertos.append, raising=False)
    assert janela_status.abrir_log(log_vazio) is True
    assert abertos == [str(log_vazio)]


def test_abrir_log_cai_no_bloco_de_notas_sem_associacao(monkeypatch, log_vazio) -> None:
    """Sem programa associado a .log, `startfile` levanta; o Bloco de Notas abre qualquer texto."""
    from agent import janela_status

    def _sem_associacao(_caminho: str) -> None:
        raise OSError("Nenhum aplicativo associado")

    lancados: list[list[str]] = []
    monkeypatch.setattr(janela_status.os, "startfile", _sem_associacao, raising=False)
    monkeypatch.setattr(janela_status.subprocess, "Popen", lambda args: lancados.append(args))
    assert janela_status.abrir_log(log_vazio) is True
    assert lancados == [["notepad.exe", str(log_vazio)]]


def test_abrir_log_nao_levanta_quando_nada_abre(monkeypatch, log_vazio) -> None:
    """Falha ao abrir um log não pode derrubar a janela de status — ela é o diagnóstico."""
    from agent import janela_status

    def _falha(*_a, **_k):
        raise OSError("sem nada")

    monkeypatch.setattr(janela_status.os, "startfile", _falha, raising=False)
    monkeypatch.setattr(janela_status.subprocess, "Popen", _falha)
    assert janela_status.abrir_log(log_vazio) is False
