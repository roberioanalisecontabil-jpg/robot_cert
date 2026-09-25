"""
Lote 5 das correções do SECURITY_AUDIT.md — abuso de recursos.

Um worker só (`Procfile`) e rotas sem teto: quem tinha uma sessão comum
derrubava o portal. Cada teste aqui foi escrito antes da correção e falhava em
`b9ddb09` (fim do lote 4). O que fica guardado:

  #11  importação lê em fluxo, com teto de bytes ANTES de receber tudo, teto
       de linhas e uma consulta só de e-mails
  #12  /duplicidades com cache por varredura, blocking key e teto de itens
  #28  /smtp/test, /alerts/trigger e o disparo por /ingest com teto;
       destinatário validado
  #29  modelos Pydantic com limites; paginação padrão em /api/certificados
  #60  /redeem, /acompanhar e /revalidar-cofre com teto
  #47  a degradação do rate limit aparece no health detalhado
"""

from __future__ import annotations

import io
import time
from typing import Any, Dict, List

import pytest
from fastapi.testclient import TestClient

import app.cert_installer as ci
import app.main as m
from app import auth, config, permissoes, taxa
from tests.test_seguranca_lote1 import _Fake, _usuario

ADMIN = ("admin@x.com", "admin")


def _h(email: str, papel: str) -> dict:
    return {"Authorization": "Bearer " + auth.create_access_token({"sub": email, "role": papel})}


@pytest.fixture
def banco(monkeypatch: pytest.MonkeyPatch) -> _Fake:
    fake = _Fake({
        "users": [_usuario("u-adm", "admin@x.com", "admin"), _usuario("u-ana", "ana@x.com", "user")],
        "user_activity": [], "cert_snapshots": [], "cert_history": [], "carteira": [], "install_token": [],
    })
    monkeypatch.setattr("app.settings_state._banco", lambda: fake)
    monkeypatch.setattr(ci, "_banco", lambda: fake)
    monkeypatch.setattr(m, "trigger_all_alerts", lambda: None)
    monkeypatch.setattr(config, "ACEITAR_API_KEY_COMPARTILHADA", True, raising=False)
    # O debounce do disparo por ingest é um carimbo do processo: outro teste
    # que ingeriu há segundos deixaria este começar "já disparado".
    monkeypatch.setattr(m, "_ultimo_disparo_por_ingest", 0.0, raising=False)
    from app import historico_agg_cache

    historico_agg_cache.invalidate_all()
    m._dup_cache_limpar() if hasattr(m, "_dup_cache_limpar") else None
    yield fake
    historico_agg_cache.invalidate_all()


def _csv(linhas: str) -> dict:
    return {"file": ("usuarios.csv", io.BytesIO(linhas.encode("utf-8")), "text/csv")}


# ──────────────────────────────────────────────────────────────────────────
# #11 — importações
# ──────────────────────────────────────────────────────────────────────────

class _Req:
    def __init__(self, content_length: str | None) -> None:
        self.headers = {"content-length": content_length} if content_length else {}


class _Arquivo:
    """UploadFile falso que conta quanto foi lido: o teto tem de agir ANTES do fim."""

    def __init__(self, total: int, pedaco: int = 64 * 1024) -> None:
        self.restante, self.pedaco, self.lido = total, pedaco, 0

    async def read(self, n: int = -1) -> bytes:
        n = self.pedaco if n is None or n < 0 else min(n, self.pedaco)
        n = min(n, self.restante)
        self.restante -= n
        self.lido += n
        return b"x" * n


@pytest.mark.anyio
async def test_content_length_acima_do_teto_e_recusado_sem_ler() -> None:
    arq = _Arquivo(total=50 * 1024 * 1024)
    with pytest.raises(m.HTTPException) as e:
        await m._ler_upload_limitado(_Req("50000000"), arq)
    assert e.value.status_code == 413
    assert arq.lido == 0, "recusar pelo cabeçalho é não receber o corpo"


@pytest.mark.anyio
async def test_corpo_maior_que_o_declarado_para_no_teto() -> None:
    """Content-Length é declaração do cliente: a leitura confere de novo."""
    arq = _Arquivo(total=8 * 1024 * 1024)
    with pytest.raises(m.HTTPException) as e:
        await m._ler_upload_limitado(_Req("1000"), arq)
    assert e.value.status_code == 413
    assert arq.lido <= m.LIMITE_UPLOAD_BYTES + 2 * 64 * 1024


