# Lote 3 — A senha no nome do arquivo (#2, #58)

Fonte: `SECURITY_AUDIT.md` (auditoria de 24/09/2026). Branch `seguranca/lote-3`, empilhado sobre `seguranca/lote-2`.

A convenção operacional da pasta de certificados põe a senha do PFX no nome do arquivo ("EMPRESA_CNPJ senha 123456.pfx"). O portal usava esse nome como identidade do certificado: chave primária de `cert_history`, campo de todo item de `cert_snapshots`, resposta de `/api/certificados`, `/duplicidades` e `/historico`, coluna copiável na tela Duplicidades e linha de log do agente. O cofre cifrava a senha; o nome ao lado a entregava em claro.

## O que o levantamento mostrou (banco local, cópia de produção, 25/09/2026)

| Onde | Antes |
|---|---|
| `cert_history` | 1.049 linhas, **1.013** com "senh" na chave primária |
| `cert_snapshots` | 340 snapshots, **247.678** itens com "senh" em `file_name`/`path` |

Formas reais dos nomes (anonimizadas; 1.049 nomes): a dominante é `NOME_CNPJ senha 999999.pfx`; existem também senhas com letras e símbolos (`senha Ab12@!`), sufixo de cópia do Windows depois da senha (`senha 123456 (2)`), anotação depois da senha (`senha 123456 - renovado`), `senha` colada no CNPJ (`…000199senha 123`), `_SENHA` sem espaço, `senh` truncado, número solto depois do CNPJ sem a palavra, CNPJ colado no nome, e nomes sem senha nenhuma. E razões sociais com "SENHOR" e subjects com "Senhora" — que **não** são senha.

## Desenho

Como o roteiro pediu, a limpeza do nome não é a base:

- **A identidade pública de um certificado legível sai do próprio PFX**: `nome` (titular do CN), `documento_numero`, `fingerprint_sha256`, já lidos do X.509 pelo scanner. O `nome_publico` é só o rótulo do arquivo, para a pessoa achá-lo na pasta.
- **O nome original não é gravado nem devolvido.** Nem cifrado nem em hash: um hash de "prefixo conhecido + senha de 6 dígitos" cai em segundos. No lugar dele, `arquivo_chave = sha256(lower(nome_publico) | lower(fingerprint))` — chave de deduplicação derivada só de dado público. O mesmo certificado sob o mesmo nome público é uma linha só, troque-se a senha do arquivo quantas vezes for; o certificado renovado (fingerprint novo) é outra linha, como hoje.
- **A limpeza por regex é o fallback do arquivo ilegível** (sem subject), em `app/nome_publico.nome_publico_de_arquivo`: corta a partir do token `senh`/`senha`/`senhas` quando ele não é precedido por letra e é seguido por espaço, dígito ou símbolo (pega `_SENHA`, `000199senha`, `senh 123`; deixa `DESENHOS`, `ENGENHARIA`, `SENHORA`); sem a palavra, corta o que vier depois de um CPF/CNPJ precedido de separador (`_21640463000198 123456`). Tabela de 25 formas reais anonimizadas em `tests/test_seguranca_lote3.py`.
- **Sanitização em três pontos**, todos com a mesma função (`sanitizar_item`): na entrada (`/api/ingest`, para o agente antigo que ainda manda o nome bruto), na saída das três rotas (para snapshots gravados antes da migração) e na leitura local do servidor (`cert_to_public_dict` já sai público, e é o que o agente novo manda).
- **`pasta` só para admin.** O operador precisa do titular e do documento; a árvore de diretórios do servidor não é dele.

## Achados tratados

| # | Achado | O que mudou |
|---|---|---|
| 2 | Senha do PFX no nome do arquivo, em claro no banco, na API e na tela | `app/nome_publico.py` (novo). `cert_history`: PK `arquivo_chave`, coluna `nome_publico`, sem `file_name`. `cert_snapshots.items[]`: sem `file_name`/`path`, com `nome_publico`/`pasta`/`arquivo_chave`. `/api/ingest` sanitiza na entrada; `/api/certificados`, `/duplicidades` e `/historico` sanitizam na saída e só mandam `pasta` a admin. A busca do histórico (`or_`) procura em `nome_publico`. `/api/mover-vencidos` devolve rótulo e pastas, não caminhos completos. Tela Duplicidades mostra `pasta/nome_publico` (admin) ou só o nome. |
| 58 | Agente loga `c.file_name` | Os cinco pontos de log em `agent/installer_client.py` e `agent/run_agent.py` logam `nome_publico_de_arquivo(c.file_name)`. |

