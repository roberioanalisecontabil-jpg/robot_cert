# CHANGELOG_DEV — Diário Técnico de Desenvolvimento
> **Analise CertiDigital** (`robot_cert`) — Roberio França | AnaliseGroupTI
>
> ⚠️ **LEIA ESTE ARQUIVO PRIMEIRO** antes de iniciar qualquer sessão de desenvolvimento.
> Ele registra o histórico real de mudanças, decisões técnicas e o estado atual do projeto.

---

## 📌 Estado Atual do Projeto (Atualizar a cada sessão)

| Campo              | Valor                                      |
|--------------------|--------------------------------------------|
| **Data da última atualização** | 2026-08-19                  |
| **Branch ativa**   | `main`, sincronizada com o origin (último: `79c165a`) |
| **Versão/Build**   | Deploy Vercel ativo em produção            |
| **Última tarefa concluída** | Sistema visual documentado (`PRODUCT.md` / `DESIGN.md`) e quatro defeitos de origem comum corrigidos — 693 testes |
| **Próxima tarefa** | Níveis de acesso por papel: começar pelo mapa de rotas × papel, não pela tela. Enforcement no servidor é o item que importa; a sidebar hoje esconde por papel só no cliente. Segue pendente: validar a coexistência em duas estações (passo 5 de `docs/PLANO_chave_composta_cofre.md`) e obter a `API_KEY` real |

---

## 🏗️ Arquitetura Resumida (Referência Rápida)

```
robot_cert/
├── api/            → Entrypoint Serverless para Vercel (api/index.py)
├── app/            → Portal Web (FastAPI) — backend principal
│   ├── main.py         → Entry point, rotas principais
│   └── notification_service.py → Serviço de alertas (SMTP, etc.)
├── agent/          → Agente Windows (scanner local de certificados)
├── templates/      → Jinja2 HTML templates do portal
├── static/         → CSS, JS, imagens
├── vercel.json     → Configuração de Serverless Function e empacotamento Vercel
├── supabase/       → Migrations SQL do banco Supabase
├── tests/          → Testes automatizados (pytest)
├── scripts/        → Scripts utilitários/auxiliares
└── .env            → Variáveis de ambiente (não versionado)
```

**Stack:** Python 3.11+, FastAPI, Uvicorn, Supabase (PostgreSQL), Vercel Serverless

---

## 📋 Registro de Sessões de Desenvolvimento

---

### 🗓️ 2026-08-19 — O conserto local que esconde a causa

**Objetivo da sessão:** documentar o sistema visual (`/impeccable init` + `document`) e, a partir daí, iterar na interface com o modo live.

Oito commits. O achado que organiza a sessão inteira **não foi planejado**: quatro defeitos independentes, em arquivos diferentes, com o mesmo formato — *alguém consertou um caso e a causa continuou lá*. Nenhum deles quebrava nada. Era essa a dificuldade.

---

#### Parte 1 — Documentação (`2b46c74`)

`PRODUCT.md` e `DESIGN.md` na raiz, mais `.impeccable/design.json`.

O `style.css` já era um design system maduro — 68 custom properties, dois temas, escala de sete níveis, razão de contraste medida ao lado de cada token de texto. Nada disso estava num lugar onde uma decisão futura pudesse consultar; vivia em comentários espalhados.

North star escolhido: **"A Mesa Limpa"** — uma superfície por vez, nada na tela que não seja a tarefa. Amarra ao fato medido em 15/08 de que a tarefa do colaborador dura menos de um minuto.

Anti-referência confirmada pelo cliente: SaaS genérico de gradiente. Deliberadamente em aberto: a linguagem visual atual é evidência do estado atual, **não** compromisso de marca.

---

#### Parte 2 — Os quatro defeitos de origem comum

**(1) O véu de hover, e o seletor de tema que mentia** (`90c067f`)

As tabelas de duplicidades usavam `rgba(59,130,246,0.06)` no hover — azul do Tailwind, não o `--accent` do projeto — e sem variante de tema escuro.

Criar o token `--row-hover` expôs um defeito no *próprio sistema*: `tbody tr:hover` resolvia tema com `@media (prefers-color-scheme: dark)` **sem** a guarda `:root:not([data-theme="light"])` que a camada de tokens usa. Quem forçava tema claro num Windows escuro recebia o hover escuro — o seletor de tema mentia naquela regra. Com o token, a media query desapareceu e o defeito com ela.

**(2) O sino não estava pequeno; estava achatado** (`bc63a20`)

Medido no navegador: o SVG do sino renderizava **7,2 × 20px**. `.sidebar-toggle-btn` fixa `width: 44px` e nunca sobrescrevia o `padding: 0.5rem 1.1rem` da regra base `button` — sobravam 7,2px de caixa de conteúdo, e o ícone, sendo item de flex, encolhia para caber.

`.theme-toggle-btn` já trazia `padding: 0`. **Um dos três botões estava certo por um remendo local**, o que fazia o sino parecer caso isolado.

**(3) `.form-control` não existia** (`bc63a20`)

Nenhuma linha no CSS, e a classe estava em **9 campos de 3 templates** (instalador 6, carteiras 2, dashboard 1). Herança de Bootstrap que veio no HTML sem a folha junto. Os nove desenhavam como `<input>` cru: Arial 13px, preto puro, `padding: 1px 2px`, canto reto.

O conserto não foi regra nova — foi a classe passar a apontar para o campo canônico que já estava escrito.

