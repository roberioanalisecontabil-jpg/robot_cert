-- ==========================================================================
-- users: separar PAPEL de ESTADO, e abrir a aresta gestor -> operador
--
-- `role` era texto livre com três valores em uso: 'admin', 'user' e
-- 'disabled'. O terceiro não é um papel -- é o estado da conta ocupando a
-- mesma coluna. A consequência estava em `deactivate_user`, que fazia
-- `update({"role": "disabled"})`: desativar um administrador APAGAVA o
-- registro de que ele era administrador, e reativá-lo virava adivinhação.
--
-- Isso bloqueia a carteira (docs/PLANO_reorganizacao_portal.md §3.3):
-- desativar um gestor apagaria o papel dele e, junto, o sentido das carteiras
-- que ele criou. Com 10 usuários a correção é barata; depois da hierarquia
-- montada, é migration mexendo em vínculo.
--
-- Ver docs/PLANO_reorganizacao_portal.md §6.1 e §6.2
-- ==========================================================================

BEGIN;

-- ─────────────────────────────────────────────────────────────────────────
-- 1. Estado da conta, separado do papel
-- ─────────────────────────────────────────────────────────────────────────
ALTER TABLE public.users
    ADD COLUMN IF NOT EXISTS ativo BOOLEAN NOT NULL DEFAULT TRUE;

COMMENT ON COLUMN public.users.ativo IS
    'Conta habilitada a entrar. Independente de `role`: desativar preserva o papel.';

-- ─────────────────────────────────────────────────────────────────────────
-- 2. Aresta gestor -> operador
--
-- Coluna em vez de tabela de associação: o caso "dois gestores para a mesma
-- pessoa" não existe hoje, e resolver o problema que se tem é mais barato de
-- desfazer do que o contrário. ON DELETE SET NULL porque apagar o gestor não
-- pode levar o operador junto.
-- ─────────────────────────────────────────────────────────────────────────
ALTER TABLE public.users
    ADD COLUMN IF NOT EXISTS gestor_id UUID REFERENCES public.users(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS users_gestor_idx ON public.users (gestor_id);

COMMENT ON COLUMN public.users.gestor_id IS
    'Gestor responsável por este operador. NULL para admin, gestor e operador sem vínculo.';

-- ─────────────────────────────────────────────────────────────────────────
-- 3. Migrar os 'disabled' existentes
--
-- O papel original destes é IRRECUPERÁVEL -- foi sobrescrito por
-- `deactivate_user` quando cada um foi desativado, e não há histórico. Cair
-- em 'user' é a escolha de menor privilégio: se algum era admin, reativá-lo
-- exige uma promoção explícita em vez de devolver poder por omissão.
-- ─────────────────────────────────────────────────────────────────────────
UPDATE public.users
   SET ativo = FALSE,
       role  = 'user'
 WHERE lower(trim(role)) = 'disabled';

-- Normaliza o resto antes do CHECK: a aplicação já comparava com lower/strip,
-- então uma linha com 'Admin' passava despercebida e reprovaria a constraint.
UPDATE public.users
   SET role = lower(trim(role))
 WHERE role IS DISTINCT FROM lower(trim(role));

-- ─────────────────────────────────────────────────────────────────────────
-- 4. Fechar o vocabulário de papéis
--
-- 'gestor' entra agora, junto, para que a etapa da carteira não precise de
-- outra migration só para acrescentar um valor.
-- ─────────────────────────────────────────────────────────────────────────
ALTER TABLE public.users
    DROP CONSTRAINT IF EXISTS users_role_valido;

ALTER TABLE public.users
    ADD CONSTRAINT users_role_valido
    CHECK (role IN ('admin', 'gestor', 'user'));

-- Ninguém é gestor de si mesmo: a consulta "meus operadores" entraria em
-- laço lógico e a tela mostraria a pessoa dentro da própria equipe.
ALTER TABLE public.users
    DROP CONSTRAINT IF EXISTS users_gestor_nao_e_a_si_mesmo;

ALTER TABLE public.users
    ADD CONSTRAINT users_gestor_nao_e_a_si_mesmo
    CHECK (gestor_id IS NULL OR gestor_id <> id);

COMMIT;
