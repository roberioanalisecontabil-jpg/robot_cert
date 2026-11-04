# Login pela Microsoft — entrega 1 (site) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** O site do CertGuard aceita "Entrar com a Microsoft" para os quatro domínios liberados, obriga esses domínios a entrar só por ela (com porta reserva senha + app para administradores), cria conta no 1º acesso e desativa a conta inteira em até 5 minutos quando a Microsoft diz que ela foi bloqueada.

**Architecture:** OIDC código de autorização + PKCE contra o locatário único, falado direto com `httpx` (sem dependência nova). Um módulo puro fala com a Microsoft (`app/microsoft_entra.py`), outro decide a conta (`app/login_microsoft.py`), um router novo tem as duas rotas do navegador, e um laço no `lifespan` renova a chave de cada conta a cada 5 min (`app/microsoft_conferencia.py`). A bandeja (entrega 2) não muda aqui: `_conferir_credenciais` continua igual para ela.

**Tech Stack:** FastAPI, psycopg/`_banco()` fake nos testes, httpx (`MockTransport` nos testes), python-jose (state cookie), `app.smtp_service.encrypt_password` (cifra da chave de renovação, a mesma do TOTP), Jinja.

**Spec:** `docs/superpowers/specs/2026-11-04-login-microsoft-design.md`

## Global Constraints

- Domínios liberados vêm de `MICROSOFT_DOMINIOS` (lista separada por vírgula, minúsculas); valor de produção: `analisegroup.cnt.br,analisecontabil.cnt.br,ndevolution.com.br,analisegestao.com.br`. `varejoconectado` nunca entra.
- `MICROSOFT_CONFERENCIA`: `simular` (padrão, também quando ausente ou inválida) ou `aplicar`. Em `simular`, a conferência nunca desativa: só manda ao TI quem seria desativado e o código `AADSTS`.
- Desligável: faltando qualquer um de `MICROSOFT_TENANT_ID`, `MICROSOFT_CLIENT_ID`, `MICROSOFT_CLIENT_SECRET`, `MICROSOFT_DOMINIOS`, `PORTAL_BASE_URL`, o botão não aparece, a obrigação não vale e o laço não roda.
- Retorno fixo: `{PORTAL_BASE_URL}/entrar/microsoft/retorno` (nunca do cabeçalho Host).
- Escopos: `openid profile email offline_access User.Read`. Nada de `User.Read.All`.
- Sem dependência nova em `requirements.txt`.
- Nenhum convite de senha é enviado a ninguém (Acessórias inclusive).
- A bandeja continua com a senha (`_conferir_credenciais` não muda); a única regra nova dela está na Task 5: conta de domínio liberado precisa estar ligada à Microsoft para registrar bandeja nova.
- Mudou `static/*.js`/`.css` ou JS do template: trocar o `?v=` nos templates.
- Migration: só escrever e ensaiar em cópia local; quem aplica no servidor é o Robério. Ordem de implantação: código → migration → `.sql`.
- Commits pelo hook (suíte inteira); correção e `git commit` em comandos separados; mensagem por arquivo (`git commit -F`). Sem push sem autorização. Revisor independente antes do push.
- Textos (exatos):
  - `ENTRE_PELA_MICROSOFT = "Entre pela Microsoft."`
  - recusa (domínio/convidado/oid diferente/ambíguo): `"Não foi possível entrar com essa conta da Microsoft. Procure o TI."`
  - conta desativada: `"Sua conta está desativada. Procure o TI."`
  - falha técnica: `"Não foi possível entrar com a Microsoft agora. Tente de novo ou procure o TI."`
  - cancelada: `"Entrada pela Microsoft cancelada."`
  - Auditoria (`contexto["metodo"]`): `microsoft`, `senha`, `senha_e_app`; criação: evento `conta_criada_microsoft`; desativação: `desativada_microsoft`.

## Review Focus

