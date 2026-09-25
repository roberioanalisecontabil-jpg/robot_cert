# Lote 2 — Identidade da máquina (fecha o risco crítico #3)

Fonte: `SECURITY_AUDIT.md` (auditoria de 24/09/2026). Branch `seguranca/lote-2`, empilhado sobre `seguranca/lote-1` (o PR do lote 1 ainda não estava mesclado quando este começou).

O ponto cego do relatório era um só: a credencial de máquina (`app/machine_credentials.py`) era **autenticada e descartada** em `require_auth`, e todo `machine_id` que decidia fila, custódia e cofre vinha do chamador. Este lote faz a identidade viajar no `TokenData` e usa **só ela**.

Método: os 32 testes de `tests/test_seguranca_lote2.py` foram escritos antes da correção e rodados contra `6b8c286` (fim do lote 1): **18 falharam, 5 erraram** (fixture de uma função que ainda não existia) e 9 passaram como controles (fila própria, curinga, admin, chave compartilhada aceita com a flag ligada). Depois das correções, os 32 passam, e a suíte inteira fecha verde: **1123 passam, 9 pulados, 0 falhas** (`pytest`, 25/09/2026).

## Achados tratados

| # | Achado | O que mudou |
|---|---|---|
| 3 | `/api/agent/next` consumia a fila de qualquer máquina | `TokenData.machine_id` vem da credencial. `_machine_da_credencial(token, declarado, exigir_identidade=True)`: credencial de máquina só fala por si (outra máquina → 403, comando fica na fila do dono); chave compartilhada → 403 **sempre**, mesmo com a janela ligada; admin continua lendo qualquer fila. Curingas `*`/`all` continuam chegando a cada máquina; enfileirá-los já era admin-only (`/api/agent/commands`, teste de controle). |
| 4 | `/upload-pfx` e `/api/ingest` com `machine_id` e `documento` declarados | `machine_id` da credencial nas duas rotas (declarar outra → 403; não declarar → a própria). No upload, o PFX é **lido** (`cert_installer.ler_metadados_do_pfx`): o fingerprint declarado tem de ser o do certificado dentro dele (422 se não for), e `documento`, `documento_tipo`, `nome_titular`, `subject`, `not_before`, `not_after` gravados são os do certificado, não os do corpo. PFX que não abre com a senha → 422. A leitura acontece **depois** da barreira de custódia: só se abre o PFX de quem já podia mandar. |
| 21 | `/claim` não conferia a máquina-alvo | `cert_installer.alvo_do_token` lê o token sem consumir; a máquina-alvo é conferida **antes** do compare-and-swap, para o token sobrar para a máquina certa. Com `CLAIM_EXIGE_CREDENCIAL_DE_MAQUINA=1`: a `X-API-Key` tem de ser a credencial de máquina da estação-alvo (chave compartilhada e outra máquina → 403, resposta única). Desligada (padrão): `X-Machine-Id`, quando vem, tem de casar com o alvo; quando não vem, WARNING no log. `/redeem` passou a exigir identidade de máquina e a conferir o alvo sempre. |
| 30 | `/instalabilidade` e `/vault-optin` com `machine_id` livre | `/instalabilidade`: sem alcance total, a estação tem de estar entre as da pessoa no portal de inventário (`_dispositivos_da_pessoa`, extraído de `minha_estacao`); se o INVENT não responde ou a ponte não está configurada, o vínculo não é conferido e o log avisa. Itens `fora_da_carteira` **não saem** da resposta (o rótulo decidia a cor; o fingerprint e o id do cofre vazavam). `/vault-optin` GET: agente só pergunta pela própria estação. |
| 22 | Desativar/excluir não revogava tokens pendentes | `cert_installer.revogar_tokens_pendentes(user_id)` marca `consumed_at` nos `install_token` abertos; chamado em desativar, excluir e editar para inativo. Nunca levanta. |
| 62 | `enqueue_install_command` morto | Removido, com os 2 testes que só o exercitavam; a propriedade da fila que sobrava (payload não vaza em `/api/agent/queue`) ficou testada direto por `command_queue.enqueue`. |
| — | Janela da chave compartilhada | `ACEITAR_API_KEY_COMPARTILHADA` (padrão: aceita sem `DATABASE_URL`, recusa com). Desligada, a chave compartilhada leva 401 em `require_auth` **sem** o marcador `X-Credencial-Invalida` (o agente não deve descartar nada) e WARNING. Ligada, passa em inventário e cofre com o `machine_id` declarado e WARNING por chamada; **nunca** em fila nem resgate. |

