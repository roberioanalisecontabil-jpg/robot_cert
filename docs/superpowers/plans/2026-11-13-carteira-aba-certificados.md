# Carteira — aba Certificados e prazo da liberação manual (Frente A) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Liberar um certificado (documento) para várias pessoas numa aba nova "Certificados" em Carteiras, com prazo opcional de até 700 dias, histórico de toda entrada e saída manual e vencimento automático.

**Architecture:** A `carteira` ganha `valido_desde`/`valido_ate`. As leituras que decidem acesso passam a ignorar linha fora do período (filtro em Python, para os fakes dos testes continuarem valendo). As escritas manuais passam a gravar `carteira_historico`. Um laço no servidor apaga as linhas vencidas a cada 5 min. A aba nova usa três rotas novas em `app/rotas/carteiras.py` e reaproveita o Retirar (`DELETE /api/carteira/{user_id}/{documento}`) e a lista de pessoas (`GET /api/carteira/operadores`).

**Tech Stack:** FastAPI, PostgreSQL 17 (cliente estilo supabase em `app/settings_state._banco`, psycopg direto em `app/acessorias.py`), Jinja2 + JS sem framework, Águia DS (`.ag-*`), pytest.

**Spec:** `docs/superpowers/specs/2026-11-13-carteira-certificados-remocao-uso-design.md` (seção "Frente A"). A Frente B ganha plano próprio depois que esta estiver no ar e as liberações manuais cadastradas.

## Global Constraints

- Prazo: indefinido (`valido_ate` nulo) ou período por calendário de **no máximo 700 dias**, contados de `valido_desde`.
- `valido_desde` padrão = hoje; pode ser futuro; nunca passado. Antes do início a liberação não vale (não instala).
- Prazo só existe para origem `manual`. Linha `acessorias`/`planilha` nunca recebe prazo.
- Quem libera: regra atual — `_exigir_alcance` (Gestor só quem ele gere, Admin todos) e `_exigir_documentos_ao_alcance`. Módulo `require_modulo("carteiras", NIVEL_EDITAR)` para escrever.
- A sincronização do Acessórias nunca apaga liberação manual; ao converter manual→acessorias, o prazo é descartado.
- "Hoje" = `date.today()` do servidor (o servidor roda no horário de Brasília).
- Ordem da casa: código tolerante primeiro, migration junto no mesmo deploy (`db/aplicar_schema.py` roda no `atualizar-portal.ps1`). Nunca pedir `.sql` à mão.
- Commits com `git commit -F <arquivo>`; mensagem termina com `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. O hook de pré-commit roda a suíte: corrigir e commitar em comandos separados.
- Textos de tela em pt-BR. Componentes Águia DS já usados em `templates/carteiras.html` e `templates/configuracao.html` (`.ag-abas`).

## Review Focus

1. Gestor manda incluir um lote em que uma pessoa está fora do alcance dele: espera-se 403 e **nada** gravado (tudo ou nada). Teste em Task 5.
2. Limite exato: 700 dias aceita, 701 recusa; início no passado recusa; fim antes do início recusa. Teste em Task 2.
3. Liberação com início futuro: aparece na aba ("começa em …") mas não entra em `listar_carteira` (não instala). Teste em Task 2.
4. Incluir com prazo uma pessoa que já tem o documento pelo Acessórias: o prazo é ignorado, a linha continua `acessorias` sem fim. Teste em Task 3.
5. Laço de vencimento com uma linha que falha ao apagar: as outras saem mesmo assim e os tokens pendentes de cada pessoa afetada são revogados. Teste em Task 4.

---

### Task 1: Migration do prazo

**Files:**
- Create: `supabase/migrations/20261113100000_carteira_prazo.sql`
- Test: `tests/test_migration_carteira_prazo.py`

**Interfaces:**
- Produces: colunas `public.carteira.valido_desde date NOT NULL DEFAULT current_date`, `public.carteira.valido_ate date NULL`; constraint `carteira_prazo_valido` = `CHECK (valido_ate IS NULL OR (valido_ate >= valido_desde AND valido_ate - valido_desde <= 700))`; `carteira_historico_origem_valida` passa a aceitar `'prazo'` além de `('manual','planilha','acessorias','papel','desativacao','bloqueio')`.

- [ ] **Step 1: Write the failing test** (padrão de `tests/test_migration_acessorias_sincronizada.py`)

```python
SQL = RAIZ / "supabase" / "migrations" / "20261113100000_carteira_prazo.sql"