**(4) Controle de formulário não herda `font-family`** (`bc63a20`)

Sem `font-family: inherit`, o navegador impõe a fonte dele: **todo botão, campo e select do portal saía em Arial**, inclusive os que as regras já acertavam no resto. `.cg-page-link` e `.cg-page-perpage-select` já contornavam isso cada um por si — de novo, o remendo local escondendo a causa.

Junto: ícones da topbar 20→24px (55% do alvo de 44px), badge de notificação 18→16px em pílula com numeral tabular, e o hambúrguer `&#9776;` virou Heroicons — era um caractere de texto fazendo papel de ícone.

---

#### Parte 3 — Três entregas pelo modo live (`f476545`, `5cd0066`, `8e16181`)

**Importação por arrastar e soltar** em `/carteiras`. Implementação deliberadamente magra: o `<input type="file">` cobre a zona com opacidade 0 — clique, DROP nativo preenchendo `input.files` e foco de teclado saem de graça. O script cuida só do realce durante o arrasto e do nome do arquivo.

Escolhida entre três desenhos pela razão que já estava no comentário do template: o `details` nasce fechado para não empurrar os painéis, e a faixa acrescenta ~56px em vez de um bloco.

**Lista de operadores** com bordas e rolagem própria, espelhando o `.transfer__lista` que já existia na mesma folha. E o item selecionado deixou de usar `border-color: var(--ok-text)` — verde é estado de certificado; "o operador que estou olhando" é navegação.

**Seleção múltipla na transfer list.** A linha virou o alvo; saiu o botão por linha e entraram quatro ações no rodapé de cada painel. Mover um passou a custar dois cliques; mover vinte custa os mesmos dois.

**Coluna Ações e "sem gestor"** em `/usuarios`. `flex-wrap: wrap` com três botões quebrava em duas linhas e fazia a altura da linha depender do texto do botão. A terceira ação foi para um menu `<details>` nativo. E "— sem gestor" saía como texto comum, no mesmo peso de um nome real — virou badge contornado, no idioma do INATIVO ao lado.

---

#### Parte 4 — A guarda que mudou de forma

`#btnAddTodos` e `#btnRemoverTodos` já existiam, escondidos até haver filtro, com o porquê escrito: *"liberar os 491 seria um clique com consequência grande demais para ficar sempre à mão"*.

O cliente pediu os botões permanentes. A proteção **não foi removida — mudou de trancar para dizer**: cada botão imprime a contagem que vai mover, desabilita quando não há nada, e `atribuir` passa a confirmar acima de um documento.

Isso fechou uma assimetria que já existia: `removerVarios` confirmava e `atribuir` não. **Tirar** acesso pedia confirmação; **dar** acesso a centenas não pedia nada — num portal cujo modelo é acesso como decisão do gestor, com falha fechada.

---

#### Dois testes quebraram, os dois por motivo legítimo

**`test_os_dois_blocos_de_tema_escuro`** — acusou divergência total entre os blocos de tema. Não havia nenhuma: o teste usa `css.index("@media (prefers-color-scheme: dark)")`, que casa com a **primeira** ocorrência do literal, e este projeto comenta o porquê de cada decisão. Uma frase explicando a guarda de tema, escrita dentro do `:root` claro, fazia o recorte virar string vazia. Passou a remover comentários antes de procurar os marcadores.

**`test_lote_so_aparece_com_filtro`** — travava a implementação (`btnAdd.hidden = !(temFiltro &&`) que o cliente pediu para mudar. Reescrito como `test_lote_em_massa_nao_e_um_clique`, travando a **intenção** do docstring original em três afirmações: liberar em lote confirma, remover em lote confirma, e os botões imprimem a contagem.

Os dois foram verificados por mutação: neutralizar a proteção faz o teste falhar; restaurar faz passar. Teste que passa não prova que morde.

---

#### Armadilhas registradas

- **`?v=` nos templates.** Duas vezes recarreguei a página, vi o defeito ainda lá e quase reabri investigação encerrada — o navegador servia a folha antiga. Girar o token junto com toda alteração de estilo virou regra sem exceção.
- **`getComputedStyle` pela ponte da extensão devolveu valores obsoletos** por quatro medições seguidas, inclusive para um `style.background` inline (impossível de ignorar sem `!important`). Quando o número diz o impossível, o número é que está errado — o screenshot resolveu em uma tentativa.
- **A `<main>` inteira é ambígua para o modo live:** os 11 templates compartilham `main.main-content`, e o andaime resolveu para `carteiras.html` enquanto a página era `/usuarios`. Selecionar sempre um elemento interno.

---

#### Estado ao fim

`main` em `79c165a`, deploy em produção, **693 testes**. `/usuarios` e `/carteiras` verificadas contra dados reais no navegador (489 disponíveis, 2 na carteira, seleção e contagens corretas).

**Pendente:** níveis de acesso por papel. Não foi feito de propósito — uma tela que promete "o gestor não vê Instalador" enquanto o servidor continua respondendo `/instalador` para ele é teatro de segurança. O trabalho real é o enforcement; a tela é a parte barata. Começar pelo mapa de rotas × papel.

---

### 🗓️ 2026-08-15 — A bandeja que mentia, o cofre indecifrável e a chave composta

**Objetivo da sessão:** partir do log do ANALISESRV de 14/08 — onde a bandeja acusava o serviço de não responder a um rescan que ele tinha aceitado em 0,7s — e terminar com a identidade do cofre corrigida.

