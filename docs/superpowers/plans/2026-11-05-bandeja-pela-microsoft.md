# Bandeja pela Microsoft — plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** a bandeja (`estacao/`) conecta pela Microsoft (navegador + volta pelo `127.0.0.1`), e a senha da bandeja dos quatro domínios desliga sozinha quando a frota dos últimos 30 dias estiver na versão nova.

**Architecture:** o portal reaproveita o fluxo web da entrega 1 (`app/rotas/microsoft.py`), marcando o pedido como "de bandeja" no `cg_ms`; no retorno, em vez de abrir sessão, emite um código de uso único amarrado a um desafio (sha256 do verificador da bandeja) e manda o navegador ao ouvinte loopback. A bandeja troca código + verificador pelo segredo do dispositivo numa rota nova, que termina pelo mesmo caminho de `/api/agent/dispositivos/registrar`. Uma tabela de uma linha guarda a virada; a rodada de 5 min do `microsoft_loop` a confere.

**Tech Stack:** FastAPI, PostgreSQL 17 (camada `db_pg` estilo Supabase), pytest com `_Fake` (`tests/test_recuperacao_de_senha.py`); bandeja Python + Tk + pystray, só biblioteca padrão para o ouvinte (`http.server`, `secrets`, `hashlib`, `base64`, `webbrowser`).

**Spec:** `docs/superpowers/specs/2026-11-05-bandeja-pela-microsoft-design.md` (aprovado em 05/11/2026). Entrega 1: `docs/superpowers/specs/2026-11-04-login-microsoft-design.md`.

## Global Constraints

- Migrations só pelo `atualizar-portal` (`db/aplicar_schema.py`); arquivo em `supabase/migrations/`, idempotente, cabeçalho "NAO rode a mao", bloco de dono/permissões no modelo de `20261016100000_carteira_sugerida_pelo_acessorias.sql`, consultas de conferência no fim.
- Nada muda no app do Entra: a URI de retorno continua `.../entrar/microsoft/retorno`.
- O segredo do app nunca vai para a bandeja; o verificador nunca sai da bandeja (só o desafio).
- O ouvinte escuta **só** em `127.0.0.1`, porta aleatória (0), aceita **um** retorno válido, prazo de **300 s**, e fecha.
- Código de uso único: **120 s**, guardado só como hash sha256, queimado na primeira tentativa (certa ou errada).
- Virada: `configurado()` **e** ≥ 1 dispositivo na nova **e** nenhum dispositivo não revogado, visto nos últimos **30 dias**, com versão `certguard-x.y.z` abaixo de **`1.2.0`**. Linhas com `versao` nula ou sem o prefixo `certguard-` não contam.
- A virada não se desfaz sozinha; sem `configurado()` ela não vale (a senha volta para todos); com as variáveis de volta, volta a valer.
- Depois da virada, `/api/agent/dispositivos/registrar` com e-mail dos domínios: **403 `"Use Entrar com a Microsoft."`**, depois dos limites de tentativa e **antes** de conferir a senha; `login_negado` com `motivo: "bandeja_so_microsoft"`.
- Versão nova da bandeja: **`1.2.0`** (`estacao/__init__.py`); `VERSAO_REPORTADA` continua `certguard-{VERSAO}`.
- Com Microsoft desligada (variáveis vazias): sem botão na bandeja, sem rotas novas (404), sem virada.
- Sem dependência nova. Commits com `git commit -F <arquivo>` e a linha `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`; nada de `--no-verify` (o hook roda a suíte). Sem push sem autorização do Robério.
- Não tocar nas mudanças não commitadas de `templates/dashboard.html` e `static/aguia-dashboard.css`.

## Review Focus

1. **Navegador não segue para `http://127.0.0.1`** (bloqueio de rede local, extensão, política): a página "Pronto" tem de ter também um link clicável para o mesmo endereço, e a bandeja desiste em 300 s com mensagem. Teste na Tarefa 3 (link presente) e Tarefa 6 (prazo).
2. **Segundo pedido ao ouvinte** (`/favicon.ico`, pré-carregamento) não pode consumir a espera nem o código. Teste na Tarefa 6.
3. **Pedido de bandeja nunca abre sessão do site**, e pedido do site nunca vai para o loopback: o `cg_ms` decide. Teste na Tarefa 3.
4. **Linhas do Hardlyze, nulas, revogadas ou antigas (>30 dias)** não seguram a virada; frota vazia não vira. Testes na Tarefa 4.
5. **Depois da virada, o 403 é igual** para conta existente ou não, senha certa ou errada; fora dos domínios nada muda; sem `configurado()` a senha volta. Testes na Tarefa 4.

