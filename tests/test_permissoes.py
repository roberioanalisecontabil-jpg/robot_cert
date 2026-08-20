# -*- coding: utf-8 -*-
"""
Matriz de permissões por papel (`app/permissoes.py`).

Etapa 3 de `docs/PLANO_niveis_de_acesso.md`. Os testes aqui travam as decisões
de modelo, não a implementação: se amanhã a matriz vier de outro lugar, estes
testes devem continuar valendo.
"""
from __future__ import annotations

import pytest

from app import permissoes


@pytest.fixture(autouse=True)
def cache_limpo() -> None:
    """A matriz é cacheada por 30s; sem isto um teste contamina o seguinte."""
    permissoes.invalidar_cache()


def test_admin_e_sempre_total_e_nao_depende_da_matriz() -> None:
    """
    `admin` não tem linha na tabela, por desenho.

    É o que impede o engano mais caro possível numa tela de permissões: o
    administrador desmarcando o próprio acesso a Usuários e ficando sem como
    voltar. Não é validação que pode falhar — é ausência de dado.
    """
    for modulo in permissoes.MODULOS:
        assert permissoes.nivel_de("admin", modulo) == permissoes.NIVEL_EDITAR

    # Nem uma matriz vinda do banco muda isso: `admin` não passa pela consulta.
    assert "admin" not in permissoes.PADRAO


def test_papel_desconhecido_nao_herda_acesso() -> None:
    """Falha fechada: papel sem linha na matriz não ganha nada por omissão."""
    for modulo in permissoes.MODULOS:
        assert permissoes.nivel_de("auditor", modulo) == permissoes.NIVEL_NENHUM
    assert permissoes.nivel_de("", "inicio") == permissoes.NIVEL_NENHUM


def test_editar_satisfaz_ler_mas_ler_nao_satisfaz_editar() -> None:
    assert permissoes.pode("gestor", "carteiras", permissoes.NIVEL_LER)
    assert permissoes.pode("gestor", "carteiras", permissoes.NIVEL_EDITAR)
    assert permissoes.pode("user", "historico", permissoes.NIVEL_LER)
    assert not permissoes.pode("user", "historico", permissoes.NIVEL_EDITAR)
    assert not permissoes.pode("user", "usuarios", permissoes.NIVEL_LER)


def test_modulo_desconhecido_estoura_em_vez_de_devolver_nenhum() -> None:
    """
    Erro de digitação no nome do módulo não pode virar "sem permissão".

    `require_modulo("usuarios ")` com espaço sobrando devolveria `nenhum` em
    silêncio e trancaria todo mundo para fora de um módulo que ninguém mexeu.
    """
    with pytest.raises(ValueError):
        permissoes.nivel_de("user", "modulo-que-nao-existe")
    with pytest.raises(ValueError):
        permissoes.pode("user", "inicio", "nivel-que-nao-existe")


def test_padrao_reproduz_o_comportamento_de_hoje() -> None:
    """
    A semente é o comportamento atual, não uma política nova.

    Ligar esta camada não pode mudar nada no dia do deploy — assim qualquer
    diferença observada depois é mudança que alguém fez de propósito, e não
    efeito colateral da migration.
    """
    # Só admin vê Dashboard, Instalador, Usuários e Configuração (ui-common.js).
    for papel in ("gestor", "user"):
        for modulo in ("dashboard", "instalador", "usuarios", "configuracao"):
            assert permissoes.nivel_de(papel, modulo) == permissoes.NIVEL_NENHUM

    # Carteiras é do gestor, e só dele entre os não-admin.
    assert permissoes.nivel_de("gestor", "carteiras") == permissoes.NIVEL_EDITAR
    assert permissoes.nivel_de("user", "carteiras") == permissoes.NIVEL_NENHUM

    # As telas de consulta ficam abertas a quem está autenticado, como hoje.
    for papel in ("gestor", "user"):
        for modulo in ("inicio", "historico", "vencidos", "duplicidades", "acompanhamento"):
            assert permissoes.nivel_de(papel, modulo) == permissoes.NIVEL_LER


def test_matriz_para_papel_devolve_todos_os_modulos() -> None:
    """O menu monta a partir disto; faltar chave viraria item invisível."""
    for papel in ("admin", "gestor", "user", "papel-novo"):
        linha = permissoes.matriz_para_papel(papel)
        assert set(linha) == set(permissoes.MODULOS)
        assert all(v in permissoes.NIVEIS for v in linha.values())


