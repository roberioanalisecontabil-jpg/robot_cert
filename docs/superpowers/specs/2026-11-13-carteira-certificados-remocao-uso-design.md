# Carteira por certificado, remoção nas estações e registro de uso

Data: 13/11/2026. Cronograma 6.4.2, 6.4.3 e 6.4.4; Demandas D-0144, D-0145 e D-0146.

## Por quê

Na contabilidade, muita gente tem acesso aos certificados. O portal já limita quem pode instalar, pela carteira. Faltam três coisas:

1. Liberar um certificado para várias pessoas sem depender do Acessórias. O caso típico é o certificado da contadora (Neuzete), que tem procurações e que quase todos usam, mesmo sem constar na carteira que vem do Acessórias.
2. Fazer valer a saída da carteira. Hoje o certificado continua instalado na máquina depois que a pessoa perde o direito.
3. Saber quem usou qual certificado, quando e em quê.

São três frentes, entregues nesta ordem: **A** (aba Certificados), **B** (remoção) e **C** (registro de uso). A prova da frente C pode rodar em paralelo. A frente B depende da A, porque sem a liberação manual cadastrada a remoção tiraria da máquina de todos o certificado da Neuzete.

## Objetivos, fora de escopo e anti-objetivos

**Objetivos**
- A: aba "Certificados" em Carteiras para liberar um certificado para várias pessoas, com prazo opcional.
- B: a bandeja remove da estação o certificado que saiu da carteira da pessoa.
- C: registro, no portal, do uso dos certificados nas estações.

**Fora de escopo**
- Limitar o uso do certificado a certos sites ou programas. O Windows não oferece isso com o certificado instalado na máquina. É uma decisão futura (ambiente central por RemoteApp), não parte deste trabalho.
- Modo lote na aba Certificados: vários certificados para várias pessoas de uma vez. O usuário escolheu a opção A, um certificado por vez.

**Anti-objetivos** (falharia mesmo funcionando)
- Remover um certificado de quem tem o direito de usá-lo. O pior caso é a Neuzete sumir de 20 máquinas.
- Tocar em certificados que não estão no acervo do CertGuard.
- A sincronização do Acessórias apagar uma liberação manual.

## Como é hoje (fatos do código)

- `carteira` (`supabase/migrations/20260815220000_carteira.sql`): chave `(user_id, documento)`, onde documento é o CNPJ ou CPF só com dígitos. Também tem `atribuido_por`, `atribuido_por_email`, `atribuido_em` e `origem`, que pode ser `manual`, `planilha` ou `acessorias` (o padrão é `manual`). Não tem coluna de prazo.
- Depois da virada, o Acessórias (`app/acessorias.py`, `calcular_plano`) só apaga linhas de origem `acessorias` ou de contas desativadas. Ele **converte** uma linha manual em `acessorias` quando passa a dar o mesmo par.
- O alcance já existe:
  - Gestor: edita só os Operadores dos departamentos que lidera (`cert_installer.pode_gerir`) e só os documentos ao alcance dele (`_documentos_ao_alcance`).
  - Admin: edita todos.
  - O módulo exige `require_modulo("carteiras", NIVEL_EDITAR)`.
- Retirar (`DELETE /api/carteira/{user_id}/{documento}`):
  - acesso de origem `acessorias`: vira `carteira_bloqueio`;
  - acesso manual: sai;
  - alvo Gestor (só o Admin chega a esse caso): registra uma Exceção (`app/rotas/carteiras.py:725`);
  - em qualquer caso, revoga os tokens pendentes.
- `carteira_historico`: o Acessórias grava, e Retirar uma linha de origem `acessorias` grava `saida`/`bloqueio` (`app/acessorias.py:1112`). Atribuir e Retirar de linha manual não deixam histórico. O CHECK de `carteira_historico.origem` já aceita `manual`, `papel`, `desativacao` e `bloqueio`.
- A página Carteiras (`templates/carteiras.html`) é mestre-detalhe por pessoa e não tem abas. O componente de abas da casa é `.ag-abas`, com `?aba=` (veja `templates/configuracao.html`).
- Bandeja (`estacao/`):
  - Roda na sessão do usuário, aberta no logon pela chave Run do HKLM.
  - Consulta o portal a cada 20 s (`GET /api/estacao/situacao`, `/api/estacao/instalacoes`).
  - Instala com `certutil -f -user -p … -importpfx My … NoExport`.
  - Não guarda o que instalou. Só conhece o `fingerprint` SHA-256 que vem no pacote.
