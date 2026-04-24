-- Execute no SQL Editor do Supabase (Project -> SQL -> New query).
-- Guarde a URL do projeto e a "service_role" (Settings -> API) no .env do servidor FastAPI
-- nunca no browser nem no agente (o agente usa só a chave do seu próprio cert_robot, ver API_KEY).

create table if not exists public.portal_settings (
  id smallint primary key default 1,
  source_folder text not null default '',
  expired_folder text not null default '',
  machine_id text not null default 'default',
  updated_at timestamptz not null default now()
);

insert into public.portal_settings (id, source_folder, expired_folder, machine_id)
values (1, '', '', 'default')
on conflict (id) do nothing;

create table if not exists public.cert_snapshots (
  id uuid primary key default gen_random_uuid(),
  machine_id text not null default 'default',
  source_folder text,
  expired_folder text,
  scanned_at timestamptz not null default now(),
  items jsonb not null default '[]'::jsonb
);

create index if not exists cert_snapshots_scanned_at_idx
  on public.cert_snapshots (scanned_at desc);

-- Fila de comandos enviada pelo portal para o agente (poll em GET /api/agent/next)
create table if not exists public.agent_command_queue (
  id uuid primary key,
  machine_id text not null,
  command text not null,
  status text not null default 'pending',
  created_at timestamptz not null default now()
);

create index if not exists agent_cmd_pending_idx
  on public.agent_command_queue (created_at) where (status = 'pending');