@pytest.mark.anyio
async def test_upload_dentro_do_teto_e_lido_inteiro() -> None:
    arq = _Arquivo(total=300_000)
    dados = await m._ler_upload_limitado(_Req("300000"), arq)
    assert len(dados) == 300_000


def test_csv_com_mais_linhas_que_o_teto_e_413(client: TestClient, banco: _Fake) -> None:
    linhas = "nome;email;senha;nivel\n" + "".join(f"P{i};p{i}@x.com;senha-123456;user\n" for i in range(m.MAX_LINHAS_IMPORT + 1))
    r = client.post("/api/users/import", headers=_h(*ADMIN), files=_csv(linhas))
    assert r.status_code == 413, r.text
    assert not any(u["email"].startswith("p") for u in banco.tabelas["users"]), "nada pode ter sido gravado"


def test_emails_existentes_numa_consulta_so(client: TestClient, banco: _Fake, monkeypatch: pytest.MonkeyPatch) -> None:
    """Uma ida ao banco por linha (mais um bcrypt) era horas de CPU num CSV de 5 MB."""
    monkeypatch.setattr(auth, "get_password_hash", lambda s: "hash-fixo")
    linhas = "nome;email;senha;nivel\n" + "".join(f"P{i};p{i}@x.com;senha-123456;user\n" for i in range(40))
    banco.consultas.clear()
    r = client.post("/api/users/import", headers=_h(*ADMIN), files=_csv(linhas))
    assert r.status_code == 200, r.text
    assert r.json()["criados"] == 40
    assert banco.consultas.count("users") <= 3, banco.consultas.count("users")


