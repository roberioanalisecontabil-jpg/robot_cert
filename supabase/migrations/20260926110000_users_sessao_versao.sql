-- Migration: versao da sessao por conta (lote 9 da auditoria de 24/09/2026,
-- SECURITY_AUDIT #23)
--
-- Ate aqui "Sair" so limpava o navegador: um JWT copiado valia ate o `exp`.
-- Agora o login grava a versao da sessao no token (`sv`) e POST /api/logout
-- incrementa esta coluna; `_sessao_do_token` recusa todo token de versao
-- diferente. E a sessao inteira da conta que se encerra ("sair em todos os
-- dispositivos"), o que uma coluna consegue sem tabela de revogados.
--
-- DEFAULT 0 e NOT NULL: e o valor que um token SEM o claim (emitido antes do
-- deploy) assume, entao ninguem e deslogado pela migration nem pelo deploy.
-- Codigo antigo ignora a coluna. Codigo novo sem a coluna faz o login e a
-- sessao falharem (o select pede a coluna) -- rode esta migration ANTES do
-- deploy do lote 9.
--
-- Volta: ALTER TABLE public.users DROP COLUMN IF EXISTS sessao_versao;
--        (so depois de voltar o codigo, pelo mesmo motivo acima)
--
-- Idempotente.

ALTER TABLE public.users
    ADD COLUMN IF NOT EXISTS sessao_versao INTEGER NOT NULL DEFAULT 0;

COMMENT ON COLUMN public.users.sessao_versao IS
    'Versao da sessao da conta. O JWT carrega a versao com que nasceu (claim sv); /api/logout incrementa aqui e todo token da versao anterior passa a ser recusado.';

-- Conferencia esperada: uma linha, integer, NO, 0.
-- SELECT column_name, data_type, is_nullable, column_default
--   FROM information_schema.columns
--  WHERE table_name = 'users' AND column_name = 'sessao_versao';