1. Pessoa cancela na tela da Microsoft (`?error=access_denied`) → volta ao `/login` com "Entrada pela Microsoft cancelada.", sem 500. Teste na Task 4.
2. Cookie de estado ausente/vencido (retorno aberto em outro navegador, >10 min, botão Voltar) → `/login` com a falha técnica, nada gravado. Teste na Task 4.
3. UPN em maiúsculas ou com espaço (`Bruno@AnaliseGroup.cnt.br`) liga à conta `bruno@analisegroup.cnt.br`. Teste na Task 3.
4. Duplo clique / duas abas no 1º acesso → uma conta só (o `INSERT` usa `ON CONFLICT DO NOTHING` e relê). Teste na Task 3.
5. Microsoft lenta, 429 ou 5xx durante a conferência → ninguém desativado, chave antiga mantida, TI avisado uma vez por hora no máximo. Teste na Task 6.

---

### Task 1: Migration das colunas da Microsoft

**Files:**
- Create: `supabase/migrations/20261105100000_login_microsoft.sql`
- Test: `tests/test_migration_login_microsoft.py` (mesmo estilo de `tests/test_migration_acessorias_sincronizada.py`)

**Interfaces:**
- Produces (colunas em `public.users`): `microsoft_oid text` (índice único parcial `users_microsoft_oid_unico ... WHERE microsoft_oid IS NOT NULL`), `microsoft_refresh_cifrado text`, `microsoft_conferido_em timestamptz`, `microsoft_sem_conferencia boolean NOT NULL DEFAULT false`, `desativada_pela_microsoft_em timestamptz`. Restrição `users_origem_valida` recriada com `CHECK (origem IN ('manual', 'acessorias', 'microsoft'))`.

- [ ] **Step 1: Teste** `test_migration_login_microsoft_idempotente_e_completa`: o texto do `.sql` tem `ADD COLUMN IF NOT EXISTS` para as 5 colunas, `DROP CONSTRAINT IF EXISTS users_origem_valida` antes do `ADD CONSTRAINT ... 'microsoft'`, `CREATE UNIQUE INDEX IF NOT EXISTS users_microsoft_oid_unico`, e termina com o `SELECT` de conferência (padrão das migrations do projeto: cabeçalho "COMO USAR", passos numerados, ASCII).
- [ ] **Step 2:** `.venv\Scripts\python.exe -m pytest tests/test_migration_login_microsoft.py -v` → FAIL (arquivo não existe).
- [ ] **Step 3:** Escrever o `.sql`.
- [ ] **Step 4:** Teste → PASS. Ensaiar duas vezes em cópia local (`certguard_leva`, `postgresql://postgres@127.0.0.1:5432/certguard_leva`): a 2ª rodada não pode dar erro.
- [ ] **Step 5:** Commit `feat(login): migration das colunas da Microsoft`.

### Task 2: Cliente da Microsoft (`app/microsoft_entra.py`)

**Files:**
- Create: `app/microsoft_entra.py`
- Modify: `app/config.py` (ler as 4 variáveis `MICROSOFT_*`; `MICROSOFT_DOMINIOS` como `frozenset` em minúsculas)
- Test: `tests/test_microsoft_entra.py`

**Interfaces:**
- Produces:
  - `configurado() -> bool`
  - `dominio_liberado(email: str) -> bool` (minúsculas, `strip`, domínio exato após o último `@`; subdomínio não vale)
  - `url_de_autorizacao(state: str, nonce: str, verificador: str) -> str` (PKCE S256, `response_mode=query`, `prompt=select_account`)
  - `@dataclass Identidade: oid: str; tid: str; upn: str; email: str; nome: str; convidado: bool`
  - `trocar_codigo(codigo: str, verificador: str, nonce: str, cliente: httpx.Client | None = None) -> tuple[Identidade, str]` (devolve a identidade e o refresh token; levanta `FalhaMicrosoft` em qualquer erro)
  - `@dataclass Renovacao: resultado: Literal["ok", "bloqueada", "sem_conferencia", "falha"]; refresh_novo: str | None; codigo_aadsts: str | None`
  - `renovar(refresh: str, cliente: httpx.Client | None = None) -> Renovacao`
  - `class FalhaMicrosoft(Exception)`