def test_colunas_idempotentes():
    s = _sql()
    assert "ADD COLUMN IF NOT EXISTS valido_desde date NOT NULL DEFAULT current_date" in s
    assert "ADD COLUMN IF NOT EXISTS valido_ate date" in s

def test_teto_de_700_dias():
    assert "valido_ate - valido_desde <= 700" in _sem_comentarios()

def test_historico_aceita_prazo_sem_perder_os_antigos():
    s = _sem_comentarios()
    for o in ("manual", "planilha", "acessorias", "papel", "desativacao", "bloqueio", "prazo"):
        assert f"'{o}'" in s
    # constraint achada pela definição, como em 20261020100000
    assert "pg_get_constraintdef" in s
```

- [ ] **Step 2:** `pytest tests/test_migration_carteira_prazo.py -v` → FAIL (arquivo não existe).
- [ ] **Step 3:** Escrever a migration. Constraints novas dentro de `DO $$ … IF NOT EXISTS (SELECT 1 FROM pg_constraint …)`; a do histórico troca pela definição (copiar o bloco de `20261020100000_carteira_sincronizada_pelo_acessorias.sql:140-151`). Cabeçalho "NAO rode a mao", só ASCII.
- [ ] **Step 4:** `pytest tests/test_migration_carteira_prazo.py -v` → PASS.
- [ ] **Step 5:** Commit `feat(carteira): migration do prazo da liberacao manual`.

### Task 2: Vigência e validação do prazo

**Files:**
- Modify: `app/cert_installer.py` (`listar_carteira` ~:821, `detalhar_carteira` ~:1157)
- Test: `tests/test_carteira_prazo.py` (novo; fake do banco copiado do de `tests/test_carteira.py`)

**Interfaces:**
- Produces:
  - `PRAZO_MAX_DIAS = 700`
  - `class PrazoInvalido(ValueError)` — a mensagem vai para a tela.
  - `validar_prazo(desde: date, ate: Optional[date], hoje: date) -> None`
  - `vigente(linha: Dict[str, Any], hoje: date) -> bool` — `valido_desde` (ISO ou `date`, ausente = vale) `<= hoje` e (`valido_ate` nulo ou `>= hoje`).
  - `listar_carteira` passa a selecionar `documento, valido_desde, valido_ate` e devolver só as vigentes.
  - `detalhar_carteira` passa a devolver também `valido_desde`, `valido_ate` (todas as linhas, inclusive futuras; a tela mostra).

- [ ] **Step 1: Failing tests**

```python
H = date(2026, 11, 13)
def test_700_aceita_701_recusa():
    ci.validar_prazo(H, H + timedelta(days=700), H)
    with pytest.raises(ci.PrazoInvalido): ci.validar_prazo(H, H + timedelta(days=701), H)
def test_inicio_no_passado_recusa():
    with pytest.raises(ci.PrazoInvalido): ci.validar_prazo(H - timedelta(days=1), None, H)
def test_fim_antes_do_inicio_recusa():
    with pytest.raises(ci.PrazoInvalido): ci.validar_prazo(H + timedelta(days=5), H + timedelta(days=4), H)
def test_vigente():
    assert ci.vigente({"valido_desde": "2026-11-13", "valido_ate": None}, H)
    assert ci.vigente({}, H)  # linha antiga, antes da migration
    assert not ci.vigente({"valido_desde": "2026-11-14"}, H)
    assert not ci.vigente({"valido_desde": "2026-01-01", "valido_ate": "2026-11-12"}, H)
def test_inicio_futuro_nao_instala(banco):  # Review Focus 3
    banco.carteira = [{"user_id": "u1", "documento": "111", "valido_desde": "2099-01-01", "valido_ate": None}]
    assert ci.listar_carteira("u1") == set()
    assert [l["documento"] for l in ci.detalhar_carteira("u1")] == ["111"]
