-- Migration: senha do PFX volta ao cofre, sob chave DEDICADA
--
-- Contexto — por que uma decisão de 03/08 está sendo revertida em parte.
--
-- Em 20260803130000 a senha saiu do banco por dois motivos:
--
--   (a) estava cifrada com a MESMA chave do PFX, então um único vazamento de
--       chave entregava certificado e senha juntos;
--   (b) não havia perda: a senha vive no nome do arquivo no servidor de origem
--       ("nome senha VALOR.pfx"), e o agente a lia de lá ao instalar.
--
-- O motivo (b) caiu com o instalador avulso — o .exe que o usuário baixa do
-- portal e executa na PRÓPRIA máquina. Ali não existe pasta de origem, logo não
-- há de onde extrair a senha, e sem senha o certutil recusa todo PFX protegido
-- (que são todos). O modelo só funciona com a senha vindo do servidor.
--
-- O motivo (a) continua de pé, e é por isso que esta migration cria colunas
-- NOVAS em vez de reaproveitar `pfx_password`: o material passa a ser cifrado
-- com CERT_PASSWORD_ENCRYPTION_KEY, distinta de CERT_ENCRYPTION_KEY. A
-- aplicação recusa iniciar a operação se as duas forem iguais
-- (`cert_installer._get_password_key`), porque chaves iguais reproduziriam o
-- defeito original com outro nome.
--
-- ATENÇÃO ao operador: a separação só vale se as duas chaves estiverem em
-- lugares distintos. Ambas no mesmo .env do mesmo servidor tornam a proteção
-- nominal — quem obtiver o arquivo leva as duas.
--
-- Executar via SQL Editor do Supabase ou `supabase db push`.

-- ─────────────────────────────────────────────────────────────────────────
-- 0. Pré-requisitos
-- ─────────────────────────────────────────────────────────────────────────
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_tables
         WHERE schemaname = 'public' AND tablename = 'cert_pfx_store'
    ) THEN
        RAISE EXCEPTION
            'Pré-requisito ausente: rode primeiro 20260803_cert_installer.sql, que cria cert_pfx_store, install_token e install_log.';
    END IF;
END $$;

-- ─────────────────────────────────────────────────────────────────────────
-- 1. Colunas da senha cifrada (AES-256-GCM, chave dedicada)
-- ─────────────────────────────────────────────────────────────────────────
-- Três colunas porque o GCM produz três partes independentes: o texto cifrado,
-- o nonce e a tag de autenticação. Guardá-las concatenadas economizaria espaço
-- e custaria um parser — e um parser a mais é um lugar a mais para errar.
ALTER TABLE public.cert_pfx_store
    ADD COLUMN IF NOT EXISTS pfx_password_enc TEXT,
    ADD COLUMN IF NOT EXISTS pfx_password_iv  TEXT,
    ADD COLUMN IF NOT EXISTS pfx_password_tag TEXT;

COMMENT ON COLUMN public.cert_pfx_store.pfx_password_enc IS
    'Senha do PFX cifrada com AES-256-GCM sob CERT_PASSWORD_ENCRYPTION_KEY (distinta da chave do PFX). Base64.';
COMMENT ON COLUMN public.cert_pfx_store.pfx_password_iv IS
    'Nonce de 12 bytes do AES-GCM da senha. Base64.';
COMMENT ON COLUMN public.cert_pfx_store.pfx_password_tag IS
    'Tag de autenticação de 16 bytes do AES-GCM da senha. Base64.';

-- ─────────────────────────────────────────────────────────────────────────
-- 2. A coluna antiga segue descontinuada
-- ─────────────────────────────────────────────────────────────────────────
-- Não é a mesma coisa que as colunas novas: `pfx_password` guardava a senha sob
-- a chave do PFX. Continua nula e sem uso. Mantida em vez de removida porque
-- DROP COLUMN em produção é irreversível e não há ganho em correr esse risco —
-- a aplicação já grava NULL nela explicitamente.
UPDATE public.cert_pfx_store SET pfx_password = NULL WHERE pfx_password IS NOT NULL;

COMMENT ON COLUMN public.cert_pfx_store.pfx_password IS
    'DESCONTINUADO — mantido nulo. Guardava a senha sob a chave do PFX (defeito corrigido em 03/08). A senha em uso está em pfx_password_enc, sob chave dedicada.';

-- ─────────────────────────────────────────────────────────────────────────
-- 3. Registros anteriores a esta migration
-- ─────────────────────────────────────────────────────────────────────────
-- Ficam com as colunas novas nulas, e é o comportamento correto: não há como
-- recuperar a senha que nunca foi guardada. O bundle sai com pfxPassword nulo,
-- o agente ainda resolve pelo nome do arquivo local, e o instalador avulso
-- falha com causa nomeada ("senha ausente no cofre") em vez de erro de
-- certutil. Para preencher, basta o agente reenviar o PFX em um novo ciclo.
