"""
Dispositivos do agente — a identidade deixa de ser uma chave compartilhada.

Cada teste aqui guarda uma propriedade que, se cair, **não dá sintoma**: o
agente continua instalando, o portal continua respondendo, e só a garantia
desaparece. É a mesma classe de risco de `test_recuperacao_de_senha.py`.

O que está guardado:

  * a senha do portal nunca vira credencial durável no agente (o segredo é
    outro valor, e ele é revogável)
  * revogar realmente corta — inclusive contra o próprio segredo que já
    funcionava
  * desativar a conta corta, mesmo com o dispositivo registrado antes
  * senha provisória não produz dispositivo
  * ninguém revoga a máquina de outra pessoa, e o 404 não conta que ela existe
  * o hash em repouso não sai pela API
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import pytest
from fastapi.testclient import TestClient

from app import agent_devices, auth

EMAIL = "ana@x.com"
SENHA = "senha-boa-123"
MAQUINA = "ESTACAO-ANA"


# ──────────────────────────────────────────────────────────────────────────
# Banco falso — mesmo formato do usado em test_recuperacao_de_senha.py
# ──────────────────────────────────────────────────────────────────────────

class _Res:
    def __init__(self, data: List[Dict[str, Any]]) -> None:
        self.data = data


class _Query:
    def __init__(self, linhas: List[Dict[str, Any]]) -> None:
        self._l = linhas
        self._f: List = []
        self._op, self._p = "select", None

    def select(self, *_c: str) -> "_Query":
        return self

    def insert(self, p: Dict[str, Any]) -> "_Query":
        self._op, self._p = "insert", p
        return self

    def update(self, p: Dict[str, Any]) -> "_Query":
        self._op, self._p = "update", p
        return self

    def delete(self) -> "_Query":
        self._op = "delete"
        return self

    def eq(self, c: str, v: Any) -> "_Query":
        self._f.append((c, v))
        return self

    def limit(self, _n: int) -> "_Query":
        return self

    def order(self, *_a: Any, **_k: Any) -> "_Query":
        return self

    def _casa(self, r: Dict[str, Any]) -> bool:
        return all(r.get(c) == v for c, v in self._f)

    def execute(self) -> _Res:
        if self._op == "insert":
            linha = dict(self._p)
            linha.setdefault("id", f"dev-{len(self._l) + 1}")
            linha.setdefault("visto_em", None)
            linha.setdefault("revogado_em", None)
            self._l.append(linha)
            return _Res([dict(linha)])
        if self._op == "update":
            alt = []
            for r in self._l:
                if self._casa(r):
                    r.update(self._p)
                    alt.append(dict(r))
            return _Res(alt)
        if self._op == "delete":
            fora = [r for r in self._l if self._casa(r)]
            self._l[:] = [r for r in self._l if not self._casa(r)]
            return _Res(fora)
        return _Res([dict(r) for r in self._l if self._casa(r)])


class _Fake:
    def __init__(self, tabelas: Dict[str, List[Dict[str, Any]]]) -> None:
        self.tabelas = tabelas

    def table(self, nome: str) -> _Query:
        return _Query(self.tabelas.setdefault(nome, []))


@pytest.fixture
def banco(monkeypatch: pytest.MonkeyPatch) -> _Fake:
    fake = _Fake({
        "users": [
            {"id": "u-ana", "email": EMAIL, "full_name": "Ana", "role": "user",
             "ativo": True, "deve_trocar_senha": False,
             "password_hash": auth.get_password_hash(SENHA)},
            {"id": "u-bruno", "email": "bruno@x.com", "full_name": "Bruno",
             "role": "user", "ativo": True, "deve_trocar_senha": False,
             "password_hash": auth.get_password_hash(SENHA)},
            {"id": "u-prov", "email": "prov@x.com", "full_name": "Provisoria",
             "role": "user", "ativo": True, "deve_trocar_senha": True,
             "password_hash": auth.get_password_hash(SENHA)},
        ],
        agent_devices.TABELA: [],
        "user_activity": [],
    })
    monkeypatch.setattr("app.settings_state._supabase", lambda: fake)
    return fake


def _registrar(client: TestClient, email: str = EMAIL, senha: str = SENHA,
               maquina: str = MAQUINA):
    return client.post(
        "/api/agent/dispositivos/registrar",
        json={"email": email, "password": senha, "machine_id": maquina},
    )


def _token(client: TestClient, segredo: str):
    return client.post("/api/agent/dispositivos/token", json={"segredo": segredo})


def _cabecalho(client: TestClient, email: str = EMAIL) -> Dict[str, str]:
    r = client.post("/api/login", json={"email": email, "password": SENHA})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


# ──────────────────────────────────────────────────────────────────────────
# 1. O caminho feliz
# ──────────────────────────────────────────────────────────────────────────

def test_registra_e_troca_o_segredo_por_token(client: TestClient, banco: _Fake) -> None:
    r = _registrar(client)
    assert r.status_code == 200, r.text
    segredo = r.json()["segredo"]
    assert len(segredo) >= 40

    t = _token(client, segredo)
    assert t.status_code == 200, t.text
    corpo = t.json()
    assert corpo["machine_id"] == MAQUINA
    # O papel REAL da pessoa, não `agent`: é o que permite às rotas perguntarem
    # "este certificado é seu" em vez de "que papel você tem".
    assert corpo["role"] == "user"

    dados = auth.decode_access_token(corpo["access_token"])
    assert dados is not None and dados.email == EMAIL


def test_o_token_do_agente_abre_as_rotas_do_portal(client: TestClient, banco: _Fake) -> None:
    """O JWT do dispositivo é um JWT normal — `require_auth` não o distingue."""
    segredo = _registrar(client).json()["segredo"]
    jwt = _token(client, segredo).json()["access_token"]

    r = client.get(
        "/api/agent/dispositivos", headers={"Authorization": f"Bearer {jwt}"}
    )
    assert r.status_code == 200
    assert r.json()["alcance"] == "proprios"


def test_a_senha_do_portal_nao_vira_o_segredo(client: TestClient, banco: _Fake) -> None:
    """
    O ponto da fase. Se um dia alguém "simplificar" guardando a senha no
    agente, isto morre — e nada mais dá sinal.
    """
    segredo = _registrar(client).json()["segredo"]
    assert segredo != SENHA
    assert SENHA not in segredo
    # E a senha não serve como segredo de dispositivo.
    assert _token(client, SENHA).status_code == 401


def test_o_hash_nunca_sai_pela_api(client: TestClient, banco: _Fake) -> None:
    _registrar(client)
    r = client.get("/api/agent/dispositivos", headers=_cabecalho(client))
    assert r.status_code == 200
    for d in r.json()["dispositivos"]:
        assert "segredo_hash" not in d


# ──────────────────────────────────────────────────────────────────────────
# 2. Revogação — o que a chave compartilhada nunca permitiu
# ──────────────────────────────────────────────────────────────────────────

def test_revogar_corta_o_segredo_que_funcionava(client: TestClient, banco: _Fake) -> None:
    segredo = _registrar(client).json()["segredo"]
    assert _token(client, segredo).status_code == 200

    dev = client.get("/api/agent/dispositivos", headers=_cabecalho(client)).json()
    device_id = dev["dispositivos"][0]["id"]

    r = client.delete(f"/api/agent/dispositivos/{device_id}", headers=_cabecalho(client))
    assert r.status_code == 200

    assert _token(client, segredo).status_code == 401


def test_revogado_some_da_lista_de_vivos(banco: _Fake) -> None:
    segredo = agent_devices.registrar("u-ana", MAQUINA, "Estação")
    assert agent_devices.autenticar(segredo) is not None
    assert len(agent_devices.vivos_do_usuario("u-ana")) == 1

    device_id = agent_devices.listar("u-ana")[0]["id"]
    assert agent_devices.revogar(device_id) is True
    assert agent_devices.vivos_do_usuario("u-ana") == []


def test_ninguem_revoga_a_maquina_de_outro(client: TestClient, banco: _Fake) -> None:
    segredo = _registrar(client).json()["segredo"]
    device_id = client.get(
        "/api/agent/dispositivos", headers=_cabecalho(client)
    ).json()["dispositivos"][0]["id"]

    r = client.delete(
        f"/api/agent/dispositivos/{device_id}", headers=_cabecalho(client, "bruno@x.com")
    )
    # 404 e não 403: um 403 confirmaria a existência daquele id para quem não
    # devia saber que ele existe.
    assert r.status_code == 404

    # E o segredo do dono continua de pé — a tentativa não tocou nele.
    assert _token(client, segredo).status_code == 200


# ──────────────────────────────────────────────────────────────────────────
# 3. A conta manda no dispositivo
# ──────────────────────────────────────────────────────────────────────────

def test_conta_desativada_depois_do_registro_para_de_emitir(
    client: TestClient, banco: _Fake
) -> None:
    """
    O dispositivo foi registrado enquanto a conta valia. Sem esta conferência
    ele continuaria emitindo token para quem já perdeu o portal — e a pessoa
    desligada seguiria instalando certificado pelo agente.
    """
    segredo = _registrar(client).json()["segredo"]
    assert _token(client, segredo).status_code == 200

    for u in banco.tabelas["users"]:
        if u["email"] == EMAIL:
            u["ativo"] = False

    assert _token(client, segredo).status_code == 403


def test_senha_provisoria_nao_produz_dispositivo(client: TestClient, banco: _Fake) -> None:
    """
    Quem entrou com senha definida por outra pessoa ainda não provou ser quem
    diz. Deixar passar daria ao portador da senha provisória uma credencial
    durável, que sobreviveria à troca.
    """
    r = _registrar(client, email="prov@x.com")
    assert r.status_code == 403
    assert r.headers.get("X-Senha-Provisoria") == "1"
    assert banco.tabelas[agent_devices.TABELA] == []


def test_senha_errada_nao_registra(client: TestClient, banco: _Fake) -> None:
    assert _registrar(client, senha="outra-coisa").status_code == 401
    assert banco.tabelas[agent_devices.TABELA] == []


# ──────────────────────────────────────────────────────────────────────────
# 4. Substituição e alcance
# ──────────────────────────────────────────────────────────────────────────

def test_registrar_de_novo_substitui_e_invalida_o_anterior(
    client: TestClient, banco: _Fake
) -> None:
    """
    Reinstalar o Windows não pode deixar a pessoa sem saída — mas o segredo
    velho tem de morrer, senão uma linha órfã continua valendo.
    """
    velho = _registrar(client).json()["segredo"]
    novo = _registrar(client).json()["segredo"]

    assert novo != velho
    assert len(banco.tabelas[agent_devices.TABELA]) == 1
    assert _token(client, velho).status_code == 401
    assert _token(client, novo).status_code == 200


def test_registrar_de_novo_limpa_a_revogacao(client: TestClient, banco: _Fake) -> None:
    _registrar(client)
    device_id = agent_devices.listar("u-ana")[0]["id"]
    agent_devices.revogar(device_id)

    novo = _registrar(client).json()["segredo"]
    assert _token(client, novo).status_code == 200


def test_admin_ve_a_frota_e_o_operador_so_a_dele(client: TestClient, banco: _Fake) -> None:
    _registrar(client)
    _registrar(client, email="bruno@x.com", maquina="ESTACAO-BRUNO")

    for u in banco.tabelas["users"]:
        if u["email"] == "bruno@x.com":
            u["role"] = "admin"

    r_admin = client.get("/api/agent/dispositivos", headers=_cabecalho(client, "bruno@x.com"))
    assert r_admin.json()["alcance"] == "todos"
    assert len(r_admin.json()["dispositivos"]) == 2

    r_ana = client.get("/api/agent/dispositivos", headers=_cabecalho(client))
    assert r_ana.json()["alcance"] == "proprios"
    assert len(r_ana.json()["dispositivos"]) == 1


# ──────────────────────────────────────────────────────────────────────────
# 5. Vivo é quem apareceu agora
# ──────────────────────────────────────────────────────────────────────────

def test_maquina_calada_nao_conta_como_viva(banco: _Fake) -> None:
    """
    O laço do agente roda a cada 10 s. Enfileirar comando para quem não
    aparece há três minutos produziria um pedido pendurado sem consumidor.
    """
    segredo = agent_devices.registrar("u-ana", MAQUINA)
    agent_devices.autenticar(segredo)
    assert len(agent_devices.vivos_do_usuario("u-ana")) == 1

    velho = datetime.now(timezone.utc) - timedelta(
        seconds=agent_devices.JANELA_VIVO_SEG + 60
    )
    banco.tabelas[agent_devices.TABELA][0]["visto_em"] = velho.isoformat()

    assert agent_devices.vivos_do_usuario("u-ana") == []
    # Mas o segredo continua VÁLIDO: estar calado não é estar revogado.
    assert agent_devices.autenticar(segredo) is not None


def test_autenticar_carimba_visto_em(banco: _Fake) -> None:
    segredo = agent_devices.registrar("u-ana", MAQUINA)
    assert banco.tabelas[agent_devices.TABELA][0]["visto_em"] is None
    agent_devices.autenticar(segredo)
    assert banco.tabelas[agent_devices.TABELA][0]["visto_em"] is not None


def test_segredo_inexistente_e_revogado_respondem_igual(
    client: TestClient, banco: _Fake
) -> None:
    """Distinguir diria a quem tenta se aquele valor já existiu."""
    segredo = _registrar(client).json()["segredo"]
    agent_devices.revogar(agent_devices.listar("u-ana")[0]["id"])

    revogado = _token(client, segredo)
    inventado = _token(client, "nunca-existiu-este-segredo-aqui-00000000")

    assert revogado.status_code == inventado.status_code == 401
    assert revogado.json()["detail"] == inventado.json()["detail"]


# ──────────────────────────────────────────────────────────────────────────
# 6. Sem banco, a rota diz o motivo em vez de estourar
# ──────────────────────────────────────────────────────────────────────────

def test_sem_supabase_responde_503(client: TestClient) -> None:
    """
    Sem o fixture `banco` não há Supabase (o conftest zera as credenciais).
    Dispositivos não têm fallback em arquivo de propósito: uma fila local de
    credenciais sobreviveria à revogação feita no portal.
    """
    r = _token(client, "qualquer-coisa")
    assert r.status_code == 503


# ──────────────────────────────────────────────────────────────────────────
# 7. Versão reportada, e a ordem de implantação
# ──────────────────────────────────────────────────────────────────────────

def test_a_versao_reportada_fica_guardada(banco: _Fake) -> None:
    segredo = agent_devices.registrar("u-ana", MAQUINA)
    agent_devices.autenticar(segredo, versao="1.1.0")
    assert banco.tabelas[agent_devices.TABELA][0]["versao"] == "1.1.0"


def test_contato_mudo_nao_apaga_a_versao_anterior(banco: _Fake) -> None:
    """
    A pergunta num diagnóstico é "o que tem naquela máquina", e ela não some
    porque um contato veio sem o número.
    """
    segredo = agent_devices.registrar("u-ana", MAQUINA)
    agent_devices.autenticar(segredo, versao="1.1.0")
    agent_devices.autenticar(segredo)
    assert banco.tabelas[agent_devices.TABELA][0]["versao"] == "1.1.0"


def test_sem_a_coluna_o_carimbo_de_vida_sobrevive(
    banco: _Fake, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    O risco de ordem. Se o agente novo reportar `versao` antes de a coluna
    existir, o PostgREST recusa o UPDATE INTEIRO (PGRST204) e o `visto_em`
    deixa de ser gravado — toda a frota apareceria "Parada", e a fase 4 não
    enfileiraria comando para máquina nenhuma. O sintoma não apontaria para a
    migration em lugar nenhum.
    """
    segredo = agent_devices.registrar("u-ana", MAQUINA)

    original = _Query.update

    def _recusa_versao(self, p):
        if "versao" in p:
            raise RuntimeError(
                "{'message': \"Could not find the 'versao' column\", 'code': 'PGRST204'}"
            )
        return original(self, p)

    monkeypatch.setattr(_Query, "update", _recusa_versao)

    d = agent_devices.autenticar(segredo, versao="1.1.0")

    assert d is not None, "o segredo continua válido; a coluna é informativa"
    assert d.get("visto_em"), "o carimbo de vida tem de sobreviver à coluna ausente"
    assert agent_devices.esta_vivo(d) is True


def test_versao_desconhecida_nao_e_desatualizada(
    banco: _Fake, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Estação que nunca reportou é DESCONHECIDA. Marcá-la de atrasada mandaria
    alguém atualizar o que talvez já esteja em dia.
    """
    monkeypatch.setattr("app.config.VERSAO_AGENTE_ESPERADA", "9.9.9", raising=False)
    segredo = agent_devices.registrar("u-ana", MAQUINA)
    agent_devices.autenticar(segredo)

    d = agent_devices.listar("u-ana")[0]
    assert d["desatualizado"] is False

    agent_devices.autenticar(segredo, versao="1.1.0")
    assert agent_devices.listar("u-ana")[0]["desatualizado"] is True
