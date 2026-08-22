-- Que versão cada estação está rodando.
--
-- Aditiva, e o código não depende da ordem — mas isso foi conquistado, não é de
-- graça, e vale saber por quê:
--
-- O agente novo reporta `versao` ao trocar o segredo por token. Se a coluna não
-- existisse, o PostgREST recusaria o UPDATE INTEIRO (PGRST204) e o `visto_em`
-- deixaria de ser gravado — toda a frota apareceria "Parada" no painel, e a
-- fase 4 não enfileiraria comando para máquina nenhuma. O sintoma não apontaria
-- para esta migration em lugar nenhum.
--
-- `agent_devices.autenticar` tenta de novo sem a coluna e deixa aviso no log.
-- Rodar isto restaura a informação; não rodar não quebra nada.
--
-- Por que isto vem ANTES de qualquer auto-atualização: hoje a pergunta "quais
-- máquinas ainda estão na versão velha?" não tem resposta em lugar nenhum. Sem
-- ela, atualizar a frota é ir de mesa em mesa perguntando, e conferir se a
-- correção chegou é impossível. Um atualizador automático construído sobre esse
-- vazio não teria como dizer se funcionou.
--
-- O valor é REPORTADO pela estação, não medido pelo portal: é o agente que diz
-- qual versão está executando, ao trocar o segredo por token. Isso significa
-- que uma máquina parada guarda a última versão que ela disse — e é isso que se
-- quer, porque a pergunta durante um diagnóstico é "o que tem lá", não "o que
-- teria se ela ligasse".

alter table public.agent_devices
  add column if not exists versao text not null default '';

comment on column public.agent_devices.versao is
  'Versão do agente reportada pela própria estação na última troca de token. '
  'Vazio = nunca reportou (agente anterior a esta coluna, ou registrado e ainda '
  'sem primeiro contato).';
