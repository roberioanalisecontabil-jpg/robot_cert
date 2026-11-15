# Registro de uso dos certificados (Frente C) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** registrar no portal quem usou qual certificado, em qual máquina e quando, a partir dos eventos 5061 do Windows, e mostrar isso numa aba "Uso" em Carteiras.

**Architecture:**
- **Tarefa SYSTEM:** a que já existe (`estacao/tarefa.py`) passa a ligar a auditoria. Ela lê os 5061 novos do log de Segurança e os manda à rota nova `/api/estacao/uso` com a chave da máquina.
- **Bandeja:** na conferência da Frente B, passa a mandar o SID do usuário e o contêiner da chave de cada certificado. O contêiner é lido sem abrir a chave.
- **Portal:**
  - guarda o mapa (máquina, SID, contêiner) → certificado e pessoa;
  - agrupa os usos por hora de Brasília;
  - resolve cada linha pelo mapa;
  - mostra a aba com o recorte de Admin e Gestor.

**Tech Stack:** FastAPI, PostgreSQL 17 (`app/db_pg.py`, API estilo Supabase), Jinja + JS sem framework (Águia DS), bandeja Python congelada pelo PyInstaller, PowerShell 5.1 e `ctypes` (crypt32) na estação, pytest.

**Spec:** `docs/superpowers/specs/2026-11-13-carteira-certificados-remocao-uso-design.md`, seção "Frente C — registro de uso".

## Global Constraints

- **Público:** o registro diz **que** o certificado foi usado, **quando** e **por quem**. Não tem programa nem site.
- **O que coleta:**
  - só o evento **5061**, do provedor `Microsoft Software Key Storage Provider`, com `ReturnCode` `0x0`;
  - o 5058 não entra.
- **Auditoria:**
  - subcategoria "Other System Events" pelo GUID `{0CCE9214-69AE-11D9-BED3-505054503030}`, com `/success:enable /failure:enable`;
  - nunca pelo nome, porque o Windows está em pt-BR.
- **Primeira coleta de uma máquina:** os últimos **7 dias**.
- **Hora cheia:** horário de Brasília, com deslocamento fixo de **-03:00**. O Brasil não tem horário de verão desde 2019.
- **Guarda:**
  - uso resolvido: **5 anos**, e depois é apagado;
  - uso que não vira certificado do acervo em **30 dias**: apagado.
- **Quem vê:**
  - Admin vê tudo;
  - Gestor vê só as pessoas dos departamentos que lidera (`cert_installer.departamentos_que_lidera`);
  - Operador não vê;
  - usos de perfil sem login aparecem só para o Admin;
  - só o Admin exporta (fora do escopo desta leva: não há exportação; o Admin usa a tela).
- **Chave da máquina:** a rota nova exige `computadores._maquina_provada`, como `/api/estacao/atualizacao/evento`.
- **Ler o contêiner da chave nunca abre a chave privada.** Abrir gera um 5058/5061 falso a cada conferência. Achado em 15/11: o `certutil -user -store My` abriu chaves às 13:03.
- **Falhas não se contaminam:**
  - erro no mapa de uso não derruba a conferência da remoção;
  - erro na coleta não impede a atualização automática;
  - erro na atualização automática não impede a coleta.
- **Projeto:**
  - arquivos `.ps1` só em ASCII;
  - migration em `supabase/migrations/`, idempotente, aplicada pelo deploy;
  - nunca mandar ninguém rodar `.sql` à mão;
  - textos da tela em pt-BR;
  - commit com `git commit -F`.

## Review Focus

1. **Log de Segurança limpo ou sobrescrito.** O `EventRecordID` recomeça abaixo do marcador. A coleta deve voltar a 7 dias, sem ficar muda para sempre (teste na Task 5).
2. **Mesma hora mandada duas vezes.** Duas rodadas com eventos da mesma hora somam a quantidade e não duplicam a linha. Reenviar os mesmos `record_id` não soma de novo (teste na Task 2).
3. **Uso que chega antes do mapa.** Ele fica sem pessoa e sem certificado e ganha os dois na primeira conferência daquele perfil (teste na Task 2).
4. **Gestor não vê ninguém de fora.** Nem pela URL com `user_id` de outro departamento, nem usos de perfil sem login (teste na Task 6).
5. **Mapa falhando não para a remoção.** Com `uso.registrar_mapa` levantando erro, a conferência responde 200 com as listas da remoção (teste na Task 3).