def test_tabela_ausente_cai_no_padrao_em_vez_de_derrubar_o_portal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Código pode chegar antes da migration.

    É a lição registrada na migration de 18/08: "código antes da coluna faria
    toda requisição autenticada virar 503 — o portal inteiro parando". Tabela
    que ainda não existe vale como "não configurado", e o padrão entra.
    """
    class _Tabela:
        def select(self, *_a, **_k):
            return self

        def execute(self):
            raise RuntimeError(
                "{'message': \"Could not find the table 'public.permissoes' "
                "in the schema cache\", 'code': 'PGRST205'}"
            )

    class _SB:
        def table(self, _nome):
            return _Tabela()

    monkeypatch.setattr("app.settings_state.supabase_configured", lambda: True)
    monkeypatch.setattr("app.settings_state._supabase", lambda: _SB())

    assert permissoes.nivel_de("gestor", "carteiras") == permissoes.NIVEL_EDITAR


def test_falha_de_leitura_nao_e_falta_de_permissao(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Banco fora do ar levanta — quem chama traduz em 503, nunca em 403.

    Mesmo princípio de `cert_installer.AlcanceIndisponivel`: um 403 aqui faria a
    pessoa acreditar que perdeu um acesso que continua sendo dela, e o suporte
    procuraria a permissão errada.
    """
    class _Tabela:
        def select(self, *_a, **_k):
            return self

        def execute(self):
            raise RuntimeError("connection refused")

    class _SB:
        def table(self, _nome):
            return _Tabela()

    monkeypatch.setattr("app.settings_state.supabase_configured", lambda: True)
    monkeypatch.setattr("app.settings_state._supabase", lambda: _SB())

    with pytest.raises(permissoes.PermissoesIndisponiveis):
        permissoes.nivel_de("gestor", "carteiras")

    # E o admin continua passando: ele não consulta a matriz.
    assert permissoes.nivel_de("admin", "carteiras") == permissoes.NIVEL_EDITAR