```

- [ ] **Step 2:** `pytest tests/test_carteira_prazo.py -v` → FAIL.
- [ ] **Step 3:** Implementar. `vigente` aceita linha sem as chaves (código antes da migration, fakes antigos).
- [ ] **Step 4:** `pytest tests/test_carteira_prazo.py tests/test_carteira.py tests/test_carteira_por_papel.py -v` → PASS.
- [ ] **Step 5:** Commit `feat(carteira): liberacao fora do periodo nao vale`.

### Task 3: Escritas manuais gravam prazo e histórico

**Files:**
- Modify: `app/cert_installer.py` (`atribuir_carteira` ~:1230, `remover_da_carteira` ~:1261)
- Modify: `app/acessorias.py` (`retirar` ~:1088: linha manual também grava histórico; conversão em `aplicar` ~:683)
- Modify: `app/rotas/carteiras.py` (`CarteiraRequest`, `atribuir_carteira` rota, `remover_carteira` rota)
- Test: `tests/test_carteira_prazo.py`, `tests/test_acessorias.py`

**Interfaces:**
- Consumes: `validar_prazo`, `PrazoInvalido` (Task 2).
- Produces:
  - `atribuir_carteira(user_id, documentos, atribuido_por, atribuido_por_email, valido_desde: Optional[date] = None, valido_ate: Optional[date] = None, hoje: Optional[date] = None) -> int`
    - lê as linhas existentes do par; documento cuja linha existe com origem ≠ `manual` **não** é regravado (Review Focus 4);
    - linha nova ou manual: upsert com `valido_desde` (padrão hoje) e `valido_ate`; mudar o prazo de uma manual = chamar de novo;
    - grava `carteira_historico` (`movimento='entrada'`, `origem='manual'`) só para linha que não existia.
  - `remover_da_carteira(user_id, documento, por_id: Optional[str] = None, por_email: str = "") -> None` — grava `saida`/`manual` se apagou alguma linha.
  - `acessorias.retirar`: quando a linha apagada era manual, grava `saida`/`manual` com `por_id`/`por_email` antes de devolver `False`.
  - Conversão no Acessórias: `UPDATE public.carteira SET origem = 'acessorias', valido_ate = NULL, valido_desde = LEAST(valido_desde, current_date) WHERE …`.
  - `CarteiraRequest` ganha `valido_desde: Optional[date] = None`, `valido_ate: Optional[date] = None`; a rota traduz `PrazoInvalido` em 400 com a mensagem.

- [ ] **Step 1: Failing tests**

```python
def test_atribuir_com_prazo_grava_e_historico(banco): ...
    # atribuir_carteira("u1", ["111"], "a", "a@x", H, H+timedelta(days=30), hoje=H)
    # banco.carteira[0] tem valido_ate == "2026-12-13"; banco.historico == [entrada/manual/111]
def test_prazo_nao_toca_linha_do_acessorias(banco):  # Review Focus 4
    # linha existente origem acessorias; atribuir com prazo -> linha sem valido_ate, origem acessorias, sem histórico
def test_reatribuir_manual_muda_prazo_sem_historico_novo(banco): ...
def test_remover_manual_grava_saida(banco): ...
def test_prazo_invalido_vira_400(client): ...  # POST /api/carteira com 701 dias -> 400, nada gravado
# tests/test_acessorias.py
def test_conversao_descarta_prazo(): ...  # SQL da conversão contém "valido_ate = NULL"
def test_retirar_manual_grava_historico(): ...
```

- [ ] **Step 2:** rodar → FAIL.
- [ ] **Step 3:** Implementar conforme Interfaces.
- [ ] **Step 4:** `pytest tests/test_carteira_prazo.py tests/test_acessorias.py tests/test_pagina_carteiras.py tests/test_carteira.py -v` → PASS.
- [ ] **Step 5:** Commit `feat(carteira): prazo e historico nas escritas manuais`.

### Task 4: Laço de vencimento

**Files:**
- Modify: `app/cert_installer.py` (função nova)
- Modify: `app/main.py` (laço novo junto de `acessorias_loop` ~:240 e `create_task` ~:290)
- Test: `tests/test_carteira_prazo.py`

**Interfaces:**
- Produces: `expirar_prazos(hoje: Optional[date] = None) -> int` — seleciona `carteira` com `valido_ate` não nulo, filtra `< hoje` em Python, apaga cada par, grava `saida`/`prazo` (`feito_por` nulo, `feito_por_email = "prazo"`), chama `revogar_tokens_pendentes(user_id)` uma vez por pessoa. Erro numa linha é logado e não para as outras. Devolve quantas saíram.
- `prazos_loop()` em `main.py`: `await asyncio.sleep(120)` inicial, depois a cada 300 s em `run_in_executor`; loga só quando `> 0`; cancelada no shutdown como as outras.

- [ ] **Step 1: Failing tests**

```python
def test_vencida_sai_com_historico_e_tokens(banco, monkeypatch): ...
    # valido_ate = H-1 sai; valido_ate = H fica (vale até o fim do dia); revogar chamado com "u1"
