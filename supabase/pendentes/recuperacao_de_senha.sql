-- ==========================================================================
-- Recuperação de senha por CÓDIGO (A8 da auditoria de UI/UX)
-- Projeto Supabase: wubokujetyaolnjxiiid
--
-- COMO USAR: rode um PASSO de cada vez. Se algum der erro, PARE e me mande a
-- mensagem exata. Sem BEGIN/COMMIT -- o SQL Editor ja roda numa transacao.
--
-- ADITIVA: cria uma tabela nova e uma coluna nova; nada existente e alterado.
--
-- >>> ESTA MIGRATION TEM DE RODAR ANTES DO DEPLOY DO CODIGO. <<<
--     O commit 3b165a8 faz `_conta_da_sessao` pedir `senha_alterada_em` no
--     select. Se o codigo subir antes da coluna existir, o PostgREST recusa a
--     consulta e TODA REQUISICAO AUTENTICADA VIRA 503 -- o portal inteiro
--     para. Por isso o push esta segurado ate o passo 5 voltar.
--
--     Rodar esta migration ANTES do deploy nao quebra nada: o codigo que esta
--     em producao hoje nao conhece nem a tabela nem a coluna.
--
-- ── Codigo, e nao link ───────────────────────────────────────────────────
--
-- O e-mail leva um codigo de 6 digitos que a pessoa digita no portal, em vez
-- de um link clicavel. Isso ELIMINA uma classe inteira de ataque: um link
-- precisa de URL absoluta, e monta-la a partir do cabecalho `Host` -- que quem
-- chama controla -- permitiria pedir recuperacao para a vitima com um Host
-- forjado: ela receberia um e-mail legitimo do portal e entregaria o token ao
-- atacante ao clicar. Sem link, nao ha o que forjar.
--
-- ── O que de fato protege aqui ───────────────────────────────────────────
--
-- Seis digitos sao 1 milhao de combinacoes. Guardar o hash protege POUCO:
-- quem tivesse leitura desta tabela reverteria um sha256 de 6 digitos em
-- segundos. O hash entra como defesa em profundidade (impede leitura casual
-- pelo Studio), mas a seguranca real e a soma dos limites:
--
--   * validade curta        -> 15 minutos
--   * 3 tentativas erradas  -> o codigo QUEIMA, nao fica adivinhavel depois
--   * teto de pedidos       -> 3 por conta por hora
--   * pedir novo codigo     -> invalida os anteriores
--
-- O teto de pedidos e o que fecha o buraco: 3 tentativas por codigo nao
-- protegem nada se der para pedir mil codigos.
--
-- ── Por que codigo_hash NAO e UNIQUE ─────────────────────────────────────
--
-- Seis digitos nao sao unicos entre pessoas: duas podem receber 418290 ao
-- mesmo tempo. Um UNIQUE aqui faria o segundo pedido falhar por colisao.
-- Consequencia que o codigo respeita: a busca e SEMPRE escopada por conta
-- (user_id + codigo). Procurar so pelo codigo faria alguem digitar um numero
-- qualquer e cair na conta de outra pessoa.
--
-- ── senha_alterada_em ────────────────────────────────────────────────────
--
-- Trocar a senha, sozinho, NAO invalida um JWT ja emitido: ele e stateless e
-- vale ate expirar (24h). Quem redefine senha geralmente o faz porque suspeita
-- que alguem entrou -- e sem esta coluna esse alguem continuaria dentro por
-- ate um dia, exatamente enquanto o dono acredita ter resolvido.
-- ==========================================================================


-- ─────────────────────────────────────────────────────────────────────────
-- PASSO 1 — Diagnostico. Nao altera nada. Me mande os dois resultados.
--
-- 1a esperado: ZERO linhas (a tabela ainda nao existe).
-- 1b esperado: as colunas de `users` SEM `senha_alterada_em`.
-- ─────────────────────────────────────────────────────────────────────────

-- 1a
SELECT tablename FROM pg_tables
WHERE schemaname = 'public' AND tablename = 'password_reset_codigo';

-- 1b
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_schema = 'public' AND table_name = 'users'
ORDER BY ordinal_position;


