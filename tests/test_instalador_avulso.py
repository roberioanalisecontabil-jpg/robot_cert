"""
Instalador avulso: o .exe que o usuário baixa do portal (modelo Ninite).

Duas fronteiras novas, e ambas são de segurança:

1. `/api/cert-installer/claim` resgata SEM API key. Tinha de ser assim — a chave
   do agente dentro de um executável público seria distribuí-la a quem baixasse.
   O token vira a credencial, então o que o protege é ser de uso único, expirar
   em minutos, e o limite por IP.
2. O token viaja no NOME do arquivo. Um binário único e assinável é o que evita
   o alerta do SmartScreen em toda instalação, mas obriga o executável a ler o
   próprio nome — inclusive quando o navegador o renomeia para "... (1).exe".
"""

from typing import Any, Dict, List, Optional
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from agent.instalador_standalone import extrair_token
from app import auth, main as app_main
import app.cert_installer as ci


# ──────────────────────────────────────────────────────────────────────────
# Token no nome do arquivo
# ──────────────────────────────────────────────────────────────────────────

TOKEN = "Ab3-xY_9zQw2Lm5PqR7sTuV1wX4yZ6aB8cD0eF2gHiJ"


def test_le_o_token_do_nome_baixado() -> None:
    assert extrair_token(f"Instalar ACME LTDA -{TOKEN}.exe") == TOKEN


def test_tolera_renomeacao_do_navegador() -> None:
    """Baixar duas vezes gera "... (1).exe" — e isso não pode quebrar o token."""
    assert extrair_token(f"Instalar ACME -{TOKEN} (1).exe") == TOKEN
    assert extrair_token(f"Instalar ACME -{TOKEN} (23).exe") == TOKEN


def test_nome_com_hifen_nao_confunde_o_token() -> None:
    """O token também contém hífens; o separador é " -", com espaço antes."""
    assert extrair_token(f"Instalar ACME - FILIAL 2 -{TOKEN}.exe") == TOKEN


def test_sem_token_devolve_none() -> None:
    assert extrair_token("Instalar ACME.exe") is None
    assert extrair_token("qualquer-coisa.exe") is None


# ──────────────────────────────────────────────────────────────────────────
# Supabase falso
# ──────────────────────────────────────────────────────────────────────────

class _Res:
    def __init__(self, data: List[Dict[str, Any]]) -> None:
        self.data = data


class _Q:
    def __init__(self, t: List[Dict[str, Any]]) -> None:
        self._t, self._f, self._op, self._p = t, [], "select", None

    def select(self, *_c): self._op = "select"; return self
    def insert(self, r): self._op, self._p = "insert", r; return self
    def update(self, r): self._op, self._p = "update", r; return self
    def delete(self): self._op = "delete"; return self
    def order(self, *_a, **_k): return self
    def limit(self, *_a): return self

    def eq(self, c, v): self._f.append((c, "eq", v)); return self
    def in_(self, c, v): self._f.append((c, "in", v)); return self
    def is_(self, c, v): self._f.append((c, "is", v)); return self
    def gt(self, c, v): self._f.append((c, "gt", v)); return self

    def _casa(self, r) -> bool:
        for c, op, v in self._f:
            a = r.get(c)
            if op == "eq" and a != v: return False
            if op == "in" and a not in v: return False
            if op == "is" and not (v == "null" and a is None): return False
            if op == "gt" and not (a is not None and str(a) > str(v)): return False
        return True

    def execute(self) -> _Res:
        if self._op == "select":
            return _Res([dict(r) for r in self._t if self._casa(r)])
        if self._op == "insert":
            row = dict(self._p); row.setdefault("id", "id-1")
            self._t.append(row); return _Res([dict(row)])
        if self._op == "update":
            alt = []
            for r in self._t:
                if self._casa(r):
                    r.update(self._p); alt.append(dict(r))
            return _Res(alt)
        if self._op == "delete":
            fora = [r for r in self._t if self._casa(r)]
            self._t[:] = [r for r in self._t if not self._casa(r)]
            return _Res(fora)
        raise AssertionError(self._op)


