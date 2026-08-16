-- ==========================================================================
-- Expurgo do cofre: a chave sai quando deixa de fazer sentido guardá-la
--
-- Até aqui a custódia só tinha metade da proteção. Certificado vencido não
-- ENTRA no cofre (filtro da etapa 2b), mas nada TIRAVA o que já estava lá
-- quando venceu — o cofre só crescia, e crescia em chave privada.
--
-- Confirmado em 16/08/2026: dois certificados vencidos em 15/08 continuavam
-- com a chave privada guardada.
--
-- Dois gatilhos, com riscos opostos:
--
--   1. VENCIDO — seguro. A data está na própria linha e não depende de mais
--      nada estar correto.
--
--   2. REMOVIDO DA PASTA — perigoso. Apagar por ausência no inventário
--      significa que uma varredura que falhe pela metade apagaria chaves em
--      massa. É a mesma armadilha de falha-aberta da etapa 2b, na direção
--      destrutiva. Daí esta coluna: em vez de apagar na primeira ausência,
--      marca-se quando a ausência começou e espera-se um prazo.
-- ==========================================================================

BEGIN;

ALTER TABLE public.cert_pfx_store
    ADD COLUMN IF NOT EXISTS ausente_desde TIMESTAMPTZ;

COMMENT ON COLUMN public.cert_pfx_store.ausente_desde IS
    'Quando o certificado deixou de aparecer no inventário da máquina. NULL = presente na última varredura. Zerada assim que ele reaparece; passado o prazo de carência, a linha é apagada.';

-- A varredura de expurgo lê exatamente por aqui: as linhas de uma máquina que
-- estão ausentes há mais tempo que a carência.
CREATE INDEX IF NOT EXISTS cert_pfx_store_ausente_idx
    ON public.cert_pfx_store (machine_id, ausente_desde)
    WHERE ausente_desde IS NOT NULL;

COMMIT;
