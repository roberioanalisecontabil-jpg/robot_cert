-- Historico: quando o arquivo SAIU das pastas (06/11/2026).
--
-- `primeira_data_registrada` ja diz quando a chave apareceu ("Entrou em").
-- Esta coluna diz desde quando ela nao aparece mais ("Saiu em").
-- NULL = esta nas pastas. O ingest (`upsert_cert_history`) a mantem:
--   - chave que veio no inventario: volta a NULL;
--   - chave presente, da mesma maquina, que nao veio: recebe now().
--
-- A maquina que viu a chave por ultimo ja esta em `machine_id` (o upsert a
-- grava a cada varredura); nao precisa de coluna nova para isso.
--
-- SEM default, de proposito: um default com valor preencheria as linhas
-- existentes (licao de 20260930140000_cert_history_primeira_data_registrada).
--
-- Backfill: em 06/11 uma varredura bem-sucedida atualizou todas as linhas
-- presentes; quem nao e visto ha mais de 2 dias saiu, e a melhor data que se
-- tem e a ultima vez em que foi visto. Nunca sobrescreve valor ja preenchido.
--
-- Ida (idempotente):
ALTER TABLE cert_history
    ADD COLUMN IF NOT EXISTS ausente_desde timestamptz;

UPDATE cert_history SET ausente_desde = ultima_data_registrada
 WHERE ausente_desde IS NULL
   AND ultima_data_registrada < now() - interval '2 days';

-- Volta:
-- ALTER TABLE cert_history DROP COLUMN IF EXISTS ausente_desde;
