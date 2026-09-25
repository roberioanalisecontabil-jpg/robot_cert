"""
Lote 6 das correções do SECURITY_AUDIT.md — caminhos e SMTP como vetor.

  #16  `source_folder`/`expired_folder` viravam `Path(p)` sem raiz permitida
       nem recusa de UNC: leitura e movimentação de PFX em qualquer caminho,
       hash NTLM da conta de serviço num `\\atacante\share`, `rglob` de `C:\`
  #33  host/porta do SMTP sem lista de portas nem bloqueio de faixa privada:
       PUT /api/settings + POST /smtp/test era um scanner de portas
  #34  vírgula em `?busca=` injetava cláusulas na DSL `or_`
  #53  /api/mover-vencidos devolvia caminhos absolutos do servidor

Cada teste foi escrito antes da correção e falhava em `32fcd1e` (fim do lote 5).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, List

import pytest
from fastapi.testclient import TestClient

import app.main as m
from app import auth, config, smtp_service
from app import settings_state as ss
from app.cert_scanner import scan_folder
from app.db_pg import Query, _dividir_or
from tests.test_db_pg import _q, _sql

ADMIN = ("admin@x.com", "admin")


def _h(email: str, papel: str) -> dict:
    return {"Authorization": "Bearer " + auth.create_access_token({"sub": email, "role": papel})}


# ──────────────────────────────────────────────────────────────────────────
# #16 — pastas
# ──────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("caminho", [r"\\atacante\share\certs", "//atacante/share/certs", r"\\?\UNC\srv\x"])
def test_unc_e_recusado_sempre(caminho: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "PASTAS_PERMITIDAS", [], raising=False)
    with pytest.raises(ss.PastaRecusada):
        ss.validar_pasta(caminho, "Pasta de origem")


def test_sem_lista_qualquer_pasta_local_e_aceita_e_resolvida(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Janela de compatibilidade: sem PASTAS_PERMITIDAS nada muda para o que já está gravado."""
    monkeypatch.setattr(config, "PASTAS_PERMITIDAS", [], raising=False)
    sub = tmp_path / "a" / ".." / "b"
    (tmp_path / "b").mkdir()
    assert ss.validar_pasta(str(sub), "x") == str((tmp_path / "b").resolve())


def test_com_lista_so_dentro_das_raizes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    raiz = tmp_path / "certs"
    raiz.mkdir()
    (raiz / "clientes").mkdir()
    monkeypatch.setattr(config, "PASTAS_PERMITIDAS", [raiz.resolve()], raising=False)
    assert ss.validar_pasta(str(raiz / "clientes"), "x") == str((raiz / "clientes").resolve())
    assert ss.validar_pasta(str(raiz), "x") == str(raiz.resolve())
    for fora in (str(tmp_path), str(raiz / ".." / "outra"), r"C:\Windows", "/etc"):
        with pytest.raises(ss.PastaRecusada):
            ss.validar_pasta(fora, "x")


def test_vazio_continua_sendo_o_padrao(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "PASTAS_PERMITIDAS", [], raising=False)
    assert ss.validar_pasta("", "x") == ""
    assert ss.validar_pasta("   ", "x") == ""


@pytest.mark.parametrize("campo", ["source_folder", "expired_folder"])
def test_put_settings_recusa_pasta_fora_da_raiz(client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                campo: str) -> None:
    monkeypatch.setattr(config, "PASTAS_PERMITIDAS", [tmp_path.resolve()], raising=False)
    gravados: List[Any] = []
    monkeypatch.setattr(m, "save_settings", lambda s, **k: gravados.append(s))
    r = client.put("/api/settings", headers=_h(*ADMIN), json={campo: r"\\atacante\share"})
    assert r.status_code == 422, r.text
    r = client.put("/api/settings", headers=_h(*ADMIN), json={campo: r"C:\Windows"})
    assert r.status_code == 422, r.text
    assert gravados == [], "nada pode ter sido gravado"


def test_put_settings_aceita_pasta_dentro_da_raiz(client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "PASTAS_PERMITIDAS", [tmp_path.resolve()], raising=False)
    gravados: List[Any] = []
    monkeypatch.setattr(m, "save_settings", lambda s, **k: gravados.append(s))
    (tmp_path / "ok").mkdir()
    r = client.put("/api/settings", headers=_h(*ADMIN), json={"source_folder": str(tmp_path / "ok")})
    assert r.status_code == 200, r.text
    assert gravados and gravados[0].source_folder == str((tmp_path / "ok").resolve())


