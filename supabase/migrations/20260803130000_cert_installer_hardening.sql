-- Migration: endurecimento do Módulo Instalador de Certificados
--
-- Três mudanças de schema decididas na revisão:
--
-- 1. cert_vault_optin — o agente enviava TODOS os certificados lidos ao cofre,
--    a cada ciclo de scan. Numa base de 1.028 certificados isso significa 1.028
--    chaves privadas e senhas copiadas para o Supabase sem ninguém ter decidido.
--    Passa a ser opt-in explícito, por fingerprint.
--
-- 2. cert_pfx_store.key_version — sem versão de chave, rotacionar
--    CERT_ENCRYPTION_KEY obriga a recifrar tudo de uma vez, sem transição.
--    Custa uma coluna agora; retrofit depois custa uma janela de manutenção.
--
-- 3. agent_command_queue.payload — o token de instalação era gerado e nunca
--    entregue ao agente (enqueue_install_command recebia token_raw e não
--    gravava; /api/agent/next não tinha campo para carregá-lo). Sem isto o
--    fluxo de instalação nunca completa.
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

    IF NOT EXISTS (
        SELECT 1 FROM pg_tables
         WHERE schemaname = 'public' AND tablename = 'agent_command_queue'
    ) THEN
        RAISE EXCEPTION
            'Pré-requisito ausente: agent_command_queue não existe. Rode 20260423000000_init_portal_certs_queue.sql.';
    END IF;
END $$;

-- ─────────────────────────────────────────────────────────────────────────
-- 1. Opt-in do cofre
-- ─────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.cert_vault_optin (
    fingerprint   CHAR(64)    PRIMARY KEY,        -- SHA-256 do certificado
    machine_id    TEXT        NOT NULL DEFAULT 'default',
    nome_titular  TEXT,                            -- cópia para exibição/auditoria
    documento     TEXT,
    enabled_by    TEXT        NOT NULL,            -- e-mail do admin que autorizou
    enabled_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS cert_vault_optin_machine_idx
    ON public.cert_vault_optin (machine_id);

COMMENT ON TABLE public.cert_vault_optin IS
    'Certificados autorizados a ter o PFX armazenado no cofre. O agente só envia os que constam aqui.';

-- ─────────────────────────────────────────────────────────────────────────
-- 2. Versão da chave de cifragem em repouso
-- ─────────────────────────────────────────────────────────────────────────
ALTER TABLE public.cert_pfx_store
    ADD COLUMN IF NOT EXISTS key_version INTEGER NOT NULL DEFAULT 1;

COMMENT ON COLUMN public.cert_pfx_store.key_version IS
    'Versão da CERT_ENCRYPTION_KEY usada. Permite rotação incremental sem recifrar tudo de uma vez.';

-- A senha do PFX deixa de ser armazenada: ela já vive no nome do arquivo no
-- servidor de origem (padrão "nome senha VALOR.pfx"), e guardá-la cifrada com a
-- MESMA chave do PFX fazia com que um único vazamento de chave entregasse os
-- dois. O agente passa a lê-la do nome do arquivo no momento da instalação.
UPDATE public.cert_pfx_store SET pfx_password = NULL WHERE pfx_password IS NOT NULL;

COMMENT ON COLUMN public.cert_pfx_store.pfx_password IS
    'DESCONTINUADO — mantido nulo. A senha vem do nome do arquivo no agente.';

-- ─────────────────────────────────────────────────────────────────────────
-- 3. Payload dos comandos do agente (carrega o token de instalação)
-- ─────────────────────────────────────────────────────────────────────────
ALTER TABLE public.agent_command_queue
    ADD COLUMN IF NOT EXISTS payload TEXT;

COMMENT ON COLUMN public.agent_command_queue.payload IS
    'Dado extra do comando. Em instalar_certificados carrega o token de uso único (TTL 5 min); a linha é removida ao ser consumida pelo agente.';

-- ─────────────────────────────────────────────────────────────────────────
-- 4. RLS da tabela nova (mesmo padrão das demais)
-- ─────────────────────────────────────────────────────────────────────────
ALTER TABLE public.cert_vault_optin ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.cert_vault_optin FROM anon, authenticated;

CREATE POLICY "service_role_acesso_total_cert_vault_optin"
  ON public.cert_vault_optin
  FOR ALL
  TO service_role
  USING (true)
  WITH CHECK (true);