## Arquivos alterados

- `app/auth.py` — `TokenData.machine_id`.
- `app/config.py` — `ACEITAR_API_KEY_COMPARTILHADA`, `CLAIM_EXIGE_CREDENCIAL_DE_MAQUINA`, `_env_bool`.
- `app/main.py` — `require_auth`, `_machine_da_credencial`, `/api/agent/next`, `/api/ingest`, `/upload-pfx`, `/vault-optin` GET, `/redeem`, `/claim` + `_exigir_maquina_alvo_no_claim`, `/instalabilidade`, `_dispositivos_da_pessoa`, `_revogar_tokens_de_instalacao` em desativar/excluir/editar.
- `app/cert_installer.py` — `alvo_do_token`, `revogar_tokens_pendentes`, `ler_metadados_do_pfx`; `enqueue_install_command` removido.
- Testes: `tests/test_seguranca_lote2.py` (novo, 32 casos); `tests/pfx_de_teste.py` (novo: gera um PFX autoassinado real, com CN `NOME:CNPJ`); ajustes em `tests/test_cofre_custodia_e2e.py` (o upload legítimo passa a mandar um PFX real), `tests/test_api_routes.py` (consumo da fila pela chave compartilhada → 403; o consumidor do teste de ping vira admin), `tests/test_inicio_selecao.py` (`fora_da_carteira` deixa de sair), `tests/test_cert_installer_hardening.py` (dois testes do caminho morto removidos).

## Testes criados (`tests/test_seguranca_lote2.py`)

| Teste | O que prova |
|---|---|
| `test_maquina_nao_puxa_a_fila_de_outra` | Credencial de A pedindo a fila de B → 403, o payload não aparece, o comando continua na fila de B. |
| `test_maquina_puxa_a_propria_fila`, `test_machine_id_compara_sem_caixa`, `test_curinga_continua_chegando_a_cada_maquina`, `test_admin_continua_lendo_qualquer_fila`, `test_so_admin_enfileira_curinga` | Controles: o que era legítimo continua. |
| `test_chave_compartilhada_nao_puxa_fila_nenhuma` | Mesmo com a janela ligada, 403 e comando intacto. |
| `test_chave_compartilhada_recusada_com_a_flag_desligada`, `..._aceita_com_a_flag_ligada`, `test_credencial_de_maquina_continua_valendo_com_a_flag_desligada` | A flag: 401 sem marcador de descarte; WARNING quando aceita; credencial de máquina indiferente à flag. |
| `test_ingest_nao_grava_inventario_de_outra_maquina`, `..._da_propria_maquina_grava`, `..._sem_machine_id_declarado_usa_o_da_credencial` | Inventário só da máquina autenticada. |
| `test_upload_nao_grava_no_cofre_de_outra_maquina` | 403 e cofre vazio. |
| `test_upload_grava_os_metadados_lidos_do_proprio_pfx` | Corpo diz `documento=9999…`, `subject=CN=FORJADO`; o cofre grava o CNPJ, o titular, o subject e o vencimento do certificado. |
| `test_upload_recusa_fingerprint_que_nao_e_do_pfx` | O passo do envenenamento: PFX do atacante sob fingerprint legítimo → 422, cofre vazio. |
| `test_upload_recusa_pfx_ilegivel_com_a_senha` | 422, cofre vazio. |
| `test_claim_com_x_machine_id_de_outra_maquina_e_recusado` | 403 e token **não consumido**. |
| `test_claim_com_x_machine_id_da_maquina_alvo_passa`, `test_claim_sem_identificacao_ainda_passa_na_janela_mas_avisa` | A janela: casa sem caixa; sem cabeçalho passa e o log diz "sem identificação". |
| `test_claim_exige_credencial_de_maquina_quando_a_flag_manda` | Sem credencial, chave compartilhada e outra máquina → 403 sem consumir; a máquina-alvo → 200 e consome. |
| `test_redeem_nunca_aceita_a_chave_compartilhada`, `test_redeem_confere_a_maquina_alvo` | Idem para `/redeem`. |
| `test_instalabilidade_omite_o_que_esta_fora_da_carteira`, `..._de_estacao_nao_vinculada_e_recusada`, `test_admin_continua_vendo_tudo_em_qualquer_estacao`, `test_sem_ponte_com_o_inventario_a_estacao_nao_e_conferida_mas_a_carteira_sim` | Recorte por carteira, vínculo por estação, degradação com aviso. |
| `test_vault_optin_so_responde_a_propria_maquina` | Credencial de B perguntando por A → 403. |
| `test_desativar_usuario_queima_os_tokens_pendentes`, `test_excluir_...`, `test_editar_para_inativo_...` | `consumed_at` marcado e `/claim` do token → 403. |
| `test_nao_existe_mais_enfileiramento_de_token_na_fila_local` | `enqueue_install_command` não existe. |

