-- Assinatura sem certificado identificado (24/11/2026).
-- NAO rode a mao: aplicada por db/aplicar_schema.py durante o deploy.
-- Idempotente: pode rodar de novo sem efeito.
--
-- uso_listagem: uma linha por rajada de aberturas de chave (3+ certificados da
--   mesma pessoa, ate 2 s entre uma e a seguinte). E o programa montando a
--   lista de escolha (o SPED, em Java, abre todas e assina sem abrir de novo):
--   sabe-se quem assinou, quando e onde, mas nao com qual certificado.
--   (machine_id, sid, primeiro_record) torna o reenvio do lote inofensivo.
--   programa e titulo: a janela em primeiro plano no primeiro evento.

CREATE TABLE IF NOT EXISTS public.uso_listagem (
  id              bigserial PRIMARY KEY,
  machine_id      text NOT NULL,
  sid             text NOT NULL,
  usuario_windows text NOT NULL,
  user_id         uuid NULL REFERENCES public.users(id) ON DELETE SET NULL,
  primeiro_em     timestamptz NOT NULL,
  ultimo_em       timestamptz NOT NULL,
  certificados    int NOT NULL,
  primeiro_record bigint NOT NULL,
  programa        text NOT NULL DEFAULT '',
  titulo          text NOT NULL DEFAULT '',
  recebido_em     timestamptz NOT NULL DEFAULT now(),
  UNIQUE (machine_id, sid, primeiro_record)
);

CREATE INDEX IF NOT EXISTS uso_listagem_quando_idx
  ON public.uso_listagem (primeiro_em DESC);
