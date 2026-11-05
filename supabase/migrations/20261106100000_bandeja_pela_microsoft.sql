-- ==========================================================================
-- Bandeja pela Microsoft (plano 05/11/2026, Tarefa 1)
--
-- COMO USAR: NAO rode a mao. O atualizacao_push.ps1 aplica as migrations com
-- o usuario certo. Idempotente.
--
-- ADITIVA: tabelas novas, sem tocar em nenhuma tabela existente. O codigo de
-- hoje nao conhece nenhuma delas, entao aplicar antes do codigo novo nao muda
-- nada.
--
-- O que entra:
--
-- 1. bandeja_codigo: codigo de uso unico que a bandeja mostra ao usuario apos
--    o login pela Microsoft. Guardado so como hash; some em 120 s ou na
--    primeira tentativa.
-- 2. bandeja_virada: marca unica (id = 1) de quando o login com senha foi
--    desligado para os dominios, e com qual versao da bandeja.
-- ==========================================================================

-- 1. Codigo de uso unico ----------------------------------------------------------
--    codigo_hash: sha256 do codigo; o codigo em claro nunca fica no banco.
--    desafio: desafio PKCE da sessao que gerou o codigo (o verificador fica so
--    na bandeja).
CREATE TABLE IF NOT EXISTS public.bandeja_codigo (
  codigo_hash  text PRIMARY KEY,
  user_id      uuid NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  desafio      text NOT NULL,
  expira_em    timestamptz NOT NULL,
  usado_em     timestamptz,
  criado_em    timestamptz NOT NULL DEFAULT now()
);

-- Limpeza periodica de codigos vencidos.
CREATE INDEX IF NOT EXISTS bandeja_codigo_expira_idx
  ON public.bandeja_codigo (expira_em);

COMMENT ON TABLE public.bandeja_codigo IS
  'Bandeja pela Microsoft: codigo de uso unico (hash sha256, validade 120 s, queimado na primeira tentativa).';

-- 2. Virada da bandeja --------------------------------------------------------------
--    Uma linha so (id = 1). desligada_em: quando a senha foi desligada para os
--    dominios. versao: a versao da bandeja que valia naquele momento.
CREATE TABLE IF NOT EXISTS public.bandeja_virada (
  id            smallint PRIMARY KEY DEFAULT 1 CHECK (id = 1),
  desligada_em  timestamptz NOT NULL DEFAULT now(),
  versao        text NOT NULL
);

COMMENT ON TABLE public.bandeja_virada IS
  'Bandeja pela Microsoft: linha unica (id = 1) com o momento em que a senha foi desligada para os dominios.';

-- 3. Dono e permissoes (modelo: 20261016100000_carteira_sugerida_pelo_acessorias.sql) --
DO $$
DECLARE
  dono text;
  r record;
BEGIN
  SELECT tableowner INTO dono FROM pg_tables WHERE schemaname = 'public' AND tablename = 'portal_settings';
  IF dono IS NOT NULL AND current_user IN (dono, 'postgres') THEN
    EXECUTE format('ALTER TABLE public.bandeja_codigo OWNER TO %I', dono);
    EXECUTE format('ALTER TABLE public.bandeja_virada OWNER TO %I', dono);
  END IF;
  FOR r IN SELECT rolname FROM pg_roles
            WHERE rolcanlogin AND NOT rolsuper
              AND has_table_privilege(rolname, 'public.portal_settings', 'UPDATE')
  LOOP
    EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE ON public.bandeja_codigo, public.bandeja_virada TO %I', r.rolname);
  END LOOP;
END $$;

-- Conferencia -------------------------------------------------------------------
-- Esperado: as duas tabelas e o indice de expiracao.
SELECT table_name FROM information_schema.tables
 WHERE table_schema = 'public' AND table_name IN ('bandeja_codigo', 'bandeja_virada')
 ORDER BY table_name;
SELECT indexname FROM pg_indexes WHERE indexname = 'bandeja_codigo_expira_idx';
