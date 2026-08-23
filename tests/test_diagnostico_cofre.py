"""Diagnóstico do cofre e das chaves de cifragem.

Escrito depois do incidente de 15/08/2026: a `CERT_ENCRYPTION_KEY` foi trocada
no painel da Vercel sem passar pela rotação, e **todo o conteúdo do cofre virou
lixo cifrado**. Nada na interface disse isso. Descobriu-se por um `InvalidTag`
no meio de outra investigação, e o caminho documentado para consertar
(`CERT_ENCRYPTION_KEY_V<n>`) estava ele próprio quebrado.

Dois testes daqui merecem destaque:

- `test_versao_sem_chave_configurada_e_o_alarme` reproduz exatamente aquele
  estado. É o número que teria transformado uma investigação de horas num
  vermelho na tela.
- `test_revalidar_detecta_chave_trocada` guarda a diferença entre contar e
  provar. Em 15/08 o cofre tinha uma linha íntegra, com todos os campos
  preenchidos, e completamente indecifrável — nenhuma contagem acusaria isso.
"""

from typing import Any, Dict, List, Optional
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app import auth, config
import app.cert_installer as ci


class _Resultado:
    def __init__(self, data: List[Dict[str, Any]]) -> None:
        self.data = data


class _Query:
    def __init__(self, tabela: List[Dict[str, Any]], banco: "_Fake", nome: str) -> None:
        self._t, self._b, self._n = tabela, banco, nome
        self._filtros: List[tuple] = []
        self._limite: Optional[int] = None

    def select(self, *_c: str) -> "_Query":
        return self

    def eq(self, c: str, v: Any) -> "_Query":
        self._filtros.append((c, v))
        return self

    def limit(self, n: int) -> "_Query":
        self._limite = n
        return self

    def execute(self) -> _Resultado:
        if self._b.quebrado.get(self._n):
            raise RuntimeError("banco fora do ar")
        linhas = [dict(r) for r in self._t if all(r.get(c) == v for c, v in self._filtros)]
        if self._limite is not None:
            linhas = linhas[: self._limite]
        return _Resultado(linhas)


class _Fake:
    def __init__(self) -> None:
        self.tabelas: Dict[str, List[Dict[str, Any]]] = {}
        self.quebrado: Dict[str, bool] = {}

    def table(self, nome: str) -> _Query:
        self.tabelas.setdefault(nome, [])
        return _Query(self.tabelas[nome], self, nome)


def _linha(fp: str, versao: int = 1, *, senha=True, claro=False, maquina="ANALISESRV") -> dict:
    """
    Linha do cofre com PFX cifrado **de verdade**, sob a chave em vigor.

    `encrypt_pfx_at_rest` só cifra com a chave corrente — não há como gravar sob
    uma versão antiga, e nem faria sentido: versões antigas existem porque foram
    correntes um dia. Por isso `versao` aqui é só o rótulo gravado na coluna, e
    os testes que exercitam a decifragem usam a versão 1.
    """
    ct, iv, tag = ci.encrypt_pfx_at_rest(b"conteudo-do-pfx")
    return {
        "id": "id-" + fp[:4],
        "fingerprint": fp,
        "machine_id": maquina,
        "key_version": versao,
        "updated_at": "2026-08-15T19:19:49Z",
        "encrypted_pfx": ct,
        "pfx_iv": iv,
        "pfx_auth_tag": tag,
        "pfx_password_enc": "cifrada" if senha else None,
        "pfx_password": "EM CLARO" if claro else None,
    }


@pytest.fixture
def banco(monkeypatch: pytest.MonkeyPatch) -> _Fake:
    fake = _Fake()
    fake.tabelas["cert_pfx_store"] = [_linha("a" * 64), _linha("b" * 64)]
    fake.tabelas["cert_vault_bloqueio"] = []
    monkeypatch.setattr(ci, "_supabase", lambda: fake)
    return fake


def _admin() -> dict:
    return {"Authorization": f"Bearer {auth.create_access_token({'sub': 'admin@x.com', 'role': 'admin'})}"}


# ──────────────────────────────────────────────────────────────────────────
# Contagens que apontam para trabalho
# ──────────────────────────────────────────────────────────────────────────

def test_agrupa_por_maquina_e_versao(banco: _Fake) -> None:
    d = ci.diagnostico_do_cofre()
    assert d["total"] == 2
    assert d["por_maquina"] == {"ANALISESRV": 2}
    assert d["por_key_version"] == {"1": 2}


def test_sem_senha_cifrada_e_contado(banco: _Fake) -> None:
    """
    Foi a causa ÚNICA das seis falhas de instalação registradas em produção
    ("Senha ausente no cofre"). Descobrir isso exigiu ler o `agent.log` de uma
    máquina remota; aqui é um número na tela.
    """
    banco.tabelas["cert_pfx_store"].append(_linha("c" * 64, senha=False))
    assert ci.diagnostico_do_cofre()["sem_senha_cifrada"] == 1


def test_senha_em_claro_e_contada(banco: _Fake) -> None:
    """
    Deve ser sempre zero. A coluna antiga guardava a senha sob a MESMA chave do
    PFX — um vazamento entregava os dois juntos, e foi por isso que ela saiu do
    banco em 03/08.
    """
    assert ci.diagnostico_do_cofre()["senha_em_claro"] == 0
    banco.tabelas["cert_pfx_store"].append(_linha("d" * 64, claro=True))
    assert ci.diagnostico_do_cofre()["senha_em_claro"] == 1