## Arquivos alterados

- `app/nome_publico.py` — novo: `nome_publico_de_arquivo`, `pasta_de`, `chave_de_arquivo`, `sanitizar_item`, `sem_pasta`. Só stdlib, importado pelo agente e pelo script de migração.
- `app/cert_scanner.py` — `cert_to_public_dict` sai sem `file_name`/`path`, com `nome_publico`/`pasta`/`arquivo_chave`; nome de item ilegível limpo.
- `app/settings_state.py` — `upsert_cert_history` grava `arquivo_chave`/`nome_publico` e faz upsert por `arquivo_chave`.
- `app/main.py` — ingest, `_list_certificados_payload`, `listar_certificados` (token + `sem_pasta`), `_item_resumo_duplicidade`/`_agrupar_duplicidades` (`incluir_pasta`), `certificados_duplicidades`, agregação e consulta do histórico, busca do painel, ordenação, `mover_vencidos`.
- `templates/duplicidades.html` — `caminhoDe` usa `nome_publico` e `pasta`.
- `agent/installer_client.py`, `agent/run_agent.py` — logs com o nome público.
- `scripts/migracao_lote3_nome_publico.py` — novo: `--dry-run`, `--ida`, `--volta`.
- `supabase/migrations/20260925120000_cert_history_nome_publico.sql` — registro do esquema final (o script aplica).
- Testes: `tests/test_seguranca_lote3.py` (novo, 48 casos); `tests/test_seguranca_lote1.py` (o fake de banco ganhou `upsert` com `on_conflict`, `range` e `select(count, head)`); `tests/test_cert_scanner.py` e `tests/test_ordem_alfabetica.py` (fixavam `file_name`).

## Testes criados (`tests/test_seguranca_lote3.py`)

Baseline em `4bf7c40`: o arquivo nem coleta (`app.nome_publico` não existia). Com o módulo criado e as rotas ainda intactas, 5 casos ponta a ponta falhavam (snapshot e histórico gravados com o nome bruto, rota do histórico, snapshot antigo, log do agente). Depois das correções, os 48 passam, e a suíte inteira fecha verde: **1174 passam, 9 pulados, 0 falhas** (`pytest`, 25/09/2026).

| Teste | O que prova |
|---|---|
| `test_nome_publico_cobre_as_formas_reais` (×25) | Cada forma real da pasta, anonimizada, vira o nome sem a senha; "SENHORA", "DESENHOS" e "ENGENHARIA" ficam intactos. |
| `test_nome_publico_nunca_devolve_o_que_vem_depois_de_senha`, `test_nome_publico_de_nome_so_com_senha_e_vazio` | O que vem depois do token nunca sai; nome que era só a senha vira vazio (quem chama decide o fallback). |
| `test_pasta_e_o_diretorio_sem_o_nome_do_arquivo` (×5), `test_chave_de_arquivo_nao_carrega_segredo_e_e_estavel` | Pasta sem arquivo; chave estável, sem caixa, distinta por fingerprint e por nome. |
| `test_item_sanitizado_*` (4) | Sem `file_name`/`path`/`password_from_name`; item ilegível com nome limpo; titular do CN com a palavra "SENHA" não é cortado; idempotente e aceita item de agente novo. |
| `test_cert_to_public_dict_ja_sai_publico` | O agente novo nem transporta o nome bruto. |
| `test_snapshot_gravado_nao_tem_nome_bruto`, `test_cert_history_gravado_pela_chave_publica` | Um agente ANTIGO manda quatro itens com senha no nome: o snapshot e o histórico gravados não têm a senha, e duas cópias do mesmo certificado são uma linha. |
| `test_nenhuma_rota_devolve_senha_nem_nome_bruto` (×3), `test_pasta_so_para_admin`, `test_duplicidades_agrupa_pelo_nome_publico` | As três rotas sem "senh", sem `file_name`, sem `path`; `pasta` só para admin; duplicatas agrupadas pelo nome público. |
| `test_snapshot_antigo_ainda_no_banco_sai_sanitizado` | Snapshot gravado antes da migração sai limpo: a API não depende de a migração ter rodado. |
| `test_busca_do_historico_procura_no_nome_publico`, `test_tela_duplicidades_mostra_o_nome_publico`, `test_agente_nao_loga_o_nome_do_arquivo`, `test_mover_vencidos_nao_devolve_o_nome_bruto` | Fonte da busca, tela, agente e mover-vencidos. |
| `test_migracao_transforma_historico_e_resolve_colisoes`, `test_migracao_sanitiza_itens_de_snapshot`, `test_migracao_tem_ida_e_volta` | Funções puras do script: colisão fica com a linha mais recente; itens sanitizados e contados; ida, volta, dry-run e backups existem. |

