-- Preferência de alerta por pessoa, na linha que ela já tem.
--
-- ⚠️ RODAR ANTES DO DEPLOY, pela mesma razão da migration de 20260820180000:
-- `save_colaborador_selecao` faz upsert da linha inteira, e o PostgREST recusa
-- o upsert todo se uma coluna não existir (`PGRST204`). Sem esta migration,
-- SALVAR SELEÇÃO DE CERTIFICADO para de funcionar — não só a preferência.
--
-- Sem tabela nova: `colaborador_cert_selecoes` já é uma linha por pessoa
-- (`user_id` UNIQUE desde a fase 3a), então a preferência mora ao lado da
-- seleção a que ela se refere, sem join e sem uma segunda linha para ficar
-- órfã.

alter table public.colaborador_cert_selecoes
  -- DEFAULT TRUE, e isso é a decisão mais importante deste arquivo.
  --
  -- Hoje quem seleciona um certificado recebe e-mail; não há opção. Se o
  -- opt-in nascesse desmarcado, TODA a base pararia de receber alerta no dia
  -- do deploy — em silêncio, e sem ninguém para reclamar, porque alerta que
  -- não chega não gera reclamação: gera certificado vencendo despercebido.
  --
  -- Nascendo marcado, o comportamento continua o de sempre e quem não quiser
  -- desmarca. É a mesma convenção de `portal_settings`: o valor de fábrica
  -- reproduz o que já acontecia.
  add column if not exists notificar_email boolean not null default true,

  -- Marcos que a pessoa RECUSA, e não os que aceita.
  --
  -- Guardar os aceitos pareceria mais direto e teria um defeito silencioso: se
  -- o administrador acrescentasse um marco depois, quem já tivesse salvo a
  -- preferência nunca o receberia, sem nada na tela indicando isso. Guardando
  -- as recusas, marco novo entra ligado para todo mundo — que é o que "não
  -- mexi nisso" deve significar.
  --
  -- Vazio = recebe todos os marcos que o portal dispara.
  add column if not exists alerta_marcos_ignorados text not null default '';

comment on column public.colaborador_cert_selecoes.notificar_email is
  'A pessoa quer receber alerta por e-mail dos certificados que acompanha. '
  'TRUE por padrão: é o que acontecia antes desta coluna existir.';

comment on column public.colaborador_cert_selecoes.alerta_marcos_ignorados is
  'Marcos (dias) que a pessoa dispensou, ex.: "30,15". Vazio = recebe todos. '
  'Guarda as RECUSAS para que um marco novo do portal entre ligado.';
