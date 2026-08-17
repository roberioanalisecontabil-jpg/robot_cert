-- ==========================================================================
-- colaborador_cert_selecoes: user_email deixa de ser chave — FASE 3b e 3b-2
--
-- Aplicadas em produção em 17/08/2026, nesta ordem.
--
-- POR QUE:
--   `user_email text primary key` implica NOT NULL. Enquanto for assim, o
--   código NÃO PODE parar de gravar a coluna — o INSERT passaria a violar o
--   NOT NULL e toda gravação de seleção falharia. E a PK também não pode sair
--   sozinha, porque o `on_conflict=user_email` do código no ar precisa de uma
--   constraint única ali. É circular; esta migration abre o círculo.
--
-- A ORDEM INTERNA É O PONTO: o UNIQUE entra ANTES de a PK sair, então nunca
-- existe um instante em que aquele `on_conflict` fique sem alvo. Invertida,
-- qualquer gravação no intervalo falharia com "there is no unique or exclusion
-- constraint matching the ON CONFLICT specification".
--
-- A TABELA FICA SEM CHAVE PRIMÁRIA daqui até a 3d, de propósito: `user_id` só
-- vira PK depois de ser NOT NULL, e isso só deve ser exigido quando o código
-- garantir que sempre a preenche — o que passa a valer na 3c. Não afeta o
-- portal: o PostgREST usa os filtros explícitos que o código manda, e as duas
-- constraints UNIQUE continuam impedindo linha duplicada.
-- ==========================================================================

-- ── Fase 3b ──────────────────────────────────────────────────────────────

ALTER TABLE public.colaborador_cert_selecoes
    ADD CONSTRAINT colaborador_cert_selecoes_user_email_key UNIQUE (user_email);

-- Em produção rodou como bloco DO que descobria o nome real da PK e travava se
-- as duas UNIQUE não estivessem no lugar. Aqui fica a forma direta, com o nome
-- que o passo de diagnóstico revelou.
ALTER TABLE public.colaborador_cert_selecoes
    DROP CONSTRAINT colaborador_cert_selecoes_pkey;


-- ── Fase 3b-2 ────────────────────────────────────────────────────────────
--
-- ERRO MEU, PEGO PELA VERIFICAÇÃO. Eu tinha escrito que, removida a PK,
-- `user_email` ficaria `is_nullable = YES`. O passo de conferência devolveu
-- **NO**. No PostgreSQL o NOT NULL é atributo próprio da coluna (`attnotnull`),
-- que a PRIMARY KEY **define** ao ser criada mas **não desfaz** ao ser removida.
--
-- Sem esta linha, a 3b tinha atingido metade do objetivo: a coluna deixou de
-- ser chave mas continuava obrigatória, então o código ainda não poderia parar
-- de gravá-la — exatamente o bloqueio que a 3b existia para abrir. Se a
-- verificação fosse só "rodou sem erro", isso teria passado, e o defeito
-- apareceria na 3c como falha de gravação em produção.

ALTER TABLE public.colaborador_cert_selecoes
    ALTER COLUMN user_email DROP NOT NULL;
