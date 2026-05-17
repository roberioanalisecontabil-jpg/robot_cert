-- Habilitar RLS em todas as tabelas (Privacy by Design / LGPD)
ALTER TABLE public.portal_settings ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.cert_snapshots ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.agent_command_queue ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.colaborador_cert_selecoes ENABLE ROW LEVEL SECURITY;

-- Políticas explícitas: Bloquear totalmente acessos anônimos e autenticados (frontend direto).
-- Apenas o backend em Python usando a chave service_role terá acesso aos dados, 
-- garantindo que todas as regras de negócio e logs passem pela API do FastAPI.

-- Remover permissões caso existam (opcional, para garantir)
REVOKE ALL ON public.portal_settings FROM anon, authenticated;
REVOKE ALL ON public.cert_snapshots FROM anon, authenticated;
REVOKE ALL ON public.agent_command_queue FROM anon, authenticated;
REVOKE ALL ON public.colaborador_cert_selecoes FROM anon, authenticated;

-- A service_role não precisa de políticas porque ela bypassa o RLS por padrão.
-- Se, por ventura, RLS for forçado (force_row_security), criamos uma política liberando tudo para o service_role:

CREATE POLICY "service_role_acesso_total_portal_settings"
  ON public.portal_settings
  FOR ALL
  TO service_role
  USING (true)
  WITH CHECK (true);

CREATE POLICY "service_role_acesso_total_cert_snapshots"
  ON public.cert_snapshots
  FOR ALL
  TO service_role
  USING (true)
  WITH CHECK (true);

CREATE POLICY "service_role_acesso_total_agent_command_queue"
  ON public.agent_command_queue
  FOR ALL
  TO service_role
  USING (true)
  WITH CHECK (true);

CREATE POLICY "service_role_acesso_total_colaborador_cert_selecoes"
  ON public.colaborador_cert_selecoes
  FOR ALL
  TO service_role
  USING (true)
  WITH CHECK (true);
