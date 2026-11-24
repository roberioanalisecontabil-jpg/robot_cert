-- Chave de API de leitura para administrador (24/11/2026).
-- NAO rode a mao: aplicada por db/aplicar_schema.py durante o deploy.
-- Idempotente: pode rodar de novo sem efeito.
--
-- api_chaves: a chave vale como o administrador dono dela, so para GET e sem
--   as rotas da maquina (cofre, fila do agente). O texto claro aparece uma vez,
--   na criacao; aqui fica so o sha256. Dono desativado ou rebaixado mata a
--   chave na hora, porque o papel e relido a cada chamada.

CREATE TABLE IF NOT EXISTS public.api_chaves (
  id            bigserial PRIMARY KEY,
  nome          text NOT NULL,
  user_id       uuid NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  segredo_hash  text NOT NULL UNIQUE,
  criada_em     timestamptz NOT NULL DEFAULT now(),
  expira_em     timestamptz NULL,
  ultimo_uso_em timestamptz NULL,
  ultimo_ip     text NULL,
  revogada_em   timestamptz NULL
);
