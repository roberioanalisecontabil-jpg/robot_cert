-- Credencial de MÁQUINA: o agente do ANALISESRV deixa a X-API-Key compartilhada.
--
-- ⚠️ RODAR ANTES DO DEPLOY. Sem a tabela nada quebra: a X-API-Key continua
-- aceita (é a transição), e o provisionamento responde 503 dizendo o motivo.
--
-- ── Por que agent_devices não basta ───────────────────────────────────────
--
-- `agent_devices` (migration 20260822180000) é a credencial da PESSOA nesta
-- máquina — e está dormente exatamente porque o serviço (LocalSystem) não
-- decifra um blob DPAPI do perfil de outra conta. Quem faz todas as chamadas
-- autenticadas do agente é o serviço, e a identidade dele seguiu sendo a
-- X-API-Key: um segredo único, estático, sem rotação nem revogação (R2 do
-- diagnóstico de 25/08/2026) — o mesmo papel `agent` que o /redeem aceita.
--
-- Esta tabela é o mesmo desenho aplicado à MÁQUINA EM SI: segredo aleatório
-- por estação, sha256 determinístico, revogação individual. No disco ele mora
-- em %ProgramData%\Analise CertiDigital Agent\maquina.dat, cifrado com DPAPI
-- de escopo MÁQUINA — o único cofre que o LocalSystem alcança.
--
-- É a MESMA tabela que o INVENT ganhou em 01/09/2026 (migrations/011 de lá):
-- um desenho, duas aplicações — ver `identidade-de-maquina-desenho.md`.
--
-- ── Sem user_id, de propósito ─────────────────────────────────────────────
--
-- Isto não é "de quem é a máquina"; é "esta máquina é ela mesma". O vínculo
-- com pessoa continua sendo `agent_devices`.
--
-- ── Como o segredo chega na estação ───────────────────────────────────────
--
-- Aqui não há fluxo de aprovação (é UM consumidor, o ANALISESRV): o serviço,
-- na primeira subida sem credencial, chama POST /api/agent/maquinas/provisionar
-- autenticado pela X-API-Key que já o autentica hoje. A emissão é única por
-- machine_id — linha existente (até revogada) recusa, e o caminho de volta é
-- um admin reemitir. O texto claro existe uma vez, nessa resposta.

create table if not exists public.machine_credentials (
  id uuid primary key default gen_random_uuid(),
  machine_id text not null,
  segredo_hash text not null,
  versao text not null default '',
  criado_em timestamptz not null default now(),
  visto_em timestamptz,
  revogado_em timestamptz
);

-- Uma máquina, uma credencial — inclusive revogada. Linha revogada BLOQUEIA
-- reemissão automática de propósito: se o provisionamento pudesse recriar o
-- segredo, revogar não revogaria nada (quem tem a X-API-Key provisiona).
-- Reemitir é ato de admin, pela rota que apaga a linha.
create unique index if not exists machine_credentials_machine
  on public.machine_credentials (machine_id);

-- O caminho quente: toda chamada do serviço procura por este hash.
create unique index if not exists machine_credentials_segredo
  on public.machine_credentials (segredo_hash);

comment on table public.machine_credentials is
  'Credencial da MÁQUINA em si (o serviço LocalSystem), uma por estação. '
  'Substitui a X-API-Key compartilhada. Irmã de agent_devices, que segue '
  'sendo a credencial da PESSOA na estação.';

comment on column public.machine_credentials.segredo_hash is
  'sha256 do segredo, não bcrypt — mesmas duas razões de '
  'agent_devices.segredo_hash: 32 bytes aleatórios não têm palpite a '
  'encarecer, e o hash precisa ser determinístico porque a autenticação acha '
  'a linha por igualdade a cada requisição.';

comment on column public.machine_credentials.visto_em is
  'Último contato AUTENTICADO por esta credencial. Carimbado no mesmo ato da '
  'autenticação — não consegue afirmar vida que não houve.';

comment on column public.machine_credentials.revogado_em is
  'Preenchido = o segredo não vale mais, e a máquina NÃO recebe outro sozinha. '
  'A linha é preservada: apagá-la (rota de reemissão) é a decisão explícita de '
  'deixar a máquina obter credencial nova no próximo provisionamento.';
