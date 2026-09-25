# Lote 5 — Abuso de recursos (#11, #12, #28, #29, #47, #60)

Fonte: `SECURITY_AUDIT.md` (auditoria de 24/09/2026). Branch `seguranca/lote-5`, empilhado sobre `seguranca/lote-4`.

O portal roda num worker só (`Procfile`, `--workers 1 --timeout 120`). Tudo o que não tinha teto derrubava o processo inteiro, e quem derrubava era uma sessão comum: uma importação de 5 MB (horas de bcrypt), a tela Duplicidades num laço de `curl` (n² de `SequenceMatcher`), o teste de SMTP como relay, um `POST /api/ingest` de tamanho livre.

Método: os 30 testes de `tests/test_seguranca_lote5.py` foram escritos antes da correção e rodados contra `b9ddb09`: **28 falharam, 2 passaram** (controles: a análise recalcula quando a varredura muda; nomes similares continuam sendo achados). Depois das correções os 30 passam, e a suíte inteira fecha verde: **1223 passam, 9 pulados, 0 falhas em 1 min 28** (`pytest`, 25/09/2026). Dois testes antigos esbarravam antes no limite do Pydantic e foram ajustados com o motivo em comentário: `tests/test_carteira.py` (o `detail` do 422 passou a ser a lista de erros do Pydantic, que também diz o limite) e `tests/test_cert_installer_hardening.py` (o upload de 2 MB agora é 422 do modelo; o 413 da rota continua testado com 1 MB + 4 KB).

## Achados tratados

| # | Achado | O que mudou |
|---|---|---|
| 11 | Importações: arquivo lido inteiro antes do teto, sem teto de linhas, bcrypt e consulta por linha, zip bomb | `_ler_upload_limitado(request, file)`: recusa pelo `Content-Length` **antes** de ler um byte e de novo durante a leitura em pedaços de 64 KB (o cabeçalho é declaração do cliente). `MAX_LINHAS_IMPORT = 2000` (413 acima) nas duas importações, aplicado **antes** de qualquer bcrypt; e-mails existentes numa consulta só (era uma por linha). `.xlsx` lido com `max_row` — a planilha de dimensão gigante não é mais materializada. |
| 12 | `/duplicidades` O(n²), sem cache, aberto a todo papel | Memoização por varredura (`origem`, `scanned_at`, admin) com TTL de 5 min; teto de 5 análises por 5 min por identidade **só quando o cache não serve**; 413 acima de `MAX_ITENS_DUPLICIDADE = 1500`. O laço de nomes similares virou vizinhança ordenada (`_JANELA_NOMES = 15`): O(n log n + n·15) em vez de n². Não é bloco por prefixo de propósito — um inventário em que todos os nomes começam pela mesma palavra cairia num bloco só. |
| 28 | `/smtp/test` e `/alerts/trigger` sem teto; destinatário não validado; `/ingest` dispara alertas a cada chamada | `_limitar(prefixo, max, janela)`: dependência de teto **por identidade** (a identidade é o que o atacante não troca de graça). `/smtp/test` 5/h e `target_email` por `_validar_email` (422 em CR/LF, sem `@`, dois endereços); `/alerts/trigger` 3/h; o disparo de alertas por `/ingest` no máximo uma vez a cada 10 min. |
| 60 | `/redeem`, `/acompanhar`, `/revalidar-cofre` sem teto | `/redeem` com o mesmo teto por IP do `/claim`; `/acompanhar` 120/min por identidade (folga para o laço da tela); `/revalidar-cofre` 3 por 10 min. |
| 29 | Modelos Pydantic sem limites; `/api/certificados` sem paginação | `max_length`/faixas em `IngestBody` (itens ≤ 20.000), `SettingsBody` (`smtp_port` 1–65535, host 253, e-mails 320, pastas 1024), `LoginBody`, `UploadPfxRequest` (base64 ≤ 1,5 M), `ReportRequest` (≤ 200 resultados), `RegistrarDispositivoBody`, `PrepararInstalacaoRequest` (≤ 50 certificados, o mesmo `MAX_CERTIFICADOS_POR_TOKEN`), `RedeemRequest`, `SmtpTestBody`, `UserCreateBody`. `/api/certificados` sem `pagina`/`por_pagina` passa a responder a página 1 de 100 (com `paginacao`); a exportação continua por `todas_filtradas`, que já tinha teto. |
| 47 | Rate limit degrada para memória em silêncio | `taxa.estado_persistente()` (True/False/None) e o campo `rate_limit_persistente` em `/api/health/detalhado`. |

## Arquivos alterados

- `app/main.py` — constantes de teto, `_ler_upload_limitado`, `_limitar`, `_pode_disparar_alerta_por_ingest`, cache das duplicidades (`_dup_cache`, `_dup_cache_limpar`), vizinhança ordenada em `_agrupar_duplicidades`, tetos nas sete rotas, limites nos modelos, paginação padrão.
- `app/taxa.py` — `estado_persistente()`.
- `scripts/diagnostico.py` — lê `paginacao.total_itens` (a listagem agora vem paginada).
- Testes: `tests/test_seguranca_lote5.py` (novo); `tests/test_seguranca_lote1.py` (o fake de banco ganhou `order`/`limit` de verdade e um contador de consultas por tabela).

## Testes criados (`tests/test_seguranca_lote5.py`)

