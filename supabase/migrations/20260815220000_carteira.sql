-- ==========================================================================
-- Carteira: quais clientes cada operador pode instalar
--
-- Modelo definido pelo cliente em 15/08: o gestor define as carteiras de quem
-- pode instalar. A custódia (o PFX ir ao cofre) já é opt-out e é decisão do
-- admin; isto é a outra metade — o ACESSO, que é opt-in e fecha por padrão.
--
-- Granularidade documento (CNPJ/CPF), como já é em colaborador_cert_selecoes
-- para alertas. O universo atual é de 488 documentos distintos.
--
-- Ver docs/PLANO_reorganizacao_portal.md §3.3
-- ==========================================================================

BEGIN;

CREATE TABLE IF NOT EXISTS public.carteira (
    user_id              UUID        NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    documento            TEXT        NOT NULL,   -- só dígitos, como cert_pfx_store.documento

    -- A trilha não é enfeite. Com o gestor podendo atribuir QUALQUER cliente do
    -- acervo (decisão de 15/08), reconstruir quem deu acesso a quê é a única
    -- forma de entender o estrago se uma conta de gestor for comprometida.
    atribuido_por        UUID        REFERENCES public.users(id) ON DELETE SET NULL,
    -- O e-mail é redundante de propósito: se a conta de quem atribuiu for
    -- apagada, o UUID vira NULL e a trilha ficaria sem responsável. O texto
    -- sobrevive à exclusão, que é justamente quando a trilha importa mais.
    atribuido_por_email  TEXT        NOT NULL,
    atribuido_em         TIMESTAMPTZ NOT NULL DEFAULT now(),

    PRIMARY KEY (user_id, documento)
);

CREATE INDEX IF NOT EXISTS carteira_user_idx ON public.carteira (user_id);
CREATE INDEX IF NOT EXISTS carteira_documento_idx ON public.carteira (documento);

COMMENT ON TABLE public.carteira IS
    'Documentos que cada operador pode instalar. Ausência de linha = sem acesso: o acesso fecha por padrão, ao contrário da custódia, que abre.';

COMMENT ON COLUMN public.carteira.documento IS
    'CNPJ/CPF só com dígitos. Mesmo formato de cert_pfx_store.documento -- divergir aqui faria a carteira nunca casar, em silêncio.';

ALTER TABLE public.carteira ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "service_role_acesso_total_carteira" ON public.carteira;

CREATE POLICY "service_role_acesso_total_carteira"
    ON public.carteira
    FOR ALL
    USING (auth.role() = 'service_role')
    WITH CHECK (auth.role() = 'service_role');

COMMIT;
