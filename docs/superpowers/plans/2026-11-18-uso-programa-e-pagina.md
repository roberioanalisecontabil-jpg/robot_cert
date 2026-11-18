# Uso dos certificados: programa e página — plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preencher a coluna Sistema/Página da aba Carteiras › Uso com o programa e o título da janela em foco no momento de cada uso, visível só para o admin.

**Architecture:** Na estação, um vigia SYSTEM residente (tarefa agendada nova) sobe um anotador SYSTEM em cada sessão interativa. O anotador grava a janela em foco num JSON lines na pasta trancada. A coleta SYSTEM que já existe (`estacao/uso.coletar`) junta até 3 janelas a cada evento 5061. No portal, uma tabela nova `uso_janela` é ligada a `uso_certificado`. A rota de listagem e uma rota de detalhe devolvem as janelas só ao admin.

**Tech Stack:** Python 3 (FastAPI, pydantic, pywin32, ctypes), PostgreSQL via `app/db_pg.py`, Inno Setup (`estacao_setup.iss`), PyInstaller (`CertguardAnalise.spec`), JS puro + Águia DS.

**Spec:** `docs/superpowers/specs/2026-11-18-uso-programa-e-pagina-design.md`

## Global Constraints

- O anotador confere a janela a cada **1 s** e grava só quando ela muda. A linha leva a hora em UTC, o processo sem caminho e sem `.exe`, e o título cortado em **300** caracteres.
- O programa vai cortado em **64** caracteres.
- A estação guarda o registro por **48 h**.
- Cada evento leva no máximo **3** janelas: a vigente no instante do evento (ordem 0) e até **2** anteriores dentro de **30 s** (ordem 1, 2).
- O registro fica sob `tarefa.pastas().raiz`, a pasta trancada para SYSTEM e Administradores por `atualizador.proteger_pasta`.
- A bandeja **não** anota janelas. O anotador e o vigia rodam como SYSTEM.
- Chave contra duplicação no portal: `uso_id` + `record_id` + `ordem` (revisão final de 18/11: o `record_id` recomeça quando o log de Segurança é limpo, e a chave por `machine_id` descartaria as janelas novas). Cada janela guarda também `evento_em`, a hora do uso.
- A guarda das janelas é a mesma do uso, `GUARDA` de 5 anos (`app/uso.py`). As janelas são apagadas junto com a linha de uso, por `ON DELETE CASCADE`.
- Janelas só para o papel `admin`, conferido no servidor. O gestor não recebe janela e não vê a coluna.
- Texto do aviso no detalhe: "É a janela que estava na tela no momento do uso. Um programa em segundo plano não aparece aqui."
- Sem aviso na bandeja e sem prazo menor para os títulos (decisões de 18/11).
- A migration só pelo deploy (`db/aplicar_schema.py`): só ASCII, sem BEGIN/COMMIT, idempotente.
- Todo dado vindo da estação é montado na tela com `textContent` e `createElement`, nunca com HTML em texto.
- Versão da estação: `1.5.0`. Ordem de entrega: portal primeiro, bandeja depois.
- Cada mudança no servidor ou publicação da bandeja só com autorização do Robério no chat.
- Commit: a correção e o `git commit -F` vão em comandos separados, porque o hook de pré-commit roda a suíte.

## Review Focus

1. **Uso sem janela anotada**: anotador recém-subido, sessão bloqueada ou arquivo apagado. O evento deve sair com `janelas: []` e a célula mostrar "—", sem erro na coleta.
2. **Reenvio do mesmo lote**, ou janela que chegou depois de a linha de uso já ter contado o evento. As janelas não podem duplicar nem se perder: são gravadas para **todos** os eventos do lote, não só para os novos.
3. **Título hostil**: quebra de linha, aspas, `<script>`, emoji, 10.000 caracteres. A linha do JSON lines continua íntegra, o título sai cortado em 300 e a tela mostra o texto como texto.
4. **Gestor chamando a rota de detalhe pelo id** de uma linha que ele vê. Deve dar 403.
5. **Anotador morto ou sessão que reabre**. O vigia relança na volta seguinte e nunca deixa dois anotadores na mesma sessão.

---

### Task 1: Prova do anotador SYSTEM na sessão (portão)

Descartável. Se falhar, **pare e volte ao Robério**, porque o design depende disso.