- Cofre `cert_pfx_store`: tem `fingerprint` SHA-256, `documento` e `not_after`. A trilha `install_log` tem os eventos SOLICITADO, REDIMIDO, CONCLUIDO e ERRO.

## Frente A — aba Certificados em Carteiras

**Decidido pelo usuário**
- A aba "Certificados" fica ao lado de "Pessoas" e segue o mesmo formato mestre-detalhe, um certificado por vez (opção A do esboço).
- À esquerda: lista de certificados com busca por nome, CNPJ ou CPF. Cada linha mostra o tipo (e-CNPJ ou e-CPF), o vencimento e quantas pessoas podem usá-lo.
- À direita: quem pode usar o certificado. Cada linha mostra a origem do acesso ("Acessórias", ou "manual · por quem · quando · até quando"). A tela tem os botões "Incluir pessoas" e "Retirar".
- A regra de quem pode liberar é a atual: o Gestor libera para os colaboradores dele e o Admin para todos.
- Prazo da liberação manual: **indefinido** (vale até alguém retirar) ou **período escolhido no calendário**, de no máximo **700 dias**. Quando o período acaba, a liberação sai da carteira sozinha.
- A sincronização do Acessórias não apaga a liberação manual.

**Escolhas minhas** (o usuário aceitou a sugestão em geral; confira os detalhes)
- A unidade da lista é o **documento** (CNPJ ou CPF), porque a carteira é por documento. Se o documento tiver mais de um arquivo no cofre (renovação), aparece uma linha só, com o vencimento do mais novo.
- A lista do Gestor mostra os documentos ao alcance dele, que é a regra atual de Atribuir. Os botões aceitam só pessoas que ele pode gerir.
- O prazo começa hoje por padrão, e dá para escolher uma data de início futura. Os 700 dias contam a partir do início. Antes do início, a liberação ainda não vale: não aparece na bandeja e não instala.
- O prazo vale só para a origem manual. Acessórias e planilha não têm prazo.
- Dá para mudar o prazo de uma liberação existente, para prorrogar ou encurtar, dentro dos mesmos 700 dias contados da nova data de início.
- Quando o Acessórias passa a dar um par que já era manual com prazo, a conversão para `acessorias` continua como hoje e o prazo é descartado, porque o Acessórias passa a mandar. Se depois o Acessórias tirar esse acesso, ele sai: o manual não volta.
- Toda entrada e saída feita pela aba, pela aba Pessoas ou pelo vencimento do prazo passa a ser gravada em `carteira_historico`. O `carteira_historico.origem` ganha o valor `prazo` (o CHECK é ampliado; `manual` já existe). A aba Pessoas mostra o prazo nas linhas manuais.
- O vencimento do prazo é aplicado por um laço no servidor, a cada 5 minutos, no mesmo estilo do `acessorias_loop`. Ele apaga a linha vencida, grava o histórico (`saida`, origem `prazo`) e revoga os tokens pendentes. As leituras de carteira também ignoram linhas fora do período, para o efeito não esperar o laço.
- Modelo de dados: colunas `valido_desde` (data, padrão hoje) e `valido_ate` (data, nula quando o prazo é indefinido) na `carteira`, com CHECK `valido_ate - valido_desde <= 700`. A migration segue a ordem da casa: código, depois migration, depois `.sql` pelo deploy.

## Frente B — remoção nas estações