Seis commits, em três blocos. O fio comum entre os dois primeiros: **todos são falhas silenciosas ou de diagnóstico errado** — o sistema não quebrava, ele apontava para o lugar errado.

---

#### Parte 1 — A bandeja acusava o inocente (`ad438d6`, `7ea532f`, `d50de7a`)

Quatro linhas do log em contradição direta:

```
08:07:23,891 [INFO]    Rescan acionado pelo tray (origem=tray)
08:09:23,285 [WARNING] Rescan ... expirou sem confirmação
```

O serviço confirmou o recebimento em 0,7s; a bandeja anunciou falha dois minutos depois. Três defeitos independentes convergindo no mesmo sintoma:

**(1) O ícone ficava permanentemente cinza.** A lógica de piscar existia e estava correta — mas vivia inteira dentro do ramo `if cfg.tray_only:`, e os atalhos chamavam o executável sem esse parâmetro. O ícone nascia cinza (padrão de `_start_tray`) e nunca era tocado, indicando "serviço parado" justamente enquanto o agente trabalhava. Virou `_loop_visual_bandeja`, rodando nos dois modos — no modo normal em thread própria, porque o laço principal fica bloqueado em I/O do portal e não animaria nada. A única diferença entre os modos passa a ser a **origem** do estado: no tray-only quem trabalha é o serviço (`sc query`), no normal é o próprio processo. Somou-se a janela de status (menu da bandeja e duplo clique).

**(2) A confirmação do rescan media o sinal errado.** `last_scan_time` só é gravado no **fim** de um ciclo inteiro e bem-sucedido, depois do upload ao portal. Bastava o envio demorar ou falhar para a bandeja acusar o serviço de não responder. O serviço entrar em `scanning`/`sending` já prova que o comando chegou, e aparece em segundos — o prazo passa a medir o intervalo entre **pedir e começar**, não a duração da varredura. Medidos ~43ms por certificado, ou ~24s para os 556 do ANALISESRV: uma base maior estoura 120s sem que nada esteja errado. A decisão saiu para `estado_do_pedido_rescan`, função pura, porque era a parte que errava e estava presa dentro do laço da bandeja.

**(3) O poll de comandos prendia o laço em silêncio.** O laço principal chama `/api/agent/next` **antes** de olhar o `trigger_event` — o mesmo gatilho do botão "Forçar leitura agora". Essa chamada herdava o timeout do client (300s de leitura), dimensionado para o ingest, que sobe centenas de certificados e é legitimamente lento. Numa resposta lenta do portal (Vercel é serverless, com cold start), o laço ficava preso até **cinco minutos sem escrever nada no log** antes de ler o pedido da bandeja. É o que explica o silêncio de dois minutos entre as duas linhas acima: falta ali a linha "Mudança detectada (ou forçada)". O poll passou a ter 20s (`AGENT_POLL_TIMEOUT_SEC`) e demora acima de 5s vira `WARNING` — este era o ponto que segurava o laço e não deixava rastro. Um poll que falha é inofensivo: a próxima volta tenta em 10s.

---

#### Parte 2 — A `CERT_ENCRYPTION_KEY` trocada sem rotação (`f3658c7`, `f96eeec`)

A chave foi trocada no painel da Vercel sem passar pelo mecanismo de rotação. A linha então existente no cofre virou lixo cifrado — AES-GCM recusando com `InvalidTag`.

**O reflexo errado foi caçar a chave antiga.** O certo era notar que **`cert_pfx_store` não é fonte de verdade**: os PFX do ANALISESRV são, e o agente extrai a senha do nome do arquivo. O cofre se reconstrói sozinho. Nenhum dado foi perdido — o rescan manual pela bandeja repovoou as **33 linhas** às 14:08 UTC.

Duas correções saíram da investigação:

- **`f96eeec`** — a rotação estava documentada no `.env.example` e implementada em `cert_installer._get_server_key`, que busca as chaves antigas em `config.CERT_ENCRYPTION_KEY_V<n>`. Só que **o config nunca expôs essas variáveis**: o `getattr` devolvia vazio e qualquer versão anterior estourava como "chave não configurada". O caminho documentado para consertar era justamente o que não funcionava. Passou a carregar por varredura do ambiente, para que a próxima rotação não exija editar o arquivo.
- **`f3658c7`** — o `/api/health` informava `cert_vault_key_configurada` e calava sobre a `CERT_PASSWORD_ENCRYPTION_KEY`. Um servidor sem essa segunda chave (ou com ela igual à primeira, que a aplicação recusa) parecia saudável enquanto `/upload-pfx` devolvia 500 em todo certificado. O sintoma aparece longe da causa: só se manifesta na máquina do usuário final, ao executar o instalador avulso, com o único rastro no `agent.log` de uma máquina remota. Dois booleanos resolvem — `configurada` e `distinta`.

---

#### Parte 3 — Chave composta `(machine_id, fingerprint)` (`40785f2`)

Execução de `docs/PLANO_chave_composta_cofre.md`, escrito em 08/08 e até aqui marcado "nada aplicado".

O fingerprint SHA-256 identifica **o certificado, não a instalação dele**. Num escritório contábil o mesmo A1 e-CNPJ costuma estar em várias estações — que é exatamente o domínio deste projeto. Sob unicidade global, autorizar o certificado X na estação B fazia o upsert sobrescrever a linha da A, trocando o `machine_id`; como `listar_optin_fingerprints` filtra por `machine_id`, o agente de A parava de receber X. Sem erro, sem log, sem mudança na tela de A — **a mesma classe de falha do bug de 08/08**.