## Migração — ensaio em cópia (25/09/2026)

Rodada três vezes em cópias frescas do banco local (`CREATE DATABASE … TEMPLATE certguard_imp`), nunca em produção. As duas primeiras encontraram defeitos, corrigidos antes da terceira:

1. O script imprimia uma seta Unicode e o console `cp1252` do Windows o derrubava antes de gravar qualquer coisa. Saída em ASCII e `reconfigure(utf-8)`.
2. A ordem do DDL inseria as linhas novas antes de derrubar a coluna `file_name`, ainda chave primária não nula. A transação reverteu sozinha (backups inclusive); a cópia ficou intacta. A coluna antiga passou a sair antes do insert.
3. Duas formas reais escapavam do regex (`_SENHA 123` e `000199senha 123`): `\b` não vê fronteira entre `_`/dígito e letra. O regex passou a exigir "não precedido de letra"; as três formas entraram na tabela de testes.

Resultado da terceira rodada (`--ida`, exit 0):

```
ANTES  cert_history: 1049 linhas, 1013 com 'senh' no file_name
ANTES  cert_snapshots: 340 snapshots, 247678 itens com 'senh' em file_name/path
PLANO  cert_history: 1049 -> 1031 linhas (18 colisoes resolvidas pela mais recente); 964 com fingerprint conhecido
backup: cert_history_bkp_lote3 (1049), cert_snapshots_bkp_lote3 (340)
DEPOIS cert_history: 1031 linhas, 0 com token de senha em nome_publico/nome
DEPOIS cert_snapshots: 337 snapshots reescritos, 0 itens com file_name/path, 0 campos com token de senha (fora error_message)
```

`--volta` na sequência: `cert_history` restaurada (1.049 linhas, 1.013 com "senh"), 340 snapshots restaurados, chave `file_name` de volta, backups removidos. `--ida` repetida numa base já migrada responde "Nada a fazer".

**Colisões (18):** o mesmo certificado renomeado com senha nova ao longo do tempo. Ficou a linha com `ultima_data_registrada` mais recente. 964 das 1.049 linhas tiveram o fingerprint localizado no snapshot mais recente que as contém; as 85 restantes são arquivos que não aparecem em snapshot nenhum (removidos há muito) e receberam chave sem fingerprint — histórico puro, nunca mais atualizado, como já eram.

**Critério de aceite, como ficou:** o roteiro pedia `SELECT count(*) FROM cert_history WHERE file_name ILIKE '%senh%'` = 0 e nenhuma resposta de API com a substring `SENH`. A coluna `file_name` deixa de existir, então a consulta literal não se aplica; o script confere o **token** de senha (`senh(a|as)?` não precedido de letra e seguido de espaço, dígito ou símbolo) em `nome_publico`/`nome` e em todos os campos dos itens exceto `error_message`, e fecha em 0. A substring pura não serve como critério: duas razões sociais contêm "SENHOR", há subjects com "Senhora", e `error_message` carrega os textos fixos do scanner ("Senha incorreta", "Nome deve seguir: «nome» senha «valor».pfx"). Os testes de API usam dados sintéticos e aí a substring é zero.

