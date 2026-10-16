-- ==========================================================================
-- Carteira sugerida pelo Acessorias (ADR 0004 e adendo, 16/10/2026)
--
-- COMO USAR: NAO rode a mao. O atualizacao_push.ps1 aplica as migrations com
-- o usuario certo. Se precisar rodar a mao, o bloco final (passo 8) acerta
-- dono e permissoes. Idempotente.
--
-- ADITIVA: tabelas novas e uma coluna nova em carteira, com valor padrao. O
-- codigo de hoje nao conhece nada disto, entao aplicar antes do codigo novo
-- nao muda comportamento nenhum.
--
-- ── O que entra ──────────────────────────────────────────────────────────
--
-- 1. acessorias_departamento: os departamentos do Acessorias, ligados (ou
--    nao) a um departamento do portal, e quais deles dao carteira.
-- 2. acessorias_empresa / acessorias_responsavel: a copia local da busca.
--    So CNPJ, razao social, ativa, departamento e o responsavel (nome e
--    e-mail). Honorario e contatos do cliente nao entram.
-- 3. acessorias_busca: cada busca (as 02:00 ou pelo botao), com o resultado.
-- 4. acessorias_recusa: sugestoes recusadas (de carteira e de departamento),
--    que nao voltam enquanto o Acessorias nao mudar aquele par.
-- 5. carteira.origem: manual, planilha ou acessorias. O que ja existe fica
--    'manual' (nao ha como separar o que veio de planilha).
-- 6. carteira_historico: entradas e saidas da carteira, de qualquer origem.
--    Hoje remover apaga a linha sem rastro.
--
-- Nada aqui escreve no Acessorias, nem muda carteira ou departamento de
-- ninguem: tudo continua dependendo de aprovacao.
-- ==========================================================================

-- 1. Departamentos do Acessorias ---------------------------------------------
--    id: o ID do Acessorias (1 = Contabil, 2 = Fiscal, 3 = Pessoal...).
--    departamento_id: o departamento do portal que corresponde. Unico: dois
--    departamentos do Acessorias no mesmo do portal misturariam as equipes.
--    conta_para_carteira: se os responsaveis deste departamento recebem
--    sugestoes de carteira (configuravel na tela).
CREATE TABLE IF NOT EXISTS public.acessorias_departamento (
  id                   integer PRIMARY KEY,
  nome                 text NOT NULL,
  departamento_id      uuid UNIQUE REFERENCES public.departamento(id) ON DELETE SET NULL,
  conta_para_carteira  boolean NOT NULL DEFAULT false,
  visto_em             timestamptz
);

COMMENT ON TABLE public.acessorias_departamento IS
  'ADR 0004: departamentos do Acessorias (id deles), a ligacao com o departamento do portal e '
  'se dao carteira. A busca atualiza o nome; a ligacao e conta_para_carteira sao do Administrador.';

-- Os tres que o ADR 0004 decidiu (16/10/2026). Os demais entram na primeira
-- busca, desmarcados. ON CONFLICT DO NOTHING: rodar de novo nao desfaz o que
-- o Administrador mudou na tela.
INSERT INTO public.acessorias_departamento (id, nome, conta_para_carteira) VALUES
  (1, 'Contábil', true),
  (2, 'Fiscal',   true),
  (3, 'Pessoal',  true)
ON CONFLICT (id) DO NOTHING;

-- 2. Copia local das empresas e dos responsaveis -----------------------------
--    vista_em: a ultima busca completa em que a empresa veio. A empresa que
--    nao veio na ultima busca terminada com sucesso foi removida no Acessorias.
CREATE TABLE IF NOT EXISTS public.acessorias_empresa (
  cnpj          text PRIMARY KEY CHECK (cnpj ~ '^[0-9]{14}$'),
  razao_social  text NOT NULL DEFAULT '',
  ativa         boolean NOT NULL,
  vista_em      timestamptz NOT NULL DEFAULT now()
);