class _Fake:
    def __init__(self) -> None:
        self.tabelas: Dict[str, List[Dict[str, Any]]] = {}

    def table(self, nome: str) -> _Q:
        return _Q(self.tabelas.setdefault(nome, []))


@pytest.fixture
def banco(monkeypatch):
    fake = _Fake()
    fake.tabelas["users"] = [{"id": "u-1", "email": "admin@x.com"}]
    monkeypatch.setattr("app.settings_state._supabase", lambda: fake)
    # O limitador é global ao processo; zerar evita um teste contaminar o outro.
    app_main._claim_tentativas.clear()
    return fake


def _token_valido(client: TestClient) -> str:
    """Cria um token real pela rota de admin e devolve o valor cru."""
    h = {"Authorization": "Bearer " + auth.create_access_token(
        {"sub": "admin@x.com", "role": "admin"})}
    # Usa a rota do instalador avulso: /prepare (instalação via agente) foi
    # removida em 16/08, e o token que este teste precisa é o mesmo objeto.
    r = client.post("/api/cert-installer/preparar-download",
                    json={"certificate_ids": ["c-1"], "nome": "ACME"},
                    headers=h)
    assert r.status_code == 200, r.text
    # O token cru não volta na resposta (por desenho); pega-se do enqueue.
    return _ULTIMO_TOKEN["valor"]


_ULTIMO_TOKEN: Dict[str, str] = {}


@pytest.fixture(autouse=True)
def captura_token(monkeypatch):
    original = ci.create_install_token

    def espiao(**kw):
        raw, tid, exp = original(**kw)
        _ULTIMO_TOKEN["valor"] = raw
        return raw, tid, exp

    monkeypatch.setattr(ci, "create_install_token", espiao)


# ──────────────────────────────────────────────────────────────────────────
# /claim — o token é a credencial
# ──────────────────────────────────────────────────────────────────────────

def test_claim_funciona_sem_api_key(client_com_chave: TestClient, banco) -> None:
    """
    O ponto da rota: o instalador não tem X-API-Key e mesmo assim resgata.

    Note que o fixture exige API_KEY configurada — é o cenário de produção, em
    que /redeem recusaria esta mesma chamada.
    """
    tok = _token_valido(client_com_chave)

    with patch.object(ci, "build_encrypted_bundle", lambda **kw: {"certificates": [{"x": 1}]}):
        r = client_com_chave.post("/api/cert-installer/claim",
                                  json={"token": tok, "clientPublicKey": "AA=="})

    assert r.status_code == 200, r.text
    assert r.json()["certificates"] == [{"x": 1}]


def test_claim_e_de_uso_unico(client_com_chave: TestClient, banco) -> None:
    tok = _token_valido(client_com_chave)

    with patch.object(ci, "build_encrypted_bundle", lambda **kw: {"certificates": []}):
        client_com_chave.post("/api/cert-installer/claim",
                              json={"token": tok, "clientPublicKey": "AA=="})

    r = client_com_chave.post("/api/cert-installer/claim",
                              json={"token": tok, "clientPublicKey": "AA=="})
    assert r.status_code == 403


def test_claim_recusa_token_inventado(client_com_chave: TestClient, banco) -> None:
    r = client_com_chave.post("/api/cert-installer/claim",
                              json={"token": "nao-existe", "clientPublicKey": "AA=="})
    assert r.status_code == 403


def test_claim_tem_limite_por_ip(client_com_chave: TestClient, banco) -> None:
    """Sem isto o token de uso único ficaria exposto a força bruta."""
    codigos = [
        client_com_chave.post("/api/cert-installer/claim",
                              json={"token": f"x{i}", "clientPublicKey": "AA=="}).status_code
        for i in range(app_main._CLAIM_MAX_POR_JANELA + 3)
    ]
    assert 429 in codigos, "o limitador não entrou"
    assert codigos.count(403) == app_main._CLAIM_MAX_POR_JANELA