**Verificação no navegador** (Chrome/Playwright contra a cópia migrada, admin e operador temporários criados e removidos com a cópia): Início, Histórico, Vencidos e Duplicidades sem erro de JS e sem token de senha no texto; Duplicidades mostra a pasta-base e `pasta/nome_publico` para admin, e o botão copia isso; as três rotas via API sem `"file_name"` nem `"path"`; `"pasta"` só na resposta do admin; os únicos acertos do regex na listagem são 53 `error_message` = "Senha incorreta".

**Ordem de implantação no servidor:**

1. Backup do banco.
2. `python scripts/migracao_lote3_nome_publico.py --dsn <DSN do servidor> --dry-run` e conferir o PLANO.
3. `--ida` (a própria migração faz `cert_history_bkp_lote3` e `cert_snapshots_bkp_lote3` antes de tocar em qualquer linha).
4. Atualizar o portal (`atualizar-portal.ps1`). Entre 3 e 4 o código antigo falha o upsert do histórico (log) e segue gravando snapshots; a tela Histórico cai no fallback de snapshots.
5. Depois de alguns dias sem problema, apagar as duas tabelas `_bkp_lote3` — elas ainda contêm os nomes com senha.

## Janela de compatibilidade

| Mudança | Quem afeta | Janela |
|---|---|---|
| Itens sem `file_name`/`path` | Agente antigo do ANALISESRV continua mandando o nome bruto: o ingest sanitiza. Agente novo (este repositório) já manda o nome público. Nada quebra. | Sem flag; sanitização idempotente nos dois formatos. |
| `cert_history` com chave nova | Código novo antes da migração: upsert do histórico falha com log, snapshot continua; leitura do histórico cai no fallback de snapshots (sanitizado). Código antigo depois da migração: mesmo comportamento invertido. Janela de minutos, documentada acima. | Migração com ida e volta. |
| `pasta` só para admin | A tela Duplicidades do operador mostra só o nome público do arquivo; a do admin mostra a pasta. O operador não perde nada que precisasse: a duplicata é identificada por titular/documento/fingerprint. | — |
| `/api/mover-vencidos` | Resposta muda de `{de, para}` com caminhos completos para `{arquivo, de, para}` com rótulo e pastas. Nenhum consumidor no repositório além do próprio admin. | — |
| Histórico: linhas fundidas | 18 linhas do histórico local desaparecem como duplicatas do mesmo certificado. É o comportamento desejado da chave nova. | Volta restaura. |

Nenhuma variável de ambiente nova.

## Pendente e por quê

- **Rodar a migração em produção** é ação humana (regra 4 do plano). O script está pronto e ensaiado; a ordem está acima.
- **Apagar as tabelas de backup** depois da migração em produção: elas guardam os nomes com senha. Deixado para a pessoa decidir o prazo.
- **Agente instalado no ANALISESRV** ainda manda o nome bruto pela rede (TLS). Some quando o agente 1.3.0 for instalado; até lá o servidor descarta na entrada.
- **`error_message`** continua com os textos fixos do scanner que contêm a palavra "senha" ("Senha incorreta"). Não é segredo; fica.

## Achados novos

- O `PFX_NAME_PATTERN` do scanner (`app/cert_scanner.py`) aceita como senha **tudo** até a extensão: `senha 123456 - renovado.pfx` vira senha `123456 - renovado`, e o certificado fica "Senha incorreta". Isso não é deste lote, mas explica parte dos itens `erro` no inventário. Anotado.
- `SequenceMatcher` do agrupamento por nome (achado #12, lote 5) agora compara `nome_publico`, que é mais curto e mais uniforme que o nome bruto: os grupos "nome similar" tendem a crescer. Observar na tela depois do deploy.
- O fake de banco dos testes (`tests/test_seguranca_lote1.py`) não honrava `on_conflict` no `upsert`: um upsert repetido parecia duplicar. Corrigido neste lote porque o teste do histórico dependia disso; testes antigos não eram afetados porque não contavam linhas depois de dois upserts iguais.
