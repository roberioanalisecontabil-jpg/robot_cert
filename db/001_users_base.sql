-- `users`: a tabela que nunca teve migration.
--
-- Ela foi criada à mão no SQL Editor do Supabase antes de o repositório
-- guardar migrations, e todo o resto a referencia (`colaborador_cert_selecoes`
-- já na 1ª migration; `carteira`, `departamento_lider`, `password_reset_codigo`
-- depois). Sem isto o esquema não sobe num Postgres vazio.
--
-- Conferida (09/09/2026) contra o dump do banco de produção: colunas, tipos,
-- defaults e o e-mail único (`users_email_key`) são os reais. As colunas que
-- as migrations acrescentam depois (ativo, gestor_id, senha_alterada_em,
-- departamento_id e o índice único por lower(email)) continuam nelas.

CREATE TABLE IF NOT EXISTS public.users (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    email             text NOT NULL UNIQUE,
    password_hash     text NOT NULL,
    full_name         text,
    role              text NOT NULL DEFAULT 'user',
    deve_trocar_senha boolean NOT NULL DEFAULT false,
    created_at        timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS users_email_idx ON public.users (email);
