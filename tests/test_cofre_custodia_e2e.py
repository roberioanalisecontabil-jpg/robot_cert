"""Custódia do cofre fim-a-fim, pelo contrato HTTP real.

Em 15/08/2026 o modelo inverteu: era opt-in (nada entrava sem autorização
explícita, e o resultado eram 33 de 560 guardados) e passou a ser opt-out (todo
certificado válido do inventário entra, menos os que o admin bloqueou).

**A inversão tem um perigo que o modelo anterior não tinha.** No opt-in, "não
consegui ler a lista" e "a lista está vazia" davam no mesmo resultado seguro:
não enviar nada. No opt-out são opostos — lista de bloqueios vazia significa
"mande tudo". Traduzir o código antigo literalmente transformaria falha fechada
em falha aberta, sem sintoma nenhum: tudo continuaria funcionando, e chaves
privadas demais subiriam. Os testes da seção 4 são os que guardam isso, e são a
razão de este arquivo existir.

O caminho e o formato da resposta que o agente consome **não mudaram**, e a
seção 1 fixa isso: o `.exe` instalado no ANALISESRV sempre perguntou "o que
posso mandar?" e agiu só sobre a resposta. Mudar o que entra na lista inverteu a
custódia sem recompilar nada — e um teste que deixe esse contrato escorregar
quebra produção sem quebrar a suíte.

O Supabase é substituído por um fake em memória que implementa só o subconjunto
de query builder usado por `cert_installer`. Não é mock de asserção — é um banco
de brinquedo, para o teste exercitar a lógica real de filtro em vez de verificar
que uma chamada aconteceu.
"""

import base64
from typing import Any, Dict, List, Optional
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app import auth
import app.cert_installer as ci


# ──────────────────────────────────────────────────────────────────────────
# Fake Supabase
# ──────────────────────────────────────────────────────────────────────────

class _Resultado:
    def __init__(self, data: List[Dict[str, Any]]) -> None:
        self.data = data


class _Query:
    """Query builder encadeável sobre uma lista de dicts."""

    def __init__(self, tabela: List[Dict[str, Any]], banco: "_FakeSupabase", nome: str) -> None:
        self._tabela = tabela
        self._banco = banco
        self._nome = nome
        self._filtros: List[tuple] = []
        self._operacao = "select"
        self._payload: Optional[Dict[str, Any]] = None
        self._on_conflict: Optional[str] = None
        self._ordem: Optional[tuple] = None
        self._limite: Optional[int] = None

    def select(self, *_cols: str) -> "_Query":
        self._operacao = "select"
        return self

    def upsert(self, row: Dict[str, Any], on_conflict: Optional[str] = None) -> "_Query":
        self._operacao = "upsert"
        self._payload = row
        self._on_conflict = on_conflict
        return self

    def delete(self) -> "_Query":
        self._operacao = "delete"
        return self

    def eq(self, coluna: str, valor: Any) -> "_Query":
        self._filtros.append((coluna, valor))
        return self

    def order(self, coluna: str, desc: bool = False) -> "_Query":
        self._ordem = (coluna, desc)
        return self

    def limit(self, n: int) -> "_Query":
        self._limite = n
        return self

    def _casa(self, row: Dict[str, Any]) -> bool:
        return all(row.get(c) == v for c, v in self._filtros)

    def execute(self) -> _Resultado:
        if self._banco.quebrado.get(self._nome):
            raise RuntimeError(f"banco fora do ar ao ler {self._nome}")

        if self._operacao == "select":
            linhas = [dict(r) for r in self._tabela if self._casa(r)]
            if self._ordem:
                coluna, desc = self._ordem
                linhas.sort(key=lambda r: r.get(coluna) or "", reverse=desc)
            if self._limite is not None:
                linhas = linhas[: self._limite]
            return _Resultado(linhas)

        if self._operacao == "upsert":
            assert self._payload is not None
            if self._on_conflict:
                # PostgREST aceita chave composta como "col_a,col_b". Comparar
                # uma coluna só faria o fake colidir onde o banco não colide,
                # escondendo justamente o comportamento sob teste.
                colunas = [c.strip() for c in self._on_conflict.split(",")]
                for i, r in enumerate(self._tabela):
                    if all(r.get(c) == self._payload.get(c) for c in colunas):
                        self._tabela[i] = dict(self._payload)
                        return _Resultado([dict(self._payload)])
            self._tabela.append(dict(self._payload))
            return _Resultado([dict(self._payload)])

        if self._operacao == "delete":
            removidos = [r for r in self._tabela if self._casa(r)]
            self._tabela[:] = [r for r in self._tabela if not self._casa(r)]
            return _Resultado(removidos)

        raise AssertionError(f"operacao nao suportada: {self._operacao}")


