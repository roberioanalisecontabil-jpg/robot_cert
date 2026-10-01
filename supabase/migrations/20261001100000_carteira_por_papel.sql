-- ==========================================================================
-- Carteira por Papel (ADR 0001, 01/10/2026)
--
-- COMO USAR: rode um PASSO de cada vez, no psql do ANALISESRV, DEPOIS do
-- deploy do codigo. Se algum der erro, PARE e me mande a mensagem exata.
-- Idempotente: rodar duas vezes nao faz mal.
--
-- ORDEM OBRIGATORIA: codigo novo primeiro, esta migration em seguida. O
-- codigo antigo ainda le as linhas "regra:gestor" da carteira; o novo nao as
-- le e passa a ler carteira_excecao, que so existe depois do PASSO 2.
--
-- ── O que muda no modelo ─────────────────────────────────────────────────
--
-- Operador: carteira de ATRIBUICOES (tabela carteira), como antes.
-- Gestor:   carteira de EXCECOES (tabela carteira_excecao, nova). Ele alcanca
--           todo o inventario, inclusive o que entrar depois, menos o que o
--           administrador retirar.
-- Gestor DERIVA da lideranca: quem esta em departamento_lider e gestor; quem
--           nao esta e operador. Administrador nao muda.
--
-- ── Transicao dos dados de hoje (PASSOS 3 e 4) ───────────────────────────
--
-- 1. A carteira de todo gestor atual e de todo lider atual e ESVAZIADA: a de
--    quem continua gestor passa a ser de excecoes (comeca sem nenhuma); a de
--    quem vai virar gestor idem. O que o administrador tinha "tirado" de um
--    gestor era ausencia de linha, nao se recupera: as excecoes comecam vazias
--    e o administrador registra de novo as que quiser, em Carteiras.
-- 2. Lider que nao e gestor nem admin vira gestor.
-- 3. Gestor que nao lidera nada vira operador (a carteira ja foi esvaziada).
-- 4. sessao_versao sobe para quem mudou de papel: o papel viaja no token, e a
--    pessoa precisa entrar de novo para receber o novo.
-- 5. Quem esta sem departamento NAO e tocado e continua entrando. Fica sem
--    gestor ate o administrador enquadra-lo; a tela de Usuarios avisa.
--
-- Vocabulario: GLOSSARY.md. Decisao: docs/adr/0001-carteira-por-papel.md.
-- ==========================================================================


-- ─────────────────────────────────────────────────────────────────────────
-- PASSO 1 — Diagnostico. Nao altera nada. Me mande os resultados.
--
-- 1a: quem VAI VIRAR gestor (lidera e hoje e operador).
-- 1b: quem VAI VIRAR operador (e gestor e nao lidera nada). Perde a carteira.
-- 1c: quantas linhas de carteira serao apagadas (gestores + lideres), e
--     quantas delas sao da regra de 30/09.
-- 1d: quem esta sem departamento (nao muda; so para voce saber).
-- ─────────────────────────────────────────────────────────────────────────

-- 1a
SELECT u.id, u.email, u.role AS papel_atual, count(l.departamento_id) AS departamentos_que_lidera
FROM public.users u
JOIN public.departamento_lider l ON l.user_id = u.id
WHERE u.role = 'user'
GROUP BY u.id, u.email, u.role
ORDER BY u.email;

-- 1b
SELECT u.id, u.email, u.role AS papel_atual,
       (SELECT count(*) FROM public.carteira c WHERE c.user_id = u.id) AS linhas_de_carteira
FROM public.users u
WHERE u.role = 'gestor'
  AND NOT EXISTS (SELECT 1 FROM public.departamento_lider l WHERE l.user_id = u.id)
ORDER BY u.email;

-- 1c
SELECT count(*) AS linhas_a_apagar,
       count(*) FILTER (WHERE c.atribuido_por_email = 'regra:gestor') AS das_quais_pela_regra
FROM public.carteira c
WHERE c.user_id IN (SELECT id FROM public.users WHERE role = 'gestor')
   OR c.user_id IN (SELECT user_id FROM public.departamento_lider);

-- 1d
SELECT id, email, role FROM public.users
WHERE departamento_id IS NULL AND ativo
ORDER BY email;


