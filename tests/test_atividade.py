"""Registro de atividade do usuário.

É a contraproposta ao pedido "tempo de uso do portal por usuário". O que estes
testes guardam, em ordem de importância:

**1. Não pode derrubar o login.** `registrar` é chamada do caminho de
autenticação. Telemetria que impede alguém de entrar no portal é pior que
telemetria nenhuma — e é um jeito fácil de transformar uma tabela nova numa
indisponibilidade total.

**2. Não vira cronômetro.** Eventos discretos, vocabulário fechado. A tarefa do
usuário final dura menos de um minuto; sessão longa neste portal significa que
a pessoa não achou o que queria, e um número que sobe quando a ferramenta piora
não serve para decidir nada.

**3. Não duplica `install_log`.** Aquela já registra quem instalou o quê e com
que desfecho. O painel junta as duas na leitura; cada fato mora num lugar só.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import pytest
from fastapi.testclient import TestClient

from app import atividade, auth
import app.dashboard as dash
import app.main as m
from app.settings_state import PortalSettings


AGORA = datetime.now(timezone.utc)


class _Resultado:
    def __init__(self, data: List[Dict[str, Any]]) -> None:
        self.data = data


class _Query:
    def __init__(self, linhas: List[Dict[str, Any]], banco: "_Fake", nome: str) -> None:
        self._l, self._b, self._n = linhas, banco, nome
        self._filtros: List[tuple] = []
        self._payload: Any = None
        self._op = "select"
        self._range: Optional[tuple] = None

    def select(self, *_c: str) -> "_Query":
        return self

    def insert(self, row: Dict[str, Any]) -> "_Query":
        self._op, self._payload = "insert", row
        return self

    def delete(self) -> "_Query":
        self._op = "delete"
        return self

    def eq(self, c: str, v: Any) -> "_Query":
        self._filtros.append(("eq", c, v))
        return self

    def gte(self, c: str, v: Any) -> "_Query":
        self._filtros.append(("gte", c, v))
        return self

    def lt(self, c: str, v: Any) -> "_Query":
        self._filtros.append(("lt", c, v))
        return self

    def limit(self, _n: int) -> "_Query":
        return self

    def range(self, i: int, f: int) -> "_Query":
        self._range = (i, f)
        return self

    def _casa(self, r: Dict[str, Any]) -> bool:
        for op, c, v in self._filtros:
            a = r.get(c)
            if op == "eq" and a != v:
                return False
            if op == "gte" and not (a and str(a) >= str(v)):
                return False
            if op == "lt" and not (a and str(a) < str(v)):
                return False
        return True

    def execute(self) -> _Resultado:
        if self._b.quebrado.get(self._n):
            raise RuntimeError(f"banco fora do ar ao usar {self._n}")
        if self._op == "insert":
            self._l.append(dict(self._payload))
            return _Resultado([dict(self._payload)])
        if self._op == "delete":
            fora = [r for r in self._l if self._casa(r)]
            self._l[:] = [r for r in self._l if not self._casa(r)]
            return _Resultado(fora)
        linhas = [dict(r) for r in self._l if self._casa(r)]
        if self._range:
            i, f = self._range
            linhas = linhas[i : f + 1]
        return _Resultado(linhas)


class _Fake:
    def __init__(self, tabelas: Dict[str, List[Dict[str, Any]]]) -> None:
        self.tabelas = tabelas
        self.quebrado: Dict[str, bool] = {}

    def table(self, nome: str) -> _Query:
        return _Query(self.tabelas.setdefault(nome, []), self, nome)


SENHA = "segredo123"


@pytest.fixture
def banco(monkeypatch: pytest.MonkeyPatch) -> _Fake:
    h = auth.get_password_hash(SENHA)
    fake = _Fake({
        "users": [
            {"id": "u-1", "email": "ana@x.com", "role": "user", "ativo": True, "password_hash": h},
            {"id": "u-2", "email": "off@x.com", "role": "user", "ativo": False, "password_hash": h},
        ],
        "user_activity": [],
        "install_log": [],
    })
    cfg = PortalSettings(source_folder="", expired_folder="")
    monkeypatch.setattr("app.settings_state._supabase", lambda: fake)
    monkeypatch.setattr("app.settings_state.load_settings", lambda: cfg)
    monkeypatch.setattr(m, "load_settings", lambda: cfg)
    monkeypatch.setattr(dash, "_supabase", lambda: fake)
    fake.cfg = cfg
    return fake


# ──────────────────────────────────────────────────────────────────────────
# 1. Telemetria não pode derrubar o que observa
# ──────────────────────────────────────────────────────────────────────────

def test_falha_ao_registrar_nao_impede_o_login(client: TestClient, banco: _Fake) -> None:
    """
    O teste mais importante do arquivo.

    `registrar` é chamada do caminho de autenticação. Se ela levantasse, uma
    tabela nova viraria indisponibilidade total do portal — e o modo de falha
    seria "ninguém consegue entrar", que é o pior possível.
    """
    banco.quebrado["user_activity"] = True

    r = client.post("/api/login", json={"email": "ana@x.com", "password": SENHA})
    assert r.status_code == 200, r.text
    assert r.json()["role"] == "user"


def test_registrar_nunca_levanta_mesmo_sem_banco(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.settings_state._supabase", lambda: None)
    atividade.registrar(atividade.EVENTO_LOGIN, "u-1", "ana@x.com")   # não deve levantar


def test_evento_fora_do_vocabulario_e_ignorado(banco: _Fake) -> None:
    """
    Texto livre viraria uma sopa de grafias em três meses, e a agregação
    passaria a mentir por diferença de acento. O banco também recusa (CHECK);
    aqui a recusa é silenciosa de propósito, porque isto é telemetria.
    """
    atividade.registrar("navegou_na_pagina", "u-1", "ana@x.com")
    assert banco.tabelas["user_activity"] == []


# ──────────────────────────────────────────────────────────────────────────
# 2. O que o login registra
# ──────────────────────────────────────────────────────────────────────────

def test_login_bem_sucedido_e_registrado(client: TestClient, banco: _Fake) -> None:
    client.post("/api/login", json={"email": "ana@x.com", "password": SENHA})
    ev = banco.tabelas["user_activity"]
    assert len(ev) == 1
    assert ev[0]["evento"] == "login"
    assert ev[0]["user_id"] == "u-1"
    assert ev[0]["user_email"] == "ana@x.com"


def test_senha_errada_em_conta_existente_e_registrada(client: TestClient, banco: _Fake) -> None:
    """Responde "alguém está tentando entrar nesta conta" — o caso que importa."""
    client.post("/api/login", json={"email": "ana@x.com", "password": "errada"})
    ev = banco.tabelas["user_activity"]
    assert len(ev) == 1
    assert ev[0]["evento"] == "login_negado"
    assert ev[0]["contexto"]["motivo"] == "senha_incorreta"


def test_email_inexistente_nao_vira_registro(client: TestClient, banco: _Fake) -> None:
    """
    Guardar o e-mail tentado seria guardar entrada arbitrária de quem chamou —
    inclusive de um varredor automático. Sem conta, sem registro.
    """
    client.post("/api/login", json={"email": "ninguem@x.com", "password": "x"})
    assert banco.tabelas["user_activity"] == []


def test_conta_desativada_registra_o_motivo(client: TestClient, banco: _Fake) -> None:
    client.post("/api/login", json={"email": "off@x.com", "password": SENHA})
    ev = banco.tabelas["user_activity"]
    assert ev[0]["evento"] == "login_negado"
    assert ev[0]["contexto"]["motivo"] == "conta_desativada"


# ──────────────────────────────────────────────────────────────────────────
# 3. Retenção — uma só para a trilha inteira
# ──────────────────────────────────────────────────────────────────────────

def test_retencao_zero_nao_apaga_nada(banco: _Fake) -> None:
    banco.tabelas["user_activity"] = [
        {"ocorrido_em": (AGORA - timedelta(days=400)).isoformat()}
    ]
    r = atividade.expurgar(dias=0)
    assert r["executado"] is False
    assert len(banco.tabelas["user_activity"]) == 1


def test_expurgo_respeita_o_prazo(banco: _Fake) -> None:
    banco.tabelas["user_activity"] = [
        {"id": "novo", "ocorrido_em": (AGORA - timedelta(days=5)).isoformat()},
        {"id": "velho", "ocorrido_em": (AGORA - timedelta(days=100)).isoformat()},
    ]
    r = atividade.expurgar(dias=30)
    assert r["apagados"] == 1
    assert [x["id"] for x in banco.tabelas["user_activity"]] == ["novo"]


def test_expurgo_usa_a_retencao_da_trilha(banco: _Fake) -> None:
    """
    Um ajuste para as duas tabelas: são o mesmo tipo de dado, com a mesma
    justificativa. Dois botões seria convite a configurar um e esquecer o outro.
    """
    banco.cfg.trilha_retencao_dias = 30
    banco.tabelas["user_activity"] = [
        {"id": "velho", "ocorrido_em": (AGORA - timedelta(days=100)).isoformat()}
    ]
    assert atividade.expurgar()["apagados"] == 1


def test_expurgo_relata_falha_em_vez_de_levantar(banco: _Fake) -> None:
    banco.quebrado["user_activity"] = True
    r = atividade.expurgar(dias=30)
    assert r["executado"] is False


def test_cron_expurga_toda_a_trilha_e_o_cofre(client: TestClient, banco: _Fake, monkeypatch) -> None:
    """
    O cron diário carrega três expurgos. O do cofre entrou em 16/08: chave
    privada de certificado vencido ou removido da pasta é passivo puro, e o
    acervo só crescia porque nada a tirava.
    """
    monkeypatch.setenv("CRON_SECRET", "s3gr3d0")
    monkeypatch.setattr(m, "trigger_all_alerts", lambda: {"enviados": 0})

    r = client.get("/api/cron/alerts", headers={"Authorization": "Bearer s3gr3d0"})
    assert r.status_code == 200, r.text
    assert set(r.json()["expurgo"]) == {"install_log", "user_activity", "cofre"}


# ──────────────────────────────────────────────────────────────────────────
# 4. O painel: quem está usando, e quem travou
# ──────────────────────────────────────────────────────────────────────────

@pytest.fixture
def com_atividade(banco: _Fake) -> _Fake:
    banco.tabelas["user_activity"] = [
        {"user_email": "ana@x.com", "evento": "login", "ocorrido_em": (AGORA - timedelta(hours=2)).isoformat()},
        {"user_email": "ana@x.com", "evento": "login", "ocorrido_em": (AGORA - timedelta(days=1)).isoformat()},
        {"user_email": "bruno@x.com", "evento": "login", "ocorrido_em": (AGORA - timedelta(days=3)).isoformat()},
        {"user_email": "bruno@x.com", "evento": "login_negado", "ocorrido_em": (AGORA - timedelta(days=3)).isoformat()},
    ]
    banco.tabelas["install_log"] = [
        {"user_email": "ana@x.com", "event": "SOLICITADO", "status": None,
         "created_at": (AGORA - timedelta(hours=1)).isoformat()},
        {"user_email": "ana@x.com", "event": "CONCLUIDO", "status": "OK",
         "created_at": (AGORA - timedelta(minutes=50)).isoformat()},
        {"user_email": "bruno@x.com", "event": "SOLICITADO", "status": None,
         "created_at": (AGORA - timedelta(days=2)).isoformat()},
        {"user_email": "bruno@x.com", "event": "ERRO", "status": "FALHA",
         "created_at": (AGORA - timedelta(days=2)).isoformat()},
    ]
    return banco


def test_painel_junta_as_duas_fontes(com_atividade: _Fake) -> None:
    """
    Logins vêm de `user_activity`, instalações de `install_log`. Duplicar os
    eventos de instalação aqui criaria duas fontes de verdade sobre o mesmo
    fato — e é assim que elas divergem.
    """
    p = dash.painel_atividade(30)
    por_email = {u["user_email"]: u for u in p["usuarios"]}

    assert por_email["ana@x.com"]["logins"] == 2
    assert por_email["ana@x.com"]["instalacoes_concluidas"] == 1
    assert por_email["bruno@x.com"]["logins_negados"] == 1
    assert por_email["bruno@x.com"]["instalacoes_falhadas"] == 1


def test_travado_e_quem_pediu_e_nao_concluiu(com_atividade: _Fake) -> None:
    """
    O campo que responde "quem travou". É gente provavelmente esperando alguém
    — o gestor atribuir carteira, o agente enviar o certificado — sem saber.
    """
    p = dash.painel_atividade(30)
    assert p["sem_sucesso"] == 1, "bruno pediu e não concluiu; ana concluiu"


def test_ordena_por_ultima_atividade(com_atividade: _Fake) -> None:
    p = dash.painel_atividade(30)
    assert [u["user_email"] for u in p["usuarios"]] == ["ana@x.com", "bruno@x.com"]


def test_painel_nao_expoe_tempo_de_sessao(com_atividade: _Fake) -> None:
    """
    Guarda a decisão, não só a implementação: se alguém acrescentar duração,
    este teste reclama antes de o número virar meta.
    """
    p = dash.painel_atividade(30)
    achatado = str(p)
    for proibido in ("duracao", "tempo_sessao", "minutos_no_portal", "tempo_de_uso"):
        assert proibido not in achatado


def test_painel_sobrevive_a_falha(banco: _Fake) -> None:
    banco.quebrado["user_activity"] = True
    assert "erro" in dash.painel_atividade(30)


def test_periodo_sem_registro_nao_vira_zero_uso(banco: _Fake) -> None:
    """
    Ausência de registro é diferente de ausência de uso: a instrumentação
    começou em 15/08, e antes disso não há histórico. O painel devolve a
    contagem separada para a tela poder dizer isso.
    """
    p = dash.painel_atividade(30)
    assert p["ativos_no_periodo"] == 0
    assert p["logins_registrados"] == 0