-- ─────────────────────────────────────────────────────────────────────────
-- PASSO 2 — A tabela dos codigos.
--
-- `tentativas` mora na LINHA, no servidor. Se o limite fosse contado no
-- navegador ou na sessao, bastaria recarregar a pagina para zerar -- e o
-- limite de 3 seria decorativo.
--
-- `consumed_at` anulavel e o que torna o codigo de USO UNICO: o consumo e um
-- UPDATE com `consumed_at IS NULL` na propria clausula WHERE, entao dois
-- envios simultaneos nao passam os dois (o Postgres serializa UPDATEs na
-- mesma linha). Mesmo desenho ja usado em `install_token`.
--
-- `on delete cascade`: conta apagada leva junto os codigos dela. Codigo
-- pendente de conta removida nao pode virar caminho de volta.
-- ─────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS public.password_reset_codigo (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     uuid        NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    codigo_hash text        NOT NULL,
    tentativas  integer     NOT NULL DEFAULT 0,
    created_at  timestamptz NOT NULL DEFAULT now(),
    expires_at  timestamptz NOT NULL,
    consumed_at timestamptz,
    client_ip   text
);

COMMENT ON TABLE public.password_reset_codigo IS
    'Codigos de redefinicao de senha, de 6 digitos e 15 minutos. O hash e defesa em profundidade, nao a garantia: 6 digitos sao reversiveis. O que protege sao validade curta, 3 tentativas e teto de 3 pedidos por hora.';

COMMENT ON COLUMN public.password_reset_codigo.codigo_hash IS
    'sha256 do codigo. NAO e UNIQUE de proposito: 6 digitos colidem entre pessoas. A busca tem de ser sempre escopada por user_id.';

COMMENT ON COLUMN public.password_reset_codigo.tentativas IS
    'Erros ja cometidos neste codigo. Mora no servidor porque contador no cliente se zera recarregando a pagina.';

-- Serve as duas consultas quentes: achar o codigo vigente da pessoa, e contar
-- quantos pedidos ela fez na ultima hora.
CREATE INDEX IF NOT EXISTS password_reset_codigo_user_criado_idx
    ON public.password_reset_codigo (user_id, created_at DESC);

-- Para a limpeza periodica dos expirados nao varrer a tabela inteira.
CREATE INDEX IF NOT EXISTS password_reset_codigo_expires_idx
    ON public.password_reset_codigo (expires_at);


-- ─────────────────────────────────────────────────────────────────────────
-- PASSO 3 — RLS, no mesmo padrao das outras tabelas.
--
-- O backend fala com SUPABASE_SERVICE_KEY, que ignora RLS -- entao isto nao
-- muda o funcionamento hoje. Existe porque qualquer caminho futuro com a
-- chave anon (front-end direto, integracao, Studio com token de usuario)
-- leria a tabela inteira. E aqui "a tabela inteira" e a lista de codigos de
-- redefinicao de senha vigentes.
-- ─────────────────────────────────────────────────────────────────────────

ALTER TABLE public.password_reset_codigo ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON public.password_reset_codigo FROM anon, authenticated;

DROP POLICY IF EXISTS "service_role_acesso_total_password_reset_codigo"
    ON public.password_reset_codigo;

CREATE POLICY "service_role_acesso_total_password_reset_codigo"
    ON public.password_reset_codigo
    FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);


-- ─────────────────────────────────────────────────────────────────────────
-- PASSO 4 — A coluna que derruba sessao aberta.
--
-- ANULAVEL de proposito: linha antiga fica NULL, e NULL significa "nunca
-- trocou", que e verdade. O codigo trata ausencia como "nao ha nada a
-- invalidar" e deixa o token valer -- ninguem e deslogado pelo deploy.
-- ─────────────────────────────────────────────────────────────────────────

ALTER TABLE public.users
    ADD COLUMN IF NOT EXISTS senha_alterada_em timestamptz;

COMMENT ON COLUMN public.users.senha_alterada_em IS
    'Instante da ultima troca de senha. require_auth recusa JWT emitido antes disto: trocar a senha passa a derrubar a sessao aberta, que e o que a pessoa espera ao redefinir por suspeita de invasao.';


-- ─────────────────────────────────────────────────────────────────────────
-- PASSO 5 — Verificacao. Me mande os tres resultados.
--
-- 5a esperado: 8 colunas -- id, user_id, codigo_hash, tentativas, created_at,
--    expires_at, consumed_at, client_ip. `tentativas` com is_nullable = NO.
-- 5b esperado: UMA linha -- senha_alterada_em, timestamptz, YES.
-- 5c esperado: rowsecurity = true.
-- ─────────────────────────────────────────────────────────────────────────

-- 5a
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_schema = 'public' AND table_name = 'password_reset_codigo'
ORDER BY ordinal_position;

-- 5b
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_schema = 'public' AND table_name = 'users'
  AND column_name = 'senha_alterada_em';

-- 5c
SELECT tablename, rowsecurity
FROM pg_tables
WHERE schemaname = 'public' AND tablename = 'password_reset_codigo';