def test_bloqueios_entram_no_diagnostico(banco: _Fake) -> None:
    banco.tabelas["cert_vault_bloqueio"] = [{"fingerprint": "x" * 64}]
    assert ci.diagnostico_do_cofre()["bloqueios"] == 1


# ──────────────────────────────────────────────────────────────────────────
# Chaves — o alarme que faltou em 15/08
# ──────────────────────────────────────────────────────────────────────────

def test_estado_saudavel_nao_acusa_nada(banco: _Fake) -> None:
    k = ci.diagnostico_das_chaves()
    assert k["versoes_no_cofre"] == [1]
    assert k["versoes_sem_chave"] == []


def test_versao_sem_chave_configurada_e_o_alarme(
    banco: _Fake, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Linhas cifradas sob uma versão que não existe no ambiente = material
    **indecifrável agora**.

    É exatamente o estado em que o cofre ficou em 15/08, e nenhuma tela dizia.
    Reproduzido aqui: uma linha em v2, e nenhuma CERT_ENCRYPTION_KEY_V2.
    """
    banco.tabelas["cert_pfx_store"].append(_linha("e" * 64, versao=2))
    monkeypatch.delattr(config, "CERT_ENCRYPTION_KEY_V2", raising=False)

    k = ci.diagnostico_das_chaves()
    assert 2 in k["versoes_no_cofre"]
    assert k["versoes_sem_chave"] == [2], "a versão órfã tem de aparecer"


def test_versao_antiga_com_chave_configurada_nao_alarma(
    banco: _Fake, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Rotação bem feita não pode gerar alarme — senão o alarme vira ruído."""
    banco.tabelas["cert_pfx_store"].append(_linha("f" * 64, versao=2))
    monkeypatch.setattr(config, "CERT_ENCRYPTION_KEY_V2", "22" * 32, raising=False)

    assert ci.diagnostico_das_chaves()["versoes_sem_chave"] == []


# ──────────────────────────────────────────────────────────────────────────
# Revalidar — a diferença entre contar e provar
# ──────────────────────────────────────────────────────────────────────────

def test_revalidar_decifra_amostra(banco: _Fake) -> None:
    res = ci.revalidar_cofre()
    assert len(res) == 1
    assert res[0]["key_version"] == 1
    assert res[0]["ok"] is True


def test_revalidar_detecta_chave_trocada(banco: _Fake, monkeypatch: pytest.MonkeyPatch) -> None:
    """
    O teste que reproduz o incidente.

    As linhas continuam íntegras — todos os campos preenchidos, contagem certa,
    `key_version` coerente. Só a chave do ambiente mudou. Nenhuma contagem
    acusaria; só tentar decifrar acusa.
    """
    monkeypatch.setattr(config, "CERT_ENCRYPTION_KEY", "ff" * 32)

    res = ci.revalidar_cofre()
    assert res and res[0]["ok"] is False
    assert ci.diagnostico_do_cofre()["total"] == 2, "as contagens seguem 'saudáveis'"


def test_revalidar_cofre_vazio_nao_quebra(banco: _Fake) -> None:
    banco.tabelas["cert_pfx_store"] = []
    assert ci.revalidar_cofre() == []


# ──────────────────────────────────────────────────────────────────────────
# Rotas
# ──────────────────────────────────────────────────────────────────────────

def test_rota_de_diagnostico_reune_tudo(client: TestClient, banco: _Fake) -> None:
    r = client.get("/api/cert-installer/diagnostico", headers=_admin())
    assert r.status_code == 200, r.text
    d = r.json()
    # `binario` e `icone` sairam em 23/08/2026 com o instalador avulso:
    # diagnosticavam um .exe que o portal nao serve mais.
    assert set(d) >= {"cofre", "chaves"}
    assert "binario" not in d, "o diagnostico voltou a falar de um .exe que nao existe"
    assert d["cofre"]["total"] == 2


def test_diagnostico_sobrevive_a_falha_do_cofre(client: TestClient, banco: _Fake) -> None:
    """
    Banco fora do ar nao pode derrubar a tela: ela tem de dizer O QUE falhou.

    Antes o argumento era "o estado do binario continua legivel e e metade do
    diagnostico". Sem o binario, a metade que resta e o motivo — e um 500 aqui
    esconderia justamente a informacao que a pessoa veio buscar.
    """
    banco.quebrado["cert_pfx_store"] = True
    r = client.get("/api/cert-installer/diagnostico", headers=_admin())
    assert r.status_code == 200, r.text
    assert "erro" in r.json()["cofre"]
    assert "erro" in r.json()["chaves"]


def test_diagnostico_e_revalidar_sao_de_admin(client: TestClient, banco: _Fake) -> None:
    """Expõe caminho de arquivo, hash e a saúde das chaves de cifragem."""
    for papel in ("user", "gestor"):
        h = {"Authorization": f"Bearer {auth.create_access_token({'sub': 'x@x.com', 'role': papel})}"}
        assert client.get("/api/cert-installer/diagnostico", headers=h).status_code == 403
        assert client.post("/api/cert-installer/revalidar-cofre", headers=h).status_code == 403


def test_rota_de_revalidar(client: TestClient, banco: _Fake) -> None:
    r = client.post("/api/cert-installer/revalidar-cofre", headers=_admin())
    assert r.status_code == 200, r.text
    assert r.json()["resultados"][0]["ok"] is True