def test_valor_ja_gravado_fora_da_raiz_cai_no_padrao_com_aviso(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                               caplog: pytest.LogCaptureFixture) -> None:
    """Defesa em profundidade: o PUT valida, mas o banco pode ter um valor
    antigo. `effective_source` não abre um caminho que o PUT recusaria."""
    monkeypatch.setattr(config, "PASTAS_PERMITIDAS", [tmp_path.resolve()], raising=False)
    s = ss.PortalSettings(source_folder=r"\\atacante\share", expired_folder=r"C:\Windows", machine_id="x")
    assert s.effective_source() == config.CERT_SOURCE_DIR
    assert s.effective_expired() == config.CERT_EXPIRED_DIR
    assert "recusad" in caplog.text.lower()


def test_scan_folder_tem_teto_de_arquivos(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    for i in range(30):
        (tmp_path / f"c{i} senha 1.pfx").write_bytes(b"x")
    itens = scan_folder(tmp_path, limite_arquivos=10)
    assert len(itens) == 10
    assert "teto" in caplog.text.lower()


def test_scan_folder_tem_teto_de_profundidade(tmp_path: Path) -> None:
    fundo = tmp_path / "n1" / "n2" / "n3" / "n4"
    fundo.mkdir(parents=True)
    (tmp_path / "n1" / "raso senha 1.pfx").write_bytes(b"x")
    (fundo / "fundo senha 1.pfx").write_bytes(b"x")
    nomes = {c.display_name for c in scan_folder(tmp_path, profundidade_max=2)}
    assert nomes == {"raso"}


def test_scan_folder_padrao_continua_recursivo(tmp_path: Path) -> None:
    (tmp_path / "a" / "b").mkdir(parents=True)
    (tmp_path / "a" / "b" / "x senha 1.pfx").write_bytes(b"x")
    assert len(scan_folder(tmp_path)) == 1


# ──────────────────────────────────────────────────────────────────────────
# #33 — SMTP como vetor de SSRF
# ──────────────────────────────────────────────────────────────────────────

@pytest.fixture
def dns(monkeypatch: pytest.MonkeyPatch):
    tabela = {"smtp.exemplo.com": ["93.184.216.34"], "interno.local": ["10.0.0.5"], "meta.local": ["169.254.169.254"]}
    monkeypatch.setattr(smtp_service, "resolver_enderecos", lambda host: tabela.get(host, [host]))
    monkeypatch.setattr(config, "SMTP_HOSTS_PERMITIDOS", [], raising=False)
    return tabela


@pytest.mark.parametrize("porta", [8080, 22, 5432, 3389, 0, 70000])
def test_porta_fora_da_lista_de_smtp_e_recusada(dns, porta: int) -> None:
    with pytest.raises(ValueError):
        smtp_service.exigir_destino_publico("smtp.exemplo.com", porta)


@pytest.mark.parametrize("host", ["169.254.169.254", "meta.local", "224.0.0.1", "0.0.0.0", "127.0.0.2", "::ffff:169.254.1.1"])
def test_destino_link_local_multicast_ou_loopback_disfarcado_e_recusado(dns, host: str) -> None:
    with pytest.raises(ValueError):
        smtp_service.exigir_destino_publico(host, 587)


@pytest.mark.parametrize("host", ["10.0.0.5", "interno.local", "192.168.1.20", "172.16.0.9"])
def test_rede_privada_so_com_permissao_explicita(dns, host: str, monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValueError):
        smtp_service.exigir_destino_publico(host, 587)
    monkeypatch.setattr(config, "SMTP_HOSTS_PERMITIDOS", [host], raising=False)
    smtp_service.exigir_destino_publico(host, 587)


@pytest.mark.parametrize("host, porta", [("smtp.exemplo.com", 587), ("smtp.exemplo.com", 465), ("93.184.216.34", 25), ("localhost", 25), ("127.0.0.1", 2525)])
def test_destino_publico_ou_servidor_local_passa(dns, host: str, porta: int) -> None:
    smtp_service.exigir_destino_publico(host, porta)


def test_nome_que_nao_resolve_e_recusado_sem_conectar(monkeypatch: pytest.MonkeyPatch) -> None:
    import socket

    def _falha(host):
        raise socket.gaierror(-2, "Name or service not known")

    monkeypatch.setattr(smtp_service, "resolver_enderecos", _falha)
    with pytest.raises(ValueError):
        smtp_service.exigir_destino_publico("nao.existe.exemplo", 587)


def test_envio_confere_o_destino_antes_de_abrir_conexao(dns, monkeypatch: pytest.MonkeyPatch) -> None:
    aberturas: List[str] = []

    class _Smtp:
        def __init__(self, host, port, timeout=0, context=None):
            aberturas.append(host)

    monkeypatch.setattr(smtp_service.smtplib, "SMTP", _Smtp)
    with pytest.raises(ValueError):
        smtp_service.send_smtp_email(host="meta.local", port=587, user="u", password_enc="", use_tls=True,
                                     use_ssl=False, from_email="u@x", to_email="d@x", subject="s", html_content="<p/>")
    assert aberturas == []


def test_teste_de_smtp_responde_curado_para_destino_interno(client: TestClient, dns, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(m, "load_settings", lambda: type("S", (), {
        "smtp_host": "meta.local", "smtp_port": 587, "smtp_user": "u", "smtp_password_encrypted": "",
        "smtp_use_tls": True, "smtp_use_ssl": False, "smtp_from_email": "u@x"})())
    r = client.post("/api/settings/smtp/test", headers=_h(*ADMIN), json={"target_email": "d@x.com"})
    assert r.status_code == 400
    assert "169.254" not in r.text and "meta.local" not in r.text
    assert "interno" in r.json()["detail"].lower() or "não é permitido" in r.json()["detail"].lower()


def test_put_settings_recusa_porta_fora_da_lista(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(m, "save_settings", lambda s, **k: None)
    r = client.put("/api/settings", headers=_h(*ADMIN), json={"smtp_host": "smtp.exemplo.com", "smtp_port": 8080})
    assert r.status_code == 422, r.text


# ──────────────────────────────────────────────────────────────────────────
# #34 — DSL or_
# ──────────────────────────────────────────────────────────────────────────

def test_dividir_or_respeita_aspas() -> None:
    assert _dividir_or('nome.ilike."%a,b%",documento.ilike."%a,b%"') == ['nome.ilike."%a,b%"', 'documento.ilike."%a,b%"']


def test_or_com_valor_entre_aspas_vira_um_parametro_so() -> None:
    (texto, params), = _sql(_q().select("*").or_('nome.ilike."%a,b.c%",x.is.null'))
    assert texto.count("ILIKE") == 1
    assert params == ["%a,b.c%"]


def test_busca_com_virgula_nao_injeta_clausula() -> None:
    filtro = m._filtro_or_da_busca("x,machine_id.eq.outra")
    partes = _dividir_or(filtro)
    assert len(partes) == 3, partes
    (texto, params), = _sql(_q().select("*").or_(filtro))
    assert "machine_id" not in texto
    assert all(p == "%x,machine\\_id.eq.outra%" for p in params)


def test_busca_com_aspas_e_barra_sobrevive() -> None:
    filtro = m._filtro_or_da_busca('a"b\\c')
    (texto, params), = _sql(_q().select("*").or_(filtro))
    assert params[0] == '%a"b\\\\c%'


# ──────────────────────────────────────────────────────────────────────────
# #53 — mover-vencidos sem caminhos absolutos
# ──────────────────────────────────────────────────────────────────────────

def test_mover_vencidos_devolve_caminhos_relativos_as_raizes(client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from datetime import datetime, timezone

    from app.cert_scanner import CertInfo, CertStatus

    origem = tmp_path / "origem" / "clientes"
    origem.mkdir(parents=True)
    arq = origem / "VELHA SA_11111111000191 senha 1.pfx"
    arq.write_bytes(b"x")
    venc = CertInfo(path=arq, file_name=arq.name, display_name="VELHA SA_11111111000191", status=CertStatus.EXPIRED,
                    not_after=datetime(2020, 1, 1, tzinfo=timezone.utc))
    monkeypatch.setattr(m, "scan_folder", lambda *a, **k: [venc])
    monkeypatch.setattr(m, "load_settings", lambda: type("S", (), {
        "effective_source": lambda self: tmp_path / "origem",
        "effective_expired": lambda self: tmp_path / "vencidos"})())
    r = client.post("/api/mover-vencidos", headers=_h(*ADMIN))
    assert r.status_code == 200, r.text
    corpo = r.text
    assert str(tmp_path) not in corpo and str(tmp_path).replace("\\", "/") not in corpo
    mov = r.json()["movidos"][0]
    assert mov["de"] == "clientes" and mov["para"] == ""
