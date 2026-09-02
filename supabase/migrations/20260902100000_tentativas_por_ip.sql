-- Rate limit durável: a janela de tentativas sai da memória da instância.
--
-- ⚠️ RODAR ANTES DO DEPLOY do item 13 (Frente 2 — R5). Sem a tabela nada
-- quebra: `app/taxa.py` cai na janela em memória (o comportamento antigo) e
-- avisa no log.
--
-- O problema que isto fecha: na Vercel cada instância tem sua memória, então
-- o teto de "10 tentativas por minuto" do /claim valia POR INSTÂNCIA — o
-- limite real era 10 × quantas instâncias a plataforma subisse. Uma tabela
-- pequena, compartilhada, faz o teto significar o que promete.
--
-- Cada tentativa é uma linha; permitir é contar as linhas da chave na janela.
-- A poda é oportunista (na própria chave, a cada chamada), então o tamanho da
-- tabela é limitado por (chaves ativas × máximo da janela) — dezenas de
-- linhas, não milhares.

create table if not exists public.rate_limit_tentativas (
  id bigint generated always as identity primary key,
  chave text not null,
  quando timestamptz not null default now()
);

-- O caminho quente: contar as tentativas de UMA chave dentro da janela, e
-- podar as antigas da mesma chave.
create index if not exists rate_limit_tentativas_chave_quando
  on public.rate_limit_tentativas (chave, quando);

alter table public.rate_limit_tentativas enable row level security;
-- Sem políticas: só a service key (que ignora RLS) escreve e lê. O front
-- nunca toca nesta tabela.

comment on table public.rate_limit_tentativas is
  'Janela deslizante de rate limit, compartilhada entre as instâncias '
  'serverless. Uma linha por tentativa; a poda é oportunista por chave. '
  'Ver app/taxa.py.';