**Files:**
- Create: `C:\Users\Roberio\Desktop\prova-uso\prova-anotador.py` (fora do repo)
- Create: `C:\Users\Roberio\Desktop\prova-uso\prova-anotador.ps1` (só ASCII)

- [ ] **Step 1: Escrever o `prova-anotador.py`**, com dois modos:
  - `--vigia`: pega o token do próprio processo (`win32security.OpenProcessToken`) e faz `DuplicateTokenEx` (primário).
  - Para cada sessão `WTSActive`, faz `SetTokenInformation(tok, TokenSessionId, sessao)` e `CreateProcessAsUser` de `python prova-anotador.py --anotador`, com `lpDesktop = "winsta0\\default"`.
  - `--anotador`: durante 60 s grava em `C:\ProgramData\prova-anotador\<sessao>.jsonl` a hora UTC, o processo de `GetForegroundWindow` e o título, só quando mudam.
- [ ] **Step 2: Escrever o `prova-anotador.ps1`**. Ele cria uma tarefa de uma vez como SYSTEM (`schtasks /Create /RU SYSTEM /SC ONCE /ST 00:00 /F`) que roda `--vigia`, dispara com `/Run` e depois apaga a tarefa.
- [ ] **Step 3: Pedir ao Robério que rode o `.ps1` elevado na TI-002** e alterne entre Chrome e Acrobat por 1 minuto.
- [ ] **Step 4: Conferir.**
  - Passa se o `.jsonl` tem as trocas de janela com `chrome` e `Acrobat`, e se o `Get-Process -IncludeUserName` mostra o anotador como `NT AUTHORITY\SYSTEM` na sessão da pessoa.
  - Passa também se o Robério, sem elevação, não consegue `Stop-Process` no anotador.
  - Se algum item falhar, pare.

### Task 2: Registro local das janelas

**Files:**
- Create: `estacao/janelas.py`
- Test: `tests/test_estacao_janelas.py`

**Interfaces:**
- Produces:
  - `PASTA = "janelas"`, `GUARDA = timedelta(hours=48)`, `JANELA_ANTES = timedelta(seconds=30)`, `MAX_ANTERIORES = 2`, `MAX_TITULO = 300`, `MAX_PROGRAMA = 64`.
  - `arquivo(raiz: str, sid: str, quando: datetime) -> str`: devolve `<raiz>/janelas/<sid>/<AAAAMMDD UTC>.jsonl`. Um arquivo por dia evita reescrever o arquivo que o anotador está usando.
  - `anotar(raiz: str, sid: str, quando: datetime, programa: str, titulo: str) -> None`: acrescenta `{"t": iso UTC, "p": programa[:64], "j": titulo[:300]}` com `json.dumps(ensure_ascii=False)` e uma linha por chamada.
  - `podar(raiz: str, agora: datetime) -> int`: apaga os arquivos de dias inteiramente anteriores a `agora - GUARDA` e devolve quantos apagou.
  - `ler(raiz: str, sid: str, ate: datetime) -> list[dict]`: devolve as linhas do dia de `ate` e dos 2 dias anteriores, ordenadas por `t`. Linha corrompida, como a do meio de uma escrita, é ignorada.
  - `janelas_do_evento(linhas: list[dict], quando: datetime) -> list[dict]`: devolve `[{"quando","programa","titulo"}]`, com a vigente primeiro e até 2 anteriores em ordem decrescente.

- [ ] **Step 1: Escrever os testes que falham.**

```python
def test_vigente_e_duas_anteriores_dentro_de_30s(tmp_path):
    t0 = datetime(2026, 11, 18, 11, 17, 0, tzinfo=timezone.utc)
    for s, p, j in [(0, "outlook", "Caixa"), (10, "chrome", "eCAC - Centro Virtual de Atendimento"),
                    (40, "chrome", "gov.br - Acesse sua conta"), (50, "Acrobat", "Relatório")]:
        janelas.anotar(str(tmp_path), SID, t0 + timedelta(seconds=s), p, j)
    linhas = janelas.ler(str(tmp_path), SID, t0 + timedelta(seconds=44))
    r = janelas.janelas_do_evento(linhas, t0 + timedelta(seconds=44))
    assert [x["titulo"] for x in r] == ["gov.br - Acesse sua conta", "eCAC - Centro Virtual de Atendimento"]
    # "Caixa" (44 s antes) passou dos 30 s; "Relatório" é depois do evento

def test_sem_linha_antes_do_evento_devolve_vazio(tmp_path): ...  # == []
def test_titulo_hostil_fica_numa_linha_e_cortado(tmp_path):
    janelas.anotar(str(tmp_path), SID, T, "chrome", "a\nb\"<script>😀" + "x" * 10_000)
    [l] = janelas.ler(str(tmp_path), SID, T)
    assert len(l["j"]) == 300 and l["j"].startswith("a\nb\"<script>😀")
def test_linha_corrompida_e_ignorada(tmp_path): ...  # meia linha no fim do arquivo não derruba a leitura
def test_poda_apaga_so_dias_inteiros_fora_das_48h(tmp_path): ...
def test_evento_perto_da_meia_noite_le_o_dia_anterior(tmp_path): ...  # janela 23:59:50, evento 00:00:05 do dia seguinte
```