def test_xlsx_com_mais_linhas_que_o_teto_e_413(client: TestClient, banco: _Fake) -> None:
    from openpyxl import Workbook

    wb = Workbook(); ws = wb.active
    ws.append(["email", "documento"])
    for i in range(m.MAX_LINHAS_IMPORT + 1):
        ws.append([f"p{i}@x.com", "11111111000191"])
    buf = io.BytesIO(); wb.save(buf)
    r = client.post("/api/carteira/importar", headers=_h(*ADMIN),
                    files={"file": ("c.xlsx", buf.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert r.status_code == 413, r.text


# ──────────────────────────────────────────────────────────────────────────
# #12 — duplicidades
# ──────────────────────────────────────────────────────────────────────────

def _snapshot(banco: _Fake, itens: List[dict], scanned_at: str = "2026-09-25T10:00:00+00:00") -> None:
    banco.tabelas["cert_snapshots"].append({"id": f"s-{len(banco.tabelas['cert_snapshots'])}", "machine_id": "srv",
                                            "scanned_at": scanned_at, "source_folder": "F:/C", "expired_folder": "F:/V",
                                            "items": itens})


def _item(i: int, fp: str | None = None) -> dict:
    return {"nome_publico": f"EMPRESA {i:05d}", "nome": f"EMPRESA NUMERO {i:05d} LTDA", "documento_numero": f"{i:014d}",
            "status": "ok", "fingerprint_sha256": fp, "not_after": "2027-01-01T00:00:00+00:00"}


def test_duplicidades_reusa_o_resultado_da_mesma_varredura(client: TestClient, banco: _Fake, monkeypatch: pytest.MonkeyPatch) -> None:
    _snapshot(banco, [_item(1, "a" * 64), _item(2, "a" * 64)])
    chamadas: List[int] = []
    original = m._agrupar_duplicidades
    monkeypatch.setattr(m, "_agrupar_duplicidades", lambda rows, incluir_pasta=False: (chamadas.append(1), original(rows, incluir_pasta))[1])
    for _ in range(3):
        assert client.get("/api/certificados/duplicidades", headers=_h(*ADMIN)).status_code == 200
    assert len(chamadas) == 1, "o snapshot não mudou: a análise não pode rodar de novo"


def test_duplicidades_recalcula_quando_a_varredura_muda(client: TestClient, banco: _Fake, monkeypatch: pytest.MonkeyPatch) -> None:
    _snapshot(banco, [_item(1)])
    chamadas: List[int] = []
    original = m._agrupar_duplicidades
    monkeypatch.setattr(m, "_agrupar_duplicidades", lambda rows, incluir_pasta=False: (chamadas.append(1), original(rows, incluir_pasta))[1])
    client.get("/api/certificados/duplicidades", headers=_h(*ADMIN))
    _snapshot(banco, [_item(1), _item(2)], scanned_at="2026-09-25T11:00:00+00:00")
    client.get("/api/certificados/duplicidades", headers=_h(*ADMIN))
    assert len(chamadas) == 2


def test_duplicidades_tem_teto_de_analises_por_identidade(client: TestClient, banco: _Fake) -> None:
    """Sem cache que sirva (varredura sempre nova), a 6ª análise em 5 min é recusada."""
    codigos = []
    for k in range(6):
        _snapshot(banco, [_item(k)], scanned_at=f"2026-09-25T1{k}:00:00+00:00")
        codigos.append(client.get("/api/certificados/duplicidades", headers=_h(*ADMIN)).status_code)
    assert codigos[:5] == [200] * 5 and codigos[5] == 429, codigos


def test_duplicidades_recusa_inventario_grande_demais(client: TestClient, banco: _Fake) -> None:
    _snapshot(banco, [_item(i) for i in range(m.MAX_ITENS_DUPLICIDADE + 1)])
    r = client.get("/api/certificados/duplicidades", headers=_h(*ADMIN))
    assert r.status_code == 413, r.text


def test_nomes_similares_nao_e_quadratico() -> None:
    """3.000 itens sem fingerprint: com blocking key termina em segundos; o
    laço n² fazia 4,5 milhões de SequenceMatcher."""
    rows = [{"nome_publico": f"CLIENTE {i:05d}", "nome": f"CLIENTE {chr(65 + i % 26)}{i:05d} COMERCIO",
             "documento_numero": f"{i:014d}", "status": "ok", "fingerprint_sha256": None} for i in range(3000)]
    t0 = time.perf_counter()
    m._agrupar_duplicidades(rows)
    assert time.perf_counter() - t0 < 5.0


def test_nomes_similares_continuam_sendo_achados_dentro_do_bloco() -> None:
    rows = [{"nome_publico": "A", "nome": "PADARIA CENTRAL LTDA", "documento_numero": "11111111000191", "status": "ok", "fingerprint_sha256": None},
            {"nome_publico": "B", "nome": "PADARIA CENTRAL LTDA ME", "documento_numero": "22222222000192", "status": "ok", "fingerprint_sha256": None}]
    _gd, gn, _gci = m._agrupar_duplicidades(rows)
    assert len(gn) == 1 and len(gn[0]["itens"]) == 2


# ──────────────────────────────────────────────────────────────────────────
# #28 — smtp/test, alerts/trigger, ingest→alertas
# ──────────────────────────────────────────────────────────────────────────

@pytest.fixture
def smtp_configurado(monkeypatch: pytest.MonkeyPatch) -> List[str]:
    enviados: List[str] = []
    from app import smtp_service

    monkeypatch.setattr(smtp_service, "send_smtp_email", lambda **kw: enviados.append(kw["to_email"]))
    monkeypatch.setattr(m, "load_settings", lambda: type("S", (), {
        "smtp_host": "smtp.x", "smtp_port": 587, "smtp_user": "u", "smtp_password_encrypted": "",
        "smtp_use_tls": True, "smtp_use_ssl": False, "smtp_from_email": "u@x"})())
    return enviados


def test_teste_de_smtp_tem_teto_por_identidade(client: TestClient, smtp_configurado: List[str]) -> None:
    codigos = [client.post("/api/settings/smtp/test", headers=_h(*ADMIN), json={"target_email": "d@x.com"}).status_code
               for _ in range(6)]
    assert codigos[:5] == [200] * 5 and codigos[5] == 429, codigos
    assert len(smtp_configurado) == 5


@pytest.mark.parametrize("dest", ["a@b.c\nBcc: vitima@x.com", "sem-arroba", "a@b.c, c@d.e"])
def test_destinatario_do_teste_e_validado(client: TestClient, smtp_configurado: List[str], dest: str) -> None:
    r = client.post("/api/settings/smtp/test", headers=_h(*ADMIN), json={"target_email": dest})
    assert r.status_code == 422, r.text
    assert smtp_configurado == []


def test_disparo_manual_tem_teto(client: TestClient, banco: _Fake) -> None:
    codigos = [client.post("/api/settings/alerts/trigger", headers=_h(*ADMIN)).status_code for _ in range(4)]
    assert codigos[:3] == [200] * 3 and codigos[3] == 429, codigos


def test_ingest_nao_agenda_alerta_a_cada_chamada(client: TestClient, banco: _Fake, monkeypatch: pytest.MonkeyPatch) -> None:
    from starlette.background import BackgroundTasks

    agendadas: List = []
    monkeypatch.setattr(BackgroundTasks, "add_task", lambda self, fn, *a, **k: agendadas.append(fn))
    corpo = {"machine_id": "srv", "source_folder": "F:/C", "expired_folder": "F:/V", "items": []}
    for _ in range(3):
        assert client.post("/api/ingest", headers=_h(*ADMIN), json=corpo).status_code == 200
    assert len(agendadas) == 1, "três ingestões em sequência: um disparo só"


# ──────────────────────────────────────────────────────────────────────────
# #60 — redeem, acompanhar, revalidar
# ──────────────────────────────────────────────────────────────────────────

def test_redeem_estourado_vira_429(client_com_chave: TestClient, api_key: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(taxa, "permitir", lambda *_a, **_k: False)
    r = client_com_chave.post("/api/cert-installer/redeem", json={"token": "t" * 32, "clientPublicKey": "x"},
                              headers=_h(*ADMIN))
    assert r.status_code == 429


def test_acompanhar_estourado_vira_429(client: TestClient, banco: _Fake, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(taxa, "permitir", lambda *_a, **_k: False)
    r = client.get("/api/cert-installer/acompanhar/00000000-0000-0000-0000-000000000000", headers=_h(*ADMIN))
    assert r.status_code == 429


def test_revalidar_cofre_tem_teto(client: TestClient, banco: _Fake, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ci, "revalidar_cofre", lambda: [])
    codigos = [client.post("/api/cert-installer/revalidar-cofre", headers=_h(*ADMIN)).status_code for _ in range(4)]
    assert codigos[:3] == [200] * 3 and codigos[3] == 429, codigos


# ──────────────────────────────────────────────────────────────────────────
# #29 — limites nos modelos; paginação padrão
# ──────────────────────────────────────────────────────────────────────────

def test_ingest_com_itens_demais_e_422(client: TestClient, banco: _Fake) -> None:
    corpo = {"machine_id": "srv", "source_folder": "F:/C", "expired_folder": "F:/V",
             "items": [{"nome_publico": "x", "status": "ok"}] * (m.MAX_ITENS_INGEST + 1)}
    assert client.post("/api/ingest", headers=_h(*ADMIN), json=corpo).status_code == 422


@pytest.mark.parametrize("campo, valor", [("smtp_port", 70000), ("smtp_port", 0), ("smtp_host", "h" * 300), ("source_folder", "p" * 2000)])
def test_settings_fora_da_faixa_e_422(client: TestClient, campo: str, valor: Any) -> None:
    r = client.put("/api/settings", headers=_h(*ADMIN), json={campo: valor})
    assert r.status_code == 422, r.text


def test_login_com_senha_gigante_e_422(client: TestClient) -> None:
    r = client.post("/api/login", json={"email": "a@x.com", "password": "x" * 5000})
    assert r.status_code == 422


def test_prepare_com_certificados_demais_e_422(client: TestClient, banco: _Fake) -> None:
    r = client.post("/api/cert-installer/prepare", headers=_h(*ADMIN),
                    json={"certificate_ids": ["c"] * (m.MAX_CERTIFICADOS_POR_TOKEN + 1), "machine_id": "m"})
    assert r.status_code == 422


def test_listagem_sem_parametros_vem_paginada(client: TestClient, banco: _Fake) -> None:
    _snapshot(banco, [_item(i, fp=f"{i:064d}") for i in range(150)])
    r = client.get("/api/certificados?fonte=remoto", headers=_h(*ADMIN))
    assert r.status_code == 200, r.text
    j = r.json()
    assert "paginacao" in j
    assert len(j["itens"]) <= 100
    assert j["paginacao"]["total_itens"] == 150


# ──────────────────────────────────────────────────────────────────────────
# #47 — a degradação do rate limit é visível
# ──────────────────────────────────────────────────────────────────────────

def test_health_detalhado_diz_se_o_rate_limit_e_persistente(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    class _Explode:
        def table(self, _n: str):
            raise RuntimeError("banco fora do ar")

    monkeypatch.setattr(taxa, "_banco", lambda: _Explode())
    assert taxa.permitir("q:x", 3, 60.0) is True
    assert taxa.estado_persistente() is False
    j = client.get("/api/health/detalhado", headers=_h(*ADMIN)).json()
    assert j["rate_limit_persistente"] is False
