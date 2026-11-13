-- Prazo da liberacao manual na carteira (aba Certificados, 13/11/2026).
-- NAO rode a mao: aplicada por db/aplicar_schema.py durante o deploy.
-- Idempotente: pode rodar de novo sem efeito.
--
-- valido_desde: quando a linha passou a valer (linhas antigas ficam com a data da migration).
-- valido_ate:   fim da liberacao; NULL = sem prazo. Teto de 700 dias.

ALTER TABLE public.carteira ADD COLUMN IF NOT EXISTS valido_desde date NOT NULL DEFAULT current_date;
ALTER TABLE public.carteira ADD COLUMN IF NOT EXISTS valido_ate date;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
     WHERE conrelid = 'public.carteira'::regclass AND conname = 'carteira_prazo_valido'
  ) THEN
    ALTER TABLE public.carteira ADD CONSTRAINT carteira_prazo_valido
      CHECK (valido_ate IS NULL OR (valido_ate >= valido_desde AND valido_ate - valido_desde <= 700));
  END IF;
END $$;

-- Historico: origem 'prazo'. A restricao antiga e achada pela definicao, nao
-- pelo nome (mesmo padrao de 20261020100000).
DO $$
DECLARE
  r record;
BEGIN
  FOR r IN SELECT conname FROM pg_constraint
            WHERE conrelid = 'public.carteira_historico'::regclass AND contype = 'c'
              AND conname <> 'carteira_historico_origem_valida'
              AND pg_get_constraintdef(oid) LIKE '%origem%'
  LOOP
    EXECUTE format('ALTER TABLE public.carteira_historico DROP CONSTRAINT %I', r.conname);
  END LOOP;
  -- Nomeada ja existente (de 20261020100000) e sem 'prazo': troca.
  IF EXISTS (
    SELECT 1 FROM pg_constraint
     WHERE conrelid = 'public.carteira_historico'::regclass
       AND conname = 'carteira_historico_origem_valida'
       AND pg_get_constraintdef(oid) NOT LIKE '%''prazo''%'
  ) THEN
    ALTER TABLE public.carteira_historico DROP CONSTRAINT carteira_historico_origem_valida;
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
     WHERE conrelid = 'public.carteira_historico'::regclass AND conname = 'carteira_historico_origem_valida'
  ) THEN
    ALTER TABLE public.carteira_historico ADD CONSTRAINT carteira_historico_origem_valida
      CHECK (origem IN ('manual', 'planilha', 'acessorias', 'papel', 'desativacao', 'bloqueio', 'prazo'));
  END IF;
END $$;
