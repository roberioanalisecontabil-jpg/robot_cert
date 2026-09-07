-- `users`: a tabela que nunca teve migration.
--
-- Ela foi criada à mão no SQL Editor do Supabase antes de o repositório
-- guardar migrations, e todo o resto a referencia (`colaborador_cert_selecoes`
-- já na 1ª migration; `carteira`, `departamento_lider`, `password_reset_codigo`
-- depois). Sem isto o esquema não sobe num Postgres vazio.
--
-- ⚠️ PROVISÓRIA (07/09/2026): reconstruída a partir do que o código lê e
-- grava (`main.py`: id, email, password_hash, full_name, role,
-- deve_trocar_senha) e do que as migrations acrescentam depois (ativo,
-- gestor_id, senha_alterada_em, departamento_id, e-mail único). Quando o dump
-- do banco real chegar, o `schema-all.sql` dele é a verdade e substitui este
-- arquivo — conferir tipos e defaults antes de importar os dados.

CREATE TABLE IF NOT EXISTS public.users (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    email             text NOT NULL,
    password_hash     text NOT NULL,
    full_name         text,
    role              text NOT NULL DEFAULT 'user',
    deve_trocar_senha boolean NOT NULL DEFAULT false,
    created_at        timestamptz NOT NULL DEFAULT now()
);
