-- SQL Migration: Add SMTP settings to portal_settings and create sent_alerts table
-- Aplicável via Supabase SQL Editor ou CLI.

-- 1. Adicionar colunas SMTP na tabela portal_settings se não existirem
ALTER TABLE public.portal_settings
  ADD COLUMN IF NOT EXISTS smtp_host text NOT NULL DEFAULT '',
  ADD COLUMN IF NOT EXISTS smtp_port integer NOT NULL DEFAULT 587,
  ADD COLUMN IF NOT EXISTS smtp_user text NOT NULL DEFAULT '',
  ADD COLUMN IF NOT EXISTS smtp_password_encrypted text NOT NULL DEFAULT '',
  ADD COLUMN IF NOT EXISTS smtp_use_tls boolean NOT NULL DEFAULT true,
  ADD COLUMN IF NOT EXISTS smtp_use_ssl boolean NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS smtp_from_email text NOT NULL DEFAULT '',
  ADD COLUMN IF NOT EXISTS smtp_alerts_enabled boolean NOT NULL DEFAULT false;

-- 2. Criar a tabela de controle de antispam sent_alerts
CREATE TABLE IF NOT EXISTS public.sent_alerts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  fingerprint_sha256 text NOT NULL,
  tipo_alerta text NOT NULL, -- 'expired' | 'expiring'
  destinatario text NOT NULL,
  data_validade timestamptz NOT NULL,
  sent_at timestamptz NOT NULL DEFAULT now()
);

-- 3. Criar índice único composto para prevenção robusta de duplicados
CREATE UNIQUE INDEX IF NOT EXISTS sent_alerts_unique_idx 
  ON public.sent_alerts (fingerprint_sha256, tipo_alerta, destinatario, data_validade);
