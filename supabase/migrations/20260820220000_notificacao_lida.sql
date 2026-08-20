-- "Li todos": o sino deixa de repetir o que a pessoa já viu.
--
-- ORDEM-INDEPENDENTE, e desta vez a afirmação foi conferida em vez de assumida
-- (a de 20260820180000 nasceu com essa etiqueta errada). Aqui é tabela NOVA, e
-- não coluna acrescentada a tabela existente: nenhum upsert em uso passa a
-- mandar campo inexistente, então o portal antigo continua funcionando sem
-- ela — apenas sem o botão. As leituras tratam a ausência caindo em "nada
-- marcado como lido", que é o comportamento anterior.

create table if not exists public.notificacao_lida (
    user_id uuid not null,

    -- MESMA FORMA da chave do antispam de e-mail: `expired` ou
    -- `expiring:{marco}`, prefixada pelo fingerprint do certificado.
    --
    -- É o ponto do desenho. Se "li todos" marcasse o CERTIFICADO, ele sumiria
    -- para sempre: quem lesse o aviso de 30 dias nunca mais veria o de 15, nem
    -- o do vencimento. Marcando o par (certificado, marco), cada limiar novo
    -- reaparece sozinho — do mesmo jeito que um novo marco dispara um novo
    -- e-mail. As duas coisas passam a concordar sobre o que é "um aviso".
    chave text not null,

    lida_em timestamptz not null default now(),

    primary key (user_id, chave)
);

-- O sino consulta "tudo que esta pessoa já leu" a cada abertura; a PK acima já
-- serve a esse filtro por ser prefixada por user_id.

alter table public.notificacao_lida enable row level security;

-- Sem policy: o portal acessa com a service key, como as demais tabelas deste
-- schema. RLS ligada e sem policy nenhuma é a postura fechada por padrão — se
-- amanhã alguém expuser a anon key, esta tabela não vaza.

comment on table public.notificacao_lida is
  'Avisos que cada pessoa marcou como lidos no sino. Uma linha por (pessoa, '
  'certificado + marco): o mesmo certificado volta a aparecer quando cruza o '
  'próximo limiar.';