def test_falha_numa_linha_nao_para_as_outras(banco, monkeypatch):  # Review Focus 5
    # delete do primeiro par levanta; o segundo sai; devolve 1
```

- [ ] **Step 2:** rodar → FAIL.
- [ ] **Step 3:** Implementar.
- [ ] **Step 4:** `pytest tests/test_carteira_prazo.py -v` → PASS.
- [ ] **Step 5:** Commit `feat(carteira): vencimento automatico do prazo`.

### Task 5: Rotas da aba Certificados

**Files:**
- Modify: `app/cert_installer.py` (função de leitura do cofre)
- Modify: `app/rotas/carteiras.py` (três rotas **declaradas antes** de `GET /api/carteira/{user_id}`, senão `certificados` vira `user_id`)
- Test: `tests/test_carteira_certificados.py` (fixtures `client`/`banco` como em `tests/test_pagina_carteiras.py`)

**Interfaces:**
- Consumes: `vigente`, `atribuir_carteira`, `PrazoInvalido`.
- Produces:
  - `cert_installer.vencimentos_por_documento() -> Dict[str, str]` — `documento → maior not_after` (ISO) de `cert_pfx_store`; falha devolve `{}`.
  - `GET /api/carteira/certificados?q=` → `{"total": int, "certificados": [{documento, documento_formatado, nome, tipo, vence_em, pessoas}]}`. Universo = `universo_de_documentos()` recortado por `_documentos_ao_alcance`, filtro `q` igual ao de `/api/carteira/documentos`. `tipo` = `"e-CNPJ"` se 14 dígitos, `"e-CPF"` se 11. `pessoas` = linhas **vigentes** do documento entre as pessoas que o ator pode gerir (Admin: todas).
  - `GET /api/carteira/certificados/{documento}` → `{documento, documento_formatado, nome, tipo, vence_em, pessoas: [{user_id, nome, email, origem, atribuido_por, atribuido_em, valido_desde, valido_ate, vigente}]}`. Só pessoas que o ator pode gerir (`cert_installer.pode_gerir`). Documento fora do alcance → 403.
  - `POST /api/carteira/certificados/{documento}/pessoas` body `{"user_ids": [str], "valido_desde": date|None, "valido_ate": date|None}` → confere `_exigir_alcance` para **todos** antes de gravar qualquer um, depois `_exigir_documentos_no_inventario` e `_exigir_documentos_ao_alcance`, depois para cada pessoa o mesmo caminho da rota `POST /api/carteira` (alvo Gestor = `remover_excecao`; senão `_desbloquear` + `atribuir_carteira` com o prazo). Devolve `{"status": "ok", "gravados": int}`. Extrair esse caminho da rota atual para `_atribuir_um(token, user_id, documentos, desde, ate) -> int` e usar nas duas rotas.
  - Mudar prazo = este mesmo POST com uma pessoa. Retirar = `DELETE /api/carteira/{user_id}/{documento}` existente.

- [ ] **Step 1: Failing tests**

```python
def test_lista_do_gestor_e_o_alcance_dele(client, banco): ...
def test_detalhe_mostra_so_quem_ele_gere(client, banco): ...
def test_detalhe_traz_prazo_e_inicio_futuro(client, banco): ...
def test_incluir_lote_com_prazo(client, banco): ...  # 2 pessoas, 30 dias -> 2 linhas manuais + 2 entradas no histórico
def test_lote_com_pessoa_fora_do_alcance_nao_grava_nada(client, banco):  # Review Focus 1
    # resposta 403; banco.carteira inalterada; banco.historico vazio
