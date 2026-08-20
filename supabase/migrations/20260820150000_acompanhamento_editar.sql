-- ==========================================================================
-- Acompanhamento passa a ter tres niveis: `editar` para quem ja tinha `ler`
-- Projeto Supabase: wubokujetyaolnjxiiid
--
-- COMO USAR: rode um PASSO de cada vez. Se algum der erro, PARE e me mande a
-- mensagem exata. Sem BEGIN/COMMIT -- o SQL Editor ja roda numa transacao.
--
-- APLICADA EM PRODUCAO EM 20/08/2026, ANTES do deploy do codigo — que era a
-- ordem obrigatoria. Conferencia do PASSO 3: gestor e user em 'editar',
-- nenhuma linha restante em 'ler'. Com isso o deploy do codigo que exige
-- `editar` para salvar a selecao nao tira nada de ninguem.
--
-- ── A ORDEM IMPORTA AQUI, ao contrario da migration anterior ─────────────
--
-- RODE ESTE SQL **ANTES** DO DEPLOY DO CODIGO.
--
-- A migration de 20/08 (permissoes_por_papel) podia rodar em qualquer ordem
-- porque o codigo caia num padrao identico ao banco. Aqui e diferente: o codigo
-- novo exige `editar` para SALVAR a selecao de certificados, e o banco hoje diz
-- `ler`. Como o BANCO VENCE o padrao do codigo, deployar primeiro deixaria todo
-- operador sem conseguir marcar os proprios certificados -- em silencio, porque
-- a tela simplesmente devolveria 403 num botao que sempre funcionou.
--
-- Rodar este UPDATE ANTES nao muda nada com o codigo atual: `editar` satisfaz
-- quem pede `ler`, entao o comportamento e identico ate o deploy acontecer.
-- Essa e a propriedade que torna a ordem segura.
--
-- ── Por que a mudanca ────────────────────────────────────────────────────
--
-- A tela de Acompanhamento TEM escrita: e onde a pessoa marca quais
-- certificados quer acompanhar. Ate agora o PUT ficava em `ler`, porque a
-- escrita e sobre ela mesma -- e o resultado era um nivel chamado "So ver" que
-- deixava editar. O nome mentia, e o cliente apontou.
--
-- Com tres niveis, cada um passa a significar o que diz:
--   nenhum -> a tela some do menu e as rotas recusam
--   ler    -> ve os proprios certificados, NAO muda quais acompanha
--   editar -> ve e escolhe
--
-- O nivel `ler` deixou de ser sinonimo de `editar` e virou um controle de
-- verdade: da para deixar alguem acompanhar sem poder mexer na propria lista.
-- ==========================================================================


-- ─────────────────────────────────────────────────────────────────────────
-- PASSO 1 — Diagnostico. Nao altera nada. Me mande o resultado.
--
-- Esperado: duas linhas, gestor e user, ambas em 'ler'.
-- ─────────────────────────────────────────────────────────────────────────

select papel, modulo, nivel
from public.permissoes
where modulo = 'acompanhamento'
order by papel;


-- ─────────────────────────────────────────────────────────────────────────
-- PASSO 2 — Concede `editar` a quem ja tinha `ler`.
--
-- `where nivel = 'ler'` de proposito: se alguem ja tiver colocado
-- 'nenhum' pela tela, essa decisao e respeitada. Um UPDATE cego reabriria um
-- acesso que alguem fechou.
-- ─────────────────────────────────────────────────────────────────────────

update public.permissoes
set nivel = 'editar',
    alterado_em = now(),
    alterado_por = 'migration 20260820150000'
where modulo = 'acompanhamento' and nivel = 'ler';


-- ─────────────────────────────────────────────────────────────────────────
-- PASSO 3 — Conferencia. Esperado: nenhuma linha em 'ler'.
-- ─────────────────────────────────────────────────────────────────────────

select papel, nivel
from public.permissoes
where modulo = 'acompanhamento'
order by papel;