- [ ] **Step 1: Testes** (httpx `MockTransport`, sem rede):
  - `test_desligado_sem_qualquer_variavel`: cada uma das 5 variáveis ausente → `configurado() is False`.
  - `test_dominio_liberado`: `"Bruno@AnaliseGroup.cnt.br "` → True; `"x@varejoconectado.com.br"`, `"x@gmail.com"`, `"x@sub.analisegroup.cnt.br"` → False.
  - `test_url_tem_pkce_state_nonce_e_retorno_fixo`: query tem `code_challenge_method=S256`, `state`, `nonce`, `redirect_uri=https://certificado.analisegroup.cnt.br/entrar/microsoft/retorno`, `scope` com `offline_access`.
  - `test_trocar_codigo_confere_claims`: id_token com `aud` ≠ client id, `tid` ≠ locatário, `iss` ≠ `https://login.microsoftonline.com/{tid}/v2.0`, `nonce` diferente ou `exp` passado → `FalhaMicrosoft` (um caso por parâmetro).
  - `test_assinatura_conferida`: id_token assinado por uma chave RSA de teste servida no JWKS falso → aceito; assinado por outra chave, `alg` ≠ `RS256`, ou `kid` ausente do JWKS (depois de rebaixar uma vez) → `FalhaMicrosoft`.
  - `test_jwks_em_cache_24h`: duas trocas seguidas fazem uma busca só ao JWKS; `kid` desconhecido força uma nova busca (no máximo 1 a cada 5 min).
  - `test_convidado_detectado`: `preferred_username` com `#EXT#` → `convidado=True`.
  - `test_renovar_classifica`: corpo de erro com `AADSTS50057` ou `AADSTS50034` → `bloqueada`; `AADSTS50173`, `AADSTS70043`, `AADSTS700082`, outro `invalid_grant` → `sem_conferencia`; `AADSTS7000215`, `AADSTS7000222`, `AADSTS700016`, HTTP 429/5xx, `httpx.TimeoutException` → `falha`; 200 → `ok` com `refresh_novo`.
- [ ] **Step 2:** Rodar → FAIL.
- [ ] **Step 3:** Implementar. Assinatura conferida com `jose.jwt.decode(..., algorithms=["RS256"], audience=client_id, issuer=...)` contra as chaves de `https://login.microsoftonline.com/{tid}/discovery/v2.0/keys`, em cache de processo por 24 h. Depois conferir `tid` e `nonce`. Timeout 10 s. Falha ao baixar o JWKS → `FalhaMicrosoft` (nunca aceitar sem conferir).
- [ ] **Step 4:** Rodar → PASS.
- [ ] **Step 5:** Commit `feat(login): cliente OIDC da Microsoft`.

### Task 3: Qual conta entra (`app/login_microsoft.py`)

**Files:**
- Create: `app/login_microsoft.py`
- Test: `tests/test_login_microsoft_conta.py` (fake de `tests/test_recuperacao_de_senha._Fake`)

**Interfaces:**
- Consumes: `Identidade`, `dominio_liberado` (Task 2); `acessorias._hash_sem_senha()`.
- Produces:
  - `@dataclass Recusa: motivo: Literal["dominio", "convidado", "oid_diferente", "ambiguo", "desativada"]`
  - `resolver_conta(sb, ident: Identidade, refresh: str) -> tuple[dict, bool] | Recusa` — devolve `(user, criada)`; grava `microsoft_oid` (só se nulo), `microsoft_refresh_cifrado` (`encrypt_password`), `microsoft_conferido_em = now()`, `microsoft_sem_conferencia = false`.
  - `pode_usar_reserva(user: dict) -> bool` — `role == "admin"`, ativo, `microsoft_oid` não nulo, `totp_ativado_em` não nulo.

Regras, nesta ordem: convidado → `convidado`; nem `upn` nem `email` em domínio liberado → `dominio`; conta com o `oid` → é ela; senão procurar por `lower(strip(upn))` e por `lower(strip(email))`: duas contas diferentes → `ambiguo`; uma conta com `microsoft_oid` de outro → `oid_diferente`; nenhuma → criar (`origem='microsoft'`, `role='user'`, `ativo=true`, `full_name=ident.nome`, sem departamento, `password_hash=_hash_sem_senha()`, `INSERT ... ON CONFLICT DO NOTHING` e reler pelo e-mail). Conta encontrada desativada → `desativada` (nada gravado).

