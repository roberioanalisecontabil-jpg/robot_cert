-- ==========================================================================
-- Cofre de certificados: identidade passa a ser (machine_id, fingerprint)
--
-- O fingerprint SHA-256 identifica O CERTIFICADO, não a instalação dele. Num
-- escritório contábil o mesmo A1 e-CNPJ costuma estar em várias estações — que
-- é exatamente o domínio deste projeto. Sob unicidade global do fingerprint,
-- autorizar o certificado X na estação B fazia o upsert sobrescrever a linha da
-- estação A, trocando o machine_id. Como listar_optin_fingerprints filtra por
-- machine_id, o agente de A simplesmente parava de receber X — sem erro, sem
-- log, sem mudança visível na tela de A.
--
-- Sem risco de perda: até aqui só podia existir uma linha por fingerprint, logo
-- toda linha existente já satisfaz a chave nova.
--
-- Ver docs/PLANO_chave_composta_cofre.md
-- ==========================================================================

BEGIN;

-- 1. cert_vault_optin: fingerprint era PRIMARY KEY
ALTER TABLE public.cert_vault_optin
    DROP CONSTRAINT IF EXISTS cert_vault_optin_pkey;

ALTER TABLE public.cert_vault_optin
    ADD CONSTRAINT cert_vault_optin_pkey
    PRIMARY KEY (machine_id, fingerprint);

-- 2. cert_pfx_store: fingerprint era UNIQUE; o PK (id UUID) continua
ALTER TABLE public.cert_pfx_store
    DROP CONSTRAINT IF EXISTS cert_pfx_store_fingerprint_key;

ALTER TABLE public.cert_pfx_store
    ADD CONSTRAINT cert_pfx_store_machine_fingerprint_key
    UNIQUE (machine_id, fingerprint);

COMMENT ON CONSTRAINT cert_pfx_store_machine_fingerprint_key
    ON public.cert_pfx_store IS
    'Um PFX por certificado POR ESTAÇÃO. O mesmo certificado em duas máquinas são duas linhas.';

COMMIT;
