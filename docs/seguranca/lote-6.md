# Lote 6 — Caminhos e SMTP como vetor (#16, #33, #34, #53)

Fonte: `SECURITY_AUDIT.md` (auditoria de 24/09/2026). Branch `seguranca/lote-6`, empilhado sobre `seguranca/lote-5`.

Método: os 43 testes de `tests/test_seguranca_lote6.py` foram escritos antes da correção e rodados contra `32fcd1e`: **18 falharam e 23 erraram** (funções que ainda não existiam), 2 passaram (controles). Depois das correções os 43 passam, e a suíte inteira fecha verde: **1266 passam, 9 pulados, 0 falhas em 1 min 27** (`pytest`, 25/09/2026). Um teste antigo (`tests/test_config_instalador.py`) comparava a pasta gravada com o texto literal digitado e passou a comparar caminhos resolvidos, porque `validar_pasta` grava a forma canônica.

## Achados tratados

| # | Achado | O que mudou |
|---|---|---|
| 16 | `source_folder`/`expired_folder` viravam `Path(p)` sem raiz permitida nem recusa de UNC; `rglob` sem teto | `settings_state.validar_pasta(bruto, rotulo)`: UNC (`\\`, `//`, `\\?\UNC`) recusado **sempre**, inclusive unidade mapeada que resolve para UNC; `resolve()`; com `PASTAS_PERMITIDAS` (env, `os.pathsep`) o caminho resolvido tem de estar sob uma raiz. Aplicado no `PUT /api/settings` (422) **e** na leitura (`effective_source`/`effective_expired`): valor antigo no banco fora da regra cai no padrão com ERROR no log — a tela de Configuração mostra o caminho efetivo diferente do salvo. `scan_folder` com `os.walk`, `limite_arquivos=20000` (WARNING e para) e `profundidade_max=8` (poda a descida); `C:\` como origem deixa de travar o processo. |
| 33 | Host/porta do SMTP sem lista nem bloqueio de faixa privada | `smtp_service.exigir_destino_publico(host, port)`, chamado **antes** de abrir a conexão em todo envio: porta fora de {25, 465, 587, 2525} → recusa; nome que não resolve → recusa; link-local (`169.254.x`, metadados da nuvem), multicast, reservado, não especificado e loopback disfarçado (`127.0.0.2`, `::ffff:169.254.1.1`) → recusa sempre; rede privada (`10/8`, `172.16/12`, `192.168/16`) só com o host em `SMTP_HOSTS_PERMITIDOS`; `localhost`/`127.0.0.1`/`::1` passam (é o "servidor local" do lote 1). As mensagens não repetem host nem IP. A porta também é validada no `PUT /api/settings` (422). |
| 34 | Vírgula em `?busca=` injetava cláusula na DSL `or_` | Duas pontas: `db_pg._dividir_or` respeita aspas duplas (a sintaxe do PostgREST) e `or_` desfaz as aspas do valor (`_desaspear`, com `\"` e `\\`); `main._filtro_or_da_busca` monta as três cláusulas do histórico com o texto do usuário **entre aspas**, então `x,machine_id.eq.outra` vira um valor literal de ILIKE e não uma quarta cláusula. |
| 53 | `/api/mover-vencidos` devolvia caminhos absolutos | `de`/`para` viram caminhos **relativos** às raízes configuradas (`_pasta_relativa`); fora da raiz, só o último nome. Nenhum caminho absoluto do servidor na resposta. |

## Arquivos alterados

- `app/config.py` — `PASTAS_PERMITIDAS`, `SMTP_HOSTS_PERMITIDOS`, aviso em `verificar_ambiente` para `PASTAS_PERMITIDAS` vazia em produção.
- `app/settings_state.py` — `PastaRecusada`, `validar_pasta`, `_pasta_efetiva`; `effective_source`/`effective_expired` passam pela validação.
- `app/cert_scanner.py` — `_candidatos` com `os.walk`, `LIMITE_ARQUIVOS_VARREDURA`, `PROFUNDIDADE_MAX_VARREDURA`; `scan_folder` ganha os dois parâmetros.
- `app/smtp_service.py` — `PORTAS_SMTP`, `resolver_enderecos`, `exigir_destino_publico`; `validate_smtp_config(port=)`; `send_smtp_email` confere o destino antes de conectar.
- `app/db_pg.py` — `_dividir_or` com aspas; `_desaspear`.
- `app/main.py` — `_valor_or`, `_filtro_or_da_busca`, `_pasta_relativa`; `put_settings` valida pastas e porta; `mover_vencidos` relativo.
- Testes: `tests/test_seguranca_lote6.py` (novo); `tests/test_seguranca_lote1.py` (fixture autouse que resolve `smtp.exemplo.com` para um IP público fixo — o envio agora resolve o nome).

## Testes criados (`tests/test_seguranca_lote6.py`)