- [ ] **Step 1: Testes:** `test_liga_conta_existente_pelo_upn_maiusculo` (Review Focus 3); `test_cria_conta_operador_sem_departamento_origem_microsoft` (`criada is True`, `role == "user"`, `origem == "microsoft"`, `departamento_id is None`); `test_segundo_login_acha_pelo_oid_mesmo_com_email_trocado`; `test_upn_e_email_em_contas_diferentes_recusa_ambiguo`; `test_oid_diferente_recusa`; `test_convidado_recusa`; `test_dominio_fora_recusa` (`@varejoconectado.com.br`); `test_desativada_recusa_sem_gravar`; `test_duas_chamadas_seguidas_criam_uma_conta` (Review Focus 4); `test_refresh_gravado_cifrado` (valor no banco ≠ refresh e `decrypt_password` devolve o original); `test_pode_usar_reserva` (só admin com oid e app).
- [ ] **Step 2:** Rodar → FAIL. **Step 3:** Implementar. **Step 4:** PASS.
- [ ] **Step 5:** Commit `feat(login): ligar ou criar a conta pela Microsoft`.

### Task 4: Rotas do navegador e botão no login

**Files:**
- Create: `app/rotas/microsoft.py` (registrar em `app/main.py` junto dos outros routers)
- Modify: `app/rotas/usuarios.py:134` (`_abrir_sessao(..., metodo: str = "senha")` grava `contexto={"metodo": metodo}`)
- Modify: `app/atividade.py` (`EVENTO_CONTA_CRIADA_MICROSOFT = "conta_criada_microsoft"`, `EVENTO_DESATIVADA_MICROSOFT = "desativada_microsoft"`; rótulos da tela de Auditoria: "Entrou pela Microsoft", "Entrou com a senha", "Entrou com senha e app autenticador", "Conta criada pela Microsoft", "Desativado: conta bloqueada na Microsoft")
- Modify: `app/main.py:472` (`pagina_login` passa `microsoft=microsoft_entra.configurado()` ao template)
- Modify: `templates/login.html` (botão "Entrar com a Microsoft" acima do formulário, só `{% if microsoft %}`; mensagem pelo `?erro_ms=` mapeado no template — nunca texto vindo da URL; trocar `?v=`)
- Test: `tests/test_login_microsoft_rotas.py`

**Interfaces:**
- Consumes: Tasks 2 e 3; `usuarios._abrir_sessao`; `alert_state._get_admin_emails()`; `correio.send_smtp_email` (mesmo padrão de `_enviar_codigo_de_login`).
- Produces: `GET /entrar/microsoft` → 302 para a Microsoft + cookie `cg_ms` (HttpOnly, Secure, SameSite=Lax, 10 min, JWT HS256 com `JWT_SECRET_KEY` contendo `state`, `nonce`, `verificador`); `GET /entrar/microsoft/retorno` → 302 para `/` com a sessão, ou para `/login?erro_ms=<cancelada|recusada|desativada|falha>`. Apaga `cg_ms` sempre. Desligado → 404 nas duas.

- [ ] **Step 1: Testes** (monkeypatch em `microsoft_entra.trocar_codigo`): `test_desligado_404_e_sem_botao`; `test_inicio_grava_cookie_e_redireciona`; `test_retorno_abre_sessao_e_audita_metodo_microsoft` (cookie `cg_sessao` presente, `user_activity` com `contexto.metodo == "microsoft"`); `test_retorno_sem_codigo_pedido_mesmo_se_LOGIN_EXIGE_CODIGO`; `test_state_diferente_falha`; `test_cookie_ausente_ou_vencido_falha_sem_gravar` (Review Focus 2); `test_access_denied_cancelada` (Review Focus 1); `test_recusa_e_desativada_mapeadas`; `test_conta_criada_avisa_admins` (um e-mail por admin, assunto `"Conta nova pela Microsoft: <nome>"`, em segundo plano; falha de envio não derruba o login); `test_pagina_login_mostra_botao_so_configurado`; `test_erro_ms_desconhecido_nao_reflete_texto`.
- [ ] **Step 2:** FAIL. **Step 3:** Implementar. **Step 4:** PASS.
- [ ] **Step 5:** Conferir a tela em `http://127.0.0.1:8079/login` (portal local contra `certguard_leva`) claro/escuro e 390 px de largura; botão no padrão Águia DS do login.
- [ ] **Step 6:** Commit `feat(login): entrar com a Microsoft no site`.

