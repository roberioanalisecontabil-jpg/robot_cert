-- ==========================================================================
-- Vinculo pessoa-computador e fila de instalacao (ADR 0002, 07/10/2026)
--
-- COMO USAR: NAO rode a mao. O atualizacao_push.ps1 aplica as migrations com
-- o usuario certo. Se precisar rodar a mao, o bloco final (passo 4) acerta
-- dono e permissoes. Idempotente.
--
-- ── O que muda ───────────────────────────────────────────────────────────
--
-- A bandeja da estacao passa a entrar com a conta DESTE portal (o dispositivo
-- em agent_devices, que existe desde 22/08 e estava parado). Em cima dele:
--
-- 1. computador_vinculo: quem pode instalar em qual maquina. Principal (a
--    maquina de trabalho, uma por pessoa) ou emprestimo (com prazo). Todo
--    vinculo novo nasce pendente ate o administrador autorizar.
-- 2. fila_instalacao: o token de uso unico de cada instalacao, cifrado, ate a
--    bandeja daquela maquina buscar. Substitui a fila do Hardlyze no caminho
--    da chave privada; na transicao as duas convivem.
-- ==========================================================================

-- 1. Vinculos ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.computador_vinculo (
  id            bigserial PRIMARY KEY,
  user_id       uuid NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  machine_id    text NOT NULL,
  nome          text NOT NULL DEFAULT '',
  tipo          text NOT NULL CHECK (tipo IN ('principal', 'emprestimo')),
  estado        text NOT NULL CHECK (estado IN ('pendente', 'ativo', 'encerrado', 'recusado')),
  expira_em     timestamptz,
  pedido_em     timestamptz NOT NULL DEFAULT now(),
  decidido_por  text NOT NULL DEFAULT '',
  decidido_em   timestamptz,
  encerrado_em  timestamptz,
  motivo        text NOT NULL DEFAULT ''
);

-- Uma principal ativa por pessoa e uma por maquina; um pedido pendente por par.
CREATE UNIQUE INDEX IF NOT EXISTS computador_vinculo_principal_da_pessoa
  ON public.computador_vinculo (user_id) WHERE tipo = 'principal' AND estado = 'ativo';
CREATE UNIQUE INDEX IF NOT EXISTS computador_vinculo_principal_da_maquina
  ON public.computador_vinculo (machine_id) WHERE tipo = 'principal' AND estado = 'ativo';
CREATE UNIQUE INDEX IF NOT EXISTS computador_vinculo_pendente_do_par
  ON public.computador_vinculo (user_id, machine_id) WHERE estado = 'pendente';
CREATE INDEX IF NOT EXISTS computador_vinculo_maquina_idx ON public.computador_vinculo (machine_id);

COMMENT ON TABLE public.computador_vinculo IS
  'ADR 0002: quem pode instalar certificado em qual maquina. Principal = maquina de trabalho '
  '(o Hardlyze mostra como responsavel); emprestimo = com prazo. Linhas encerradas sao o historico.';

-- 2. Fila de instalacao ---------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.fila_instalacao (
  id             bigserial PRIMARY KEY,
  machine_id     text NOT NULL,
  token_id       text NOT NULL,
  token_cifrado  text NOT NULL,
  criado_em      timestamptz NOT NULL DEFAULT now(),
  expira_em      timestamptz NOT NULL,
  entregue_em    timestamptz
);
CREATE INDEX IF NOT EXISTS fila_instalacao_maquina_idx
  ON public.fila_instalacao (machine_id) WHERE entregue_em IS NULL;

COMMENT ON COLUMN public.fila_instalacao.token_cifrado IS
  'Token de uso unico cifrado com a chave do SMTP (Fernet). Entregue uma vez a bandeja da maquina.';

-- 3. Dispositivo: a bandeja informa a versao (coluna pode ja existir) ---------
ALTER TABLE public.agent_devices ADD COLUMN IF NOT EXISTS versao text;

-- 4. Dono e permissoes (modelo: 20261007120000_inclusao_no_sieg.sql) ----------
DO $$
DECLARE
  dono text;
  r record;
BEGIN
  SELECT tableowner INTO dono FROM pg_tables WHERE schemaname = 'public' AND tablename = 'portal_settings';
  IF dono IS NOT NULL AND current_user IN (dono, 'postgres') THEN
    EXECUTE format('ALTER TABLE public.computador_vinculo OWNER TO %I', dono);
    EXECUTE format('ALTER TABLE public.fila_instalacao OWNER TO %I', dono);
  END IF;
  FOR r IN SELECT rolname FROM pg_roles
            WHERE rolcanlogin AND NOT rolsuper
              AND has_table_privilege(rolname, 'public.portal_settings', 'UPDATE')
  LOOP
    EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE ON public.computador_vinculo, public.fila_instalacao TO %I', r.rolname);
    EXECUTE format('GRANT USAGE, SELECT ON SEQUENCE public.computador_vinculo_id_seq, public.fila_instalacao_id_seq TO %I', r.rolname);
  END LOOP;
END $$;

-- Conferencia -------------------------------------------------------------------
SELECT table_name FROM information_schema.tables
 WHERE table_schema = 'public' AND table_name IN ('computador_vinculo', 'fila_instalacao')
 ORDER BY table_name;
