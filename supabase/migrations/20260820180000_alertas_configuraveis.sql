-- Alertas por e-mail configuráveis pela tela: destinatários, marcos e intervalo.
--
-- ⚠️ RODAR ANTES DO DEPLOY. Não é opcional, e a razão não é a leitura.
--
-- A LEITURA sobrevive à ausência das colunas: `_from_row` usa `row.get(...)`
-- com default e cai no padrão. Foi por isso que esta migration nasceu com o
-- cabeçalho dizendo "ordem-independente" — e o cabeçalho estava errado.
--
-- A ESCRITA não sobrevive. `save_settings` faz um upsert com a linha INTEIRA;
-- com uma coluna inexistente o PostgREST recusa o upsert todo (`PGRST204`), e
-- não apenas os campos novos. Sem esta migration aplicada, salvar QUALQUER
-- configuração do portal — pastas, SMTP, instalador — para de funcionar.
--
-- Verificado em 20/08/2026 rodando o portal contra o banco sem as colunas: a
-- gravação falhou e a tela ainda respondia "salvo com sucesso". As duas coisas
-- foram corrigidas; esta é a que só o banco resolve.

alter table public.portal_settings
  -- Vazio = o resumo vai para todo administrador ativo, como sempre foi.
  -- Preenchido = vai exatamente para esta lista.
  add column if not exists alertas_destinatarios text not null default '',

  -- Vazio = 30,15,7,1 (o que valia antes desta tela). Guardado como texto e
  -- não como int[]: o mesmo valor precisa sobreviver ao fallback em
  -- data/portal_settings.json, que é JSON puro, e a normalização já acontece
  -- em app/alertas_config.py — um só lugar decidindo a forma.
  add column if not exists alertas_marcos text not null default '',

  -- 0 = 20 horas, o intervalo mínimo que já existia no código. Não é horário
  -- de disparo: é o intervalo mínimo entre duas execuções do job, que existe
  -- porque o worker recicla várias vezes ao dia (--max-requests 500).
  add column if not exists alertas_intervalo_horas integer not null default 0;

comment on column public.portal_settings.alertas_destinatarios is
  'E-mails do resumo diário, separados por vírgula. Vazio = todos os admins ativos. '
  'ATENÇÃO: endereço que não pertence a uma conta do portal não deixa de receber '
  'quando alguém é desativado — não há conta para desativar.';

comment on column public.portal_settings.alertas_marcos is
  'Dias que faltam para o vencimento em que sai um novo aviso, ex.: "30,15,5". '
  'Vazio = 30,15,7,1.';

comment on column public.portal_settings.alertas_intervalo_horas is
  'Intervalo mínimo entre execuções do job de alertas. 0 = 20 horas.';
