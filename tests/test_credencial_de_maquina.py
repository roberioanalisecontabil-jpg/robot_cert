"""
Credencial de MÁQUINA: o agente do ANALISESRV deixa a X-API-Key (Frente 1, item 8).

Substitui `test_identidade_dormente.py`, apagado como ele próprio mandava: a
troca que ele vigiava — `_headers()` deixar a chave compartilhada — foi feita,
e pela credencial certa (a de MÁQUINA, não a da pessoa).

O que está preso aqui, nas duas pontas:

  * a emissão é uma só por máquina, e linha revogada NÃO reabre sozinha —
    senão revogar não revogaria nada para quem tem a X-API-Key
  * o segredo emitido autentica no mesmo header de sempre; o legado continua
    aceito e AVISA no log (é o sinal de quando pode morrer)
  * o 401 de credencial leva o marcador `X-Credencial-Invalida`; problema de
    implantação (sem banco/tabela) NÃO leva — o agente não pode descartar um
    segredo válido por causa de uma migration
  * no agente, o cofre é ProgramData + DPAPI de escopo máquina + ACL, o
    descarte só acontece para o segredo que o portal de fato recusou, e o
    provisionamento só é pedido depois do ensaio de gravação
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any, Dict

import pytest
from fastapi.testclient import TestClient

from app import auth, machine_credentials
from agent import identidade, identidade_maquina
from tests.test_dispositivos_do_agente import _Fake

MAQUINA = "analisesrv"
RAIZ = Path(__file__).resolve().parents[1]

ADMIN = "admin@x.com"
SENHA = "senha-boa-123"


@pytest.fixture
def banco(monkeypatch: pytest.MonkeyPatch) -> _Fake:
    fake = _Fake({
        "users": [
            {"id": "u-adm", "email": ADMIN, "full_name": "Admin", "role": "admin",
             "ativo": True, "deve_trocar_senha": False,
             "password_hash": auth.get_password_hash(SENHA)},
        ],
        machine_credentials.TABELA: [],
        "user_activity": [],
    })
    monkeypatch.setattr("app.settings_state._supabase", lambda: fake)
    return fake


def _provisionar(client: TestClient, chave: str, maquina: str = MAQUINA):
    return client.post(
        "/api/agent/maquinas/provisionar",
        json={"machine_id": maquina, "versao": "1.2.0"},
        headers={"X-API-Key": chave},
    )


def _cabecalho_admin(client: TestClient) -> Dict[str, str]:
    r = client.post("/api/login", json={"email": ADMIN, "password": SENHA})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


# ──────────────────────────────────────────────────────────────────────────
# 1. Emissão: uma vez, e revogação não reabre
# ──────────────────────────────────────────────────────────────────────────


def test_provisiona_uma_vez_e_so_uma(client_com_chave: TestClient, api_key: str,
                                     banco: _Fake) -> None:
    r = _provisionar(client_com_chave, api_key)
    assert r.status_code == 200, r.text
    assert len(r.json()["segredo"]) >= 40

    # Segunda emissão para o mesmo machine_id: recusada. O primeiro chamador
    # levou o único texto claro; reabrir aqui seria um balcão de credenciais.
    assert _provisionar(client_com_chave, api_key).status_code == 409


def test_linha_revogada_bloqueia_emissao_nova(client_com_chave: TestClient,
                                              api_key: str, banco: _Fake) -> None:
    _provisionar(client_com_chave, api_key)
    assert machine_credentials.revogar(MAQUINA) is True
    # Quem tem a X-API-Key não consegue "des-revogar" provisionando de novo.
    assert _provisionar(client_com_chave, api_key).status_code == 409


def test_identidade_anonima_nao_provisiona(client: TestClient, banco: _Fake) -> None:
    """Sem API_KEY configurada, `require_auth` devolve a identidade anônima —
    que não pode criar segredo durável a partir de credencial nenhuma."""
    r = client.post("/api/agent/maquinas/provisionar", json={"machine_id": MAQUINA})
    assert r.status_code == 403


# ──────────────────────────────────────────────────────────────────────────
# 2. O segredo emitido autentica; o legado continua e avisa
# ──────────────────────────────────────────────────────────────────────────


def test_o_segredo_emitido_autentica_no_header_de_sempre(
    client_com_chave: TestClient, api_key: str, banco: _Fake
) -> None:
    segredo = _provisionar(client_com_chave, api_key).json()["segredo"]

    # A mesma rota, agora com a credencial própria: passa da autenticação
    # (senão seria 401) e morre no 409 de "já provisionada" — a prova de que o
    # portal reconheceu a máquina sem a chave compartilhada.
    r = _provisionar(client_com_chave, segredo)
    assert r.status_code == 409

    # E o contato carimbou visto_em — é o que responde "migrou?" na tela.
    linha = banco.tabelas[machine_credentials.TABELA][0]
    assert linha["visto_em"] is not None


def test_a_chave_compartilhada_continua_e_avisa(
    client_com_chave: TestClient, api_key: str, banco: _Fake,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """O WARNING é o instrumento da transição: quando ele sumir do log, a
    X-API-Key pode ser desligada. Mesmo padrão do INVENT."""
    with caplog.at_level("WARNING"):
        r = _provisionar(client_com_chave, api_key)
    assert r.status_code == 200
    assert any("compartilhada" in m for m in caplog.messages)


# ──────────────────────────────────────────────────────────────────────────
# 3. O marcador de credencial inválida — e quando ele NÃO pode sair
# ──────────────────────────────────────────────────────────────────────────


def test_segredo_revogado_leva_o_marcador(
    client_com_chave: TestClient, api_key: str, banco: _Fake
) -> None:
    segredo = _provisionar(client_com_chave, api_key).json()["segredo"]
    machine_credentials.revogar(MAQUINA)

    r = _provisionar(client_com_chave, segredo)
    assert r.status_code == 401
    assert r.headers.get(machine_credentials.CABECALHO_CREDENCIAL_INVALIDA) == "1"


def test_sem_banco_o_401_nao_leva_o_marcador(client_com_chave: TestClient) -> None:
    """Migration/banco ausente é problema de implantação, não da credencial.
    Com o marcador, o agente descartaria um segredo perfeitamente válido."""
    r = _provisionar(client_com_chave, "um-segredo-qualquer-que-nao-e-a-chave")
    # Sem `banco`, o conftest zera o Supabase: machine_credentials.SemBanco.
    assert r.status_code in (401, 503)
    assert machine_credentials.CABECALHO_CREDENCIAL_INVALIDA not in r.headers


def test_os_dois_lados_falam_o_mesmo_cabecalho() -> None:
    """Agente e portal só se entendem pelo literal; divergir quebra em
    silêncio — a estação voltaria a emudecer como o INVENT em 24/08/2026."""
    assert (
        identidade_maquina.CABECALHO_CREDENCIAL_INVALIDA
        == machine_credentials.CABECALHO_CREDENCIAL_INVALIDA
    )


# ──────────────────────────────────────────────────────────────────────────
# 4. Rotas de admin: mapa da migração, revogar, reemitir
# ──────────────────────────────────────────────────────────────────────────


def test_listar_e_de_admin_e_nao_vaza_o_hash(
    client_com_chave: TestClient, api_key: str, banco: _Fake
) -> None:
    _provisionar(client_com_chave, api_key)

    # O agente (papel 'agent') não lista credenciais.
    r = client_com_chave.get("/api/agent/maquinas", headers={"X-API-Key": api_key})
    assert r.status_code == 403

    r = client_com_chave.get("/api/agent/maquinas", headers=_cabecalho_admin(client_com_chave))
    assert r.status_code == 200
    maquinas = r.json()["maquinas"]
    assert len(maquinas) == 1
    assert "segredo_hash" not in maquinas[0]
    assert "vivo" in maquinas[0]


def test_reemitir_e_o_unico_caminho_de_volta(
    client_com_chave: TestClient, api_key: str, banco: _Fake
) -> None:
    segredo = _provisionar(client_com_chave, api_key).json()["segredo"]
    adm = _cabecalho_admin(client_com_chave)

    r = client_com_chave.delete(f"/api/agent/maquinas/{MAQUINA}", headers=adm)
    assert r.status_code == 200 and r.json()["status"] == "revogado"

    # Revogada: nem o segredo antigo autentica, nem a emissão reabre sozinha.
    assert _provisionar(client_com_chave, segredo).status_code == 401
    assert _provisionar(client_com_chave, api_key).status_code == 409

    r = client_com_chave.post(f"/api/agent/maquinas/{MAQUINA}/reemitir", headers=adm)
    assert r.status_code == 200 and r.json()["status"] == "descartada"

    # Agora sim: a próxima subida do serviço emite uma credencial NOVA.
    r = _provisionar(client_com_chave, api_key)
    assert r.status_code == 200
    assert r.json()["segredo"] != segredo


def test_revogar_sem_linha_e_404(client_com_chave: TestClient, banco: _Fake) -> None:
    adm = _cabecalho_admin(client_com_chave)
    assert client_com_chave.delete("/api/agent/maquinas/fantasma", headers=adm).status_code == 404
    assert (
        client_com_chave.post("/api/agent/maquinas/fantasma/reemitir", headers=adm).status_code
        == 404
    )


# ──────────────────────────────────────────────────────────────────────────
# 5. O agente: _headers prefere a máquina, com a X-API-Key de rede de segurança
# ──────────────────────────────────────────────────────────────────────────


def test_headers_prefere_a_credencial_de_maquina() -> None:
    """
    O inverso do sentinela apagado: `_headers()` agora LÊ a credencial de
    máquina — e tem de continuar caindo na X-API-Key quando ela não existe,
    senão uma estação sem credencial fica muda.

    Estático porque `_headers` é fechamento dentro de `run_agent_application`,
    e subir o agente inteiro exigiria bandeja e portal. Mesma técnica dos
    testes de ordem de inicialização deste repositório.
    """
    fonte = (RAIZ / "agent" / "run_agent.py").read_text(encoding="utf-8")
    inicio = fonte.index("def _headers()")
    corpo = fonte[inicio: fonte.index("\n    _start_tray()", inicio)]

    assert "identidade_maquina" in corpo, (
        "_headers() deixou de ler a credencial de máquina; o serviço voltaria "
        "à chave compartilhada sem ninguém decidir isso"
    )
    assert "api_key" in corpo, (
        "_headers() perdeu a queda para a X-API-Key; uma estação sem "
        "credencial (ou com o cofre ilegível) ficaria muda"
    )
    # A credencial da PESSOA continua fora daqui — o serviço não a decifra.
    assert "from agent import identidade\n" not in corpo


def test_o_provisionamento_ensaia_antes_de_pedir() -> None:
    """`pode_guardar` ANTES de `provisionar`, no fluxo real: pedir sem
    conseguir gravar queima a emissão única e prende a estação na X-API-Key
    até um admin reemitir."""
    fonte = (RAIZ / "agent" / "run_agent.py").read_text(encoding="utf-8")
    arvore = ast.parse(fonte)
    fn = next(
        no for no in ast.walk(arvore)
        if isinstance(no, ast.FunctionDef) and no.name == "run_agent_application"
    )
    corpo = ast.unparse(fn)
    assert "pode_guardar()" in corpo
    assert corpo.index("pode_guardar()") < corpo.index("identidade_maquina.provisionar(")


# ──────────────────────────────────────────────────────────────────────────
# 6. O agente: descarte só do segredo que o portal de fato recusou
# ──────────────────────────────────────────────────────────────────────────


class _Resp:
    def __init__(self, headers: Dict[str, str], enviado: Dict[str, str]) -> None:
        self.headers = headers

        class _Req:
            pass

        self.request = _Req()
        self.request.headers = enviado


def _com_cofre(monkeypatch: pytest.MonkeyPatch, segredo: str | None) -> list:
    apagados: list = []
    monkeypatch.setattr(
        identidade_maquina, "ler",
        lambda: {"segredo": segredo} if segredo else None,
    )
    monkeypatch.setattr(
        identidade_maquina, "apagar", lambda: apagados.append(True) or True
    )
    return apagados


def test_descarta_o_segredo_marcado(monkeypatch: pytest.MonkeyPatch) -> None:
    apagados = _com_cofre(monkeypatch, "segredo-vivo")
    r = _Resp(
        {identidade_maquina.CABECALHO_CREDENCIAL_INVALIDA: "1"},
        {"X-API-Key": "segredo-vivo"},
    )
    assert identidade_maquina.descartar_se_recusada(r) is True
    assert apagados == [True]


@pytest.mark.parametrize(
    "cabecalhos, enviado, guardado",
    [
        # Sem o marcador: 401 comum (portal em deploy, chave errada) não apaga.
        ({}, {"X-API-Key": "segredo-vivo"}, "segredo-vivo"),
        # Marcado, mas o que foi era a X-API-Key legada — nada a descartar.
        ({identidade_maquina.CABECALHO_CREDENCIAL_INVALIDA: "1"},
         {"X-API-Key": "chave-da-frota"}, "segredo-vivo"),
        # Marcado, mas não há cofre nesta estação.
        ({identidade_maquina.CABECALHO_CREDENCIAL_INVALIDA: "1"},
         {"X-API-Key": "qualquer"}, None),
        # Marcado, mas a requisição nem levava X-API-Key (ex.: JWT do navegador).
        ({identidade_maquina.CABECALHO_CREDENCIAL_INVALIDA: "1"}, {}, "segredo-vivo"),
    ],
)
def test_o_que_nao_pode_ser_descartado(
    monkeypatch: pytest.MonkeyPatch, cabecalhos: dict, enviado: dict, guardado: str | None
) -> None:
    apagados = _com_cofre(monkeypatch, guardado)
    assert identidade_maquina.descartar_se_recusada(_Resp(cabecalhos, enviado)) is False
    assert apagados == []


# ──────────────────────────────────────────────────────────────────────────
# 7. O agente: provisionar guarda, e só quando o portal emitiu
# ──────────────────────────────────────────────────────────────────────────


class _ClienteFalso:
    def __init__(self, status: int, corpo: dict | None = None) -> None:
        self._status = status
        self._corpo = corpo or {}
        self.enviados: list = []

    def post(self, url: str, json: dict | None = None, headers: dict | None = None):
        self.enviados.append({"url": url, "json": json, "headers": headers or {}})

        class _R:
            status_code = self._status

            @staticmethod
            def json() -> dict:
                return dict(self._corpo)

        return _R()


def test_provisionar_guarda_o_que_o_portal_emitiu(monkeypatch: pytest.MonkeyPatch) -> None:
    guardados: list = []
    monkeypatch.setattr(
        identidade_maquina, "guardar",
        lambda segredo, base, mid: guardados.append((segredo, base, mid)),
    )
    cliente = _ClienteFalso(200, {"machine_id": MAQUINA, "segredo": "s3gr3d0-novo"})

    ok = identidade_maquina.provisionar(
        cliente, "https://portal.teste/", MAQUINA,
        versao="1.2.0", cabecalhos={"X-API-Key": "chave-legada"},
    )
    assert ok is True
    assert guardados == [("s3gr3d0-novo", "https://portal.teste", MAQUINA)]
    # A posse é provada pela X-API-Key que já autentica o agente.
    assert cliente.enviados[0]["headers"]["X-API-Key"] == "chave-legada"
    assert cliente.enviados[0]["url"].endswith("/api/agent/maquinas/provisionar")


@pytest.mark.parametrize("status", [409, 401, 500, 503])
def test_provisionar_recusado_nao_guarda_nada(
    monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    guardados: list = []
    monkeypatch.setattr(
        identidade_maquina, "guardar",
        lambda *a, **k: guardados.append(a),
    )
    ok = identidade_maquina.provisionar(_ClienteFalso(status), "https://p", MAQUINA)
    assert ok is False
    assert guardados == []


# ──────────────────────────────────────────────────────────────────────────
# 8. O cofre da máquina: ProgramData, DPAPI de escopo máquina, ACL
# ──────────────────────────────────────────────────────────────────────────


def test_o_cofre_fica_na_pasta_do_servico(monkeypatch: pytest.MonkeyPatch) -> None:
    """O inverso da credencial da pessoa: ESTE arquivo tem de estar onde o
    LocalSystem alcança — na mesma pasta de agent_status.json."""
    monkeypatch.setenv("PROGRAMDATA", r"C:\ProgramData")
    destino = identidade_maquina.caminho()
    assert destino.parent.name == "Analise CertiDigital Agent"
    assert "ProgramData" in str(destino)
    # E a da pessoa continua fora de lá.
    assert "ProgramData" not in str(identidade.caminho())


_dpapi = pytest.mark.skipif(
    not identidade.dpapi_disponivel(),
    reason="O cofre da máquina usa DPAPI; só existe no Windows.",
)


@pytest.fixture
def cofre(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """
    Cofre isolado em tmp, para não tocar no ProgramData do desenvolvedor.

    A ACL vira no-op AQUI de propósito: ela restringe o arquivo a SYSTEM e
    Administradores, e o pytest roda como usuário comum — o próprio teste
    perderia o direito de ler o que acabou de gravar. O comportamento da ACL
    tem testes próprios, que capturam a chamada em vez de sofrer o efeito.
    """
    destino = tmp_path / "maquina.dat"
    monkeypatch.setattr(identidade_maquina, "caminho", lambda: destino)
    monkeypatch.setattr(identidade_maquina, "_aplicar_acl", lambda arquivo: None)
    return destino


@_dpapi
def test_o_arquivo_gravado_nao_contem_o_segredo(cofre: Path) -> None:
    identidade_maquina.guardar("segredo-em-claro-nunca", "https://p", MAQUINA)
    cru = cofre.read_bytes()
    assert b"segredo-em-claro-nunca" not in cru
    assert b"machine_id" not in cru


@_dpapi
def test_o_que_foi_guardado_volta_inteiro(cofre: Path) -> None:
    identidade_maquina.guardar("um-segredo", "https://portal.teste/", MAQUINA.upper())
    lido = identidade_maquina.ler()
    assert lido is not None
    assert lido["segredo"] == "um-segredo"
    assert lido["base_url"] == "https://portal.teste"
    assert lido["machine_id"] == MAQUINA


@_dpapi
def test_blob_corrompido_cai_na_chave_em_vez_de_estourar(cofre: Path) -> None:
    identidade_maquina.guardar("um-segredo", "https://p", MAQUINA)
    cofre.write_bytes(b"isto nao e um blob dpapi valido")
    assert identidade_maquina.ler() is None


@_dpapi
def test_guardar_aplica_a_acl(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A ACL é parte da cifra: DPAPI de escopo máquina decifra para qualquer
    processo local, então quem impede uma conta comum de ler é a ACL."""
    destino = tmp_path / "maquina.dat"
    monkeypatch.setattr(identidade_maquina, "caminho", lambda: destino)
    restritos: list = []
    monkeypatch.setattr(identidade_maquina, "_aplicar_acl", restritos.append)

    identidade_maquina.guardar("um-segredo", "https://p", MAQUINA)
    assert restritos == [destino]


@_dpapi
def test_acl_que_falha_apaga_o_arquivo_e_levanta(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Arquivo legível por qualquer conta local é pior que arquivo nenhum —
    mesma recusa em degradar de `identidade.SemCofreLocal`."""
    destino = tmp_path / "maquina.dat"
    monkeypatch.setattr(identidade_maquina, "caminho", lambda: destino)

    def _falha(arquivo: Path) -> None:
        raise identidade.SemCofreLocal("icacls falhou")

    monkeypatch.setattr(identidade_maquina, "_aplicar_acl", _falha)

    with pytest.raises(identidade.SemCofreLocal):
        identidade_maquina.guardar("um-segredo", "https://p", MAQUINA)
    assert not destino.exists()


@_dpapi
def test_pode_guardar_ensaia_de_verdade(cofre: Path) -> None:
    assert identidade_maquina.pode_guardar() is True
    assert not cofre.with_name("maquina.probe").exists(), "o ensaio se limpa"
