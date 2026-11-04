-- ==========================================================================
-- Entrar com a Microsoft no site (spec 04/11/2026)
--
-- COMO USAR: NAO rode a mao. O atualizacao_push.ps1 aplica as migrations com
-- o usuario certo. Idempotente.
--
-- ADITIVA: colunas novas com valor padrao ou nulas. O codigo de hoje nao
-- conhece nenhuma, entao aplicar antes do codigo novo nao muda nada. A unica
-- troca e a restricao users_origem_valida, que so ganha o valor 'microsoft'.
--
-- O que entra:
--
-- 1. users.microsoft_oid: identidade da pessoa no Entra ID (claim oid). Unico
--    quando preenchido.
-- 2. users.microsoft_refresh_cifrado: refresh token cifrado, para a conferencia
--    periodica da conta.
-- 3. users.microsoft_conferido_em / microsoft_sem_conferencia: ultima
--    conferencia bem-sucedida e marca de que ela nao foi possivel.
-- 4. users.desativada_pela_microsoft_em: quando a conferencia desativou a conta.
-- 5. users_origem_valida passa a aceitar 'microsoft'.
-- ==========================================================================

-- 1 a 4. Colunas ---------------------------------------------------------------
ALTER TABLE public.users ADD COLUMN IF NOT EXISTS microsoft_oid text;
ALTER TABLE public.users ADD COLUMN IF NOT EXISTS microsoft_refresh_cifrado text;
ALTER TABLE public.users ADD COLUMN IF NOT EXISTS microsoft_conferido_em timestamptz;
ALTER TABLE public.users ADD COLUMN IF NOT EXISTS microsoft_sem_conferencia boolean NOT NULL DEFAULT false;
ALTER TABLE public.users ADD COLUMN IF NOT EXISTS desativada_pela_microsoft_em timestamptz;

CREATE UNIQUE INDEX IF NOT EXISTS users_microsoft_oid_unico
  ON public.users (microsoft_oid) WHERE microsoft_oid IS NOT NULL;

COMMENT ON COLUMN public.users.microsoft_oid IS
  'Login Microsoft: oid da pessoa no Entra ID, gravado no primeiro login ou ligado pelo e-mail.';

-- 5. Origem 'microsoft' -----------------------------------------------------------
ALTER TABLE public.users DROP CONSTRAINT IF EXISTS users_origem_valida;
ALTER TABLE public.users
  ADD CONSTRAINT users_origem_valida CHECK (origem IN ('manual', 'acessorias', 'microsoft'));

-- Conferencia -------------------------------------------------------------------
-- Esperado: 5 colunas em users; o indice unico; a restricao com 'microsoft'.
SELECT column_name FROM information_schema.columns
 WHERE table_schema = 'public' AND table_name = 'users'
   AND column_name IN ('microsoft_oid', 'microsoft_refresh_cifrado', 'microsoft_conferido_em',
                       'microsoft_sem_conferencia', 'desativada_pela_microsoft_em')
 ORDER BY 1;
SELECT indexname FROM pg_indexes WHERE indexname = 'users_microsoft_oid_unico';
SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = 'users_origem_valida';