---

### Tarefa 1: Migration das duas tabelas

**Files:**
- Create: `supabase/migrations/20261106100000_bandeja_pela_microsoft.sql`
- Test: `tests/test_migration_bandeja_microsoft.py`

**Interfaces:**
- Produces: `public.bandeja_codigo (codigo_hash text PRIMARY KEY, user_id uuid NOT NULL REFERENCES public.users(id) ON DELETE CASCADE, desafio text NOT NULL, expira_em timestamptz NOT NULL, usado_em timestamptz, criado_em timestamptz NOT NULL DEFAULT now())`; `public.bandeja_virada (id smallint PRIMARY KEY DEFAULT 1 CHECK (id = 1), desligada_em timestamptz NOT NULL DEFAULT now(), versao text NOT NULL)`.

- [ ] **Step 1: Teste** no molde de `tests/test_migration_login_microsoft.py`: `test_migration_bandeja_idempotente_e_completa` — sem comentários, o SQL tem `CREATE TABLE IF NOT EXISTS public.bandeja_codigo`, `CREATE TABLE IF NOT EXISTS public.bandeja_virada`, `CHECK (id = 1)`, `ON DELETE CASCADE`, nenhum `DROP TABLE`, e o `GRANT SELECT, INSERT, UPDATE, DELETE` cobre as duas tabelas. `test_migration_bandeja_vem_depois_da_do_login` — o nome ordena depois de `20261105100000_login_microsoft.sql`.
- [ ] **Step 2:** `pytest tests/test_migration_bandeja_microsoft.py -v` → FAIL (arquivo não existe).
- [ ] **Step 3:** escrever a migration (tabelas, `COMMENT ON TABLE` de cada uma, bloco `DO $$` de dono/permissões, conferência `SELECT table_name ... IN ('bandeja_codigo','bandeja_virada')`). Índice em `bandeja_codigo (expira_em)` para a limpeza.
- [ ] **Step 4:** teste → PASS.
- [ ] **Step 5:** commit `feat(bandeja): tabelas do codigo de uso unico e da virada`.

### Tarefa 2: Código de uso único

**Files:**
- Create: `app/bandeja_codigo.py`
- Test: `tests/test_bandeja_codigo.py`

**Interfaces:**
- Produces:
  - `VALIDADE_S = 120`
  - `desafio_de(verificador: str) -> str` — base64url sem `=` do sha256 de `verificador` (43 caracteres).
  - `emitir(user_id: str, desafio: str, sb: Any = None) -> str` — devolve o código em claro (`secrets.token_urlsafe(32)`); grava `codigo_hash` (sha256 hex), `user_id`, `desafio`, `expira_em = agora + 120 s`. Aproveita para apagar linhas com `expira_em` de mais de 1 dia.
  - `queimar(codigo: str, verificador: str, sb: Any = None) -> Optional[str]` — devolve `user_id` ou `None`. Marca `usado_em` **antes** de conferir prazo e desafio (uma tentativa só). `None` para: código desconhecido, já usado, vencido, `desafio_de(verificador) != desafio` (comparação com `hmac.compare_digest`).
  - `sb=None` → `app.settings_state._banco()`; sem banco → `None` em `queimar`, `RuntimeError` em `emitir`.

- [ ] **Step 1: Testes** com `_Fake({"bandeja_codigo": []})`:
  - `test_desafio_e_base64url_do_sha256`: `desafio_de("abc") == "ungWv48Bz-pBQUDeXa4iI7ADYaOWF3qctBD_YfIAFa0"`.
  - `test_emitir_guarda_so_o_hash`: o código devolvido não aparece em nenhuma coluna da linha; `codigo_hash == sha256(codigo).hexdigest()`.
  - `test_queimar_certo_devolve_o_usuario_uma_vez`: 1ª chamada → `"u-1"`, 2ª → `None`.
  - `test_verificador_errado_queima`: errado → `None`; depois o certo → `None`.
  - `test_vencido_nao_vale` (expira_em no passado → `None`).
  - `test_codigo_desconhecido_none`.
