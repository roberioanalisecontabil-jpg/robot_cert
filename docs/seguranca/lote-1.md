# Lote 1 — Correções pequenas e de alto retorno

Fonte: `SECURITY_AUDIT.md` (auditoria de 24/09/2026 sobre `ea9c3de`). Branch `seguranca/lote-1`.

Método: os 75 testes de `tests/test_seguranca_lote1.py` foram escritos antes de qualquer correção e rodados contra `ea9c3de`: **70 falharam, 5 passaram**. Os cinco que passavam são controles de comportamento preservado (admin continua criando admin, gestor continua gerindo operadores, SMTP local sem TLS, `*.pfx` já ignorado, Host livre sem lista). Depois das correções, os 75 passam, e a suíte inteira fecha verde: **1093 passam, 9 pulados, 0 falhas** (`pytest`, 24/09/2026).

## Achados tratados

| # | Achado | O que mudou |
|---|---|---|
| 6 | `X-Forwarded-For` aceito sem validação | `_ip_do_cliente` conta a partir da **direita**, com `NUM_PROXIES_CONFIAVEIS` (padrão 1, o Caddy). Zero desliga o cabeçalho; cadeia mais curta que a esperada cai no socket. |
| 7 | `/api/agent/dispositivos/registrar` sem teto | Mesma chave `login:{ip}` (20/60 s) do `/api/login`, mais teto por conta `senha:{email}` (10/300 s). |
| 8 | Recuperação de senha sem limite por IP; SMTP síncrono | `/api/senha/codigo`: 5/h por IP, respondendo 200 genérico; envio via `BackgroundTasks`. `/verificar` e `/redefinir`: 20/h por IP, respondendo o mesmo 400 de código errado (não 429: o fluxo tem duas respostas, e uma terceira seria sinal). |
| 26 | Oráculo de timing no login | Conta inexistente confere contra um hash bcrypt falso de custo real (`_hash_falso`, gerado uma vez). |
| 27 | 403 "Usuário desativado" | Conta desativada responde o mesmo 401 de senha errada; o motivo fica em `user_activity`. |
| 41 | `X-API-Key` comparada com `==` | `hmac.compare_digest`. |
| 9 | `usuarios:editar` cria/promove admin | `_exigir_alcance_de_papel` (só admin concede `admin`) em criar, editar e importar; `_exigir_alcance_sobre_conta` (só admin altera conta de admin) em editar, redefinir senha, desativar, reativar e apagar. A segunda cobre o caminho menos óbvio: trocar o e-mail do admin e pedir código de redefinição para o endereço novo. |
| 10 | CSV cria conta sem senha provisória | O insert grava `deve_trocar_senha=True` e `ativo=True`, como `create_user`. |
| 24 | Reset por admin não carimba `senha_alterada_em` | Carimba, na mesma gravação da senha. |
| 13 | `esc()` não escapa aspas | Tabela fixa `& < > " '`, sem DOM. |
| 14 | Fórmula em CSV exportado | `celulaCsv()` em `ui-common.js`, usada por Início, Histórico e Vencidos; prefixa `'` em célula que começa com `= + - @ \t \r`. |
| 15 | SMTP sem verificação de certificado; "Nenhuma" | `ssl.create_default_context()` em `SMTP_SSL` e `starttls`; sem TLS só para `localhost`/`127.0.0.1`/`::1` (na validação do `PUT /api/settings` e no envio); a opção da tela diz "só para servidor local". |
| 20 | `.gitignore` sem `*.p12` etc. | Adicionados `*.p12 *.pem *.key *.cer *.crt certificados/ certificados_vencidos/ agent_config.json *.bak *.old *.orig *.swp`; hook `.githooks/pre-commit` recusa `.p12/.pfx/.pem/.key/.cer/.crt` no stage. |
| 35 | Erros crus ao cliente | Handler global (`{"detail":"Erro interno","ref":<id>}`, traceback só no log). 25 `detail=str(e)` em `except Exception`/`RuntimeError` viraram mensagens fixas com `logger.exception`; mais 9 concatenações (`"... Detalhe: " + str(e)`, `f"...: {e}"`, "Veja o terminal do uvicorn"). Teste SMTP responde por classe (`ErroAutenticacaoSmtp`, `ErroConexaoSmtp`, `ErroTlsSmtp`, `ErroSmtp`). |
| 48 | `/api/health` descreve a postura | `/api/health` → `{"ok": true}`; `/api/health/detalhado` com `require_admin`. `ui-common.js` e `scripts/verificar_deploy.py --token` leem o detalhado. |
| 49 | CSP sem `base-uri` | `base-uri 'none'`. |
| 50 | Cabeçalho `Server` | `--no-server-header` em `scripts/servir.ps1`; `app/worker.py` (worker do gunicorn com `server_header: False`) no `Procfile`. |
| 36 | Sem `TrustedHostMiddleware` | `hosts_permitidos_middleware` lê `HOSTS_PERMITIDOS` (nomes sem porta, separados por vírgula) e responde 400 fora da lista. |

