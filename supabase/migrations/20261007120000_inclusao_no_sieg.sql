-- ==========================================================================
-- Inclusao de certificado no SIEG (07/10/2026) — docs/modal-detalhes-e-sieg.md
--
-- COMO USAR: rode no psql do ANALISESRV ANTES do deploy do codigo. Salvar a
-- Configuracao grava a linha inteira de portal_settings; sem as colunas novas
-- o banco recusa e a tela responde 503. Idempotente: rodar duas vezes nao faz
-- mal.
--
--   & "C:\Program Files\PostgreSQL\17\bin\psql.exe" -U postgres -p 5433 -d certguard -v ON_ERROR_STOP=1 -f <este arquivo>
--
-- ── O que muda ───────────────────────────────────────────────────────────
--
-- 1. portal_settings ganha as credenciais do SIEG (Client ID; Secret Key e
--    API Key cifradas com a chave do SMTP, nunca em claro) e os padroes de
--    UF e de consultas enviados no cadastro (JSON).
-- 2. sieg_inclusao: um estado por CERTIFICADO (fingerprint) — incluindo,
--    no_sieg, erro, substituido (renovacao: o novo do mesmo CNPJ entrou) ou
--    removido (a reconciliacao do administrador nao achou no SIEG).
-- 3. sieg_trilha: cada tentativa e cada reconciliacao, com operacao, HTTP,
--    mensagem da API, opcoes de consulta desligadas e avisos. Sem segredo,
--    senha nem certificado.
-- 4. Limpeza da tentativa de junho (automacao Playwright, removida): as
--    tabelas sieg_* antigas e os comandos sieg_* pendentes na fila do agente.
--    O codigo atual nao le nenhuma delas.
-- ==========================================================================

-- Antes de apagar: quais tabelas sieg_* antigas existem, e com quantas linhas.
SELECT table_name AS sieg_antiga_existente
  FROM information_schema.tables
 WHERE table_schema = 'public'
   AND table_name IN ('sieg_logs', 'sieg_processamentos', 'sieg_mapping_sessions', 'sieg_selectors_history')
 ORDER BY table_name;

-- 1. Configuracao ---------------------------------------------------------
ALTER TABLE public.portal_settings
  ADD COLUMN IF NOT EXISTS sieg_client_id text NOT NULL DEFAULT '',
  ADD COLUMN IF NOT EXISTS sieg_secret_key_encrypted text NOT NULL DEFAULT '',
  ADD COLUMN IF NOT EXISTS sieg_api_key_encrypted text NOT NULL DEFAULT '',
  ADD COLUMN IF NOT EXISTS sieg_padroes text NOT NULL DEFAULT '';

COMMENT ON COLUMN public.portal_settings.sieg_secret_key_encrypted IS
  'Secret Key do SIEG (gera o JWT), cifrada com a chave do SMTP.';
COMMENT ON COLUMN public.portal_settings.sieg_api_key_encrypted IS
  'API Key da conta SIEG (cabecalho X-Api-Key), cifrada com a chave do SMTP.';
COMMENT ON COLUMN public.portal_settings.sieg_padroes IS
  'JSON com UfCertificado e as opcoes Consulta* enviadas no cadastro. Vazio = padroes do codigo.';

-- 2. Estado por certificado -------------------------------------------------
CREATE TABLE IF NOT EXISTS public.sieg_inclusao (
  fingerprint      text PRIMARY KEY,
  documento        text NOT NULL,
  nome             text NOT NULL DEFAULT '',
  estado           text NOT NULL
                   CHECK (estado IN ('incluindo', 'no_sieg', 'erro', 'substituido', 'removido')),
  sieg_id          text NOT NULL DEFAULT '',
  solicitado_por   text NOT NULL DEFAULT '',
  solicitado_em    timestamptz NOT NULL DEFAULT now(),
  atualizado_em    timestamptz NOT NULL DEFAULT now(),
  substituido_por  text NOT NULL DEFAULT '',
  mensagem         text NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS sieg_inclusao_documento_idx ON public.sieg_inclusao (documento);

-- 3. Trilha -----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.sieg_trilha (
  id                    bigserial PRIMARY KEY,
  fingerprint           text NOT NULL,
  documento             text NOT NULL DEFAULT '',
  nome                  text NOT NULL DEFAULT '',
  evento                text NOT NULL,
  operacao              text NOT NULL DEFAULT '',
  http_status           integer,
  mensagem              text NOT NULL DEFAULT '',
  opcoes_desabilitadas  text NOT NULL DEFAULT '',
  avisos                text NOT NULL DEFAULT '',
  sieg_id               text NOT NULL DEFAULT '',
  por                   text NOT NULL DEFAULT '',
  em                    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS sieg_trilha_fingerprint_idx ON public.sieg_trilha (fingerprint, em DESC);
CREATE INDEX IF NOT EXISTS sieg_trilha_em_idx ON public.sieg_trilha (em DESC);

-- 4. Limpeza da tentativa de junho -----------------------------------------
DROP TABLE IF EXISTS public.sieg_logs;
DROP TABLE IF EXISTS public.sieg_processamentos;
DROP TABLE IF EXISTS public.sieg_mapping_sessions;
DROP TABLE IF EXISTS public.sieg_selectors_history;

DELETE FROM public.agent_command_queue
 WHERE command LIKE 'sieg\_%' ESCAPE '\'
   AND status = 'pending';

-- Conferencia -----------------------------------------------------------------
SELECT column_name
  FROM information_schema.columns
 WHERE table_schema = 'public' AND table_name = 'portal_settings'
   AND column_name LIKE 'sieg\_%' ESCAPE '\'
 ORDER BY column_name;
SELECT table_name
  FROM information_schema.tables
 WHERE table_schema = 'public' AND table_name LIKE 'sieg%'
 ORDER BY table_name;
SELECT count(*) AS comandos_sieg_pendentes
  FROM public.agent_command_queue
 WHERE command LIKE 'sieg\_%' ESCAPE '\';
