"""Expurgo do cofre: a chave sai quando deixa de fazer sentido guardá-la.

Até 16/08/2026 a custódia tinha só metade da proteção. Certificado vencido não
**entrava** no cofre (filtro da etapa 2b), mas nada **tirava** o que já estava
lá quando venceu — o acervo só crescia, e crescia em chave privada. Confirmado
contra produção: dois certificados vencidos em 15/08 seguiam guardados no dia
seguinte.

**Os dois gatilhos têm riscos opostos, e é isso que este arquivo guarda.**

*Vencido* é seguro: a data está na própria linha e não depende de mais nada
estar correto.

*Removido da pasta* é perigoso. Apagar por ausência no inventário significa que
uma varredura que falhe pela metade apaga chaves em massa — a mesma armadilha
de falha-aberta da etapa 2b, agora na direção destrutiva. Os testes da seção 3
são os que impedem isso, e são a razão de o arquivo existir.

Atenua o risco o cofre ser derivado: se o arquivo ainda existir na origem, a
varredura seguinte o traz de volta. Mas "dá para refazer" não é desculpa para
apagar por engano — o reenvio custa uma janela de indisponibilidade e 5 MB.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import pytest

import app.cert_installer as ci


AGORA = datetime.now(timezone.utc)


class _Resultado:
    def __init__(self, data: List[Dict[str, Any]]) -> None:
        self.data = data


class _Query:
    def __init__(self, linhas: List[Dict[str, Any]], banco: "_Fake", nome: str) -> None:
        self._l, self._b, self._n = linhas, banco, nome
        self._filtros: List[tuple] = []
        self._op = "select"
        self._payload: Any = None
        self._ordem: Optional[tuple] = None
        self._limite: Optional[int] = None

    def select(self, *_c: str) -> "_Query":
        return self

    def update(self, row: Dict[str, Any]) -> "_Query":
        self._op, self._payload = "update", row
        return self

    def delete(self) -> "_Query":
        self._op = "delete"
        return self

    def eq(self, c: str, v: Any) -> "_Query":
        self._filtros.append((c, v))
        return self

    def order(self, c: str, desc: bool = False) -> "_Query":
        self._ordem = (c, desc)
        return self

    def limit(self, n: int) -> "_Query":
        self._limite = n
        return self

    def _casa(self, r: Dict[str, Any]) -> bool:
        return all(r.get(c) == v for c, v in self._filtros)

    def execute(self) -> _Resultado:
        if self._b.quebrado.get(self._n):
            raise RuntimeError("banco fora do ar")
        if self._op == "update":
            tocados = []
            for r in self._l:
                if self._casa(r):
                    r.update(self._payload)
                    tocados.append(dict(r))
            return _Resultado(tocados)
        if self._op == "delete":
            fora = [r for r in self._l if self._casa(r)]
            self._l[:] = [r for r in self._l if not self._casa(r)]
            self._b.apagados.extend(fora)
            return _Resultado(fora)
        linhas = [dict(r) for r in self._l if self._casa(r)]
        if self._ordem:
            col, desc = self._ordem
            linhas.sort(key=lambda r: r.get(col) or "", reverse=desc)
        if self._limite is not None:
            linhas = linhas[: self._limite]
        return _Resultado(linhas)


class _Fake:
    def __init__(self, tabelas: Dict[str, List[Dict[str, Any]]]) -> None:
        self.tabelas = tabelas
        self.quebrado: Dict[str, bool] = {}
        self.apagados: List[Dict[str, Any]] = []

    def table(self, nome: str) -> _Query:
        return _Query(self.tabelas.setdefault(nome, []), self, nome)


MAQ = "ANALISESRV"
FP_OK = "a" * 64
FP_VENCIDO = "b" * 64
FP_SEM_DATA = "c" * 64
FP_SUMIU = "d" * 64


def _linha(fp: str, *, not_after: Optional[str] = "2027-01-01T00:00:00Z",
           ausente_desde: Optional[str] = None) -> dict:
    return {
        "id": f"id-{fp[:4]}", "fingerprint": fp, "machine_id": MAQ,
        "not_after": not_after, "ausente_desde": ausente_desde,
    }


def _snapshot(fps: List[str], horas_atras: float = 1.0) -> dict:
    return {
        "machine_id": MAQ,
        "scanned_at": (AGORA - timedelta(hours=horas_atras)).isoformat(),
        "items": [{"fingerprint_sha256": f} for f in fps],
    }


@pytest.fixture
def banco(monkeypatch: pytest.MonkeyPatch) -> _Fake:
    fake = _Fake({
        "cert_pfx_store": [
            _linha(FP_OK),
            _linha(FP_VENCIDO, not_after=(AGORA - timedelta(days=1)).isoformat()),
            _linha(FP_SEM_DATA, not_after=None),
            _linha(FP_SUMIU),
        ],
        # O inventário atual NÃO tem FP_SUMIU: é o caso "removido da pasta".
        "cert_snapshots": [
            _snapshot([FP_OK, FP_VENCIDO, FP_SEM_DATA], horas_atras=1),
            _snapshot([FP_OK, FP_VENCIDO, FP_SEM_DATA, FP_SUMIU], horas_atras=25),
        ],
    })
    monkeypatch.setattr(ci, "_supabase", lambda: fake)
    return fake


def _no_cofre(banco: _Fake) -> set:
    return {l["fingerprint"] for l in banco.tabelas["cert_pfx_store"]}


# ──────────────────────────────────────────────────────────────────────────
# 1. Vencido — o defeito confirmado em produção
# ──────────────────────────────────────────────────────────────────────────

def test_vencido_sai_do_cofre(banco: _Fake) -> None:
    """
    O caso real: dois certificados venceram em 15/08 e seguiam com a chave
    privada guardada no dia seguinte, porque nada os tirava.
    """
    r = ci.expurgar_cofre()
    assert r["vencidos_apagados"] == 1
    assert FP_VENCIDO not in _no_cofre(banco)


def test_valido_fica(banco: _Fake) -> None:
    ci.expurgar_cofre()
    assert FP_OK in _no_cofre(banco)


def test_sem_data_de_validade_nao_e_apagado(banco: _Fake) -> None:
    """
    Sem data não dá para afirmar que venceu. Guardar a mais é desperdício;
    apagar a mais é perda — e as duas não se equivalem.
    """
    ci.expurgar_cofre()
    assert FP_SEM_DATA in _no_cofre(banco)


# ──────────────────────────────────────────────────────────────────────────
# 2. Removido da pasta — carência antes de apagar
# ──────────────────────────────────────────────────────────────────────────

def test_ausente_e_marcado_e_nao_apagado_de_imediato(banco: _Fake) -> None:
    """
    Uma varredura ruim isolada não pode apagar nada. A primeira ausência só
    inicia o relógio.
    """
    r = ci.expurgar_cofre()
    assert FP_SUMIU in _no_cofre(banco), "não pode sair na primeira ausência"
    assert r["maquinas"][0]["marcados_ausentes"] == 1

    linha = next(l for l in banco.tabelas["cert_pfx_store"] if l["fingerprint"] == FP_SUMIU)
    assert linha["ausente_desde"]


def test_reaparecer_zera_o_relogio(banco: _Fake) -> None:
    """
    Sem isto, um certificado que sumisse por um dia e voltasse seria apagado
    depois — já presente na pasta, e sem ninguém entender por quê.
    """
    for l in banco.tabelas["cert_pfx_store"]:
        if l["fingerprint"] == FP_SUMIU:
            l["ausente_desde"] = (AGORA - timedelta(days=2)).isoformat()
    banco.tabelas["cert_snapshots"][0]["items"].append({"fingerprint_sha256": FP_SUMIU})

    r = ci.expurgar_cofre()
    assert r["maquinas"][0]["reapareceram"] == 1
    linha = next(l for l in banco.tabelas["cert_pfx_store"] if l["fingerprint"] == FP_SUMIU)
    assert linha["ausente_desde"] is None
    assert FP_SUMIU in _no_cofre(banco)


def test_ausente_alem_da_carencia_e_apagado(banco: _Fake) -> None:
    for l in banco.tabelas["cert_pfx_store"]:
        if l["fingerprint"] == FP_SUMIU:
            l["ausente_desde"] = (
                AGORA - timedelta(days=ci.CARENCIA_AUSENCIA_DIAS + 1)
            ).isoformat()

    r = ci.expurgar_cofre()
    assert r["maquinas"][0]["apagados_por_ausencia"] == 1
    assert FP_SUMIU not in _no_cofre(banco)


def test_ausente_dentro_da_carencia_sobrevive(banco: _Fake) -> None:
    for l in banco.tabelas["cert_pfx_store"]:
        if l["fingerprint"] == FP_SUMIU:
            l["ausente_desde"] = (AGORA - timedelta(hours=6)).isoformat()

    ci.expurgar_cofre()
    assert FP_SUMIU in _no_cofre(banco)


# ──────────────────────────────────────────────────────────────────────────
# 3. As guardas — a razão de o arquivo existir
#
# Cada uma impede um jeito diferente de apagar chave privada por engano.
# ──────────────────────────────────────────────────────────────────────────

def test_guarda_varredura_velha(banco: _Fake) -> None:
    """
    Agente parado tem inventário de outra era. Agir sobre ele apagaria tudo o
    que mudou desde então — e o agente parado é justamente o cenário em que
    ninguém está olhando.
    """
    # TODAS as varreduras precisam ser velhas: a mais recente é que decide, e
    # envelhecer só uma deixaria a outra assumir o posto.
    for i, s in enumerate(banco.tabelas["cert_snapshots"]):
        s["scanned_at"] = (
            AGORA - timedelta(hours=ci.MAX_HORAS_VARREDURA + 5 + i)
        ).isoformat()

    r = ci.expurgar_cofre()
    maq = r["maquinas"][0]
    assert maq["agiu"] is False
    assert "parado" in maq["motivo"]
    assert FP_SUMIU in _no_cofre(banco), "nada pode ser marcado nem apagado"


def test_guarda_inventario_vazio(banco: _Fake) -> None:
    """
    Uma pasta temporariamente inacessível reporta zero itens **sem erro
    nenhum**. Sem esta guarda, isso limparia o cofre inteiro numa varredura.
    """
    banco.tabelas["cert_snapshots"][0]["items"] = []

    r = ci.expurgar_cofre()
    maq = r["maquinas"][0]
    assert maq["agiu"] is False
    assert "vazio" in maq["motivo"]
    assert len(banco.tabelas["cert_pfx_store"]) >= 3


def test_guarda_queda_brusca(banco: _Fake) -> None:
    """
    Inventário que despenca entre duas varreduras seguidas é varredura
    suspeita, não acervo que encolheu. Um disco de rede meio montado produz
    exatamente isso.
    """
    banco.tabelas["cert_snapshots"][0]["items"] = [{"fingerprint_sha256": FP_OK}]

    r = ci.expurgar_cofre()
    maq = r["maquinas"][0]
    assert maq["agiu"] is False
    assert "suspeita" in maq["motivo"]
    assert FP_SEM_DATA in _no_cofre(banco), "os ausentes não podem ser marcados"


def test_expurgo_de_vencido_independe_das_guardas(banco: _Fake) -> None:
    """
    As guardas protegem a decisão por **ausência**, que depende do inventário
    estar íntegro. Validade não depende de nada disso — bloquear os dois juntos
    manteria chave morta guardada por causa de um agente parado.
    """
    banco.tabelas["cert_snapshots"][0]["items"] = []   # dispara a guarda 2

    r = ci.expurgar_cofre()
    assert r["vencidos_apagados"] == 1
    assert FP_VENCIDO not in _no_cofre(banco)
    assert r["maquinas"][0]["agiu"] is False


def test_sem_varredura_nenhuma_nao_apaga_por_ausencia(banco: _Fake) -> None:
    banco.tabelas["cert_snapshots"] = []
    r = ci.expurgar_cofre()
    assert r["maquinas"][0]["agiu"] is False
    assert FP_SUMIU in _no_cofre(banco)


# ──────────────────────────────────────────────────────────────────────────
# 4. Relatar o que fez E o que se recusou a fazer
# ──────────────────────────────────────────────────────────────────────────

def test_recusa_vem_com_motivo(banco: _Fake) -> None:
    """
    Um expurgo que se recusa a agir em silêncio é indistinguível de um expurgo
    quebrado — e é justamente nas varreduras suspeitas que ele não age.
    """
    banco.tabelas["cert_snapshots"][0]["items"] = []
    maq = ci.expurgar_cofre()["maquinas"][0]
    assert maq["motivo"], "recusar sem dizer por quê esconde o próprio expurgo"


def test_falha_de_banco_nao_levanta(banco: _Fake) -> None:
    """Roda pendurado no cron de alertas; levantar derrubaria o envio."""
    banco.quebrado["cert_pfx_store"] = True
    r = ci.expurgar_cofre()
    assert r["executado"] is False
    assert r["motivo"]


def test_sem_supabase_nao_apaga_nada(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ci, "_supabase", lambda: None)
    assert ci.expurgar_cofre()["executado"] is False
