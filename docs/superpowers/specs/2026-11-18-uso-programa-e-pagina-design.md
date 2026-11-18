# Uso dos certificados: programa e página (Frente C, parte 2)

Design de 18/11/2026. Continua `2026-11-13-carteira-certificados-remocao-uso-design.md`, seção da Frente C.

## Por que

A aba Carteiras › Uso já mostra **quando** cada certificado foi usado, **por quem** e **em qual máquina**. Ela não mostra **onde** foi usado. O Robério precisa disso para saber se alguém está violando as regras de uso. Os exemplos que ele confirmou foram três: usar o certificado de um cliente num portal que não tem relação com o serviço, usar um programa não autorizado e usar fora do horário.

Em 15/11 ele tinha dito que o programa não importava. Mudou de ideia em 18/11. A coluna "Sistema/Página" já existe na aba e mostra "—" desde então.

## O que se quer

- O administrador vê, em cada linha de uso, o programa e a página em que o certificado foi usado, por exemplo "Chrome · eCAC - Centro Virtual de Atendimento" ou "Acrobat · Relatório de integridade da aparência".
- **Ele julga caso a caso.** Não há regras cadastradas, alertas ou bloqueio.
- **Só o administrador vê** essa informação. Hoje o gestor vê a aba Uso das pessoas dos departamentos que lidera; ele continua vendo a aba, mas sem programa e página.

## Fora do escopo

- Regras de permitido ou proibido por certificado, cliente, programa, portal ou horário.
- Alertas, e-mails e notificações.
- Bloquear o uso.
- Histórico do navegador e log CAPI2 (ver "Prova").
- Registrar tudo o que a pessoa faz no dia. Só sai da máquina o que está ao redor de um uso de certificado.

## Prova (18/11, TI-002)

Script `Desktop\prova-uso\prova-uso-programa.ps1`, rodado pelo usuário como administrador. Os usos feitos foram e-CAC no Chrome e uma assinatura no Acrobat, ambos com o certificado SUPERMERCADO ADRIELLE.

- **Log de Segurança.** Os eventos 5058/5061 trazem hora, usuário e contêiner da chave para os dois programas: Chrome às 08:17:44 e Acrobat às 08:17:59. São os eventos que a coleta já usa. O processo do evento é sempre o `lsass`, então não dizem o programa.
- **Janela em foco.** Anotada a cada segundo pelo script. No segundo de cada 5061 ela dizia o programa e a página:
  - 08:17:44, `chrome`, "gov.br - Acesse sua conta". A janela anterior, 4 segundos antes, era "eCAC - Centro Virtual de Atendimento".
  - 08:17:59, `Acrobat`, "Relatório de integridade da aparência".
- **CAPI2** (`Microsoft-Windows-CAPI2/Operational`). O evento 70 dá o processo (`chrome.exe`) no caso do Chrome. **Não registra nada do Acrobat**: nenhum evento com o certificado ADRIELLE vindo do `Acrobat.exe`. Gera cerca de 4.400 eventos em 10 minutos. **Descartado**, porque a janela em foco já cobre o que ele daria.
- **Limite conhecido.** Se o certificado for usado por um programa sem janela em foco, como um serviço, um robô em segundo plano ou uma aba que não está à frente, a janela anotada é a errada ou não há janela. O registro mostra o que estava na tela, não prova qual programa abriu a chave. A tela diz isso ao administrador (ver "Na tela").

## Como funciona

### Na estação

1. **Um anotador protegido, fora do alcance da pessoa** (decisão do Robério em 18/11: a pessoa não pode apagar nem forjar o registro). A bandeja **não** faz a anotação, porque roda com o usuário da pessoa.
   - **Vigia.** Uma tarefa agendada nova, como SYSTEM, sobe na partida e fica residente, no mesmo molde das tarefas de `estacao/tarefa.py` (`TAREFAS`, criadas por `preparar_atualizacao`). Ela confere as sessões interativas abertas (`WTSEnumerateSessions`) a cada poucos segundos.
   - **Anotador por sessão.** Para cada sessão ativa sem anotador, o vigia lança um processo **como SYSTEM dentro daquela sessão**, na área de trabalho `winsta0\default`. É o token SYSTEM duplicado com o `TokenSessionId` da sessão, via `CreateProcessAsUser`. Só assim ele enxerga a janela em foco, e a pessoa, sem ser administradora, não consegue encerrá-lo.
   - Se o anotador morrer, o vigia o relança na volta seguinte. Troca rápida de usuário e área de trabalho remota contam como sessões separadas.
   - O anotador confere a janela em foco a cada 1 segundo, usando `GetForegroundWindow`, `GetWindowText` e o processo dono.
   - Anota só quando muda: hora em UTC, nome do processo sem caminho (por exemplo `chrome`) e título até 300 caracteres.
   - O SID gravado é o do dono da sessão (`WTSQueryUserToken`), não o do processo, que é SYSTEM.
2. **Onde fica.** Na pasta da máquina já trancada para SYSTEM e Administradores (`atualizador.proteger_pasta`, a mesma do marcador). A pessoa não lê nem escreve ali. **Guarda 48 horas.** A tarefa de coleta roda na partida e a cada 6 horas, e a máquina pode ficar desligada entre uma coleta e outra; 48h cobre isso com folga. Linha mais velha que 48h é descartada pelo próprio anotador.
3. **A tarefa SYSTEM cruza.** Na coleta (`estacao/uso.py`, `coletar`), para cada 5061 lido, ela pega no registro do SID do evento:
   - a janela vigente no segundo do evento, isto é, a última anotada até aquele instante;
   - até 2 janelas anteriores dentro de 30 segundos antes do evento.

   Manda essas janelas junto com o evento. **Nenhuma outra janela sai da máquina.**