## Arquivos alterados

- `app/main.py` — todos os itens acima do lado do servidor.
- `app/config.py` — `NUM_PROXIES_CONFIAVEIS`, `HOSTS_PERMITIDOS`, aviso em `verificar_ambiente`.
- `app/smtp_service.py` — contexto TLS, regra do servidor local, classes de erro, `_classificar`.
- `app/worker.py` — novo.
- `static/ui-common.js` — `esc`, `celulaCsv`, `health()`.
- `templates/index.html`, `historico.html`, `vencidos.html` — exportação usa `celulaCsv`.
- `templates/configuracao.html` — texto da opção "Nenhuma".
- Os 10 templates — cache-buster `ui-common.js?v=aguia-2026-09f` (sem isso `esc`/`celulaCsv` não chegam ao navegador).
- `.gitignore`, `.githooks/pre-commit`, `scripts/servir.ps1`, `Procfile`, `scripts/verificar_deploy.py`.
- Testes: `tests/test_seguranca_lote1.py` (novo). Sete testes antigos fixavam exatamente o comportamento que os achados mudam e foram ajustados, cada um com o motivo em comentário: `tests/test_taxa_e_fila.py` (o teste do XFF fixava o valor **vulnerável**: passou a esperar o último salto); `tests/test_api_routes.py` (health → detalhado com admin); `tests/test_login_email_normalizado.py` e `tests/test_usuarios_papel_estado.py` (403 → 401 no login de conta desativada); `tests/test_smtp_test_endpoint.py` ("535" deixa de chegar à tela; a classe chega); `tests/test_cron_alerts.py` (texto da exceção não sai no 500); `tests/test_config_instalador.py` (o `PGRST204` chega a quem conserta pelo log, conferido com `caplog`, não pela resposta); `tests/test_instalar_pelo_agente.py` (a ponte INVENT ganhou `PonteRecusou`: o `detail` do outro portal continua na tela, e um teste novo garante que erro de rede/proxy não sai).

## Testes criados (`tests/test_seguranca_lote1.py`, 75 casos)

