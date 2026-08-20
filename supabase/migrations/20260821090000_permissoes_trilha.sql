-- Histórico das mudanças de permissão.
--
-- ORDEM-INDEPENDENTE (conferido, não assumido): é tabela NOVA, e o `upsert` de
-- `permissoes` não passa a mandar campo nenhum a mais. O portal sem ela grava
-- permissão normalmente e só não registra o histórico.
--
-- POR QUE, se `permissoes` já tem `alterado_em` e `alterado_por`:
--
-- Aquelas duas colunas dizem quem mexeu POR ÚLTIMO naquela célula. Não dizem o
-- que havia antes, nem quantas vezes mudou. Conceder e revogar no mesmo dia
-- deixa a linha idêntica à de quem nunca mexeu — e é justamente a sequência
-- que uma auditoria de acesso precisa ver.
--
-- O comentário da migration de 20260820100000 já dizia que "uma tabela de
-- permissões sem rastro seria a única concessão sem histórico". As colunas de
-- lá foram a metade barata; esta é a outra.

create table if not exists public.permissoes_trilha (
    id           bigserial primary key,
    papel        text not null,
    modulo       text not null,

    -- O par (de, para) é o que torna a linha legível sozinha. Guardar só o
    -- valor novo obrigaria a reconstruir o estado anterior lendo a trilha
    -- inteira de trás para frente — e qualquer buraco no histórico
    -- inutilizaria a leitura.
    de           text not null,
    para         text not null,

    alterado_por text not null default '',
    em           timestamptz not null default now()
);

-- Sem constraint de valores em `de`/`para`, ao contrário de `permissoes`.
-- Deliberado: histórico registra o que ACONTECEU. Se um nível for renomeado ou
-- removido no futuro, um CHECK aqui recusaria gravar o passado — ou pior,
-- impediria a mudança de permissão por causa da linha de trilha.

-- A consulta é sempre "as últimas N, mais recentes primeiro".
create index if not exists permissoes_trilha_em_idx
    on public.permissoes_trilha (em desc);

alter table public.permissoes_trilha enable row level security;

-- Sem policy: o portal acessa com a service key. RLS ligada e sem policy é a
-- postura fechada — esta tabela diz quem tem acesso a quê, e é exatamente o
-- que não deve vazar se alguém expuser a anon key um dia.

comment on table public.permissoes_trilha is
  'Histórico de concessão e revogação de acesso por papel. Uma linha por '
  'célula que MUDOU de valor — salvar a tela sem alterar nada não gera linha.';
