-- ==========================================================================
-- Matriz de permissoes por papel (modulo x nivel)
-- Projeto Supabase: wubokujetyaolnjxiiid
--
-- COMO USAR: rode um PASSO de cada vez. Se algum der erro, PARE e me mande a
-- mensagem exata. Sem BEGIN/COMMIT -- o SQL Editor ja roda numa transacao.
--
-- NAO APLICADA. Etapa 3 de docs/PLANO_niveis_de_acesso.md.
--
-- ADITIVA: uma tabela nova. Nada existente e alterado.
--
-- ── A ORDEM AQUI NAO IMPORTA, e isso foi construido de proposito ─────────
--
-- Ao contrario da migration de 18/08 (departamentos), esta pode rodar ANTES ou
-- DEPOIS do deploy do codigo, em qualquer ordem:
--
--   * Codigo sem tabela  -> `app/permissoes.py` detecta PGRST205 ("Could not
--                           find the table") e cai no padrao embutido.
--   * Tabela sem semente -> zero linhas vale como "ainda nao semeada", e o
--                           padrao entra igual.
--   * Tabela semeada     -> a matriz do banco passa a valer.
--
-- Os tres estados produzem o MESMO comportamento no dia da virada, porque a
-- semente do PASSO 3 e exatamente o que o portal ja faz hoje. Isso e o ponto:
-- ligar a camada nao muda nada, e qualquer diferenca observada depois e
-- mudanca que alguem fez de proposito.
--
-- ── Por que `admin` nao aparece na tabela ────────────────────────────────
--
-- `admin` e sempre total, resolvido no codigo antes de qualquer consulta. Nao
-- e uma validacao que pode falhar: e uma linha que nao existe. Isso elimina o
-- engano mais caro possivel numa tela de permissoes -- o administrador
-- desmarcando o proprio acesso a Usuarios e ficando sem como voltar.
--
-- Consequencia pratica: a tela mostra 2 linhas (gestor, user), nao 3.
--
-- ── Por que ALCANCE nao esta aqui ────────────────────────────────────────
--
-- De QUEM um gestor pode tratar ja e decidido por `require_admin_ou_lider` +
-- `_exigir_alcance`, a partir da lideranca de departamento. Esta tabela
-- responde outra pergunta -- QUAL modulo, e em que profundidade. Juntar as
-- duas perderia a barreira que impede um lider do Fiscal de mexer na carteira
-- do Contabil.
-- ==========================================================================


-- ─────────────────────────────────────────────────────────────────────────
-- PASSO 1 — Diagnostico. Nao altera nada. Me mande o resultado.
--
-- Esperado: ZERO linhas (a tabela ainda nao existe).
-- ─────────────────────────────────────────────────────────────────────────

select table_name
from information_schema.tables
where table_schema = 'public' and table_name = 'permissoes';


-- ─────────────────────────────────────────────────────────────────────────
-- PASSO 2 — Cria a tabela.
--
-- `check` nos tres campos: papel, modulo e nivel sao vocabulario fechado, e um
-- valor fora dele viraria "nenhum" em silencio no codigo -- trancando gente
-- para fora de um modulo que ninguem mexeu. Melhor recusar a escrita.
--
-- A lista de modulos espelha `app/permissoes.py:MODULOS`. Se um modulo novo
-- entrar la, o `check` aqui precisa acompanhar -- e a duplicacao e proposital:
-- o banco recusando valor invalido e a ultima barreira quando o codigo erra.
-- ─────────────────────────────────────────────────────────────────────────

create table if not exists public.permissoes (
    papel       text not null check (papel in ('gestor', 'user')),
    modulo      text not null check (modulo in (
                    'inicio', 'dashboard', 'historico', 'vencidos',
                    'duplicidades', 'acompanhamento', 'carteiras',
                    'instalador', 'usuarios', 'configuracao'
                )),
    nivel       text not null check (nivel in ('nenhum', 'ler', 'editar')),
    -- Trilha de quem concedeu o que, e quando. Mudar permissao e conceder
    -- acesso, e este portal ja trata concessao com trilha no cofre; uma tabela
    -- de permissoes sem rastro seria a unica concessao sem historico.
    alterado_em timestamptz not null default now(),
    alterado_por text,
    primary key (papel, modulo)
);


-- ─────────────────────────────────────────────────────────────────────────
-- PASSO 3 — Semente: EXATAMENTE o comportamento de hoje (20/08/2026).
--
-- gestor  -> ve as telas de consulta, edita Carteiras.
-- user    -> ve as telas de consulta, nada mais.
-- Nenhum dos dois alcanca Dashboard, Instalador, Usuarios ou Configuracao,
-- que e o que `ui-common.js` ja revela apenas para admin.
--
-- `on conflict do nothing`: rodar duas vezes nao sobrescreve configuracao que
-- alguem ja tenha ajustado pela tela.
-- ─────────────────────────────────────────────────────────────────────────

insert into public.permissoes (papel, modulo, nivel, alterado_por) values
    ('gestor', 'inicio',          'ler',    'migration 20260820'),
    ('gestor', 'dashboard',       'nenhum', 'migration 20260820'),
    ('gestor', 'historico',       'ler',    'migration 20260820'),
    ('gestor', 'vencidos',        'ler',    'migration 20260820'),
    ('gestor', 'duplicidades',    'ler',    'migration 20260820'),
    ('gestor', 'acompanhamento',  'ler',    'migration 20260820'),
    ('gestor', 'carteiras',       'editar', 'migration 20260820'),
    ('gestor', 'instalador',      'nenhum', 'migration 20260820'),
    ('gestor', 'usuarios',        'nenhum', 'migration 20260820'),
    ('gestor', 'configuracao',    'nenhum', 'migration 20260820'),
    ('user',   'inicio',          'ler',    'migration 20260820'),
    ('user',   'dashboard',       'nenhum', 'migration 20260820'),
    ('user',   'historico',       'ler',    'migration 20260820'),
    ('user',   'vencidos',        'ler',    'migration 20260820'),
    ('user',   'duplicidades',    'ler',    'migration 20260820'),
    ('user',   'acompanhamento',  'ler',    'migration 20260820'),
    ('user',   'carteiras',       'nenhum', 'migration 20260820'),
    ('user',   'instalador',      'nenhum', 'migration 20260820'),
    ('user',   'usuarios',        'nenhum', 'migration 20260820'),
    ('user',   'configuracao',    'nenhum', 'migration 20260820')
on conflict (papel, modulo) do nothing;


-- ─────────────────────────────────────────────────────────────────────────
-- PASSO 4 — Conferencia. Esperado: 20 linhas, e a de carteiras/gestor em
-- 'editar'.
-- ─────────────────────────────────────────────────────────────────────────

select papel, count(*) as modulos
from public.permissoes
group by papel
order by papel;

select papel, modulo, nivel
from public.permissoes
where nivel <> 'nenhum'
order by papel, modulo;


-- ─────────────────────────────────────────────────────────────────────────
-- PASSO 5 (opcional) — RLS.
--
-- O portal fala com o Supabase pela service key, que ignora RLS; ligar aqui
-- nao muda o comportamento do servidor. Vale como rede de seguranca se algum
-- dia uma chave anon alcancar esta tabela: sem policy, ninguem le nada.
-- ─────────────────────────────────────────────────────────────────────────

-- alter table public.permissoes enable row level security;