### Task 5: Obrigação dos domínios e porta reserva dos admins

**Files:**
- Modify: `app/rotas/usuarios.py:214` (`login`), `:188` (`_pedir_codigo(..., so_app: bool = False)`), `:263` (`entrar_com_codigo`)
- Modify: `app/login_codigo.py` (`criar_desafio(user, so_app: bool = False)` grava `so_app` no desafio; `desafio_so_app(desafio) -> bool`)
- Test: `tests/test_login_microsoft_obrigacao.py`

**Interfaces:**
- Consumes: `microsoft_entra.configurado`, `dominio_liberado`; `login_microsoft.pode_usar_reserva`.

Regra em `login`, depois do teto por IP: se `configurado()` e `dominio_liberado(body.email)`: roda `_conferir_credenciais` (o bcrypt sempre, mesmo tempo); se a senha falhar **ou** a conta não puder usar a reserva → 403 `ENTRE_PELA_MICROSOFT` (mesma resposta nos dois casos: não revela se a senha estava certa); se puder → `_pedir_codigo(user, request, background, so_app=True)` (não manda e-mail, ignora navegador lembrado). Em `entrar_com_codigo`: desafio `so_app` com `metodo != "app"` → 400 `CODIGO_DE_LOGIN_INVALIDO`; `lembrar` ignorado; `_abrir_sessao(..., metodo="senha_e_app")`. Fora dos domínios: tudo como hoje.

- [ ] **Step 1: Testes:** `test_dominio_operador_senha_certa_403`; `test_dominio_senha_errada_403_igual`; `test_dominio_sem_configuracao_entra_como_hoje`; `test_admin_reserva_pede_so_app_sem_email` (nenhum e-mail enviado, `app_autenticador is True`); `test_admin_reserva_metodo_email_recusado`; `test_admin_reserva_ignora_navegador_lembrado` (com `cg_confia` válido ainda pede o app); `test_admin_sem_app_ou_sem_oid_403`; `test_admin_reserva_audita_senha_e_app`; `test_gmail_continua_com_codigo_por_email`; `test_bandeja_registrar_com_senha_de_dominio_ligada_continua` (rota de registro da bandeja, `registrar_dispositivo` em `app/rotas/agente.py`, aceita a senha da conta do domínio com `microsoft_oid`); `test_bandeja_registrar_dominio_nunca_ligado_recusa` (sem `microsoft_oid` → 403 `"Entre uma vez no site pela Microsoft para liberar a bandeja."`, audita `login_negado` motivo `microsoft_nao_ligada`); `test_bandeja_gmail_continua`; `test_bandeja_sem_configuracao_como_hoje`.

Regra da bandeja (só com `configurado()`): conta de domínio liberado sem `microsoft_oid` não registra bandeja nova com a senha. Bandeja já conectada não cai por esta regra (só pela conferência).
- [ ] **Step 2:** FAIL. **Step 3:** Implementar. **Step 4:** PASS, e `tests/test_login_com_codigo.py` inteiro continua PASS.
- [ ] **Step 5:** Commit `feat(login): dominios da Microsoft so entram por ela; reserva dos admins`.

### Task 6: Conferência a cada 5 minutos

**Files:**
- Create: `app/microsoft_conferencia.py`
- Modify: `app/main.py` (laço `microsoft_loop` no `lifespan`, igual ao `acessorias_loop`: retorna logo se `not configurado()`; `await asyncio.sleep(300)`; `run_in_executor(None, conferir_todas)`; cancelado no shutdown junto dos outros)
- Test: `tests/test_microsoft_conferencia.py`

