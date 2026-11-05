# Bandeja pela Microsoft (entrega 2 do login pela Microsoft)

05/11/2026. Continua `2026-11-04-login-microsoft-design.md` (entrega 1, site, em
produção desde 05/11/2026, main `ab8daf1`). Roteiro de produção:
`docs/login-microsoft.md`.

## Por que

Todo mundo que baixa certificado precisa da bandeja (`estacao/`, versão atual
`1.1.1`) conectada. Hoje a bandeja só conecta com e-mail + senha do CertGuard.
Com a entrega 1, o site dos quatro domínios já é só pela Microsoft, mas a
bandeja ainda aceita a senha: quem sai da empresa e é bloqueado na Microsoft é
desativado pela conferência, mas a senha da bandeja continua sendo uma segunda
porta, e a conta criada pela Microsoft nasce sem senha e fica sem bandeja.

Objetivo: a bandeja entra pela Microsoft, e depois a senha deixa de valer na
bandeja para os quatro domínios.

## O que o Robério disse

- Todos que baixam certificado precisam da bandeja conectada; a **própria
  pessoa** conecta a bandeja.
- Cada pessoa tem **o próprio usuário do Windows** (e, portanto, o próprio
  navegador), e as pessoas **já estão conectadas ao Microsoft 365 no
  navegador**.
- Depois da virada, **todos os quatro domínios entram na bandeja só pela
  Microsoft, admins incluídos**: sem porta reserva na bandeja. Quem é de fora
  dos domínios continua com e-mail + senha.
- A senha da bandeja dos quatro domínios **desliga sozinha** quando todas as
  máquinas estiverem atualizadas. Regra aceita: **todo dispositivo visto nos
  últimos 30 dias na versão nova**; o TI recebe e-mail no dia em que desliga.
- Nada mais o incomoda "por hora".
- **A bandeja não roda em servidor nem em acesso remoto compartilhado**
  (terminal server/RDS): só em estações, uma pessoa por sessão. Isso sustenta
  o retorno pelo `127.0.0.1` da própria máquina. Se um dia passar a rodar numa
  máquina com várias sessões ao mesmo tempo, o retorno por loopback tem de ser
  revisto (outra sessão poderia ocupar a porta e pegar o código).

## Como a pessoa vê

A janela de login da bandeja (`estacao/janela_login.py`) abre como hoje (só na
primeira execução sem conta e quando o portal derruba a conexão). Ela ganha, no
topo, o botão **Entrar com a Microsoft** (com o logo de quatro quadrados, como
no site). E-mail + senha ficam abaixo, para quem é de fora dos domínios.

1. A pessoa clica no botão. A bandeja abre o navegador padrão do Windows numa
   página do portal, que segue para a Microsoft. Quem já está conectado ao
   Microsoft 365 passa direto (um clique, no máximo escolher a conta).
