"""
Lote 1 das correções do SECURITY_AUDIT.md (24/09/2026).

Cada teste aqui foi escrito ANTES da correção e falhava no commit `ea9c3de`.
O que cada bloco guarda, pelo número do achado:

  #6   o teto por IP não pode ser trocado por quem escreve o X-Forwarded-For
  #7   registrar dispositivo prova a senha, então tem o mesmo teto do login
  #8   recuperação de senha tem teto por IP e não prende o worker no SMTP
  #26  e-mail inexistente paga o mesmo bcrypt que e-mail existente
  #27  conta desativada responde igual a senha errada
  #41  a X-API-Key é comparada em tempo constante
  #9   `usuarios:editar` não cria, promove nem mexe em administrador
  #10  conta importada por CSV nasce com senha provisória
  #24  redefinir senha por admin derruba as sessões abertas
  #13  `esc()` escapa aspas — é usada dentro de atributos
  #14  célula de CSV que começa com =, +, -, @ não vira fórmula
  #15  SMTP verifica o certificado do servidor; sem TLS só para servidor local
  #20  .gitignore e hook recusam material de certificado
  #35  erro interno nunca sai com o texto da exceção
  #48  /api/health público não descreve a postura do deploy
  #49  CSP com base-uri 'none'
  #50  servidor sem cabeçalho Server
  #36  Host fora da lista é recusado
"""

from __future__ import annotations

import io
import os
import re
import shutil
import ssl
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest
from fastapi.testclient import TestClient

import app.main as m
from app import auth, config, permissoes, smtp_service, taxa

RAIZ = Path(__file__).resolve().parent.parent
UI_COMMON = RAIZ / "static" / "ui-common.js"
TEMPLATES = RAIZ / "templates"
NODE = shutil.which("node")
SH = shutil.which("sh") or shutil.which("bash")

SENHA = "senha-de-teste-123"


# ──────────────────────────────────────────────────────────────────────────
# Banco falso — mesmo formato de test_recuperacao_de_senha.py, com `gte`/`lt`
# porque `app/taxa.py` os usa na janela durável.
# ──────────────────────────────────────────────────────────────────────────

class _Res:
    def __init__(self, data: List[Dict[str, Any]], count: Optional[int] = None) -> None:
        self.data = data
        self.count = count


class _Query:
    def __init__(self, linhas: List[Dict[str, Any]], nome: str, banco: "_Fake") -> None:
        self._l, self._n, self._b = linhas, nome, banco
        self._f: List = []
        self._op, self._p = "select", None
        self._head = False
        self._range: Optional[tuple] = None
        self._on_conflict: Optional[List[str]] = None

    def select(self, *_c: str, **kw: Any) -> "_Query":
        self._head = bool(kw.get("head"))
        return self

    def insert(self, p: Any) -> "_Query":
        self._op, self._p = "insert", p
        return self

    def upsert(self, p: Any, on_conflict: Optional[str] = None, **_k: Any) -> "_Query":
        """`on_conflict` honrado: a linha com as mesmas colunas é substituída,
        como no Postgres — sem isso um upsert repetido parecia duplicar."""
        self._op, self._p = "insert", p
        self._on_conflict = [c.strip() for c in on_conflict.split(",")] if on_conflict else None
        return self

    def range(self, a: int, b: int) -> "_Query":
        self._range = (a, b)
        return self

    def update(self, p: Dict[str, Any]) -> "_Query":
        self._op, self._p = "update", p
        return self

    def delete(self) -> "_Query":
        self._op = "delete"
        return self

    def eq(self, c: str, v: Any) -> "_Query":
        self._f.append((c, "eq", v))
        return self

    def neq(self, c: str, v: Any) -> "_Query":
        self._f.append((c, "neq", v))
        return self

    def is_(self, c: str, v: Any) -> "_Query":
        self._f.append((c, "is", v))
        return self

    def gt(self, c: str, v: Any) -> "_Query":
        self._f.append((c, "gt", v))
        return self

    def gte(self, c: str, v: Any) -> "_Query":
        self._f.append((c, "gte", v))
        return self

    def lt(self, c: str, v: Any) -> "_Query":
        self._f.append((c, "lt", v))
        return self

    def in_(self, c: str, vs: List[Any]) -> "_Query":
        self._f.append((c, "in", list(vs)))
        return self

    def limit(self, _n: int) -> "_Query":
        return self

    def order(self, *_a: Any, **_k: Any) -> "_Query":
        return self

    def _casa(self, r: Dict[str, Any]) -> bool:
        for c, op, v in self._f:
            a = r.get(c)
            if op == "eq" and a != v:
                return False
            if op == "neq" and a == v:
                return False
            if op == "is" and not (v == "null" and a is None):
                return False
            if op == "gt" and not (a is not None and str(a) > str(v)):
                return False
            if op == "gte" and not (a is not None and str(a) >= str(v)):
                return False
            if op == "lt" and not (a is not None and str(a) < str(v)):
                return False
            if op == "in" and a not in v:
                return False
        return True

    def execute(self) -> _Res:
        if self._b.quebrado.get(self._n):
            # Uma tabela "fora do ar": é como se testa que a barreira falha
            # FECHADA (503) e não aberta (lista vazia = "pode tudo").
            raise RuntimeError(f"banco fora do ar ao ler {self._n}")
        if self._op == "insert":
            novas = self._p if isinstance(self._p, list) else [self._p]
            saida = []
            for p in novas:
                linha = dict(p)
                if self._on_conflict:
                    existente = next((r for r in self._l
                                      if all(r.get(c) == linha.get(c) for c in self._on_conflict)), None)
                    if existente is not None:
                        existente.update(linha)
                        self._b.gravados.append((self._n, dict(existente)))
                        saida.append(dict(existente))
                        continue
                linha.setdefault("id", f"{self._n}-{len(self._l) + 1}")
                self._l.append(linha)
                self._b.gravados.append((self._n, dict(linha)))
                saida.append(dict(linha))
            return _Res(saida)
        if self._op == "update":
            alt = []
            for r in self._l:
                if self._casa(r):
                    r.update(self._p)
                    self._b.gravados.append((self._n, dict(self._p)))
                    alt.append(dict(r))
            return _Res(alt)
        if self._op == "delete":
            fora = [r for r in self._l if self._casa(r)]
            self._l[:] = [r for r in self._l if not self._casa(r)]
            return _Res(fora)
        rows = [dict(r) for r in self._l if self._casa(r)]
        total = len(rows)
        if self._range:
            a, b = self._range
            rows = rows[a:b + 1]
        return _Res([] if self._head else rows, count=total)


