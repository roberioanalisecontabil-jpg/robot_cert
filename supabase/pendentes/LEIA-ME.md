# SQL pendente de aplicação

Migrations **escritas mas ainda não rodadas em produção**. Assim que uma for
aplicada e verificada, ela sai daqui e entra em `../migrations/` com o
timestamp de quando foi aplicada.

Esta pasta existe porque, em 17/08/2026, os arquivos `.sql` que estavam sendo
entregues pela Área de Trabalho **desapareceram** — a pasta seguia com todos os
outros arquivos, só os `.sql` sumiram, e não ficou claro o que os removeu.
Entrega por Área de Trabalho continua sendo o caminho prático (é de lá que se
copia para o SQL Editor), mas a cópia boa mora aqui, versionada.

## O que está pendente

| Arquivo | O que faz | Ordem |
|---|---|---|
| `recuperacao_de_senha.sql` | cria `password_reset_codigo` e `users.senha_alterada_em` | **antes** do deploy de `3b165a8` |

### `recuperacao_de_senha.sql` — atenção à ordem

O commit `3b165a8` faz `_conta_da_sessao` pedir `senha_alterada_em` no
`select`. Se o código subir antes de a coluna existir, o PostgREST recusa a
consulta e **toda requisição autenticada vira 503** — o portal inteiro para.

O contrário é seguro: rodar a migration antes do deploy não quebra nada,
porque o código que está em produção hoje não conhece nem a tabela nem a
coluna.

Por isso o push de `3b165a8` fica segurado até o passo 5 da migration voltar
conferido.