**Interfaces:**
- Consumes: `microsoft_entra.renovar`; `decrypt_password`/`encrypt_password`.
- Produces:
  - `MAX_DESATIVACOES_POR_RODADA = 5`
  - `desativar_pela_microsoft(sb, user_id: str) -> None` — `ativo=false`, `desativada_pela_microsoft_em=now()`, apaga `departamento_lider` e `carteira_excecao` da conta, depois `papeis.derrubar_sessoes`, `computadores.sair_de_tudo(uid, "conta bloqueada na Microsoft")`, `cert_installer.revogar_tokens_pendentes`, `papeis.rederivar`; audita `EVENTO_DESATIVADA_MICROSOFT`. Nunca desativa o último admin ativo (reusar a regra de `_garantir_que_sobra_admin`; nesse caso só avisa o TI).
  - `conferir_todas(sb=None, renovar=microsoft_entra.renovar) -> dict` com chaves `ok`, `bloqueadas`, `sem_conferencia`, `falhas`, `travado: bool`, `simulado: bool`.

Simulação: com `MICROSOFT_CONFERENCIA != "aplicar"`, as bloqueadas não são desativadas; o TI recebe a lista (nome, e-mail, código `AADSTS`) uma vez por conta por dia. Refresh e `sem_conferencia` são gravados normalmente (não desativam ninguém).

Rodada: contas ativas com `microsoft_refresh_cifrado` não nulo. `ok` → grava `refresh_novo` e `microsoft_conferido_em`; `sem_conferencia` → `microsoft_sem_conferencia=true` (não desativa); `falha` → não grava nada; `bloqueada` → junta. Se houver qualquer `falha` de configuração do app (`AADSTS7000215/7000222/700016`) ou se `bloqueadas > MAX_DESATIVACOES_POR_RODADA`: não desativa ninguém, `travado=True`, e-mail ao TI (admins) com a lista — no máximo um aviso por hora (guardar o último aviso em memória do processo). Senão desativa cada bloqueada.

- [ ] **Step 1: Testes** (`renovar` falso por injeção): `test_bloqueada_desativa_tudo` (ativo false, `desativada_pela_microsoft_em` preenchido, `sessao_versao` subiu, `sair_de_tudo` chamado); `test_sem_conferencia_so_marca`; `test_ok_grava_refresh_novo`; `test_falha_rede_nao_mexe_e_avisa_uma_vez_por_hora` (Review Focus 5); `test_seis_bloqueadas_trava_e_avisa`; `test_segredo_invalido_trava`; `test_ultimo_admin_nao_desativa`; `test_conta_sem_refresh_ignorada`; `test_simular_nao_desativa_e_avisa_com_codigo`; `test_variavel_ausente_ou_invalida_simula`; `test_aplicar_desativa`.
- [ ] **Step 2:** FAIL. **Step 3:** Implementar. **Step 4:** PASS.
- [ ] **Step 5:** Commit `feat(login): conferencia da Microsoft a cada 5 minutos`.

### Task 7: Acessórias — adoção, sem reativar, sem convite

**Files:**
- Modify: `app/acessorias.py` (`carregar_estado` `:437` lê `desativada_pela_microsoft_em`; `calcular_contas` `:259`; `aplicar` `:600`; `depois_de_aplicar` `:708`; docstring do topo `:27-31`)
- Modify: `docs/adr/0005-carteira-sincronizada-pelo-acessorias.md` (adendo 04/11/2026: desativação pela Microsoft vence; conta `microsoft` adotada pelo e-mail; convite removido)
- Test: `tests/test_acessorias.py`

**Interfaces:**
- Produces: `calcular_contas(...)` devolve também `"adotar": List[Tuple[str, int]]` (id da conta, id do Acessórias).

Regras: conta `origem == "microsoft"` (não admin) com e-mail igual ao de um usuário do Acessórias → `adotar` (vira `origem='acessorias'` + `acessorias_id`, e a partir daí entra na carteira/desativação como as outras; o plano efetivo já a trata como `acessorias` na mesma aplicação). Conta com `desativada_pela_microsoft_em` não nulo nunca entra em `reativar`. `depois_de_aplicar` não cria código nem manda `_enviar_convite` (apagar `_enviar_convite` e `CONVITE_MIN` se ficarem sem uso); contas novas continuam nascendo sem senha.