Verificação de conflito com testes antigos: 13 fixavam o comportamento anterior (upload com quatro bytes em base64 como "PFX", fila consumida pela chave compartilhada, `fora_da_carteira` rotulado). Cada um foi ajustado com o motivo em comentário; nenhum foi apagado sem substituto.

## Janela de compatibilidade

| Mudança | Quem afeta | Janela |
|---|---|---|
| `ACEITAR_API_KEY_COMPARTILHADA` | Estações que ainda autenticam pela `X-API-Key` compartilhada (o ANALISESRV até instalar o agente 1.2.0+; a Fase 0 pediu essa contagem e ela **não foi informada**). Padrão em produção: **recusa** (`DATABASE_URL` definida). Se houver estação não migrada, definir `=1` no `.env` do servidor até o WARNING "autenticou pela X-API-Key compartilhada" zerar no log; depois remover. | Flag com padrão seguro; 401 explícito com WARNING, nunca em silêncio. |
| Fila e resgate recusam a chave compartilhada mesmo com a flag ligada | Uma estação na chave compartilhada continua **ingerindo e subindo PFX** (com WARNING), mas deixa de receber `rescan`/`mover_vencidos`/`ping` pela fila e de resgatar token em `/redeem` até ter credencial própria. | Sem flag: sem identidade não há como saber de quem é a fila. |
| `CLAIM_EXIGE_CREDENCIAL_DE_MAQUINA` (padrão desligado) | O agente do INVENT (`INVENT/core/instalador_certificado.py`) resgata em `/claim` mandando só `token` e `clientPublicKey`. Ligar hoje pararia toda instalação. Enquanto desligada, o `/claim` confere `X-Machine-Id` se vier e avisa se não vier. | Ligar quando o agente do INVENT passar a apresentar uma credencial de máquina **deste** portal (mudança no repositório INVENT: provisionar via `/api/agent/maquinas/provisionar` e mandar `X-API-Key` no `/claim`). Passo intermediário barato, também no INVENT: mandar `X-Machine-Id: <mac>` no `/claim` — fecha o roubo oportunista do #3 sem credencial. |
| Metadados do cofre lidos do PFX | O agente do ANALISESRV continua mandando `documento`/`subject`/datas no corpo; são ignorados. PFX cuja senha o agente não conheça (nome fora do padrão) passa a ser recusado com 422 em vez de gravado sem senha — e ele já não era instalável. | Sem flag; nenhuma mudança no agente. |
| `/instalabilidade` restrita à estação vinculada | Operador que abre o Início numa máquina cujo agente do INVENT não está vivo em seu nome: o botão "Instalar nesta máquina" já não aparecia (`minha_estacao`), então a tela não muda. Sem ponte INVENT configurada, o vínculo não é conferido (WARNING) e o recorte por carteira vale sozinho. | Degradação com aviso. |
| Tokens revogados ao desativar | Nenhum efeito em conta ativa. | — |

