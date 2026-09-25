# Lote 9 — Restante (#23, #25, #37, #38, #40, #51, #52, #57, #59)

Fonte: `SECURITY_AUDIT.md` (auditoria de 24/09/2026). Branch `seguranca/lote-9`, empilhado sobre `seguranca/lote-8`. Último lote do plano.

Método: os 38 testes de `tests/test_seguranca_lote9.py` foram escritos antes da correção e rodados contra `4150e51` (fim do lote 8): **36 falharam, 2 passaram** (controles: senha comum "password1234" já era recusada por tamanho num caso; a importação de carteiras já não ecoava em outro). Depois das correções os 38 passam, e a suíte inteira fecha verde: **1353 passam, 9 pulados, 0 falhas em 1 min 29** (`pytest`, 25/09/2026). Quatro testes antigos foram adaptados porque descreviam a implementação anterior: dois usavam a senha de teste `segredo123` (10 caracteres) para criar contas, um afirmava que a mensagem de senha curta dizia "6", e um esperava o e-mail ecoado no motivo da importação de carteiras. O que eles garantiam continua garantido.

## Achados tratados

| # | Achado | O que mudou |
|---|---|---|
| 23 | JWT de 24 h sem revogação; "Sair" só limpava o `localStorage` | Coluna `users.sessao_versao` (DEFAULT 0); o login grava a versão no claim `sv`; `POST /api/logout` incrementa a coluna e `_sessao_do_token` recusa token de versão diferente (`_sessao_encerrada_por_logout`). Token sem `sv` (anterior ao deploy) vale como 0 e morre no primeiro Sair. `logout()` do front chama a rota (`keepalive`) antes de limpar o navegador. Validade: **8 h** por padrão (`SESSAO_HORAS`, 1–24, no ambiente). Revoga a sessão da conta inteira — sem `jti` por token não há como revogar um só sem tabela de revogados. |
| 25 | Mínimo 6 em cinco lugares; sem teto de 72 bytes; sem lista de senhas comuns | `auth.validar_senha(senha, email)`: mínimo **12**, máximo **72 bytes** (o bcrypt trunca em silêncio), sem caractere único repetido, sem sequência numérica, lista curta de senhas comuns, sem o e-mail (ou a parte local dele) dentro. `main._exigir_senha_valida` (422) nas quatro rotas — criar, redefinir pelo admin, redefinir por código, trocar a própria — e a mesma função na importação de usuários. `SENHA_MINIMA` passou a apontar para `auth.SENHA_MINIMA`. |
| 37 | HSTS emitido sem configuração do proxy TLS versionada | `deploy/Caddyfile`: cópia de referência do Caddyfile do ANALISESRV (reverse proxy para `127.0.0.1:8020/8021`, TLS Let's Encrypt por DNS Cloudflare com o token só em `{env.CLOUDFLARE_API_TOKEN}`, redirecionamento 80→443 do próprio Caddy). Sem segredo nenhum no arquivo. |
| 38 | Documentação e script orientavam HTTP em `0.0.0.0` | `docs/GUIA_MIGRACAO_WINDOWS_SERVER.md`: Partes 2, 3, 4, 5, 6 e 7 reescritas — bind em `127.0.0.1`, firewall só 80/443, sem encaminhamento da 8020, HTTPS com Caddy obrigatório, checklist e troubleshooting coerentes. `scripts/setup_porta_servidor.ps1` reescrito: abre 80/443, remove a regra antiga da 8020, confere que a 8020 só ouve em loopback (ASCII, para o PowerShell 5.1). `scripts/servir.ps1` continua em `127.0.0.1`. |
| 40 | Ponte com o INVENT aceitava `http://` para fora da máquina | `verificar_ambiente`: em produção, `INVENT_API_URL` em `http://` para host **fora de loopback** é **fatal** (o `CERT_PORTAL_TOKEN` e o token de instalação viajam nela). `http://127.0.0.1:8021` — o caso real do ANALISESRV — continua aceito: não sai da máquina. |
| 51 | DSN do PostgreSQL remoto sem `sslmode` | `config.dsn_efetivo()`: host fora de loopback sem `sslmode` na URL ganha `sslmode=require`; `settings_state` passa a construir o cliente com ele. `sslmode=disable/allow/prefer` explícito em host remoto vira aviso no boot. Local (`127.0.0.1`, o caso do servidor) fica igual. |
| 52 | 409 ecoava o e-mail; importação de carteiras ecoava o e-mail | "Já existe uma conta com esse e-mail…" e "Não existe usuário com esse e-mail." — a resposta já traz a `linha` da planilha. |
| 57 | `SecureJSONFormatter` apagava a mensagem inteira e não redigia `exc_info` | `redigir_segredos(texto)`: mascara **valores** — JWT (`eyJ…`), `Bearer/Basic …`, `X-API-Key:/token=/senha=/password:` seguidos de valor, cadeias base64url/hex ≥ 32, e "token/senha/chave + valor que parece segredo" — e preserva a frase. Aplicado à mensagem **e** ao `exc_info`. O WARNING da X-API-Key compartilhada (lista de estações não migradas) e o log de resgate recusado voltam a aparecer. |
| 59 | `servir.ps1` subia com `--reload` | `-Dev` liga o `--reload`; sem ele, não há watcher. `--no-server-header` mantido. |

## Arquivos alterados

- `app/auth.py` — `SESSAO_HORAS_PADRAO`, `_horas_de_sessao`, `ACCESS_TOKEN_EXPIRE_MINUTES` (8 h), `SENHA_MINIMA`, `SENHA_MAX_BYTES`, `SENHAS_PROIBIDAS`, `validar_senha`; `TokenData.sessao_versao`; `decode_access_token` lê `sv`.
- `app/config.py` — `_HOSTS_LOCAIS`, `_host_da_url`, `dsn_efetivo`, `_sslmode_fraco`; fatal da ponte em `http://` remoto; aviso de `sslmode` fraco.
- `app/main.py` — `_conta_da_sessao` seleciona `sessao_versao`; `_sessao_encerrada_por_logout`; login grava `sv`; rota `POST /api/logout`; `SENHA_MINIMA = auth.SENHA_MINIMA`, `_exigir_senha_valida`; quatro rotas e a importação usam a regra única; 409 e importação de carteiras sem eco; `redigir_segredos` e `SecureJSONFormatter`.
- `app/settings_state.py` — `db_pg.Client(config.dsn_efetivo())`.
- `static/ui-common.js` — `logout()` chama `/api/logout` (cache-buster `aguia-2026-09g`).
- `supabase/migrations/20260926110000_users_sessao_versao.sql` — a coluna, idempotente, com a volta comentada.
- `deploy/Caddyfile` (novo), `docs/GUIA_MIGRACAO_WINDOWS_SERVER.md`, `scripts/setup_porta_servidor.ps1`, `scripts/servir.ps1`.
- Testes: `tests/test_seguranca_lote9.py` (novo); `tests/test_usuarios_papel_estado.py`, `tests/test_atividade.py`, `tests/test_carteiras_ui.py` (adaptados).

## Testes criados (`tests/test_seguranca_lote9.py`)

| Teste | O que prova |
|---|---|
| `test_logout_derruba_o_token_que_saiu` | O "Como testar" do #23: 200 antes, `/api/logout`, 401 depois; login novo (v1) entra. |
| `test_token_antigo_sem_claim_de_versao_continua_valendo_ate_o_primeiro_logout` | Janela: token sem `sv` vale como 0 e morre no primeiro Sair. |
| `test_sem_a_coluna_a_sessao_nao_e_derrubada` | Migration pendente → fail-open, como `senha_alterada_em`. |
| `test_login_emite_token_com_a_versao_da_sessao` | O `sv` do token é o da conta. |
| `test_validade_do_jwt_caiu_para_no_maximo_8h`, `test_o_sair_do_navegador_chama_a_rota`, `test_migration_da_versao_de_sessao_existe`, `test_a_sessao_le_a_coluna_da_versao` | 8 h; o front chama a rota; a migration existe; a coluna está no `select` da sessão (o fake não pegaria). |
| `test_validar_senha_recusa` (×6), `test_validar_senha_recusa_o_proprio_email`, `test_validar_senha_aceita_senha_razoavel` | Curta, 80 bytes, repetida, sequência, comum, e-mail dentro; 72 bytes cabem, 73 não. |
| `test_criar_usuario_recusa_senha_fraca`, `test_redefinir_pelo_admin_recusa_senha_fraca`, `test_trocar_a_propria_senha_recusa_senha_fraca` | Os "Como testar" do #25: `123456` → 422 em criar e redefinir; 80 bytes → 422 com "72". |
| `test_a_regra_mora_num_lugar_so` | Sem `len(new_pw) < 6`, sem "6 caracteres", `_exigir_senha_valida` em ≥ 4 rotas e `validar_senha` na importação. |
| `test_configuracao_do_proxy_esta_versionada_sem_segredo` | Caddyfile com `reverse_proxy 127.0.0.1:…`, token via `{env.…}`, nenhuma cadeia de 40 caracteres que pareça token. |
| `test_documentacao_nao_orienta_mais_http_em_todas_as_interfaces` | Guia sem `0.0.0.0`, com `127.0.0.1` e Caddy; script abre 443 e não a porta da aplicação. |
| `test_ponte_por_http_para_outro_host_e_fatal_em_producao`, `test_ponte_por_http_na_propria_maquina_e_aceita` | O "Como testar" do #40, e o caso real do servidor. |
| `test_dsn_remoto_ganha_sslmode_require` (×5), `test_dsn_remoto_sem_tls_explicito_gera_aviso`, `test_o_cliente_do_banco_usa_o_dsn_efetivo` | Local intacto; remoto sem `sslmode` → `require`; `disable` explícito respeitado com aviso; o cliente usa o DSN efetivo. |
| `test_409_nao_ecoa_o_email`, `test_importacao_de_carteiras_nao_ecoa_o_email` | Sem o endereço na resposta. |
| `test_mensagem_com_token_mantem_o_texto_e_mascara_o_valor` | O "Como testar" do #57: `token abc.def.ghi rejeitado` → `token *** rejeitado`. |
| `test_aviso_operacional_deixa_de_ser_apagado`, `test_jwt_e_bearer_sao_mascarados_onde_aparecerem`, `test_exc_info_tambem_e_redigido` | A frase fica; JWT e Bearer somem; `senha=` e `X-API-Key:` somem do traceback e o tipo da exceção fica. |
| `test_servir_so_recarrega_com_dev` | `[switch] $Dev` e o único `"--reload"` dentro do `if ($Dev)`. |

## Migração

`20260926110000_users_sessao_versao.sql` acrescenta `users.sessao_versao INTEGER NOT NULL DEFAULT 0`. **Rodar antes do deploy**: o `select` da sessão passa a pedir a coluna, e sem ela login e sessão falhariam (503, com o erro do Postgres no log — alto, não silencioso). Código antigo ignora a coluna. Volta: `DROP COLUMN` depois de voltar o código (comentado no arquivo). Não há dado a migrar; não precisa de ensaio em cópia — é `ADD COLUMN … DEFAULT`, sem reescrita de linha. As duas migrations pendentes (lote 8 e lote 9) podem ir juntas.

## Janela de compatibilidade

| Mudança | Quem afeta | Janela |
|---|---|---|
| Validade do JWT 24 h → 8 h | Quem estiver logado há mais de 8 h no momento do deploy relogará uma vez; depois, uma vez por jornada. `SESSAO_HORAS` no `.env` ajusta (1–24). | Padrão novo; knob para voltar. |
| Versão de sessão | Tokens emitidos antes do deploy continuam válidos (sem `sv` = 0); morrem no primeiro Sair, como qualquer outro. Migration antes do deploy. | Fail-open sem a coluna. |
| Política de senha | Só senhas **novas**. Contas com senha curta continuam entrando; a regra pega na próxima troca — inclusive as trocas obrigatórias de senha provisória, que passam a exigir 12. Importação de usuários com senha fraca lista a linha e segue. | — |
| Ponte INVENT em `http://` remoto | Fatal no boot em produção. O ANALISESRV usa `http://127.0.0.1:8021`, aceito. Quem tiver a ponte para outro host em http verá o boot recusar com a mensagem. | Sem flag: é o token em claro no fio. |
| `sslmode=require` no DSN remoto | O servidor usa banco local — nada muda. Um Postgres remoto sem TLS passaria a recusar conexão; quem aceitar o risco escreve `sslmode=disable` na URL (com aviso). | Opt-out explícito na URL. |
| Log | Nenhuma mensagem some inteira; valores viram `***`. Quem grep-ava `REDACTED` no log não encontra mais. | — |
| Scripts/docs | `servir.ps1` sem `--reload` por padrão; `setup_porta_servidor.ps1` não abre mais a 8020 e remove a regra antiga se rodar de novo. | — |

## Pendente e por quê

- **Rodar a migration** `20260926110000` no ANALISESRV antes do deploy (junto com a do lote 8).
- **Conferir no servidor** que o NSSM sobe com `--host 127.0.0.1` e que a regra de firewall da 8020, se existir, saiu (`scripts/setup_porta_servidor.ps1` faz as duas coisas). O `atualizar-portal.ps1` não está no repositório: não verificável daqui (#59).
- **`Procfile`** ainda faz bind em `0.0.0.0:$PORT`: é o arquivo do Render, pausado desde 22/09; em PaaS o bind em todas as interfaces é exigido pela plataforma e o TLS é dela. Deixado como está.
- **Achado do lote 7** (`login.html` guarda o JWT em `localStorage` sob o nome `cert_robot_api_key`): renomear a chave de armazenamento exige migrar o valor no navegador de quem já está logado e mexer em `ui-common.js`, `login.html` e templates. Não entrou: é cosmético e o valor guardado é só o JWT desde o lote 7. Fica anotado.

## Achados novos

- `user_activity` tem `CHECK` fechado sobre os eventos; registrar "logout" na trilha exige migration para ampliar a lista. O logout fica no log do servidor por enquanto.
- A rota `/api/logout` revoga a **conta inteira** (todos os dispositivos). Um `jti` por token com tabela de revogados permitiria "sair só daqui"; não pareceu valer a tabela.
- `verificar_ambiente` não conferia o formato das chaves `_V<n>` (feito no lote 8) nem o esquema da ponte (feito aqui); `ENCRYPTION_KEY` (Fernet do SMTP) continua sem verificação de formato no boot — falha no primeiro uso.