**A revogação era a metade perigosa.** `revogar_do_cofre` apagava por fingerprint nas duas tabelas — correto enquanto só podia existir uma linha por certificado. Com a chave composta, deixá-la como estava transformaria "revogar nesta estação" em "apagar o material de todas". Por isso `machine_id` ficou **obrigatório** ali e na rota DELETE, sem default: faltando o parâmetro a chamada é recusada com 422 em vez de apagar demais. Essa função tinha de mudar junto com a migration, não depois.

**Arquivos:**
- `supabase/migrations/20260815160000_cofre_chave_composta.sql` → PK `(machine_id, fingerprint)` em `cert_vault_optin`; UNIQUE composto em `cert_pfx_store` (o PK `id` UUID continua)
- `app/cert_installer.py` → os dois `on_conflict`; `revogar_do_cofre(fingerprint, machine_id)` filtrando pelos dois nos dois deletes
- `app/main.py` → `machine_id` como `Query(...)` obrigatório no DELETE; comentário da barreira de upload atualizado (a chave composta fechou a metade **destrutiva** do vetor — um upload declarado como outra estação cria linha própria em vez de sobrescrever; o que ela *não* faz é decidir se aquele PFX podia ser guardado, e isso continua sendo trabalho da barreira)
- `templates/instalador.html` → `machine_id` no DELETE, e a confirmação diz de qual máquina

**O fake de Supabase precisou mudar antes dos testes.** O `_Query.upsert` comparava **uma coluna só** no `on_conflict` — colidiria onde o banco não colide, escondendo justamente o comportamento sob teste. Passou a aceitar chave composta como o PostgREST aceita (`"col_a,col_b"`).

**Testes acrescentados (5):** coexistência da autorização em A e B; dois uploads do mesmo fingerprint gerando duas linhas com materiais distintos (aqui `upsert_pfx` roda de verdade, sem patch, porque o que se testa é o `on_conflict`); revogar em A não alcança B; revogar sem `machine_id` recusado com 422; e a asserção em `test_cert_installer_hardening` de que os dois deletes filtram pela máquina.

---

#### Validação

- Suíte completa: **258 passed**
- Migration aplicada em produção pelo SQL Editor. `pg_constraint` confirma exatamente três linhas — `cert_vault_optin_pkey PRIMARY KEY (machine_id, fingerprint)`, `cert_pfx_store_machine_fingerprint_key UNIQUE (machine_id, fingerprint)`, `cert_pfx_store_pkey PRIMARY KEY (id)` — **sem sobra** de `UNIQUE (fingerprint)`
- Deploy verificado pelo `openapi.json` de produção: `machine_id` consta como query param `required: true` no DELETE
- Dados intactos após a migration: 33 linhas em `cert_pfx_store`, 34 em `cert_vault_optin`
- `/api/health` verde, incluindo `cert_senha_key_distinta`

#### Decisões técnicas

- **Migration e deploy em janela única, sem migration em duas fases.** Nos dois sentidos há incompatibilidade momentânea (`42P10 — no unique or exclusion constraint matching the ON CONFLICT specification`): código velho contra schema novo, ou o inverso. A alternativa zero-downtime seria adicionar a constraint composta → deploy → derrubar a antiga. Para 33 linhas numa máquina só, com agente rodando a cada 24h e o resto sendo clique manual, é cerimônia demais. Na prática o deploy já estava no ar quando foi verificado.
- **`machine_id` obrigatório, sem default, na revogação.** Um default reintroduziria pela porta dos fundos o apagão que a mudança existe para evitar.
- **A coluna `pfx_password` antiga continua sem uso e sem `DROP`** — mesma decisão de 11/08.

#### Pendências

1. **Passo 5 do plano: validar a coexistência em duas estações reais.** Todas as 33 linhas são de `ANALISESRV` — só existe uma máquina no cofre. Está coberto por teste, **não por campo**.
2. `API_KEY` real do ANALISESRV — o valor do `.env` local **não** é o da Vercel (levou 401 ao tentar `/api/agent/commands`). Idem `CERT_ENCRYPTION_KEY`. Só o `SUPABASE_SERVICE_KEY` local funciona contra produção.
3. Migration neste projeto **só pelo SQL Editor**: não há `DATABASE_URL` no `.env` nem CLI do Supabase, e o service key fala com o PostgREST, que não executa DDL.

---

### 🗓️ 2026-08-10/11 — Instalador avulso (modelo Ninite) + três bloqueios do agente em produção

**Objetivo da sessão:** partir de um agente em produção que não conectava havia 11 horas e chegar a um fluxo em que o usuário escolhe o certificado no portal, baixa um `.exe` e o instala na própria máquina, sem agente na estação.

---

#### Parte 1 — Três bloqueios empilhados no ANALISESRV

O `agent.log` tinha 1.675 linhas, e **1.333 delas eram o mesmo `WinError 10061`**. Nenhuma dizia a causa. Eram três defeitos em série, cada um escondendo o seguinte:

