# Lote 8 — Criptografia do cofre (#19, #42, #55, #56)

Fonte: `SECURITY_AUDIT.md` (auditoria de 24/09/2026). Branch `seguranca/lote-8`, empilhado sobre `seguranca/lote-7`. É o lote de maior risco operacional: mexe em como o cofre é cifrado e lido. **Nenhuma chave antiga é removida por este lote** — remover é decisão humana, depois de "Recifrar cofre" zerar e o Revalidar provar.

Método: os 25 testes de `tests/test_seguranca_lote8.py` foram escritos antes da correção e rodados contra `c2da1a6` (fim do lote 7): **23 falharam, 2 passaram** (controles: código errado continua recusado; a rota de recifrar não existia e o 403 do `user`/`gestor` já vinha do roteador). Depois das correções os 25 passam, e a suíte inteira fecha verde: **1315 passam, 9 pulados, 0 falhas em 1 min 28** (`pytest`, 25/09/2026). Três testes antigos foram adaptados porque descreviam a implementação anterior: dublê de `encrypt_pfx_at_rest` sem o argumento `aad`, comparação com a constante `CURRENT_KEY_VERSION` (que virou variável de ambiente) e o hash do código de redefinição como 64 hex puros. O que eles garantiam continua garantido.

## Achados tratados

| # | Achado | O que mudou |
|---|---|---|
| 19 | A senha do PFX era cifrada sem `key_version` e sempre decifrada com a chave corrente: rotacionar `CERT_PASSWORD_ENCRYPTION_KEY` tornava todas as senhas do cofre ilegíveis | Coluna nova `password_key_version` (DEFAULT 1 = tudo o que existia). `CERT_PASSWORD_ENCRYPTION_KEY_VERSION` no ambiente diz a versão em vigor; as anteriores ficam em `CERT_PASSWORD_ENCRYPTION_KEY_V<n>` (o config as carrega como já fazia para o PFX). `decifrar_senha_da_linha(row)` usa a versão gravada; linha sem a coluna vale 1. O upsert grava a versão em vigor. Revalidar passa a provar também a senha (`senha_ok`) e o diagnóstico ganha bloco `senha` com versões no cofre, configuradas e **sem chave**. |
| 42 | `CERT_ENCRYPTION_KEY_V1` inalcançável (a versão em vigor era a constante 1); versões antigas aceitas para sempre; nada recifrava; a ajuda do botão prometia correção | A versão em vigor vem do ambiente (`CERT_ENCRYPTION_KEY_VERSION`, padrão 1). `verificar_ambiente` avisa quando `_V<versão em vigor>` está definida (nunca seria lida) e recusa `_V<n>` fora do formato. Nova rota `POST /api/cert-installer/recifrar-cofre` e botão "Recifrar cofre": regrava só as linhas fora do estado em vigor (versão do PFX, da senha ou envelope), decifrando com a versão gravada e cifrando com a em vigor; **linha que não decifra fica intocada e vem em `falhas`**; `limite` de 500 por chamada, idempotente. Diagnóstico mostra "para recifrar". A ajuda do Revalidar passou a dizer que ele só prova; a do Recifrar diz quando usar e quando a chave antiga pode sair. |
| 55 | AES-GCM sem dados associados: um ciphertext podia ser trocado de linha (outra máquina, outro fingerprint) sem a tag acusar | AAD `machine_id|fingerprint|key_version` no PFX e `machine_id|fingerprint|senha|password_key_version` na senha. Coluna `aad_version` (0 = envelope antigo, 1 = com AAD) diz à decifra o que esperar — não se tenta "com e sem". Envelope antigo aceito com WARNING (uma vez por processo) enquanto `COFRE_EXIGE_AAD` estiver desligada; ligada, `EnvelopeLegado`. "Recifrar cofre" leva tudo a `aad_version = 1`, mesmo sem rotação de chave. |
| 56 | Código de redefinição em SHA-256 puro: tabela de 10⁶ entradas revelava todos os códigos pendentes de um dump | `senha_reset._hash` → `v2$<sal>$<HMAC-SHA256>` com sal aleatório por linha e o segredo do servidor (`JWT_SECRET_KEY`). `_confere` aceita o formato antigo (sha256 puro) com WARNING — um código pedido antes do deploy vale 15 min e tem de funcionar; a janela se fecha sozinha porque nenhum hash novo nasce no formato antigo. Sem migração: os dois formatos se distinguem pela forma. |

