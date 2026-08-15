-- ==========================================================================
-- portal_settings: três configurações do módulo instalador
--
-- Leva 3b da etapa 3 (docs/PLANO_reorganizacao_portal.md §4, pontos 2, 5 e 7).
-- Os três valores estavam fixos no código, e cada um tem um trade-off que só
-- quem administra o portal sabe resolver.
-- ==========================================================================

BEGIN;

-- Ponto 2 — nome do arquivo baixado.
--
-- O `{token}` é FUNCIONAL, não decorativo: o instalador o lê do próprio
-- argv[0]. Um template sem ele quebra toda instalação, e o sintoma aparece na
-- máquina do usuário final. A validação está em cert_installer.validar_template
-- e recusa salvar sem o marcador.
ALTER TABLE public.portal_settings
    ADD COLUMN IF NOT EXISTS instalador_nome_template TEXT NOT NULL DEFAULT '';

COMMENT ON COLUMN public.portal_settings.instalador_nome_template IS
    'Template do nome do .exe baixado. Vazio = padrão do código. Precisa conter {token}: o instalador lê o token do próprio nome do arquivo.';

-- Ponto 5 — validade do token de instalação.
--
-- Zero significa "usar o padrão do ambiente" (CERT_INSTALL_TOKEN_TTL_MIN).
-- O trade-off vai na tela: curto demais e o usuário perde a janela e volta a
-- pedir; longo demais e o link fica vivo numa caixa de e-mail.
ALTER TABLE public.portal_settings
    ADD COLUMN IF NOT EXISTS install_token_ttl_min INTEGER NOT NULL DEFAULT 0;

COMMENT ON COLUMN public.portal_settings.install_token_ttl_min IS
    'Minutos de validade do token de instalação. 0 = usar CERT_INSTALL_TOKEN_TTL_MIN do ambiente.';

-- Ponto 7 — retenção do log de instalação (LGPD).
--
-- install_log guarda client_ip e user_email e não tinha política de expurgo:
-- crescia para sempre com dado pessoal. Zero mantém o comportamento atual
-- (guardar tudo), de propósito — ligar expurgo é decisão de quem responde
-- pelos dados, não default de migration.
ALTER TABLE public.portal_settings
    ADD COLUMN IF NOT EXISTS install_log_retencao_dias INTEGER NOT NULL DEFAULT 0;

COMMENT ON COLUMN public.portal_settings.install_log_retencao_dias IS
    'Dias de retenção de install_log. 0 = guardar indefinidamente. O expurgo roda no cron diário.';

COMMIT;