**(1) `agent_config.json` com JSON inválido.** Caminhos Windows não escapados (`"F:\07. CERTIFICADOS"` — `\0` não é escape JSON). O `except` em `_load_local_agent_config` imprimia em `stderr` e devolvia `{}` — e **stderr num serviço Windows não vai a lugar nenhum**. Sem config, o agente caía no `DEFAULT_ROBOT_BASE` (`127.0.0.1:8020`) e batia num portal local que nunca existiu naquela máquina. A pista estava na contradição entre o log (`Conectando a: http://127.0.0.1:8020`) e o config (`certificado.analisegroup.cnt.br`).

**(2) Redirect 308 não seguido.** Corrigido o (1), o agente passaria a usar a URL do config — que apontava para `http://`, e o portal responde **308** para `https://`. O `httpx` não segue redirects por padrão, então o 308 chegava ao `raise_for_status` e virava `"unavailable"`: o mesmo laço de erro, com outra causa.

**(3) API key inválida.** A chave do config recebe **401** do portal. Não é a de produção. **Continua aberto** — depende do valor real da `API_KEY`.

**Consequência do (3) para o instalador:** a senha do PFX só é gravada no cofre quando o agente reenvia o certificado. Enquanto o agente não conectar, os registros existentes ficam sem senha e o instalador avulso falha neles com causa nomeada.

---

#### Parte 2 — Instalador avulso

**Por que existir:** o fluxo anterior enfileirava um comando para um agente rodando na estação destino. Como o serviço roda por padrão como **LocalSystem** e o `certutil` é chamado com `-user`, o certificado ia para o repositório do LocalSystem — invisível para a pessoa que loga na máquina e abre o navegador. O modelo novo instala no repositório de quem executa, que é o ponto.

**Token no nome do arquivo, não dentro do binário.** Injetar o token no `.exe` faria cada download ser um binário inédito para o Windows, e o alerta do SmartScreen apareceria em **toda** instalação — justo no fluxo que deveria ser de um clique, e justo com um público que está instalando credenciais. Com o token no nome, o binário é único e pode ser assinado uma vez. É o que o Ninite faz.

**A senha do PFX voltou ao cofre, sob chave dedicada.** Ela saiu em 03/08 por dois motivos: estava cifrada com a **mesma** chave do PFX, e o agente a lia do nome do arquivo na pasta de origem. O segundo motivo não vale para o instalador avulso — a máquina do usuário não tem pasta nenhuma — e sem senha o `certutil` recusa todo PFX. O primeiro continua valendo: `_get_password_key()` **recusa operar** se `CERT_PASSWORD_ENCRYPTION_KEY` for igual a `CERT_ENCRYPTION_KEY`.

> ⚠️ A separação só vale se as duas chaves viverem em lugares distintos. Ambas no mesmo `.env` do mesmo servidor tornam a proteção nominal.

**`/claim` resgata sem `X-API-Key`.** Embutir a chave do agente num executável público seria distribuí-la a quem baixasse, e ela abre todas as rotas do agente. O token vira a credencial — uso único (compare-and-swap), TTL de 5 min, e limite de 10 tentativas por IP/minuto contra força bruta.

**O caminho via agente continua intacto.** O botão novo foi adicionado ao lado do antigo, não no lugar dele.

---

#### Arquivos criados
- `agent/instalador_standalone.py` → o `.exe` que o usuário baixa
- `Instalar_Certificado.spec` + `scripts/build_instalador_avulso.ps1` → build (o endereço do portal é gravado em `agent/_build_config.py`, gitignored)
- `supabase/migrations/20260811000000_senha_pfx_chave_dedicada.sql` → colunas `pfx_password_{enc,iv,tag}`
- `tests/test_agent_config_loader.py`, `tests/test_agente_redirect.py`, `tests/test_instalador_avulso.py`

#### Arquivos modificados
- `agent/run_agent.py` → loader loga no LOGGER e recupera barras invertidas; `_novo_http_client()` com `follow_redirects=True`
- `app/cert_installer.py` → cifragem da senha sob chave própria; bundle leva a senha via ECDH
- `app/main.py` → `/claim`, `/preparar-download`, `/instalador/baixar/{token}`, `/report-avulso`
- `agent/installer_client.py` → volta a enviar a senha no upload
- `templates/instalador.html` → botão "Baixar Instalador"
- `vercel.json` → `dist/Instalar_Certificado.exe` em `includeFiles`
- `.gitignore` → `dist/*` + exceção para o executável

#### Decisões técnicas
- **O `.exe` é versionado.** O deploy é Vercel, que builda num container Linux e jamais geraria um `.exe` de Windows. Sem ele no repositório, `/instalador/baixar` responde 503. Custo: ~16 MB permanentes no histórico por rebuild.
- **`dist/*` em vez de `dist/`** no `.gitignore` — o git não entra em diretório excluído, então a exceção nunca seria avaliada.
- **Um teste guarda o `vercel.json`.** Sem a entrada em `includeFiles`, o deploy sobe verde e a rota falha só para o usuário — modo de falha que nenhum teste de aplicação pega, porque o arquivo existe na máquina de quem desenvolve.
- **`test_senha_do_pfx_nunca_e_armazenada` foi reescrito**, não removido. Virou `test_senha_e_guardada_cifrada_sob_chave_propria`, fixando o que continua valendo: nunca em claro, nunca na coluna antiga, sob chave distinta. Mais um teste que recusa chaves iguais.
- **A coluna `pfx_password` antiga não foi removida.** `DROP COLUMN` em produção é irreversível e não há ganho.