**Decidido** (proposta aceita pelo usuário)
- **Quando:** na próxima conversa da bandeja com o portal. Máquina desligada remove quando voltar, e o portal mostra "remoção pendente".
- **O quê:** só os certificados do acervo do CertGuard cujo documento não está na carteira em vigor da pessoa. Sai qualquer cópia, inclusive uma instalada por fora (PFX de pendrive). Certificado fora do acervo nunca é tocado.
- **Onde:** só no repositório `CurrentUser\My` do perfil logado. O agente não mexe no perfil de outra pessoa (veja "Conta desativada").
- **Aviso:** depois de remover, a bandeja mostra "Certificado X removido: saiu da sua carteira". Para liberação com prazo, avisa alguns dias antes ("vence em 3 dias, fale com seu gestor").
- **Registro:** a trilha ganha "Removido", com o motivo (prazo vencido, retirado por fulano, saiu no Acessórias). A carteira e o painel mostram isso.
- **Ligar com cuidado:**
  1. A frente A vai ao ar e as liberações manuais são cadastradas.
  2. A remoção roda em **modo só relatório** por uma ou duas semanas: o portal lista o que removeria, sem remover.
  3. O usuário confere a lista e liga a remoção de verdade.

**Escolhas minhas**
- "Carteira em vigor" quer dizer **fora de `documentos_ao_alcance`** (`app/cert_installer.py`), a mesma regra que decide quem pode instalar. Não é "fora da tabela `carteira`":
  - Admin tem alcance total e nunca perde nada.
  - Gestor perde só o que estiver nas Exceções dele.
  - Operador perde o que não está na carteira em vigor (incluindo o prazo).
- Retirar na aba Certificados chama a mesma rota e tem o mesmo efeito da aba Pessoas:
  - acesso de origem `acessorias`: vira bloqueio;
  - acesso manual: sai;
  - alvo Gestor (só Admin): registra Exceção. Do mesmo jeito, "Incluir pessoas" com alvo Gestor equivale a tirar a Exceção (`remover_excecao`).

  O bloqueio e a Exceção também contam como motivo de remoção ("retirado por fulano").
- Como identificar o certificado:
  - A bandeja lê o `CurrentUser\My`, calcula o SHA-256 do certificado (DER) de cada item e manda a lista ao portal.
  - O portal devolve quais remover: os fingerprints que estão no cofre e cujo `documento` não está na carteira em vigor da conta.
  - O portal não manda à estação a lista do acervo.
- A conferência roda no logon e depois a cada 5 minutos. Os 20 s atuais continuam só para as instalações.
- O aviso de vencimento sai 3 dias antes, uma vez por dia, só para liberações manuais com prazo.
- **Duas chaves** na Configuração (decidido pelo usuário em 13/11), cada uma com `desligado`, `relatorio` e `ligado`: uma para a regra da carteira, a conta desativada e a máquina recusada; outra só para o perfil sem login, que pode ficar mais tempo em relatório. O padrão é `desligado` até o deploy, depois `relatorio`. Só o Admin muda as chaves.
- A remoção apaga o certificado **e a chave privada**. O jeito exato fica com o builder (por exemplo `Remove-Item Cert:\CurrentUser\My\<thumb> -DeleteKey`).
- Eventos novos em `install_log`:
  - `REMOVIDO`, com o motivo;
  - `REMOCAO_PENDENTE`, ou um estado calculado;
  - `REMOVERIA`, no modo relatório.
- Exige uma versão nova da bandeja. A atualização automática já existe.

### Conta desativada

**Decidido pelo usuário** (13/11)
- Não existe perfil do Windows compartilhado entre pessoas.
- Conta desativada no portal: a bandeja remove do perfil **todos** os certificados do acervo, inclusive os que estavam na carteira.
- Usuário do Windows que passa para outra pessoa (máquina aprovada no portal como principal ou empréstimo para o novo colaborador): ao logar, a remoção normal da frente B tira o que não está na carteira do novo dono. Os certificados do antigo saem aí.
- Usuário de domínio desativado ou usuário local apagado: ninguém mais entra no perfil, e a chave privada (DPAPI) só abre com a senha daquela conta. O agente não mexe em perfil de outra pessoa.
- Nada se reinstala sozinho. Instalar continua sendo trabalho manual do colaborador.

