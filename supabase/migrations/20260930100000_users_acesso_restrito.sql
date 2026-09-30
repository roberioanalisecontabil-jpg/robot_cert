-- Migration: alcance de leitura do GESTOR (decisao de produto de 30/09/2026)
--
-- O lote 4 da auditoria recortou a leitura do gestor a carteira propria +
-- carteiras do setor que lidera. Em uso, o padrao passou a ser o oposto:
--   * administrador: tudo;
--   * gestor: tudo POR PADRAO; so um administrador o limita, ligando esta
--     coluna -- limitado, volta ao alcance do lote 4;
--   * operador: so o que gestor ou administrador liberar (a carteira).
--
-- DEFAULT false = o padrao pedido; nenhum gestor fica limitado pela migration.
-- O codigo tolera a coluna ausente (trata como false, com aviso no log), entao
-- a ordem entre migration e deploy nao importa -- mas sem ela o administrador
-- nao consegue limitar ninguem (o UPDATE falharia).
--
-- Volta: ALTER TABLE public.users DROP COLUMN IF EXISTS acesso_restrito;
-- Idempotente.

ALTER TABLE public.users
    ADD COLUMN IF NOT EXISTS acesso_restrito BOOLEAN NOT NULL DEFAULT false;

COMMENT ON COLUMN public.users.acesso_restrito IS
    'So para gestor. false (padrao) = ve todos os certificados; true = so a carteira propria e as do setor que lidera. Somente administrador altera.';

-- Conferencia esperada: uma linha -- acesso_restrito | boolean | NO | false
-- SELECT column_name, data_type, is_nullable, column_default
--   FROM information_schema.columns
--  WHERE table_name = 'users' AND column_name = 'acesso_restrito';
