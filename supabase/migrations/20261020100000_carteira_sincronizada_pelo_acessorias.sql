-- ==========================================================================
-- Carteira sincronizada pelo Acessorias (ADR 0005, 18/10/2026)
--
-- COMO USAR: NAO rode a mao. O atualizacao_push.ps1 aplica as migrations com
-- o usuario certo. Se precisar rodar a mao, o bloco final (passo 8) acerta
-- dono e permissoes. Idempotente.
--
-- ADITIVA: tabelas e colunas novas, com valor padrao. O codigo de hoje nao
-- conhece nada disto, entao aplicar antes do codigo novo nao muda nada.
-- carteira_excecao NAO sai aqui: o codigo de hoje ainda a le (Gestor = tudo
-- menos as Excecoes). Ela sai numa migration seguinte, depois da virada.
--
-- ── O que entra ──────────────────────────────────────────────────────────
--
-- 1. acessorias_usuario: copia dos usuarios do Acessorias (id, nome, e-mail,
--    ativo). E deles que nascem e se desativam as contas.
-- 2. users.origem / users.acessorias_id: a conta veio do Acessorias? So essas
--    a busca cria, desativa e reativa. Admin e contas manuais nunca.
-- 3. carteira_bloqueio: o Gestor (seus Operadores) ou o Admin (qualquer um)
--    segura um documento; a busca nao recria o acesso.
-- 4. acessorias_busca: o resultado fica guardado quando precisa de
--    confirmacao (primeira vez ou mais de 10% de saidas), e a aplicacao e
--    registrada.
-- 5. carteira_historico.origem ganha 'bloqueio'.
-- 6. departamento.arquivado: departamento do portal sem par no Acessorias
--    que o Admin decidiu nao usar.
-- 7. acessorias_departamento.conta_para_carteira passa a ser a chave
--    "trazer" da tela (mesmo dado, nome do ADR 0004 mantido).
-- ==========================================================================

-- 1. Usuarios do Acessorias ----------------------------------------------------
--    id: o ID do Acessorias. email em minusculas, como em acessorias_responsavel:
--    e por ele que a pessoa e ligada a conta do portal.
CREATE TABLE IF NOT EXISTS public.acessorias_usuario (
  id        integer PRIMARY KEY,
  nome      text NOT NULL DEFAULT '',
  email     text NOT NULL DEFAULT '' CHECK (email = lower(email)),
  ativo     boolean NOT NULL,
  vista_em  timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS acessorias_usuario_email_idx
  ON public.acessorias_usuario (email);

COMMENT ON TABLE public.acessorias_usuario IS
  'ADR 0005: usuarios do escritorio no Acessorias (GET /users/ListAll). Ativo la = conta ativa '
  'aqui, para as contas com users.origem = acessorias.';

-- 2. De onde veio a conta --------------------------------------------------------
ALTER TABLE public.users
  ADD COLUMN IF NOT EXISTS origem text NOT NULL DEFAULT 'manual';
ALTER TABLE public.users
  ADD COLUMN IF NOT EXISTS acessorias_id integer;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
     WHERE conrelid = 'public.users'::regclass AND conname = 'users_origem_valida'
  ) THEN
    ALTER TABLE public.users
      ADD CONSTRAINT users_origem_valida CHECK (origem IN ('manual', 'acessorias'));
  END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS users_acessorias_id_unico
  ON public.users (acessorias_id) WHERE acessorias_id IS NOT NULL;

COMMENT ON COLUMN public.users.origem IS
  'ADR 0005: acessorias = criada pela busca; so essas sao desativadas e reativadas com o '
  'Acessorias. manual = todas as anteriores a 20/10/2026 e as criadas na tela.';
COMMENT ON COLUMN public.users.acessorias_id IS
  'ADR 0005: id do usuario no Acessorias, gravado quando a conta e criada ou ligada pelo e-mail.';

-- 3. Bloqueios -------------------------------------------------------------------
--    Um por pessoa e documento. Bloquear tira a linha da carteira (historico
--    com origem 'bloqueio'); desbloquear so apaga esta linha, e a proxima
--    busca devolve o acesso se o Acessorias ainda o der.
CREATE TABLE IF NOT EXISTS public.carteira_bloqueio (
  user_id               uuid NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  documento             text NOT NULL CHECK (documento ~ '^[0-9]{11}$|^[0-9]{14}$'),
  bloqueado_por         uuid REFERENCES public.users(id) ON DELETE SET NULL,
  bloqueado_por_email   text NOT NULL,
  bloqueado_em          timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (user_id, documento)
);

COMMENT ON TABLE public.carteira_bloqueio IS
  'ADR 0005: documento que a busca do Acessorias nao pode dar a esta pessoa. Gestor bloqueia '
  'para os Operadores dos departamentos que lidera; Admin para qualquer um.';