- [ ] **Step 2: Rodar** `pytest tests/test_estacao_janelas.py -v`. Esperado: FAIL na importação.
- [ ] **Step 3: Implementar `estacao/janelas.py`.** Cada `anotar` abre o arquivo em modo append, grava e fecha. Uma escrita cortada estraga só a última linha.
- [ ] **Step 4: Rodar de novo.** Esperado: PASS.
- [ ] **Step 5: Commit**, que leva junto o design. Crie o ramo `feat/uso-programa-pagina` antes.

```bash
git add estacao/janelas.py tests/test_estacao_janelas.py docs/superpowers/specs/2026-11-18-uso-programa-e-pagina-design.md docs/superpowers/plans/2026-11-18-uso-programa-e-pagina.md
git commit -F <arquivo-da-mensagem>
```

### Task 3: Anotador e vigia

**Files:**
- Create: `estacao/anotador.py`
- Modify: `estacao/__main__.py` (modos `--vigia` e `--anotador`; documentar na docstring)
- Modify: `CertguardAnalise.spec` (hiddenimports: `win32security`)
- Test: `tests/test_estacao_anotador.py`

**Interfaces:**
- Consumes: `janelas.anotar`, `janelas.podar`, `tarefa.pastas().raiz`, `tarefa.configurar_log`.
- Produces:
  - `janela_em_foco() -> tuple[str, str] | None`, com `(programa, titulo)`.
    - Usa ctypes: `GetForegroundWindow`, `GetWindowTextW`, `GetWindowThreadProcessId`, `OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION)` e `QueryFullProcessImageNameW`.
    - O programa é o nome base sem `.exe`. Devolve `None` sem janela, por exemplo com a sessão bloqueada.
  - `passo(estado: dict, agora: datetime, lida: tuple | None, gravar) -> None`: chama `gravar(agora, programa, titulo)` só quando `lida` difere de `estado["ultima"]`. `None` não grava, mas zera a última, para a mesma janela reaparecer depois do bloqueio.
  - `rodar_anotador(sid: str, dormir=time.sleep, ler=janela_em_foco, relogio=...) -> int`:
    - roda o laço a cada 1 s;
    - poda uma vez por hora;
    - tem mutex `Global\CertguardAnotador-<sessao>` e sai se ele já existir;
    - sai quando a própria sessão deixa de existir.
  - `sessoes_sem_anotador(sessoes: list[dict], vivos: dict[int, object]) -> list[int]`: devolve as sessões `WTSActive` sem processo vivo em `vivos`. `vivos` mapeia a sessão a um objeto com `.poll()` igual ao do `Popen`.
  - `lancar_na_sessao(sessao: int, exe: str) -> object | None`: duplica o token SYSTEM, ajusta o `TokenSessionId` e chama `CreateProcessAsUser(..., f'"{exe}" --anotador', lpDesktop="winsta0\\default")`. Pega o SID com `WTSQueryUserToken(sessao)` + `GetTokenInformation(TokenUser)`, passa no argumento `--sid`, e devolve o handle do processo. Reaproveite o molde de `estacao/sessoes._abrir_na_sessao`.
  - `rodar_vigia(intervalo=5) -> int`: mutex `Global\CertguardVigia`; a cada `intervalo` s, lança o anotador nas `sessoes_sem_anotador`.

- [ ] **Step 1: Escrever os testes que falham.** Use só as partes puras, sem Win32.

