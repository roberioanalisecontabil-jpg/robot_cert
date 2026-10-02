-- ==========================================================================
-- Movimentos: pasta de origem (02/10/2026, agente 1.6.0)
--
-- COMO USAR: rode no psql do ANALISESRV DEPOIS do deploy do codigo. O codigo
-- novo grava `pasta_origem`; sem a coluna, o INSERT do relatorio do agente
-- falha e o log do portal acusa — nada mais quebra. Idempotente.
--
--   & "C:\Program Files\PostgreSQL\17\bin\psql.exe" -U postgres -p 5433 -d certguard -f <este arquivo>
--
-- A aba Instalador > Entrada virou "Movimentos" e passou a registrar tambem o
-- vencido que a varredura tira da pasta da letra (resultado 'vencido') e o
-- que ela nao conseguiu tirar (resultado 'vencido_preso', pendencia). Para
-- isso cada linha ganha a pasta de onde o arquivo saiu.
-- ==========================================================================

-- PASSO 1 — coluna
ALTER TABLE public.entrada_eventos
  ADD COLUMN IF NOT EXISTS pasta_origem text NOT NULL DEFAULT '';

-- PASSO 2 — o indice das pendencias passa a incluir o vencido preso
DROP INDEX IF EXISTS public.entrada_eventos_pendentes_idx;
CREATE INDEX IF NOT EXISTS entrada_eventos_pendentes_idx
  ON public.entrada_eventos (machine_id, pasta_origem, arquivo_original)
  WHERE resultado IN ('pendente', 'vencido_preso') AND resolvido_em IS NULL;

-- PASSO 3 — conferir (deve listar pasta_origem)
SELECT column_name
  FROM information_schema.columns
 WHERE table_name = 'entrada_eventos' AND column_name = 'pasta_origem';
