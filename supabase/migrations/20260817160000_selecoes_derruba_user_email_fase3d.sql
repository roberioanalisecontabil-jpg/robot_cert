-- ==========================================================================
-- colaborador_cert_selecoes: fim do rechaveamento — FASE 3d (última)
--
-- Aplicada em produção em 17/08/2026. Verificada: PRIMARY KEY (user_id),
-- FOREIGN KEY para users(id) ON DELETE CASCADE, nenhuma UNIQUE avulsa,
-- 1 linha preservada.
--
-- ÚNICA IRREVERSÍVEL DA SÉRIE. As anteriores adicionavam; esta apaga a coluna
-- `user_email`. Por isso o DROP roda dentro de um bloco com trava: se existir
-- UMA linha sem `user_id`, levanta exceção e nada é apagado. Sem a trava, o
-- `DROP COLUMN` roda alegremente e destrói o único vínculo daquela seleção com
-- uma pessoa — viraria dado sem dono, sem recuperação.
--
-- A `UNIQUE (user_email)` da fase 3b cai junto com a coluna, automaticamente.
--
-- ── Onde termina a série ─────────────────────────────────────────────────
--
--   fase 1   coluna user_id anulável + FK + backfill + índice parcial
--   fase 2   código lê pela identidade e grava nas duas colunas
--   fase 3a  UNIQUE (user_id) como constraint (índice parcial não serve
--            para o ON CONFLICT inferir alvo)
--   fase 3b  UNIQUE (user_email) e remove a PRIMARY KEY
--   fase 3b-2 ALTER COLUMN user_email DROP NOT NULL — remover a PK no
--            PostgreSQL NÃO remove o NOT NULL da coluna
--   fase 3c  código para de gravar/ler user_email; on_conflict → user_id;
--            `_mover_selecoes_de_email` apagado
--   fase 3d  esta
--
-- O passo 3 abaixo é o que fecha de verdade: com `user_id NOT NULL`, o BANCO
-- passa a recusar linha sem identidade. Até aqui isso dependia de o código se
-- comportar.
-- ==========================================================================

DO $$
DECLARE
    orfas integer;
    total integer;
BEGIN
    SELECT count(*) FILTER (WHERE user_id IS NULL), count(*)
      INTO orfas, total
      FROM public.colaborador_cert_selecoes;

    IF orfas > 0 THEN
        RAISE EXCEPTION
            'ABORTADO: % de % selecoes estao sem user_id. Apagar user_email '
            'agora tornaria essas linhas dado sem dono, sem recuperacao.',
            orfas, total;
    END IF;

    ALTER TABLE public.colaborador_cert_selecoes DROP COLUMN user_email;
    RAISE NOTICE 'user_email removida. % linha(s) conferida(s), todas com identidade.', total;
END $$;


ALTER TABLE public.colaborador_cert_selecoes
    ALTER COLUMN user_id SET NOT NULL;


-- A tabela estava sem PK desde a 3b, de propósito: só quis exigir NOT NULL
-- depois de o código garantir que sempre preenche, o que passou a valer na 3c.
ALTER TABLE public.colaborador_cert_selecoes
    ADD CONSTRAINT colaborador_cert_selecoes_pkey PRIMARY KEY (user_id);


-- A UNIQUE (user_id) da 3a virou um segundo índice cobrando escrita a cada
-- gravação sem proteger nada que a chave primária já não proteja.
--
-- DEPOIS da PK, nunca antes: entre uma coisa e outra o `on_conflict=user_id`
-- do código em produção precisa de ALGUM alvo único. Invertida, a ordem
-- deixaria uma janela em que salvar seleção falha.
ALTER TABLE public.colaborador_cert_selecoes
    DROP CONSTRAINT IF EXISTS colaborador_cert_selecoes_user_id_key;
