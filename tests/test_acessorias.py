"""Carteira sincronizada pelo Acessórias (ADR 0005).

Duas partes:

1. **Regras** (sem banco): leitura da API com paginação e erros, matriz,
   cálculo do que entra e sai, trava e intervalo da busca.
2. **Integração** (com banco): só roda com `TEST_DATABASE_URL_ESQUEMA`
   apontando para um banco DESCARTÁVEL com o esquema inteiro aplicado
   (`python db/aplicar_schema.py <dsn>`). O teste apaga carteira, usuários
   e buscas desse banco.
"""
from __future__ import annotations

import os
from datetime import datetime

import httpx
import pytest

from app import acessorias
from app.acessorias import Estado, calcular_plano, cnpj_matriz, motivo_para_confirmar

FILIAL = "34045475000297"
MATRIZ = cnpj_matriz(FILIAL)
OUTRA = "11222333000181"


# ──────────────────────────────────────────────────────────────────────────
# Leitura
# ──────────────────────────────────────────────────────────────────────────

def _empresa_api(cnpj: str, status: str = "Ativa", deps=()):
    return {
        "Identificador": cnpj, "Razao": f"Empresa {cnpj}", "Status": status,
        "Departamentos": [{"ID": str(i), "Nome": n, "RespNome": "X", "RespEmail": e} for i, n, e in deps],
    }


def _api_falsa(paginas: dict, falhar_em: str = ""):
    """paginas: caminho -> lista de páginas (cada uma, lista de itens)."""
    def responder(req: httpx.Request) -> httpx.Response:
        caminho = req.url.path
        if caminho == falhar_em:
            return httpx.Response(500)
        n = int(req.url.params.get("Pagina", "1"))
        lotes = paginas.get(caminho, [])
        if n > len(lotes):
            return httpx.Response(204)
        return httpx.Response(200, json=lotes[n - 1])

    http = httpx.Client(transport=httpx.MockTransport(responder))
    return acessorias.Api("tok", url="https://falso", http=http, dormir=lambda s: None)


PAGINAS = {
    "/companies/ListAll": [
        [_empresa_api("34.045.475/0002-97", deps=[(1, "Contábil", "Ana@Escritorio.com"), (8, "TI", "ti@e.com")]),
         _empresa_api("111.222.333-44")],  # CPF: fora
        [_empresa_api(OUTRA, status="Inativa", deps=[(2, "Fiscal", "bia@escritorio.com")])],
    ],
    "/users/ListAll": [[{"id": "10", "nome": "Ana", "email": "ANA@escritorio.com", "status": "Ativo"},
                        {"id": "11", "nome": "Bia", "email": "bia@escritorio.com", "status": "Inativo"}]],
    "/departments/ListAll": [[{"ID": "1", "Nome": "Contábil"}, {"ID": "17", "Nome": "Controladoria"}]],
}


def test_le_todas_as_paginas_e_normaliza():
    dados = acessorias.ler_acessorias(_api_falsa(PAGINAS))
    cnpjs = {e["cnpj"]: e for e in dados["empresas"]}
    assert set(cnpjs) == {FILIAL, OUTRA}
    assert cnpjs[FILIAL]["departamentos"][0]["resp_email"] == "ana@escritorio.com"
    assert cnpjs[OUTRA]["ativa"] is False
    assert {u["email"]: u["ativo"] for u in dados["usuarios"]} == {"ana@escritorio.com": True, "bia@escritorio.com": False}
    assert {d["id"] for d in dados["departamentos"]} == {1, 2, 8, 17}


def test_pagina_com_erro_derruba_a_busca_inteira():
    with pytest.raises(acessorias.ErroAcessorias):
        acessorias.ler_acessorias(_api_falsa(PAGINAS, falhar_em="/users/ListAll"))


def test_busca_sem_empresas_e_erro():
    with pytest.raises(acessorias.ErroAcessorias):
        acessorias.ler_acessorias(_api_falsa({}))


def test_token_recusado():
    api = acessorias.Api("tok", url="https://falso", dormir=lambda s: None,
                         http=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(401))))
    with pytest.raises(acessorias.ErroAcessorias, match="401"):
        api.listar("/users/ListAll")


# ──────────────────────────────────────────────────────────────────────────
# Cálculo
# ──────────────────────────────────────────────────────────────────────────

