-- ==========================================================================
-- colaborador_cert_selecoes: UNIQUE de verdade sobre user_id — FASE 3a
--
-- Aplicada em produção em 17/08/2026.
--
-- A fase 1 criou um índice único PARCIAL sobre `user_id`
-- (`WHERE user_id IS NOT NULL`), porque a coluna nascia anulável. Índice
-- parcial **não serve** para o `ON CONFLICT` do Postgres inferir alvo — e é
-- disso que o código da 3c precisa para trocar `on_conflict=user_email` por
-- `on_conflict=user_id`.
--
-- CONSTRAINT, e não `CREATE UNIQUE INDEX`: as duas criam o mesmo índice por
-- baixo, mas só a constraint aparece em `pg_constraint`, e é essa a forma que
-- o `ON CONFLICT (user_id)` reconhece sem ambiguidade.
--
-- Aditiva: o código em produção na época (fase 2) grava as duas colunas e usa
-- `on_conflict=user_email`, e seguiu funcionando igual.
-- ==========================================================================

ALTER TABLE public.colaborador_cert_selecoes
    ADD CONSTRAINT colaborador_cert_selecoes_user_id_key UNIQUE (user_id);

-- A constraint acima cobre tudo o que o índice parcial cobria. Manter os dois
-- seria duas fontes da mesma regra, e no dia em que divergissem ninguém saberia
-- qual manda.
DROP INDEX IF EXISTS public.colaborador_cert_selecoes_user_id_idx;
