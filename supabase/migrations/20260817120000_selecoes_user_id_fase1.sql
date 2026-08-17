-- ==========================================================================
-- colaborador_cert_selecoes ganha user_id — FASE 1 de 4 (aditiva)
--
-- Aplicada em produção em 17/08/2026.
--
-- A tabela tem `user_email` como chave primária. E-mail é atributo mutável,
-- não identidade. Quando o endereço muda, a linha se desprende da pessoa SEM
-- ERRO NENHUM: o UPDATE em `users` funciona, a linha continua lá, e as duas
-- deixam de se referir à mesma pessoa. O efeito é duplo e mudo — a seleção
-- some da tela de Acompanhamento, e `_get_todos_colaboradores_selecoes`
-- descarta a órfã por não achar o endereço em `users`, então o alerta de
-- vencimento para de chegar. Ninguém abre chamado por parar de receber e-mail;
-- o sintoma real é um certificado vencendo sem aviso.
--
-- Em 16/08 isso foi remendado em `main._mover_selecoes_de_email`, que carrega
-- a linha quando `update_user` troca o e-mail. Mas aquilo conserta o CHAMADOR:
-- um UPDATE direto no SQL Editor, uma rota nova ou uma importação voltam a
-- criar a órfã. Esta migration move a garantia de "lembrar de chamar o helper"
-- para "não há como acontecer".
--
-- ── As quatro fases, e por que a ordem é o ponto inteiro ──────────────────
--
--   1. (esta) coluna anulável + FK + backfill + índice único parcial
--   2. código passa a ler por `user_id` e gravar nas DUAS colunas
--   3. DROP COLUMN user_email; `user_id` vira a chave primária
--   4. código para de gravar `user_email`; `_mover_selecoes_de_email` vira
--      código morto e é apagado — poder apagá-lo é a prova de que funcionou
--
-- O código em produção LÊ `user_email`. Derrubar a coluna antes da fase 2
-- faria a leitura levantar exceção, o `except` cairia no fallback de arquivo
-- — que na Vercel é efêmero e chega vazio — e uma rodada de alertas sairia
-- sem destinatário nenhum, em silêncio. Aditivo primeiro elimina essa janela.
-- ==========================================================================


-- ANULÁVEL de propósito. O código em produção grava via upsert sem mencionar
-- `user_id`; com NOT NULL, toda gravação nova de seleção falharia entre esta
-- fase e o deploy da fase 2. Vira NOT NULL / chave primária na fase 3.
--
-- ON DELETE CASCADE é metade do ganho: hoje quem apaga a linha é
-- `main.delete_my_data`, na mão, e um DELETE na conta por qualquer outro
-- caminho deixa órfã. Com a FK, o banco cuida.
ALTER TABLE public.colaborador_cert_selecoes
    ADD COLUMN user_id uuid REFERENCES public.users(id) ON DELETE CASCADE;


-- Normaliza os dois lados. A coluna `users.email` já está toda em minúsculas
-- desde `20260816180000_users_email_unico`, mas normalizar aqui cobre
-- `user_email` gravado com caixa diferente por versão antiga do portal.
--
-- Idempotente: pode ser rodado de novo enquanto as fases 2 e 3 não vierem —
-- linha criada pelo código antigo no meio-tempo nasce com `user_id` nulo.
--
-- Linha sem conta correspondente fica nula, e é o certo: ela já é ignorada
-- pelo job de alertas hoje, e a fase 3 poderá removê-la explicitamente em vez
-- de ela seguir invisível.
UPDATE public.colaborador_cert_selecoes s
   SET user_id = u.id
  FROM public.users u
 WHERE lower(btrim(u.email)) = lower(btrim(s.user_email))
   AND s.user_id IS DISTINCT FROM u.id;


-- PARCIAL porque a coluna ainda admite nulo nesta fase. Um índice único comum
-- já trataria cada NULL como distinto, mas o predicado explícito diz a
-- intenção a quem ler isto depois, em vez de depender de lembrar dessa regra
-- do Postgres.
CREATE UNIQUE INDEX IF NOT EXISTS colaborador_cert_selecoes_user_id_idx
    ON public.colaborador_cert_selecoes (user_id)
 WHERE user_id IS NOT NULL;

COMMENT ON COLUMN public.colaborador_cert_selecoes.user_id IS
    'Identidade real do dono da seleção. user_email continua aqui só até a fase 3: e-mail é atributo mutável, e chavear por ele desprendia a linha da pessoa em silêncio quando o endereço mudava — a seleção sumia da tela e o alerta de vencimento parava de chegar.';
