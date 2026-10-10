-- ==========================================================================
-- Login em dois passos (10/10/2026): senha + codigo por e-mail ou app
--
-- COMO USAR: NAO rode a mao. O atualizacao_push.ps1 aplica as migrations com
-- o usuario certo. Idempotente; so acrescenta colunas a tabelas que ja
-- existem (as permissoes delas continuam valendo).
--
-- ── Por que ──────────────────────────────────────────────────────────────
--
-- Pre-requisito para abrir o portal na internet: so a senha nao abre mais o
-- portal. Sem o navegador lembrado (7 dias), o login pede um codigo de 6
-- digitos enviado por e-mail (15 minutos, 3 erros e queima) ou o do app
-- autenticador (TOTP), que e a saida de emergencia se o e-mail cair.
-- ==========================================================================

-- 1. O codigo de login usa a mesma tabela da recuperacao de senha, com
--    proposito proprio: um codigo de login nunca redefine senha -------------
ALTER TABLE public.password_reset_codigo
  ADD COLUMN IF NOT EXISTS proposito text NOT NULL DEFAULT 'senha';

CREATE INDEX IF NOT EXISTS password_reset_codigo_user_proposito_idx
  ON public.password_reset_codigo (user_id, proposito, created_at DESC);

COMMENT ON COLUMN public.password_reset_codigo.proposito IS
  '''senha'' (recuperacao) ou ''login'' (segundo passo do login, 10/10/2026).';

-- 2. App autenticador da conta ---------------------------------------------
--    totp_cifrado: o segredo, cifrado com a mesma chave da senha do SMTP.
--    totp_ativado_em: nulo enquanto a pessoa nao confirmou um codigo do app.
--    totp_ultimo_passo: o ultimo passo de 30 s aceito; o mesmo codigo nao
--    entra duas vezes.
ALTER TABLE public.users ADD COLUMN IF NOT EXISTS totp_cifrado text;
ALTER TABLE public.users ADD COLUMN IF NOT EXISTS totp_ativado_em timestamptz;
ALTER TABLE public.users ADD COLUMN IF NOT EXISTS totp_ultimo_passo bigint;

-- Conferencia -------------------------------------------------------------------
SELECT table_name, column_name FROM information_schema.columns
 WHERE table_schema = 'public'
   AND ((table_name = 'password_reset_codigo' AND column_name = 'proposito')
     OR (table_name = 'users' AND column_name IN ('totp_cifrado', 'totp_ativado_em', 'totp_ultimo_passo')))
 ORDER BY table_name, column_name;
