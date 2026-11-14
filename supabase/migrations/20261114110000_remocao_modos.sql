-- Chaves de modo da remocao nas estacoes (Frente B, 14/11/2026).
-- NAO rode a mao: aplicada por db/aplicar_schema.py durante o deploy.
-- Idempotente. Vazio = "relatorio" (ver app/remocao.py).

ALTER TABLE public.portal_settings
  ADD COLUMN IF NOT EXISTS remocao_carteira_modo text NOT NULL DEFAULT '',
  ADD COLUMN IF NOT EXISTS remocao_sem_login_modo text NOT NULL DEFAULT '';
