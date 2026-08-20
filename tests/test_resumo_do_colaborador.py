"""O colaborador recebe UM resumo, e não um e-mail por certificado.

O administrador ganhou resumo consolidado em 09/08/2026, com a justificativa
registrada em `_enviar_resumo_admins`: *"enviar um e-mail por certificado ao
admin geraria centenas de mensagens"*. O mesmo raciocínio vale para quem
acompanha 12 certificados, mas o código que agrupa morava dentro da função dos
admins — e o colaborador não passava por lá.

Não era decisão de desenho, era onde o código estava. Estes testes travam a
correção e as três coisas que ela NÃO pode quebrar:

1. **O antispam continua por (certificado, marco, destinatário).** Agrupar muda
   quantos e-mails saem, não o que faz um aviso repetir.
2. **Falha de envio não marca como enviado.** Marcar antes silenciaria aquele
   certificado até o próximo marco — e o próximo marco pode ser o vencimento.
3. **Cada pessoa vê só o que acompanha.** É o resumo de certificados de
   clientes: nome, CNPJ/CPF e vencimento.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

import app.alert_state as als


class _Settings:
    smtp_host = "smtp.exemplo.com"
    smtp_port = 587
    smtp_user = "u"
    smtp_password_encrypted = "x"
    smtp_use_tls = True
    smtp_use_ssl = False
    smtp_from_email = "portal@exemplo.com"
    smtp_alerts_enabled = True
    alertas_destinatarios = ""
    alertas_marcos = ""
    alertas_intervalo_horas = 0


def _cert(nome: str, dias: int, doc: str) -> dict:
    venc = datetime.now(timezone.utc) + timedelta(days=dias)
    return {
        "nome": nome,
        "display_name": nome,
        "not_after": venc.isoformat(),
        "fingerprint_sha256": "fp-" + doc,
        "documento_numero": doc,
        "documento_formatado": doc,
    }


@pytest.fixture
def disparar(tmp_path, monkeypatch: pytest.MonkeyPatch):
    """Roda `trigger_all_alerts` sem banco e sem SMTP.

    Devolve a lista de e-mails que sairiam, mais as estatísticas.
    """
    monkeypatch.setattr(als, "SENT_ALERTS_FILE", tmp_path / "sent.json")
    monkeypatch.setattr(als, "JOB_STATE_FILE", tmp_path / "job.json")
    monkeypatch.setattr(als, "_supabase", lambda: None)
    monkeypatch.setattr(als, "load_settings", lambda: _Settings())
    # O resumo dos admins tem teste próprio; aqui ele só atrapalharia a contagem.
    monkeypatch.setattr(als, "_enviar_resumo_admins", lambda *a, **k: {})

    def _executar(itens, selecoes, falhar=False):
        monkeypatch.setattr(als, "_get_selecoes_com_preferencia", lambda: selecoes)
        monkeypatch.setattr(
            "app.settings_state.get_latest_snapshot", lambda *a, **k: None
        )
        monkeypatch.setattr(
            "app.main._list_certificados_payload", lambda *a, **k: {"itens": itens}
        )
        enviados: list[dict] = []

        def _envio(**kw):
            enviados.append(kw)
            if falhar:
                raise RuntimeError("SMTP fora do ar")

        with patch.object(als, "send_smtp_email", _envio):
            stats = als.trigger_all_alerts()
        return enviados, stats

    return _executar


def _pref(docs, notificar=True, ignorados=()):
    return als.PreferenciaDeAlerta(list(docs), notificar, tuple(ignorados))


# ══════════════════════════════════════════════════════════════════════════
# O ponto central
# ══════════════════════════════════════════════════════════════════════════

def test_doze_certificados_geram_um_email_e_nao_doze(disparar) -> None:
    """O defeito, medido.

    Doze certificados da mesma pessoa cruzando a janela no mesmo dia: antes,
    doze mensagens; a caixa de entrada dela ficava inutilizável justamente no
    dia em que a informação importava.
    """
    docs = [f"1234567800{i:02d}" for i in range(12)]
    itens = [_cert(f"CLIENTE {i}", 5, d) for i, d in enumerate(docs)]

    enviados, stats = disparar(itens, {"pessoa@x.com": _pref(docs)})

    assert len(enviados) == 1, f"esperava 1 resumo, saíram {len(enviados)}"
    assert stats["alerts_sent"] == 1
    # E o resumo precisa realmente CONTER os doze — agrupar não pode virar
    # "manda um e esquece os outros".
    assert "12 a vencer" in enviados[0]["subject"], enviados[0]["subject"]
    for i in range(12):
        assert f"CLIENTE {i}" in enviados[0]["html_content"]


def test_cada_pessoa_ve_somente_os_certificados_que_acompanha(disparar) -> None:
    """Agrupar por destinatário não pode misturar as listas."""
    itens = [_cert("DA ANA", 5, "11111111000111"), _cert("DO BRUNO", 5, "22222222000122")]
    enviados, _ = disparar(
        itens,
        {
            "ana@x.com": _pref(["11111111000111"]),
            "bruno@x.com": _pref(["22222222000122"]),
        },
    )

    por_dest = {e["to_email"]: e["html_content"] for e in enviados}
    assert set(por_dest) == {"ana@x.com", "bruno@x.com"}
    assert "DA ANA" in por_dest["ana@x.com"]
    assert "DO BRUNO" not in por_dest["ana@x.com"]
    assert "DO BRUNO" in por_dest["bruno@x.com"]
    assert "DA ANA" not in por_dest["bruno@x.com"]


def test_o_rodape_diz_por_que_chegou_e_onde_mudar(disparar) -> None:
    """O e-mail do colaborador não pode dizer que ele é administrador."""
    enviados, _ = disparar(
        [_cert("CLIENTE", 5, "11111111000111")],
        {"pessoa@x.com": _pref(["11111111000111"])},
    )
    corpo = enviados[0]["html_content"]
    assert "escolheu acompanhar" in corpo
    assert "Acompanhamento" in corpo
    assert "perfil de administrador" not in corpo


# ══════════════════════════════════════════════════════════════════════════
# Preferência da pessoa
# ══════════════════════════════════════════════════════════════════════════

def test_quem_desligou_nao_recebe(disparar) -> None:
    enviados, stats = disparar(
        [_cert("CLIENTE", 5, "11111111000111")],
        {"pessoa@x.com": _pref(["11111111000111"], notificar=False)},
    )
    assert enviados == []
    assert stats["skipped_optout"] == 1


def test_marco_dispensado_nao_entra_mas_o_vencimento_entra(disparar) -> None:
    """Dispensar "faltam 15 dias" é razoável; nunca saber que venceu não é.

    Por isso o vencido não consulta a lista de marcos dispensados — só o
    opt-in geral. Quem não quer nada desliga tudo.
    """
    # 12 dias cai no marco de 15, que a pessoa dispensou.
    a_vencer = _cert("A VENCER", 12, "11111111000111")
    ja_vencido = _cert("VENCIDO", -3, "22222222000122")

    enviados, stats = disparar(
        [a_vencer, ja_vencido],
        {"pessoa@x.com": _pref(["11111111000111", "22222222000122"], ignorados=(15,))},
    )

    assert stats["skipped_marco_dispensado"] == 1
    assert len(enviados) == 1
    corpo = enviados[0]["html_content"]
    assert "VENCIDO" in corpo
    assert "A VENCER" not in corpo


def test_preferencia_ausente_significa_receber_tudo() -> None:
    """O padrão de fábrica, no objeto que o job usa.

    Uma instalação sem a migration lê `row.get("notificar_email", True)` — e a
    ausência precisa significar o comportamento antigo, não silêncio.
    """
    p = als.PreferenciaDeAlerta(["123"])
    assert p.notificar is True
    assert p.ignorados == ()
    assert p.aceita_marco(30) and p.aceita_marco(1)


# ══════════════════════════════════════════════════════════════════════════
# O que a mudança não pode quebrar
# ══════════════════════════════════════════════════════════════════════════

def test_o_antispam_continua_valendo_entre_execucoes(disparar) -> None:
    """Agrupar muda quantos e-mails saem, não o que faz um aviso repetir."""
    itens = [_cert("CLIENTE", 5, "11111111000111")]
    selecao = {"pessoa@x.com": _pref(["11111111000111"])}

    primeiros, _ = disparar(itens, selecao)
    segundos, stats = disparar(itens, selecao)

    assert len(primeiros) == 1
    assert segundos == [], "o job rodando de novo não pode reenviar"
    assert stats["skipped_already_sent"] == 1


def test_falha_de_envio_nao_marca_como_enviado(disparar) -> None:
    """Marcar antes do envio silenciaria o certificado até o próximo marco.

    E o próximo marco pode ser o vencimento — o aviso que existe justamente
    para não deixar chegar até lá.
    """
    itens = [_cert("CLIENTE", 5, "11111111000111")]
    selecao = {"pessoa@x.com": _pref(["11111111000111"])}

    _, stats = disparar(itens, selecao, falhar=True)
    assert stats["errors"] == 1
    assert stats["alerts_sent"] == 0

    # Próxima rodada, agora com o SMTP de volta: precisa tentar de novo.
    enviados, _ = disparar(itens, selecao)
    assert len(enviados) == 1, "a falha anterior não pode ter consumido o alerta"


def test_certificado_fora_da_janela_nao_gera_resumo(disparar) -> None:
    enviados, _ = disparar(
        [_cert("DAQUI A UM ANO", 300, "11111111000111")],
        {"pessoa@x.com": _pref(["11111111000111"])},
    )
    assert enviados == []