---

### Task 1: Migration das três tabelas

**Files:**
- Create: `supabase/migrations/20261115100000_uso_certificado.sql`
- Test: `tests/test_migration_uso_certificado.py`, no estilo de `tests/test_migration_remocao_estacao.py`

**Interfaces:**
- Produces:
  - `public.uso_conteiner` (machine_id text, sid text, conteiner text, fingerprint char(64), usuario_windows text, user_id uuid NULL REFERENCES public.users(id) ON DELETE SET NULL, atualizado_em timestamptz), UNIQUE (machine_id, sid, conteiner);
  - `public.uso_certificado` (id bigserial, machine_id, sid, usuario_windows, conteiner, hora timestamptz [início da hora de Brasília], primeiro_em, ultimo_em timestamptz, quantidade int NOT NULL, ultimo_record bigint NOT NULL, fingerprint char(64) NULL, documento text NULL, user_id uuid NULL REFERENCES public.users(id) ON DELETE SET NULL, recebido_em timestamptz DEFAULT now()), UNIQUE (machine_id, sid, conteiner, hora), índices em (hora DESC), (user_id, hora DESC) e (documento, hora DESC);
  - `public.uso_coleta` (machine_id text PRIMARY KEY, ultima_em timestamptz NOT NULL, auditoria text NOT NULL CHECK (auditoria IN ('ligada','desligada','desconhecida'))).

- [ ] **Step 1: Teste.** `test_tabelas_e_restricoes` lê o SQL e verifica:
  - os três `CREATE TABLE IF NOT EXISTS`;
  - o `UNIQUE (machine_id, sid, conteiner, hora)`;
  - o `CHECK` da auditoria;
  - o `REFERENCES public.users(id)`;
  - o cabeçalho "NAO rode a mao".

  `test_nome_segue_a_ordem` verifica que o arquivo ordena depois de `20261114110000_remocao_modos.sql`.
- [ ] **Step 2:** `pytest tests/test_migration_uso_certificado.py -q`. Esperado: FAIL, porque o arquivo não existe.
- [ ] **Step 3:** escrever a migration, com o cabeçalho no formato de `20261114100000_remocao_estacao.sql`.
- [ ] **Step 4:** rodar de novo. Esperado: PASS.
- [ ] **Step 5:** commit `feat(uso): tabelas do registro de uso dos certificados`.

### Task 2: Domínio do portal, `app/uso.py`

**Files:**
- Create: `app/uso.py`
- Test: `tests/test_uso_dominio.py`, com o `_Fake` de `tests/test_seguranca_lote1.py`, que conta as consultas em `fake.consultas`

**Interfaces:**
- Consumes:
  - `remocao.do_acervo(fps) -> {fp: documento}`;
  - `computadores.mac(machine_id)`;
  - `ci._banco()`.
- Produces:
  - `BRASILIA = timezone(timedelta(hours=-3))`, com o comentário `shortcut:` sobre o horário de verão;
  - `GUARDA = timedelta(days=5*365)` e `PENDENTE = timedelta(days=30)`;
  - `hora_de(quando: datetime) -> datetime`: o início da hora de Brasília, como datetime com fuso;
  - `registrar_mapa(machine_id: str, sid: str, usuario_windows: str, user_id: Optional[str], conteineres: Dict[str, str], agora: datetime) -> int`:
    - `conteineres` mapeia contêiner para fingerprint;
    - grava `uso_conteiner` por upsert;
    - depois resolve as linhas de `uso_certificado` da máquina e do SID que estão com `fingerprint` nulo e cujo contêiner apareceu no mapa, preenchendo `fingerprint`, `documento` (pelo `do_acervo`) e `user_id`;
    - devolve quantas linhas resolveu;
  - `registrar_usos(machine_id: str, eventos: List[Evento], auditoria: str, agora: datetime) -> int`:
    - `Evento` é uma dataclass com `record_id: int`, `quando: datetime` (UTC), `sid: str`, `usuario: str` e `conteiner: str`;
    - agrupa por (sid, contêiner, `hora_de(quando)`) e soma na linha existente: `quantidade` cresce, `primeiro_em` fica com o mínimo, `ultimo_em` com o máximo;
    - **ignora** eventos com `record_id <= ultimo_record` da linha, para que o reenvio não some de novo;
    - resolve pelo `uso_conteiner` já gravado;
    - grava `uso_coleta`;
    - devolve quantas linhas gravou;
  - `limpar(agora: datetime) -> None`: apaga uso com `hora < agora - GUARDA`, e uso com `fingerprint` nulo e `recebido_em < agora - PENDENTE`.
