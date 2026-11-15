-- Registro de uso dos certificados (Frente C, 15/11/2026).
-- NAO rode a mao: aplicada por db/aplicar_schema.py durante o deploy.
-- Idempotente: pode rodar de novo sem efeito.
--
-- uso_conteiner: de-para (maquina, SID, conteiner de chave) para o certificado,
--   mantido pela bandeja a partir do que a estacao tem instalado.
-- uso_certificado: uma linha por (maquina, SID, conteiner, hora de Brasilia);
--   hora e o inicio da hora; quantidade soma os usos naquela hora.
-- uso_coleta: ultima coleta por maquina e se a auditoria do Windows estava ligada.

CREATE TABLE IF NOT EXISTS public.uso_conteiner (
  machine_id      text NOT NULL,
  sid             text NOT NULL,
  conteiner       text NOT NULL,
  fingerprint     char(64) NOT NULL,
  usuario_windows text NOT NULL,
  user_id         uuid NULL REFERENCES public.users(id) ON DELETE SET NULL,
  atualizado_em   timestamptz NOT NULL DEFAULT now(),
  UNIQUE (machine_id, sid, conteiner)
);

CREATE TABLE IF NOT EXISTS public.uso_certificado (
  id              bigserial PRIMARY KEY,
  machine_id      text NOT NULL,
  sid             text NOT NULL,
  usuario_windows text NOT NULL,
  conteiner       text NOT NULL,
  hora            timestamptz NOT NULL,
  primeiro_em     timestamptz NOT NULL,
  ultimo_em       timestamptz NOT NULL,
  quantidade      int NOT NULL,
  ultimo_record   bigint NOT NULL,
  fingerprint     char(64) NULL,
  documento       text NULL,
  user_id         uuid NULL REFERENCES public.users(id) ON DELETE SET NULL,
  recebido_em     timestamptz NOT NULL DEFAULT now(),
  UNIQUE (machine_id, sid, conteiner, hora)
);

CREATE INDEX IF NOT EXISTS uso_certificado_hora_idx
  ON public.uso_certificado (hora DESC);

CREATE INDEX IF NOT EXISTS uso_certificado_user_idx
  ON public.uso_certificado (user_id, hora DESC);

CREATE INDEX IF NOT EXISTS uso_certificado_documento_idx
  ON public.uso_certificado (documento, hora DESC);

CREATE TABLE IF NOT EXISTS public.uso_coleta (
  machine_id text PRIMARY KEY,
  ultima_em  timestamptz NOT NULL,
  auditoria  text NOT NULL CHECK (auditoria IN ('ligada', 'desligada', 'desconhecida'))
);