- [ ] **Step 2:** `pytest tests/test_bandeja_codigo.py -v` → FAIL.
- [ ] **Step 3:** implementar. `queimar` lê a linha e depois grava `usado_em`; comentário `shortcut: ler-e-marcar não é atômico; dois pedidos simultâneos com o mesmo verificador passariam — só a bandeja que abriu tem o verificador. Trocar por UPDATE ... WHERE usado_em IS NULL RETURNING se o código passar a ter outro uso.`
- [ ] **Step 4:** PASS.
- [ ] **Step 5:** commit `feat(bandeja): codigo de uso unico amarrado ao desafio`.

### Tarefa 3: Fluxo web "de bandeja" no portal

**Files:**
- Modify: `app/rotas/microsoft.py`
- Test: `tests/test_bandeja_microsoft_rotas.py` (reusa fixtures `ligado`, `banco`, `troca`, `_ident` de `tests/test_login_microsoft_rotas.py` por import)

**Interfaces:**
- Consumes: `bandeja_codigo.emitir(user_id, desafio) -> str`.
- Produces:
  - `GET /entrar/microsoft/bandeja?porta=<int>&desafio=<str>` — 404 sem `configurado()`; 400 se `porta` fora de 1024–65535 ou `desafio` não casa `^[A-Za-z0-9_-]{43}$`; senão o mesmo 302 + `cg_ms` de `/entrar/microsoft`, com o JWT carregando também `"bandeja": {"porta": <int>, "desafio": <str>}`.
  - Extrair `_iniciar(request: Request, extra: dict) -> Response` usado pelas duas idas.
  - `_volta_bandeja(porta: int, request: Request, codigo: Optional[str] = None, erro: Optional[str] = None) -> HTMLResponse` — 200, `Cache-Control: no-store`, apaga o `cg_ms`, `<meta http-equiv="refresh" content="0;url=http://127.0.0.1:<porta>/?codigo=<c>">` (ou `?erro=<chave>`), **e** um `<a href>` para o mesmo endereço. Texto do corpo: sucesso `"Pronto, pode voltar para a bandeja."`; erro: `MENSAGENS_ERRO[chave]`. Valores com `urllib.parse.quote` + `html.escape`.
  - No retorno: ler o `cg_ms` **antes** do `access_denied`; se o pedido tem `bandeja`, todo desvio vai para `_volta_bandeja(..., erro=<chave do conjunto MENSAGENS_ERRO>)` e o sucesso para `_volta_bandeja(..., codigo=emitir(user["id"], desafio))`, **sem** `_abrir_sessao`. Sucesso registra `EVENTO_LOGIN` com `contexto={"metodo": "microsoft_bandeja"}`; recusas registram como hoje, com `"metodo": "microsoft_bandeja"` no contexto. Conta criada → mesmo evento e `_avisar_admins`. Falha de `emitir` → `erro="falha"`.

- [ ] **Step 1: Testes:**
  - `test_ida_da_bandeja_guarda_porta_e_desafio`: 302 para a Microsoft; o `cg_ms` decodificado tem `bandeja == {"porta": 50123, "desafio": D}` e `typ == "cg_ms"`.
  - `test_ida_da_bandeja_recusa_porta_e_desafio_ruins` (parametrizado: `porta=80`, `porta=70000`, `desafio="curto"`) → 400.
  - `test_ida_da_bandeja_desligada_404` (sem variáveis).
  - `test_retorno_da_bandeja_emite_codigo_sem_sessao`: 200; `url=http://127.0.0.1:50123/?codigo=` no meta refresh e no `href`; sem cookie `cg_sessao` na resposta; uma linha em `bandeja_codigo` com `desafio == D` e `user_id == "u-ana"`; `user_activity` tem `login` com `metodo == "microsoft_bandeja"`.
  - `test_retorno_da_bandeja_cancelado_volta_ao_loopback`: `error=access_denied` → `?erro=cancelada`, sem linha em `bandeja_codigo`.
  - `test_retorno_da_bandeja_recusada_volta_ao_loopback`: `resolver_conta` devolve `Recusa("convidado")` → `?erro=recusada`.
  - `test_retorno_do_site_continua_abrindo_sessao`: `cg_ms` sem `bandeja` → comportamento da entrega 1 (`_entra_direto`).