#### Validação
E2E real nesta máquina, com dois certificados ICP-Brasil de verdade: portal local → escolher → baixar → executar → certificado no repositório do usuário, **não-exportável** (confirmado tentando exportar e recebendo recusa), trilha `SOLICITADO → REDIMIDO → CONCLUIDO`, token consumido, reuso recusado com 403. **219 testes.**

#### Pendências
1. `API_KEY` real para o ANALISESRV *(bloqueia o reenvio de certificados ao cofre)*
2. Rodar a migration no Supabase **antes** do deploy
3. `CERT_PASSWORD_ENCRYPTION_KEY` no painel da **Vercel** (não no `.env`, que não sobe)
4. Assinatura de código — decidido adiar; mitigação é diretiva de grupo pondo o domínio na zona Intranet Local nas estações. **Não verificado em máquina real.**
5. Agente por estação (instalação silenciosa repetida) — avaliado e adiado; vale se a frequência de instalação por máquina for alta

---

### 🗓️ 2026-08-08 — Painel de Opt-in do Cofre: correção do `machine_id` e testes de regressão

**Objetivo da sessão:** Validar o painel de opt-in recém-commitado (`c28f98a`) e fechar as pendências de infraestrutura de teste.

**Bug encontrado e corrigido (falha silenciosa, severidade alta):**

O painel gravava a autorização com `machine_id: cert.machine_id || "default"`. Mas em `fonte=auto` o portal devolve o `machine_id` na **raiz** do payload de `/api/certificados` (`app/main.py:334-342`), não em cada item — então `cert.machine_id` era sempre `undefined` e **toda autorização ia para o literal `"default"`**.

Do outro lado, o agente consulta filtrando pelo machine_id dele (`agent/installer_client.py:57`) e `listar_optin_fingerprints` aplica `.eq("machine_id", ...)` (`app/cert_installer.py:332`). O `_machine_id()` do agente (`agent/run_agent.py:335`) resolve de `MACHINE_ID` → config local → settings → `"default"`.

Resultado: em qualquer instalação cujo machine_id não fosse literalmente `"default"`, o admin clicava "Autorizar", o badge ficava verde, e o agente **nunca recebia o certificado**. Nenhum erro em lugar nenhum. O GET sem filtro de máquina agravava, mostrando o opt-in de todas as máquinas e mascarando a divergência.

**Arquivos modificados:**
- `templates/instalador.html` → `_optinMachineId` lido da raiz do payload; POST usa ele; GET de `/vault-optin` passa `?machine_id=`; busca do inventário virou sequencial (o machine_id precisa sair dela antes); máquina exibida no resumo do painel

**Arquivos criados:**
- `pytest.ini` → `testpaths = tests` + `norecursedirs`. Sem isto, `pytest` sem argumentos varria `robot_cert-main/` (backup do zip antigo) e quebrava com `ImportPathMismatchError`
- `tests/test_instalador_optin_machine_id.py` → 4 testes de invariante do painel (lado da tela)
- `tests/test_cert_installer_optin_e2e.py` → 8 testes do circuito completo pelo HTTP real (lado do servidor), com fake de Supabase em memória

**Por que dois arquivos de teste:** o bug sobreviveu porque *cada lado, isolado, estava correto* — a tela gravava um machine_id válido, o servidor filtrava corretamente por machine_id. O que faltava era um teste **atravessando a fronteira**: autorizar na máquina A e verificar que o agente da A vê e o da B não vê. O fake de Supabase é um banco de brinquedo, não mock de asserção, para exercitar a lógica de filtro real em vez de conferir que uma chamada aconteceu.

**Decisões técnicas tomadas:**
- O `Promise.all` do carregamento do painel foi desfeito **de propósito**: o machine_id sai do inventário e precisa entrar na consulta de autorizações. Reintroduzir o paralelismo volta a perder o filtro — está documentado no código e coberto por teste.
- `robot_cert-main/` **não foi apagado** (é backup, gitignored, 0,7 MB). Resolvido por config em vez de remoção.

**Validações executadas:**
- Suíte: **136 passed** (123 anteriores + 4 do painel + 9 do circuito), `pytest` puro já funciona
- Teste de mutação em ambos os arquivos novos — não são testes decorativos:
  - reintroduzindo cada metade do bug no template: 1 e 2 falhas
  - removendo `.eq("machine_id", ...)` de `listar_optin_fingerprints`: 2 falhas
  - fazendo `revogar_do_cofre` não apagar o PFX: 1 falha
  - devolvendo a barreira do `/upload-pfx` ao estado global: 1 falha
- Portal no ar em `127.0.0.1:8020`: `/api/health` respondeu com os campos novos, `/instalador` renderizou HTTP 200 com todos os marcadores do painel
- Os 6 helpers JS usados pelo painel conferidos em `static/ui-common.js`

**Segundo achado, corrigido na mesma sessão — barreira global no `/upload-pfx`:**

`app/main.py` chamava `cert_installer.listar_optin_fingerprints()` **sem `machine_id`**, embora `body.machine_id` estivesse disponível na requisição. A barreira de servidor do upload era portanto global: bastava o fingerprint estar autorizado em qualquer máquina.

O agente bem-comportado nunca esbarrava nisso — só envia o que a consulta filtrada dele devolveu. Mas a barreira existe justamente para o agente "desatualizado (ou adulterado)", e contra esse é que ela não olhava a máquina: declarando-se da estação B, ele gravava o PFX de um certificado autorizado só na A e, como `upsert_pfx` usa `on_conflict="fingerprint"`, sobrescrevia o registro legítimo — o mesmo vetor já descrito em `require_agent_or_admin`, por outro caminho.