class _Fake:
    def __init__(self, tabelas: Dict[str, List[Dict[str, Any]]]) -> None:
        self.tabelas = tabelas
        self.gravados: List = []
        self.quebrado: Dict[str, bool] = {}

    def table(self, nome: str) -> _Query:
        return _Query(self.tabelas.setdefault(nome, []), nome, self)


_HASHES: Dict[str, str] = {}


def _hash_de(senha: str) -> str:
    """bcrypt custo 12 leva ~0,6 s; quatro usuários por teste em quatro
    arquivos de lote somavam minutos de suíte. O hash de uma mesma senha é
    reaproveitado — o que se testa é a regra, não o custo do bcrypt."""
    if senha not in _HASHES:
        _HASHES[senha] = auth.get_password_hash(senha)
    return _HASHES[senha]


def _usuario(uid: str, email: str, papel: str, **extra: Any) -> Dict[str, Any]:
    linha = {
        "id": uid, "email": email, "full_name": email.split("@")[0].title(),
        "role": papel, "ativo": True, "deve_trocar_senha": False,
        "senha_alterada_em": None, "departamento_id": None,
        "password_hash": _hash_de(SENHA),
    }
    linha.update(extra)
    return linha


@pytest.fixture
def banco(monkeypatch: pytest.MonkeyPatch) -> _Fake:
    fake = _Fake({
        "users": [
            _usuario("u-adm", "admin@x.com", "admin"),
            _usuario("u-ges", "gestor@x.com", "gestor"),
            _usuario("u-ana", "ana@x.com", "user"),
            _usuario("u-off", "fora@x.com", "user", ativo=False),
        ],
        "user_activity": [],
        "password_reset_codigo": [],
        "rate_limit_tentativas": [],
    })
    monkeypatch.setattr("app.settings_state._banco", lambda: fake)
    return fake


@pytest.fixture
def gestor_edita_usuarios(monkeypatch: pytest.MonkeyPatch) -> None:
    """A matriz que o achado #9 descreve: um admin deu `usuarios: editar` a gestor."""
    matriz = {"gestor": {mod: permissoes.NIVEL_NENHUM for mod in permissoes.MODULOS}}
    matriz["gestor"]["usuarios"] = permissoes.NIVEL_EDITAR
    monkeypatch.setattr(permissoes, "_matriz", lambda: matriz)


def _h(email: str, papel: str) -> dict:
    return {"Authorization": "Bearer " + auth.create_access_token({"sub": email, "role": papel})}


ADMIN = ("admin@x.com", "admin")
GESTOR = ("gestor@x.com", "gestor")


def _login(client: TestClient, email: str, senha: str = SENHA, **headers: str):
    return client.post("/api/login", json={"email": email, "password": senha}, headers=headers)


# ──────────────────────────────────────────────────────────────────────────
# #6 — X-Forwarded-For contado a partir da direita
# ──────────────────────────────────────────────────────────────────────────

class _Req:
    def __init__(self, xff: Optional[str], host: str = "10.9.9.9") -> None:
        self.headers = {"x-forwarded-for": xff} if xff is not None else {}
        self.client = type("C", (), {"host": host})()


