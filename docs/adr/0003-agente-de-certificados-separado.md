---
status: accepted
date: 2026-10-12
---

# Agente de certificados próprio nas estações, separado do Hardlyze

Até aqui a estação tinha um programa só: o agente do Hardlyze (INVENT), com o serviço de
inventário e, dentro da mesma bandeja, o login deste portal e a instalação de certificado
(ADR 0002, adendo de 08/10/2026: "continua um instalador só"). Em 10/10/2026 o 2.1.3 caiu na
bandeja por um defeito no código de certificado, e o serviço que vai ganhar acesso remoto
(RustDesk) carregava o login de pessoa de outro portal. A decisão foi tomada no INVENT
(`docs/decisoes-proximas-frentes.md`, seções A e B, commit f190574) e este ADR a registra do
lado do portal de certificados. **Substitui o "um instalador só" do adendo de 08/10 do ADR
0002.**

## Decisão

- **Dois programas, dois instaladores, dois ícones.** O Hardlyze fica com inventário,
  comandos, acesso remoto, scripts e a bandeja de status e chamados. Um **agente de
  certificados** novo, deste repositório, fica com o login deste portal e a instalação de
  certificado.
- **Programa novo e enxuto**, não um "modo estação" do agente do servidor (`agent/`, que roda só
  no ANALISESRV lendo a pasta dos PFX e continua como está). Ele leva o código que funciona hoje
  na bandeja do Hardlyze (`core/conta_certificados.py`, `instalador_certificado.py`,
  `chave_maquina.py`, `janela_login.py`, partes de `identidade.py`) e tem: a **bandeja** da
  pessoa (entrar, situação, receber e instalar) e um **serviço pequeno** (LocalSystem) que gera
  e guarda a chave da máquina e se atualiza.
- **Autorizações separadas.** Cada portal decide sobre o próprio agente. Aqui vale só o vínculo
  pessoa ↔ computador deste portal (Usuários › Computadores, ADR 0002) com a chave da máquina
  (adendo de 10/10). A aprovação de máquina do Hardlyze não entra em nada daqui, e o Hardlyze
  não lê nada daqui (a rota `GET /api/computadores/principais` saiu em 12/10/2026).
- **O dispositivo não abre sessão do portal** (auditoria run-2, 12/10/2026, commit ff84e87):
  o segredo da bandeja só vale nas rotas da estação, com `X-Device-Secret` —
  `/api/estacao/situacao`, `/api/estacao/instalacoes`, `/api/estacao/sair`,
  `/api/cert-installer/claim` e `/api/cert-installer/report-avulso`. O agente novo segue esse
  contrato; nada de JWT de pessoa guardado na estação.
- **Transição sem novo login nem nova autorização.** Na primeira execução a bandeja nova lê o
  `certificados.dat` que a bandeja do Hardlyze já guarda (DPAPI da pessoa), e o serviço novo
  **copia uma vez** a chave da máquina de `%ProgramData%\InventAgent\chave_certificados.dat`
  para a pasta dele. Daí em diante cada agente é dono da sua. Como o hash da chave é o mesmo,
  o vínculo já aprovado continua valendo sem passar pelo administrador.
- **Atualização automática pelo mesmo mecanismo do Hardlyze 2.2.0:** manifesto (versão, SHA-256
  do instalador, "pode voltar") assinado com Ed25519, duas chaves públicas embutidas
  (principal e reserva), atualizador rodando de uma cópia do executável, volta automática em
  10 minutos sem sinal. **Lista de versões própria**, publicada por este portal.
- **Download aberto** (decidido em 12/10/2026). O manifesto e o instalador do agente de
  certificados ficam disponíveis sem credencial: a assinatura é o que garante que o pacote é
  nosso, e o instalador não leva segredo nenhum. Exigir a chave da máquina só complicaria a
  primeira instalação e a reinstalação. Cuidados que vêm junto: teto de requisições por
  endereço nas rotas de download, e o agente nunca instala sem conferir a assinatura (versão
  menor só com a marca "pode voltar").

## Consequências

- O Hardlyze tira da bandeja dele todo o código de certificado na versão que instala o agente
  novo; chega às estações pela atualização automática, sem ninguém passar máquina por máquina.
- Um defeito no agente de certificados não derruba inventário nem acesso remoto, e o fluxo de
  certificado muda sem gerar versão do Hardlyze.
- Este portal passa a publicar instaladores: precisa de pasta de versões no servidor, script de
  publicação (ASCII, como `deploy/` do INVENT) e rotas de leitura.
- A estação passa a ter dois serviços LocalSystem. O de certificados é pequeno de propósito: só
  chave da máquina e atualização; o login e a instalação continuam na bandeja, como a pessoa.
- Enquanto a bandeja antiga do Hardlyze existir, as duas falam com as mesmas rotas e o mesmo
  vínculo; não é preciso rodar as duas ao mesmo tempo na mesma estação (o instalador do Hardlyze
  que tira a bandeja de certificados é o mesmo que instala o agente novo).

## Plano (cada passo com testes, nesta ordem)

Começa **depois** do ensaio do Hardlyze 2.2.0 (atualização automática) terminar, que é a ordem
combinada em `decisoes-proximas-frentes.md`.

1. **Portal — publicação.** Pasta de versões do agente de certificados no servidor;
   `deploy/publicar-agente.ps1` (ASCII) copia instalador + manifesto + assinatura; rotas
   abertas de leitura (manifesto vigente e instalador pelo SHA-256) com teto por endereço; o
   portal confere a assinatura antes de publicar, com o mesmo módulo de manifesto do agente.