| Teste | O que prova |
|---|---|
| `test_ip_vem_do_ultimo_salto_que_o_proxy_escreveu`, `test_sem_proxy_confiavel_o_cabecalho_e_ignorado`, `test_cadeia_mais_curta_que_os_proxies_cai_no_socket` | A chave do rate limit vem do que o proxy escreveu, não do que o cliente mandou. |
| `test_xff_forjado_nao_escapa_do_teto_do_login` | 30 logins com XFF forjado e mesmo cliente real → 429. |
| `test_registrar_dispositivo_tem_teto_por_ip`, `test_registrar_e_login_dividem_a_mesma_janela`, `test_registrar_tem_teto_por_conta_que_ip_nenhum_contorna` | O registro de dispositivo tem o teto do login, a chave é compartilhada (o 21º alternado é 429) e trocar de IP não escapa do teto por conta. |
| `test_pedido_de_codigo_tem_teto_por_ip_e_responde_200_generico` | 6 pedidos do mesmo IP → no máximo 5 envios, todos 200 com a mesma mensagem. |
| `test_envio_do_codigo_sai_do_caminho_da_resposta` | O SMTP é agendado em `BackgroundTasks`, nunca chamado dentro da requisição. |
| `test_verificar_codigo_tem_teto_por_ip`, `test_redefinir_senha_tem_teto_por_ip` | Após 20 conferências erradas do IP, a 21ª com código válido é recusada com o mesmo 400. |
| `test_email_inexistente_paga_o_bcrypt` | `verify_password` roda exatamente uma vez mesmo sem conta. |
| `test_conta_desativada_responde_igual_a_senha_errada` | Status e corpo idênticos. |
| `test_x_api_key_e_comparada_em_tempo_constante` | Fonte: `compare_digest` na `X-API-Key`, sem `==`. |
| `test_gestor_nao_cria_admin`, `test_gestor_nao_se_promove`, `test_gestor_nao_mexe_em_conta_de_admin` (×4: reset, editar, desativar, apagar) | 403 e conta intacta. |
| `test_admin_continua_podendo_criar_admin`, `test_gestor_continua_gerindo_operadores` | Controles: o que era permitido continua. |
| `test_conta_importada_por_csv_nasce_com_senha_provisoria`, `test_senha_do_csv_nao_abre_o_portal`, `test_gestor_nao_importa_admin_por_csv` | A conta do CSV nasce provisória; a senha da planilha leva 403 com `X-Senha-Provisoria`; a linha `admin` de um gestor vira erro. |
| `test_reset_por_admin_derruba_a_sessao_antiga` | Sessão aberta 30 s antes do reset responde 401 depois dele. |
| `test_esc_escapa_aspas`, `test_esc_dentro_de_atributo_nao_fecha_o_atributo` | Executados no node, com um stub de DOM que reproduz o `innerHTML` do navegador (é ele que fazia a versão antiga passar). |
| `test_celula_csv_neutraliza_formula` (×7) | Tabela de células. |
| `test_exportacao_csv_usa_o_helper_compartilhado` (×3), `test_templates_apontam_para_o_ui_common_novo` | Nenhum template copia o escape; todos os templates apontam para a mesma versão nova de `ui-common.js`. |
| `test_starttls_verifica_o_certificado_do_servidor`, `test_ssl_implicito_verifica_o_certificado_do_servidor` | O contexto passado à `smtplib` tem `CERT_REQUIRED` e `check_hostname`. |
| `test_credencial_sem_tls_e_recusada_para_servidor_externo`, `test_sem_tls_e_aceito_para_servidor_local`, `test_configuracao_recusa_nenhuma_com_servidor_externo`, `test_tela_avisa_que_nenhuma_e_so_para_servidor_local` | Regra do servidor local no envio, no `PUT /api/settings` (422) e no texto da tela. |
| `test_smtp_classifica_a_falha`, `test_teste_de_smtp_responde_por_classe_de_erro` (×4) | `SMTPAuthenticationError` vira `ErroAutenticacaoSmtp`; a rota responde a mensagem fixa da classe, sem o texto do servidor. |
| `test_gitignore_cobre_material_de_certificado` (×10) | `git check-ignore` para cada padrão. |
| `test_hook_pre_commit_recusa_material_de_certificado` (×5) | Repositório temporário com o arquivo no stage: `.p12/.pfx/.pem/.key` → exit 1; `.py` → exit 0. |
| `test_erro_inesperado_sai_com_referencia_e_sem_o_texto`, `test_listagem_de_certificados_nao_vaza_a_excecao`, `test_importacao_csv_nao_vaza_o_erro_do_banco` | Uma marca única na exceção nunca aparece na resposta. |
| `test_nenhum_except_generico_devolve_str_da_excecao` | Fonte: nenhum `except Exception`/`RuntimeError` seguido de `detail=…str(e)`/`{e}`. |
| `test_health_publico_so_diz_que_esta_vivo`, `test_health_detalhado_exige_admin` | Corpo exato `{"ok": true}`; detalhado 401/403 sem admin. |
| `test_csp_tem_base_uri_none`, `test_servidor_sobe_sem_cabecalho_server` | Cabeçalho e scripts de subida. |
| `test_host_fora_da_lista_e_recusado`, `test_sem_lista_de_hosts_nada_muda` | 400 fora da lista, porta ignorada, lista vazia = comportamento antigo. |

