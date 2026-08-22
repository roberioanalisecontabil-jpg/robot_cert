-- Identidade do agente: quem, e não só qual chave.
--
-- ⚠️ RODAR ANTES DO DEPLOY. Sem a tabela, as rotas de dispositivo respondem 503
-- com o motivo — não corrompem nada e não afetam o resto do portal (ao
-- contrário da migration de 22/08 do modelo de e-mail, cujo upsert derrubava a
-- gravação inteira de `portal_settings`). Ainda assim, a tela de dispositivos
-- fica inútil até isto rodar.
--
-- Até aqui o agente autenticava-se por `X-API-Key`: um segredo ÚNICO para toda
-- a instalação (`main.require_auth`, ramo 2). Com UM agente, num servidor sob
-- controlo da operação, isso era proporcional. Distribuí-lo por uma frota de
-- estações não é — o valor fica no disco de cada máquina, e quem o lê fala pelo
-- portal inteiro com papel `agent`, que é justamente o papel que `/redeem`
-- aceita para entregar chave privada.
--
-- Cada linha aqui é um par (pessoa, máquina) com segredo PRÓPRIO e revogável um
-- a um. É também o que responde "qual é a máquina do usuário X" sem ninguém
-- escolher `machine_id` numa lista.

create table if not exists public.agent_devices (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.users(id) on delete cascade,
  machine_id text not null,
  nome text not null default '',
  segredo_hash text not null,
  criado_em timestamptz not null default now(),
  visto_em timestamptz,
  revogado_em timestamptz
);

-- Uma pessoa, uma máquina, um dispositivo. Registrar de novo na mesma estação
-- substitui o segredo em vez de acumular linhas órfãs que ninguém revoga — e
-- linha órfã com segredo válido é exatamente o que uma revogação deveria ter
-- eliminado.
create unique index if not exists agent_devices_user_machine
  on public.agent_devices (user_id, machine_id);

-- O caminho quente: a cada renovação de token o portal procura por este hash.
-- Único porque colisão aqui significaria dois dispositivos com o mesmo segredo.
create unique index if not exists agent_devices_segredo
  on public.agent_devices (segredo_hash);

comment on table public.agent_devices is
  'Pares (pessoa, máquina) autorizados a agir pelo agente. O agente troca o '
  'segredo desta linha por um JWT curto; a senha do portal nunca fica guardada '
  'na estação.';

comment on column public.agent_devices.segredo_hash is
  'sha256 do segredo, e não bcrypt como users.password_hash. Duas razões: o '
  'segredo tem 32 bytes de secrets.token_urlsafe e não cai em dicionário, logo '
  'não há palpite a encarecer; e o hash TEM de ser determinístico, porque o '
  'agente apresenta só o segredo e a troca por JWT acha a linha por igualdade. '
  'Com hash salgado seria varrer a tabela a cada renovação.';

comment on column public.agent_devices.visto_em is
  'Último contato do agente. Responde "esta máquina está viva?" antes de o '
  'portal enfileirar um comando de instalação para ela.';

comment on column public.agent_devices.revogado_em is
  'Preenchido = o segredo não vale mais. A linha é preservada de propósito: '
  'apagá-la tiraria da trilha que aquela máquina existiu e foi revogada.';