```python
def test_grava_so_quando_muda():
    gravadas, estado = [], {}
    for lida in [("chrome", "A"), ("chrome", "A"), ("chrome", "B"), None, ("chrome", "B")]:
        anotador.passo(estado, T, lida, lambda q, p, t: gravadas.append((p, t)))
    assert gravadas == [("chrome", "A"), ("chrome", "B"), ("chrome", "B")]

def test_vigia_lanca_so_onde_falta():
    vivo, morto = SimpleNamespace(poll=lambda: None), SimpleNamespace(poll=lambda: 1)
    sessoes = [{"SessionId": 1, "State": ACTIVE}, {"SessionId": 2, "State": ACTIVE},
               {"SessionId": 3, "State": ACTIVE}, {"SessionId": 4, "State": DISCONNECTED}]
    assert anotador.sessoes_sem_anotador(sessoes, {1: vivo, 2: morto}) == [2, 3]

def test_main_despacha_vigia_e_anotador(monkeypatch): ...  # --vigia chama rodar_vigia; --anotador --sid S chama rodar_anotador("S")
def test_spec_inclui_win32security(): ...
```

- [ ] **Step 2: Rodar** `pytest tests/test_estacao_anotador.py -v`. Esperado: FAIL.
- [ ] **Step 3: Implementar** `estacao/anotador.py` e os modos em `estacao/__main__.py`.
  - Os modos vêm antes do `bandeja.main()`.
  - Cada modo chama `tarefa.configurar_log` com seu arquivo: `vigia.log` e `anotador.log`.
  - O anotador não abre janela, não lê arquivo da pasta da pessoa e não recebe comando de fora.
- [ ] **Step 4: Rodar de novo.** Esperado: PASS.
- [ ] **Step 5: Commit.**

### Task 4: Tarefa do vigia, instalador e versão 1.5.0

**Files:**
- Modify: `estacao/tarefa.py` (`NOME_VIGIA`, criação da tarefa por XML, `/Run` do vigia em `rodar_tarefa`)
- Modify: `estacao_setup.iss` (`/Run` do vigia após instalar; `/Delete` na desinstalação)
- Modify: `estacao/__init__.py` (`VERSAO = "1.5.0"`)
- Test: `tests/test_estacao_atualizacao_automatica.py` (acrescentar)

**Interfaces:**
- Produces:
  - `NOME_VIGIA = NOME_TAREFA.replace("atualizacao", "vigia")`, isto é, `"Certguard Analise - vigia"`.
  - `xml_do_vigia(exe: str) -> str`, com:
    - gatilho `BootTrigger`;
    - `UserId` `S-1-5-18` e `RunLevel` `HighestAvailable`;
    - `ExecutionTimeLimit` `PT0S` (o `schtasks` sem XML mata em 72 h);
    - `MultipleInstancesPolicy` `IgnoreNew`;
    - `RestartOnFailure` de 1 min, 999 vezes;
    - `DisallowStartIfOnBatteries` e `StopIfGoingOnBatteries` `false`;
    - ação `"<exe>" --vigia`.
  - `comandos_das_tarefas(exe)` passa a devolver também a criação do vigia: grava o XML num temporário dentro de `pastas().raiz` e roda `schtasks /Create /F /TN <NOME_VIGIA> /XML <arquivo>`.
  - `rodar_tarefa()` roda `schtasks /Run /TN <NOME_VIGIA>` a cada rodada. Isso conserta a tarefa parada por alguém; com `IgnoreNew`, não duplica.

- [ ] **Step 1: Escrever os testes que falham.**

```python
def test_xml_do_vigia_sem_limite_e_sem_duplicar():
    x = tarefa.xml_do_vigia(r"C:\Program Files\CertGuard\certguard_analise.exe")
    for trecho in ("<ExecutionTimeLimit>PT0S</ExecutionTimeLimit>", "<MultipleInstancesPolicy>IgnoreNew",
                   "<UserId>S-1-5-18</UserId>", "<BootTrigger>", "--vigia", "<RestartOnFailure>"):
        assert trecho in x

def test_preparar_cria_tambem_o_vigia(...): ...  # entre os comandos há /Create /TN "Certguard Analise - vigia" /XML
def test_rodada_da_tarefa_religa_o_vigia(...): ...  # rodar_tarefa executa schtasks /Run /TN "Certguard Analise - vigia"
def test_instalador_liga_e_desliga_o_vigia():
    iss = (RAIZ / "estacao_setup.iss").read_text(encoding="utf-8")
    assert "Certguard Analise - vigia" in iss and iss.count("vigia") >= 2
def test_versao_1_5_0(): ...
```