- Um fingerprint fora do acervo (`do_acervo` sem ele) conta como não resolvido.

- [ ] **Step 1: Testes.**
  - `test_hora_de_brasilia`: `hora_de(datetime(2026,11,15,16,6,51,tzinfo=UTC)) == datetime(2026,11,15,13,0,tzinfo=BRASILIA)`.
  - `test_mesma_hora_soma_e_nao_duplica`: dois envios na mesma hora, com `record_id` 10 e 11 e depois 12, dão uma linha com `quantidade == 3`.
  - `test_reenvio_nao_soma`: mandar de novo o `record_id` 11 mantém a quantidade.
  - `test_uso_antes_do_mapa_resolve_depois`: o uso fica com `fingerprint is None`. Depois de `registrar_mapa`, a mesma linha tem fingerprint, documento e `user_id`, e a função devolve 1.
  - `test_conteiner_fora_do_acervo_fica_pendente_e_some_em_30_dias`.
  - `test_guarda_de_5_anos`.
  - `test_coleta_grava_auditoria`: `uso_coleta` fica com `auditoria == "desligada"` quando é isso que foi mandado.
- [ ] **Step 2:** `pytest tests/test_uso_dominio.py -q`. Esperado: FAIL na importação.
- [ ] **Step 3:** implementar, ler e gravar pela API de tabela (`client.table(...)`), sem SQL cru, para o `_Fake` cobrir.
  - Leitura e escrita sem trava são aceitáveis: um coletor por máquina, protegido pelo `_unica()` da tarefa. Comentar com `shortcut:`.
- [ ] **Step 4:** rodar de novo. Esperado: PASS.
- [ ] **Step 5:** commit `feat(uso): agrupamento por hora, mapa contêiner->certificado e guarda`.

### Task 3: Rotas da estação, `POST /api/estacao/uso` e conferência com mapa

**Files:**
- Create: `app/rotas/uso_estacao.py`, registrada em `app/main.py` como as outras rotas de `app/rotas`
- Modify: `app/rotas/remocao.py`
  - acrescentar ao modelo `Conferencia` os campos `sid` (str, 0 a 184) e `conteineres` (dict str → Fingerprint, até 500, com padrão vazio);
  - chamar o mapa dentro de `_conferir`.
- Test: `tests/test_uso_rotas.py`; `tests/test_remocao_rotas.py` continua passando sem mudar os casos existentes.

**Interfaces:**
- Consumes:
  - `uso.registrar_usos`, `uso.registrar_mapa`, `uso.limpar` (Task 2);
  - `computadores._maquina_provada`, `computadores.hash_da_chave`;
  - `_limitar` de `app/rotas/atualizacao.py` (importar, não copiar);
  - `alert_state.job_ja_executado_recentemente` não serve, porque é de outro job. Usar um marcador próprio em memória do processo: `limpar` roda no máximo uma vez a cada 24 h.
- Produces:
  - `POST /api/estacao/uso`, com corpo `{machine_id, chave, auditoria: "ligada"|"desligada"|"desconhecida", eventos: [{record_id, quando, sid, usuario, conteiner}] (max 2000)}` e resposta `{"ok": true, "gravadas": n}`;
  - teto `_TETO_USO = (30, 600)`;
  - chave errada → 403; banco fora → 503.