| Teste | O que prova |
|---|---|
| `test_unc_e_recusado_sempre` (×3) | `\\atacante\share`, `//atacante/share`, `\\?\UNC\…` recusados mesmo sem lista de raízes. |
| `test_sem_lista_qualquer_pasta_local_e_aceita_e_resolvida`, `test_vazio_continua_sendo_o_padrao` | Janela de compatibilidade: sem lista, pasta local vale, resolvida (`a/../b` → `b`); vazio é o padrão. |
| `test_com_lista_so_dentro_das_raizes` | Sob a raiz passa; `tmp`, `raiz/../outra`, `C:\Windows`, `/etc` recusados. |
| `test_put_settings_recusa_pasta_fora_da_raiz` (×2), `test_put_settings_aceita_pasta_dentro_da_raiz` | 422 sem gravar; dentro da raiz grava o caminho resolvido. |
| `test_valor_ja_gravado_fora_da_raiz_cai_no_padrao_com_aviso` | Defesa em profundidade na leitura, com ERROR no log. |
| `test_scan_folder_tem_teto_de_arquivos`, `..._profundidade`, `..._padrao_continua_recursivo` | 30 arquivos com teto 10 → 10 e WARNING; nível 4 fora com profundidade 2; o padrão continua recursivo. |
| `test_porta_fora_da_lista_de_smtp_e_recusada` (×6) | 8080, 22, 5432, 3389, 0, 70000. |
| `test_destino_link_local_multicast_ou_loopback_disfarcado_e_recusado` (×6) | Metadados da nuvem, multicast, `0.0.0.0`, `127.0.0.2`, IPv4 mapeado em IPv6. |
| `test_rede_privada_so_com_permissao_explicita` (×4) | Recusado sem a lista; passa com o host em `SMTP_HOSTS_PERMITIDOS`. |
| `test_destino_publico_ou_servidor_local_passa` (×5) | Público nas quatro portas e `localhost`/`127.0.0.1`. |
| `test_nome_que_nao_resolve_e_recusado_sem_conectar`, `test_envio_confere_o_destino_antes_de_abrir_conexao` | Nenhuma conexão é aberta para destino recusado. |
| `test_teste_de_smtp_responde_curado_para_destino_interno` | 400 sem o host nem o IP no texto. |
| `test_put_settings_recusa_porta_fora_da_lista` | 422. |
| `test_dividir_or_respeita_aspas`, `test_or_com_valor_entre_aspas_vira_um_parametro_so`, `test_busca_com_virgula_nao_injeta_clausula`, `test_busca_com_aspas_e_barra_sobrevive` | A DSL com aspas; `x,machine_id.eq.outra` vira três cláusulas com o literal como parâmetro, e `machine_id` não aparece no SQL. |
| `test_mover_vencidos_devolve_caminhos_relativos_as_raizes` | `de: "clientes"`, `para: ""`, nenhum trecho do caminho absoluto na resposta. |

## Janela de compatibilidade

| Mudança | Quem afeta | Janela |
|---|---|---|
| `PASTAS_PERMITIDAS` (padrão vazio) | Vazio = qualquer pasta local, como sempre; aviso em `verificar_ambiente` em produção. Ao definir (ex.: `F:\07. CERTIFICADOS;F:\99.CERTIFICADOS VENCIDOS` — `;` no Windows), um valor já gravado fora das raízes **cai no padrão com ERROR no log** e a tela de Configuração mostra o caminho efetivo diferente do salvo. Conferir as duas pastas gravadas antes de definir a variável. | Flag com padrão seguro para o que existe. |
| UNC recusado sempre | Instalação que aponte a origem para um compartilhamento de rede deixa de funcionar e cai no padrão com ERROR. A pasta do ANALISESRV é local (`F:`). | Sem flag: é o vetor do hash NTLM. |
| Tetos da varredura | Pasta com mais de 20.000 `.pfx` ou mais de 8 níveis é lida até o teto, com WARNING. A pasta real tem ~1.000 arquivos em 3 níveis. | Parâmetros com padrão folgado. |
| Destino do SMTP | Gmail/Office365 (público) continuam. Um relay na rede interna passa a exigir `SMTP_HOSTS_PERMITIDOS=<nome ou IP>` no `.env`; sem isso o envio falha com "Servidor SMTP em rede interna não é permitido…" e os alertas param — o log e o botão de teste dizem por quê. Porta fora de 25/465/587/2525 é recusada no salvar. | Sem flag para as faixas reservadas (é o SSRF); a lista cobre o relay legítimo. |
| DSL `or_` | Só o histórico usa `or_`; a busca com vírgula ou ponto passa a funcionar como texto literal. | — |
| `/api/mover-vencidos` | Resposta com caminhos relativos. Nenhum consumidor além do admin. | — |

Nenhuma migração de dados.

## Pendente e por quê

- **TOCTOU de DNS (rebinding)**: o destino é resolvido e conferido antes de conectar, mas `smtplib` resolve o nome de novo ao conectar. Fechar exige conectar pelo IP conferido e validar o certificado pelo nome (`server_hostname`), o que a `smtplib` não expõe sem subclasse. Risco residual baixo (exige controlar o DNS do host configurado por um admin); anotado.
- **`PASTAS_PERMITIDAS` e `SMTP_HOSTS_PERMITIDOS` em produção** são ação humana no `.env` do servidor.
- **Agente**: `scan_folder` no agente ganhou os mesmos tetos por padrão (é o mesmo módulo); o agente instalado só os recebe na próxima versão.

## Achados novos

- `validate_smtp_config` era chamada no `PUT /api/settings` sem a porta; a porta só chegava ao envio. Agora as duas pontas conferem.
- O `Path("Z:\\").resolve()` de uma unidade de rede mapeada devolve o UNC no Windows: a recusa de UNC pega também esse caso, o que não estava no relatório.