class _FakeSupabase:
    def __init__(self) -> None:
        self.tabelas: Dict[str, List[Dict[str, Any]]] = {}
        # Permite derrubar UMA tabela: é assim que se testa falha parcial, que
        # é o caso realista — o banco raramente cai inteiro.
        self.quebrado: Dict[str, bool] = {}

    def table(self, nome: str) -> _Query:
        self.tabelas.setdefault(nome, [])
        return _Query(self.tabelas[nome], self, nome)


FP = "a" * 64
FP_B = "b" * 64
FP_VENCIDO = "c" * 64
FP_ILEGIVEL = "d" * 64
MAQUINA_A = "PC-CONTABIL-01"
MAQUINA_B = "PC-FISCAL-02"


def _item(fp: str, status: str = "ok") -> dict:
    return {"fingerprint_sha256": fp, "status": status, "nome": "ACME LTDA"}


@pytest.fixture
def banco() -> _FakeSupabase:
    fake = _FakeSupabase()
    # Inventário: A tem um válido, um vencido e um ilegível. B tem o mesmo
    # certificado da A (é o caso comum num escritório contábil) e mais um.
    fake.tabelas["cert_snapshots"] = [
        {
            "machine_id": MAQUINA_A,
            "scanned_at": "2026-08-15T10:00:00Z",
            "items": [_item(FP), _item(FP_VENCIDO, "expirado"), _item(FP_ILEGIVEL, "erro")],
        },
        {
            "machine_id": MAQUINA_A,
            "scanned_at": "2026-08-14T10:00:00Z",   # varredura antiga, ignorada
            "items": [_item("e" * 64)],
        },
        {
            "machine_id": MAQUINA_B,
            "scanned_at": "2026-08-15T10:00:00Z",
            "items": [_item(FP), _item(FP_B)],
        },
    ]
    with patch.object(ci, "_supabase", lambda: fake):
        yield fake


def _headers_admin() -> dict:
    tok = auth.create_access_token({"sub": "admin@exemplo.com", "role": "admin"})
    return {"Authorization": f"Bearer {tok}"}


def _headers_agente() -> dict:
    tok = auth.create_access_token({"sub": "agente@exemplo.com", "role": "agent"})
    return {"Authorization": f"Bearer {tok}"}


def _lista(client: TestClient, maquina: str, headers=None) -> list:
    r = client.get(
        f"/api/cert-installer/vault-optin?machine_id={maquina}",
        headers=headers or _headers_agente(),
    )
    assert r.status_code == 200, r.text
    return r.json()["fingerprints"]


# ──────────────────────────────────────────────────────────────────────────
# 1. O contrato com o agente compilado
# ──────────────────────────────────────────────────────────────────────────

def test_resposta_mantem_caminho_e_formato_do_agente(
    client: TestClient, banco: _FakeSupabase
) -> None:
    """
    O `.exe` do ANALISESRV lê `fingerprints` de `/api/cert-installer/vault-optin`.

    Mudar caminho ou formato quebraria produção sem quebrar mais nada — o agente
    trata resposta inesperada como falha e simplesmente para de sincronizar, em
    silêncio. Foi por caber neste contrato que a inversão não exigiu recompilar.
    """
    r = client.get(
        f"/api/cert-installer/vault-optin?machine_id={MAQUINA_A}",
        headers=_headers_agente(),
    )
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert set(corpo) == {"fingerprints"}
    assert isinstance(corpo["fingerprints"], list)


def test_sem_machine_id_e_recusado(client: TestClient, banco: _FakeSupabase) -> None:
    """A custódia é por estação; lista global não responde pergunta nenhuma."""
    r = client.get("/api/cert-installer/vault-optin", headers=_headers_agente())
    assert r.status_code == 422, r.text


# ──────────────────────────────────────────────────────────────────────────
# 2. Opt-out: entra por padrão
# ──────────────────────────────────────────────────────────────────────────

