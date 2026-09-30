-- Migration: descarta users.acesso_restrito (30/09/2026, segunda versao da
-- regra do gestor)
--
-- A coluna nasceu de manha (20260930100000) para limitar o alcance do gestor
-- por flag. A tarde a regra mudou: o gestor recebe todos os clientes NA
-- CARTEIRA ao ser promovido (origem "regra:gestor") e o administrador tira
-- o que quiser; a leitura e a instalacao passam pela carteira, como para
-- todo mundo. O codigo deixou de ler a coluna; ela pode sair.
--
-- Opcional e idempotente. Rode DEPOIS do deploy do codigo (o codigo antigo
-- ainda a lia; o novo nao).
--
-- Volta: ALTER TABLE public.users ADD COLUMN IF NOT EXISTS acesso_restrito BOOLEAN NOT NULL DEFAULT false;

ALTER TABLE public.users DROP COLUMN IF EXISTS acesso_restrito;