## Arquivos alterados

- `app/config.py` — `CERT_ENCRYPTION_KEY_VERSION`, `CERT_PASSWORD_ENCRYPTION_KEY_VERSION`, `COFRE_EXIGE_AAD`; carga de `CERT_PASSWORD_ENCRYPTION_KEY_V*`; avisos em `verificar_ambiente`.
- `app/cert_installer.py` — `versao_corrente`, `versao_corrente_senha`, `AAD_VERSAO_ATUAL`, `EnvelopeLegado`, `_get_server_key`/`_get_password_key` por versão, `aad_do_pfx`, `aad_da_senha`, `_cifrar`/`_decifrar`, `encrypt_*`/`decrypt_*` com `aad`, `_aad_da_linha`, `decifrar_pfx_da_linha`, `decifrar_senha_da_linha`, `precisa_recifrar`, `recifrar_cofre`, `descrever_falha_de_decifra_da_senha`; `upsert_pfx` grava as colunas novas; `build_encrypted_bundle` e `revalidar_cofre` leem pela linha; `diagnostico_do_cofre` (`senhas_por_key_version`, `sem_aad`, `para_recifrar`) e `diagnostico_das_chaves` (`senha`, `linhas_para_recifrar`, `exige_aad`). `CURRENT_KEY_VERSION` deixou de existir.
- `app/main.py` — rota `recifrar-cofre`; textos `ajuda_revalidar`/`ajuda_recifrar`; problemas de envelope antigo e de senha sem chave no diagnóstico.
- `app/senha_reset.py` — `PREFIXO_HASH`, `_segredo`, `_hash(codigo, sal)`, `_hash_legado`, `_confere`.
- `templates/instalador.html` — botão e área "Recifrar cofre"; itens novos no diagnóstico (sem dados associados, para recifrar, versão da senha, senhas por versão, exige AAD).
- `supabase/migrations/20260926100000_cofre_versao_da_senha_e_aad.sql` — as duas colunas, idempotente.
- `scripts/migracao_lote8_cofre.py` — `--dry-run`, `--ida`, `--recifrar`, `--volta`.
- Testes: `tests/test_seguranca_lote8.py` (novo); `tests/test_cert_installer_hardening.py`, `tests/test_recuperacao_de_senha.py` (adaptados).

## Testes criados (`tests/test_seguranca_lote8.py`)

