-- Regra "Saiu da pasta" da remocao nas estacoes (22/11/2026).
-- NAO rode a mao: aplicada por db/aplicar_schema.py durante o deploy.
-- Idempotente: pode rodar de novo sem efeito.
--
-- O expurgo do cofre apagava o certificado vencido ou removido da pasta e,
-- com ele, a unica prova de que aquele certificado era do escritorio: as
-- copias instaladas ficavam nas estacoes para sempre. cert_acervo_saida guarda
-- so a impressao digital, o documento e o titular (nunca chave nem senha).

CREATE TABLE IF NOT EXISTS public.cert_acervo_saida (
  fingerprint  char(64) PRIMARY KEY,
  documento    text,
  nome_titular text,
  motivo       text NOT NULL DEFAULT '',
  saiu_em      timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE public.remocao_estacao DROP CONSTRAINT IF EXISTS remocao_estacao_regra_check;
ALTER TABLE public.remocao_estacao ADD CONSTRAINT remocao_estacao_regra_check
  CHECK (regra IN ('carteira', 'desativada', 'vinculo', 'emprestimo', 'sem_login', 'fora_da_pasta'));

-- Vazio = "relatorio" (ver app/remocao.py).
ALTER TABLE public.portal_settings
  ADD COLUMN IF NOT EXISTS remocao_fora_da_pasta_modo text NOT NULL DEFAULT '';