-- ─────────────────────────────────────────────────────────────────────────
-- PASSO 2 — A tabela de Excecoes.
--
-- Mesma forma da carteira, com o sinal invertido: uma linha aqui e um
-- documento que o gestor NAO alcanca. Tabela propria, e nao uma coluna
-- `tipo` em carteira: "documento X" significando "pode" para um papel e
-- "nao pode" para outro e o tipo de ambiguidade que um WHERE esquecido
-- transforma em vazamento.
--
-- A trilha (quem retirou, quando) e redundante de proposito, como em
-- carteira: o e-mail sobrevive a exclusao da conta de quem registrou.
-- ─────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS public.carteira_excecao (
    user_id              uuid        NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    documento            text        NOT NULL,   -- so digitos, como carteira.documento
    registrado_por       uuid        REFERENCES public.users(id) ON DELETE SET NULL,
    registrado_por_email text        NOT NULL,
    registrado_em        timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, documento)
);

CREATE INDEX IF NOT EXISTS carteira_excecao_user_idx      ON public.carteira_excecao (user_id);
CREATE INDEX IF NOT EXISTS carteira_excecao_documento_idx ON public.carteira_excecao (documento);

COMMENT ON TABLE public.carteira_excecao IS
    'Excecoes da carteira de um Gestor (ADR 0001): documentos que ele NAO alcanca. O Gestor alcanca todo o inventario menos estas linhas. So o Administrador registra.';

COMMENT ON COLUMN public.carteira_excecao.documento IS
    'CNPJ/CPF so com digitos, mesmo formato de carteira.documento.';

ALTER TABLE public.carteira_excecao ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON public.carteira_excecao FROM anon, authenticated;

DROP POLICY IF EXISTS "service_role_acesso_total_carteira_excecao" ON public.carteira_excecao;
CREATE POLICY "service_role_acesso_total_carteira_excecao"
    ON public.carteira_excecao FOR ALL TO service_role USING (true) WITH CHECK (true);


-- ─────────────────────────────────────────────────────────────────────────
-- PASSO 3 — Esvaziar as carteiras de gestores e de lideres.
--
-- ANTES do PASSO 4, porque o PASSO 4 troca os papeis e este passo seleciona
-- pelo papel de hoje. Gestor que vai virar operador perde a carteira (regra:
-- carteira nao guarda estado dormente); lider que vai virar gestor tambem (a
-- carteira nova e de excecoes). As linhas da regra de 30/09 saem junto.
-- ─────────────────────────────────────────────────────────────────────────

DELETE FROM public.carteira
WHERE user_id IN (SELECT id FROM public.users WHERE role = 'gestor')
   OR user_id IN (SELECT user_id FROM public.departamento_lider);

DELETE FROM public.carteira
WHERE atribuido_por_email = 'regra:gestor';


-- ─────────────────────────────────────────────────────────────────────────
-- PASSO 4 — Os papeis seguem a lideranca.
--
-- sessao_versao + 1 derruba as sessoes de quem mudou: o papel viaja no token.
-- Administrador nao e tocado, lidere ou nao.
-- ─────────────────────────────────────────────────────────────────────────

UPDATE public.users
SET role = 'gestor',
    sessao_versao = COALESCE(sessao_versao, 0) + 1
WHERE role = 'user'
  AND id IN (SELECT user_id FROM public.departamento_lider);

UPDATE public.users
SET role = 'user',
    sessao_versao = COALESCE(sessao_versao, 0) + 1
WHERE role = 'gestor'
  AND NOT EXISTS (SELECT 1 FROM public.departamento_lider l WHERE l.user_id = users.id);


-- ─────────────────────────────────────────────────────────────────────────
-- PASSO 5 — Verificacao. Me mande os resultados.
--
-- 5a esperado: carteira_excecao com rowsecurity = true.
-- 5b esperado: ZERO linhas (nenhum lider que nao seja gestor ou admin).
-- 5c esperado: ZERO linhas (nenhum gestor sem lideranca).
-- 5d esperado: ZERO (nenhuma linha de carteira em gestor; nenhuma da regra).
-- ─────────────────────────────────────────────────────────────────────────

-- 5a
SELECT tablename, rowsecurity FROM pg_tables
WHERE schemaname = 'public' AND tablename = 'carteira_excecao';

-- 5b
SELECT u.email, u.role FROM public.users u
JOIN public.departamento_lider l ON l.user_id = u.id
WHERE u.role NOT IN ('gestor', 'admin');

-- 5c
SELECT u.email FROM public.users u
WHERE u.role = 'gestor'
  AND NOT EXISTS (SELECT 1 FROM public.departamento_lider l WHERE l.user_id = u.id);

-- 5d
SELECT count(*) FILTER (WHERE u.role = 'gestor') AS carteira_em_gestor,
       count(*) FILTER (WHERE c.atribuido_por_email = 'regra:gestor') AS linhas_da_regra
FROM public.carteira c
JOIN public.users u ON u.id = c.user_id;