def test_certificado_valido_entra_sem_ninguem_autorizar(
    client: TestClient, banco: _FakeSupabase
) -> None:
    """O ponto da inversão: sem nenhuma linha de autorização, o válido já entra."""
    assert banco.tabelas.get("cert_vault_bloqueio", []) == []
    assert FP in _lista(client, MAQUINA_A)


@pytest.mark.parametrize("fp,motivo", [
    (FP_VENCIDO, "vencido não instala"),
    (FP_ILEGIVEL, "o scanner não conseguiu ler"),
])
def test_o_que_nao_instala_nao_entra(
    client: TestClient, banco: _FakeSupabase, fp: str, motivo: str
) -> None:
    """
    "Tudo por padrão" é "todo certificado VÁLIDO e LEGÍVEL por padrão".

    Guardar a chave privada de um certificado que não instala é passivo puro:
    aumenta o raio de um vazamento sem entregar nada em troca.
    """
    assert fp not in _lista(client, MAQUINA_A), motivo


def test_so_a_varredura_mais_recente_conta(client: TestClient, banco: _FakeSupabase) -> None:
    """Certificado que sumiu da máquina não pode continuar autorizado."""
    assert "e" * 64 not in _lista(client, MAQUINA_A)


def test_maquina_sem_varredura_nao_autoriza_nada(
    client: TestClient, banco: _FakeSupabase
) -> None:
    """
    Máquina desconhecida devolve lista vazia — e isso NÃO é erro.

    É o resultado conservador correto: não há inventário, logo não há nada a
    autorizar. Um agente que se declare de uma estação inexistente não ganha
    permissão por omissão.
    """
    assert _lista(client, "MAQUINA-QUE-NAO-EXISTE") == []


# ──────────────────────────────────────────────────────────────────────────
# 3. Bloqueio — a exceção, por estação
# ──────────────────────────────────────────────────────────────────────────

def test_bloqueado_sai_da_lista(client: TestClient, banco: _FakeSupabase) -> None:
    r = client.delete(
        f"/api/cert-installer/vault-optin/{FP}?machine_id={MAQUINA_A}",
        headers=_headers_admin(),
    )
    assert r.status_code == 200, r.text
    assert FP not in _lista(client, MAQUINA_A)


def test_bloquear_registra_o_bloqueio_e_nao_so_apaga_o_material(
    client: TestClient, banco: _FakeSupabase
) -> None:
    """
    Sem a linha de bloqueio, o botão desfaz a si mesmo.

    Sob opt-in bastava apagar a autorização: sem ela o agente não reenviava. Sob
    opt-out o certificado continua no inventário — apagar só o PFX faria ele
    voltar a ser autorizado no ciclo seguinte e subir de novo em até 24h. O
    admin veria o certificado sumir e reaparecer sozinho, sem erro nenhum.
    """
    banco.tabelas.setdefault("cert_pfx_store", []).append(
        {"fingerprint": FP, "machine_id": MAQUINA_A, "encrypted_pfx": "material"}
    )

    client.delete(
        f"/api/cert-installer/vault-optin/{FP}?machine_id={MAQUINA_A}",
        headers=_headers_admin(),
    )

    bloqueios = banco.tabelas["cert_vault_bloqueio"]
    assert len(bloqueios) == 1, "o bloqueio precisa persistir, senão o agente reenvia"
    assert bloqueios[0]["fingerprint"] == FP
    assert bloqueios[0]["machine_id"] == MAQUINA_A
    assert bloqueios[0]["bloqueado_por"] == "admin@exemplo.com", "a trilha diz quem tirou"
    assert banco.tabelas["cert_pfx_store"] == [], "a chave privada tem de sair junto"


def test_bloquear_numa_maquina_nao_alcanca_a_outra(
    client: TestClient, banco: _FakeSupabase
) -> None:
    """O mesmo certificado em duas estações: bloquear em A não toca em B."""
    client.delete(
        f"/api/cert-installer/vault-optin/{FP}?machine_id={MAQUINA_A}",
        headers=_headers_admin(),
    )
    assert FP not in _lista(client, MAQUINA_A)
    assert FP in _lista(client, MAQUINA_B), "o bloqueio vazou para a outra estação"


