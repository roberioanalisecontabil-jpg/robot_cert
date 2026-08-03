"""Testes das correções críticas do Módulo Instalador de Certificados.

Três defeitos que permitiam roubo ou substituição de certificado:

1. `/upload-pfx` usava `require_auth`, que aceita qualquer usuário do portal.
   Como `upsert_pfx` grava com `on_conflict="fingerprint"`, um usuário comum
   podia enviar um PFX próprio com o fingerprint de um certificado existente e
   sobrescrever o registro legítimo — o certificado do atacante acabaria
   instalado num servidor pelo fluxo normal de instalação.

2. `validate_and_consume_token` fazia SELECT e depois UPDATE em duas chamadas.
   Dois resgates simultâneos passavam pelo SELECT antes de qualquer UPDATE e
   ambos recebiam o bundle: "uso único" era só intenção.

3. As tabelas do módulo foram criadas sem RLS, destoando das 4 tabelas
   anteriores do projeto — e `cert_pfx_store` guarda os PFX e as senhas.
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import auth
import app.cert_installer as ci


# ==========================================================================
# 1. Autorização dos endpoints de máquina
# ==========================================================================

def _jwt(role: str, email: str = "alguem@exemplo.com") -> dict:
    return {"Authorization": f"Bearer {auth.create_access_token({'sub': email, 'role': role})}"}


ROTAS_DE_MAQUINA = [
    ("/api/cert-installer/upload-pfx", {"fingerprint": "a" * 64, "pfx_b64": "AAAA", "machine_id": "m1"}),
    ("/api/cert-installer/redeem", {"token": "x", "clientPublicKey": "AAAA"}),
    ("/api/cert-installer/report", {"token": "x", "results": []}),
]


def _barrado_na_autorizacao(resposta) -> bool:
    """
    Distingue "barrado pela autorização" de "passou e falhou na regra de negócio".

    Necessário porque /redeem também responde 403 para token inválido: olhar só
    o código de status confundiria as duas coisas e o teste passaria por engano.
    """
    from app.main import ERRO_ACESSO_MAQUINA

    if resposta.status_code == 401:
        return True
    if resposta.status_code != 403:
        return False
    try:
        return resposta.json().get("detail") == ERRO_ACESSO_MAQUINA
    except Exception:
        return False


@pytest.mark.parametrize("rota, corpo", ROTAS_DE_MAQUINA)
def test_usuario_comum_nao_acessa_rotas_de_maquina(client: TestClient, rota: str, corpo: dict) -> None:
    r = client.post(rota, json=corpo, headers=_jwt("user"))
    assert _barrado_na_autorizacao(r), f"{rota} aceitou role 'user' ({r.status_code}: {r.text[:120]})"


@pytest.mark.parametrize("rota, corpo", ROTAS_DE_MAQUINA)
def test_sem_credencial_nenhuma_e_recusado(client: TestClient, rota: str, corpo: dict) -> None:
    """
    A fixture `client` roda SEM API_KEY. Nesse modo `require_auth` devolve uma
    identidade anônima com role 'agent' para compatibilidade com rotas antigas —
    o que daria acesso livre a PFX e senhas. `require_agent_or_admin` recusa.
    """
    r = client.post(rota, json=corpo)
    assert _barrado_na_autorizacao(r), f"{rota} aceitou requisição anônima ({r.status_code})"


@pytest.mark.parametrize("rota, corpo", ROTAS_DE_MAQUINA)
def test_agente_passa_pela_autorizacao(
    client_com_chave: TestClient, api_key: str, rota: str, corpo: dict
) -> None:
    """
    O agente autentica com X-API-Key e recebe role 'agent'.
    `require_admin` teria quebrado o agente — daí `require_agent_or_admin`.
    O que acontece depois da autorização não importa aqui.
    """
    r = client_com_chave.post(rota, json=corpo, headers={"X-API-Key": api_key})
    assert not _barrado_na_autorizacao(r), f"{rota} bloqueou o agente ({r.text[:120]})"


@pytest.mark.parametrize("rota, corpo", ROTAS_DE_MAQUINA)
def test_admin_passa_pela_autorizacao(
    client_com_chave: TestClient, rota: str, corpo: dict
) -> None:
    r = client_com_chave.post(rota, json=corpo, headers=_jwt("admin", "admin@exemplo.com"))
    assert not _barrado_na_autorizacao(r), f"{rota} bloqueou admin ({r.text[:120]})"


# ==========================================================================
# 2. Consumo atômico do token (compare-and-swap)
# ==========================================================================

class _FakeTable:
    """
    Simula o comportamento do Postgres para UPDATE ... WHERE numa única linha:
    o primeiro que casa com as condições escreve; os demais casam com 0 linhas.
    """

    def __init__(self, linhas: list):
        self._linhas = linhas
        self._update = None
        self._filtros = []

    def update(self, valores):
        self._update = valores
        return self

    def select(self, *a, **k):
        return self

    def eq(self, campo, valor):
        self._filtros.append(("eq", campo, valor))
        return self

    def is_(self, campo, valor):
        self._filtros.append(("is", campo, valor))
        return self

    def gt(self, campo, valor):
        self._filtros.append(("gt", campo, valor))
        return self

    def execute(self):
        casadas = []
        for linha in self._linhas:
            ok = True
            for tipo, campo, valor in self._filtros:
                if tipo == "eq" and linha.get(campo) != valor:
                    ok = False
                elif tipo == "is" and valor == "null" and linha.get(campo) is not None:
                    ok = False
                elif tipo == "gt" and not (str(linha.get(campo) or "") > str(valor)):
                    ok = False
            if ok:
                casadas.append(linha)

        if self._update is not None:
            for linha in casadas:
                linha.update(self._update)  # a escrita fecha a janela para o próximo

        class _R:
            data = [dict(x) for x in casadas]

        return _R()


class _FakeClient:
    def __init__(self, linhas):
        self._linhas = linhas

    def table(self, _nome):
        return _FakeTable(self._linhas)


@pytest.fixture
def token_valido(monkeypatch):
    import hashlib

    bruto = "token-de-teste"
    futuro = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
    linha = {
        "id": "tok-1",
        "token_hash": hashlib.sha256(bruto.encode()).hexdigest(),
        "user_id": "u-1",
        "user_email": "admin@exemplo.com",
        "target_machine": "SRV01",
        "certificate_ids": ["c-1"],
        "expires_at": futuro,
        "consumed_at": None,
    }
    monkeypatch.setattr(ci, "_supabase", lambda: _FakeClient([linha]))
    return bruto, linha


def test_token_valido_e_consumido_uma_vez(token_valido) -> None:
    bruto, linha = token_valido
    assert ci.validate_and_consume_token(bruto) is not None
    assert linha["consumed_at"] is not None


def test_segundo_resgate_do_mesmo_token_falha(token_valido) -> None:
    """O defeito original: os dois passavam."""
    bruto, _ = token_valido
    primeiro = ci.validate_and_consume_token(bruto)
    segundo = ci.validate_and_consume_token(bruto)
    assert primeiro is not None
    assert segundo is None, "token de uso único foi resgatado duas vezes"


def test_resgates_concorrentes_produzem_um_unico_vencedor(token_valido) -> None:
    """
    Dez threads disputando o mesmo token. Com SELECT-depois-UPDATE, várias
    venciam; com compare-and-swap, exatamente uma.
    """
    import threading

    bruto, _ = token_valido
    resultados = []
    trava = threading.Lock()

    def resgatar():
        r = ci.validate_and_consume_token(bruto)
        with trava:
            resultados.append(r)

    threads = [threading.Thread(target=resgatar) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    vencedores = [r for r in resultados if r is not None]
    assert len(vencedores) == 1, f"{len(vencedores)} resgates venceram; esperado 1"


def test_token_expirado_e_recusado(monkeypatch) -> None:
    import hashlib

    bruto = "token-velho"
    passado = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    linha = {
        "id": "tok-2",
        "token_hash": hashlib.sha256(bruto.encode()).hexdigest(),
        "expires_at": passado,
        "consumed_at": None,
    }
    monkeypatch.setattr(ci, "_supabase", lambda: _FakeClient([linha]))

    assert ci.validate_and_consume_token(bruto) is None
    assert linha["consumed_at"] is None, "token expirado não deve ser marcado como consumido"


def test_token_inexistente_e_recusado(monkeypatch) -> None:
    monkeypatch.setattr(ci, "_supabase", lambda: _FakeClient([]))
    assert ci.validate_and_consume_token("nao-existe") is None


# ==========================================================================
# 3. RLS nas tabelas do módulo
# ==========================================================================

MIGRATIONS = Path(__file__).resolve().parent.parent / "supabase" / "migrations"
TABELAS_DO_MODULO = ["cert_pfx_store", "install_token", "install_log"]


@pytest.fixture(scope="module")
def sql_migrations() -> str:
    return "\n".join(
        p.read_text(encoding="utf-8") for p in sorted(MIGRATIONS.glob("*.sql"))
    )


@pytest.mark.parametrize("tabela", TABELAS_DO_MODULO)
def test_rls_habilitado(sql_migrations: str, tabela: str) -> None:
    esperado = f"ALTER TABLE public.{tabela}  ENABLE ROW LEVEL SECURITY;"
    normalizado = " ".join(sql_migrations.split())
    assert " ".join(esperado.split()) in normalizado, f"{tabela} sem RLS"


@pytest.mark.parametrize("tabela", TABELAS_DO_MODULO)
def test_acesso_anonimo_revogado(sql_migrations: str, tabela: str) -> None:
    normalizado = " ".join(sql_migrations.split())
    assert f"REVOKE ALL ON public.{tabela} FROM anon, authenticated;" in normalizado


@pytest.mark.parametrize("tabela", TABELAS_DO_MODULO)
def test_politica_para_service_role(sql_migrations: str, tabela: str) -> None:
    assert f"ON public.{tabela}" in sql_migrations
    assert f"service_role_acesso_total_{tabela}" in sql_migrations