| Teste | O que prova |
|---|---|
| `test_upsert_grava_versao_da_senha_e_versao_do_envelope` | O upsert grava `key_version`, `password_key_version` e `aad_version`. |
| `test_senha_cifrada_na_v1_decifra_depois_da_rotacao_para_v2` | O "Como testar" do #19: cifrar em v1, subir com v2 em vigor e v1 em `_V1`, decifrar PFX e senha. |
| `test_depois_da_rotacao_o_upsert_grava_na_versao_nova` | Após a rotação, linha nova sai em v2/v2 e decifra. |
| `test_linha_antiga_sem_versao_da_senha_e_tratada_como_v1` | Banco anterior à migração (coluna ausente) vale 1. |
| `test_versao_em_vigor_vem_do_ambiente` | `versao_corrente()` segue o config. |
| `test_ciphertext_trocado_de_linha_nao_decifra`, `test_mudar_a_maquina_da_linha_tambem_falha` | O "Como testar" do #55: ciphertext de outra linha, ou linha com outra máquina, dá `InvalidTag`; as íntegras continuam abrindo. |
| `test_linha_legada_sem_aad_ainda_decifra_com_aviso` | Janela: envelope antigo decifra e o log manda recifrar. |
| `test_com_cofre_exige_aad_a_linha_legada_e_recusada` | `COFRE_EXIGE_AAD=1` fecha a janela (`EnvelopeLegado`). |
| `test_recifrar_leva_tudo_para_a_versao_em_vigor_e_com_aad` | O "Como testar" do #42: linhas v1, rotação para v2, recifrar → `count(key_version < 2) = 0`, tudo decifra, e decifra **sem** as chaves `_V1` no ambiente. |
| `test_recifrar_e_idempotente`, `test_recifrar_sem_rotacao_ainda_acrescenta_o_aad`, `test_recifrar_respeita_o_limite_por_chamada` | Segunda chamada não faz nada; sem rotação ainda fecha o #55; `limite` vale. |
| `test_recifrar_nao_toca_no_que_nao_consegue_decifrar` | Linha ilegível fica idêntica e sai em `falhas` com o nome da chave; as outras avançam. |
| `test_diagnostico_conta_o_que_falta_recifrar` | `sem_aad`, `senhas_por_key_version`, `linhas_para_recifrar`, e senha em versão sem chave → `versoes_sem_chave`. |
| `test_revalidar_tambem_prova_a_senha` | `senha_ok` e o nome `CERT_PASSWORD_ENCRYPTION_KEY` no detalhe quando a chave da senha está errada. |
| `test_v_da_versao_em_vigor_no_ambiente_gera_aviso`, `test_sem_cofre_exige_aad_em_producao_gera_aviso` | Os dois avisos novos do boot. |
| `test_rota_de_recifrar_e_de_admin_e_devolve_contagens` | 403 para `user`/`gestor`; admin recebe as contagens. |
| `test_ajuda_do_revalidar_nao_promete_correcao` | A frase antiga saiu do template e do `main.py`; a tela tem o botão de recifrar. |
| `test_migration_acrescenta_as_duas_colunas` | A migration existe, cria as duas colunas e é idempotente. |
| `test_hash_nao_e_mais_sha256_puro_do_codigo`, `test_dois_pedidos_com_o_mesmo_codigo_geram_hashes_diferentes` | O "Como testar" do #56: formato `v2$`, sem o sha256 do código dentro; mesmo código, hashes diferentes. |
| `test_codigo_novo_confere_e_errado_nao`, `test_codigo_legado_em_sha256_puro_ainda_confere` | O fluxo continua; hash antigo aceito com aviso, código errado recusado. |

## Migração e ensaio (`scripts/migracao_lote8_cofre.py`)

Ensaio em **cópia** local (`CREATE DATABASE certguard_lote8 TEMPLATE certguard_imp`, 473 linhas reais do cofre, cifradas sob a chave antiga da Vercel — que se perdeu, então não decifram com o `.env` local; isso serviu para provar o caminho de falha), 25/09/2026:

| Passo | Resultado |
|---|---|
| `--dry-run` | 473 linhas, `key_version {1: 473}`, colunas ausentes; plano de acrescentar as duas; nada gravado. |
| `--ida` | ANTES 473 → DEPOIS 473 linhas, 473 com senha v1, 473 sem AAD (os três iguais, como a migration exige). Commit. |
| semente | 3 linhas no envelope antigo cifradas com as chaves do `.env` local (`machine_id = ENSAIO`), inseridas sem as colunas novas → DEFAULT 1/0. |
| `--recifrar` | 3 recifradas (PFX v1 / senha v1, `aad_version = 1`); **473 não decifram e ficaram idênticas** (`InvalidTag`, motivo nomeia `CERT_ENCRYPTION_KEY`); saída 2. Estado: 473 × (aad 0) + 3 × (aad 1). |
| `--volta` | As 3 linhas com AAD voltaram ao envelope antigo sob as chaves em vigor; colunas removidas; 476 linhas. Conferência com o caminho de leitura **antigo** (`decrypt_pfx_at_rest(..., key_version=1)` sem AAD): as 3 decifram PFX e senha. |
| limpeza | `DROP DATABASE certguard_lote8`. |