- [ ] **Step 2:** `pytest tests/test_bandeja_microsoft_rotas.py -v` → FAIL.
- [ ] **Step 3:** implementar.
- [ ] **Step 4:** `pytest tests/test_bandeja_microsoft_rotas.py tests/test_login_microsoft_rotas.py -v` → PASS.
- [ ] **Step 5:** commit `feat(bandeja): fluxo da Microsoft com volta pela propria maquina`.

### Tarefa 4: Virada automática e bloqueio da senha na bandeja

**Files:**
- Create: `app/bandeja_virada.py`
- Modify: `app/rotas/agente.py` (`registrar_dispositivo`), `app/main.py` (`microsoft_loop`)
- Test: `tests/test_bandeja_virada.py`

**Interfaces:**
- Produces:
  - `VERSAO_NOVA = (1, 2, 0)`, `JANELA_DIAS = 30`, `TABELA = "bandeja_virada"`.
  - `situacao(dispositivos: list[dict], agora: datetime) -> dict` — pura: `{"na_nova": int, "segurando": list[dict]}`. Conta só linhas sem `revogado_em`, com `visto_em >= agora - 30 dias`, `versao` começando com `certguard-` e parte numérica válida (`agent_devices._versao_tupla`). `segurando` = as que estão abaixo de `VERSAO_NOVA`.
  - `pronta(s: dict) -> bool` — `s["na_nova"] >= 1 and not s["segurando"]`.
  - `desligada_em(sb: Any = None) -> Optional[str]` — lê a linha `id = 1`; qualquer erro (tabela ausente, sem banco) → `None` com `logger.warning`.
  - `senha_bloqueada(email: str) -> bool` — `configurado() and dominio_liberado(email) and desligada_em() is not None`.
  - `conferir(sb: Any = None) -> dict` — sem `configurado()` → `{"ligada": False}`; já desligada → `{"desligada_em": ...}`; senão calcula com as linhas cruas de `agent_devices` (`select("id, user_id, machine_id, nome, versao, visto_em, revogado_em")`); se `pronta`, `insert({"id": 1, "versao": "1.2.0"})`. Só quem inseriu manda **um** e-mail pelo `microsoft_conferencia._enviar_ti("A senha da bandeja foi desligada para os domínios da Microsoft", [f"Desligada em {dd/mm/aaaa HH:MM}.", f"Domínios: {', '.join(sorted(config.MICROSOFT_DOMINIOS))}.", "Quem é de fora dos domínios continua com e-mail e senha."])`. Insert que falha (outro processo inseriu: a chave primária é a trava) → relê e não manda e-mail.
- Em `registrar_dispositivo`, logo depois dos dois `taxa.permitir` e antes de `_conferir_credenciais`: se `bandeja_virada.senha_bloqueada(email_alvo)`, registrar `EVENTO_LOGIN_NEGADO` (`user_id=None`, `user_email=email_alvo`, `contexto={"motivo": "bandeja_so_microsoft"}`) e `HTTPException(403, "Use Entrar com a Microsoft.")`.
- Em `microsoft_loop`, depois de `conferir_todas`: `await loop.run_in_executor(None, bandeja_virada.conferir)` em `try` próprio (falha dela não derruba a conferência, e vice-versa).

- [ ] **Step 1: Testes** (`agora` fixo; linhas montadas à mão):
  - `test_hardlyze_e_nulas_nao_contam`: `[certguard-1.2.0, "2.2.0", None]` → `na_nova == 1`, `segurando == []`, `pronta`.
  - `test_antiga_recente_segura`: `certguard-1.1.1` visto há 3 dias → em `segurando`.
  - `test_antiga_revogada_ou_velha_nao_segura`: revogada, ou vista há 31 dias → fora.
  - `test_frota_vazia_nao_vira`: só Hardlyze → `not pronta`.
  - `test_versao_acima_conta_como_nova`: `certguard-1.3.0` → `na_nova == 1`.
  - `test_conferir_vira_uma_vez_e_avisa_uma_vez`: duas chamadas → uma linha em `bandeja_virada`, `_enviar_ti` chamado 1 vez (monkeypatch).
  - `test_conferir_desligada_sem_configuracao` → `{"ligada": False}`, nada gravado.
  - `test_registrar_depois_da_virada_403_antes_da_senha` (parametrizado: conta existente + senha certa, existente + errada, e-mail inexistente do domínio): 403 com `detail == "Use Entrar com a Microsoft."` e `_conferir_credenciais` não chamado (monkeypatch que levanta).
  - `test_registrar_fora_do_dominio_segue`: `fulano@gmail.com` com virada → não 403 da virada.
  - `test_registrar_sem_configuracao_ignora_a_marca`: marca gravada, variáveis vazias → passa para a conferência da senha.
