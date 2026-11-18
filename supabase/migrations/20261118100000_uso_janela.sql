-- Janela em primeiro plano no uso do certificado (18/11/2026).
-- NAO rode a mao: aplicada por db/aplicar_schema.py durante o deploy.
-- Idempotente: pode rodar de novo sem efeito.
--
-- uso_janela: ate 3 janelas por evento de uso (ordem 0 = a vigente), vindas do
--   anotador da estacao. (uso_id, record_id, ordem) torna o reenvio do lote
--   inofensivo; e por linha de uso, e nao por maquina, porque o record_id
--   recomeca quando o log de Seguranca e limpo. O UNIQUE ja serve de indice
--   por uso_id. evento_em e a hora do evento 5061 (quando e a da janela).
--   Apagar o uso apaga as janelas.

CREATE TABLE IF NOT EXISTS public.uso_janela (
  id         bigserial PRIMARY KEY,
  uso_id     bigint NOT NULL REFERENCES public.uso_certificado(id) ON DELETE CASCADE,
  machine_id text NOT NULL,
  record_id  bigint NOT NULL,
  ordem      smallint NOT NULL CHECK (ordem BETWEEN 0 AND 2),
  evento_em  timestamptz NOT NULL,
  quando     timestamptz NOT NULL,
  programa   text NOT NULL,
  titulo     text NOT NULL,
  UNIQUE (uso_id, record_id, ordem)
);
