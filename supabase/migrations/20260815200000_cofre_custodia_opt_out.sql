-- ==========================================================================
-- Custódia do cofre: opt-in vira opt-out
--
-- Até aqui nada ia para o cofre sem autorização explícita, e o resultado era
-- 33 de 560 certificados guardados -- 6% do acervo instalável pelo portal.
-- O modelo definido pelo cliente em 15/08 inverte: todo certificado válido
-- entra por padrão, e o admin desativa pontualmente.
--
-- Esta tabela é a lista de EXCEÇÕES. Vazia significa "tudo entra", que é o
-- estado inicial pretendido.
--
-- `cert_vault_optin` NÃO é apagada: as 34 linhas dela são registro de quem
-- autorizou o quê, e continuam valendo como trilha. Ela deixa de participar
-- da decisão de custódia -- ver o COMMENT no fim.
--
-- Ver docs/PLANO_reorganizacao_portal.md §3.2
-- ==========================================================================

BEGIN;

CREATE TABLE IF NOT EXISTS public.cert_vault_bloqueio (
    machine_id     TEXT        NOT NULL,
    fingerprint    CHAR(64)    NOT NULL,
    motivo         TEXT,                             -- por que saiu, para a trilha
    bloqueado_por  TEXT        NOT NULL,             -- e-mail do admin
    bloqueado_em   TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Mesma identidade do cofre desde a chave composta de 15/08: o bloqueio é
    -- "este certificado, nesta estação". Desativar a custódia numa máquina não
    -- pode alcançar as outras que têm o mesmo certificado.
    PRIMARY KEY (machine_id, fingerprint)
);

CREATE INDEX IF NOT EXISTS cert_vault_bloqueio_machine_idx
    ON public.cert_vault_bloqueio (machine_id);

COMMENT ON TABLE public.cert_vault_bloqueio IS
    'Exceções à custódia. Vazia = todo certificado válido vai ao cofre. O agente recebe o inventário MENOS estas linhas.';

COMMENT ON COLUMN public.cert_vault_bloqueio.motivo IS
    'Texto livre do admin. A ausência não impede o bloqueio -- exigir justificativa faria o campo virar ponto.';

-- Row Level Security no mesmo padrão das demais tabelas do módulo: a aplicação
-- fala pelo service_role, então isto é barreira contra acesso direto com a
-- chave anônima, não contra a própria aplicação.
ALTER TABLE public.cert_vault_bloqueio ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "service_role_acesso_total_cert_vault_bloqueio"
    ON public.cert_vault_bloqueio;

CREATE POLICY "service_role_acesso_total_cert_vault_bloqueio"
    ON public.cert_vault_bloqueio
    FOR ALL
    USING (auth.role() = 'service_role')
    WITH CHECK (auth.role() = 'service_role');

COMMENT ON TABLE public.cert_vault_optin IS
    'LEGADO (até 15/08/2026): lista de autorizações do modelo opt-in. Mantida como trilha de quem autorizou o quê; não participa mais da decisão de custódia, que agora é opt-out via cert_vault_bloqueio.';

COMMIT;