def test_tabela_vazia_vale_como_nao_semeada(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Zero linhas é "ainda não semeada", não "ninguém pode nada".

    Fechar tudo aqui derrubaria o acesso de todo mundo entre a criação da tabela
    e o INSERT da semente — uma janela de segundos que ninguém quer descobrir em
    produção.
    """
    class _Resp:
        data: list = []

    class _Tabela:
        def select(self, *_a, **_k):
            return self

        def execute(self):
            return _Resp()

    class _SB:
        def table(self, _nome):
            return _Tabela()

    monkeypatch.setattr("app.settings_state.supabase_configured", lambda: True)
    monkeypatch.setattr("app.settings_state._supabase", lambda: _SB())

    assert permissoes.nivel_de("gestor", "carteiras") == permissoes.NIVEL_EDITAR


def test_matriz_do_banco_vence_o_padrao(monkeypatch: pytest.MonkeyPatch) -> None:
    """Configurar tem que valer — senão a tela seria decorativa."""
    class _Resp:
        data = [
            {"papel": "gestor", "modulo": "carteiras", "nivel": "ler"},
            {"papel": "user", "modulo": "instalador", "nivel": "editar"},
            # Lixo: módulo inexistente e nível inválido são descartados sem
            # derrubar a leitura inteira.
            {"papel": "user", "modulo": "modulo-fantasma", "nivel": "editar"},
            {"papel": "user", "modulo": "inicio", "nivel": "super"},
        ]

    class _Tabela:
        def select(self, *_a, **_k):
            return self

        def execute(self):
            return _Resp()

    class _SB:
        def table(self, _nome):
            return _Tabela()

    monkeypatch.setattr("app.settings_state.supabase_configured", lambda: True)
    monkeypatch.setattr("app.settings_state._supabase", lambda: _SB())

    assert permissoes.nivel_de("gestor", "carteiras") == permissoes.NIVEL_LER
    assert permissoes.nivel_de("user", "instalador") == permissoes.NIVEL_EDITAR
    # O que veio do banco substitui a linha inteira do papel: o que não foi
    # gravado é `nenhum`, e não o valor do padrão. Meia-configuração seria pior
    # que nenhuma — a tela mostraria uma coisa e o servidor faria outra.
    assert permissoes.nivel_de("user", "historico") == permissoes.NIVEL_NENHUM
    assert permissoes.nivel_de("user", "inicio") == permissoes.NIVEL_NENHUM


def test_semente_da_migration_e_identica_ao_padrao_do_codigo() -> None:
    """
    O SQL e o Python não podem divergir.

    Se a semente da migration disser uma coisa e `PADRAO` outra, o portal se
    comporta de um jeito antes de rodar a migration e de outro depois — e a
    diferença apareceria como "mudou sozinho" para quem usa. Este teste é a
    única coisa que amarra os dois arquivos.
    """
    import re
    from pathlib import Path

    sql_path = Path("supabase/pendentes/20260820100000_permissoes_por_papel.sql")
    if not sql_path.is_file():  # migration já aplicada e movida para migrations/
        sql_path = Path("supabase/migrations/20260820100000_permissoes_por_papel.sql")
    assert sql_path.is_file(), "migration de permissões sumiu"

    sql = sql_path.read_text(encoding="utf-8")

    semente: dict = {}
    for papel, modulo, nivel in re.findall(r"\('(gestor|user)',\s*'(\w+)',\s*'(\w+)'", sql):
        semente.setdefault(papel, {})[modulo] = nivel

    for papel in ("gestor", "user"):
        for modulo in permissoes.MODULOS:
            assert semente[papel][modulo] == permissoes.PADRAO[papel][modulo], (
                f"{papel}/{modulo}: SQL diz {semente[papel][modulo]!r}, "
                f"código diz {permissoes.PADRAO[papel][modulo]!r}"
            )

    # E o `check` do banco tem que aceitar exatamente os módulos que o código
    # conhece — nem mais (aceitaria lixo), nem menos (recusaria valor legítimo).
    bloco = re.search(r"modulo\s+text not null check \(modulo in \(([^)]*)\)", sql, re.S)
    assert bloco, "o check de modulo sumiu da migration"
    assert set(re.findall(r"'(\w+)'", bloco.group(1))) == set(permissoes.MODULOS)


# ── A guarda ligada em rota de verdade ──────────────────────────────────────

def _token(papel: str) -> dict:
    from app import auth
    return {"Authorization": "Bearer " + auth.create_access_token(
        {"sub": f"{papel}@exemplo.com", "role": papel})}


def test_dashboard_respeita_a_matriz(client) -> None:
    """
    `/api/dashboard` saiu de `require_admin` para `require_modulo("dashboard")`.

    O comportamento tinha que continuar IDENTICO — a matriz da `nenhum` a gestor
    e user para este modulo. Nenhum teste existente notou a troca, o que e o
    resultado desejado e tambem o motivo de este teste existir: sem ele, a
    camada nova estaria em producao sem uma linha que prove que ela barra.
    """
    for rota in ("/api/dashboard", "/api/dashboard/renovacoes"):
        for papel in ("user", "gestor"):
            r = client.get(rota, headers=_token(papel))
            assert r.status_code == 403, f"{papel} alcancou {rota}"

        # Admin passa sem consultar a matriz. 200 ou 5xx de dependencia externa
        # servem; o que nao pode e 403.
        r = client.get(rota, headers=_token("admin"))
        assert r.status_code != 403, f"admin foi barrado em {rota}"


def test_matriz_indisponivel_vira_503_e_nao_403(
    client, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Banco fora do ar nao pode parecer falta de permissao.

    Um 403 aqui faria o gestor acreditar que perdeu um acesso que continua sendo
    dele — e o suporte procuraria a permissao errada, em vez de olhar o banco.
    """
    def _explode(*_a, **_k):
        raise permissoes.PermissoesIndisponiveis("connection refused")

    monkeypatch.setattr(permissoes, "pode", _explode)

    r = client.get("/api/dashboard", headers=_token("gestor"))
    assert r.status_code == 503, f"esperava 503, veio {r.status_code}"


def test_require_modulo_recusa_nome_invalido_na_importacao() -> None:
    """
    Erro de digitacao no nome do modulo derruba o servidor na partida, e nao
    silenciosamente tranca todo mundo para fora em producao.
    """
    from app.main import require_modulo

    with pytest.raises(ValueError):
        require_modulo("dashbaord")
    with pytest.raises(ValueError):
        require_modulo("dashboard", "editarr")


def test_usuarios_respeita_a_matriz(client) -> None:
    """As 13 rotas de Usuários saíram de `require_admin` para a matriz."""
    for papel in ("user", "gestor"):
        h = _token(papel)
        assert client.get("/api/users", headers=h).status_code == 403
        assert client.get("/api/departamentos", headers=h).status_code == 403
        assert client.post("/api/users", json={}, headers=h).status_code == 403
        assert client.delete("/api/users/qualquer", headers=h).status_code == 403

    assert client.get("/api/users", headers=_token("admin")).status_code != 403


def test_ler_deixa_ver_e_nao_deixa_mexer(client, monkeypatch: pytest.MonkeyPatch) -> None:
    """
    O eixo que o cliente pediu: "editar ou só visualizar".

    Este é o teste que prova que a promessa da tela é real. Um papel com `ler`
    em Usuários enxerga a lista e é recusado em toda escrita — sem ele, a
    separação leitura/escrita seria só nome de variável.
    """
    monkeypatch.setattr(
        permissoes, "_matriz",
        lambda: {"gestor": {**permissoes.PADRAO["gestor"], "usuarios": permissoes.NIVEL_LER}},
    )
    h = _token("gestor")

    # Vê.
    assert client.get("/api/users", headers=h).status_code != 403
    assert client.get("/api/departamentos", headers=h).status_code != 403

    # Não mexe — nem criando, nem alterando, nem apagando.
    assert client.post("/api/users", json={}, headers=h).status_code == 403
    assert client.put("/api/users/x", json={}, headers=h).status_code == 403
    assert client.delete("/api/users/x", headers=h).status_code == 403
    assert client.post("/api/users/x/deactivate", headers=h).status_code == 403
    assert client.post("/api/departamentos", json={}, headers=h).status_code == 403


def test_lgpd_da_propria_conta_nao_depende_do_modulo_usuarios(
    client, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Exportar e apagar os PRÓPRIOS dados é direito de quem está logado.

    Amarrar isso à permissão do módulo Usuários tiraria de um operador comum o
    direito de exportar os próprios dados — que é exatamente o oposto do que a
    LGPD pede. As duas rotas ficam em `require_auth`, e este teste impede que
    alguém as "padronize" junto com as outras 13.
    """
    monkeypatch.setattr(
        permissoes, "_matriz",
        lambda: {"user": {**permissoes.PADRAO["user"], "usuarios": permissoes.NIVEL_NENHUM}},
    )
    r = client.get("/api/users/me/export", headers=_token("user"))
    assert r.status_code != 403, "operador foi barrado ao exportar os próprios dados"


def test_agente_de_verdade_nao_alcanca_modulo_de_gente(client_com_chave, api_key: str) -> None:
    """
    `agent@internal` e barrado nos modulos humanos; `anonymous@local` nao.

    A distincao e por E-MAIL, nao por papel — os dois chegam com role 'agent'.
    O agente de verdade nao tem o que fazer em Histórico ou Acompanhamento; já a
    identidade anônima é a compatibilidade documentada de ambiente sem API_KEY,
    e barrá-la pararia o portal em dev e em instalação ainda sem chave.
    """
    h = {"X-API-Key": api_key}
    for rota in ("/api/certificados/historico",
                 "/api/certificados/vencidos",
                 "/api/certificados/duplicidades",
                 "/api/colaborador/certificados/painel"):
        assert client_com_chave.get(rota, headers=h).status_code == 403, rota

    # `/api/certificados` ficou FORA da matriz de propósito — `diagnostico.py` a
    # consome com a chave, e Início é onde todo mundo aterrissa.
    assert client_com_chave.get(
        "/api/certificados", headers=h
    ).status_code != 403


def test_ambiente_sem_api_key_continua_aberto(client) -> None:
    """
    A guarda nova não pode ser mais estrita que `require_auth`.

    Sem API_KEY, `require_auth` devolve identidade anônima e o portal inteiro
    fica aberto — compatibilidade que o próprio `require_auth` documenta. Se
    `require_modulo` barrasse aí, o portal pararia em dev e em qualquer
    instalação que ainda não configurou a chave.
    """
    for rota in ("/api/certificados/historico", "/api/colaborador/certificados/painel"):
        assert client.get(rota).status_code != 403, rota


# ── A API da tela ───────────────────────────────────────────────────────────

def test_editar_permissoes_exige_admin_e_nao_o_modulo_usuarios(
    client, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Quem concede tem que estar ACIMA do que concede.

    Se a rota fosse `require_modulo("usuarios", "editar")`, um gestor com
    escrita em Usuários se autoconcederia Configuração e Instalador em dois
    cliques.

    O teste dá a esse gestor exatamente esse acesso — `usuarios: editar` — e
    exige 403 mesmo assim. Sem essa preparação o teste não provaria nada: com a
    semente atual o gestor tem `usuarios: nenhum`, e as DUAS guardas recusam
    igualmente. Foi o que uma verificação por mutação mostrou.
    """
    monkeypatch.setattr(
        permissoes, "_matriz",
        lambda: {
            "gestor": {**permissoes.PADRAO["gestor"], "usuarios": permissoes.NIVEL_EDITAR},
            "user": {**permissoes.PADRAO["user"], "usuarios": permissoes.NIVEL_EDITAR},
        },
    )
    for papel in ("user", "gestor"):
        h = _token(papel)
        assert client.get("/api/permissoes", headers=h).status_code == 403, papel
        assert client.put(
            "/api/permissoes", json={"matriz": {}}, headers=h
        ).status_code == 403, f"{papel} editou a matriz de permissoes"


def test_get_permissoes_entrega_o_que_a_tela_precisa(client) -> None:
    r = client.get("/api/permissoes", headers=_token("admin"))
    assert r.status_code == 200
    d = r.json()
    # `modulos` deixou de ser lista de nomes e passou a carregar, por modulo,
    # os niveis que ele aceita e se ja e governado — e o que a tela precisa
    # para nao oferecer controle inerte.
    assert [m["id"] for m in d["modulos"]] == list(permissoes.MODULOS)
    por_id = {m["id"]: m for m in d["modulos"]}
    assert por_id["usuarios"]["niveis"] == list(permissoes.NIVEIS)
    assert permissoes.NIVEL_EDITAR not in por_id["vencidos"]["niveis"]
    assert por_id["usuarios"]["governado"] is True
    assert por_id["carteiras"]["governado"] is False
    assert d["papeis"] == list(permissoes.PAPEIS_CONFIGURAVEIS)
    assert d["papeis_totais"] == list(permissoes.PAPEIS_TOTAIS)
    # `admin` nao vem como linha editavel: e o que impede a tela de oferecer
    # uma coluna que trancaria o proprio administrador para fora.
    assert "admin" not in d["matriz"]
    for papel in permissoes.PAPEIS_CONFIGURAVEIS:
        assert set(d["matriz"][papel]) == set(permissoes.MODULOS)


def test_gravar_recusa_admin_modulo_invalido_e_matriz_incompleta() -> None:
    with pytest.raises(ValueError, match="não configurável"):
        permissoes.gravar({"admin": {m: "editar" for m in permissoes.MODULOS}})
    with pytest.raises(ValueError, match="desconhecido"):
        permissoes.gravar({"user": {"modulo-fantasma": "ler"}})
    with pytest.raises(ValueError, match="incompleta"):
        permissoes.gravar({"user": {"inicio": "ler"}, "gestor": {"inicio": "ler"}})


def test_gravar_sem_banco_avisa_em_vez_de_fingir_que_salvou(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Sem Supabase nao ha onde gravar — e a tela precisa saber.

    Retornar sucesso aqui seria pior que o erro: a pessoa fecharia a tela
    achando que configurou, e a matriz continuaria a de antes.
    """
    monkeypatch.setattr("app.settings_state.supabase_configured", lambda: False)
    completa = {p: {m: "nenhum" for m in permissoes.MODULOS}
                for p in permissoes.PAPEIS_CONFIGURAVEIS}
    with pytest.raises(permissoes.PermissoesIndisponiveis):
        permissoes.gravar(completa)


# ── A declaracao nao pode mentir ────────────────────────────────────────────

def _modulos_ligados_de_verdade() -> dict:
    """Le `main.py` e devolve {modulo: {niveis usados}} a partir das rotas."""
    import re
    from pathlib import Path

    fonte = Path("app/main.py").read_text(encoding="utf-8")
    achados: dict = {}
    padrao = re.compile(
        # O  opcional entra no padrao: sem ele, uma rota de
        # mao dupla nao seria contada e o teste acusaria divergencia falsa.
        r'require_modulo\(\s*"(\w+)"(?:\s*,\s*permissoes\.NIVEL_(\w+))?'
        r'(?:\s*,\s*permitir_agente=\w+)?\s*\)'
    )
    for modulo, nivel in padrao.findall(fonte):
        achados.setdefault(modulo, set()).add((nivel or "LER").lower())
    return achados


def test_modulos_governados_bate_com_as_rotas() -> None:
    """
    `MODULOS_GOVERNADOS` tem que ser a verdade, e não uma intenção.

    A tela desabilita o controle dos módulos fora dessa lista e diz "ainda não
    governado". Se a lista dissesse que um módulo é governado e nenhuma rota o
    usasse, a tela ofereceria um controle inerte — exatamente o defeito que ela
    existe para não repetir. E o inverso é pior: um módulo ligado de verdade
    apareceria travado, e ninguém conseguiria configurá-lo.
    """
    reais = _modulos_ligados_de_verdade()
    assert set(reais) == set(permissoes.MODULOS_GOVERNADOS), (
        f"declarado {sorted(permissoes.MODULOS_GOVERNADOS)}, "
        f"ligado de verdade {sorted(reais)}"
    )


def test_modulos_com_escrita_bate_com_as_rotas() -> None:
    """
    `MODULOS_COM_ESCRITA` decide se a tela oferece "Ver e editar".

    Declarar escrita onde não há faria a opção voltar a ser promessa vazia — o
    que o cliente apontou. Deixar de declarar onde há tornaria impossível
    conceder uma escrita que existe.
    """
    reais = _modulos_ligados_de_verdade()
    com_escrita = {m for m, niveis in reais.items() if "editar" in niveis}
    assert com_escrita == set(permissoes.MODULOS_COM_ESCRITA), (
        f"declarado {sorted(permissoes.MODULOS_COM_ESCRITA)}, "
        f"com rota em editar {sorted(com_escrita)}"
    )


def test_niveis_de_modulo_nao_oferece_editar_sem_escrita() -> None:
    for modulo in permissoes.MODULOS:
        niveis = permissoes.niveis_de_modulo(modulo)
        assert permissoes.NIVEL_NENHUM in niveis and permissoes.NIVEL_LER in niveis
        tem_editar = permissoes.NIVEL_EDITAR in niveis
        assert tem_editar == (modulo in permissoes.MODULOS_COM_ESCRITA), modulo


def test_gravar_recusa_editar_em_modulo_sem_escrita() -> None:
    """
    Esconder na tela não basta: o servidor tem que recusar.

    Aceitar `editar` num módulo sem escrita gravaria um valor que o servidor
    ignora — a matriz passaria a afirmar um poder que ninguém tem, e a próxima
    pessoa a ler a tabela acreditaria nela.
    """
    completa = {p: {m: permissoes.NIVEL_LER for m in permissoes.MODULOS}
                for p in permissoes.PAPEIS_CONFIGURAVEIS}
    completa["gestor"]["vencidos"] = permissoes.NIVEL_EDITAR
    with pytest.raises(ValueError, match="não tem escrita"):
        permissoes.gravar(completa)


def test_configuracao_governa_gente_e_deixa_a_maquina_passar(
    client_com_chave, api_key: str
) -> None:
    """
    `GET /api/settings` e de mao dupla, e o teste trava os dois lados.

    A tela de Configuracao le dali, mas `agent/run_agent.py` tambem — e o que
    diz ao agente quais pastas varrer. Sem a valvula `permitir_agente` so haveria
    escolha ruim: deixar a rota fora da matriz, e ai "Nao entra" mentiria (a
    pessoa continuaria lendo pastas e host de SMTP), ou liga-la sem ressalva e
    parar a varredura em producao.
    """
    from app import auth as _auth

    # Gente sem o modulo: recusada, inclusive na leitura.
    for papel in ("user", "gestor"):
        h = {"Authorization": "Bearer " + _auth.create_access_token(
            {"sub": f"{papel}@exemplo.com", "role": papel})}
        assert client_com_chave.get("/api/settings", headers=h).status_code == 403, papel
        assert client_com_chave.put(
            "/api/settings", json={}, headers=h
        ).status_code == 403, papel

    # A maquina passa pelo caminho dela.
    assert client_com_chave.get(
        "/api/settings", headers={"X-API-Key": api_key}
    ).status_code == 200, "o agente foi barrado nas proprias configuracoes"


def test_escrita_de_configuracao_nao_e_de_mao_dupla(client_com_chave, api_key: str) -> None:
    """
    A valvula vale so para a LEITURA. O agente le a configuracao; ele nao a
    altera — e abrir a escrita para a chave transformaria a X-API-Key numa
    credencial de administracao.
    """
    h = {"X-API-Key": api_key}
    assert client_com_chave.put("/api/settings", json={}, headers=h).status_code == 403
    assert client_com_chave.post(
        "/api/settings/alerts/trigger", json={}, headers=h
    ).status_code == 403