-- Um responsavel por empresa e departamento (e o que a API devolve). O e-mail
-- fica em minusculas: e por ele que a pessoa e ligada a conta do portal.
-- Sem FK em departamento_acessorias_id: a copia reflete a API como veio, e um
-- departamento novo no Acessorias nao pode derrubar a busca.
CREATE TABLE IF NOT EXISTS public.acessorias_responsavel (
  cnpj                       text NOT NULL REFERENCES public.acessorias_empresa(cnpj) ON DELETE CASCADE,
  departamento_acessorias_id integer NOT NULL,
  nome                       text NOT NULL DEFAULT '',
  email                      text NOT NULL DEFAULT '' CHECK (email = lower(email)),
  PRIMARY KEY (cnpj, departamento_acessorias_id)
);

CREATE INDEX IF NOT EXISTS acessorias_responsavel_email_idx
  ON public.acessorias_responsavel (email);

COMMENT ON TABLE public.acessorias_responsavel IS
  'ADR 0004: responsavel do escritorio por empresa e departamento, copiado do Acessorias '
  '(ListAll?departments). So nome e e-mail; contatos do cliente nao entram.';

-- 3. Buscas ----------------------------------------------------------------
--    Uma de cada vez: o indice parcial recusa uma segunda busca 'rodando'
--    (o botao apertado durante a das 02:00, ou duas abas). O limite de 100
--    chamadas por minuto da API e compartilhado com o DIARIO2.0.
CREATE TABLE IF NOT EXISTS public.acessorias_busca (
  id                   bigserial PRIMARY KEY,
  origem               text NOT NULL CHECK (origem IN ('agendada', 'botao')),
  disparada_por_email  text NOT NULL DEFAULT '',
  iniciada_em          timestamptz NOT NULL DEFAULT now(),
  terminada_em         timestamptz,
  estado               text NOT NULL DEFAULT 'rodando' CHECK (estado IN ('rodando', 'ok', 'erro')),
  paginas              integer NOT NULL DEFAULT 0,
  empresas             integer NOT NULL DEFAULT 0,
  erro                 text NOT NULL DEFAULT ''
);

CREATE UNIQUE INDEX IF NOT EXISTS acessorias_busca_uma_rodando
  ON public.acessorias_busca ((true)) WHERE estado = 'rodando';

CREATE INDEX IF NOT EXISTS acessorias_busca_iniciada_idx
  ON public.acessorias_busca (iniciada_em DESC);

-- 4. Recusas -----------------------------------------------------------------
--    tipo 'carteira_entrada' / 'carteira_saida': chave = documento (so digitos).
--    tipo 'departamento': chave = departamento do portal sugerido (uuid).
--    motivo 'recusada' (botao) ou 'mudanca_manual' (o Administrador pos a
--    pessoa noutro departamento: a mudanca manual vence).
--    A busca apaga a recusa quando a sugestao deixa de existir; se ela voltar
--    depois, e uma sugestao nova.
CREATE TABLE IF NOT EXISTS public.acessorias_recusa (
  id                  bigserial PRIMARY KEY,
  tipo                text NOT NULL CHECK (tipo IN ('carteira_entrada', 'carteira_saida', 'departamento')),
  user_id             uuid NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  chave               text NOT NULL,
  motivo              text NOT NULL DEFAULT 'recusada' CHECK (motivo IN ('recusada', 'mudanca_manual')),
  recusado_por        uuid REFERENCES public.users(id) ON DELETE SET NULL,
  recusado_por_email  text NOT NULL,
  recusado_em         timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tipo, user_id, chave)
);

-- 5. De onde veio cada Atribuicao --------------------------------------------
--    So o que veio do Acessorias e sugerido para remocao (ADR 0004).
ALTER TABLE public.carteira
  ADD COLUMN IF NOT EXISTS origem text NOT NULL DEFAULT 'manual';

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
     WHERE conrelid = 'public.carteira'::regclass AND conname = 'carteira_origem_valida'
  ) THEN
    ALTER TABLE public.carteira
      ADD CONSTRAINT carteira_origem_valida CHECK (origem IN ('manual', 'planilha', 'acessorias'));
  END IF;
END $$;

COMMENT ON COLUMN public.carteira.origem IS
  'manual (tela), planilha (importacao) ou acessorias (sugestao aprovada; atribuido_por e quem '
  'aprovou). As anteriores a 16/10/2026 ficaram manual.';