def test_bloquear_sem_machine_id_e_recusado(client: TestClient, banco: _FakeSupabase) -> None:
    r = client.delete(
        f"/api/cert-installer/vault-optin/{FP}", headers=_headers_admin()
    )
    assert r.status_code == 422, r.text
    assert not banco.tabelas.get("cert_vault_bloqueio")


def test_reativar_devolve_a_custodia(client: TestClient, banco: _FakeSupabase) -> None:
    client.delete(
        f"/api/cert-installer/vault-optin/{FP}?machine_id={MAQUINA_A}",
        headers=_headers_admin(),
    )
    assert FP not in _lista(client, MAQUINA_A)

    r = client.post(
        "/api/cert-installer/vault-optin",
        json={"fingerprint": FP, "machine_id": MAQUINA_A},
        headers=_headers_admin(),
    )
    assert r.status_code == 200, r.text
    assert FP in _lista(client, MAQUINA_A), "reativar tem de devolver à lista"


def test_usuario_comum_nao_bloqueia_nem_reativa(
    client: TestClient, banco: _FakeSupabase
) -> None:
    """Decidir o que guarda chave privada no servidor é ação de admin."""
    tok = auth.create_access_token({"sub": "user@exemplo.com", "role": "user"})
    h = {"Authorization": f"Bearer {tok}"}

    r = client.post(
        "/api/cert-installer/vault-optin",
        json={"fingerprint": FP, "machine_id": MAQUINA_A},
        headers=h,
    )
    assert r.status_code == 403

    r = client.delete(
        f"/api/cert-installer/vault-optin/{FP}?machine_id={MAQUINA_A}", headers=h
    )
    assert r.status_code == 403


# ──────────────────────────────────────────────────────────────────────────
# 4. Falha FECHADA — o que a inversão põe em risco
#
# Estes são os testes que justificam o arquivo. No opt-in, erro e lista vazia
# levavam ao mesmo lugar seguro. No opt-out são opostos, e o modo de falha é
# invisível: nada quebra, só sobem chaves privadas a mais.
# ──────────────────────────────────────────────────────────────────────────

def test_falha_ao_ler_bloqueios_nao_libera_tudo(
    client: TestClient, banco: _FakeSupabase
) -> None:
    """
    Consulta de bloqueios fora do ar → 503, **nunca** a lista completa.

    Devolver o inventário inteiro aqui seria dizer "nada está bloqueado" quando
    a verdade é "não sei". O agente trata não-200 como "não enviar nada".
    """
    banco.quebrado["cert_vault_bloqueio"] = True

    r = client.get(
        f"/api/cert-installer/vault-optin?machine_id={MAQUINA_A}",
        headers=_headers_agente(),
    )
    assert r.status_code == 503, r.text
    assert FP not in r.text, "a lista não pode vazar numa resposta de erro"


def test_falha_ao_ler_inventario_nao_libera_tudo(
    client: TestClient, banco: _FakeSupabase
) -> None:
    banco.quebrado["cert_snapshots"] = True

    r = client.get(
        f"/api/cert-installer/vault-optin?machine_id={MAQUINA_A}",
        headers=_headers_agente(),
    )
    assert r.status_code == 503, r.text


def test_upload_recusa_quando_nao_da_para_saber_a_custodia(
    client: TestClient, banco: _FakeSupabase
) -> None:
    """
    A barreira do upload falha fechada pelo mesmo motivo.

    É o ponto mais fácil de errar da inversão: quem escrevesse
    `bloqueados = ler() or set()` aqui teria uma barreira que **aceita tudo**
    exatamente quando o banco está instável, e nada no comportamento diria isso.
    """
    banco.quebrado["cert_vault_bloqueio"] = True

    with patch.object(ci, "upsert_pfx", lambda **kw: "id-fake") as gravou:
        r = client.post(
            "/api/cert-installer/upload-pfx",
            json={"fingerprint": FP, "pfx_b64": "AAAA", "machine_id": MAQUINA_A},
            headers=_headers_agente(),
        )

    assert r.status_code == 503, r.text
    assert banco.tabelas.get("cert_pfx_store", []) == []