def test_cnpj_matriz():
    assert cnpj_matriz("33000167000101") == "33000167000101"  # já é matriz
    assert cnpj_matriz("33000167100102")[:12] == "330001670001"
    assert cnpj_matriz("33000167100102") == "33000167000101"


def test_documento_cai_na_matriz_so_sem_certificado_da_filial():
    assert acessorias.documento_da_empresa(FILIAL, {FILIAL, MATRIZ}) == FILIAL
    assert acessorias.documento_da_empresa(FILIAL, {MATRIZ}) == MATRIZ
    assert acessorias.documento_da_empresa(FILIAL, set()) == FILIAL


def _dados(*empresas):
    return {"empresas": list(empresas), "usuarios": [], "departamentos": []}


def _emp(cnpj, *deps, ativa=True):
    return {"cnpj": cnpj, "razao": "", "ativa": ativa,
            "departamentos": [{"id": i, "nome": "", "resp_nome": "", "resp_email": e} for i, e in deps]}


def _estado(carteira=None, **kw):
    contas = {
        "ana@e.com": {"id": "u-ana", "email": "ana@e.com", "role": "user", "ativo": True},
        "gil@e.com": {"id": "u-gil", "email": "gil@e.com", "role": "gestor", "ativo": True},
        "adm@e.com": {"id": "u-adm", "email": "adm@e.com", "role": "admin", "ativo": True},
        "ex@e.com": {"id": "u-ex", "email": "ex@e.com", "role": "user", "ativo": False},
    }
    base = dict(contas=contas, carteira=carteira or {}, trazer={1, 2}, ja_aplicou=True)
    base.update(kw)
    return Estado(**base)


def test_entrada_para_operador_e_gestor_nunca_admin_nem_desativado():
    dados = _dados(_emp(OUTRA, (1, "ana@e.com"), (2, "gil@e.com")),
                   _emp(FILIAL, (1, "adm@e.com"), (2, "ex@e.com")))
    p = calcular_plano(dados, _estado())
    assert p["entradas"] == [("u-ana", OUTRA), ("u-gil", OUTRA)]


def test_departamento_sem_trazer_empresa_inativa_e_email_desconhecido_nao_dao_nada():
    dados = _dados(_emp(OUTRA, (8, "ana@e.com")), _emp(FILIAL, (1, "ana@e.com"), ativa=False),
                   _emp(MATRIZ, (1, "ninguem@e.com")))
    assert calcular_plano(dados, _estado())["entradas"] == []


def test_saida_so_do_que_veio_do_acessorias_depois_da_virada():
    carteira = {("u-ana", OUTRA): "acessorias", ("u-ana", FILIAL): "manual", ("u-ana", "12345678901"): "manual"}
    p = calcular_plano(_dados(), _estado(carteira))
    assert p["saidas"] == [("u-ana", OUTRA)]


def test_virada_tira_manual_de_cnpj_mas_nao_e_cpf():
    carteira = {("u-ana", OUTRA): "manual", ("u-ana", "12345678901"): "manual"}
    p = calcular_plano(_dados(), _estado(carteira, ja_aplicou=False))
    assert p["saidas"] == [("u-ana", OUTRA)]


def test_manual_confirmado_pelo_acessorias_vira_acessorias():
    carteira = {("u-ana", OUTRA): "manual"}
    p = calcular_plano(_dados(_emp(OUTRA, (1, "ana@e.com"))), _estado(carteira))
    assert p["conversoes"] == [("u-ana", OUTRA)] and not p["entradas"] and not p["saidas"]


def test_bloqueio_impede_a_entrada():
    p = calcular_plano(_dados(_emp(OUTRA, (1, "ana@e.com"))), _estado(bloqueios={("u-ana", OUTRA)}))
    assert p["entradas"] == []


def test_trava():
    carteira = {("u-ana", str(10**13 + i)): "acessorias" for i in range(20)}
    est = _estado(carteira)
    # tirar 2 de 20 = 10%: passa; 3 = 15%: espera
    dados2 = _dados(*[_emp(str(10**13 + i), (1, "ana@e.com")) for i in range(18)])
    assert motivo_para_confirmar(calcular_plano(dados2, est), est) == ""
    dados3 = _dados(*[_emp(str(10**13 + i), (1, "ana@e.com")) for i in range(17)])
    assert "mais de 10%" in motivo_para_confirmar(calcular_plano(dados3, est), est)
    assert motivo_para_confirmar(calcular_plano(dados2, est), _estado(carteira, ja_aplicou=False)) == "primeira aplicação"
    queda = _estado(carteira, empresas_ultima_aplicada=30)
    assert "empresas" in motivo_para_confirmar(calcular_plano(dados2, queda), queda)


