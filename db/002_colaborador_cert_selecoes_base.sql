-- `colaborador_cert_selecoes` na forma ORIGINAL (chaveada por e-mail).
--
-- A tabela nasceu à mão no Supabase; `supabase/schema.sql` mostra a forma
-- FINAL (chave por `user_id`), mas as migrations de 17/08/2026 (fases 1, 3a,
-- 3b e 3d) contam a transição a partir da forma antiga: acrescentam
-- `user_id`, preenchem pelo e-mail, movem a chave e derrubam `user_email`.
-- Para a história rodar num Postgres vazio, ela precisa começar de onde
-- começou. Depois da fase 3d o resultado é idêntico ao `schema.sql`.
--
-- ⚠️ PROVISÓRIA (07/09/2026), como `001_users_base.sql`: o dump do banco real
-- é a verdade e substitui as duas quando chegar.

CREATE TABLE IF NOT EXISTS public.colaborador_cert_selecoes (
    user_email text PRIMARY KEY,
    documentos jsonb NOT NULL DEFAULT '[]'::jsonb,
    updated_at timestamptz NOT NULL DEFAULT now()
);