# ──────────────────────────────────────────────────────────────────────────
# Rota de download
# ──────────────────────────────────────────────────────────────────────────

def test_vercel_empacota_o_executavel() -> None:
    """
    Produção é Vercel, e o bundle só leva o que está em `includeFiles`.

    Sem esta entrada o deploy sobe verde e a rota de download responde 503 para
    todo usuário — o binário simplesmente não existe no runtime. É um modo de
    falha que nenhum teste de aplicação pega, porque o arquivo existe na máquina
    de quem desenvolve.
    """
    import json as _json
    from pathlib import Path as _Path

    raiz = _Path(__file__).resolve().parents[1]
    cfg = _json.loads((raiz / "vercel.json").read_text(encoding="utf-8"))
    incluidos = cfg["builds"][0]["config"]["includeFiles"]

    relativo = app_main.INSTALADOR_AVULSO_EXE.relative_to(raiz).as_posix()
    assert relativo in incluidos, (
        f"{relativo} não está em vercel.json:includeFiles — "
        "a rota /instalador/baixar responderá 503 em produção"
    )


def _nome_do_download(resposta) -> str:
    """Nome do arquivo como o navegador o gravaria (RFC 5987, percent-encoded)."""
    from urllib.parse import unquote

    cd = resposta.headers["content-disposition"]
    bruto = cd.split("filename*=utf-8''")[-1] if "filename*=" in cd \
        else cd.split("filename=")[-1].strip('"; ')
    return unquote(bruto)


def test_download_recusa_token_malformado(client: TestClient) -> None:
    """O token vai para o nome do arquivo servido — barrar antes do disco."""
    r = client.get("/instalador/baixar/..%2F..%2Fetc%2Fpasswd")
    assert r.status_code in (400, 404)


def test_download_avisa_quando_exe_nao_foi_compilado(client: TestClient, tmp_path) -> None:
    with patch.object(app_main, "INSTALADOR_AVULSO_EXE", tmp_path / "nao-existe.exe"):
        r = client.get(f"/instalador/baixar/{TOKEN}")
    assert r.status_code == 503
    assert "compilado" in r.json()["detail"]


def test_download_poe_o_token_no_nome_do_arquivo(client: TestClient, tmp_path) -> None:
    exe = tmp_path / "Instalar_Certificado.exe"
    exe.write_bytes(b"MZ conteudo de teste")

    with patch.object(app_main, "INSTALADOR_AVULSO_EXE", exe):
        r = client.get(f"/instalador/baixar/{TOKEN}?nome=ACME LTDA")

    assert r.status_code == 200
    assert r.content == b"MZ conteudo de teste"
    # É deste cabeçalho que sai o nome no disco do usuário — e é dele que o
    # executável extrai o token ao rodar. O circuito só fecha se o nome
    # entregue pelo servidor for legível pelo parser do instalador.
    assert extrair_token(_nome_do_download(r)) == TOKEN


def test_download_sanitiza_o_nome_recebido(client: TestClient, tmp_path) -> None:
    """O `nome` vem da querystring; sem filtro ele desenha o arquivo no disco."""
    exe = tmp_path / "Instalar_Certificado.exe"
    exe.write_bytes(b"MZ")

    with patch.object(app_main, "INSTALADOR_AVULSO_EXE", exe):
        r = client.get(f"/instalador/baixar/{TOKEN}", params={"nome": '../../ev"il;x'})

    assert r.status_code == 200
    nome = _nome_do_download(r)
    assert "../" not in nome and '"' not in nome and ";" not in nome
    # E continua legível pelo instalador, que é o ponto de tudo.
    assert extrair_token(nome) == TOKEN
