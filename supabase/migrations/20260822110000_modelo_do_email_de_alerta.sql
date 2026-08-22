-- O texto do e-mail de alerta, editável pela tela (Configuração › Alertas).
--
-- ⚠️ RODAR ANTES DO DEPLOY, pelo mesmo motivo da migration de 20/08 e não pela
-- leitura: `_from_row` usa `row.get(...)` com default e sobrevive à ausência
-- das colunas, mas `save_settings` faz upsert com a LINHA INTEIRA — com uma
-- coluna inexistente o PostgREST recusa o upsert todo (`PGRST204`), e salvar
-- QUALQUER configuração do portal para de funcionar.
--
-- As quatro colunas guardam só a moldura do e-mail. A tabela de certificados
-- continua sendo gerada a cada envio, porque não é texto: é o inventário do
-- dia. Um campo editável no lugar dela produziria um e-mail que afirma
-- vencimentos que ninguém conferiu.
--
-- Vazio significa "usar o padrão do código" nas quatro, sem exceção — a mesma
-- convenção do resto de `portal_settings`. Uma instalação que nunca abrir o
-- modal manda exatamente o e-mail que mandava antes dele existir.

alter table public.portal_settings
  add column if not exists alerta_email_assunto text not null default '',
  add column if not exists alerta_email_titulo text not null default '',
  add column if not exists alerta_email_abertura text not null default '',
  add column if not exists alerta_email_recado text not null default '';

comment on column public.portal_settings.alerta_email_assunto is
  'Assunto do resumo. Marcadores: {data} {a_vencer} {vencidos} {janela}. '
  'Vazio = "Resumo de certificados — {a_vencer} a vencer, {vencidos} vencidos recentemente". '
  'Quebra de linha é removida na gravação: em cabeçalho SMTP ela injeta cabeçalho novo.';

comment on column public.portal_settings.alerta_email_titulo is
  'Título dentro do e-mail. Vazio = "Resumo de certificados".';

comment on column public.portal_settings.alerta_email_abertura is
  'Parágrafo antes das tabelas. Vazio = a frase com a data e os totais do dia.';

comment on column public.portal_settings.alerta_email_recado is
  'Recado no rodapé, acima da linha de procedência. Vazio = o aviso sobre a '
  'janela de dias. A linha que diz POR QUE a pessoa recebeu e como parar de '
  'receber não é editável: é a única saída que o destinatário tem.';