- [ ] **Step 2:** `pytest tests/test_bandeja_virada.py -v` → FAIL.
- [ ] **Step 3:** implementar.
- [ ] **Step 4:** `pytest tests/test_bandeja_virada.py tests/test_login_microsoft_obrigacao.py -v` → PASS.
- [ ] **Step 5:** commit `feat(bandeja): senha da bandeja desliga sozinha quando a frota atualiza`.

### Tarefa 5: Rotas que a bandeja chama e painel

**Files:**
- Modify: `app/rotas/agente.py`, `app/rotas/computadores.py` (`listar_computadores`), `templates/usuarios.html` (aba Computadores)
- Test: `tests/test_bandeja_microsoft_registro.py`

**Interfaces:**
- Consumes: `bandeja_codigo.queimar(codigo, verificador) -> Optional[str]`; `bandeja_virada.situacao`, `bandeja_virada.desligada_em`.
- Produces:
  - `GET /api/agent/microsoft` → `{"ligado": microsoft_entra.configurado()}` (pública).
  - Extrair de `registrar_dispositivo` `_concluir_registro(user: dict, machine_id: str, nome: Optional[str], chave_maquina: Optional[str]) -> dict` — tudo de `machine_id = computadores.mac(...)` até o `return` (mesmos 400/409/500/403 `X-Confirmacao-Pendente` e o mesmo corpo).
  - `RegistrarPelaMicrosoftBody(codigo: str ≤128, verificador: str ≤128, machine_id: str ≤128, nome: Optional[str] ≤128, chave_maquina: Optional[str] ≤256)`.
  - `POST /api/agent/dispositivos/registrar-microsoft` — 404 sem `configurado()`; `taxa.permitir(f"login:{ip}", 20, 60)` senão 429; `queimar` → `None` = 401 `"A entrada pela Microsoft expirou. Clique de novo em Entrar com a Microsoft."`; usuário lido por id; inativo (`auth.conta_ativa`) = 403 `"Esta conta está desativada. Procure um administrador."`; senão `_concluir_registro(...)`. Sem checagem de senha provisória (a senha não entra).
  - `/api/computadores` → `resumo["bandeja"] = {"desligada_em": str|None, "segurando": [{"nome", "machine_id", "versao", "email"}]}` só com `configurado()`.
  - `usuarios.html`, aba Computadores, acima da lista: antes da virada, "A senha da bandeja dos domínios desliga quando estes computadores chegarem à versão 1.2.0:" + lista (nome, pessoa, versão), ou "Aguardando a primeira bandeja na versão 1.2.0." quando `segurando` vazio e não virou; depois, "Senha da bandeja desligada em dd/mm/aaaa." Forma visual: classes `.ag-*` já usadas na aba.

- [ ] **Step 1: Testes:**
  - `test_microsoft_ligado_reflete_a_configuracao` (ligado/desligado).
  - `test_registrar_microsoft_devolve_o_mesmo_corpo`: código emitido com `emitir`, verificador certo → 200 com `segredo`, `machine_id`, `email`, `role`, `autorizacao`, `mensagem` (mesmas chaves de `/registrar`).
  - `test_registrar_microsoft_codigo_reusado_401`.
  - `test_registrar_microsoft_conta_desativada_403`.
  - `test_registrar_microsoft_confirmacao_pendente_igual`: `computadores.entrar` devolve `(None, ...)` → 403 com `X-Confirmacao-Pendente: 1`.
  - `test_registrar_microsoft_desligado_404`.
  - `test_registrar_por_senha_inalterado`: os testes existentes de `/registrar` passam sem mudança (rodar `tests/test_computadores_rotas.py`).
  - `test_computadores_mostra_quem_segura_a_virada`: um `certguard-1.1.1` recente aparece em `resumo.bandeja.segurando`.