def test_ip_vem_do_ultimo_salto_que_o_proxy_escreveu(monkeypatch: pytest.MonkeyPatch) -> None:
    """O primeiro valor é o que o CLIENTE mandou; o proxy anexa o real no fim."""
    monkeypatch.setattr(config, "NUM_PROXIES_CONFIAVEIS", 1, raising=False)
    assert m._ip_do_cliente(_Req("9.9.9.9, 203.0.113.7")) == "203.0.113.7"


def test_sem_proxy_confiavel_o_cabecalho_e_ignorado(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "NUM_PROXIES_CONFIAVEIS", 0, raising=False)
    assert m._ip_do_cliente(_Req("9.9.9.9", host="10.0.0.5")) == "10.0.0.5"


def test_cadeia_mais_curta_que_os_proxies_cai_no_socket(monkeypatch: pytest.MonkeyPatch) -> None:
    """Cabeçalho forjado sem proxy à frente não pode virar identidade."""
    monkeypatch.setattr(config, "NUM_PROXIES_CONFIAVEIS", 2, raising=False)
    assert m._ip_do_cliente(_Req("9.9.9.9", host="10.0.0.5")) == "10.0.0.5"


def test_xff_forjado_nao_escapa_do_teto_do_login(
    client: TestClient, banco: _Fake, monkeypatch: pytest.MonkeyPatch
) -> None:
    """30 tentativas, cada uma com um primeiro valor diferente, mesmo cliente real."""
    monkeypatch.setattr(config, "NUM_PROXIES_CONFIAVEIS", 1, raising=False)
    codigos = [
        _login(client, "ana@x.com", "errada", **{"X-Forwarded-For": f"9.9.9.{i}, 203.0.113.7"}).status_code
        for i in range(30)
    ]
    assert 429 in codigos, codigos


# ──────────────────────────────────────────────────────────────────────────
# #7 — /api/agent/dispositivos/registrar
# ──────────────────────────────────────────────────────────────────────────

def _registrar(client: TestClient, email: str, senha: str, **headers: str):
    return client.post(
        "/api/agent/dispositivos/registrar",
        json={"email": email, "password": senha, "machine_id": "MAQ-1", "nome": "x"},
        headers=headers,
    )


def test_registrar_dispositivo_tem_teto_por_ip(client: TestClient, banco: _Fake) -> None:
    codigos = [_registrar(client, "ana@x.com", "errada").status_code for _ in range(25)]
    assert 429 in codigos, codigos


def test_registrar_e_login_dividem_a_mesma_janela(client: TestClient, banco: _Fake) -> None:
    """Duas chaves separadas dariam 40 tentativas/min a quem alternasse as rotas."""
    codigos = []
    for i in range(21):
        if i % 2:
            codigos.append(_registrar(client, "ana@x.com", "errada").status_code)
        else:
            codigos.append(_login(client, "ana@x.com", "errada").status_code)
    assert codigos[-1] == 429, codigos