- [ ] **Step 2: Rodar** `pytest tests/test_estacao_atualizacao_automatica.py -v`. Esperado: FAIL nos novos.
- [ ] **Step 3: Implementar.**
  - O XML vai em UTF-16, que é o que o `schtasks /XML` espera.
  - No `.iss`, depois do `/Run` da atualização, vem o `/Run` do vigia. Na desinstalação, um `/End` e um `/Delete` do vigia. O `FecharBandejas` (`taskkill /IM certguard_analise.exe`) já mata o vigia e os anotadores antes de trocar o exe.
- [ ] **Step 4: Rodar a suíte da estação:** `pytest tests -k estacao -q`. Esperado: PASS.
- [ ] **Step 5: Commit.**

### Task 5: A coleta manda as janelas

**Files:**
- Modify: `estacao/uso.py` (`coletar`)
- Test: `tests/test_estacao_uso.py` (acrescentar)

**Interfaces:**
- Consumes: `janelas.ler`, `janelas.janelas_do_evento`, `tarefa.pastas().raiz`.
- Produces: cada evento do lote ganha `"janelas": [{"quando": iso, "programa": str, "titulo": str}]`, que pode vir vazio.

- [ ] **Step 1: Escrever os testes que falham.**

```python
def test_evento_leva_as_janelas_do_sid(...):
    # registro com chrome "eCAC" 5 s antes do evento do SID S-1-5-21-1
    lote = http.posts[0][1]["eventos"]
    assert lote[0]["janelas"][0] == {"quando": ..., "programa": "chrome", "titulo": "eCAC"}

def test_sem_registro_vai_lista_vazia_e_nao_quebra(...): ...  # janelas == [] e o marcador avança
def test_erro_lendo_janelas_nao_impede_a_coleta(...): ...  # monkeypatch janelas.ler para levantar OSError -> janelas == []
```

- [ ] **Step 2: Rodar** `pytest tests/test_estacao_uso.py -v`. Esperado: FAIL.
- [ ] **Step 3: Implementar.** Leia o registro uma vez por SID no lote (`ate` = maior `quando` do SID) e guarde num dicionário. Em qualquer erro, use `[]`.
- [ ] **Step 4: Rodar de novo.** Esperado: PASS.
- [ ] **Step 5: Commit.**

### Task 6: Portal grava as janelas

**Files:**
- Create: `supabase/migrations/20261118100000_uso_janela.sql`
- Modify: `app/rotas/uso_estacao.py` (modelo `JanelaDeUso`, campo `janelas` em `EventoDeUso`)
- Modify: `app/uso.py` (`Evento.janelas`, gravação em `registrar_usos`; corrigir a docstring "nunca qual programa ou site")
- Test: `tests/test_migration_uso_janela.py`, `tests/test_uso_dominio.py`, `tests/test_uso_rotas.py` (acrescentar)

**Interfaces:**
- Produces:
  - Tabela `uso_janela`: `id bigserial PK`, `uso_id bigint NOT NULL REFERENCES uso_certificado(id) ON DELETE CASCADE`, `machine_id text NOT NULL`, `record_id bigint NOT NULL`, `ordem smallint NOT NULL CHECK (ordem BETWEEN 0 AND 2)`, `quando timestamptz NOT NULL`, `programa text NOT NULL`, `titulo text NOT NULL`, `UNIQUE (machine_id, record_id, ordem)`, mais índice `(uso_id, record_id)`.
  - `JanelaDeUso`: `quando: datetime`, `programa: str` com `max_length=64`, `titulo: str` com `max_length=300`.
  - `EventoDeUso.janelas: List[JanelaDeUso] = Field(default_factory=list, max_length=3)`.
  - `Evento.janelas: List[dict] = field(default_factory=list)`, com `quando`, `programa` e `titulo`.
  - `registrar_usos` grava as janelas de **todos** os eventos do grupo, inclusive os já contados. Faz `upsert(..., on_conflict="machine_id,record_id,ordem", ignore_duplicates=True)` com o `uso_id` da linha: `atual["id"]` ou o `id` que volta do upsert da linha.