- [ ] **Step 1: Testes:** `test_conta_microsoft_adotada_pelo_email`; `test_conta_microsoft_sem_email_no_acessorias_fica_manual`; `test_desativada_pela_microsoft_nao_reativa`; `test_conta_nova_nao_recebe_convite` (nenhum e-mail, nenhum código criado). Ajustar os testes existentes que esperavam o convite.
- [ ] **Step 2:** FAIL. **Step 3:** Implementar + adendo do ADR. **Step 4:** `tests/test_acessorias.py` inteiro PASS.
- [ ] **Step 5:** Commit `feat(acessorias): adota conta da Microsoft, nao reativa bloqueada, sem convite`.

### Task 8: Tela de Usuários e aviso do app

**Files:**
- Modify: `app/rotas/usuarios.py` (`POST /api/users/{user_id}/microsoft/desligar`, admin: zera `microsoft_oid`, `microsoft_refresh_cifrado`, `microsoft_conferido_em`, `microsoft_sem_conferencia`; audita; `GET /api/users` passa a devolver `microsoft_ligada: bool`, `microsoft_sem_conferencia`, `nova_pela_microsoft` (= `origem == "microsoft"` e sem departamento), `desativada_pela_microsoft: bool`; `reactivate` `:1060` zera `desativada_pela_microsoft_em`)
- Modify: `templates/usuarios.html` (+ JS da página; trocar `?v=`): selo "Microsoft" na linha; destaque "Nova pela Microsoft — falta configurar"; ação "Desfazer ligação com a Microsoft" com confirmação; motivo "bloqueada na Microsoft" na conta desativada; faixa no topo para o admin logado de domínio liberado sem app autenticador: "Cadastre o app autenticador: é a sua entrada se a Microsoft falhar."
- Test: `tests/test_pagina_usuarios.py`, `tests/test_login_microsoft_rotas.py`

- [ ] **Step 1: Testes:** `test_desligar_microsoft_so_admin`; `test_desligar_permite_ligar_a_outro_oid` (com `resolver_conta` da Task 3); `test_reativar_limpa_marca_da_microsoft`; `test_lista_traz_campos_microsoft`; `test_pagina_usuarios_tem_acao_desligar`.
- [ ] **Step 2:** FAIL. **Step 3:** Implementar. **Step 4:** PASS.
- [ ] **Step 5:** Conferir a tela no portal local (claro/escuro, 1366×657 e 390×700).
- [ ] **Step 6:** Commit `feat(usuarios): ligacao com a Microsoft na tela de Usuarios`.

### Task 9: Roteiro de implantação

**Files:**
- Create: `docs/login-microsoft.md` (adaptado do roteiro do CRM para o CertGuard: aplicativo novo `CertGuard Análise - Login`, locatário único, Web `https://certificado.analisegroup.cnt.br/entrar/microsoft/retorno`, `User.Read` + `offline_access` delegadas, segredo 24 meses no cofre; variáveis no ambiente do NSSM do ANALISESRV; `PORTAL_BASE_URL=https://certificado.analisegroup.cnt.br`; ordem: código (atualizar-portal) → migration da Task 1 → variáveis → reiniciar; liga com `MICROSOFT_CONFERENCIA=simular`; aviso às pessoas dos quatro domínios: entrar uma vez no site pela Microsoft antes de reconectar a bandeja; testes de aceite: conta de teste bloqueada no Entra aparece na lista de simulação com `AADSTS50057` e a mesma conta com senha trocada **não** aparece; só depois `MICROSOFT_CONFERENCIA=aplicar` e reiniciar; admin entra pela Microsoft, operador de domínio com senha leva "Entre pela Microsoft.", gmail com código, conta de teste bloqueada no Entra cai em ≤ 5 min, admin com senha + app; caminho de volta: apagar as variáveis e reiniciar; troca do segredo; erros `AADSTS50011/7000215/700016`; Cloudflare: conferir que `/entrar/microsoft/retorno` não é barrado pelas regras de `certificado.`)
- Modify: `.env.example` (as 4 `MICROSOFT_*` e `PORTAL_BASE_URL`, comentadas; conferir no servidor se `PORTAL_BASE_URL` já existe — o convite do Acessórias a usava)

- [ ] **Step 1:** Escrever. **Step 2:** Commit `docs(login): roteiro de implantacao do login pela Microsoft`.

---

**Fora deste plano:** entrega 2 (bandeja com "Entrar com a Microsoft") — plano próprio no repositório da bandeja, depois desta em produção.