def test_registrar_tem_teto_por_conta_que_ip_nenhum_contorna(
    client: TestClient, banco: _Fake, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(config, "NUM_PROXIES_CONFIAVEIS", 1, raising=False)
    codigos = [
        _registrar(client, "ana@x.com", "errada", **{"X-Forwarded-For": f"198.51.100.{i}"}).status_code
        for i in range(12)
    ]
    assert codigos[-1] == 429, codigos


# ──────────────────────────────────────────────────────────────────────────
# #8 — recuperação de senha
# ──────────────────────────────────────────────────────────────────────────

@pytest.fixture
def smtp_gravador(monkeypatch: pytest.MonkeyPatch) -> List[dict]:
    enviados: List[dict] = []

    def _falso(conta: dict, codigo: str) -> None:
        enviados.append({"email": conta["email"], "codigo": codigo})

    monkeypatch.setattr(m, "_enviar_codigo_por_email", _falso)
    return enviados


def test_pedido_de_codigo_tem_teto_por_ip_e_responde_200_generico(
    client: TestClient, banco: _Fake, smtp_gravador: List[dict]
) -> None:
    """Seis e-mails diferentes do mesmo IP: o sexto não gera envio, e ninguém vê 429."""
    emails = ["admin@x.com", "gestor@x.com", "ana@x.com", "admin@x.com", "gestor@x.com", "ana@x.com"]
    respostas = [client.post("/api/senha/codigo", json={"email": e}) for e in emails]
    assert all(r.status_code == 200 for r in respostas)
    assert all(r.json()["message"] == m.RESPOSTA_GENERICA for r in respostas)
    assert len(smtp_gravador) <= 5, len(smtp_gravador)


def test_envio_do_codigo_sai_do_caminho_da_resposta(
    client: TestClient, banco: _Fake, monkeypatch: pytest.MonkeyPatch
) -> None:
    """O SMTP prende o worker por até 10 s e é o oráculo de timing: vai para depois."""
    from starlette.background import BackgroundTasks

    agendadas: List = []
    chamadas_diretas: List = []
    monkeypatch.setattr(BackgroundTasks, "add_task", lambda self, fn, *a, **k: agendadas.append(fn))
    monkeypatch.setattr(m, "_enviar_codigo_por_email", lambda conta, codigo: chamadas_diretas.append(codigo))

    r = client.post("/api/senha/codigo", json={"email": "ana@x.com"})

    assert r.status_code == 200
    assert agendadas, "o envio precisa ser agendado em BackgroundTasks"
    assert not chamadas_diretas, "o envio não pode acontecer dentro da requisição"


def test_verificar_codigo_tem_teto_por_ip(
    client: TestClient, banco: _Fake, smtp_gravador: List[dict]
) -> None:
    """20 conferências erradas do mesmo IP; a 21ª, mesmo certa, é recusada."""
    assert client.post("/api/senha/codigo", json={"email": "ana@x.com"}).status_code == 200
    codigo = smtp_gravador[0]["codigo"]
    for _ in range(20):
        client.post("/api/senha/verificar", json={"email": "ninguem@x.com", "codigo": "000000"})
    r = client.post("/api/senha/verificar", json={"email": "ana@x.com", "codigo": codigo})
    assert r.status_code == 400
    assert r.json()["detail"] == m.CODIGO_INVALIDO


def test_redefinir_senha_tem_teto_por_ip(
    client: TestClient, banco: _Fake, smtp_gravador: List[dict]
) -> None:
    assert client.post("/api/senha/codigo", json={"email": "ana@x.com"}).status_code == 200
    codigo = smtp_gravador[0]["codigo"]
    for _ in range(20):
        client.post("/api/senha/redefinir",
                    json={"email": "ninguem@x.com", "codigo": "000000", "password": "nova-senha-12"})
    r = client.post("/api/senha/redefinir",
                    json={"email": "ana@x.com", "codigo": codigo, "password": "nova-senha-12"})
    assert r.status_code == 400
    assert r.json()["detail"] == m.CODIGO_INVALIDO


# ──────────────────────────────────────────────────────────────────────────
# #26 / #27 — login sem oráculo
# ──────────────────────────────────────────────────────────────────────────

def test_email_inexistente_paga_o_bcrypt(
    client: TestClient, banco: _Fake, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pular o hash quando a conta não existe é o que fazia o tempo denunciar a conta."""
    chamadas: List = []
    original = auth.verify_password
    monkeypatch.setattr(auth, "verify_password",
                        lambda s, h: (chamadas.append(h), original(s, h))[1])
    r = _login(client, "ninguem@x.com", "qualquer")
    assert r.status_code == 401
    assert len(chamadas) == 1


def test_conta_desativada_responde_igual_a_senha_errada(client: TestClient, banco: _Fake) -> None:
    errada = _login(client, "ana@x.com", "errada")
    desativada = _login(client, "fora@x.com", SENHA)
    assert desativada.status_code == errada.status_code == 401
    assert desativada.json() == errada.json()


# ──────────────────────────────────────────────────────────────────────────
# #41 — comparação da X-API-Key
# ──────────────────────────────────────────────────────────────────────────

def test_x_api_key_e_comparada_em_tempo_constante() -> None:
    fonte = (RAIZ / "app" / "main.py").read_text(encoding="utf-8")
    assert "x_api_key == config.API_KEY" not in fonte
    assert re.search(r"compare_digest\([^)]*x_api_key", fonte), "esperava hmac.compare_digest na X-API-Key"


# ──────────────────────────────────────────────────────────────────────────
# #9 — usuarios:editar não alcança administrador
# ──────────────────────────────────────────────────────────────────────────

def test_gestor_nao_cria_admin(client: TestClient, banco: _Fake, gestor_edita_usuarios: None) -> None:
    r = client.post("/api/users", headers=_h(*GESTOR),
                    json={"email": "novo@x.com", "password": "senha-123456", "full_name": "Novo", "role": "admin"})
    assert r.status_code == 403
    assert not any(u["email"] == "novo@x.com" for u in banco.tabelas["users"])


def test_gestor_nao_se_promove(client: TestClient, banco: _Fake, gestor_edita_usuarios: None) -> None:
    r = client.put("/api/users/u-ges", headers=_h(*GESTOR),
                   json={"email": "gestor@x.com", "full_name": "Gestor", "role": "admin"})
    assert r.status_code == 403
    assert next(u for u in banco.tabelas["users"] if u["id"] == "u-ges")["role"] == "gestor"


@pytest.mark.parametrize("acao", [
    ("post", "/api/users/u-adm/reset-password", {"password": "senha-123456"}),
    ("put", "/api/users/u-adm", {"email": "gestor-controla@x.com", "full_name": "Admin", "role": "admin"}),
    ("post", "/api/users/u-adm/deactivate", None),
    ("delete", "/api/users/u-adm", None),
])
def test_gestor_nao_mexe_em_conta_de_admin(
    client: TestClient, banco: _Fake, gestor_edita_usuarios: None, acao
) -> None:
    """Trocar o e-mail do admin e pedir código de redefinição seria tomada de conta."""
    metodo, url, corpo = acao
    r = getattr(client, metodo)(url, headers=_h(*GESTOR), **({"json": corpo} if corpo else {}))
    assert r.status_code == 403, (url, r.status_code, r.text)
    admin = next(u for u in banco.tabelas["users"] if u["id"] == "u-adm")
    assert admin["email"] == "admin@x.com" and admin["ativo"] is True


def test_admin_continua_podendo_criar_admin(client: TestClient, banco: _Fake) -> None:
    r = client.post("/api/users", headers=_h(*ADMIN),
                    json={"email": "novo@x.com", "password": "senha-123456", "full_name": "Novo", "role": "admin"})
    assert r.status_code == 200, r.text


def test_gestor_continua_gerindo_operadores(
    client: TestClient, banco: _Fake, gestor_edita_usuarios: None
) -> None:
    r = client.post("/api/users/u-ana/reset-password", headers=_h(*GESTOR), json={"password": "senha-123456"})
    assert r.status_code == 200, r.text


# ──────────────────────────────────────────────────────────────────────────
# #10 — importação CSV
# ──────────────────────────────────────────────────────────────────────────

def _csv(linhas: str) -> dict:
    return {"file": ("usuarios.csv", io.BytesIO(linhas.encode("utf-8")), "text/csv")}


def test_conta_importada_por_csv_nasce_com_senha_provisoria(client: TestClient, banco: _Fake) -> None:
    r = client.post("/api/users/import", headers=_h(*ADMIN),
                    files=_csv("nome;email;senha;nivel\nBia;bia@x.com;senha-123456;user\n"))
    assert r.status_code == 200, r.text
    assert r.json()["criados"] == 1
    bia = next(u for u in banco.tabelas["users"] if u["email"] == "bia@x.com")
    assert bia.get("deve_trocar_senha") is True
    assert bia.get("ativo") is True


def test_senha_do_csv_nao_abre_o_portal(client: TestClient, banco: _Fake) -> None:
    client.post("/api/users/import", headers=_h(*ADMIN),
                files=_csv("nome;email;senha;nivel\nBia;bia@x.com;senha-123456;user\n"))
    token = _login(client, "bia@x.com", "senha-123456").json()["access_token"]
    r = client.get("/api/permissoes/minhas", headers={"Authorization": "Bearer " + token})
    assert r.status_code == 403
    assert r.headers.get("X-Senha-Provisoria") == "1"


def test_gestor_nao_importa_admin_por_csv(
    client: TestClient, banco: _Fake, gestor_edita_usuarios: None
) -> None:
    r = client.post("/api/users/import", headers=_h(*GESTOR),
                    files=_csv("nome;email;senha;nivel\nBia;bia@x.com;senha-123456;admin\n"))
    assert r.status_code == 200, r.text
    assert r.json()["criados"] == 0
    assert not any(u["email"] == "bia@x.com" for u in banco.tabelas["users"])


# ──────────────────────────────────────────────────────────────────────────
# #24 — reset por admin carimba senha_alterada_em
# ──────────────────────────────────────────────────────────────────────────

def test_reset_por_admin_derruba_a_sessao_antiga(
    client: TestClient, banco: _Fake, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datetime import datetime as _dt, timedelta

    # Sessão aberta 30 s ANTES do reset: `_senha_trocada_depois_do_token` tem
    # margem de 5 s para relógios fora de sincronia, e um token emitido no
    # mesmo segundo do reset cairia dentro dela.
    class _Passado(_dt):
        @classmethod
        def now(cls, tz=None):
            return _dt.now(tz) - timedelta(seconds=30)

    with monkeypatch.context() as mp:
        mp.setattr(auth, "datetime", _Passado)
        token_ana = _login(client, "ana@x.com").json()["access_token"]
    assert client.post("/api/users/u-ana/reset-password", headers=_h(*ADMIN),
                       json={"password": "senha-123456"}).status_code == 200
    r = client.post("/api/senha/trocar", headers={"Authorization": "Bearer " + token_ana},
                    json={"senha_atual": SENHA, "nova_senha": "outra-senha-12"})
    assert r.status_code == 401, r.text


# ──────────────────────────────────────────────────────────────────────────
# #13 / #14 — helpers do front, executados no node
# ──────────────────────────────────────────────────────────────────────────

def _funcao_js(nome: str) -> str:
    fonte = UI_COMMON.read_text(encoding="utf-8")
    m_ = re.search(rf"^function {nome}\(.*?^\}}", fonte, re.S | re.M)
    assert m_, f"function {nome} não está em ui-common.js"
    return m_.group(0)


def _node(js: str) -> str:
    r = subprocess.run([NODE, "-e", js], capture_output=True, text=True, timeout=20)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


# `innerHTML` de um nó de texto escapa só & < >: é o que o navegador faz e o
# que a versão antiga de `esc()` devolvia.
_DOM_DO_NAVEGADOR = """
const document = { createElement: () => ({ set textContent(v) { this._t = v; },
  get innerHTML() { return this._t.replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;"); } }) };
"""


@pytest.mark.skipif(NODE is None, reason="node não está no PATH")
def test_esc_escapa_aspas() -> None:
    saida = _node(_DOM_DO_NAVEGADOR + _funcao_js("esc") + """
console.log(esc('a"b\\'c<d>&e'));""")
    assert saida == "a&quot;b&#39;c&lt;d&gt;&amp;e"


@pytest.mark.skipif(NODE is None, reason="node não está no PATH")
def test_esc_dentro_de_atributo_nao_fecha_o_atributo() -> None:
    saida = _node(_DOM_DO_NAVEGADOR + _funcao_js("esc") + """
const titular = '" onmouseover="x';
console.log(`<span title="${esc(titular)}">`);""")
    assert 'onmouseover="' not in saida.replace("&quot;", "")
    assert saida.count('"') == 2


@pytest.mark.skipif(NODE is None, reason="node não está no PATH")
@pytest.mark.parametrize("celula, esperado", [
    ("=1+1", "\"'=1+1\""),
    ("+55 11", "\"'+55 11\""),
    ("-5", "\"'-5\""),
    ("@SUM(A1)", "\"'@SUM(A1)\""),
    ("\tx", "\"'\tx\""),
    ('diz "oi"', '"diz ""oi"""'),
    ("normal", '"normal"'),
])
def test_celula_csv_neutraliza_formula(celula: str, esperado: str) -> None:
    saida = _node(_funcao_js("celulaCsv") + f"\nconsole.log(celulaCsv({celula!r}));")
    assert saida == esperado


@pytest.mark.parametrize("template", ["index.html", "historico.html", "vencidos.html"])
def test_exportacao_csv_usa_o_helper_compartilhado(template: str) -> None:
    html = (TEMPLATES / template).read_text(encoding="utf-8")
    assert "celulaCsv" in html
    assert "replace(/\"/g, '\"\"')" not in html, "escape de CSV copiado no template"


def test_templates_apontam_para_o_ui_common_novo() -> None:
    """`esc()` e `celulaCsv` só chegam ao navegador se o cache-buster mudar."""
    versoes = set()
    for t in TEMPLATES.glob("*.html"):
        for v in re.findall(r"ui-common\.js\?v=([\w.-]+)", t.read_text(encoding="utf-8")):
            versoes.add(v)
    assert versoes and versoes != {"aguia-2026-09e"}, versoes
    assert len(versoes) == 1, f"templates com versões diferentes: {versoes}"


# ──────────────────────────────────────────────────────────────────────────
# #15 — SMTP
# ──────────────────────────────────────────────────────────────────────────

class _SmtpFalso:
    instancias: List["_SmtpFalso"] = []

    def __init__(self, host: str, port: int, timeout: float = 0, context: Any = None) -> None:
        self.host, self.port, self.context = host, port, context
        self.starttls_context: Any = "nao-chamado"
        self.logins: List = []
        _SmtpFalso.instancias.append(self)

    def __enter__(self) -> "_SmtpFalso":
        return self

    def __exit__(self, *_a: Any) -> None:
        return None

    def starttls(self, context: Any = None) -> None:
        self.starttls_context = context

    def login(self, u: str, p: str) -> None:
        self.logins.append(u)

    def sendmail(self, *_a: Any) -> None:
        return None


@pytest.fixture
def smtplib_falso(monkeypatch: pytest.MonkeyPatch) -> type:
    _SmtpFalso.instancias = []
    monkeypatch.setattr(smtp_service.smtplib, "SMTP", _SmtpFalso)
    monkeypatch.setattr(smtp_service.smtplib, "SMTP_SSL", _SmtpFalso)
    return _SmtpFalso


def _enviar(**kw: Any) -> None:
    base = dict(host="smtp.exemplo.com", port=587, user="u@x.com",
                password_enc=smtp_service.encrypt_password("segredo"),
                use_tls=True, use_ssl=False, from_email="u@x.com",
                to_email="d@x.com", subject="t", html_content="<p>x</p>")
    base.update(kw)
    smtp_service.send_smtp_email(**base)


def _contexto_verifica(ctx: Any) -> bool:
    return isinstance(ctx, ssl.SSLContext) and ctx.verify_mode == ssl.CERT_REQUIRED and ctx.check_hostname


def test_starttls_verifica_o_certificado_do_servidor(smtplib_falso: type) -> None:
    _enviar(use_tls=True, use_ssl=False)
    assert _contexto_verifica(smtplib_falso.instancias[0].starttls_context)


def test_ssl_implicito_verifica_o_certificado_do_servidor(smtplib_falso: type) -> None:
    _enviar(use_tls=False, use_ssl=True, port=465)
    assert _contexto_verifica(smtplib_falso.instancias[0].context)


def test_credencial_sem_tls_e_recusada_para_servidor_externo(smtplib_falso: type) -> None:
    with pytest.raises(ValueError):
        _enviar(use_tls=False, use_ssl=False)
    assert not smtplib_falso.instancias, "não pode nem abrir a conexão"


def test_sem_tls_e_aceito_para_servidor_local(smtplib_falso: type) -> None:
    _enviar(use_tls=False, use_ssl=False, host="127.0.0.1", port=25)
    assert smtplib_falso.instancias[0].starttls_context == "nao-chamado"


def test_configuracao_recusa_nenhuma_com_servidor_externo(client: TestClient) -> None:
    r = client.put("/api/settings", headers=_h(*ADMIN), json={
        "smtp_host": "smtp.exemplo.com", "smtp_port": 25, "smtp_use_tls": False, "smtp_use_ssl": False,
    })
    assert r.status_code == 422, r.text


def test_tela_avisa_que_nenhuma_e_so_para_servidor_local() -> None:
    html = (TEMPLATES / "configuracao.html").read_text(encoding="utf-8")
    opcao = re.search(r'<option value="nenhuma">([^<]*)</option>', html)
    assert opcao and "local" in opcao.group(1).lower()


# ──────────────────────────────────────────────────────────────────────────
# #20 — .gitignore e hook
# ──────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("caminho", [
    "certificados/x.p12", "x.p12", "chave.pem", "chave.key", "cert.cer", "cert.crt",
    "app/main.py.bak", "app/main.py.orig", "agent_config.json", "certificados_vencidos/a.pfx",
])
def test_gitignore_cobre_material_de_certificado(caminho: str) -> None:
    r = subprocess.run(["git", "check-ignore", "-q", caminho], cwd=RAIZ, capture_output=True)
    assert r.returncode == 0, f"{caminho} não está ignorado"


@pytest.mark.skipif(SH is None, reason="sh não está no PATH")
@pytest.mark.parametrize("arquivo, esperado", [("segredo.p12", 1), ("cert.pfx", 1), ("chave.pem", 1),
                                               ("chave.key", 1), ("codigo.py", 0)])
def test_hook_pre_commit_recusa_material_de_certificado(arquivo: str, esperado: int) -> None:
    hook = RAIZ / ".githooks" / "pre-commit"
    assert hook.exists(), ".githooks/pre-commit não existe"
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(["git", "init", "-q", tmp], check=True)
        (Path(tmp) / arquivo).write_bytes(b"x")
        subprocess.run(["git", "-C", tmp, "add", arquivo], check=True)
        r = subprocess.run([SH, str(hook)], cwd=tmp, capture_output=True, text=True)
    assert (r.returncode != 0) == (esperado == 1), (arquivo, r.returncode, r.stderr)


# ──────────────────────────────────────────────────────────────────────────
# #35 — erros sem o texto da exceção
# ──────────────────────────────────────────────────────────────────────────

SEGREDO_NO_ERRO = "SEGREDO-NA-EXCECAO-7f3a"


def test_erro_inesperado_sai_com_referencia_e_sem_o_texto(monkeypatch: pytest.MonkeyPatch) -> None:
    def _explode() -> bool:
        raise RuntimeError(SEGREDO_NO_ERRO)

    monkeypatch.setattr(m, "banco_configurado", _explode)
    cliente = TestClient(m.app, raise_server_exceptions=False)
    r = cliente.get("/api/health/detalhado", headers=_h(*ADMIN))
    assert r.status_code == 500
    corpo = r.json()
    assert corpo["detail"] == "Erro interno"
    assert corpo.get("ref")
    assert SEGREDO_NO_ERRO not in r.text


def test_listagem_de_certificados_nao_vaza_a_excecao(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    def _explode(*_a: Any, **_k: Any) -> dict:
        raise RuntimeError(SEGREDO_NO_ERRO)

    monkeypatch.setattr(m, "_list_certificados_payload", _explode)
    r = client.get("/api/certificados", headers=_h(*ADMIN))
    assert r.status_code == 500
    assert SEGREDO_NO_ERRO not in r.text
    assert "uvicorn" not in r.text.lower()


def test_importacao_csv_nao_vaza_o_erro_do_banco(client: TestClient, banco: _Fake, monkeypatch: pytest.MonkeyPatch) -> None:
    def _explode(*_a: Any, **_k: Any) -> str:
        raise RuntimeError(SEGREDO_NO_ERRO)

    monkeypatch.setattr(auth, "get_password_hash", _explode)
    r = client.post("/api/users/import", headers=_h(*ADMIN),
                    files=_csv("nome;email;senha;nivel\nBia;bia@x.com;senha-123456;user\n"))
    assert r.status_code == 200
    assert r.json()["erros"], "a linha tem de aparecer como erro"
    assert SEGREDO_NO_ERRO not in r.text


@pytest.mark.parametrize("classe, trecho", [
    ("ErroAutenticacaoSmtp", "usuário ou a senha"),
    ("ErroConexaoSmtp", "conectar"),
    ("ErroTlsSmtp", "segura"),
    ("ErroSmtp", "log"),
])
def test_teste_de_smtp_responde_por_classe_de_erro(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, classe: str, trecho: str
) -> None:
    excecao = getattr(smtp_service, classe)

    def _falha(**_k: Any) -> None:
        raise excecao("535 5.7.8 " + SEGREDO_NO_ERRO)

    monkeypatch.setattr(smtp_service, "send_smtp_email", _falha)
    monkeypatch.setattr(m, "load_settings", lambda: type("S", (), {
        "smtp_host": "smtp.x", "smtp_port": 587, "smtp_user": "u", "smtp_password_encrypted": "",
        "smtp_use_tls": True, "smtp_use_ssl": False, "smtp_from_email": "u@x"})())
    r = client.post("/api/settings/smtp/test", headers=_h(*ADMIN), json={"target_email": "d@x.com"})
    assert r.status_code == 400
    assert trecho in r.json()["detail"].lower()
    assert SEGREDO_NO_ERRO not in r.text


def test_nenhum_except_generico_devolve_str_da_excecao() -> None:
    """Fonte: `except Exception`/`RuntimeError` seguido de `detail=str(e)` é o padrão que vaza."""
    fonte = (RAIZ / "app" / "main.py").read_text(encoding="utf-8").splitlines()
    ruins = []
    for i, linha in enumerate(fonte):
        if re.search(r"except (Exception|RuntimeError)( as e)?:", linha):
            bloco = "\n".join(fonte[i:i + 5])
            if re.search(r"detail=.*(str\(e\)|\{e\})", bloco):
                ruins.append(i + 1)
    assert not ruins, f"linhas com detail=str(e) em except genérico: {ruins}"


def test_smtp_classifica_a_falha(monkeypatch: pytest.MonkeyPatch) -> None:
    import smtplib

    class _Recusa(_SmtpFalso):
        def login(self, u: str, p: str) -> None:
            raise smtplib.SMTPAuthenticationError(535, b"5.7.8 Username and Password not accepted")

    _SmtpFalso.instancias = []
    monkeypatch.setattr(smtp_service.smtplib, "SMTP", _Recusa)
    with pytest.raises(smtp_service.ErroAutenticacaoSmtp):
        _enviar()


# ──────────────────────────────────────────────────────────────────────────
# #48 / #49 / #50 / #36 — cabeçalhos, health e Host
# ──────────────────────────────────────────────────────────────────────────

def test_health_publico_so_diz_que_esta_vivo(client: TestClient) -> None:
    assert client.get("/api/health").json() == {"ok": True}


def test_health_detalhado_exige_admin(client: TestClient) -> None:
    assert client.get("/api/health/detalhado").status_code in (401, 403)
    assert client.get("/api/health/detalhado", headers=_h("ana@x.com", "user")).status_code == 403
    j = client.get("/api/health/detalhado", headers=_h(*ADMIN)).json()
    assert "api_key_required" in j and "banco" in j


def test_csp_tem_base_uri_none(client: TestClient) -> None:
    csp = client.get("/api/health").headers["Content-Security-Policy"]
    assert "base-uri 'none'" in csp


def test_servidor_sobe_sem_cabecalho_server() -> None:
    assert "--no-server-header" in (RAIZ / "scripts" / "servir.ps1").read_text(encoding="utf-8")
    assert "server_header" in (RAIZ / "app" / "worker.py").read_text(encoding="utf-8")
    assert "app.worker" in (RAIZ / "Procfile").read_text(encoding="utf-8")


def test_host_fora_da_lista_e_recusado(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "HOSTS_PERMITIDOS", ["portal.exemplo", "10.200.0.4"], raising=False)
    assert client.get("/api/health", headers={"Host": "evil.exemplo"}).status_code == 400
    assert client.get("/api/health", headers={"Host": "portal.exemplo"}).status_code == 200
    assert client.get("/api/health", headers={"Host": "portal.exemplo:8020"}).status_code == 200
    assert client.get("/api/health", headers={"Host": "10.200.0.4:8020"}).status_code == 200


def test_sem_lista_de_hosts_nada_muda(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Janela de compatibilidade: sem HOSTS_PERMITIDOS o portal aceita qualquer Host."""
    monkeypatch.setattr(config, "HOSTS_PERMITIDOS", [], raising=False)
    assert client.get("/api/health", headers={"Host": "qualquer.coisa"}).status_code == 200