- [ ] **Step 1: Escrever os testes que falham.**

```python
def test_migration_uso_janela():  # no molde de test_migration_uso_certificado.py
    sql = ...
    assert "ON DELETE CASCADE" in sql and "UNIQUE (machine_id, record_id, ordem)" in sql
    assert "CREATE TABLE IF NOT EXISTS public.uso_janela" in sql and sql.isascii()

def test_janelas_gravadas_com_a_ordem(banco): ...  # 1 evento com 2 janelas -> 2 linhas, ordem 0 e 1, uso_id da linha
def test_reenvio_nao_duplica_janelas(banco): ...  # mesmo lote 2x -> ainda 2 linhas
def test_janela_de_evento_ja_contado_e_gravada(banco): ...  # 1º envio sem janelas, 2º com -> quantidade não muda, janelas entram
def test_guarda_apaga_as_janelas_junto(): ...  # o cascade está na migration (o _Fake não faz FK)
def test_rota_aceita_lote_sem_janelas_e_recusa_4(client, banco): ...  # sem campo -> 200; 4 janelas -> 422; título 301 -> 422
```

- [ ] **Step 2: Rodar** `pytest tests/test_migration_uso_janela.py tests/test_uso_dominio.py tests/test_uso_rotas.py -v`. Esperado: FAIL nos novos.
- [ ] **Step 3: Implementar.** Se o `_Fake` de `tests/test_seguranca_lote1.py` não devolver a linha no `upsert`, leia o `id` com um `select` logo depois, nos dois caminhos.
- [ ] **Step 4: Rodar de novo.** Esperado: PASS.
- [ ] **Step 5: Commit.**

### Task 7: Rotas de leitura, só para o admin

**Files:**
- Modify: `app/rotas/carteiras.py` (`listar_uso`; rota nova `GET /api/carteira/uso/{uso_id}/janelas`, antes de `/api/carteira/{user_id}`)
- Test: `tests/test_uso_tela.py` (acrescentar)

**Interfaces:**
- Produces:
  - A resposta de `listar_uso` ganha `"mostra_sistema": bool`, verdadeiro só para o admin.
  - Só para o admin, cada linha ganha `"id"`, `"sistema": "<programa> · <titulo>" | ""` e `"outras": int`.
    - `sistema` vem da janela de ordem 0 do maior `record_id` da linha.
    - `outras` é o número de pares `(programa, titulo)` distintos entre as janelas de ordem 0 da linha, menos 1.
    - Leia `uso_janela` com um único `in_("uso_id", ids da página)`.
  - Para o gestor, as linhas saem **sem** as chaves `id`, `sistema` e `outras`.
  - `GET /api/carteira/uso/{uso_id}/janelas`:
    - usa `require_admin`;
    - devolve `{"usos": [{"record_id", "janelas": [{"ordem","quando","programa","titulo"}]}]}` em ordem de `record_id`;
    - devolve 404 se a linha não existe e 503 com o banco fora.

- [ ] **Step 1: Escrever os testes que falham.**

```python
def test_admin_recebe_sistema_e_outras(client, banco): ...  # 2 usos, títulos diferentes -> sistema do último, outras == 1
def test_gestor_nao_recebe_janela_nem_id(client, banco):
    j = client.get("/api/carteira/uso", headers=_gestor()).json()
    assert j["mostra_sistema"] is False
    assert all(not ({"id", "sistema", "outras"} & set(l)) for l in j["linhas"])
def test_detalhe_so_admin(client, banco):
    assert client.get("/api/carteira/uso/1/janelas", headers=_gestor()).status_code == 403
    assert client.get("/api/carteira/uso/1/janelas", headers=_admin()).status_code == 200
def test_detalhe_inexistente_404(client, banco): ...
def test_linha_sem_janela_sai_vazia(client, banco): ...  # sistema == "" e outras == 0
```

- [ ] **Step 2: Rodar** `pytest tests/test_uso_tela.py -v`. Esperado: FAIL nos novos.
- [ ] **Step 3: Implementar.**
- [ ] **Step 4: Rodar de novo.** Esperado: PASS.
- [ ] **Step 5: Commit.**

### Task 8: A tela

