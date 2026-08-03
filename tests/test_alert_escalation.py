"""Testes do escalonamento de alertas, do resumo para admins e da cadência do job.

Contexto dos defeitos que estes testes travam:

- A chave antispam era (certificado, "expiring", destinatário, validade), então
  um certificado que entrava na janela de 30 dias recebia UM e-mail no dia 30 e
  silêncio até vencer. Agora a chave inclui o marco (30/15/7/1).
- O admin via todos os alertas no sino e recebia zero e-mails, porque os
  destinatários saíam apenas de `colaborador_cert_selecoes`.
- O laço do job dormia 86400s, mas o Procfile recicla o worker a cada 500
  requisições e o job redisparava em cada boot+60s.
"""

from datetime import datetime, timezone, timedelta
from unittest.mock import patch

import pytest

import app.alert_state as als


# --------------------------------------------------------------------------
# Marcos de escalonamento
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "dias, marco_esperado",
    [
        (30, 30),
        (25, 30),
        (16, 30),
        (15, 15),
        (12, 15),
        (8, 15),
        (7, 7),
        (5, 7),
        (2, 7),
        (1, 1),
        (0, 1),
    ],
)
def test_marco_expiracao(dias: int, marco_esperado: int) -> None:
    assert als._marco_expiracao(dias) == marco_esperado


def test_marcos_geram_chaves_antispam_distintas() -> None:
    """O reforço só acontece se cada limiar produzir uma chave diferente."""
    chaves = {f"expiring:{als._marco_expiracao(d)}" for d in (25, 12, 5, 1)}
    assert len(chaves) == 4, f"marcos colidiram: {chaves}"


def test_um_alerta_por_marco_e_nao_por_dia(tmp_path, monkeypatch) -> None:
    """
    Simula o certificado atravessando a janela dia a dia e conta quantos
    e-mails sairiam. Antes seria 1; com marcos, 4.
    """
    monkeypatch.setattr(als, "SENT_ALERTS_FILE", tmp_path / "sent.json")
    monkeypatch.setattr(als, "_supabase", lambda: None)

    enviados = 0
    for dias in range(30, -1, -1):  # de 30 dias até o vencimento
        chave = f"expiring:{als._marco_expiracao(dias)}"
        if not als._is_alert_already_sent("fp1", chave, "dest@x.com", "2026-09-01T00:00:00Z"):
            als._record_sent_alert("fp1", chave, "dest@x.com", "2026-09-01T00:00:00Z")
            enviados += 1

    assert enviados == len(als.MARCOS_EXPIRACAO) == 4


def test_vencido_continua_com_alerta_unico(tmp_path, monkeypatch) -> None:
    """Um certificado vencido há dois anos não pode cobrar todo dia."""
    monkeypatch.setattr(als, "SENT_ALERTS_FILE", tmp_path / "sent.json")
    monkeypatch.setattr(als, "_supabase", lambda: None)

    enviados = 0
    for _ in range(10):  # dez execuções do job
        if not als._is_alert_already_sent("fp2", "expired", "dest@x.com", "2024-01-01T00:00:00Z"):
            als._record_sent_alert("fp2", "expired", "dest@x.com", "2024-01-01T00:00:00Z")
            enviados += 1

    assert enviados == 1


# --------------------------------------------------------------------------
# Cadência do job
# --------------------------------------------------------------------------

