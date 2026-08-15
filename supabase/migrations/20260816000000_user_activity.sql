-- ==========================================================================
-- user_activity: quem está usando o portal, e quem travou
--
-- Etapa 4b. É a contraproposta ao pedido "tempo de uso do portal por usuário"
-- (docs/PLANO_reorganizacao_portal.md §0.1 e §5.3).
--
-- NÃO é um cronômetro, e é de propósito. A tarefa do usuário final dura menos
-- de um minuto: entrar, achar o certificado, baixar o .exe. Sessão longa aqui
-- não significa engajamento -- significa que a pessoa não achou o que queria.
-- Otimizar para o número subir seria otimizar para a ferramenta piorar.
--
-- A pergunta real -- quem está usando e quem travou -- responde-se com eventos
-- discretos. Sem heartbeat, sem rastreio de navegação, sem tempo de sessão. O
-- que também mantém a coleta proporcional, e isso importa: é dado pessoal de
-- funcionário.
--
-- NÃO duplica install_log. Aquela já registra quem instalou o quê, quando e com
-- que desfecho; repetir os mesmos eventos aqui criaria duas fontes de verdade
-- sobre o mesmo fato. Esta guarda só o que não estava em lugar nenhum -- hoje,
-- os logins. O dashboard junta as duas na leitura.
-- ==========================================================================

BEGIN;

CREATE TABLE IF NOT EXISTS public.user_activity (
    id           UUID        PRIMARY KEY DEFAULT gen_random_uuid(),

    -- NULL quando a conta foi apagada depois: o evento continua valendo como
    -- registro do que aconteceu. Por isso o e-mail vai junto, redundante de
    -- propósito -- é o mesmo raciocínio da trilha da carteira.
    user_id      UUID        REFERENCES public.users(id) ON DELETE SET NULL,
    user_email   TEXT        NOT NULL,

    evento       TEXT        NOT NULL,
    client_ip    TEXT,
    contexto     JSONB       NOT NULL DEFAULT '{}'::jsonb,
    ocorrido_em  TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Vocabulário fechado no banco, e não só na aplicação: texto livre viraria
    -- uma sopa de grafias em três meses, e a agregação passaria a mentir por
    -- diferença de acento.
    CONSTRAINT user_activity_evento_valido
        CHECK (evento IN ('login', 'login_negado'))
);

-- Os dois eixos de leitura: "o que esta pessoa fez" e "o que houve no período".
CREATE INDEX IF NOT EXISTS user_activity_user_idx
    ON public.user_activity (user_id, ocorrido_em DESC);
CREATE INDEX IF NOT EXISTS user_activity_periodo_idx
    ON public.user_activity (ocorrido_em DESC);

COMMENT ON TABLE public.user_activity IS
    'Eventos discretos de uso do portal. Não é cronômetro: sem tempo de sessão, sem heartbeat, sem rastreio de navegação. Expurgada pela retenção da trilha.';

ALTER TABLE public.user_activity ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "service_role_acesso_total_user_activity" ON public.user_activity;

CREATE POLICY "service_role_acesso_total_user_activity"
    ON public.user_activity
    FOR ALL
    USING (auth.role() = 'service_role')
    WITH CHECK (auth.role() = 'service_role');


-- ─────────────────────────────────────────────────────────────────────────
-- Retenção: um ajuste para a trilha inteira
--
-- `install_log_retencao_dias` nasceu hoje de manhã cobrindo uma tabela só.
-- Com user_activity, passa a haver duas -- mesmo tipo de dado (quem fez o quê,
-- quando), mesma justificativa, mesmo prazo. Dois botões de retenção para a
-- mesma categoria seria convite a configurar um e esquecer o outro.
--
-- Renomeada agora, com quatro horas de vida e o valor 0 em toda parte, porque
-- nome que mente sai caro depois: `cert_history` neste mesmo projeto não é
-- histórico, e quem tentou usá-la como tal obteve zero.
-- ─────────────────────────────────────────────────────────────────────────
ALTER TABLE public.portal_settings
    ADD COLUMN IF NOT EXISTS trilha_retencao_dias INTEGER NOT NULL DEFAULT 0;

UPDATE public.portal_settings
   SET trilha_retencao_dias = COALESCE(install_log_retencao_dias, 0)
 WHERE trilha_retencao_dias = 0;

ALTER TABLE public.portal_settings
    DROP COLUMN IF EXISTS install_log_retencao_dias;

COMMENT ON COLUMN public.portal_settings.trilha_retencao_dias IS
    'Dias de retenção de install_log E user_activity. 0 = guardar indefinidamente. Expurgo no cron diário.';

COMMIT;
