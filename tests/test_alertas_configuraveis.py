"""Alertas configuráveis pela tela: marcos, destinatários e periodicidade.

Três invariantes governam este módulo, e as três são sobre o que acontece
quando a configuração está VAZIA ou ESTRAGADA — o caso que nunca é testado à
mão porque a tela sempre manda algo:

1. **Vazio é "usar o padrão", nunca "desligado".** Uma instalação que nunca
   abriu esta tela precisa se comportar exatamente como antes de ela existir.
2. **Valor ilegível não pode calar o envio.** O job roda sem ninguém olhando;
   alerta que para de sair não gera reclamação, gera certificado vencendo em
   silêncio.
3. **A tela recusa o que o job toleraria.** As duas coisas são diferentes de
   propósito: cair no padrão é certo para o job e péssimo como resposta a quem
   acabou de digitar — salvaria "30,15,cinco" e receberia "salvo".
"""

import pytest

from app import alertas_config as ac


# ══════════════════════════════════════════════════════════════════════════
# Marcos
# ══════════════════════════════════════════════════════════════════════════

def test_marcos_saem_ordenados_do_maior_para_o_menor() -> None:
    """A ordem não é estética: `marco_de` e a janela dependem dela."""
    assert ac.parse_marcos("5, 30, 15") == (30, 15, 5)


def test_marcos_aceitam_os_separadores_que_alguem_realmente_digita() -> None:
    assert ac.parse_marcos("30;15 5") == (30, 15, 5)
    assert ac.parse_marcos("30\n15\n5") == (30, 15, 5)


def test_marco_repetido_e_recusado() -> None:
    """Duplicata não é inofensiva: sugere um aviso a mais que não existe."""
    with pytest.raises(ac.ConfiguracaoInvalida, match="repetidos"):
        ac.parse_marcos("30,15,15")


def test_marco_nao_numerico_diz_qual_pedaco_esta_errado() -> None:
    with pytest.raises(ac.ConfiguracaoInvalida, match="cinco"):
        ac.parse_marcos("30,15,cinco")


def test_marco_fora_do_intervalo_e_recusado() -> None:
    with pytest.raises(ac.ConfiguracaoInvalida):
        ac.parse_marcos("0")
    with pytest.raises(ac.ConfiguracaoInvalida):
        ac.parse_marcos("400")


def test_marcos_demais_sao_recusados_porque_cada_um_e_um_email() -> None:
    excesso = ",".join(str(n) for n in range(1, ac.MARCOS_MAX_QTD + 2))
    with pytest.raises(ac.ConfiguracaoInvalida, match="máximo"):
        ac.parse_marcos(excesso)


def test_marcos_vazios_significam_o_padrao_e_nao_silencio() -> None:
    """A invariante 1, no ponto onde ela decide se sai e-mail."""
    assert ac.parse_marcos("") == ()
    assert ac.marcos_efetivos("") == ac.MARCOS_PADRAO
    assert ac.marcos_efetivos("   ") == ac.MARCOS_PADRAO


def test_marcos_ilegiveis_caem_no_padrao_sem_levantar() -> None:
    """A invariante 2. `marcos_efetivos` roda dentro do job."""
    assert ac.marcos_efetivos("30,15,cinco") == ac.MARCOS_PADRAO
    assert ac.marcos_efetivos("-1") == ac.MARCOS_PADRAO


def test_marco_de_escolhe_o_limiar_ainda_nao_ultrapassado() -> None:
    """É a chave do antispam: mesmo marco, nenhum reforço; cruzou, sai um."""
    marcos = (30, 15, 5)
    assert ac.marco_de(25, marcos) == 30
    assert ac.marco_de(15, marcos) == 15
    assert ac.marco_de(12, marcos) == 15
    assert ac.marco_de(5, marcos) == 5
    # Abaixo do menor marco: fica no menor, e não sem marco — senão o
    # certificado a 1 dia do vencimento mudaria de chave todo dia e cobraria
    # todo dia.
    assert ac.marco_de(0, marcos) == 5


def test_a_janela_do_resumo_acompanha_o_maior_marco() -> None:
    """Configurar 60 dias e o resumo continuar olhando 30 seria mentira."""
    assert ac.janela_dias((60, 30, 5)) == 60
    assert ac.janela_dias(()) == ac.MARCOS_PADRAO[0]


# ══════════════════════════════════════════════════════════════════════════
# Destinatários
# ══════════════════════════════════════════════════════════════════════════

def test_destinatarios_normalizam_e_nao_repetem() -> None:
    assert ac.parse_destinatarios("A@X.com, a@x.com ; b@y.com") == ("a@x.com", "b@y.com")


