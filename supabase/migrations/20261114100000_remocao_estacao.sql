-- Remocao de certificados nas estacoes (Frente B, 14/11/2026).
-- Spec: docs/superpowers/specs/2026-11-13-carteira-certificados-remocao-uso-design.md, secao "Frente B".
-- NAO rode a mao: aplicada por db/aplicar_schema.py durante o deploy.
-- Idempotente: pode rodar de novo sem efeito.
--
-- Uma linha por (maquina, usuario Windows, certificado): o que o robo removeria
-- ou ja removeu naquela estacao, e em que estado esta a remocao.
-- regra:  motivo da remocao (carteira, desativada, vinculo, emprestimo, sem_login).
-- estado: removeria (so registrado), aviso (contagem do prazo), remover (na fila),
--         removido, falhou.

CREATE TABLE IF NOT EXISTS public.remocao_estacao (
  id              bigserial PRIMARY KEY,
  machine_id      text NOT NULL,
  usuario_windows text NOT NULL,
  user_id         uuid NULL REFERENCES public.users(id) ON DELETE SET NULL,
  fingerprint     char(64) NOT NULL,
  documento       text,
  regra           text NOT NULL CHECK (regra IN ('carteira', 'desativada', 'vinculo', 'emprestimo', 'sem_login')),
  motivo          text NOT NULL DEFAULT '',
  estado          text NOT NULL CHECK (estado IN ('removeria', 'aviso', 'remover', 'removido', 'falhou')),
  aviso_desde     timestamptz,
  detalhe         text NOT NULL DEFAULT '',
  atualizado_em   timestamptz NOT NULL DEFAULT now(),
  UNIQUE (machine_id, usuario_windows, fingerprint)
);

CREATE INDEX IF NOT EXISTS remocao_estacao_estado_idx
  ON public.remocao_estacao (estado, atualizado_em DESC);

CREATE INDEX IF NOT EXISTS remocao_estacao_user_idx
  ON public.remocao_estacao (user_id);