-- 6. Historico da carteira ---------------------------------------------------
--    user_email e feito_por_email redundantes de proposito, como na carteira:
--    o historico sobrevive a exclusao das contas.
--    origem: de onde veio a mudanca. 'papel' e 'desativacao' sao as saidas em
--    massa de esvaziar_carteira (ADR 0001).
CREATE TABLE IF NOT EXISTS public.carteira_historico (
  id               bigserial PRIMARY KEY,
  user_id          uuid REFERENCES public.users(id) ON DELETE SET NULL,
  user_email       text NOT NULL,
  documento        text NOT NULL,
  movimento        text NOT NULL CHECK (movimento IN ('entrada', 'saida')),
  origem           text NOT NULL CHECK (origem IN ('manual', 'planilha', 'acessorias', 'papel', 'desativacao')),
  feito_por        uuid REFERENCES public.users(id) ON DELETE SET NULL,
  feito_por_email  text NOT NULL,
  feito_em         timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS carteira_historico_user_idx
  ON public.carteira_historico (user_id, feito_em DESC);
CREATE INDEX IF NOT EXISTS carteira_historico_documento_idx
  ON public.carteira_historico (documento, feito_em DESC);

COMMENT ON TABLE public.carteira_historico IS
  'ADR 0004: entradas e saidas das Atribuicoes, de qualquer origem (manual, planilha, '
  'Acessorias, troca de papel, desativacao). So acrescenta; nunca se apaga linha daqui.';

-- 7. (reservado: nada muda em users nem em departamento_lider. A lideranca
--    continua so manual, adendo do ADR 0004.)

-- 8. Dono e permissoes (modelo: 20261007120000_inclusao_no_sieg.sql) ----------
DO $$
DECLARE
  dono text;
  r record;
BEGIN
  SELECT tableowner INTO dono FROM pg_tables WHERE schemaname = 'public' AND tablename = 'portal_settings';
  IF dono IS NOT NULL AND current_user IN (dono, 'postgres') THEN
    EXECUTE format('ALTER TABLE public.acessorias_departamento OWNER TO %I', dono);
    EXECUTE format('ALTER TABLE public.acessorias_empresa OWNER TO %I', dono);
    EXECUTE format('ALTER TABLE public.acessorias_responsavel OWNER TO %I', dono);
    EXECUTE format('ALTER TABLE public.acessorias_busca OWNER TO %I', dono);
    EXECUTE format('ALTER TABLE public.acessorias_recusa OWNER TO %I', dono);
    EXECUTE format('ALTER TABLE public.carteira_historico OWNER TO %I', dono);
  END IF;
  FOR r IN SELECT rolname FROM pg_roles
            WHERE rolcanlogin AND NOT rolsuper
              AND has_table_privilege(rolname, 'public.portal_settings', 'UPDATE')
  LOOP
    EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE ON public.acessorias_departamento, '
                   'public.acessorias_empresa, public.acessorias_responsavel, public.acessorias_busca, '
                   'public.acessorias_recusa, public.carteira_historico TO %I', r.rolname);
    EXECUTE format('GRANT USAGE, SELECT ON SEQUENCE public.acessorias_busca_id_seq, '
                   'public.acessorias_recusa_id_seq, public.carteira_historico_id_seq TO %I', r.rolname);
  END LOOP;
END $$;

-- Conferencia -------------------------------------------------------------------
-- Esperado: as seis tabelas; carteira.origem; os tres departamentos marcados.
SELECT table_name FROM information_schema.tables
 WHERE table_schema = 'public'
   AND table_name IN ('acessorias_departamento', 'acessorias_empresa', 'acessorias_responsavel',
                      'acessorias_busca', 'acessorias_recusa', 'carteira_historico')
 ORDER BY table_name;
SELECT column_name FROM information_schema.columns
 WHERE table_schema = 'public' AND table_name = 'carteira' AND column_name = 'origem';
SELECT id, nome, conta_para_carteira FROM public.acessorias_departamento ORDER BY id;
