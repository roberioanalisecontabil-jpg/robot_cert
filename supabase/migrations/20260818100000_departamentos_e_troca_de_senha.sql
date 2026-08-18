-- ==========================================================================
-- Departamentos, lideres, e troca de senha obrigatoria
-- Projeto Supabase: wubokujetyaolnjxiiid
--
-- COMO USAR: rode um PASSO de cada vez. Se algum der erro, PARE e me mande a
-- mensagem exata. Sem BEGIN/COMMIT -- o SQL Editor ja roda numa transacao.
--
-- APLICADA EM PRODUCAO EM 18/08/2026, antes do deploy do codigo.
-- Verificado: departamento_id (uuid, anulavel) e deve_trocar_senha
-- (boolean, NOT NULL) existem em users.
--
-- A ORDEM ERA OBRIGATORIA: o select de _conta_da_sessao pede
-- deve_trocar_senha. Codigo antes da coluna faria toda requisicao
-- autenticada virar 503 -- o portal inteiro parando.
--
-- ADITIVA: duas tabelas novas e duas colunas novas. Nada existente e alterado,
-- e o codigo em producao hoje nao conhece nada disto -- entao rodar agora nao
-- muda comportamento nenhum.
--
-- ── O que muda no modelo, e por que importa ──────────────────────────────
--
-- Hoje a permissao e: `admin` e `gestor` tem ALCANCE TOTAL, `user` so instala o
-- que esta na carteira dele. Ou seja, qualquer gestor libera qualquer cliente
-- para qualquer operador. `users.gestor_id` existe e e exibido, mas NAO
-- autoriza nada -- e informativo.
--
-- Com departamento e lider passa a existir o primeiro recorte real: o lider
-- atribui carteira apenas a quem esta no setor dele.
--
-- ── Por que duas tabelas, e nao uma coluna lider_id ──────────────────────
--
-- Um departamento pode ter VARIOS lideres (ferias, turnos, redundancia), e uma
-- pessoa pode liderar mais de um setor. Coluna unica forcaria escolher um, e a
-- primeira ausencia do titular deixaria o setor sem quem libere.
-- ==========================================================================


-- ─────────────────────────────────────────────────────────────────────────
-- PASSO 1 — Diagnostico. Nao altera nada. Me mande os dois resultados.
--
-- 1a esperado: ZERO linhas (as tabelas ainda nao existem).
-- 1b esperado: as colunas de users SEM departamento_id e SEM deve_trocar_senha.
-- ─────────────────────────────────────────────────────────────────────────

-- 1a
SELECT tablename FROM pg_tables
WHERE schemaname = 'public' AND tablename IN ('departamento', 'departamento_lider');

-- 1b
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_schema = 'public' AND table_name = 'users'
ORDER BY ordinal_position;


