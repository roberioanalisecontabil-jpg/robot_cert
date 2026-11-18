-- Janela em primeiro plano no uso do certificado (18/11/2026).
-- NAO rode a mao: aplicada por db/aplicar_schema.py durante o deploy.
-- Idempotente: pode rodar de novo sem efeito.
--
-- uso_janela: ate 3 janelas por evento de uso (ordem 0 = a vigente), vindas do
--   anotador da estacao. (machine_id, record_id, ordem) identifica o evento 5061
--   e torna o reenvio do lote inofensivo. Apagar o uso apaga as janelas.

CREATE TABLE IF NOT EXISTS public.uso_janela (
  id         bigserial PRIMARY KEY,
  uso_id     bigint NOT NULL REFERENCES public.uso_certificado(id) ON DELETE CASCADE,
  machine_id text NOT NULL,
  record_id  bigint NOT NULL,
  ordem      smallint NOT NULL CHECK (ordem BETWEEN 0 AND 2),
  quando     timestamptz NOT NULL,
  programa   text NOT NULL,
  titulo     text NOT NULL,
  UNIQUE (machine_id, record_id, ordem)
);

CREATE INDEX IF NOT EXISTS uso_janela_uso_idx
  ON public.uso_janela (uso_id, record_id);
