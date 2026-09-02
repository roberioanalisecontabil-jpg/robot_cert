-- Pop atômico da fila de comandos do agente (item 14 da Frente 2 — R8).
--
-- ⚠️ RODAR ANTES DO DEPLOY. Sem a função nada quebra: `command_queue.py`
-- detecta a ausência e cai no SELECT+DELETE antigo, com aviso no log.
--
-- O problema que isto fecha: `_pop_from_supabase` fazia SELECT e depois
-- DELETE em duas idas. Dois consumidores do mesmo machine_id podiam ler a
-- MESMA linha antes de qualquer um apagá-la — e o comando executaria duas
-- vezes. Hoje há um agente só e a corrida não aparece; é exatamente a mina
-- que se desarma ANTES do dia em que houver dois.
--
-- `for update skip locked` é o desenho canônico de fila em Postgres: a
-- primeira transação tranca a linha, a concorrente PULA a linha trancada em
-- vez de esperar por ela, e cada comando sai exatamente uma vez.

create or replace function public.pop_agent_command(p_machine_id text)
returns setof public.agent_command_queue
language plpgsql
security definer
set search_path = public
as $$
declare
  linha public.agent_command_queue;
begin
  select * into linha
  from public.agent_command_queue
  where status = 'pending'
    -- Espelho de `_matches_agent` do command_queue.py: os curingas valem para
    -- qualquer estação. Divergir daqui faria o curinga funcionar só no
    -- caminho de fallback, e o sintoma seria "o rescan geral não chega".
    and (machine_id = p_machine_id or machine_id in ('*', 'all', 'qualquer'))
  order by created_at
  limit 1
  for update skip locked;

  if not found then
    return;
  end if;

  delete from public.agent_command_queue where id = linha.id;
  return next linha;
end;
$$;

comment on function public.pop_agent_command(text) is
  'Retira atomicamente o próximo comando pendente desta máquina (ou curinga). '
  'SELECT+DELETE numa transação com FOR UPDATE SKIP LOCKED: dois consumidores '
  'nunca levam o mesmo comando. Chamada por app/command_queue.py.';
