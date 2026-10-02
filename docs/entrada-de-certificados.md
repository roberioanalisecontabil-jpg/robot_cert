# Entrada de certificados e aviso de novos por hora cheia (02/10/2026)

Decidido em grill com o usuário em 02/10/2026, logo depois da
[revisão página a página](revisao-paginas-2026-10.md). Dois pedidos:

1. **O agente do servidor renomeia o que chega.** Os PFX chegam com o nome que
   o cliente ou o e-mail lhes deu (resumido, com `_` ou `-`, às vezes sem o
   CNPJ). O nome passa a vir do que está DENTRO do certificado: o titular e o
   documento do CN, no padrão do acervo.
2. **E move para a pasta certa.** Pessoa jurídica (CNPJ) ou pessoa física
   (CPF), na subpasta da primeira letra do titular.

E, da conversa, um terceiro: o aviso de "certificado novo" passa a sair por
hora cheia, num e-mail só com todos os novos da hora.

## Decisões

| # | Pergunta | Decisão |
|---|----------|---------|
| F1 | Onde os PFX chegam? | Pasta de **entrada** separada do acervo, configurável no portal. O que está nela ainda não é Inventário. |
| F2 | Formato do nome | `TITULAR DOCUMENTO senha VALOR.pfx` — maiúsculas, sem acento, sem caracteres que o Windows recusa, documento só dígitos. Ex.: `BRASIL EXEMPLO LTDA 12345678000199 senha 123.pfx`. |
| F3 | O que não abre | **Fica na entrada**, com o nome original. O portal lista como *pendente* em Instalador › Entrada, com o motivo, e avisa os administradores por e-mail uma vez por arquivo. |
| F4 | Pasta da letra | Sob a raiz de pessoa jurídica ou física: `A`–`Z`, e `0 a 9` para titular que começa por algarismo. As pastas já existem; o agente cria a que faltar. |
| F5 | Colisão | Pelo **Documento**, não pelo nome do arquivo. Mesmo fingerprint = cópia, descartada mas registrada. Anterior vencido vai para vencidos e o novo toma o lugar. Dois vigentes ficam os dois; o novo ganha sufixo ` (2)` e é marcado *duplicidade*. |
| F6 | Quando | Ao chegar (observador na pasta) e antes de cada varredura. Registro na aba **Entrada** do Instalador. |
| G1 | Caminhos | Configuráveis em Configuração › Pastas e agente: entrada, pessoa jurídica, pessoa física. Caminhos como o **servidor** os vê. `0 a 9` é nome fixo. |
| G2 | Validação | A mesma de origem/vencidos (`validar_pasta`: UNC recusado, raízes permitidas). Entrada exige PJ e PF; não pode ser a mesma pasta do acervo ou dos vencidos. |
| G3 | Chegou vencido | Renomeado e **direto para a pasta de vencidos**. |
| G4 | Aviso de novo | Chave própria **"Avisar quando chegar certificado novo"** (ligada por padrão). O aviso só sai depois do renomear+mover: a entrada fica fora da varredura, então o certificado só entra no Inventário no lugar certo. Envio **a cada hora cheia** (padrão: os novos das 09:01–09:59 vão num e-mail às 10:00) ou **imediato**. |

## Como funciona

**Agente** (`agent/entrada.py`, chamado de `run_agent.py`):

1. Lê `pasta_entrada`, `pasta_pj`, `pasta_pf` de `GET /api/settings` (ou do
   `agent_config.json`). Sem `pasta_entrada`, o passo não existe.
2. Antes da varredura: `scan_folder(entrada, recursive=False)`; para cada PFX
   legível monta o nome canônico, escolhe `PJ|PF / letra`, compara com os
   certificados do mesmo documento já na pasta (F5), move. Vencido vai para
   vencidos (G3). Ilegível fica e vira pendente (F3).
3. `POST /api/agent/entrada` com `{eventos, pendentes}` — sempre, mesmo vazio:
   é a lista de pendentes que o portal reconcilia (o que saiu da pasta fecha).
4. A entrada entra em `exclude_dirs` da varredura quando está sob a origem;
   fora dela, ganha um segundo observador (não recursivo).
5. Nenhum nome com senha sai do agente: `nome_publico_de_arquivo` em tudo.

**Portal** (`app/entrada.py`):

- Tabela `entrada_eventos`: uma linha por evento; pendentes com
  `resultado='pendente'` e `resolvido_em` nulo enquanto o arquivo estiver lá.
- Pendente NOVO → e-mail aos administradores (ou à lista fixa de
  destinatários), com arquivo e motivo. Uma vez por arquivo.
- `GET /api/cert-installer/entrada?dias=` (só administrador) alimenta a aba.

**Aviso de novos por hora** (`app/novos_certificados.py`):

- `/api/ingest` chama `agendar_ou_notificar(novos)`: desligado → nada;
  `imediato` → `notificar_novos` como antes; `hora` (padrão) → grava em
  `novos_pendentes`.
- Tarefa no lifespan dorme até a próxima hora cheia (`segundos_ate_a_proxima_
  hora_cheia`) e chama `enviar_novos_pendentes`: um e-mail por destinatário com
  todos os itens da fila, depois esvazia. O antispam em `sent_alerts` continua
  valendo, então reinício entre gravar e enviar só atrasa.
- Sem a tabela (migration por rodar) o aviso sai de imediato — não se perde.

## Operação

1. Deploy do código (`C:\Apps\atualizacao_push.ps1`) e reinício do serviço.
2. Migration `supabase/migrations/20261002120000_entrada_de_certificados.sql`
   (cópia em `Desktop\robot_cert-entrada-de-certificados.sql`), no psql do
   ANALISESRV. Ensaiada duas vezes numa cópia local em 02/10/2026.
3. Agente **1.5.0** no servidor (`agent_setup.iss`). Nas estações não muda nada
   além da versão esperada pelo portal.
4. Configuração › Pastas e agente: as três pastas, como o servidor as vê.
   Configuração › Alertas: a chave do aviso de novo e o modo.

## Testes

`tests/test_entrada_certificados.py`: nome e letra (F2, F4); processamento com
PFX reais em pasta temporária (movido, CPF, `0 a 9`, vencido, cópia,
substituição, duplicidade, pendentes, sem documento); relatório do agente e
reconciliação dos pendentes; e-mail aos administradores; telas; configuração
(validação e preservação); migration; fila por hora (guardar, enviar, imediato,
desligado, sem tabela, sem banco).
