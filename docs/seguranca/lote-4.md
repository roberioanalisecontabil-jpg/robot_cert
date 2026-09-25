# Lote 4 — Leitura restrita à carteira (#5, #31, #32, #54, #61)

Fonte: `SECURITY_AUDIT.md` (auditoria de 24/09/2026). Branch `seguranca/lote-4`, empilhado sobre `seguranca/lote-3`.

O portal impedia **instalar** fora da carteira (`assegurar_carteira`, desde 18/08) mas não impedia **ler** a base inteira de clientes: `/api/certificados` devolvia até 5.000 itens — titular, CNPJ/CPF, subject, fingerprint, datas — a qualquer autenticado, inclusive `role=user`; o mesmo valia para histórico, vencidos, as opções do Acompanhamento e o cofre disponível. A trilha e os logs de instalação expunham e-mail e IP de todos os operadores a quem tivesse `instalador: ler`.

Método: os 19 testes de `tests/test_seguranca_lote4.py` foram escritos antes da correção e rodados contra `a36556c`: **16 falharam, 3 passaram** (controles: admin vê tudo, datas válidas continuam filtrando, contrato do universo de documentos). Depois das correções os 19 passam, e a suíte inteira fecha verde: **1193 passam, 9 pulados, 0 falhas** (`pytest`, 25/09/2026).

## Desenho: um recorte só

`_recortar_pela_carteira(itens, alcance)` em `app/main.py`, alimentado por `_documentos_ao_alcance(token)`, que chama `cert_installer.documentos_ao_alcance(user_id, role)`:

| Papel | Alcance de leitura |
|---|---|
| `admin` | tudo (`None`: sem recorte) |
| `gestor` | a própria carteira **mais** as carteiras de quem está nos departamentos que ele lidera — o mesmo alcance que `pode_gerir` lhe dá para atribuir |
| `user` | a própria carteira |
| qualquer um, carteira ilegível | **503**, nunca lista vazia ("não consegui ler" não é "não tem") |

Item sem documento (arquivo ilegível) não é de ninguém e fica de fora para quem não tem alcance total. O gestor recebeu alcance de setor de propósito: desde 18/08 ele não tem alcance total, e recortá-lo só pela própria carteira (normalmente vazia) deixaria o Início dele em branco.

Sem banco configurado (modo local de arquivos, sem diretório de usuários nem login) não há por onde recortar e a leitura segue como sempre; em produção o banco existe.

## Achados tratados

| # | Achado | O que mudou |
|---|---|---|
| 5 | Acervo inteiro a qualquer autenticado | Recorte em `/api/certificados` antes de resumo, paginação e exportação (as exportações PDF/Excel são feitas no navegador a partir desta resposta); em `/api/certificados/historico` (com paginação feita **depois** do recorte, para o total contar só o que a pessoa vê); em `/api/certificados/vencidos`; em `/api/colaborador/certificados/opcoes`. |
| 32 | `/api/cert-installer/available` listava o cofre inteiro | Recortado pelo documento do certificado. |
| 31 | `/logs` e `/trilha` com e-mail e IP de todos; `user_email` filtro livre | Sem alcance total: `/logs` só os próprios eventos e sem `client_ip`; `/trilha` com `user_email` forçado ao da sessão e sem `client_ip`. Admin inalterado. |
| 54 | `busca` ignorada no export do histórico; datas dos vencidos sem validação | `historico_certificados` aplica a busca também no caminho não paginado de `cert_history` (era exatamente o caminho do arquivo exportado). `data_inicio`/`data_fim` passam por `_data_da_query`: fora de `AAAA-MM-DD` ou data impossível (`2026-13-99`) → 422; antes viravam `datetime.min` e o filtro sumia em silêncio. |
| 61 | `/api/carteira/documentos` devolve o universo a qualquer líder | **Risco aceito e documentado.** O líder precisa poder atribuir qualquer cliente à carteira de um operador do seu setor — recortar o universo tornaria impossível incluir um cliente novo. O que fica garantido por teste: só admin ou líder chega (`require_admin_ou_lider`), e cada item traz só `nome` e `documento`. |

## Arquivos alterados

- `app/cert_installer.py` — `documentos_ao_alcance(user_id, role)`.
- `app/main.py` — `_documentos_ao_alcance`, `_recortar_pela_carteira`, `_data_da_query`; aplicação em `listar_certificados`, `historico_certificados_http`, `historico_certificados` (busca no export), `vencidos_certificados`, `colaborador_opcoes_certificados`, `list_available_certificates`, `list_installer_logs`, `trilha_de_instalacao`.
- Testes: `tests/test_seguranca_lote4.py` (novo); `tests/test_seguranca_lote1.py` (o fake de banco ganhou `quebrado` por tabela, para testar falha fechada).