| Teste | O que prova |
|---|---|
| `test_content_length_acima_do_teto_e_recusado_sem_ler` | 413 pelo cabeçalho com **zero** bytes lidos. |
| `test_corpo_maior_que_o_declarado_para_no_teto` | Cabeçalho mentindo: a leitura para no teto, não no fim do corpo. |
| `test_upload_dentro_do_teto_e_lido_inteiro` | Controle. |
| `test_csv_com_mais_linhas_que_o_teto_e_413`, `test_xlsx_com_mais_linhas_que_o_teto_e_413` | 2.001 linhas → 413, nada gravado. |
| `test_emails_existentes_numa_consulta_so` | 40 linhas: no máximo 3 consultas à tabela `users` (era 40+). |
| `test_duplicidades_reusa_o_resultado_da_mesma_varredura`, `..._recalcula_quando_a_varredura_muda` | Três leituras da mesma varredura, uma análise; varredura nova, análise nova. |
| `test_duplicidades_tem_teto_de_analises_por_identidade` | Seis varreduras novas seguidas: a sexta análise é 429. |
| `test_duplicidades_recusa_inventario_grande_demais` | 1.501 itens → 413. |
| `test_nomes_similares_nao_e_quadratico` | 3.000 itens sem fingerprint, **todos começando pela mesma palavra**, em menos de 5 s (a versão n² levou 108 s nesta máquina; a primeira versão por prefixo também). |
| `test_nomes_similares_continuam_sendo_achados_dentro_do_bloco` | "PADARIA CENTRAL LTDA" e "PADARIA CENTRAL LTDA ME" continuam no mesmo grupo. |
| `test_teste_de_smtp_tem_teto_por_identidade`, `test_destinatario_do_teste_e_validado` (×3) | Sexto envio 429; CR/LF, sem `@` e lista de endereços → 422 sem enviar. |
| `test_disparo_manual_tem_teto` | Quarto disparo 429. |
| `test_ingest_nao_agenda_alerta_a_cada_chamada` | Três ingestões, um disparo agendado. |
| `test_redeem_estourado_vira_429`, `test_acompanhar_estourado_vira_429`, `test_revalidar_cofre_tem_teto` | Tetos das três rotas. |
| `test_ingest_com_itens_demais_e_422`, `test_settings_fora_da_faixa_e_422` (×4), `test_login_com_senha_gigante_e_422`, `test_prepare_com_certificados_demais_e_422` | Limites dos modelos. |
| `test_listagem_sem_parametros_vem_paginada` | 150 itens sem parâmetros → `paginacao`, ≤ 100 itens, `total_itens = 150`. |
| `test_health_detalhado_diz_se_o_rate_limit_e_persistente` | Banco fora do ar → `rate_limit_persistente: false` no health detalhado. |

## Janela de compatibilidade

| Mudança | Quem afeta | Janela |
|---|---|---|
| `/api/certificados` paginada por padrão | O Início e o Instalador já mandam `pagina`/`por_pagina`; a exportação usa `todas_filtradas`. `scripts/diagnostico.py` foi ajustado. Um consumidor externo que lesse `itens` inteiros sem parâmetros passa a receber 100 e `paginacao.total_itens`. | Sem flag; o corpo da resposta paginada já existia. |
| Tetos por identidade | Admin que testa SMTP mais de 5× por hora, dispara alertas mais de 3× por hora ou revalida o cofre mais de 3× em 10 min recebe 429 com a mensagem "Muitas requisições. Aguarde alguns minutos." | Sem flag; os números têm folga sobre o uso real. |
| Tela Duplicidades | Quem atualiza a tela dentro de 5 min vê o resultado memoizado (mesma varredura); uma varredura nova invalida sozinha. O botão "Atualizar" não gera análise nova sem varredura nova — antes gerava, a n². | — |
| Importações | Planilhas com mais de 2.000 linhas passam a ser recusadas com a instrução de dividir o arquivo. | — |
| Alertas por ingestão | Várias estações ingerindo em sequência produzem um disparo a cada 10 min, não um por ingestão. O job de fundo continua de hora em hora, e a deduplicação por certificado/marco continua. | — |
| Limites de campo | Um agente que mandasse `machine_id` com mais de 128 caracteres ou pastas com mais de 1024 receberia 422; nenhum valor real chega perto. | — |

Nenhuma migração de dados; nenhuma variável de ambiente nova.

## Pendente e por quê

- **Limite de corpo no servidor HTTP** (`--limit-request-*` do gunicorn cobre só cabeçalhos; o uvicorn não tem teto de corpo): a leitura em fluxo fecha o vetor nas duas rotas de upload, mas um corpo gigante num endpoint JSON ainda é lido pelo Starlette antes de o Pydantic recusar. Um teto global fica para o proxy (Caddy `request_body max_size`) — ação no servidor, fora do repositório.
- **`/api/users` e `_garantir_email_livre`** continuam lendo a tabela `users` inteira por operação (achado 2.7 do relatório, parte de #29); são admin-only e a tabela tem dezenas de linhas. Anotado, não tratado.
- **Job de alertas com `job_ja_executado_recentemente`**: o debounce do ingest é um carimbo em memória do processo (10 min); com mais de um worker seria por worker. Hoje há um.

## Achados novos

- A memoização das duplicidades guarda o resultado por `admin` (com/sem `pasta`): duas entradas por varredura no pior caso. O cache é limpo acima de 32 entradas.
- O fake de banco dos testes ignorava `order` e `limit`: `get_latest_snapshot()` devolvia sempre a primeira linha inserida, o que mascarava qualquer teste que dependesse do "último" snapshot. Corrigido no fake; nenhum teste anterior dependia disso (eles gravavam um snapshot só).
