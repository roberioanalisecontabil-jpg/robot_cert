-- Quando cada certificado apareceu pela primeira vez na pasta (30/09/2026).
--
-- O sino do portal passa a mostrar "certificados novos" e um e-mail avisa
-- quem tem o certificado na carteira. "Novo" = a linha de cert_history não
-- existia antes desta ingestão; esta coluna guarda quando ela nasceu.
--
-- O upsert do portal NUNCA envia esta coluna: o DEFAULT a preenche na
-- inserção e o ON CONFLICT ... DO UPDATE só toca as colunas enviadas, então
-- ela é preservada nas atualizações diárias.
--
-- Linhas anteriores a esta migration ficam com NULL de propósito. Preencher
-- com a última data registrada (= o scan de hoje, para os 500+ certificados
-- que o agente reenvia todo dia) faria o acervo inteiro aparecer como "novo"
-- nos próximos 7 dias. NULL é "não se sabe quando apareceu", e o portal trata
-- NULL como "não é novo".
--
-- ATENÇÃO à ordem: `ADD COLUMN ... DEFAULT now()` preencheria as linhas
-- EXISTENTES com now() (o Postgres aplica o default a todas na criação), e o
-- acervo inteiro viraria "novo" — foi exatamente o que a cópia local mostrou
-- em 30/09 (1031 de 1031 linhas). Primeiro a coluna nasce sem default
-- (linhas antigas ficam NULL); só depois o default passa a valer para as
-- inserções seguintes.
--
-- Ida (idempotente):
ALTER TABLE cert_history
    ADD COLUMN IF NOT EXISTS primeira_data_registrada timestamptz;

ALTER TABLE cert_history
    ALTER COLUMN primeira_data_registrada SET DEFAULT now();

CREATE INDEX IF NOT EXISTS cert_history_primeira_data_registrada_idx
    ON cert_history (primeira_data_registrada);

-- Volta:
-- DROP INDEX IF EXISTS cert_history_primeira_data_registrada_idx;
-- ALTER TABLE cert_history DROP COLUMN IF EXISTS primeira_data_registrada;