def test_intervalo_da_busca():
    assert acessorias.proxima_espera(datetime(2026, 10, 20, 7, 0)) == 300
    assert acessorias.proxima_espera(datetime(2026, 10, 20, 19, 59)) == 300
    assert acessorias.proxima_espera(datetime(2026, 10, 20, 20, 0)) == 3600
    assert acessorias.proxima_espera(datetime(2026, 10, 20, 3, 0)) == 3600


# ──────────────────────────────────────────────────────────────────────────
# Integração
# ──────────────────────────────────────────────────────────────────────────

_DSN = os.getenv("TEST_DATABASE_URL_ESQUEMA", "").strip()
integracao = pytest.mark.skipif(not _DSN, reason="TEST_DATABASE_URL_ESQUEMA não definida")


@pytest.fixture
def banco(monkeypatch):
    from app import db_pg

    cliente = db_pg.Client(_DSN, min_size=1, max_size=3)
    with cliente.conexao() as conn, conn.cursor() as cur:
        cur.execute(
            "TRUNCATE public.carteira, public.carteira_historico, public.carteira_bloqueio, "
            "public.acessorias_busca, public.acessorias_empresa, public.acessorias_usuario, "
            "public.cert_history CASCADE"
        )
        cur.execute("DELETE FROM public.users WHERE email LIKE '%%@teste-acessorias'")
        cur.execute("UPDATE public.acessorias_departamento SET conta_para_carteira = (id IN (1, 2, 3))")
        ids = {}
        for nome, role in (("ana", "user"), ("gil", "gestor"), ("adm", "admin")):
            cur.execute(
                "INSERT INTO public.users (email, password_hash, role) VALUES (%s, 'x', %s) RETURNING id::text",
                (f"{nome}@teste-acessorias", role),
            )
            ids[nome] = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO public.cert_history (file_name, documento_numero, ultima_data_registrada) "
            "VALUES ('a.pfx', %s, now())", (MATRIZ,)
        )
    monkeypatch.setattr(acessorias, "_cliente", lambda: cliente)
    try:
        yield cliente, ids
    finally:
        cliente.fechar()


def _api_com(*empresas):
    return _api_falsa({
        "/companies/ListAll": [list(empresas)],
        "/users/ListAll": [[{"id": "10", "nome": "Ana", "email": "ana@teste-acessorias", "status": "Ativo"}]],
        "/departments/ListAll": [[{"ID": "1", "Nome": "Contábil"}]],
    })


def _linhas(cliente, sql, *params):
    with cliente.conexao() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall() if cur.description else []


@integracao
def test_ciclo_completo(banco):
    cliente, ids = banco
    _linhas(cliente, "INSERT INTO public.carteira (user_id, documento, atribuido_por_email) VALUES (%s, %s, 'x')",
            ids["ana"], OUTRA)
    emp = _empresa_api(FILIAL, deps=[(1, "Contábil", "ana@teste-acessorias"), (2, "Fiscal", "gil@teste-acessorias"),
                                     (3, "Pessoal", "adm@teste-acessorias")])

    # Primeira: sempre aguarda, nada muda.
    r = acessorias.buscar(api=_api_com(emp))
    assert r["estado"] == "aguardando" and r["motivo"] == "primeira aplicação"
    assert _linhas(cliente, "SELECT documento FROM public.carteira") == [(OUTRA,)]

    # Confirmada: filial sem certificado cai na matriz; manual de fora sai.
    r = acessorias.confirmar(r["id"], "adm@teste-acessorias")
    assert r["resumo"]["entradas"] == 2 and r["resumo"]["saidas"] == 1
    cart = sorted(_linhas(cliente, "SELECT user_id::text, documento, origem FROM public.carteira"))
    assert cart == sorted([(ids["ana"], MATRIZ, "acessorias"), (ids["gil"], MATRIZ, "acessorias")])
    hist = _linhas(cliente, "SELECT movimento, feito_por_email FROM public.carteira_historico ORDER BY id")
    assert ("saida", "adm@teste-acessorias") in hist and hist.count(("entrada", "adm@teste-acessorias")) == 2
    assert _linhas(cliente, "SELECT count(*) FROM public.acessorias_empresa") == [(1,)]
    assert _linhas(cliente, "SELECT email FROM public.acessorias_usuario") == [("ana@teste-acessorias",)]

    # Confirmar de novo não vale.
    with pytest.raises(acessorias.ErroAcessorias):
        acessorias.confirmar(r["id"], "adm@teste-acessorias")

    # Tirar a Ana = 1 de 2 acessos (50%): aguarda; a busca seguinte substitui.
    so_gil = _empresa_api(FILIAL, deps=[(2, "Fiscal", "gil@teste-acessorias")])
    r1 = acessorias.buscar(api=_api_com(so_gil))
    assert r1["estado"] == "aguardando" and "10%" in r1["motivo"]
    r2 = acessorias.buscar(api=_api_com(so_gil))
    assert r2["estado"] == "aguardando"
    assert _linhas(cliente, "SELECT estado FROM public.acessorias_busca WHERE id = %s", r1["id"]) == [("descartada",)]
    acessorias.descartar(r2["id"], "adm@teste-acessorias")
    assert len(_linhas(cliente, "SELECT 1 FROM public.carteira")) == 2

    # Bloqueio: a Ana bloqueada não volta; o resto aplica sozinho.
    _linhas(cliente, "DELETE FROM public.carteira WHERE user_id = %s", ids["ana"])
    _linhas(cliente, "INSERT INTO public.carteira_bloqueio (user_id, documento, bloqueado_por_email) "
                     "VALUES (%s, %s, 'adm')", ids["ana"], MATRIZ)
    r = acessorias.buscar(api=_api_com(emp))
    assert r["estado"] == "ok" and r["resumo"]["entradas"] == 0
    assert _linhas(cliente, "SELECT user_id::text FROM public.carteira") == [(ids["gil"],)]