- [ ] **Step 2:** `pytest tests/test_bandeja_microsoft_registro.py -v` → FAIL.
- [ ] **Step 3:** implementar.
- [ ] **Step 4:** `pytest tests/test_bandeja_microsoft_registro.py tests/test_computadores_rotas.py tests/test_helpers_compartilhados.py -v` → PASS.
- [ ] **Step 5:** commit `feat(bandeja): registro pelo codigo da Microsoft e contador da virada`.

### Tarefa 6: Ouvinte loopback e chamadas da bandeja

**Files:**
- Create: `estacao/login_microsoft.py`
- Modify: `estacao/conta.py`
- Test: `tests/test_estacao_login_microsoft.py`

**Interfaces:**
- Produces (`estacao/login_microsoft.py`):
  - `PRAZO_S = 300`
  - `MENSAGENS: dict[str, str]` — as quatro de `app/rotas/microsoft.py` `MENSAGENS_ERRO`, copiadas, mais `"prazo": "O navegador não voltou a tempo. Tente de novo."`.
  - `novo_verificador() -> tuple[str, str]` — `(verificador, desafio)`; verificador `secrets.token_urlsafe(48)`, desafio igual a `app.bandeja_codigo.desafio_de` (reimplementado: a bandeja não importa `app`).
  - `class Ouvinte` — `__init__(self, prazo_s: float = PRAZO_S)` liga em `("127.0.0.1", 0)`; `_servidor: HTTPServer`; `porta: int`; `esperar(self) -> dict[str, str]` devolve `{"codigo": ...}` ou `{"erro": <chave>}` (prazo → `{"erro": "prazo"}`) e fecha o socket; só `GET /` com `codigo` ou `erro` encerra a espera (responde 200 com "Pronto, pode voltar para a bandeja." ou a mensagem); qualquer outro caminho → 404 e continua esperando. `http.server.HTTPServer` + `handle_request` em laço com `timeout`; log de acesso desligado.
  - `url_de_entrada(portal: str, porta: int, desafio: str) -> str`.
  - `entrar(portal: str, abrir: Callable[[str], Any] = webbrowser.open, prazo_s: float = PRAZO_S) -> tuple[str, str]` — `(codigo, verificador)`; erro → `RuntimeError(MENSAGENS[chave])`.
- Produces (`estacao/conta.py`):
  - `microsoft_ligada(sessao, portal: str) -> bool` — `GET {portal}/api/agent/microsoft`, timeout 5; qualquer falha → `False`.
  - `registrar_pela_microsoft(sessao, portal, codigo, verificador, machine_id, nome="", chave_maquina=None) -> dict` — mesmo retorno de `registrar`; extrair o fim comum `_guardar_resposta(r, base, email, machine_id) -> dict`.

- [ ] **Step 1: Testes** (sem Tk; o "navegador" é um `abrir` falso que faz `urllib.request.urlopen` no loopback numa thread):
  - `test_desafio_da_bandeja_igual_ao_do_portal`: o desafio de `novo_verificador()` é igual a `app.bandeja_codigo.desafio_de(verificador)`.
  - `test_ouvinte_so_em_loopback`: `ouvinte._servidor.server_address[0] == "127.0.0.1"`.
  - `test_entrar_devolve_codigo`: `abrir` chama `/?codigo=abc` → `("abc", verificador)` e a URL aberta contém `porta=` e `desafio=`.
  - `test_favicon_nao_encerra`: `abrir` pede `/favicon.ico` (404) e depois `/?codigo=abc` → `"abc"`.
  - `test_erro_do_portal_vira_mensagem`: `/?erro=cancelada` → `RuntimeError("Entrada pela Microsoft cancelada.")`.
  - `test_prazo_esgota`: `prazo_s=0.5`, `abrir` não faz nada → `RuntimeError` com a mensagem de `"prazo"`; a porta fecha (novo `connect` falha).
  - `test_registrar_pela_microsoft_guarda_a_conta` e `test_microsoft_ligada_falha_vira_false` com sessão falsa, no molde de `tests/test_estacao.py`.
