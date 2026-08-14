"""
Confirmação do rescan pedido pela bandeja.

Incidente de 14/08 no ANALISESRV — quatro linhas do agent.log contando uma
contradição:

    08:07:23,118 [INFO] Rescan manual solicitado pelo menu da bandeja.
    08:07:23,169 [INFO] Comando 'rescan' enviado ao serviço via ...json
    08:07:23,891 [INFO] Rescan acionado pelo tray (origem=tray)      <- recebeu
    08:09:23,285 [WARNING] Rescan ... expirou sem confirmação        <- e mesmo assim

O serviço confirmou o recebimento em 0,7 s e a bandeja anunciou falha 2 min
depois. O motivo é o sinal escolhido: `last_scan_time` só é gravado no FIM de um
ciclo inteiro e bem-sucedido, depois do upload ao portal. Bastava o envio
demorar ou falhar para a bandeja acusar o serviço de não responder.

O serviço entrar em `scanning`/`sending` já prova que o comando chegou, e
aparece em segundos. O prazo passa a cobrir só o intervalo entre pedir e
começar — não a duração da varredura, que numa base grande é legitimamente
longa (medidos ~24 s para os 556 certificados do ANALISESRV).
"""

import pytest

from agent.run_agent import estado_do_pedido_rescan


def _situacao(**kw) -> str:
    base = dict(
        pendente_desde=1000.0,
        baseline=500.0,
        status={},
        agora=1010.0,
        timeout_sec=120.0,
    )
    base.update(kw)
    return estado_do_pedido_rescan(**base)


def test_servico_comecou_a_escanear_confirma() -> None:
    """O que faltava: começar a trabalhar é prova de que o comando chegou."""
    assert _situacao(status={"state": "scanning"}) == "confirmado"


def test_servico_enviando_tambem_confirma() -> None:
    assert _situacao(status={"state": "sending"}) == "confirmado"


def test_scan_longo_nao_expira_mais() -> None:
    """
    O cerne do incidente: varredura em andamento além do prazo.

    Antes, passados 120 s sem o ciclo TERMINAR, a bandeja declarava falha. Com
    uma base grande — ou um upload lento — isso acusava o serviço de algo que
    ele não fez.
    """
    assert _situacao(status={"state": "scanning"}, agora=1000.0 + 600) == "confirmado"


def test_ciclo_concluido_confirma() -> None:
    """Caminho que já funcionava: last_scan_time avançou além do baseline."""
    assert _situacao(status={"last_scan_time": 900.0}) == "confirmado"


def test_scan_anterior_ao_pedido_nao_confirma() -> None:
    """Um last_scan_time mais VELHO que o baseline não é resposta ao clique."""
    assert _situacao(baseline=900.0, status={"last_scan_time": 900.0}) == "aguardando"


def test_sem_sinal_algum_segue_aguardando() -> None:
    assert _situacao(status={"state": "idle"}) == "aguardando"


def test_expira_se_o_servico_nunca_comecar() -> None:
    """O prazo continua existindo — só mudou o que ele mede."""
    assert _situacao(status={"state": "idle"}, agora=1000.0 + 121) == "expirado"


def test_sem_pedido_pendente_nao_ha_o_que_aguardar() -> None:
    assert _situacao(pendente_desde=0.0) == "confirmado"


def test_status_ausente_nao_explode() -> None:
    assert _situacao(status=None) == "aguardando"


def test_timestamp_corrompido_nao_explode() -> None:
    """O status vem de um arquivo em disco, gravado por outro processo."""
    assert _situacao(status={"last_scan_time": "abacaxi"}) == "aguardando"


@pytest.mark.parametrize("estado", ["stale", "", "qualquer-coisa"])
def test_estados_desconhecidos_nao_confirmam(estado: str) -> None:
    """
    Só `scanning` e `sending` provam trabalho em curso.

    `stale` em especial significa status parado há mais de 5 min — o oposto de
    "começou agora".
    """
    assert _situacao(status={"state": estado}) == "aguardando"
