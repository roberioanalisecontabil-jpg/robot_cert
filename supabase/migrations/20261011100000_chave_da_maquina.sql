-- ==========================================================================
-- Chave da maquina (adendo ao ADR 0002, 10/10/2026)
--
-- COMO USAR: NAO rode a mao. O atualizacao_push.ps1 aplica as migrations com
-- o usuario certo. Se precisar rodar a mao, o bloco final (passo 3) acerta
-- dono e permissoes. Idempotente.
--
-- ── Por que ──────────────────────────────────────────────────────────────
--
-- O machine_id que a bandeja manda e so um texto. Com a senha de alguem, dava
-- para registrar uma bandeja dizendo ser a maquina dela, de qualquer lugar: o
-- par ja autorizado reconectava sem o administrador e recebia os PFX da
-- carteira (auditoria de 10/10/2026, achado
-- app/agent_devices.py:registrar:machine-id-autodeclarado-autoriza-reentrada).
--
-- A bandeja 2.1.4 gera na instalacao uma chave secreta que fica na estacao. A
-- primeira aprovacao do administrador FIXA a chave daquela maquina; depois,
-- reconectar sem ela e "equipamento novo" e volta para o administrador.
-- ==========================================================================

-- 1. A chave fixada de cada maquina ------------------------------------------
CREATE TABLE IF NOT EXISTS public.maquina_chave (
  machine_id  text PRIMARY KEY,
  chave_hash  text NOT NULL,
  fixada_em   timestamptz NOT NULL DEFAULT now(),
  fixada_por  text NOT NULL DEFAULT ''
);

COMMENT ON TABLE public.maquina_chave IS
  'Adendo ao ADR 0002: sha256 da chave que a bandeja gera na instalacao. Fixada pela aprovacao '
  'do administrador; reconexao sem ela volta a pedir aprovacao.';

-- 2. O pedido guarda a chave que veio com ele; a aprovacao de bandeja antiga
--    (sem chave) libera um reacesso por uma hora -----------------------------
ALTER TABLE public.computador_vinculo ADD COLUMN IF NOT EXISTS chave_hash text;
ALTER TABLE public.computador_vinculo ADD COLUMN IF NOT EXISTS reconexao_liberada_ate timestamptz;

-- 3. Dono e permissoes (modelo: 20261007120000_inclusao_no_sieg.sql) ----------
DO $$
DECLARE
  dono text;
  r record;
BEGIN
  SELECT tableowner INTO dono FROM pg_tables WHERE schemaname = 'public' AND tablename = 'portal_settings';
  IF dono IS NOT NULL AND current_user IN (dono, 'postgres') THEN
    EXECUTE format('ALTER TABLE public.maquina_chave OWNER TO %I', dono);
  END IF;
  FOR r IN SELECT rolname FROM pg_roles
            WHERE rolcanlogin AND NOT rolsuper
              AND has_table_privilege(rolname, 'public.portal_settings', 'UPDATE')
  LOOP
    EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE ON public.maquina_chave TO %I', r.rolname);
  END LOOP;
END $$;

-- Conferencia -------------------------------------------------------------------
SELECT column_name FROM information_schema.columns
 WHERE table_schema = 'public' AND table_name = 'computador_vinculo'
   AND column_name IN ('chave_hash', 'reconexao_liberada_ate')
 ORDER BY column_name;
SELECT table_name FROM information_schema.tables
 WHERE table_schema = 'public' AND table_name = 'maquina_chave';