def test_destinatario_invalido_e_recusado_com_o_valor_no_texto() -> None:
    with pytest.raises(ac.ConfiguracaoInvalida, match="fulano"):
        ac.parse_destinatarios("fulano")


def test_lista_vazia_devolve_none_para_o_padrao_valer() -> None:
    """Vazio manda para os admins, como sempre foi."""
    assert ac.destinatarios_configurados("") is None
    assert ac.destinatarios_configurados("   ") is None


def test_lista_ilegivel_cai_nos_admins_em_vez_de_cortar_o_envio() -> None:
    """A invariante 2 no caminho mais perigoso.

    Um endereço estragado no banco poderia zerar a lista, e lista vazia num
    laço de envio significa "ninguém recebe" — sem erro, sem log, sem sintoma.
    """
    assert ac.destinatarios_configurados("isto-nao-e-email") is None


# ══════════════════════════════════════════════════════════════════════════
# Intervalo
# ══════════════════════════════════════════════════════════════════════════

def test_zero_e_valido_e_significa_o_padrao() -> None:
    assert ac.validar_intervalo(0) == 0
    assert ac.intervalo_efetivo_horas(0) == ac.INTERVALO_PADRAO_HORAS


def test_intervalo_fora_da_faixa_e_recusado_na_tela() -> None:
    with pytest.raises(ac.ConfiguracaoInvalida):
        ac.validar_intervalo(-5)
    with pytest.raises(ac.ConfiguracaoInvalida):
        ac.validar_intervalo(ac.INTERVALO_MAX_HORAS + 1)


def test_intervalo_ilegivel_cai_no_padrao_e_nao_em_zero() -> None:
    """Zero horas faria o job rodar a cada volta do laço — e-mail repetido."""
    assert ac.intervalo_efetivo_horas(-5) == ac.INTERVALO_PADRAO_HORAS
    assert ac.intervalo_efetivo_horas(10**9) == ac.INTERVALO_PADRAO_HORAS


# ══════════════════════════════════════════════════════════════════════════
# Ida e volta
# ══════════════════════════════════════════════════════════════════════════

def test_o_formato_gravado_volta_igual() -> None:
    """O que a tela salva é relido pelo job sem passar por outra normalização."""
    texto = ac.formatar_marcos(ac.parse_marcos("5,30,15"))
    assert texto == "30,15,5"
    assert ac.marcos_efetivos(texto) == (30, 15, 5)

    emails = ac.formatar_destinatarios(ac.parse_destinatarios("B@x.com,a@x.com"))
    assert emails == "b@x.com,a@x.com"
    assert ac.destinatarios_configurados(emails) == ("b@x.com", "a@x.com")


# ══════════════════════════════════════════════════════════════════════════
# O job lendo a configuração
# ══════════════════════════════════════════════════════════════════════════
#
# As funções puras acima decidem; estes testes verificam que o job realmente
# PERGUNTA a elas. Uma configuração que a tela grava e o envio ignora é o
# mesmo defeito da matriz de permissões governando o servidor enquanto o menu
# mostrava tudo — e foi o último a ser encontrado naquela sessão.

from datetime import datetime, timedelta, timezone  # noqa: E402
from unittest.mock import patch  # noqa: E402

import app.alert_state as als  # noqa: E402


class _SettingsAlertas:
    """Configuração viva na memória, com os campos novos preenchíveis."""

    smtp_host = "smtp.exemplo.com"
    smtp_port = 587
    smtp_user = "u"
    smtp_password_encrypted = "x"
    smtp_use_tls = True
    smtp_use_ssl = False
    smtp_from_email = "portal@exemplo.com"
    smtp_alerts_enabled = True

    def __init__(self, destinatarios: str = "", marcos: str = "", intervalo: int = 0) -> None:
        self.alertas_destinatarios = destinatarios
        self.alertas_marcos = marcos
        self.alertas_intervalo_horas = intervalo


def _certificado(nome: str, dias: int, fp: str) -> dict:
    venc = datetime.now(timezone.utc) + timedelta(days=dias)
    return {
        "nome": nome,
        "display_name": nome,
        "not_after": venc.isoformat(),
        "fingerprint_sha256": fp,
        "documento_formatado": "12.345.678/0001-99",
    }