@integracao
def test_erro_na_api_nao_muda_nada_e_libera_a_proxima(banco):
    cliente, _ = banco
    api = _api_falsa(PAGINAS, falhar_em="/departments/ListAll")
    r = acessorias.buscar(api=api)
    assert r["estado"] == "erro"
    assert _linhas(cliente, "SELECT count(*) FROM public.acessorias_empresa") == [(0,)]
    assert acessorias.buscar(api=_api_com(_empresa_api(OUTRA)))["estado"] == "aguardando"


@integracao
def test_uma_busca_por_vez_e_rodando_abandonada_e_liberada(banco):
    cliente, _ = banco
    _linhas(cliente, "INSERT INTO public.acessorias_busca (origem, estado) VALUES ('agendada', 'rodando')")
    assert acessorias.buscar(api=_api_com(_empresa_api(OUTRA)))["estado"] == "ocupada"
    _linhas(cliente, "UPDATE public.acessorias_busca SET iniciada_em = now() - interval '1 hour'")
    assert acessorias.buscar(api=_api_com(_empresa_api(OUTRA)))["estado"] == "aguardando"
    assert ("erro",) in _linhas(cliente, "SELECT estado FROM public.acessorias_busca")


# ──────────────────────────────────────────────────────────────────────────
# Tela e rotas
# ──────────────────────────────────────────────────────────────────────────

RAIZ = __import__("pathlib").Path(__file__).resolve().parent.parent


def test_rotas_so_de_administrador():
    fonte = (RAIZ / "app" / "rotas" / "acessorias.py").read_text(encoding="utf-8")
    blocos = fonte.split("@router.")[1:]
    assert len(blocos) == 4
    for bloco in blocos:
        assert "Depends(require_admin)" in bloco.split(") -> ")[0], bloco[:60]


def test_painel_numa_linha_e_lista_descontada():
    html = (RAIZ / "templates" / "carteiras.html").read_text(encoding="utf-8")
    css = (RAIZ / "static" / "aguia-carteiras.css").read_text(encoding="utf-8")
    painel = html[html.index('<section id="acessPainel"'):html.index("</section>", html.index('<section id="acessPainel"'))]
    # Os números da busca aguardando ficam no modal, não no painel: o painel
    # empurrava a lista de pessoas para baixo da dobra em 1366x657.
    assert "acessNumeros" not in painel and "ag-alert" not in painel
    assert 'id="modalAcess"' in html and 'id="acessNumeros"' in html
    assert 'classList.add("cg-com-acess")' in html
    media = css[css.index("@media (min-width: 1025px)"):]
    assert ".cg-com-acess .cg-op-rolagem { max-height: max(12rem, calc(100vh - 30rem)); }" in media
    assert "aguia-carteiras.css?v=acessorias-2026-10-20" in html