2. No fim, o navegador mostra "Pronto, pode voltar para a bandeja." e a janela
   da bandeja fecha sozinha, conectada (ou "aguardando autorização do
   administrador", como hoje com computador novo — ADR 0002, sem mudança).
3. Se a pessoa cancelar ou a Microsoft recusar, a bandeja mostra a mensagem do
   portal e continua na janela.

Depois da virada, se alguém dos quatro domínios digitar e-mail + senha, a
bandeja responde "Use Entrar com a Microsoft." (texto vindo do portal).

## Como funciona (decisões minhas, não do Robério)

**Volta pela própria máquina (loopback), com o fluxo web do portal no meio.**

1. A bandeja abre um ouvinte só em `127.0.0.1`, numa porta livre aleatória,
   gera um segredo aleatório (`verificador`) e abre o navegador em
   `https://<portal>/entrar/microsoft/bandeja?porta=<porta>&desafio=<sha256(verificador)>`.
2. O portal faz **o mesmo fluxo da entrega 1** (cookie `cg_ms`, PKCE, `state`,
   `nonce`, mesma URI de retorno já cadastrada no Entra), com o pedido marcado
   como "de bandeja" e guardando `porta` e `desafio` no `cg_ms`.
3. No retorno, o portal resolve a conta com `login_microsoft.resolver_conta`
   (mesmas regras: liga, cria Operador, recusa convidado/domínio/ambíguo/
   desativada, grava a chave de renovação). **Não abre sessão do site.** Gera um
   **código de uso único** (curto, ~2 min, guardado só como hash, amarrado à
   conta e ao `desafio`) e manda o navegador para
   `http://127.0.0.1:<porta>/?codigo=<código>` através de uma página de "Pronto"
   (mesma técnica de página que navega sozinha da entrega 1).
4. A bandeja recebe o código no ouvinte, fecha o ouvinte e chama uma rota nova
   do portal com `codigo` + `verificador` + `machine_id` + `nome` +
   `chave_maquina` (os mesmos campos do registro de hoje). O portal confere
   `sha256(verificador) == desafio`, queima o código e registra o dispositivo
   **pelo mesmo caminho** de `/api/agent/dispositivos/registrar` (chave da
   máquina, vínculo pendente ADR 0002). As respostas são **as mesmas de hoje**,
   inteiras: o corpo de sucesso (`segredo`, `email`, `machine_id`, `role`,
   `tipo`, `expira_em`, `autorizacao`, `mensagem`) e o 403 com
   `X-Confirmacao-Pendente` sem segredo, para computador já autorizado sem a
   chave da máquina. Hoje o registro não manda e-mail ao admin nem grava
   auditoria própria; isso não muda (o único e-mail é o de conta nova, da
   entrega 1).

Por quê:

- **Nada muda no Entra**: a URI de retorno é a do site, já cadastrada. Não
  precisa do `http://localhost` nem de "cliente público" no app compartilhado
  do envio de e-mail.
- **O segredo do app nunca vai para a bandeja.**
- **Phishing de link não rende nada**: se alguém mandar a outra pessoa um link
  `/entrar/microsoft/bandeja?...`, o código volta para o `127.0.0.1` de quem
  clicou, e sem o `verificador` (que só a bandeja que abriu tem) ele não serve.
- A parte difícil (OIDC, conferência do token, criação de conta) é a da entrega
  1, já em produção.

Auditoria: o login pela bandeja registra o evento de login com
`metodo: "microsoft_bandeja"` (ou equivalente) e o registro de dispositivo como
hoje.

## Virada automática da senha na bandeja

- **A versão nova** da bandeja (ex.: `1.2.0`, número a escolher) é a que tem o
  botão. A versão chega ao portal no cabeçalho `X-Agent-Version` e fica em
  `agent_devices.versao`, com `visto_em`.
- **Condição:** Microsoft configurada **e** todo dispositivo **não revogado**
  com `visto_em` nos últimos **30 dias** está com versão **≥ a nova**. Precisa
  haver ao menos um dispositivo na versão nova (frota vazia não vira).
  *Minha decisão:* contam só as linhas com versão no formato desta bandeja
  (`certguard-<x.y.z>`, `estacao/__init__.py` `VERSAO_REPORTADA`; comparar sem
  o prefixo, como `_desatualizada` em `app/agent_devices.py`). Linhas com
  `versao` nula ou no formato do Hardlyze (`2.x` sem prefixo) são de outro
  programa ou de antes do carimbo e **não contam** nem travam.
- **Virada travada por um PC que nunca atualiza** (servidor sem atualização
  automática, versão bloqueada): *minha decisão:* a saída é o admin revogar o
  dispositivo na tela de computadores; o painel lista quais dispositivos estão
  segurando a virada.
- **Quem confere:** a rodada de 5 min que já existe (`microsoft_loop`) ou uma
  irmã dela, com a mesma trava entre processos.
- **Quando vira:** grava uma marca persistente (data da virada) — **a virada não
  desfaz sozinha** se um PC antigo reaparecer — e manda **um** e-mail ao TI
  ("A senha da bandeja foi desligada para os quatro domínios em <data>").
- **Efeito:** `POST /api/agent/dispositivos/registrar` com e-mail dos quatro
  domínios passa a responder 403 "Use Entrar com a Microsoft." (e registra
  `login_negado` com motivo próprio). Fora dos domínios, nada muda.
  *Minha decisão:* o 403 vem **antes** de conferir a senha (depois do limite de
  tentativas), igual para e-mail existente ou não e para senha certa ou
  errada: a rota deixa de servir para testar senha ou descobrir contas.
- **Microsoft desligada depois da virada** (variáveis apagadas): *minha
  decisão:* a virada só vale com `configurado()`; sem as variáveis, a senha da
  bandeja volta para todos, como o site volta à senha. É a mesma chave geral da
  entrega 1, não uma porta reserva nova. A marca da virada continua gravada e
  volta a valer quando as variáveis voltarem.
- **Antes da virada:** a regra de hoje continua (conta de domínio só registra
  com senha se já estiver ligada à Microsoft).
- **Bandeja já conectada não cai** em nenhum momento: ela usa o segredo do
  dispositivo, não a senha.
- **PC que volta depois da virada com versão antiga:** a atualização automática
  da bandeja leva à nova; enquanto não chega, ele não conecta conta nova dos
  domínios, só as de fora. Aceito pelo Robério (regra dos 30 dias).
- **Painel:** o admin vê na tela de computadores (ou equivalente) quantos
  dispositivos dos últimos 30 dias faltam atualizar e, depois, a data da
  virada. Forma da tela: a critério do builder.

## Fora desta entrega

- Entrar no Windows pela Microsoft / login automático (estações no domínio
  `ANALISE` local, sem ligação com o Entra).
- Porta reserva na bandeja para admins (decisão do Robério: não terá).
- Mudar qualquer coisa no app do Entra.
- Tirar a senha das contas de fora dos domínios.

## Restrições

- Migrations só pelo `atualizar-portal` (`db/aplicar_schema.py`); nunca à mão.
- A bandeja é Python + Tk + pystray (`estacao/`), distribuída pela atualização
  automática assinada (`estacao/atualizador.py`, manifesto). A versão nova sai
  por esse caminho; o rollout nas máquinas é do Robério.
- O ouvinte loopback escuta **só** em `127.0.0.1`, aceita **um** pedido, tem
  prazo (ex.: 5 min) e fecha.
- Sem dependência nova se a biblioteca padrão resolver (`http.server`,
  `webbrowser`, `secrets`, `hashlib`).
- Tudo com Microsoft desligada (variáveis vazias) se comporta como hoje: sem
  botão na bandeja (a bandeja pergunta ao portal se o login Microsoft está
  ligado) e sem virada.

## O que fica para o builder

- Nomes de rotas, colunas/tabela do código de uso único (ou reaproveitar algo
  existente), formato exato das mensagens.
- Como a bandeja descobre se o portal tem Microsoft ligada (rota pública
  simples ou campo numa rota existente).
- Onde mostrar o contador da virada no painel.
- Número da versão nova.
- Testes: os mesmos níveis da entrega 1 (rotas com fakes, lógica da virada,
  ouvinte loopback e `validar_campos`/mensagens sem Tk).
