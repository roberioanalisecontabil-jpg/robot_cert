# Plano — chave composta no cofre de certificados

> **Status: proposta. Nada aplicado.**
> Elaborado em 2026-08-08 a pedido do item #4 de `a.txt`.

## 1. Onde `on_conflict="fingerprint"` é usado

Duas ocorrências, ambas em `app/cert_installer.py`:

| Local | Tabela | Efeito |
|---|---|---|
| `cert_installer.py:248` (`upsert_pfx`) | `cert_pfx_store` | grava o PFX cifrado |
| `cert_installer.py:361` (`autorizar_no_cofre`) | `cert_vault_optin` | grava a autorização |

Os outros `on_conflict` do projeto (`portal_settings.id`, `cert_history.file_name`, `colaborador_cert_selecoes.user_email`) não têm relação com este assunto.

A restrição vem do schema, não só do código:

```sql
-- 20260803_cert_installer.sql
fingerprint CHAR(64) NOT NULL UNIQUE          -- cert_pfx_store

-- 20260803130000_cert_installer_hardening.sql
fingerprint CHAR(64) PRIMARY KEY              -- cert_vault_optin
```

Nas duas tabelas o fingerprint é **globalmente único**, embora ambas tenham `machine_id` e um índice por `machine_id` — o schema já trata a máquina como dimensão relevante, mas não a inclui na identidade.

## 2. Efeito prático hoje

O fingerprint SHA-256 identifica **o certificado**, não a instalação dele. O mesmo A1 e-CNPJ costuma estar em várias estações de um escritório contábil — que é exatamente o domínio deste projeto. Consequências:

**a) A autorização não coexiste em duas máquinas.** Autorizar o certificado X na estação B faz o upsert sobrescrever a linha da estação A, trocando `machine_id`. Como `listar_optin_fingerprints` filtra por `machine_id`, o agente de A simplesmente para de receber X — sem erro, sem log, sem mudança visível na tela de A. É a mesma classe de falha silenciosa do bug corrigido em 08/08.

**b) O cofre guarda um PFX por certificado, não por instalação.** O último upload vence e sobrescreve `encrypted_pfx`, `pfx_iv`, `pfx_auth_tag` e `machine_id`. Se as estações tiverem cópias com senhas diferentes do mesmo certificado, a cópia guardada deixa de corresponder à da máquina que a enviou primeiro.

**c) É metade de um vetor de segurança já documentado.** O comentário em `app/main.py:98-103` descreve a sobrescrita do registro legítimo via `on_conflict="fingerprint"`. O endurecimento de 08/08 fechou o caminho pelo `machine_id` na barreira do upload; a unicidade global continua sendo o que torna a sobrescrita possível quando alguém passa pela barreira.

**O que NÃO é afetado:** `get_pfx_by_ids` (`cert_installer.py:297`) busca pelo UUID `id`, não pelo fingerprint. O caminho de leitura que monta o bundle de instalação não muda — a alteração é menor do que aparenta.

## 3. Mudança proposta

Chave composta **`(machine_id, fingerprint)`** nas duas tabelas.

Preferida sobre `fingerprint + serial`: o serial é atributo do certificado, então `fingerprint + serial` continua identificando o certificado, não a instalação — não resolve nada. `machine_id` já existe nas duas tabelas, já é indexado, já é o eixo pelo qual o agente consulta e pelo qual a barreira do upload filtra. A identidade passa a ser "este certificado, nesta estação", que é o que o sistema realmente modela.

### Migration

```sql
-- supabase/migrations/AAAAMMDDHHMMSS_cofre_chave_composta.sql

BEGIN;

-- 1. cert_vault_optin: fingerprint era PRIMARY KEY
ALTER TABLE public.cert_vault_optin
    DROP CONSTRAINT IF EXISTS cert_vault_optin_pkey;

ALTER TABLE public.cert_vault_optin
    ADD CONSTRAINT cert_vault_optin_pkey
    PRIMARY KEY (machine_id, fingerprint);

-- 2. cert_pfx_store: fingerprint era UNIQUE; o PK (id UUID) continua
ALTER TABLE public.cert_pfx_store
    DROP CONSTRAINT IF EXISTS cert_pfx_store_fingerprint_key;

ALTER TABLE public.cert_pfx_store
    ADD CONSTRAINT cert_pfx_store_machine_fingerprint_key
    UNIQUE (machine_id, fingerprint);

COMMIT;
```

Sem risco de perda: hoje só pode existir uma linha por fingerprint, e toda linha existente satisfaz a chave nova. A migration é reversível trocando as constraints de volta, **desde que** nenhuma segunda instalação tenha sido gravada nesse meio-tempo.

### Alterações de código que a migration exige

| Arquivo | Mudança | Por quê |
|---|---|---|
| `cert_installer.py:248` | `on_conflict="machine_id,fingerprint"` | senão o upsert continua colidindo por fingerprint |
| `cert_installer.py:361` | `on_conflict="machine_id,fingerprint"` | idem |
| `cert_installer.py:365` `revogar_do_cofre` | receber `machine_id` e filtrar por ele nos dois `delete` | hoje apaga **de todas as máquinas**; com chave composta isso vira apagão silencioso |
| `main.py` `DELETE /vault-optin/{fingerprint}` | aceitar `machine_id` (query param obrigatório) | a rota não tem como saber qual instalação revogar |
| `templates/instalador.html` | mandar `machine_id` no DELETE | já tem `_optinMachineId` desde a correção de 08/08 |

**A revogação é o ponto de atenção.** Hoje `revogar_do_cofre(fingerprint)` apaga por fingerprint nas duas tabelas — comportamento correto sob unicidade global. Com chave composta, deixá-la como está significa que revogar numa estação apaga o material de todas. Essa função precisa mudar **junto** com a migration, não depois.

### Testes a acrescentar

1. Mesmo fingerprint autorizado em A e em B coexiste; revogar em A não afeta B.
2. Upload do mesmo fingerprint por A e por B gera duas linhas em `cert_pfx_store`, cada uma com o material da sua origem.
3. Revogação exige `machine_id` — sem ele a rota recusa em vez de apagar tudo.
4. Regressão da barreira: certificado autorizado só em A continua barrado no upload declarado como B (`test_cert_installer_optin_e2e.py` já cobre; confirmar que segue valendo).

O fake de Supabase de `test_cert_installer_optin_e2e.py` precisa de suporte a `on_conflict` com múltiplas colunas — hoje o `_Query.upsert` compara uma coluna só.

## 4. Ordem sugerida

1. Aplicar a migration em produção (`cert_vault_optin` está com 0 linhas e `cert_pfx_store` com 0 — momento barato)
2. Trocar os dois `on_conflict`
3. Mudar `revogar_do_cofre` + rota DELETE + template, na mesma leva
4. Acrescentar os testes acima
5. Só então autorizar o mesmo certificado em duas máquinas para validar de ponta a ponta

## 5. Se não fizer

O sistema continua funcionando enquanto cada certificado viver numa estação só. O defeito aparece no dia em que alguém autorizar o mesmo certificado numa segunda máquina — e vai aparecer como "o agente da primeira parou de instalar", sem nada nos logs apontando para a causa.