- [ ] **Step 2:** `pytest tests/test_estacao_login_microsoft.py -v` → FAIL.
- [ ] **Step 3:** implementar.
- [ ] **Step 4:** `pytest tests/test_estacao_login_microsoft.py tests/test_estacao.py -v` → PASS.
- [ ] **Step 5:** commit `feat(estacao): volta da Microsoft pelo 127.0.0.1 da estacao`.

### Tarefa 7: Botão na janela, versão 1.2.0 e roteiro

**Files:**
- Modify: `estacao/janela_login.py`, `estacao/bandeja.py` (`on_login`), `estacao/__init__.py`, `docs/login-microsoft.md`
- Test: `tests/test_janela_login.py`

**Interfaces:**
- Consumes: `login_microsoft.entrar`, `conta.microsoft_ligada`, `conta.registrar_pela_microsoft`.
- Produces:
  - `abrir_janela(ao_registrar, portal, machine_id, ao_concluir=None, ao_microsoft: Callable[[], Any] | None = None)` — com `ao_microsoft`, no topo o botão "Entrar com a Microsoft" com o logo de quatro quadrados (Canvas 14×14: `#f25022`, `#7fba00`, `#00a4ef`, `#ffb900`), e o texto de apoio passa a "E-mail da empresa: use Entrar com a Microsoft. Os demais: e-mail e senha do portal."; janela `440x400`. O clique desabilita os dois botões, roda `ao_microsoft` em thread e reusa `_conseguiu`/`_falhou`. Sem `ao_microsoft`, a janela é a de hoje.
  - `mensagem_de_falha` devolve o texto do portal para `"Use Entrar com a Microsoft."` e para as mensagens de `login_microsoft.MENSAGENS` (não cai no ramo "incorretos").
  - `on_login`: `ms = conta.microsoft_ligada(http, portal)` antes de abrir; `_microsoft()` = `entrar(portal)` → `registrar_pela_microsoft(..., nome=COMPUTERNAME or mid, chave_maquina=chave_maquina.ler())`; `ao_microsoft=_microsoft if ms else None`.
  - `VERSAO = "1.2.0"`.
  - `docs/login-microsoft.md`: seção "Entrega 2: bandeja pela Microsoft" com a ordem de produção — (1) push + `atualizar-portal` (aplica `20261106100000_bandeja_pela_microsoft.sql`); (2) publicar a 1.2.0 com `scripts/versoes_certguard.py` pelo Robério; (3) acompanhar Usuários › Computadores; (4) a virada acontece sozinha e manda e-mail ao TI; (5) para voltar a senha de todos: tirar as variáveis `MICROSOFT_*` (mesma chave geral da entrega 1). Mais a nota do loopback: só estações, uma pessoa por sessão.

- [ ] **Step 1: Testes:**
  - `test_mensagem_use_microsoft_passa_intacta`: `mensagem_de_falha(RuntimeError("Use Entrar com a Microsoft.")) == "Use Entrar com a Microsoft."`.
  - `test_mensagens_da_microsoft_passam_intactas` (parametrizado sobre `login_microsoft.MENSAGENS.values()`).
  - `test_versao_reportada_e_a_nova`: `VERSAO_REPORTADA == "certguard-1.2.0"` e `agent_devices._versao_tupla("1.2.0") == bandeja_virada.VERSAO_NOVA` (a bandeja e a virada não podem divergir).
- [ ] **Step 2:** `pytest tests/test_janela_login.py -v` → FAIL.
- [ ] **Step 3:** implementar; conferir na mão, numa estação de teste, que a janela abre com o botão e que, com `CERT_PORTAL_URL` apontando para um portal sem as variáveis, o botão some.
- [ ] **Step 4:** suíte inteira `pytest -q` → PASS.
- [ ] **Step 5:** commit `feat(estacao): botao Entrar com a Microsoft na bandeja 1.2.0`.

---

## Depois das tarefas

- Revisor independente sobre o diff inteiro (desde `f878de0`) antes de pedir o push.
- Push só com autorização. Produção: Robério roda `atualizar-portal`, publica a 1.2.0 e testa numa máquina: botão → navegador → "Pronto" → bandeja conectada; e-mail + senha de domínio continua entrando até a virada.