Passou a ser `listar_optin_fingerprints(body.machine_id)`. Verificado antes de aplicar que o caminho legítimo não quebra: `agent/installer_client.py` usa a **mesma** variável `machine_id` na consulta (linha 84) e no payload do upload (linha 108).

**Pendências / Próximos passos:**
- [ ] Validação com agente Windows real — o circuito lógico está coberto, mas o transporte ECDH/AES e a instalação na estação não
- [ ] Definir `ENCRYPTION_KEY` nos ambientes (ver dívida técnica #2)

---

### 🗓️ 2026-08-03 — Módulo Instalador Remoto de Certificados

**Objetivo da sessão:** Implementar instalação remota de certificados na estação do usuário via agente Windows, e endurecer o módulo após revisão.

**Commits:** `fce8c4a` (implementação) e `f2557aa` (endurecimento + testes)

**Entregue:**
- Transporte cifrado ponta a ponta: **AES-256-GCM + ECDH** entre portal e agente
- Cofre de PFX no servidor (`cert_pfx_store`) com material cifrado em repouso e `key_version` gravado por registro, permitindo rotação incremental de chave
- Tabela `cert_vault_optin` + **RLS no Supabase** (`REVOKE` de `anon`/`authenticated`, acesso só via `service_role`)
- Suíte de **123 testes** automatizados

**Cinco decisões do endurecimento** (documentadas em `tests/test_cert_installer_hardening.py`):
1. **Opt-in do cofre** — o agente enviava TODOS os certificados lidos a cada ciclo; numa base de 1.028, mil chaves privadas copiadas ao servidor sem decisão explícita
2. **Token de instalação** era gerado no `/prepare` e nunca chegava ao agente — a instalação nunca completava
3. **`key_version` gravado** — sem ele, rotacionar a chave exigiria recifrar tudo
4. **Senha do PFX não é mais armazenada** — era cifrada com a MESMA chave do PFX
5. **Limite de upload** reduzido de 50 MB para 1 MB

**Migrations criadas:**
- `20260803_cert_installer.sql`, `20260803120000_cert_installer_rls.sql`, `20260803130000_cert_installer_hardening.sql`

**Nota:** a UI do opt-in ficou pendente nesta sessão e foi entregue em `c28f98a` — com o bug de `machine_id` corrigido em 08/08.

---

### 🗓️ 2026-08-02 — Configuração Completa e Deploy de Sucesso no Vercel

**Objetivo da sessão:** Preparar e verificar o projeto FastAPI para rodar nativamente como Serverless Function no Vercel e colocar o portal no ar.

**Ações realizadas:**
- Criado o arquivo `api/index.py` importando `app` de `app.main` para padrão nativo Vercel Python.
- Criado `vercel.json` configurado com `@vercel/python`, rotas genéricas (`/(.*)` -> `api/index.py`) e empacotamento explícito dos assets (`templates/**`, `static/**`).
- Protegidos os hooks de inicialização e salvamento (`app/main.py` e `app/settings_state.py`) com blocos `try...except OSError` para imunidade contra o sistema de arquivos read-only do Vercel.
- Validada a importação limpa da aplicação via `api/index.py`.
- **Deploy realizado com sucesso no Vercel!** O portal web agora está operando em produção no ambiente serverless.

**Arquivos criados / modificados:**
- `api/index.py` → Entrypoint da função serverless
- `vercel.json` → Arquivo de rotas e build Vercel
- `app/main.py` → Proteção `OSError` na startup hook
- `app/settings_state.py` → Proteção `OSError` na `_save_file`

**Status do Deploy:**
- [x] Conectar conta GitHub no Vercel
- [x] Importar o repositório `roberioanalisecontabil-jpg/robot_cert`
- [x] Definir variáveis de ambiente (`JWT_SECRET_KEY`, `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `API_KEY`)
- [x] Deploy concluído e portal funcionando no Vercel.

---

### 🗓️ 2026-08-01 — Scripts de Liberação e Teste de Porta

**Objetivo da sessão:** Criar scripts PowerShell para configurar o firewall e validar acesso externo.

**Contexto:** Servidor de destino é uma **máquina Windows separada** com acesso via RDP/TeamViewer.

**Arquivos criados:**
- `scripts/setup_porta_servidor.ps1` → Rodar **no servidor** (como Admin): configura firewall, exibe IPs, valida Python
- `scripts/testar_porta_externa.ps1` → Rodar **nesta máquina** (dev): testa se a porta ficou acessível externamente

**Plano de execução (ordem):**
1. Copiar `scripts/setup_porta_servidor.ps1` para o servidor via RDP
2. Rodar como Administrador → anota o IP local e externo exibidos
3. Configurar Port Forwarding no roteador usando o IP local exibido
4. Voltar para esta máquina e rodar `scripts/testar_porta_externa.ps1`
5. Se OK → prosseguir com a migração do portal

**Decisões técnicas tomadas:**
- Banco (Supabase) permanece na nuvem por ora → migração do banco fica para fase 2
- Servidor de destino confirmado: máquina Windows separada (acesso RDP)

**Pendências / Próximos passos:**
- [ ] Executar `setup_porta_servidor.ps1` no servidor Windows
- [ ] Configurar Port Forwarding no roteador
- [ ] Validar com `testar_porta_externa.ps1`
- [ ] Iniciar migração do portal (copiar projeto, .env, instalar deps, NSSM)

---

### 🗓️ 2026-08-01 — Planejamento: Migração Render → Windows Server

**Objetivo da sessão:** Planejar e documentar a migração do portal do Render para Windows Server self-hosted.

**Contexto:** O Render reduziu o plano gratuito, causando instabilidade. A solução é hospedar o portal em servidor Windows próprio.

**Arquivos criados:**
- `docs/GUIA_MIGRACAO_WINDOWS_SERVER.md` → Guia completo passo a passo da migração

**Decisões técnicas tomadas:**
- `gunicorn` NÃO funciona no Windows nativamente → usar `uvicorn` diretamente ou `waitress`
- Usar **NSSM** para registrar o portal como serviço Windows (auto-start, logs automáticos)
- Porta escolhida: **8020** (mesma já usada no projeto)
- Nginx como proxy reverso opcional se quiser HTTPS com domínio

**Pendências / Próximos passos:**
- [ ] Instalar Python 3.11+ no Windows Server
- [ ] Clonar/copiar projeto para `C:\Apps\robot_cert`
- [ ] Criar `.env` com variáveis de produção
- [ ] Abrir porta 8020 no Firewall do Windows (comando NSSM pronto no guia)
- [ ] Configurar Port Forwarding no roteador (se servidor em rede local)
- [ ] Instalar NSSM e registrar serviço
- [ ] Atualizar `CERT_ROBOT_BASE_URL` no `.env` dos agentes locais
- [ ] Testar acesso externo antes de desligar o Render

---

### 🗓️ 2026-08-01 — Sessão Inicial / Setup do Changelog

**Objetivo da sessão:** Criar estrutura de rastreamento contínuo para o projeto.

**Arquivos criados:**
- `CHANGELOG_DEV.md` ← este arquivo, na raiz do projeto

**Arquivos em foco (abertos no editor):**
- `tests/test_smtp_alerts.py`
- `app/notification_service.py`
- `supabase/migrations/20260620_add_smtp_settings.sql`
- `tests/test_api_routes.py`
- `scratch/delete_test_user.py`
- `app/main.py`

**Contexto identificado:**
- O projeto está em fase ativa de desenvolvimento do módulo de **alertas SMTP**.
- Existe uma migration SQL para configurações SMTP (`20260620_add_smtp_settings.sql`).
- Testes estão sendo escritos para as rotas de API e para os alertas SMTP.

**Decisões técnicas tomadas:**
- Nenhuma nesta sessão (apenas setup).

**Pendências / Próximos passos:**
- [ ] Definir e registrar o escopo da próxima tarefa de desenvolvimento.

---

## 📐 Template para Nova Sessão

> Copie e cole este bloco ao iniciar cada nova sessão:

```
### 🗓️ YYYY-MM-DD — [Título da Sessão]

**Objetivo da sessão:** 

**Arquivos modificados:**
- `caminho/arquivo.py` → descrição da mudança

**Arquivos criados:**
- `caminho/novo_arquivo.py` → propósito

**Arquivos removidos:**
- (nenhum)

**Decisões técnicas tomadas:**
- 

**Bugs corrigidos:**
- 

**Pendências / Próximos passos:**
- [ ] 
```

---

## 🔑 Convenções do Projeto

| Convenção              | Detalhe                                          |
|------------------------|--------------------------------------------------|
| API Key header         | `X-API-Key`                                      |
| Banco de dados         | Supabase (PostgreSQL via REST)                   |
| Porta do portal local  | `8020`                                           |
| Ambiente virtual       | `.venv/` na raiz                                 |
| Testes                 | `pytest` em `tests/`                             |
| Agente                 | `agent/run_agent.py`                             |
| Variáveis de ambiente  | `.env` (não versionado), exemplo em `.env.example` |

---

## ⚠️ Dívidas Técnicas / Riscos Conhecidos

| # | Descrição | Severidade | Status |
|---|-----------|------------|--------|
| 1 | `robot_cert-main/` é uma cópia inteira do projeto dentro dele mesmo (backup do zip de 25/05, gitignored, 0,7 MB). Contornado por `pytest.ini`, mas continua confundindo buscas e ferramentas | Baixa | Contornado |
| 2 | `ENCRYPTION_KEY` não definida (`/api/health` → `smtp_key_dedicada: false`). Sem ela a chave do SMTP é derivada da `JWT_SECRET_KEY` — se a JWT diferir entre ambientes, a senha SMTP para de descriptografar | Média | Aberto |
| 3 | Instalação fim-a-fim: o circuito do opt-in passou a ter cobertura (`test_cert_installer_optin_e2e.py`); falta o transporte ECDH/AES e a instalação na estação, que dependem de agente Windows real | Média | Parcial |
| 6 | Barreira de servidor do `/upload-pfx` era global — não conferia o `machine_id` do agente contra o da autorização. Agente adulterado podia sobrescrever `cert_pfx_store` de outra máquina | Média | **Resolvido em 08/08** |
| 4 | `autorizar_no_cofre` usa `on_conflict="fingerprint"` — o mesmo certificado não pode estar autorizado em duas máquinas ao mesmo tempo; a segunda autorização move a primeira | Baixa | Aberto |
| 5 | `app/main.py` usa `@app.on_event("startup")`, deprecado no FastAPI (avisos na suíte). Migrar para lifespan handlers | Baixa | Aberto |

---

*Arquivo mantido manualmente a cada sessão de desenvolvimento com o assistente de IA.*
