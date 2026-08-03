-- Migration: Módulo Instalador de Certificados Digitais
-- Cria tabelas para armazenamento seguro de PFX, tokens de instalação e auditoria.
-- Executar via SQL Editor do Supabase ou `supabase db push`.

-- 1. Armazenamento seguro dos PFX (cifrados em repouso com AES-256-GCM)
CREATE TABLE IF NOT EXISTS public.cert_pfx_store (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    fingerprint     CHAR(64) NOT NULL UNIQUE,           -- SHA-256 hex do certificado (deduplicação)
    machine_id      TEXT NOT NULL DEFAULT 'default',     -- máquina de origem do upload
    nome_titular    TEXT,
    documento       TEXT,                                -- CNPJ/CPF
    documento_tipo  TEXT,                                -- 'cnpj' | 'cpf' | NULL
    subject         TEXT,                                -- Subject do X.509
    not_before      TIMESTAMPTZ,
    not_after       TIMESTAMPTZ,
    friendly_name   TEXT,
    encrypted_pfx   TEXT NOT NULL,                       -- PFX cifrado, base64
    pfx_iv          TEXT NOT NULL,                       -- IV (nonce) AES-GCM, base64
    pfx_auth_tag    TEXT NOT NULL,                       -- Auth tag AES-GCM, base64
    pfx_password    TEXT,                                -- Senha do PFX (cifrada junto no bundle)
    uploaded_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS cert_pfx_store_machine_idx
    ON public.cert_pfx_store (machine_id);
CREATE INDEX IF NOT EXISTS cert_pfx_store_not_after_idx
    ON public.cert_pfx_store (not_after);

-- 2. Token de uso único para sessão de instalação
CREATE TABLE IF NOT EXISTS public.install_token (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    token_hash      CHAR(64) NOT NULL UNIQUE,           -- SHA-256 do token (nunca o token cru)
    user_id         UUID NOT NULL REFERENCES public.users(id),
    user_email      TEXT NOT NULL,
    target_machine  TEXT NOT NULL,                       -- machine_id do agente destino
    certificate_ids UUID[] NOT NULL,                     -- IDs de cert_pfx_store
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at      TIMESTAMPTZ NOT NULL,                -- created_at + 5 min
    consumed_at     TIMESTAMPTZ,                         -- NULL = ainda não usado
    client_ip       INET
);

CREATE INDEX IF NOT EXISTS install_token_expires_idx
    ON public.install_token (expires_at);
CREATE INDEX IF NOT EXISTS install_token_user_idx
    ON public.install_token (user_id);

-- 3. Trilha de auditoria: um registro por evento
CREATE TABLE IF NOT EXISTS public.install_log (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    token_id        UUID REFERENCES public.install_token(id),
    user_id         UUID NOT NULL REFERENCES public.users(id),
    user_email      TEXT,
    event           TEXT NOT NULL,                       -- 'SOLICITADO' | 'REDIMIDO' | 'CONCLUIDO' | 'ERRO'
    certificate_id  UUID,                                -- ref cert_pfx_store.id (NULL em eventos de sessão)
    fingerprint     CHAR(64),
    target_machine  TEXT,
    status          TEXT,                                -- 'OK' | 'FALHA'
    detail          TEXT,
    client_ip       INET,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS install_log_user_idx
    ON public.install_log (user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS install_log_token_idx
    ON public.install_log (token_id);

-- 4. Rotina de limpeza de tokens expirados (executar via cron ou manualmente)
-- DELETE FROM public.install_token WHERE expires_at < now() - interval '1 day';