-- 4. Buscas: resultado guardado e aplicacao --------------------------------------
--    estado:
--      rodando     lendo a API
--      ok          lida e aplicada (aplicada_em preenchido)
--      aguardando  lida inteira, mas pede confirmacao do Admin (primeira
--                  aplicacao ou mais de 10% de saidas); plano guardado
--      descartada  aguardava e foi recusada, ou uma busca mais nova a substituiu
--      erro        incompleta: nada aplicado
--    plano: o que a aplicacao faria (entradas, saidas, contas), calculado na
--    hora da leitura; resumo: as contagens mostradas na confirmacao.
ALTER TABLE public.acessorias_busca ADD COLUMN IF NOT EXISTS plano jsonb NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE public.acessorias_busca ADD COLUMN IF NOT EXISTS resumo jsonb NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE public.acessorias_busca ADD COLUMN IF NOT EXISTS aplicada_em timestamptz;
ALTER TABLE public.acessorias_busca ADD COLUMN IF NOT EXISTS decidida_por_email text NOT NULL DEFAULT '';
ALTER TABLE public.acessorias_busca ADD COLUMN IF NOT EXISTS decidida_em timestamptz;

-- A restricao de estado veio inline em 20261016100000 (nome gerado pelo
-- PostgreSQL). Troca pela nomeada, achando a antiga pela definicao, nao pelo
-- nome: DROP CONSTRAINT IF EXISTS com nome errado passaria calado.
DO $$
DECLARE
  r record;
BEGIN
  FOR r IN SELECT conname FROM pg_constraint
            WHERE conrelid = 'public.acessorias_busca'::regclass AND contype = 'c'
              AND conname <> 'acessorias_busca_estado_valido'
              AND pg_get_constraintdef(oid) LIKE '%estado%'
  LOOP
    EXECUTE format('ALTER TABLE public.acessorias_busca DROP CONSTRAINT %I', r.conname);
  END LOOP;
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
     WHERE conrelid = 'public.acessorias_busca'::regclass AND conname = 'acessorias_busca_estado_valido'
  ) THEN
    ALTER TABLE public.acessorias_busca ADD CONSTRAINT acessorias_busca_estado_valido
      CHECK (estado IN ('rodando', 'ok', 'aguardando', 'descartada', 'erro'));
  END IF;
END $$;

-- 5. Historico: saida por bloqueio ----------------------------------------------
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
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
     WHERE conrelid = 'public.carteira_historico'::regclass AND conname = 'carteira_historico_origem_valida'
  ) THEN
    ALTER TABLE public.carteira_historico ADD CONSTRAINT carteira_historico_origem_valida
      CHECK (origem IN ('manual', 'planilha', 'acessorias', 'papel', 'desativacao', 'bloqueio'));
  END IF;
END $$;

-- 6. Departamento arquivado ------------------------------------------------------
ALTER TABLE public.departamento
  ADD COLUMN IF NOT EXISTS arquivado boolean NOT NULL DEFAULT false;

COMMENT ON COLUMN public.departamento.arquivado IS
  'ADR 0005: departamento sem par no Acessorias que o Admin arquivou. Some das listas de escolha.';

-- 7. Chave "trazer" ---------------------------------------------------------------
COMMENT ON COLUMN public.acessorias_departamento.conta_para_carteira IS
  'ADR 0005: chave "trazer". Ligada, os responsaveis deste departamento ganham as carteiras '
  'das empresas dele e o departamento existe no portal; desligada, esses acessos saem na '
  'proxima busca (com a trava).';

-- 8. Dono e permissoes (modelo: 20261007120000_inclusao_no_sieg.sql) ----------
DO $$
DECLARE
  dono text;
  r record;
BEGIN
  SELECT tableowner INTO dono FROM pg_tables WHERE schemaname = 'public' AND tablename = 'portal_settings';
  IF dono IS NOT NULL AND current_user IN (dono, 'postgres') THEN
    EXECUTE format('ALTER TABLE public.acessorias_usuario OWNER TO %I', dono);
    EXECUTE format('ALTER TABLE public.carteira_bloqueio OWNER TO %I', dono);
  END IF;
  FOR r IN SELECT rolname FROM pg_roles
            WHERE rolcanlogin AND NOT rolsuper
              AND has_table_privilege(rolname, 'public.portal_settings', 'UPDATE')
  LOOP
    EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE ON public.acessorias_usuario, '
                   'public.carteira_bloqueio TO %I', r.rolname);
  END LOOP;
END $$;

-- Conferencia -------------------------------------------------------------------
-- Esperado: as duas tabelas; users.origem e users.acessorias_id; as duas
-- restricoes nomeadas; departamento.arquivado.
SELECT table_name FROM information_schema.tables
 WHERE table_schema = 'public' AND table_name IN ('acessorias_usuario', 'carteira_bloqueio')
 ORDER BY table_name;
SELECT table_name, column_name FROM information_schema.columns
 WHERE table_schema = 'public'
   AND ((table_name = 'users' AND column_name IN ('origem', 'acessorias_id'))
     OR (table_name = 'departamento' AND column_name = 'arquivado'))
 ORDER BY 1, 2;
SELECT conname FROM pg_constraint
 WHERE conname IN ('acessorias_busca_estado_valido', 'carteira_historico_origem_valida', 'users_origem_valida')
 ORDER BY 1;
