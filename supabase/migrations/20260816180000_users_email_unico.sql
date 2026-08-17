-- ==========================================================================
-- users.email: único, e normalizado em minúsculas
--
-- Até 16/08/2026 nada impedia dois usuários com o mesmo e-mail. Confirmado
-- por sonda: editar a conta A para o e-mail de B devolvia HTTP 200 e deixava
-- as duas com o mesmo endereço.
--
-- O estrago é silencioso e progressivo:
--
--   * o login faz `.eq("email", ...).limit(1)` e pega UMA arbitrariamente --
--     a outra pessoa simplesmente nunca mais entra, sem mensagem nenhuma;
--   * `_resolve_user_id` passa a resolver para a conta errada, e com ela vão
--     junto a carteira (quem pode instalar o quê) e a trilha (quem instalou).
--
-- A aplicação também passa a checar, para dar mensagem decente em vez de um
-- 400 cru do PostgREST. Mas a checagem na aplicação tem janela de corrida --
-- duas requisições simultâneas passam as duas pela leitura antes de qualquer
-- uma gravar. Só a restrição no banco fecha isso de verdade.
--
-- Índice sobre `lower(email)`: o portal já normaliza para minúsculas ao
-- gravar, mas uma linha antiga com "Fulano@x.com" tornaria "fulano@x.com"
-- gravável, e as duas seriam a mesma pessoa para qualquer leitor humano.
--
-- CORREÇÃO DE 17/08/2026 — a versão original desta linha dizia que o índice
-- era sobre `lower(email)` "porque é assim que o login compara". Não era: o
-- login consultava `.eq("email", body.email)` com o valor CRU do formulário.
-- Quem digitasse "Ana@X.com" não casava com nada e levava 401 "E-mail ou senha
-- incorretos" — a mensagem manda trocar a senha por causa de uma maiúscula.
--
-- Pior, isso torna o UPDATE abaixo capaz de trancar gente para fora: uma linha
-- "Fulano@x.com" vira "fulano@x.com", e quem entrava digitando com maiúscula
-- deixa de entrar. Em 16/08 não havia divergência de caixa em produção, então
-- não aconteceu — sorte medida, não desenho.
--
-- O login passou a normalizar antes de consultar (`main.login`, coberto por
-- `tests/test_login_email_normalizado.py`). A escolha do índice continua
-- certa; o que estava errado era a justificativa.
-- ==========================================================================

BEGIN;

-- Normaliza o que existe antes de criar a restrição. Em 16/08 não havia
-- divergência de caixa nem duplicata em produção; isto é para bases que já
-- tenham derivado.
UPDATE public.users
   SET email = lower(trim(email))
 WHERE email IS DISTINCT FROM lower(trim(email));

CREATE UNIQUE INDEX IF NOT EXISTS users_email_unico_idx
    ON public.users (lower(email));

COMMENT ON INDEX public.users_email_unico_idx IS
    'E-mail identifica a pessoa no login e em _resolve_user_id. Duplicata tornava uma das contas inacessível e desviava carteira e trilha para a errada.';

COMMIT;
