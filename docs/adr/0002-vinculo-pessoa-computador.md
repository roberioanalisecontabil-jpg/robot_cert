---
status: accepted
date: 2026-10-07
---

# Vínculo pessoa–computador no portal de certificados, sem login de pessoa no Hardlyze

Até 07/10/2026 o portal descobria "a máquina da pessoa" perguntando ao Hardlyze (INVENT)
quais máquinas vivas tinham aquele e-mail. O vínculo só existia porque a pessoa entrava na
bandeja do agente do Hardlyze com **e-mail e senha do Hardlyze**; o e-mail precisava existir
igual nas duas bases; e só a bandeja logada com essa conta recebia o comando de instalação,
pela fila do Hardlyze. O login do Hardlyze era exigido para descobrir a máquina, para
autorizar a entrega e para dizer se a máquina estava viva. Além disso, `/prepare` não
conferia que a máquina pedida era da pessoa e `/claim` não conferia qual máquina buscava.

Decidimos separar os dois papéis. O **Hardlyze cuida da máquina**: ela se registra com a
autorização do próprio Hardlyze e se identifica pela credencial de máquina; contas do
Hardlyze ficam para quem administra o portal do Hardlyze. O **portal de certificados cuida de
quem instala onde**: a bandeja da estação entra com a conta do portal de certificados
(Operador, Gestor ou Administrador), o vínculo pessoa ↔ computador é guardado aqui, e todo
vínculo novo fica **pendente até o Administrador autorizar** (Usuários › Computadores, aviso
no sino). A fila de instalação passa a ser do portal de certificados; a ponte de segredo
compartilhado com o Hardlyze sai do caminho da chave privada.

## Regras

- **Principal**: a máquina de trabalho, uma por pessoa. É o vínculo que o Hardlyze mostra como
  responsável da máquina, consultando este portal.
- **Temporário (empréstimo)**: a pessoa entra na bandeja de outra máquina (colega, máquina
  cedida). O Administrador autoriza como Empréstimo, com prazo (fim do dia, 3 ou 7 dias), ou
  como Nova máquina principal (troca de equipamento; a antiga perde o dono e fica no
  histórico). O empréstimo termina ao voltar à principal, ao sair da bandeja emprestada ou no
  prazo, e nunca muda o responsável no Hardlyze.
- **Um acesso por vez**: entrar em outra máquina desativa a anterior na hora, antes da
  autorização. Reconectar a mesma pessoa na mesma máquina já autorizada não pede autorização;
  o dono principal sempre retoma a própria máquina (e encerra o empréstimo de outro nela).
- **Onde instala**: Operador e Gestor, só no computador ativo deles; Administrador, em
  qualquer computador (o certificado vai para a sessão Windows de quem está logado na bandeja
  daquela máquina). Sem computador, a pessoa usa o portal normalmente e o botão explica.
- **Validade**: o login da bandeja vale até sair, ser desvinculado, ter a conta desativada ou a
  senha redefinida; não expira por tempo.
- **Servidor confere**: `/prepare` só aceita a máquina ativa da pessoa (ou qualquer, para o
  Administrador); a busca do certificado exige a credencial do dispositivo daquela máquina.

## Opções consideradas

- **Continuar copiando o vínculo do Hardlyze**: mantém a dependência do login do Hardlyze e o
  e-mail duplicado nas duas bases.
- **Dois logins na bandeja** (Hardlyze e certificados): dobra o atrito e não resolve "usuário do
  Hardlyze = computador".
- **Um programa novo do portal de certificados em cada estação**: dobra instalação e
  manutenção em ~60 máquinas; a bandeja do agente do Hardlyze já está lá e ganha o novo login.
- **Responsável preenchido à mão no Hardlyze**: duas fontes para "quem usa esta máquina" que
  divergiriam.

## Consequências

- Agente do Hardlyze **2.1.0** (inclui o 2.0.2: log próprio da bandeja e instância única): a
  bandeja entra no portal de certificados e busca nele as instalações; o serviço continua no
  inventário com a credencial da máquina. Rollout em lotes de 10 pelo servidor.
- Transição com os dois caminhos aceitos até todas as estações estarem na 2.1.0; os vínculos
  atuais do Hardlyze viram pedidos pendentes já preenchidos. Depois: corte da ponte antiga e do
  login de pessoa na bandeja do Hardlyze.
- Reaproveita o registro de dispositivo por e-mail e senha do portal (`app/agent_devices.py`),
  parado desde agosto.
- Vem antes da Leva D (sessão em cookie).

## Adendo (08/10/2026): independência do Hardlyze

Decidido depois do primeiro teste com operador. Na estação, `Failed to resolve` era rede ou VPN,
não a aprovação pendente no Hardlyze.

- A aprovação da máquina no Hardlyze vale só para o inventário. Instalar certificado depende
  apenas da autorização em Usuários › Computadores: uma máquina pendente, recusada ou ausente
  no Hardlyze recebe certificado se estiver autorizada aqui. A bandeja 2.1.0 já não espera a
  aprovação do Hardlyze, e este portal não o consulta no login, na autorização nem na
  instalação.
- Continua um instalador só (o do Hardlyze), com o serviço de inventário e a bandeja de
  certificados separados por dentro.
- O caminho antigo (fila de comandos e login de pessoa do Hardlyze) fica até todas as estações
  estarem no 2.1.x e então sai.
- A publicação na internet fica para depois. Para instalar fora do escritório basta este portal
  estar acessível; o Hardlyze fora da VPN afeta só o inventário. O usuário fornece o
  certificado quando for o momento.
