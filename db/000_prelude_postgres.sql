-- Prelúdio para PostgreSQL puro (desde 05/09/2026).
--
-- As 34 migrations em `supabase/migrations/` foram escritas para o Supabase e
-- usam duas coisas que um PostgreSQL comum não tem:
--
--   1. `auth.role()` nas políticas de RLS ("service_role_acesso_total_*").
--      Aqui o portal conecta com o usuário dono das tabelas, e RLS não se
--      aplica ao dono (sem FORCE ROW LEVEL SECURITY). As políticas ficam
--      inertes — só precisam COMPILAR. Este esquema `auth` mínimo garante isso
--      sem editar as migrations, que continuam sendo a história real do banco.
--   2. Nada mais: `gen_random_uuid()` é nativo desde o Postgres 13.
--
-- `db/aplicar_schema.py` roda este arquivo antes das migrations, uma vez.

CREATE SCHEMA IF NOT EXISTS auth;

-- Os papéis que as políticas e GRANTs das migrations citam. NOLOGIN: existem
-- só para o SQL antigo compilar; ninguém conecta com eles.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
        CREATE ROLE anon NOLOGIN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
        CREATE ROLE authenticated NOLOGIN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        CREATE ROLE service_role NOLOGIN;
    END IF;
END $$;

-- Sem JWT não há papel: devolve 'service_role' porque é o único chamador que
-- existe (o próprio portal). Não é uma barreira de segurança — a barreira é a
-- rede (só VPN) e o usuário do banco com senha própria.
CREATE OR REPLACE FUNCTION auth.role() RETURNS text
LANGUAGE sql STABLE AS $$ SELECT 'service_role'::text $$;

CREATE OR REPLACE FUNCTION auth.uid() RETURNS uuid
LANGUAGE sql STABLE AS $$ SELECT NULL::uuid $$;

CREATE OR REPLACE FUNCTION auth.jwt() RETURNS jsonb
LANGUAGE sql STABLE AS $$ SELECT '{}'::jsonb $$;

-- Registro do que já foi aplicado, para `aplicar_schema.py` ser reexecutável.
CREATE TABLE IF NOT EXISTS public.schema_migrations (
    arquivo     text PRIMARY KEY,
    aplicado_em timestamptz NOT NULL DEFAULT now()
);