## Testes criados (`tests/test_seguranca_lote4.py`)

| Teste | O que prova |
|---|---|
| `test_operador_so_ve_a_propria_carteira`, `test_operador_sem_setor_so_ve_a_propria_carteira` | Operador recebe só os documentos da própria carteira. |
| `test_lider_ve_a_propria_carteira_e_as_do_seu_setor` | Gestor vê a própria carteira e as dos operadores do setor que lidera; não vê a de operador sem setor nem cliente de ninguém. |
| `test_admin_continua_vendo_tudo` | Controle: cinco itens, inclusive o ilegível sem documento. |
| `test_paginacao_conta_so_o_que_a_pessoa_alcanca` | `total_itens` e `total_paginas` contam o recorte, não o acervo. |
| `test_carteira_indisponivel_e_503_e_nao_lista_vazia` | Tabela `carteira` fora do ar → 503 para operador; admin não depende dela. |
| `test_historico_recortado`, `test_vencidos_recortado`, `test_opcoes_do_acompanhamento_recortadas`, `test_cofre_disponivel_recortado` | O mesmo recorte nas quatro outras leituras, com total coerente. |
| `test_recorte_exclui_item_sem_documento_para_quem_nao_tem_alcance_total` | Função pura: sem documento sai; `None` não recorta. |
| `test_logs_so_os_proprios_e_sem_ip`, `test_trilha_ignora_user_email_alheio_e_esconde_ip` | Escopo e ausência de `client_ip` para operador; admin filtra e vê IP. |
| `test_export_do_historico_aplica_a_busca` | Duas linhas em `cert_history`, `todas_filtradas&busca=ALFA` → uma. |
| `test_data_invalida_nos_vencidos_e_422` (×3), `test_data_valida_nos_vencidos_continua_filtrando` | `abc`, `2026-13-99` e data-hora → 422; intervalo válido filtra. |
| `test_universo_de_documentos_so_nome_e_documento_e_so_para_lider` | Contrato mínimo do #61. |

Ajuste de isolamento: a agregação do histórico tem cache em RAM com TTL (`app/historico_agg_cache.py`); a fixture limpa o cache antes e depois, porque o agregado de outro teste respondia por este quando a suíte rodava inteira.

## Janela de compatibilidade

| Mudança | Quem afeta | Janela |
|---|---|---|
| Recorte nas leituras | Operador (`user`) passa a ver no Início, Histórico, Vencidos e Acompanhamento só os clientes da própria carteira; gestor, os do setor. Quem hoje usa o Início como consulta geral sem ter carteira **vai ver a lista vazia** — o sinal de que falta atribuir carteira, e não um defeito. `scripts/diagnostico.py` chama com `X-API-Key` (papel `agent`) e continua vendo tudo. | Sem flag: a leitura fora da carteira era o achado. |
| Arquivo ilegível (sem documento) | Some do Início do operador; admin continua vendo (é ele quem conserta o arquivo). | — |
| Datas dos vencidos | Cliente que mandava data em formato livre passa a receber 422. A tela manda `AAAA-MM-DD` (`input type=date`). | — |
| `/logs` e `/trilha` | Só muda para quem não é admin, e hoje só admin tem `instalador: ler` por padrão. | — |

Nenhuma migração de dados; nenhuma variável de ambiente nova.

## Pendente e por quê

- **Gestor sem liderança registrada** (`departamento_lider` vazio) fica com o alcance da própria carteira — provavelmente vazio. É consequência do modelo de 18/08, não deste lote; a tela Carteiras já recusa esse gestor com a mensagem "não lidera departamento".
- **`/api/carteira/documentos`** continua devolvendo o universo ao líder (risco aceito, acima).
- **Dashboard** (`/api/dashboard`, `/renovacoes`) não estava no escopo do lote e continua agregando o acervo inteiro para quem tem `dashboard: ler` (padrão de gestor). Anotado como achado novo.

## Achados novos

- `/api/dashboard` e `/api/dashboard/renovacoes` agregam contagens e a curva de vencimento sobre o acervo inteiro para qualquer papel com `dashboard: ler`. São agregados (sem titular), mas a lista de renovações traz nomes. Candidato ao mesmo recorte num lote seguinte.
- A suíte completa tinha subido de ~2 min para ~6 min ao longo dos lotes: a fixture de banco dos quatro arquivos de lote recriava cada usuário com bcrypt custo 12 (2,5 s de setup por teste). O hash de teste passou a ser calculado uma vez por senha (`_hash_de` em `tests/test_seguranca_lote1.py`); a suíte voltou a ~3 min 50. O que sobra são os testes de rate limit, que fazem dezenas de logins reais de propósito.
