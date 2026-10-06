-- ==========================================================================
-- Envio de e-mail pelo Microsoft 365 (Graph), ao lado do SMTP (03/10/2026)
--
-- COMO USAR: rode no psql do ANALISESRV ANTES do deploy do codigo (ou logo
-- depois, antes de alguem salvar a Configuracao). Ler tolera coluna ausente,
-- mas SALVAR a configuracao grava a linha inteira de portal_settings e, sem
-- as colunas, o banco recusa e a tela responde 503 "nao foi possivel gravar".
-- Idempotente: rodar duas vezes nao faz mal.
--
--   & "C:\Program Files\PostgreSQL\17\bin\psql.exe" -U postgres -p 5433 -d certguard -v ON_ERROR_STOP=1 -f <este arquivo>
--
-- ── O que muda ───────────────────────────────────────────────────────────
--
-- portal_settings ganha a forma de envio ('smtp' | 'graph') e os campos do
-- aplicativo do Entra: tenant, id do app, segredo (cifrado com a mesma chave
-- do SMTP), caixa de envio (remetente), "responder para" e a validade do
-- segredo, para o portal avisar 30 dias antes de ele vencer.
-- Vazio = o mesmo que antes desta migration: continua SMTP.
-- ==========================================================================

ALTER TABLE public.portal_settings
  ADD COLUMN IF NOT EXISTS email_transporte text NOT NULL DEFAULT 'smtp',
  ADD COLUMN IF NOT EXISTS graph_tenant_id text NOT NULL DEFAULT '',
  ADD COLUMN IF NOT EXISTS graph_client_id text NOT NULL DEFAULT '',
  ADD COLUMN IF NOT EXISTS graph_client_secret_encrypted text NOT NULL DEFAULT '',
  ADD COLUMN IF NOT EXISTS graph_remetente text NOT NULL DEFAULT '',
  ADD COLUMN IF NOT EXISTS graph_reply_to text NOT NULL DEFAULT '',
  ADD COLUMN IF NOT EXISTS graph_secret_validade text NOT NULL DEFAULT '';

COMMENT ON COLUMN public.portal_settings.email_transporte IS
  'Forma de envio dos e-mails: smtp (padrao) ou graph (Microsoft 365, por aplicativo).';
COMMENT ON COLUMN public.portal_settings.graph_client_secret_encrypted IS
  'Segredo do aplicativo do Entra, cifrado com a chave do SMTP (nunca em claro).';
COMMENT ON COLUMN public.portal_settings.graph_secret_validade IS
  'Validade do segredo (AAAA-MM-DD). O sino do administrador avisa 30 dias antes.';

-- Conferencia: as sete colunas existem e a forma de envio continua smtp.
SELECT column_name
  FROM information_schema.columns
 WHERE table_schema = 'public' AND table_name = 'portal_settings'
   AND column_name IN ('email_transporte', 'graph_tenant_id', 'graph_client_id',
                       'graph_client_secret_encrypted', 'graph_remetente',
                       'graph_reply_to', 'graph_secret_validade')
 ORDER BY column_name;
SELECT id, email_transporte FROM public.portal_settings;