-- ─────────────────────────────────────────────────────────────────────────
-- PASSO 2 — Os departamentos.
--
-- O indice unico e sobre lower(btrim(nome)): "Fiscal" e "fiscal " seriam o
-- mesmo setor para qualquer pessoa lendo a tela, e dois registros fariam
-- metade da equipe cair em cada um -- com os lideres de um sem alcance sobre
-- os do outro. E a falha silenciosa que este modelo existe para evitar.
-- ─────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS public.departamento (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    nome       text        NOT NULL,
    criado_em  timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS departamento_nome_unico_idx
    ON public.departamento (lower(btrim(nome)));

COMMENT ON TABLE public.departamento IS
    'Setores da empresa. Recorta quem cada lider pode liberar: o lider atribui carteira apenas a quem esta no departamento dele.';


-- ─────────────────────────────────────────────────────────────────────────
-- PASSO 3 — Os lideres.
--
-- Chave composta (departamento, pessoa): a mesma pessoa nao entra duas vezes
-- no mesmo setor, e nada impede que lidere varios.
--
-- ON DELETE CASCADE nos dois lados: apagar o setor ou a conta remove a
-- lideranca. Uma lideranca orfa seria pior que nenhuma -- daria alcance a um
-- id que nao existe mais, e o codigo teria de adivinhar o que fazer.
-- ─────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS public.departamento_lider (
    departamento_id uuid NOT NULL REFERENCES public.departamento(id) ON DELETE CASCADE,
    user_id         uuid NOT NULL REFERENCES public.users(id)        ON DELETE CASCADE,
    criado_em       timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (departamento_id, user_id)
);

-- Para responder "quais setores esta pessoa lidera?" sem varrer a tabela --
-- e a pergunta feita a cada atribuicao de carteira.
CREATE INDEX IF NOT EXISTS departamento_lider_user_idx
    ON public.departamento_lider (user_id);


-- ─────────────────────────────────────────────────────────────────────────
-- PASSO 4 — O departamento de cada pessoa.
--
-- ON DELETE SET NULL, e NAO CASCADE: apagar um setor nao pode apagar as
-- pessoas dele. Elas ficam sem departamento, o que e visivel na tela e
-- corrigivel; o contrario seria irreversivel.
-- ─────────────────────────────────────────────────────────────────────────

ALTER TABLE public.users
    ADD COLUMN IF NOT EXISTS departamento_id uuid
    REFERENCES public.departamento(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS users_departamento_idx
    ON public.users (departamento_id);


-- ─────────────────────────────────────────────────────────────────────────
-- PASSO 5 — Troca de senha obrigatoria.
--
-- NOT NULL com DEFAULT false: as contas que ja existem NAO sao afetadas. Elas
-- escolheram a propria senha em algum momento, e forcar todo mundo a trocar no
-- deploy seria uma surpresa desagradavel sem ganho nenhum.
--
-- Passa a true quando o admin cadastra alguem ou redefine a senha de alguem --
-- os dois casos em que outra pessoa conhece a senha.
-- ─────────────────────────────────────────────────────────────────────────

ALTER TABLE public.users
    ADD COLUMN IF NOT EXISTS deve_trocar_senha boolean NOT NULL DEFAULT false;

COMMENT ON COLUMN public.users.deve_trocar_senha IS
    'Senha definida por outra pessoa (cadastro ou redefinicao pelo admin) e que precisa ser trocada no proximo acesso. A barreira e no servidor: require_auth recusa qualquer rota que nao seja a de trocar a senha enquanto isto for true.';


-- ─────────────────────────────────────────────────────────────────────────
-- PASSO 6 — RLS nas tabelas novas, no mesmo padrao das demais.
--
-- O backend usa SUPABASE_SERVICE_KEY, que ignora RLS -- isto nao muda o
-- funcionamento hoje. Existe porque qualquer caminho futuro com a chave anon
-- leria as tabelas inteiras, e aqui elas dizem quem manda em quem.
-- ─────────────────────────────────────────────────────────────────────────

ALTER TABLE public.departamento        ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.departamento_lider  ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON public.departamento       FROM anon, authenticated;
REVOKE ALL ON public.departamento_lider FROM anon, authenticated;

DROP POLICY IF EXISTS "service_role_acesso_total_departamento" ON public.departamento;
CREATE POLICY "service_role_acesso_total_departamento"
    ON public.departamento FOR ALL TO service_role USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS "service_role_acesso_total_departamento_lider" ON public.departamento_lider;
CREATE POLICY "service_role_acesso_total_departamento_lider"
    ON public.departamento_lider FOR ALL TO service_role USING (true) WITH CHECK (true);


-- ─────────────────────────────────────────────────────────────────────────
-- PASSO 7 — Verificacao. Me mande os tres resultados.
--
-- 7a esperado: DUAS linhas -- departamento e departamento_lider -- as duas com
--    rowsecurity = true.
-- 7b esperado: departamento_id (uuid, YES) e deve_trocar_senha (boolean, NO).
-- 7c esperado: ZERO em obrigados_a_trocar. Se vier alguem, o DEFAULT pegou
--    errado e essa pessoa seria barrada no proximo acesso.
-- ─────────────────────────────────────────────────────────────────────────

-- 7a
SELECT tablename, rowsecurity FROM pg_tables
WHERE schemaname = 'public' AND tablename IN ('departamento', 'departamento_lider');

-- 7b
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_schema = 'public' AND table_name = 'users'
  AND column_name IN ('departamento_id', 'deve_trocar_senha');

-- 7c
SELECT count(*) FILTER (WHERE deve_trocar_senha) AS obrigados_a_trocar,
       count(*)                                  AS total
FROM public.users;