@pytest.fixture
def resumo_isolado(tmp_path, monkeypatch: pytest.MonkeyPatch):
    """Sem Supabase e sem SMTP: devolve a lista de e-mails que sairiam."""
    monkeypatch.setattr(als, "SENT_ALERTS_FILE", tmp_path / "sent.json")
    monkeypatch.setattr(als, "_supabase", lambda: None)
    monkeypatch.setattr(als, "_get_admin_emails", lambda: ["admin@portal.com"])

    def _executar(settings, itens):
        enviados: list[dict] = []
        with patch.object(als, "send_smtp_email", lambda **kw: enviados.append(kw)):
            als._enviar_resumo_admins(settings, itens, datetime.now(timezone.utc))
        return enviados

    return _executar


def test_lista_configurada_substitui_os_administradores(resumo_isolado) -> None:
    enviados = resumo_isolado(
        _SettingsAlertas(destinatarios="chefe@x.com,fiscal@y.com"),
        [_certificado("CERT", 5, "fp1")],
    )
    assert sorted(e["to_email"] for e in enviados) == ["chefe@x.com", "fiscal@y.com"]
    assert "admin@portal.com" not in [e["to_email"] for e in enviados]


def test_sem_lista_o_resumo_continua_indo_para_os_administradores(resumo_isolado) -> None:
    """A invariante 1 no ponto em que ela decide quem recebe."""
    enviados = resumo_isolado(_SettingsAlertas(), [_certificado("CERT", 5, "fp1")])
    assert [e["to_email"] for e in enviados] == ["admin@portal.com"]


def test_o_rodape_deixa_de_dizer_administrador_quando_ha_lista(resumo_isolado) -> None:
    """A única linha do e-mail que explica por que aquilo chegou.

    Com lista fixa, "você recebe porque é administrador" é falso — e quem quer
    parar de receber precisa saber onde mexer.
    """
    com_lista = resumo_isolado(
        _SettingsAlertas(destinatarios="chefe@x.com"), [_certificado("CERT", 5, "fp1")]
    )
    assert "perfil de administrador" not in com_lista[0]["html_content"]
    assert "lista de destinatários" in com_lista[0]["html_content"]

    sem_lista = resumo_isolado(_SettingsAlertas(), [_certificado("CERT", 5, "fp2")])
    assert "perfil de administrador" in sem_lista[0]["html_content"]


def test_a_janela_do_resumo_segue_o_maior_marco(resumo_isolado) -> None:
    """Configurar 60 dias e o resumo olhar 30 seria configuração decorativa."""
    cert = [_certificado("DAQUI A 45 DIAS", 45, "fp-45")]

    padrao = resumo_isolado(_SettingsAlertas(), cert)
    assert padrao == [], "com 30 dias de janela, 45 dias está fora"

    ampliada = resumo_isolado(_SettingsAlertas(marcos="60,30,5"), cert)
    assert len(ampliada) == 1, "com 60 dias de janela, 45 dias entra"
    assert "1 a vencer" in ampliada[0]["subject"]


def test_marcos_ilegiveis_no_banco_nao_derrubam_o_resumo(resumo_isolado) -> None:
    """A invariante 2, no caminho de verdade e não só na função pura."""
    enviados = resumo_isolado(
        _SettingsAlertas(marcos="isto,nao,presta"), [_certificado("CERT", 5, "fp1")]
    )
    assert len(enviados) == 1


def test_a_chave_do_antispam_usa_os_marcos_configurados() -> None:
    """Com 30/15/5, um certificado a 12 dias pertence ao marco de 15.

    Se continuasse usando o padrão, 12 dias cairia em 15 por coincidência — mas
    7 dias cairia em 7, um marco que a pessoa removeu da tela, e sairia um
    e-mail que ela não pediu.
    """
    configurados = (30, 15, 5)
    assert als._marco_expiracao(7, configurados) == 15
    assert als._marco_expiracao(7) == 7, "sem marcos, o padrão continua valendo"


def test_o_intervalo_do_job_vem_da_configuracao(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(als, "JOB_STATE_FILE", tmp_path / "job.json")
    als.registrar_execucao_job()

    # 20h é o padrão; a execução acabou de acontecer, então ainda está dentro.
    assert als.job_ja_executado_recentemente(horas=20) is True
    # Com intervalo de 1 hora ainda está dentro; o marcador é de agora.
    assert als.job_ja_executado_recentemente(horas=1) is True

    antigo = datetime.now(timezone.utc) - timedelta(hours=30)
    (tmp_path / "job.json").write_text(
        '{"ultima_execucao": "%s"}' % antigo.isoformat(), encoding="utf-8"
    )
    assert als.job_ja_executado_recentemente(horas=20) is False, "30h > 20h: pode rodar"
    assert als.job_ja_executado_recentemente(horas=168) is True, "semanal: ainda não"
