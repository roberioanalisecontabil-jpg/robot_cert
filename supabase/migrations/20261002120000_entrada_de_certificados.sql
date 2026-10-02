-- ==========================================================================
-- Entrada de certificados e aviso de novos por hora cheia (02/10/2026)
--
-- COMO USAR: rode no psql do ANALISESRV DEPOIS do deploy do codigo. Pode
-- rodar antes ou depois de reiniciar o servico; o codigo trata coluna ausente
-- como "padrao" (portal_settings) e tabela ausente como "sem fila" (o aviso
-- de novos sai de imediato e a entrada aparece vazia no Instalador).
-- Idempotente: rodar duas vezes nao faz mal.
--
--   & "C:\Program Files\PostgreSQL\17\bin\psql.exe" -U postgres -p 5433 -d certguard -f <este arquivo>
--
-- ── O que muda ───────────────────────────────────────────────────────────
--
-- 1. portal_settings ganha as pastas da ENTRADA (onde os PFX chegam) e as
--    raizes do acervo (pessoa juridica / pessoa fisica, com subpastas A-Z e
--    "0 a 9"), mais a chave e o modo do aviso de certificado novo.
-- 2. entrada_eventos: o que o agente fez com cada arquivo que chegou
--    (renomeou e moveu, mandou para vencidos, descartou copia, marcou
--    duplicidade) e o que ficou pendente na pasta por nao abrir.
-- 3. novos_pendentes: a fila dos certificados novos que esperam a proxima
--    hora cheia para sair num e-mail so.
-- ==========================================================================

-- PASSO 1 — colunas em portal_settings
ALTER TABLE public.portal_settings
  ADD COLUMN IF NOT EXISTS pasta_entrada text NOT NULL DEFAULT '',
  ADD COLUMN IF NOT EXISTS pasta_pj text NOT NULL DEFAULT '',
  ADD COLUMN IF NOT EXISTS pasta_pf text NOT NULL DEFAULT '',
  ADD COLUMN IF NOT EXISTS alertas_novos_enabled boolean NOT NULL DEFAULT true,
  ADD COLUMN IF NOT EXISTS alertas_novos_modo text NOT NULL DEFAULT '';

-- PASSO 2 — eventos e pendentes da entrada
CREATE TABLE IF NOT EXISTS public.entrada_eventos (
  id uuid PRIMARY KEY,
  machine_id text NOT NULL DEFAULT 'default',
  quando timestamptz NOT NULL DEFAULT now(),
  -- movido | vencido | substituiu | copia_descartada | duplicidade | pendente
  resultado text NOT NULL,
  motivo text NOT NULL DEFAULT '',
  -- Nomes SEM a senha: o agente os limpa antes de enviar.
  arquivo_original text NOT NULL DEFAULT '',
  arquivo_novo text NOT NULL DEFAULT '',
  pasta_destino text NOT NULL DEFAULT '',
  nome text NOT NULL DEFAULT '',
  documento_numero text NOT NULL DEFAULT '',
  documento_tipo text NOT NULL DEFAULT '',
  fingerprint_sha256 text NOT NULL DEFAULT '',
  not_after timestamptz,
  -- So para resultado = 'pendente': quando o arquivo deixou de estar na pasta.
  resolvido_em timestamptz
);

CREATE INDEX IF NOT EXISTS entrada_eventos_quando_idx
  ON public.entrada_eventos (quando DESC);

CREATE INDEX IF NOT EXISTS entrada_eventos_pendentes_idx
  ON public.entrada_eventos (machine_id, arquivo_original)
  WHERE resultado = 'pendente' AND resolvido_em IS NULL;

-- PASSO 3 — fila dos certificados novos da hora
CREATE TABLE IF NOT EXISTS public.novos_pendentes (
  fingerprint_sha256 text PRIMARY KEY,
  item jsonb NOT NULL,
  registrado_em timestamptz NOT NULL DEFAULT now()
);

-- PASSO 4 — conferir (deve listar as 5 colunas e as 2 tabelas)
SELECT column_name
  FROM information_schema.columns
 WHERE table_name = 'portal_settings'
   AND column_name IN ('pasta_entrada', 'pasta_pj', 'pasta_pf', 'alertas_novos_enabled', 'alertas_novos_modo')
 ORDER BY column_name;

SELECT table_name
  FROM information_schema.tables
 WHERE table_schema = 'public'
   AND table_name IN ('entrada_eventos', 'novos_pendentes')
 ORDER BY table_name;