2. **Programa — base.** Pacote novo (ex.: `estacao/`) com o código portado da bandeja do
   Hardlyze, só com `X-Device-Secret`; testes portados junto. Ícone e nome próprios
   ("Certificados Análise").
3. **Programa — serviço.** Gera e guarda a chave da máquina (DPAPI de máquina, gravação já
   restrita como em `agent/identidade_maquina.gravar_protegido`); faz a cópia única da chave
   do Hardlyze; consulta o manifesto e dispara o atualizador.
4. **Programa — transição.** Leitura única do `certificados.dat` do Hardlyze; nenhum pedido
   novo ao administrador para quem já estava autorizado (teste com o vínculo e a chave de hoje).
5. **Instalador** (Inno Setup, como o do agente do servidor), com a cópia de si mesmo para a
   volta automática.
6. **Hardlyze** (no INVENT): versão que instala o agente novo e remove a bandeja de
   certificados.
7. **Ensaio** numa máquina de teste: Hardlyze com bandeja antiga → atualização → agente novo
   entra sozinho, instala um certificado de teste; depois uma versão quebrada volta sozinha.

## Adendo de 14/10/2026: separação antes da atualização automática

O ensaio da atualização automática do Hardlyze 2.2.x falhou de novo, e esperar por ele
travava os dois portais. A ordem foi invertida (decidido em conversa, 14/10/2026): o agente de
certificados sai **agora**, o INVENT põe o próprio agente em pleno funcionamento e publica o
site, e a atualização automática dos dois agentes fica **por último**. O que muda neste ADR:

- **Instalação manual, máquina por máquina.** Em cada estação: desinstalar o Hardlyze atual,
  instalar o Hardlyze sem certificados e o agente novo. Nunca há duas bandejas de certificado
  na mesma máquina. O passo 6 do plano deixa de ser "o Hardlyze instala o agente novo".
- **1.0 sem serviço.** Sem atualização automática, o serviço só guardaria a chave da máquina.
  Quem cuida dela é o **instalador**, que já roda como administrador: copia
  `%ProgramData%\InventAgent\chave_certificados.dat` para `%ProgramData%\CertguardAnalise\`
  (mesma ACL: SYSTEM e Administradores total, Usuários leitura) e **apaga o original**; se não
  houver chave antiga, gera uma nova (e a máquina passa pela aprovação do administrador, como
  equipamento novo). O serviço volta junto com a atualização automática.
- **Transição.** A bandeja, no primeiro uso de cada pessoa, lê o
  `%LOCALAPPDATA%\InventAgent\certificados.dat` do Hardlyze, grava o seu e **apaga o
  original**. Como o hash da chave não muda, quem já estava autorizado continua autorizado.
  Consequência aceita: se o Hardlyze antigo for reinstalado, ele gera outra chave e aquela
  máquina volta a pedir aprovação; o agente novo não é afetado.
- **1.0 só com o que a bandeja do Hardlyze faz hoje** (entrar, situação, receber e instalar,
  sair). Nada de função nova: se algo quebrar, foi a separação.
- **Nada no portal para distribuir** (passo 1 do plano adiado): o instalador fica numa pasta
  do ANALISESRV.
- **Nome e lugar:** "CertGuard Análise", `C:\Program Files\Certguard Analise`,
  `%ProgramData%\CertguardAnalise`, `%LOCALAPPDATA%\CertguardAnalise`,
  `certguard_analise.exe`, versão 1.0.0, código em `estacao/`.
- **Ensaio** na máquina de teste, na ordem real (Hardlyze logado → desinstala → instala os
  dois → bandeja já entra logada → instala um certificado), antes de qualquer estação.

O que o INVENT precisa tirar do Hardlyze está em `docs/separacao-agente-hardlyze.md`.

## Adendo de 20/10/2026: atualização automática (1.1.0)

Decidido com o usuário em 20/10/2026, depois da virada da carteira (ADR 0005):

- **O portal de certificados entrega a versão**, não o INVENT: `GET /api/estacao/atualizacao`
  (o pacote assinado, 204 sem publicação) e `GET /api/estacao/atualizacao/arquivo/{sha256}`,
  **abertas**, com teto por endereço, como este ADR previa. A pasta é
  `ATUALIZACOES_DIR/certificados` (padrão `C:\Apps\robot_cert\atualizacoes\certificados`), com
  `vigente.json` e o instalador; publicar é copiar os dois (`deploy/publicar-certguard.ps1`).
- **Chave própria do CertGuard**, não a do Hardlyze: par Ed25519 principal (cifrado na máquina
  de build) e reserva (fora do computador), gerados e usados por
  `scripts/versoes_certguard.py`. O formato do manifesto veio do Hardlyze
  (`estacao/manifesto.py`), mas só aceita o produto `certificados`.
- **Sem serviço: tarefa agendada.** No lugar do serviço LocalSystem previsto acima, duas
  tarefas SYSTEM (`Certguard Analise - atualizacao`, na partida com 5 min de atraso, e a
  mesma com ` 6h`) rodam `certguard_analise.exe --atualizacao`. Elas fazem o papel do serviço
  do Hardlyze (`estacao/atualizador.py`, `estacao/tarefa.py`): conferir, baixar, disparar o
  atualizador, confirmar a versão nova depois de ela alcançar o portal e reabrir a bandeja
  nas sessões. Volta automática em 10 min, como no Hardlyze. Windows Server não se atualiza.
- **O evento** (`POST /api/estacao/atualizacao/evento`) leva a chave da máquina e só vai para o
  log do portal; não há tabela nova.
- **A 1.1.0 entra máquina a máquina**, pela TI: é a última instalação manual. A bandeja
  `certguard-*` passa a se comparar com a versão publicada na aba Computadores.