- [ ] **Step 1: Testes.**
  - `test_uso_exige_chave_da_maquina` → 403.
  - `test_uso_grava_e_responde_contagem`.
  - `test_lote_acima_de_2000_recusado` → 422.
  - `test_conferencia_grava_mapa_com_remocao_desligada`: com o modo desligado, `registrar_mapa` é chamado com o `sid` e os `conteineres` do corpo.
  - `test_mapa_falhando_nao_derruba_conferencia`: com `registrar_mapa` levantando erro, a resposta é 200 com `remover` e `avisos`.
  - `test_conferencia_antiga_sem_sid_continua_valendo`: o corpo da 1.3.1, sem `sid` e `conteineres`, responde 200 e não chama o mapa.
- [ ] **Step 2:** rodar. Esperado: FAIL.
- [ ] **Step 3:** implementar.
  - Em `_conferir`, o mapa vai **antes** do `try` da remoção, num `try` próprio que só registra a falha no log.
  - Só chama o mapa quando `corpo.sid` vem preenchido.
  - O `user_id` vem do `user` (é `None` na rota sem conta).
- [ ] **Step 4:** `pytest tests/test_uso_rotas.py tests/test_remocao_rotas.py -q`. Esperado: PASS.
- [ ] **Step 5:** commit `feat(uso): rota de coleta com chave da maquina e mapa na conferencia`.

### Task 4: Bandeja, contêiner e SID na conferência

**Files:**
- Create: `estacao/conteineres.py`
- Modify: `estacao/conferencia.py`, que monta o `corpo` perto da linha 54; `CertguardAnalise.spec` (hiddenimports); `estacao_setup.iss`, se a lista de módulos estiver lá
- Test: `tests/test_estacao_conteineres.py`; `tests/test_estacao_conferencia.py`

**Interfaces:**
- Produces:
  - `conteineres() -> Dict[str, str]`: mapa de sha256 do DER (minúsculo) para o nome do contêiner, com os certificados de `CurrentUser\My` que têm a propriedade `CERT_KEY_PROV_INFO_PROP_ID` (2). Qualquer falha devolve `{}` e registra no log;
  - `sid_atual() -> str`: o SID do token do processo, ou `""` em caso de falha.
- O corpo da conferência ganha `"sid"` e `"conteineres"`, este restrito aos sha256 que já vão em `certificados`.

- [ ] **Step 1: Testes.**
  - `test_conferencia_manda_sid_e_conteineres`: com `conteineres` e `sid_atual` substituídos por versões falsas, o corpo postado traz os dois, e o mapa só tem chaves que estão em `certificados`.
  - `test_falha_nos_conteineres_nao_impede_conferencia`: `conteineres` devolvendo `{}` faz o corpo sair com `"conteineres": {}`.
  - `@so_windows test_conteineres_le_o_repositorio_real`: devolve um dict cujas chaves são sha256 de 64 caracteres hexadecimais. Rodado nesta máquina, ele lê os certificados de verdade sem abrir chave.
- [ ] **Step 2:** rodar. Esperado: FAIL.
- [ ] **Step 3:** implementar.
  - `conteineres`: `ctypes` com crypt32 (`CertOpenSystemStoreW(0, "MY")`, `CertEnumCertificatesInStore`, `CertGetCertificateContextProperty(ctx, 2, ...)`), lendo `pwszContainerName` de `CRYPT_KEY_PROV_INFO` e o sha256 de `pbCertEncoded`/`cbCertEncoded`.
    - **Proibido:** `CryptAcquireCertificatePrivateKey`, `PrivateKey`, `GetRSAPrivateKey` e `certutil`. Os quatro abrem a chave.
  - `sid_atual`: `ctypes` com `OpenProcessToken` + `GetTokenInformation(TokenUser)` + `ConvertSidToStringSidW`.
- [ ] **Step 4:** rodar. Esperado: PASS.
- [ ] **Step 5: Verificação manual nesta máquina, que tem a auditoria ligada.**
  - Rodar `python -c "from estacao import conteineres as c; print(len(c.conteineres()))"`.
  - Conferir com `Get-WinEvent` que **não** apareceu nenhum 5058/5061 novo nos 2 minutos seguintes. Esse comando exige admin, então o usuário roda `C:\Users\Roberio\Desktop\prova-uso\prova-uso.ps1 -Coletar -MinutosAntes 0` e mostra a saída.
  - Se apareceu evento, a Task para: o método abriu a chave.