**Files:**
- Modify: `static/carteiras-uso.js`
- Modify: `templates/carteiras.html` (`th` da coluna com `id="uso-th-sistema"`, `<dialog class="ag-modal" id="modalUsoJanelas">` no molde do `modalAcess`, cache-buster do JS)
- Modify: `static/aguia-carteiras.css` se precisar, e então subir o `?v=` nos três lugares que o testam (`templates/carteiras.html`, `tests/test_acessorias.py`, `tests/test_ajustes_ui_30_09.py`)
- Test: `tests/test_uso_tela.py` (acrescentar)

**Interfaces:**
- Consumes: `mostra_sistema`, `linhas[].id`, `linhas[].sistema`, `linhas[].outras`, `GET /api/carteira/uso/{id}/janelas`.

O comportamento da tela:
- Com `mostra_sistema` falso, o `th` e a célula não aparecem, e o `colSpan` da mensagem vira 5.
- Com verdadeiro, a célula mostra:
  - um `<button class="ag-btn ag-btn--ghost">` com `sistema` e, se `outras > 0`, o texto ` +N`;
  - "—" quando `sistema` está vazio.
- O botão abre o `modalUsoJanelas`. O modal tem a hora de cada uso, a lista das janelas (ordem 0 primeiro, marcada "no momento") e o aviso exato das Global Constraints.

- [ ] **Step 1: Escrever os testes que falham.** São textuais, no estilo de `test_js_nunca_monta_html_com_dado_da_estacao`.

```python
def test_js_mostra_sistema_e_abre_detalhe():
    js = (RAIZ / "static" / "carteiras-uso.js").read_text(encoding="utf-8")
    assert "mostra_sistema" in js and "/janelas" in js and "modalUsoJanelas" in js
    assert "innerHTML" not in js and "cg-uso-futuro" not in js
def test_modal_tem_o_aviso():
    html = (RAIZ / "templates" / "carteiras.html").read_text(encoding="utf-8")
    assert "É a janela que estava na tela no momento do uso. Um programa em segundo plano não aparece aqui." in html
    assert 'id="modalUsoJanelas"' in html and 'id="uso-th-sistema"' in html
def test_cache_buster_do_js_subiu(): ...  # carteiras-uso.js?v=janelas-2026-11-18
```

- [ ] **Step 2: Rodar** `pytest tests/test_uso_tela.py -v`. Esperado: FAIL.
- [ ] **Step 3: Implementar.**
- [ ] **Step 4: Rodar a suíte toda** com `pytest -q`. Esperado: PASS.
- [ ] **Step 5: Conferir no navegador, localmente,** com dados de mentira: a célula, o "+N", o modal no tema claro e no escuro, a largura de 390 px e o gestor sem a coluna. Use `robot-cert-validacao-ui-no-navegador` da memória.
- [ ] **Step 6: Commit.**

### Task 9: Entrega

Cada passo no servidor e a publicação da bandeja **só com a autorização do Robério no chat**.

- [ ] **Step 1: Revisão independente do ramo inteiro**, antes do push.
- [ ] **Step 2: Push, PR e merge** do `feat/uso-programa-pagina`.
- [ ] **Step 3: Deploy do portal** com `C:\Apps\deploy\atualizar-portal.ps1 -Portal robot_cert`.
  - Conferir `git -C C:\Apps\robot_cert log --oneline -1`.
  - Conferir a tabela `uso_janela` criada.
  - Conferir que a aba Uso segue igual, com "—" para o admin.
- [ ] **Step 4: Gerar a bandeja 1.5.0** (PyInstaller + Inno Setup) e instalar na TI-002.
  - Conferir no `vigia.log` e no `Get-Process -IncludeUserName`: um anotador SYSTEM por sessão.
  - Fazer um uso no e-CAC e um no Acrobat e rodar a tarefa (`schtasks /Run`).
  - A coluna deve mostrar `chrome · …` e `Acrobat · …`.
  - Conferir também: tela bloqueada, logoff e novo logon, troca rápida de usuário. Sem administrador, `Stop-Process` no anotador deve dar "Acesso negado".
  - Contar as pastas `_MEI*` em `C:\Windows\SystemTemp` e `C:\Windows\Temp` depois de 3 reinícios. Se crescerem, limpar as velhas na subida do vigia ou gerar o exe em onedir.
- [ ] **Step 5: Publicar a 1.5.0** com `lancar-certguard.ps1`.
- [ ] **Step 6: Atualizar a memória** `robot-cert-carteira-certificados.md`.