def test_conta_ativa_da_custodia_nao_e_silenciosa() -> None:
    """
    `listar_bloqueios` **levanta**; não devolve vazio.

    Devolver `set()` num `except` é o caminho de menor resistência, e sob
    opt-out ele significa "libera tudo". A exceção existe para que quem chamar
    seja obrigado a decidir.
    """
    class _Quebrado:
        def table(self, _n):
            raise RuntimeError("banco fora do ar")

    with patch.object(ci, "_supabase", lambda: _Quebrado()):
        with pytest.raises(ci.CustodiaIndisponivel):
            ci.listar_bloqueios(MAQUINA_A)
        with pytest.raises(ci.CustodiaIndisponivel):
            ci.fingerprints_do_inventario(MAQUINA_A)


# ──────────────────────────────────────────────────────────────────────────
# 5. Barreira de servidor no upload
# ──────────────────────────────────────────────────────────────────────────

def test_upload_barra_certificado_bloqueado(client: TestClient, banco: _FakeSupabase) -> None:
    """
    A barreira existe para o agente desatualizado ou adulterado.

    O agente bem-comportado nunca tentaria — só envia o que a lista dele
    devolveu. Mas um que se declare de outra estação, ou que use uma lista
    velha, esbarra aqui.
    """
    client.delete(
        f"/api/cert-installer/vault-optin/{FP}?machine_id={MAQUINA_A}",
        headers=_headers_admin(),
    )

    with patch.object(ci, "upsert_pfx", lambda **kw: "id-fake"):
        r = client.post(
            "/api/cert-installer/upload-pfx",
            json={"fingerprint": FP, "pfx_b64": "AAAA", "machine_id": MAQUINA_A},
            headers=_headers_agente(),
        )
    assert r.status_code == 403, r.text


def test_upload_barra_fingerprint_fora_do_inventario(
    client: TestClient, banco: _FakeSupabase
) -> None:
    """Certificado que a máquina nunca reportou não pode ser gravado por ela."""
    with patch.object(ci, "upsert_pfx", lambda **kw: "id-fake"):
        r = client.post(
            "/api/cert-installer/upload-pfx",
            json={"fingerprint": "f" * 64, "pfx_b64": "AAAA", "machine_id": MAQUINA_A},
            headers=_headers_agente(),
        )
    assert r.status_code == 403, r.text


def test_upload_barra_vencido(client: TestClient, banco: _FakeSupabase) -> None:
    with patch.object(ci, "upsert_pfx", lambda **kw: "id-fake"):
        r = client.post(
            "/api/cert-installer/upload-pfx",
            json={"fingerprint": FP_VENCIDO, "pfx_b64": "AAAA", "machine_id": MAQUINA_A},
            headers=_headers_agente(),
        )
    assert r.status_code == 403, r.text


def test_upload_aceita_o_caminho_legitimo(client: TestClient, banco: _FakeSupabase) -> None:
    """Contraprova: o endurecimento não pode barrar o que deve passar."""
    with patch.object(ci, "upsert_pfx", lambda **kw: "id-fake"):
        r = client.post(
            "/api/cert-installer/upload-pfx",
            json={"fingerprint": FP, "pfx_b64": "AAAA", "machine_id": MAQUINA_A},
            headers=_headers_agente(),
        )
    assert r.status_code == 200, r.text


def test_upload_do_mesmo_fingerprint_por_duas_maquinas_gera_duas_linhas(
    client: TestClient, banco: _FakeSupabase
) -> None:
    """
    Cada estação guarda a SUA cópia — a chave composta de 15/08.

    O `upsert` roda de verdade aqui (sem patch em `upsert_pfx`) porque o que se
    testa é o `on_conflict`: com uma coluna só, o segundo upload sobrescreveria
    o material do primeiro.
    """
    for maquina in (MAQUINA_A, MAQUINA_B):
        r = client.post(
            "/api/cert-installer/upload-pfx",
            json={
                "fingerprint": FP,
                "pfx_b64": base64.b64encode(f"pfx-de-{maquina}".encode()).decode(),
                "machine_id": maquina,
            },
            headers=_headers_agente(),
        )
        assert r.status_code == 200, r.text

    cofre = banco.tabelas["cert_pfx_store"]
    assert len(cofre) == 2, "o segundo upload sobrescreveu o primeiro"
    assert sorted(l["machine_id"] for l in cofre) == sorted([MAQUINA_A, MAQUINA_B])
    assert len({l["encrypted_pfx"] for l in cofre}) == 2
