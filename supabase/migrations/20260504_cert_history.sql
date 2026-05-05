-- =============================================================================
-- Migração: tabela materializada cert_history
-- Execute no SQL Editor do Supabase (Project → SQL → New query)
-- =============================================================================
--
-- Objetivo: manter UMA linha por certificado (file_name único) com os dados
-- mais recentes. O endpoint /api/ingest faz UPSERT nesta tabela a cada scan,
-- tornando o /api/certificados/historico uma simples SELECT sem processamento.
--
-- Antes: API buscava N snapshots inteiros → Python deduplicava → ~3-8s
-- Depois: API lê cert_history diretamente                      → <200ms

create table if not exists public.cert_history (
  file_name             text        primary key,          -- chave de deduplicação
  machine_id            text        not null default 'default',
  nome                  text,
  documento             text,                              -- CNPJ/CPF formatado
  documento_numero      text,                              -- só dígitos
  status_ultimo         text,
  vencimento_certificado timestamptz,                     -- not_after do cert
  ultima_data_registrada timestamptz not null,            -- scanned_at do snapshot
  updated_at            timestamptz not null default now()
);

-- Índices para as queries mais comuns
create index if not exists cert_history_status_idx
  on public.cert_history (status_ultimo);

create index if not exists cert_history_vencimento_idx
  on public.cert_history (vencimento_certificado);

create index if not exists cert_history_ultima_data_idx
  on public.cert_history (ultima_data_registrada desc);
