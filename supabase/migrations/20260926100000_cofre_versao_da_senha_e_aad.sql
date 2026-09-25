-- Migration: cofre com versão da chave da SENHA e versão do ENVELOPE
-- (lote 8 da auditoria de 24/09/2026 — SECURITY_AUDIT #19, #42, #55)
--
-- Contexto.
--
--   #19  `key_version` existia só para o PFX. A senha (pfx_password_enc) era
--        cifrada sem versão e SEMPRE decifrada com CERT_PASSWORD_ENCRYPTION_KEY
--        corrente: trocar essa chave tornava todas as senhas do cofre ilegíveis,
--        e a rotação de emergência (após vazamento) virava perda operacional.
--   #55  O AES-GCM não levava dados associados: um ciphertext podia ser movido
--        para outra linha (outra máquina, outro fingerprint) sem a tag acusar.
--        A partir do lote 8 cada linha grava se foi cifrada com AAD
--        ("machine_id|fingerprint|key_version") ou no envelope antigo.
--
-- O que muda: duas colunas, ambas com DEFAULT que descreve EXATAMENTE o que
-- já está gravado — senha na versão 1 (a única que existiu) e envelope 0 (sem
-- AAD). Nenhuma linha é reescrita aqui; quem reprocessa o material é o botão
-- "Recifrar cofre" (POST /api/cert-installer/recifrar-cofre), depois do deploy,
-- linha a linha e só depois de decifrar com sucesso.
--
-- Ordem de implantação: rodar esta migration ANTES de subir o código do lote 8.
-- O código novo grava `password_key_version` e `aad_version` no upsert; sem as
-- colunas, o upsert do agente falharia. O código ANTIGO ignora as colunas
-- novas (DEFAULT), então a migration pode ir na frente sem janela.
--
-- Volta: `scripts/migracao_lote8_cofre.py --volta` recifra as linhas com AAD
-- de volta ao envelope antigo (o código anterior não sabe ler AAD) e remove as
-- colunas. Só DROP COLUMN não basta — ver o script.
--
-- Idempotente: pode ser rodada mais de uma vez.

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
            'Pré-requisito ausente: rode primeiro 20260803_cert_installer.sql, que cria cert_pfx_store.';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
         WHERE table_schema = 'public' AND table_name = 'cert_pfx_store' AND column_name = 'pfx_password_enc'
    ) THEN
        RAISE EXCEPTION
            'Pré-requisito ausente: rode primeiro 20260811000000_senha_pfx_chave_dedicada.sql (colunas da senha cifrada).';
    END IF;
END $$;

-- ─────────────────────────────────────────────────────────────────────────
-- 1. Versão da chave da senha (#19)
-- ─────────────────────────────────────────────────────────────────────────
ALTER TABLE public.cert_pfx_store
    ADD COLUMN IF NOT EXISTS password_key_version INTEGER NOT NULL DEFAULT 1;

COMMENT ON COLUMN public.cert_pfx_store.password_key_version IS
    'Versão da CERT_PASSWORD_ENCRYPTION_KEY que cifrou pfx_password_enc. 1 = tudo o que existia antes do lote 8. Permite rotacionar a chave da senha sem perder o cofre.';

-- ─────────────────────────────────────────────────────────────────────────
-- 2. Versão do envelope (#55)
-- ─────────────────────────────────────────────────────────────────────────
ALTER TABLE public.cert_pfx_store
    ADD COLUMN IF NOT EXISTS aad_version INTEGER NOT NULL DEFAULT 0;

COMMENT ON COLUMN public.cert_pfx_store.aad_version IS
    '0 = AES-GCM sem dados associados (envelope anterior ao lote 8); 1 = AAD machine_id|fingerprint|key_version (e ...|senha|password_key_version para a senha). Linhas em 0 são aceitas enquanto COFRE_EXIGE_AAD estiver desligada; "Recifrar cofre" as leva a 1.';

-- ─────────────────────────────────────────────────────────────────────────
-- 3. Conferência (o que a migration NÃO muda)
-- ─────────────────────────────────────────────────────────────────────────
-- Depois de rodar, tudo deve estar assim — é o estado que o código novo lê
-- como "legado, ainda aceito":
--   SELECT count(*) FILTER (WHERE password_key_version = 1),
--          count(*) FILTER (WHERE aad_version = 0),
--          count(*)
--     FROM public.cert_pfx_store;
-- Os três números têm de ser iguais.