Ordem no servidor: rodar a migration (SQL) **antes** do deploy do código do lote 8 — o upsert novo grava as colunas; o código antigo ignora as colunas (DEFAULT), então a migration pode ir na frente sem janela. Depois do deploy: "Recifrar cofre" no Instalador (ou `--recifrar` no servidor, que tem o `.env`) até "para recifrar" zerar; "Revalidar cofre"; então `COFRE_EXIGE_AAD=1` e reiniciar.

## Janela de compatibilidade

| Mudança | Quem afeta | Janela |
|---|---|---|
| Colunas novas | Código novo sem a migration: o upsert do agente falha (coluna inexistente) — por isso a migration vai na frente. Código antigo com a migration: ignora as colunas. | Migration antes do deploy; volta pelo script. |
| Versão em vigor pelo ambiente | Sem `CERT_ENCRYPTION_KEY_VERSION`/`CERT_PASSWORD_ENCRYPTION_KEY_VERSION` no `.env`, tudo fica como hoje (versão 1). O cofre do ANALISESRV está inteiro em v1 desde a rotação de 22/09. | Padrão = comportamento atual. |
| Envelope antigo (sem AAD) | As ~470 linhas reais continuam decifrando com WARNING único por processo até serem recifradas. `COFRE_EXIGE_AAD` padrão desligada; aviso no boot em produção enquanto desligada. | Flag com padrão seguro para o que existe; ligar só depois de "sem dados associados" zerar. |
| Hash do código de redefinição | Códigos pendentes no formato antigo continuam válidos por até 15 min após o deploy, com WARNING. | Fecha sozinha. |
| Revalidar | O resultado ganha `senha_ok` e `aad_version`; a tela já os mostra. Um cofre com a chave da senha errada passa a aparecer como falha no Revalidar (antes só aparecia na instalação). | — |
| `CURRENT_KEY_VERSION` | Removida do módulo; só testes a referenciavam. | — |

## Pendente e por quê

- **Rodar a migration e recifrar em produção** são ações humanas no ANALISESRV (SQL pela ferramenta do usuário; `--recifrar` ou o botão). Só então ligar `COFRE_EXIGE_AAD`.
- **Chaves antigas no `.env`**: este lote não remove nada. Hoje não há `_V<n>` no servidor (a rotação de 22/09 zerou o cofre e recriou tudo em v1). Quando houver uma rotação de verdade, a remoção da `_V<n>` é o último passo, depois de `restantes = 0` e Revalidar ok.
- **Fase 0**: o achado #42 fala em "corrigir o texto de ajuda" — feito; a rotação em si (trocar `CERT_ENCRYPTION_KEY`) continua humana.
- **`recifrar_cofre` lê a tabela inteira** para escolher as candidatas (um SELECT de ~470 linhas com os ciphertexts). É o mesmo custo do Revalidar+diagnóstico e cabe no limite de 3 por 10 min; com dezenas de milhares de linhas valeria um filtro no banco. Anotado, não tratado.

## Achados novos

- O texto de erro do `InvalidTag` no Revalidar dizia só "CERT_ENCRYPTION_KEY não é a que cifrou o cofre"; com AAD há uma segunda causa (registro alterado — máquina, fingerprint ou versão). Os dois textos agora dizem "ou o registro foi alterado".
- `diagnostico_das_chaves` conferia as chaves só do PFX; a chave da senha não tinha diagnóstico nenhum — mesmo tendo sido a causa das seis falhas de instalação registradas em produção. Ganhou bloco próprio.
- A versão sem `aad` da API (`encrypt_pfx_at_rest(pfx)`) continua existindo e é o que o script de volta usa para produzir o envelope antigo; nada no código do portal a chama sem AAD. Se um dia o envelope antigo deixar de ser aceito de vez, ela pode ser removida junto.