- [ ] **Step 6:** commit `feat(estacao): conferencia manda SID e conteiner da chave sem abrir a chave`.

### Task 5: Coletor na tarefa SYSTEM

**Files:**
- Create: `estacao/uso.py`
- Modify:
  - `estacao/tarefa.py`, `rodar_tarefa`: a coleta vai depois do `_unica()` e antes do `buscar_pacote`, em `try` próprio, só quando `e_estacao()`;
  - `estacao/__init__.py`: `VERSAO = "1.4.0"`;
  - `estacao_setup.iss`: `MyAppVersion "1.4.0"`;
  - os testes que fixam a versão: `tests/test_estacao_conferencia.py::test_versao_1_3_1`, que passa a `test_versao_1_4_0`, e `tests/test_janela_login.py::test_versao_reportada_e_a_nova`.
- Test: `tests/test_estacao_uso.py`

**Interfaces:**
- Consumes: a rota `POST /api/estacao/uso` (Task 3); `chave_maquina.ler()`; `bandeja.machine_id()`; `tarefa.portal()`.
- Produces:
  - `MARCADOR = pastas raiz / "uso-marcador.json"`, no formato `{"record_id": int}`, na pasta de ProgramData que a tarefa já usa;
  - `ligar_auditoria(executar) -> str`: roda o `auditpol /set` com o GUID e depois o `auditpol /get /subcategory:<GUID> /r`. Lê a 5ª coluna do CSV **por posição**, porque o nome da coluna vem traduzido. A saída é `"ligada"` se a configuração não estiver vazia nem indicar "sem auditoria" (`No Auditing`/`Sem Auditoria`), `"desligada"` no caso contrário, e `"desconhecida"` em erro;
  - `ler_eventos(desde_record: int, executar) -> List[dict]`: PowerShell `Get-WinEvent -FilterXPath` com `EventID=5061` e `EventRecordID > desde_record`. Quando `desde_record == 0`, filtra por `TimeCreated` dos últimos 7 dias. Só fica o que tem `ProviderName == "Microsoft Software Key Storage Provider"` e `ReturnCode == "0x0"`. A saída é JSON com `record_id`, `quando` (ISO em UTC), `sid`, `usuario` e `conteiner`;
  - `coletar(http, executar=_powershell) -> int`:
    - liga a auditoria e lê o marcador;
    - **se o maior `EventRecordID` atual do log for menor que o marcador, zera o marcador** (o log foi limpo);
    - lê os eventos e manda em lotes de 2000;
    - grava o marcador com o maior `record_id` aceito **depois** de cada 200;
    - devolve o total enviado.

- [ ] **Step 1: Testes**, com executor e http falsos no estilo de `tests/test_estacao_conferencia.py`:
  - `test_liga_auditoria_pelo_guid`: o comando contém `{0CCE9214-69AE-11D9-BED3-505054503030}` e não contém "Other System Events".
  - `test_auditoria_lida_por_posicao_em_portugues`: uma saída com os cabeçalhos em português e "Êxito e Falha" dá `"ligada"`.
  - `test_so_avanca_marcador_depois_do_200`: com o portal respondendo 503, o marcador não muda.
  - `test_lotes_de_2000`: 4500 eventos viram 3 POSTs.
  - `test_log_limpo_volta_a_7_dias`: com o marcador em 9000 e o log no máximo em 120, a leitura sai com `desde_record == 0`.
  - `test_falha_na_coleta_nao_impede_atualizacao`: em `rodar_tarefa`, com `coletar` levantando erro, o `buscar_pacote` ainda é chamado.
  - `test_atualizacao_fora_nao_impede_coleta`: com `buscar_pacote` levantando erro, `coletar` já foi chamado.
  - `test_nao_estacao_nao_coleta`.