def test_prazo_de_701_dias_e_400(client, banco): ...
def test_rota_certificados_nao_e_capturada_por_user_id(client, banco): ...  # GET /api/carteira/certificados -> 200 com "certificados"
```

- [ ] **Step 2:** rodar → FAIL.
- [ ] **Step 3:** Implementar.
- [ ] **Step 4:** `pytest tests/test_carteira_certificados.py tests/test_pagina_carteiras.py tests/test_carteira.py -v` → PASS.
- [ ] **Step 5:** Commit `feat(carteira): rotas da aba Certificados`.

### Task 6: Tela — abas e aba Certificados

**Files:**
- Modify: `app/main.py` (`pagina_carteiras` ~:733: lê `?aba=` em `{"pessoas","certificados"}`, padrão `pessoas`, passa `aba` ao contexto)
- Modify: `templates/carteiras.html` (abas `.ag-abas` como em `templates/configuracao.html:42-48`; seção atual vira o painel `pessoas`; painel `certificados` novo; na lista "Na carteira" da aba Pessoas, linha manual com prazo mostra "até dd/mm/aaaa" e com início futuro "começa em dd/mm/aaaa")
- Create: `static/carteiras-certificados.js` (só a aba nova; incluído com cache-buster `?v=certificados-2026-11-13`)
- Test: `tests/test_carteiras_ui.py`

**Interfaces:**
- Consumes: rotas da Task 5, `GET /api/carteira/operadores` (escolha de pessoas), `DELETE /api/carteira/{user_id}/{documento}`.
- Comportamento (esboço aprovado, opção A, em `.superpowers/brainstorm/106-1794572502/content/aba-certificados.html`):
  - Esquerda: busca "Nome, CNPJ ou CPF"; cada linha: nome, `tipo · vence mm/aaaa · N pessoas`. `?certificado=<documento>` seleciona, como `?operador=` na aba Pessoas.
  - Direita: cabeçalho do certificado; botão "Incluir pessoas"; tabela Pessoa | Origem | ação. Origem: "Acessórias", "Planilha" ou "manual · por <email> · <dd/mm> · até <dd/mm/aaaa>|sem prazo". Linha manual tem "Alterar prazo" e "Retirar"; linha do Acessórias só "Retirar".
  - Modal "Incluir pessoas" (`dialog.ag-modal`, como `#modalImportar`): lista com busca e caixas de seleção (pessoas que ainda não têm o documento vigente); prazo em rádio "Sem prazo" / "Período" com dois `input type=date` — `min` = hoje, fim com `max` = início + 700 dias, recalculado ao mudar o início. "Alterar prazo" abre o mesmo modal só com o prazo.
  - Erros do servidor no `#cartMsg` existente; Gestor sem nada a gerir vê estado vazio.

- [ ] **Step 1: Failing tests** (estáticos, padrão de `tests/test_carteiras_ui.py`)

```python
def test_abas_pessoas_e_certificados(): ...  # HTML tem ag-abas com data-aba="pessoas" e "certificados", aria-controls
def test_pagina_aceita_aba(client): ...       # GET /carteiras?aba=certificados -> aria-selected="true" na aba certa; aba inválida cai em pessoas
def test_script_da_aba_carrega_com_cache_buster(): ...
def test_teto_de_700_dias_na_tela(): ...      # static/carteiras-certificados.js contém 700
```

- [ ] **Step 2:** rodar → FAIL.
- [ ] **Step 3:** Implementar.
- [ ] **Step 4:** `pytest tests/test_carteiras_ui.py tests/test_pagina_carteiras.py tests/test_altura_menu_e_carteiras.py -v` → PASS.
- [ ] **Step 5:** Conferir no navegador (prévia local como na memória `robot-cert-validacao-ui-no-navegador`): claro e escuro, 1366×657 e 390×700, axe sem erro novo, Gestor e Admin.
- [ ] **Step 6:** Commit `feat(carteira): aba Certificados`.

### Task 7: Fechamento

- [ ] **Step 1:** Suíte inteira: `pytest -q` → verde (base de 12/11: 2139 passed, 16 skipped).
- [ ] **Step 2:** Diff do ramo ao revisor independente; tratar achados.
- [ ] **Step 3:** Atualizar `projeto/04-Gestao.xlsx` (D-0144 e 6.4.2) com o commit. Push e deploy **só com autorização do Robério no chat**.
- [ ] **Step 4:** Depois do deploy: conferir a migration aplicada (`schema_migrations`) e `GET /carteiras?aba=certificados` em produção, só leitura.