Desvios do "Como testar" do relatório: os testes de timing (#26, #8: "mediana < 25 ms") foram substituídos por testes determinísticos (contagem de chamadas ao bcrypt; envio agendado em `BackgroundTasks`), porque medir tempo em CI é instável e o mecanismo é o que importa.

Verificação no navegador (Playwright, Chrome, banco local `certguard_imp` com admin temporário criado e removido): as dez telas carregam sem erro de JS; a exportação CSV do Início gera o arquivo (519 linhas); `esc('a"b<c>')` e `celulaCsv('=1+1')` respondem o esperado no navegador; a tela de Configuração continua mostrando "Banco de dados conectado" e "Chave API obrigatória" pelo `/api/health/detalhado`; `/api/health` anônimo devolve `{"ok":true}` e o detalhado 401; a resposta do uvicorn com `--no-server-header` não traz `server:` e a CSP traz `base-uri 'none'`.

## Janela de compatibilidade

| Mudança | Quem afeta | Janela |
|---|---|---|
| `NUM_PROXIES_CONFIAVEIS` (padrão 1) | O rate limit passa a usar o **último** valor do XFF. Com um Caddy à frente, é o cliente real. **A Fase 0 pediu o número de proxies em produção e ele não foi informado**: o padrão 1 assume só o Caddy. Se houver outro salto (VPN com proxy, balanceador), o teto por IP vira teto global até ajustar a variável. Nada quebra: só a granularidade do limite. Em dev/testes (sem proxy) defina 0. | Variável de ambiente; aviso não é necessário. |
| `HOSTS_PERMITIDOS` (padrão vazio) | Vazio = aceita qualquer Host, como antes. `verificar_ambiente` avisa em produção. Ao preencher, incluir **todos** os nomes usados: `certificado.analisegroup.cnt.br,10.200.0.4,127.0.0.1,localhost` (o portal foi acessado por IP em 17/09). | Flag com padrão seguro para o que já existe. |
| Login 401 para conta desativada | `agent/janela_login.py` traduzia "desativado" para "Procure um administrador"; agora a estação verá "E-mail ou senha incorretos". Deliberado (#27). O ramo no agente ficou, inofensivo. | Sem ação. |
| Teto por IP em `/api/senha/*` | 5 pedidos/h por IP. Um escritório atrás de um NAT com mais de 5 pessoas esquecendo a senha na mesma hora vê a resposta genérica sem receber e-mail. Ajuste em `senha_pedir_codigo` se acontecer. | Sem flag; o log avisa ("Teto de pedidos de código por IP atingido"). |
| Teto por conta em `/registrar` (10/5 min) | Só o registro de dispositivo do agente. Estação que erra a senha dez vezes espera 5 minutos. | Sem flag. |
| SMTP sem TLS recusado para host externo | Uma configuração gravada com "Nenhuma" e host externo passa a falhar no envio com `ValueError` (mensagem curada) até ser trocada para STARTTLS/SSL. O `PUT /api/settings` recusa gravar assim (422). Verificar em produção qual opção está gravada antes do deploy. | Sem flag: aceitar seria manter a senha em claro. |
| Verificação de certificado do SMTP | Um servidor SMTP com certificado autoassinado ou nome divergente passa a falhar (`ErroTlsSmtp`, "A conexão segura … falhou"). Gmail/Office365 verificam. | Sem flag. |
| `/api/health` só `ok` | `scripts/verificar_deploy.py` ganhou `--token` (JWT de admin) para ler o detalhado; sem token confere só que o portal responde. A tela de Configuração já lê o detalhado com a sessão. | Compatível. |
| Cache-buster `ui-common.js?v=aguia-2026-09f` | Obrigatório: sem ele o navegador manteria o `esc()` antigo. Sonda de deploy: `/static/ui-common.js` contém `celulaCsv`. | — |
| `Procfile` → `app.worker.Worker` | Só Vercel/Render (pausados). O servidor real sobe pelo `atualizar-portal.ps1`, que **não está no repositório**: incluir `--no-server-header` lá é ação humana. | — |
| Hook `pre-commit` | `core.hooksPath` é configuração local: já ativado neste clone (`git config core.hooksPath .githooks`); cada clone novo precisa rodar o mesmo comando. | — |

Nenhuma mudança toca o agente, a `X-API-Key` compartilhada ou JWTs já emitidos.

## Migração de dados

Nenhuma. O lote não altera esquema nem dados.

## Pendente e por quê

- **#35, parcial por decisão**: 14 `detail=str(e)` ficaram, todos em exceções de **domínio** com texto escrito pelo próprio app para a pessoa (`ConfiguracaoInvalida`, `ModeloInvalido`, `ForaDaCarteira`, `JaProvisionada`, `CarteiraIndisponivel`, `SemBanco`, `ValueError` de `validate_smtp_config`/`permissoes.gravar`/`enqueue`, `ValueError` do bundle → 404), mais a ponte INVENT (`PonteRecusou`, cujo texto vem do nosso outro portal). Trocar por mensagem fixa apagaria validações úteis ("Marco inválido: …") sem ganho: nenhuma delas embrulha erro de banco ou de sistema. O teste `test_nenhum_except_generico_devolve_str_da_excecao` fixa a fronteira: `except Exception`/`RuntimeError` não devolve `str(e)`. Item que sobrou: `expurgo["motivo"] = str(e)` no cron (`main.py`, rota guardada por `CRON_SECRET`) e `erros[].erro = str(e)` em `/api/mover-vencidos` (admin; #53, lote 6).
- **#50**: o `server: uvicorn` só some quando o processo sobe com `--no-server-header` — o script do servidor não está no repositório. O Caddy à frente adiciona `Server: Caddy` por conta própria (não verificável aqui).
- **#36**: `HOSTS_PERMITIDOS` precisa ser definida no `.env` do servidor para a barreira existir.
- **Fase 0** continua inteira em aberto (revogação do `.p12`, rewrite do histórico, troca de segredos, número de proxies, contagem de estações na chave compartilhada, TTL do token).

## Achados novos

- `SecureJSONFormatter` (`app/main.py`, #57 do relatório) apaga a mensagem inteira de log quando ela contém "senha"/"token": os novos avisos "Teto de pedidos de código por IP atingido" e "Teto de conferências de código por IP atingido" não contêm essas palavras de propósito, mas a mensagem do reset ("Falha ao gravar a senha nova") some do log. Já listado como #57 (lote 9); registrado aqui porque o lote 1 esbarrou nele.
- `main.py` importa `secrets` no meio do arquivo (antes do middleware), não no topo; `_hash_falso` e o handler global dependem dele. Funciona porque é global de módulo, mas é frágil a reordenação. Sem correção (escopo).
- O `Procfile` e a documentação de deploy ainda falam de Vercel/Render, pausados desde 22/09. Fora do escopo.