- [ ] **Step 2:** rodar. Esperado: FAIL.
- [ ] **Step 3:** implementar. O PowerShell vai como `-Command`, no padrão de `estacao/repositorio.py`, com `[Console]::OutputEncoding = UTF8` e `ConvertTo-Json -Compress`.
- [ ] **Step 4:** `pytest tests/test_estacao_uso.py tests/test_estacao*.py tests/test_janela_login.py -q`. Esperado: PASS.
- [ ] **Step 5:** commit `feat(estacao): tarefa SYSTEM coleta os 5061 e manda ao portal (bandeja 1.4.0)`.

### Task 6: Aba "Uso" em Carteiras

**Files:**
- Modify:
  - `app/main.py`: a lista de abas de `/carteiras` ganha `"uso"`;
  - `templates/carteiras.html`: aba e seção `sec-uso`, no padrão das abas `pessoas` e `certificados`;
  - `app/rotas/carteiras.py`: a rota de leitura.
- Create: `static/carteiras-uso.js`, renderizado só com `textContent`, como `static/configuracao-remocao.js`.
- Test: `tests/test_uso_tela.py`

**Interfaces:**
- Consumes: as tabelas da Task 1 e `cert_installer.departamentos_que_lidera`.
- Produces: `GET /api/carteira/uso?desde=YYYY-MM-DD&ate=YYYY-MM-DD&user_id=&documento=&pagina=1`, com `dependencies=[Depends(require_modulo("carteiras"))]` e `token = Depends(require_admin_ou_gestor)`.
  - Resposta: `{"linhas": [{hora, primeiro_em, ultimo_em, quantidade, pessoa, email, usuario_windows, sem_login: bool, maquina, nome_maquina, documento, titular}], "coletas": {machine_id: {ultima_em, auditoria}}, "pagina": n, "tem_mais": bool}`.
  - 50 por página, ordenado por `hora DESC`. O padrão de `desde` é 7 dias atrás.
  - Só linhas resolvidas (`fingerprint` não nulo).
  - Gestor: só `user_id` de pessoas cujo `departamento_id` está em `departamentos_que_lidera`. Um `user_id` de fora no filtro dá lista vazia, não 403. Linhas sem `user_id` ficam fora.
  - `AlcanceIndisponivel` → 503.
- Na tela:
  - colunas Quando (data, primeiro–último), Pessoa (ou "usuário do Windows (sem login)"), Máquina, Certificado (titular e documento) e Usos;
  - filtros de período, pessoa e certificado;
  - abaixo da tabela, "Última coleta por máquina" com a hora e a marca "auditoria desligada" quando for o caso.

- [ ] **Step 1: Testes.**
  - `test_admin_ve_tudo_inclusive_sem_login`.
  - `test_gestor_so_ve_os_departamentos_dele`.
  - `test_gestor_com_user_id_de_fora_recebe_vazio`.
  - `test_operador_recebe_403`.
  - `test_pendente_nao_aparece`.
  - `test_aba_uso_existe_e_abre_pelo_link`.
  - `test_js_nunca_monta_html_com_dado_da_estacao`: o mesmo critério de `tests/test_pagina_configuracao_remocao.py`.
- [ ] **Step 2:** rodar. Esperado: FAIL.
- [ ] **Step 3:** implementar.
  - Nome da máquina: o mesmo que a aba Computadores usa, buscado em `app/computadores.py`. O builder escolhe a função existente.
  - `?v=` novo no `<script>`.
- [ ] **Step 4:** `pytest tests/test_uso_tela.py tests/test_pagina_carteiras*.py -q`. Esperado: PASS.
- [ ] **Step 5:** commit `feat(uso): aba Uso em Carteiras com recorte de Admin e Gestor`.

### Task 7: Suíte e build

- [ ] **Step 1:** rodar a suíte completa, `pytest -q`. Esperado: tudo verde.
- [ ] **Step 2:** rodar `scripts\build_estacao.ps1`, que gera `Instalador_CertguardAnalise_1.4.0.exe`. A publicação fica com o usuário: `deploy\lancar-certguard.ps1 -Publicar`.
- [ ] **Step 3:** sem commit: o build não versiona nada.