4. **Depois que o portal aceita o lote**, as linhas anteriores ao último evento enviado podem ser apagadas do registro, como já se faz com o marcador.

### No portal

- `POST /api/estacao/uso` passa a aceitar, em cada evento, uma lista opcional `janelas` com `quando`, `programa` e `titulo`, no máximo 3 itens, nos tamanhos acima. A bandeja antiga não manda o campo e continua funcionando.
- **Gravação.** `uso_certificado` agrega por (máquina, SID, contêiner, hora). Várias janelas cabem numa linha agregada, então elas vão para uma **tabela nova**, `uso_janela`, ligada à linha de `uso_certificado`, com `quando`, `programa`, `titulo` e o `record_id` do evento.
  - O reenvio do mesmo lote não duplica: a chave é `machine_id` + `record_id` + a ordem da janela, porque o `record_id` só é único dentro do log de uma máquina (escolha do construtor, anotada no design).
  - A guarda é a mesma de `uso_certificado`: `GUARDA` de 5 anos em `app/uso.py`, e a limpeza apaga as duas juntas.
- A migration vai em `supabase/migrations/`, aplicada pelo deploy (`db/aplicar_schema.py`), nunca à mão.

### Na tela (Carteiras › Uso)

- Para o administrador, a coluna **Sistema/Página** mostra o programa e o título da janela no momento do **último uso daquela linha**, por exemplo "chrome · gov.br - Acesse sua conta".
- Se os usos da linha tiveram programas ou páginas diferentes, aparece também "+N".
- Clicando na célula abre um detalhe com cada uso da linha: a hora, a janela no momento e as anteriores.
- No detalhe vai um aviso curto: "É a janela que estava na tela no momento do uso. Um programa em segundo plano não aparece aqui."
- Sem janela, por versão antiga na estação, anotador fora do ar ou uso antes desta versão, a célula continua "—".
- **Gestor:** a rota `/api/carteira/uso` não devolve janelas para quem não é admin. A coluna continua "—" para ele, ou some; essa escolha fica com o construtor. Isso é conferido no servidor, não só escondido na tela.

## Entrega

- O pacote da estação muda (vigia, anotador e tarefa nova), então é preciso uma **bandeja nova (1.5.0)**, publicada pelo mesmo caminho das anteriores (`lancar-certguard.ps1`). A atualização automática leva às estações. O instalador roda como admin e cria a tarefa do vigia junto com as outras.
- A coluna só se preenche nas estações que atualizaram.
- A ordem é a de sempre: portal primeiro (migration + rota que aceita `janelas` + tela) e bandeja depois.

## Riscos aceitos e pontos de atenção

- **Adulteração.** Resolvida para quem não é administrador da máquina: o anotador roda como SYSTEM e grava na pasta trancada. **Quem é administrador local** ainda pode parar a tarefa ou mexer na pasta, como já pode com o marcador. Isso não esconde o uso, porque o 5061 vem do log de Segurança; só apaga o "onde".
- **Fechar a bandeja** não para mais a anotação, porque ela não depende da bandeja.
- **Processo SYSTEM na sessão da pessoa** é poder alto. O anotador só lê a janela em foco e escreve no seu registro. Ele não abre janela, não recebe comando de fora e não carrega nada da pasta da pessoa.
- **Títulos podem ter dado pessoal**, como o assunto de um e-mail ou o nome de um arquivo. Por isso só saem as janelas ao redor de um uso e só o admin vê.
- **Aviso às pessoas:** não vai aviso na bandeja. O Robério informou em 18/11 que isso é feito formalmente em treinamentos e alinhamentos.
- **Guarda dos títulos:** a mesma do uso, 5 anos. Não foi pedido prazo menor.
- **Volume.** Na prova, um uso gerou 1 par 5058/5061. Na TI-169 houve 12 usos por certificado em 47 minutos, com dezenas de certificados. Com até 3 janelas por evento, são algumas centenas de linhas por máquina por dia em `uso_janela`. Aceitável; o construtor confere índices.

## Para o construtor decidir

- O formato do registro local: JSON lines, CSV ou SQLite, desde que sobreviva a um anotador morto no meio da escrita.
- Um arquivo por SID ou um só com o SID em cada linha.
- Se o vigia e o anotador são o mesmo executável com outro argumento, como o `--atualizacao` de hoje.
- O intervalo do vigia entre conferências de sessão.
- Gestor: esconder a coluna ou mostrar "—".
- O desenho do detalhe ao clicar, desde que siga o Águia DS dos modais existentes.
- Nomes de tabela e coluna, além dos já citados.

## Escolhas do autor do design (não do Robério)

- Conferência da janela a cada 1 s; guarda local de 48 h; até 2 janelas anteriores dentro de 30 s, 3 no total por evento; título até 300 caracteres.
- Chave contra duplicação: `machine_id` + `record_id` + ordem da janela.
- Vigia como tarefa agendada SYSTEM residente, em vez de serviço do Windows, para seguir o caminho de instalação que já existe.
- Registro na pasta já trancada do marcador.
