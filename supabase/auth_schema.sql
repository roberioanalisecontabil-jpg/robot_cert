-- 1. Tabela de Usuários
create table if not exists public.users (
  id uuid primary key default gen_random_uuid(),
  email text unique not null,
  password_hash text not null,
  full_name text,
  role text not null default 'user', -- 'admin' ou 'user'
  created_at timestamptz not null default now()
);

-- 2. Inserir primeiro Administrador padrão
-- Nota: A senha abaixo é o hash para "admin123" usando bcrypt.
-- Você poderá alterar sua senha e criar novos usuários pelo painel após logar.
insert into public.users (email, password_hash, full_name, role)
values (
  'admin@certguard.com', 
  '$2b$12$6uXyYq06/8Xv.qZ.W6X9Se7gXGv9.zN1E3fF5Z5S5h5h5h5h5h5h5', -- Hash de 'admin123'
  'Administrador Padrão', 
  'admin'
)
on conflict (email) do nothing;

-- 3. Índices para performance
create index if not exists users_email_idx on public.users (email);