**Fatos do código** (verificados em 13/11)
- O vínculo (`computador_vinculo`, `agent_devices`) é por par (pessoa, máquina). O portal não guarda o perfil do Windows. Quem guarda é o próprio perfil: `%LOCALAPPDATA%\CertguardAnalise\conta.dat` (e-mail, `machine_id` e o segredo do dispositivo).
- Desativar (Usuários, `app/rotas/usuarios.py:1177`; Microsoft, `app/microsoft_conferencia.py`; Acessórias, `app/acessorias.py:747`) chama `computadores.sair_de_tudo`. Ele marca `revogado_em` nas linhas de `agent_devices`. A linha e o `segredo_hash` continuam no banco.
- A bandeja recebe 401 e `estacao/conta.py:_get` apaga o `conta.dat` na hora. Depois disso, o perfil não sabe mais quem era. Se a revogação falhou, a rota devolve 403 ("Conta sem acesso ao portal"), e a bandeja trata isso como erro genérico.
- A `chave_maquina` é usada no registro e em `POST /api/estacao/atualizacao/evento` (`app/rotas/atualizacao.py:82`), que autentica por `computadores._maquina_provada` com limite de requisições (`_limitar`). As rotas novas sem conta seguem esse padrão. Todo usuário da máquina consegue ler a chave.
- Também revogam o segredo com a conta ativa: senha redefinida ou trocada (`usuarios.py:1003`, `:1447`, `:1530`), a pessoa entrar em outra máquina (`computadores.py:350`), outra pessoa entrar com prova na máquina (`_so_ela_na_maquina`, `:338`), recusar (`:443`) e desvincular (`:452`). Revogado não quer dizer desativado. Empréstimo vencido não revoga: a vigência é calculada.
- O cofre aceita `documento` nulo (`20260803_cert_installer.sql:11`). Item sem documento nunca é removido. Falha ao ler a carteira (`CarteiraIndisponivel`) nunca leva a remover.

**Último dono do perfil** (decidido pelo usuário em 13/11, depois da revisão)

A sessão cai com a conta ativa em vários casos. Se o perfil virasse "sem login", quem tem direito perderia certificados. Por isso:

- Ao receber 401 ou 403, a bandeja **não apaga** o `conta.dat`. Ela o marca como "sessão encerrada" e guarda quem era o último dono do perfil. A tela pede para entrar de novo, como hoje.
- Enquanto não houver login novo, a conferência usa uma rota nova. A rota leva o segredo revogado, a `chave_maquina` e a lista de SHA-256 do `CurrentUser\My`. O portal aceita o segredo revogado **só nessa rota**, e a rota só sabe mandar remover: um segredo vazado não instala nem lê nada.
- O portal decide pelo último dono:
  - conta **desativada**, de qualquer origem (Usuários, Microsoft ou Acessórias): sai tudo do acervo, sem prazo. Motivo na trilha: "conta desativada";
  - conta ativa e vínculo **recusado ou desvinculado**: 7 dias de aviso contados da recusa ou do desvínculo, depois sai tudo do acervo. Se a máquina for aceita de novo no prazo, o aviso some;
  - conta ativa e vínculo em vigor ou pendente (senha trocada, entrou em outra máquina, outra pessoa entrou nesta): vale a carteira do último dono, como se estivesse logado.
- Login novo no perfil substitui o último dono.
- Contra desativação em massa por erro, valem a trava que já existe no Acessórias (espera o Admin quando tiraria mais de 10% dos acessos, `LIMITE_SAIDAS` em `app/acessorias.py`) e o modo só relatório no começo.
- O mesmo vale para a máquina que estava desligada: a conferência acontece quando alguém entra nesse perfil.

### Perfil sem login na bandeja

**Decidido pelo usuário** (13/11)
- Um perfil do Windows que **nunca** teve conta do portal na bandeja (sem `conta.dat`) não fica com certificado do acervo. Isso cobre o certificado instalado por fora (pendrive) e a conta derrubada antes da versão nova, que já apagou o `conta.dat`. Perfil com último dono segue a seção anterior.
- A bandeja avisa por **7 dias** antes de remover: "Entre na bandeja do CertGuard. Sem login, os certificados da empresa serão retirados deste computador em N dias." Quem faz login no prazo passa à regra normal da carteira.
- Ao remover, o aviso diz como reinstalar. Nada se perde: o PFX continua no cofre.
- A regra também passa primeiro pelo modo só relatório. O portal lista máquina, usuário do Windows e certificados, e o TI trata caso a caso antes de ligar.