Nenhuma migração de dados: o lote não altera esquema nem linhas existentes.

### Como migrar uma estação para a credencial de máquina

1. Instalar o agente **1.2.0 ou superior** na estação (o `.exe` de 04/09 está no Desktop; o serviço provisiona sozinho na primeira subida: `POST /api/agent/maquinas/provisionar` com a `X-API-Key` compartilhada, guarda o segredo em `ProgramData\…\maquina.dat` cifrado com DPAPI e passa a mandá-lo no mesmo cabeçalho).
2. Enquanto houver estação nesse passo, `ACEITAR_API_KEY_COMPARTILHADA=1` no servidor — sem isso o provisionamento (que usa a chave compartilhada para provar posse) é recusado.
3. Conferir no log do portal que o WARNING "Agente autenticou pela X-API-Key compartilhada" parou de aparecer para aquela estação, e em `GET /api/agent/maquinas` (admin) que ela consta com `visto_em` recente.
4. Emissão perdida (serviço recebeu o segredo e não gravou; o log do agente diz "já tem credencial, mas não há maquina.dat"): admin faz `POST /api/agent/maquinas/{machine_id}/reemitir` e reinicia o serviço.
5. Quando todas constarem, remover `ACEITAR_API_KEY_COMPARTILHADA` do `.env` (volta ao padrão: recusa) e, na sequência, trocar a `API_KEY` (Fase 0).

O `machine_id` da credencial é gravado em minúsculas e comparado sem caixa com o que o agente declara: `ANALISESRV` e `analisesrv` são a mesma máquina.

## Pendente e por quê

- **#21 na forma forte** (credencial de máquina obrigatória no `/claim`) depende do agente do INVENT, que está em outro repositório. Está pronto atrás da flag; ligar é ação humana depois da mudança lá.
- **#3 no INVENT**: a fila que o agente do INVENT consome é a do outro portal; se lá o `machine_id` também vier da query, o roubo do token continua possível por aquele caminho. Não verificável nem corrigível daqui; registrado para o INVENT.
- **`X-API-Key` compartilhada**: a contagem de estações que ainda a usam (Fase 0) decide se a flag precisa ser ligada no deploy. Sem a resposta, o deploy com o padrão (recusa) **pode parar o agente do ANALISESRV** se ele ainda não tiver credencial própria. Conferir o log antes.
- `/vault-optin` GET para gente (módulo Instalador) continua com `machine_id` livre: é admin-only por padrão e a tela precisa listar qualquer estação.

## Achados novos

- O agente do INVENT resgata em `/claim` sem identificar a máquina de nenhuma forma (nem `X-Machine-Id`), o que deixa o `target_machine` do token sem contraparte no resgate. É o que a flag deste lote espera; anotado para o repositório INVENT.
- `require_agent_or_admin` aceita um **JWT** com `role=agent` (é o que `tests/test_cofre_custodia_e2e.py` usa como "agente"). Nenhuma rota emite esse JWT hoje, mas se alguém o emitir, ele passa nas rotas de máquina sem `machine_id`, caindo na janela da chave compartilhada. Vale restringir `role=agent` à `X-API-Key` (lote 9 ou INVENT).
- `identidade_maquina.provisionar` no agente usa a chave compartilhada para provar posse: com `ACEITAR_API_KEY_COMPARTILHADA` desligada, uma estação nova não consegue se provisionar sozinha. Documentado no roteiro acima; a alternativa (admin emitir e entregar o segredo fora de banda) fica para quando a chave compartilhada for retirada de vez.