def test_job_nao_repete_apos_reinicio_do_worker(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(als, "JOB_STATE_FILE", tmp_path / "job.json")

    assert als.job_ja_executado_recentemente() is False, "primeira execução deve rodar"
    als.registrar_execucao_job()
    assert als.job_ja_executado_recentemente() is True, "reinício não deve redisparar"


def test_job_volta_a_rodar_apos_o_intervalo(tmp_path, monkeypatch) -> None:
    arquivo = tmp_path / "job.json"
    monkeypatch.setattr(als, "JOB_STATE_FILE", arquivo)

    antigo = datetime.now(timezone.utc) - timedelta(hours=als.INTERVALO_MINIMO_JOB_HORAS + 1)
    arquivo.write_text(f'{{"ultima_execucao": "{antigo.isoformat()}"}}', encoding="utf-8")

    assert als.job_ja_executado_recentemente() is False


def test_estado_corrompido_nao_bloqueia_o_job(tmp_path, monkeypatch) -> None:
    arquivo = tmp_path / "job.json"
    monkeypatch.setattr(als, "JOB_STATE_FILE", arquivo)
    arquivo.write_text("isto não é json", encoding="utf-8")

    assert als.job_ja_executado_recentemente() is False


# --------------------------------------------------------------------------
# Resumo consolidado para administradores
# --------------------------------------------------------------------------

def _cert(nome: str, dias: int, fp: str) -> dict:
    venc = datetime.now(timezone.utc) + timedelta(days=dias)
    return {
        "nome": nome,
        "display_name": nome,
        "not_after": venc.isoformat(),
        "fingerprint_sha256": fp,
        "documento_formatado": "12.345.678/0001-99",
    }


class _Settings:
    smtp_host = "smtp.exemplo.com"
    smtp_port = 587
    smtp_user = "u"
    smtp_password_encrypted = "x"
    smtp_use_tls = True
    smtp_use_ssl = False
    smtp_from_email = "portal@exemplo.com"
    smtp_alerts_enabled = True


def test_admin_recebe_um_resumo_e_nao_um_email_por_certificado(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(als, "SENT_ALERTS_FILE", tmp_path / "sent.json")
    monkeypatch.setattr(als, "_supabase", lambda: None)
    monkeypatch.setattr(als, "_get_admin_emails", lambda: ["admin@x.com"])

    itens = [_cert(f"CERT {i}", 5, f"fp{i}") for i in range(40)]
    enviados = []
    with patch.object(als, "send_smtp_email", lambda **kw: enviados.append(kw)):
        out = als._enviar_resumo_admins(_Settings(), itens, datetime.now(timezone.utc))

    assert len(enviados) == 1, "40 certificados devem gerar 1 resumo, não 40 e-mails"
    assert out["admin_resumos_enviados"] == 1
    assert "40" in enviados[0]["subject"]


def test_resumo_do_admin_e_diario(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(als, "SENT_ALERTS_FILE", tmp_path / "sent.json")
    monkeypatch.setattr(als, "_supabase", lambda: None)
    monkeypatch.setattr(als, "_get_admin_emails", lambda: ["admin@x.com"])

    itens = [_cert("UNICO", 3, "fp1")]
    enviados = []
    with patch.object(als, "send_smtp_email", lambda **kw: enviados.append(kw)):
        agora = datetime.now(timezone.utc)
        als._enviar_resumo_admins(_Settings(), itens, agora)
        out2 = als._enviar_resumo_admins(_Settings(), itens, agora)  # job roda de novo

    assert len(enviados) == 1
    assert out2["admin_resumos_ignorados"] == 1


def test_resumo_ignora_vencidos_antigos(tmp_path, monkeypatch) -> None:
    """486 certificados vencidos há 1-2 anos não podem inundar o resumo."""
    monkeypatch.setattr(als, "SENT_ALERTS_FILE", tmp_path / "sent.json")
    monkeypatch.setattr(als, "_supabase", lambda: None)
    monkeypatch.setattr(als, "_get_admin_emails", lambda: ["admin@x.com"])

    itens = [_cert(f"ANTIGO {i}", -400 - i, f"fp{i}") for i in range(50)]
    enviados = []
    with patch.object(als, "send_smtp_email", lambda **kw: enviados.append(kw)):
        out = als._enviar_resumo_admins(_Settings(), itens, datetime.now(timezone.utc))

    assert enviados == [], "nada dentro da janela: nenhum e-mail deve sair"
    assert out["admin_resumos_enviados"] == 0


def test_resumo_deduplica_o_mesmo_certificado(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(als, "SENT_ALERTS_FILE", tmp_path / "sent.json")
    monkeypatch.setattr(als, "_supabase", lambda: None)
    monkeypatch.setattr(als, "_get_admin_emails", lambda: ["admin@x.com"])

    itens = [_cert("MESMO CERT", 5, "fp-igual") for _ in range(4)]
    enviados = []
    with patch.object(als, "send_smtp_email", lambda **kw: enviados.append(kw)):
        als._enviar_resumo_admins(_Settings(), itens, datetime.now(timezone.utc))

    assert "1 a vencer" in enviados[0]["subject"], enviados[0]["subject"]


def test_sem_admins_nao_quebra(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(als, "_get_admin_emails", lambda: [])
    out = als._enviar_resumo_admins(_Settings(), [_cert("X", 5, "fp")], datetime.now(timezone.utc))
    assert out["admin_resumos_enviados"] == 0


# --------------------------------------------------------------------------
# Escape de HTML
# --------------------------------------------------------------------------

def test_nome_do_certificado_e_escapado_no_resumo(tmp_path, monkeypatch) -> None:
    """O CN do certificado é controlado por quem gera o .pfx."""
    monkeypatch.setattr(als, "SENT_ALERTS_FILE", tmp_path / "sent.json")
    monkeypatch.setattr(als, "_supabase", lambda: None)
    monkeypatch.setattr(als, "_get_admin_emails", lambda: ["admin@x.com"])

    malicioso = '<script>alert(1)</script>'
    itens = [_cert(malicioso, 5, "fp1")]
    enviados = []
    with patch.object(als, "send_smtp_email", lambda **kw: enviados.append(kw)):
        als._enviar_resumo_admins(_Settings(), itens, datetime.now(timezone.utc))

    corpo = enviados[0]["html_content"]
    assert "<script>" not in corpo
    assert "&lt;script&gt;" in corpo