**Escolhas minhas**
- Sem conta, a bandeja fala com o portal pela `chave_maquina` e pelo `machine_id`. Manda a lista de SHA-256 do `CurrentUser\My` e o nome do usuário do Windows (só para a lista do TI). O portal responde quais desses são do acervo.
- A rota aceita máquina ainda sem chave fixada (computador nunca aprovado). Ela só diz quais dos hashes enviados estão no cofre e não devolve mais nada. O vazamento possível é confirmar que um certificado que a pessoa já tem é da empresa.
- Os 7 dias contam do primeiro aviso, e o portal guarda essa data por máquina e usuário do Windows. Se a bandeja guardasse a data no perfil, apagar o arquivo zeraria o prazo.

### Situação da máquina

**Decidido pelo usuário** (13/11). Vale só para os certificados do acervo, com a bandeja nova instalada e o modo ligado.

| Situação | Efeito |
|---|---|
| Perfil que nunca teve login na bandeja (máquina aprovada ou não) | Regra do perfil sem login: 7 dias de aviso, depois sai tudo do acervo. |
| Logado (ou último dono com conta ativa), máquina aguardando aceite | Regra da carteira: fica o que está nela, sai o resto. O aceite controla só a instalação. |
| Logado (ou último dono com conta ativa), máquina aceita | Regra da carteira. |
| Empréstimo vencido (não revoga a sessão) | 7 dias de aviso contados do fim do empréstimo, depois sai tudo do acervo. |
| Vínculo recusado ou desvinculado (revoga a sessão) | 7 dias de aviso contados da recusa ou do desvínculo, pelo último dono. Aceita de novo no prazo, o aviso some. |
| Conta desativada, de qualquer origem | Sai tudo do acervo, sem prazo. |

## Frente C — registro de uso

**Decidido:** começa por uma **prova numa máquina**, antes de qualquer código no portal. O limite por site ou programa fica fora de escopo.

**O que a prova responde**
1. Com a auditoria "Other System Events" ligada, os eventos 5058 e 5061 do log de Segurança aparecem quando o Chrome e um programa desktop (ReceitanetBX ou outro de uso real) usam o certificado? Que campos vêm (usuário, nome da chave, processo)?
2. Isso exige a chave no provedor CNG ("Microsoft Software Key Storage Provider")? O `certutil -importpfx` de hoje usa o provedor antigo, que não é auditado? Importar com `-csp "Microsoft Software Key Storage Provider"` quebra algum programa que eles usam?
3. Quantos eventos por dia uma estação gera? O volume define a coleta: resumo por hora ou evento a evento.

**Depois da prova** (desenho a fechar com o resultado)
- A bandeja lê os eventos, liga o nome da chave ao certificado instalado e envia ao portal o resumo: pessoa, máquina, certificado, programa, início e fim, quantidade.
- Tela "Uso do certificado": Admin vê todos, Gestor vê os colaboradores dele.
- Limite conhecido: no navegador o registro mostra o programa (chrome.exe), não o site.
- Ligar a auditoria nas estações exige privilégio: a tarefa SYSTEM de atualização pode fazer isso. Isso entra no desenho depois da prova.

## O que fica com o builder

- Nomes de rotas, funções e arquivos, seguindo os padrões do `app/rotas/carteiras.py` e do `estacao/`.
- O desenho fino da aba, no Águia DS. O esboço aprovado está em `.superpowers/brainstorm/…/aba-certificados.html` (opção A).
- Como paginar a lista de certificados (a casa já tem 50/100 por página).
- Testes: seguir a suíte existente. Cada regra de prazo, alcance e remoção ganha um teste. A remoção na bandeja ganha teste com repositório falso.
