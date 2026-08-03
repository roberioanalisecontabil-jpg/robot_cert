-- Migration: RLS para as tabelas do Módulo Instalador de Certificados
--
-- A migration 20260803_cert_installer.sql criou cert_pfx_store, install_token e
-- install_log sem RLS. Isso destoa do resto do projeto: a migration
-- 20260517193000_rls_lgpd.sql protege as 4 tabelas anteriores com o mesmo padrão
-- (bloquear anon/authenticated, liberar apenas service_role).
--
-- É a lacuna mais séria das três tabelas porque cert_pfx_store guarda o material
-- mais sensível do sistema: os PFX cifrados E as senhas deles. Hoje o backend
-- acessa com SUPABASE_SERVICE_KEY, que ignora RLS — mas qualquer caminho futuro
-- com a chave anon (front-end direto, integração, Supabase Studio com token de
-- usuário) leria a tabela inteira.
--
-- Executar via SQL Editor do Supabase ou `supabase db push`.

-- 0. Pré-requisito: as tabelas precisam existir.
--    Sem esta verificação, rodar fora de ordem devolve apenas
--    "42P01: relation public.cert_pfx_store does not exist", que não diz o que fazer.
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

-- 1. Habilitar RLS
ALTER TABLE public.cert_pfx_store  ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.install_token   ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.install_log     ENABLE ROW LEVEL SECURITY;

-- 2. Revogar acesso direto de anon/authenticated.
--    Todo acesso precisa passar pela API FastAPI, que é onde vivem as regras de
--    autorização e a gravação da trilha de auditoria.
REVOKE ALL ON public.cert_pfx_store FROM anon, authenticated;
REVOKE ALL ON public.install_token  FROM anon, authenticated;
REVOKE ALL ON public.install_log    FROM anon, authenticated;

-- 3. Políticas explícitas para service_role.
--    A service_role já bypassa RLS por padrão; estas políticas existem para o
--    caso de force_row_security ser habilitado — mesmo racional da migration LGPD.
CREATE POLICY "service_role_acesso_total_cert_pfx_store"
  ON public.cert_pfx_store
  FOR ALL
  TO service_role
  USING (true)
  WITH CHECK (true);

CREATE POLICY "service_role_acesso_total_install_token"
  ON public.install_token
  FOR ALL
  TO service_role
  USING (true)
  WITH CHECK (true);

CREATE POLICY "service_role_acesso_total_install_log"
  ON public.install_log
  FOR ALL
  TO service_role
  USING (true)
  WITH CHECK (true);

-- 4. Verificação — deve retornar rowsecurity = true nas três.
-- SELECT tablename, rowsecurity
--   FROM pg_tables
--  WHERE schemaname = 'public'
--    AND tablename IN ('cert_pfx_store', 'install_token', 'install_log');
