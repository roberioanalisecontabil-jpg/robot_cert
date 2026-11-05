# Entrar com a Microsoft no CertGuard: roteiro de implantação

Decidido em 04/11/2026 (design em
`docs/superpowers/specs/2026-11-04-login-microsoft-design.md`). Este roteiro é
o da entrega 1, o site. A bandeja com "Entrar com a Microsoft" (entrega 2) tem
plano próprio, no repositório da bandeja.

O que muda para as pessoas:

- Contas dos quatro domínios (`analisegroup.cnt.br`, `analisecontabil.cnt.br`,
  `ndevolution.com.br`, `analisegestao.com.br`) entram no site **só pela
  Microsoft**. E-mail e senha delas é recusado com "Entre pela Microsoft.".
- Contas de fora (ex.: `@gmail.com`) entram como hoje: senha e código.
- Quem é bloqueado no Entra perde o CertGuard em até 5 minutos.

Sem as variáveis `MICROSOFT_*` e `PORTAL_BASE_URL` no ambiente, o botão não
aparece e tudo é como hoje. Por isso o código pode ir ao servidor antes do
aplicativo existir no Entra.

## Ordem

A ordem importa. Cada passo tem o seu detalhe adiante.

1. **Antes de tudo (obrigatório):** ensaiar a migration numa cópia do banco e
   rodar a conferência 6a em produção (passo 1).
2. **Cadastrar o aplicativo no Entra** (passo 2) e **os administradores
   cadastrarem o app autenticador** (passo 3).
3. **Push + `atualizar-portal.ps1`** no ANALISESRV (passo 4). O código e a
   migration vão **juntos**: ninguém roda o `.sql` à mão.
4. **Avisar as pessoas** dos quatro domínios (passo 5).
5. **Variáveis** no serviço (passo 6), com `MICROSOFT_CONFERENCIA=simular`.
6. **Reiniciar** o serviço (passo 7) e conferir.
7. **Aceite** em simulação (passo 8).
8. **Virar para `aplicar`** (passos 9 e 10).

**O aviso sai antes das variáveis.** A proibição da senha no site para os
quatro domínios começa no reinício com as variáveis (passo 7), e não na virada
para `aplicar`: `simular` só afeta a conferência de 5 minutos (desativar ou
não quem foi bloqueado no Entra). Desde o reinício, e-mail e senha dessas
contas no site recebem "Entre pela Microsoft.".

## 1. Antes do deploy: ensaio e conferência

Arquivo: `supabase/migrations/20261105100000_login_microsoft.sql`. Ela é
aditiva (colunas novas, nulas ou com valor padrão) e idempotente, mas troca duas
restrições (`users_origem_valida` e `user_activity_evento_valido`). Se o banco
tiver dado que a restrição nova não aceita, o `ADD CONSTRAINT` falha.

**A migration não é aplicada à mão.** Quem a aplica é o `atualizar-portal.ps1`
(passo 4), por meio do `db/aplicar_schema.py`: cada arquivo novo roda numa
transação própria, com o dono certo do banco, e fica registrado em
`public.schema_migrations`. Se um arquivo falha, a transação desfaz e o deploy
**aborta sem reiniciar o serviço**. Rodar o `.sql` à mão como `postgres` deixa
tabelas com dono e permissões errados e não o registra, e o deploy o rodaria de
novo.

### 1a. Conferência 6a, em produção (somente leitura)

É o `SELECT` do passo 6a do arquivo. Pode ser rodado a qualquer hora, sem
alterar nada:

```sql
SELECT evento, count(*) FROM public.user_activity
 WHERE evento NOT IN ('login', 'login_negado', 'senha_redefinida', 'conta_criada_microsoft',
                      'desativada_microsoft', 'microsoft_desligada')
 GROUP BY evento;
```

Tem de voltar **nenhuma linha**. Se voltar alguma, o `ADD CONSTRAINT` falharia, o
deploy abortaria sem reiniciar o serviço: **avise o desenvolvimento antes de
seguir**.

### 1b. Ensaio numa cópia (obrigatório)

**Estado em 04/11/2026: nada desta entrega rodou contra um Postgres de
verdade** (a máquina de desenvolvimento não tinha Postgres funcionando): nem a
migration, nem a trava da conferência (advisory lock), nem o SQL novo do
`_aplicar`. O design pede a migration "ensaiada antes numa cópia". **Não siga
para o passo 4 sem este ensaio.**

O `psql` não está no PATH do servidor: use os caminhos completos abaixo (a
pasta `C:\Program Files\PostgreSQL\17\bin` é a usual do PostgreSQL 17; confirme no
servidor). `<banco de produção>` é o nome do banco no `DATABASE_URL` do portal;
a porta é a **5433**. Quem tem o papel `postgres` faz os passos 1 a 3 e 6.
`CREATE DATABASE ... TEMPLATE` **não serve**: falha enquanto o portal mantém
conexões com o banco de produção, e levaria a parar a produção.

1. Despejar a produção num arquivo (não bloqueia o portal):
   `& "C:\Program Files\PostgreSQL\17\bin\pg_dump.exe" -h 127.0.0.1 -p 5433 -U postgres -Fc -f C:\Temp\certguard_ensaio.dump <banco de produção>`
2. Criar a cópia vazia:
   `& "C:\Program Files\PostgreSQL\17\bin\createdb.exe" -h 127.0.0.1 -p 5433 -U postgres certguard_ensaio`
3. Restaurar nela:
   `& "C:\Program Files\PostgreSQL\17\bin\pg_restore.exe" -h 127.0.0.1 -p 5433 -U postgres -d certguard_ensaio C:\Temp\certguard_ensaio.dump`
   (avisos de dono/papel inexistente na restauração são esperados na cópia).
4. Antes do deploy a pasta do portal ainda não tem a migration nova: baixar o
   código novo à parte (`git clone --depth 1 <repo> C:\Temp\certguard_codigo`) e
   rodar **duas vezes**, com a DSN da cópia **escrita por inteiro** no comando:
   `C:\Apps\robot_cert\.venv\Scripts\python.exe C:\Temp\certguard_codigo\db\aplicar_schema.py postgresql://<usuário>:<senha>@127.0.0.1:5433/certguard_ensaio`

   **A DSN da cópia é obrigatória: sem o argumento ele usa o banco de
   produção** (`DATABASE_URL`) e aplicaria a migration lá, à mão. Não omita.
5. A primeira execução mostra `  ok   20261105100000_login_microsoft.sql`. A
   **segunda** tem de terminar sem erro e dizer `Pronto: 0 arquivo(s)
   aplicado(s)` (o resto da linha traz quantas já estavam).

   Depois da segunda execução, **não inicie mais nada** contra a cópia (nem
   portal, nem serviço, nem outro script): o ensaio é só as duas execuções e a
   limpeza do item 6.
6. Apagar a cópia **e o arquivo**, que tem dados de produção:
   `& "C:\Program Files\PostgreSQL\17\bin\dropdb.exe" -h 127.0.0.1 -p 5433 -U postgres certguard_ensaio`
   (equivale a `DROP DATABASE certguard_ensaio;`) e
   `Remove-Item C:\Temp\certguard_ensaio.dump`.

## 2. Aplicativo no Entra

**Decisão do Robério (05/11/2026): o login usa o mesmo app do envio de e-mail**,
`Analise CertiDigital - envio de e-mail` (cliente
`b51ca893-20b3-464c-a9dc-23b1fd124913`, diretório
`0951afb2-5e7b-4b07-98d2-db282cde7b2f`), compartilhado com Hardlyze, DIÁRIO 2.0
e CRM. Foram acrescentados nele a URI Web abaixo, `User.Read` + `offline_access`
delegadas, a declaração `acct` (token de ID) e o segredo próprio
`certguard-login`. Custo aceito: **desativar esse app derruba o e-mail dos
quatro sistemas e o login do CertGuard juntos** (operadores sem porta reserva);
a tela da Microsoft mostra o nome do app de e-mail. Trocar ou apagar só o
segredo `certguard-login` não afeta o envio.

As instruções abaixo valem para um app novo, se um dia o login for separado.

Entra admin center → Identidade → Aplicativos → **Registros de aplicativo** →
Novo registro:

- Nome: `CertGuard Análise - Login`
- Tipos de conta: somente este diretório (locatário único)
- URI de redirecionamento: plataforma **Web**,
  `https://certificado.analisegroup.cnt.br/entrar/microsoft/retorno`. O
  endereço tem de ser **idêntico** ao que o portal monta (sem barra no fim,
  `https`, sem porta). A entrega 2 acrescentará depois o de aplicativo de
  computador (`http://localhost`); não é preciso agora.

Da visão geral, anotar o **ID do aplicativo (cliente)** e o **ID do diretório
(locatário)**.

**Permissões de API** → Microsoft Graph → **Permissões delegadas**:
`User.Read` e `offline_access`. Nada mais. Elas não precisam de consentimento
do administrador (a pessoa consente ao entrar na primeira vez, ou a tela pode
ser pré-aprovada com "Conceder consentimento do administrador", que também
vale).

**Configuração de token** → Adicionar declaração opcional → tipo de token
**ID** → marcar **`acct`**. Com ela o portal também reconhece convidado pela
declaração (`acct = 1`), além do `#EXT#` no nome de usuário.

**Certificados e segredos** → Novo segredo do cliente → descrição "portal
certificado", validade **24 meses**. Copiar o **Valor** na hora (não aparece de
novo). Guardar o Valor e a **data de validade** no cofre do TI e marcar a troca
**um mês antes** (ver "Quando o segredo vencer").

> O `MICROSOFT_TENANT_ID` é o **GUID do diretório** (ID do diretório), nunca o
> domínio. O portal compara com ele o `tid` e o `iss` do token. Com um nome de
> domínio (`analisegroup.cnt.br`) no lugar, nenhum login passa: todos falham
> fechados, com a mensagem de falha técnica.

## 3. Administradores: cadastrar o app autenticador

Antes da virada, **todo administrador** dos quatro domínios cadastra o app
autenticador (no perfil da conta). A porta reserva dos administradores é
**senha + app autenticador**; o código por e-mail não vale nela, porque chega
pelo Outlook e cai junto com a Microsoft. Administrador sem o app, se a
Microsoft cair, fica sem entrada. O painel avisa quem ainda não cadastrou.

Operadores **não têm porta reserva** (decisão do Robério, 04/11/2026): sem a
Microsoft, não entram.

A porta reserva também só vale para o administrador que **já entrou pela
Microsoft ao menos uma vez**. Por isso, na primeira entrada de cada
administrador pelo botão, o app autenticador deve estar cadastrado antes.

## 4. Push e atualizar-portal.ps1 (código e migration juntos)

Ramo `feat/login-microsoft` revisado e mesclado, push, e então o
`atualizar-portal.ps1` no ANALISESRV, como em qualquer atualização do portal.
É o `C:\Apps\atualizar-portal.ps1`; o cabeçalho da migration o chama de
`atualizacao_push.ps1`, mas é o mesmo script.
Ele traz o código e aplica a migration (por `db/aplicar_schema.py`). Se a
migration falhar, o deploy aborta sem reiniciar o serviço e o portal segue como
estava.

Neste ponto nada muda para ninguém: sem as variáveis o botão não aparece. Ao
fim, conferir na saída do script a linha
`  ok   20261105100000_login_microsoft.sql`.

## 5. Avisar as pessoas

**Antes das variáveis (passo 6)**, avisar quem tem conta nos quatro domínios
(por e-mail ou pelo canal da empresa), com a data do reinício. A proibição da
senha no site começa nesse reinício, mesmo com `MICROSOFT_CONFERENCIA=simular`:

- No site, a entrada passa a ser **pelo botão "Entrar com a Microsoft"**. E-mail
  e senha no site deixam de funcionar para essas contas.
- **Quem usa a bandeja:** a bandeja já conectada segue funcionando, com a senha
  de hoje. Para **conectar uma bandeja nova**, a pessoa precisa antes **entrar
  uma vez no site pela Microsoft**; sem isso, a bandeja responde "Entre uma vez
  no site pela Microsoft para liberar a bandeja.". Contas dos quatro domínios
  continuam usando a senha na bandeja até a entrega 2.
- Quem não tinha conta no CertGuard terá uma criada na primeira entrada:
  Operador, sem departamento, sem carteira. Os administradores recebem aviso e
  configuram.

## 6. Variáveis no ambiente do serviço

No ANALISESRV, no serviço `certguard` (conferido em 05/11/2026; o
`AnaliseCertiDigital` do GUIA_MIGRACAO é nome antigo). As variáveis ficam no ambiente do
serviço (NSSM), não no repositório.

1. Ver o que já existe (e se `PORTAL_BASE_URL` já está lá):
   `nssm get certguard AppEnvironmentExtra`
2. Abrir o editor: `nssm edit certguard` (PowerShell como
   administrador), aba **Environment**. Acrescentar **uma linha por variável**,
   sem apagar as que já estão, e clicar em **Edit service**.
3. Conferir de novo com `nssm get certguard AppEnvironmentExtra`.

`PORTAL_BASE_URL=https://certificado.analisegroup.cnt.br` (sem barra no fim).
O convite do Acessórias já usava essa variável. Se ela existe com esse valor,
não repita; se tem outro valor, **pare e avise o desenvolvimento**, porque o
retorno da Microsoft é montado a partir dela.

| Variável | Valor |
|---|---|
| `MICROSOFT_TENANT_ID` | GUID do diretório. **Não** o domínio. |
| `MICROSOFT_CLIENT_ID` | ID do aplicativo (cliente) |
| `MICROSOFT_CLIENT_SECRET` | Valor do segredo (passo 2) |
| `MICROSOFT_DOMINIOS` | Os quatro domínios, separados por vírgula, minúsculas |
| `PORTAL_BASE_URL` | `https://certificado.analisegroup.cnt.br` |
| `MICROSOFT_CONFERENCIA` | `simular` (começa assim) ou `aplicar` |

Faltando **qualquer** uma das cinco primeiras, o login pela Microsoft fica
todo desligado e o login é o de hoje. `MICROSOFT_CONFERENCIA` só aceita o valor
exato `aplicar` para desativar contas; qualquer outro valor, ou a ausência da
variável, é `simular`.

O segredo fica no ambiente do serviço, nunca no repositório nem no `.env`
versionado.

## 7. Reiniciar e conferir

```powershell
nssm restart certguard
```

- A tela de login mostra o botão "Entrar com a Microsoft".
- Pelo botão, um administrador entra, sem código por e-mail. Na primeira
  entrada, conferir em Usuários que o e-mail da conta bate com o que a
  Microsoft informa (o UPN tem de ser igual ao e-mail principal; a primeira
  entrada de teste confere isso nos quatro domínios).
- Auditoria registra "Entrou pela Microsoft".

A conferência de 5 minutos usa uma trava no Postgres por rodada, então é segura
com 1 ou 2 processos (workers) do uvicorn. Nada a fazer. Com `--workers 2`, os
e-mails ao TI e os de simulação podem chegar **em dobro**: a memória de "já
avisei" é de cada processo. É inofensivo.

## 8. Testes de aceite, ainda em simulação

Com uma **conta de teste** que tenha entrado pelo botão uma vez:

1. **Bloqueio.** No Entra, bloqueie a entrada da conta de teste (Usuários →
   a conta → Editar → "Bloquear entrada"; tirar só a licença não é percebido).
   Em até 5 minutos (mais, se o `simular` já avisou hoje), os administradores
   recebem o e-mail "Simulação da conferência da Microsoft: seriam
   desativadas", com a conta e o código `AADSTS50057`. A conta **continua
   ativa** no CertGuard.
2. **Senha trocada.** Desbloqueie a conta, entre pelo botão de novo e troque a
   senha dela no Microsoft 365. O mais provável é **nada mudar**: a troca de
   senha não revoga a chave de renovação de um aplicativo com segredo
   (confidencial), e a conferência segue dando "ok". Pode também aparecer a
   marca "sem conferência" em Usuários, até a pessoa entrar pela Microsoft de
   novo; as duas coisas estão certas. O que **não** pode é a conta aparecer na
   lista de simulação: trocar a senha do Outlook jamais pode desativar alguém.
3. **Bloquear entrada + Revogar sessões.** Entre pelo botão de novo e, no
   Entra, na mesma conta, faça "Bloquear entrada" e "Revogar sessões". O
   esperado é o e-mail de simulação com `AADSTS50057`, como no caso 1. A
   simulação avisa cada conta uma vez por dia: use uma segunda conta de teste,
   ou faça este caso no dia seguinte ao caso 1.

   **Se em vez disso a conta ficar "sem conferência" em Usuários e não entrar na
   lista de simulação** (no log, `AADSTS50173`), **pare e avise o TI antes de
   `aplicar`**: a revogação apaga a chave antes de o bloqueio ser visto, e a
   conta bloqueada não seria desativada. Nesse caso o desligamento de alguém
   passa a ser **só "Bloquear entrada", sem revogar antes**, ou o código tem de
   ser revisto.
4. Registrar o resultado. Só com os três resultados certos siga para o
   passo 9.

O limite de segurança vale também em simulação: com mais de 5 contas
bloqueadas numa rodada, ou com erro do próprio aplicativo (segredo vencido,
ID errado), o serviço não simula nem desativa nada e avisa o TI.

## 9. Virar para `aplicar`

Só depois do aceite do passo 8 (o aviso do passo 5 já saiu): `nssm edit
certguard`, aba **Environment**, trocar a linha
`MICROSOFT_CONFERENCIA=simular` por `MICROSOFT_CONFERENCIA=aplicar`, **Edit
service**, e conferir com `nssm get certguard AppEnvironmentExtra`.
Depois:

```powershell
nssm restart certguard
```

## 10. Aceite depois de `aplicar`

1. **Administrador** entra pelo botão da Microsoft.
2. **Operador de um dos quatro domínios**, com e-mail e senha, recebe "Entre
   pela Microsoft.".
3. **Conta de fora** (ex.: `@gmail.com`) entra com senha e código, como hoje.
4. **Conta de teste bloqueada no Entra** cai no CertGuard em **até 5
   minutos**: some da lista de ativos, perde sessões e bandeja, e a auditoria
   registra "Desativado: conta bloqueada na Microsoft". A reativação é só pelo
   administrador, em Usuários.
5. **Administrador** com senha + app autenticador entra pela porta reserva
   (auditoria: "Entrou com senha e app autenticador").

A desativação pela Microsoft vence o Acessórias: o sincronismo não reativa a
conta. O último administrador ativo nunca é desativado; nesse caso só o TI é
avisado. **Atenção:** esse administrador, bloqueado no Entra, continua ativo no
CertGuard e mantém a porta reserva (senha + app autenticador). O TI resolve à
mão: nomear outro administrador ativo; a rodada seguinte da conferência
desativa este (ou desative-o em Usuários).

## Conta duplicada na primeira entrada

Se o UPN **e** o e-mail da Microsoft forem diferentes do e-mail da conta no
CertGuard (ex.: `joao.silva@` no CertGuard e `jsilva@` na Microsoft), a
primeira entrada pelo botão **cria uma conta nova de operador** em vez de usar
a antiga. Não existe rota para apagar conta. Para corrigir, em Usuários:

1. Na conta duplicada (a nova, "Nova pela Microsoft"): **Desfazer ligação com a
   Microsoft**, trocar o e-mail dela por um que não seja usado (ex.:
   `duplicada.jsilva@...`) e **desativar**.
2. Na conta antiga: trocar o e-mail para o UPN da Microsoft (`jsilva@...`).
3. Pedir à pessoa que entre pelo botão de novo: a conta antiga se liga.

## Cloudflare e Caddy

A rota de retorno tem de passar pelas regras da Cloudflare de `certificado.`
(`docs/publicacao-na-web.md`, passo 1). Conferir:

- O **modo geográfico** (`certificado-so-brasil`): a rota é aberta pelo
  navegador da pessoa, que está no Brasil. Quem estiver fora do país, ou em VPN
  com saída fora dele, não volta da Microsoft, como já não entra no portal.
- O **rate limiting** é só de `/api/login`; o retorno `/entrar/microsoft/retorno`
  não é pego por ele.
- Nenhuma regra de **cache**, **reescrita** ou **redirecionamento** pode atuar
  em `/entrar/microsoft/retorno`, nem na Cloudflare nem no Caddy. A resposta de
  sucesso é uma **página 200 com `meta refresh`**, e não um 302: o cookie de
  sessão é `SameSite=Strict`, e um redirecionamento vindo da Microsoft o
  descartaria. Cachear ou reescrever essa página perde a sessão ou entrega a
  de outra pessoa.
- A **Verificação de integridade do navegador** continua desligada para
  `certificado.`, como está.

Conferência rápida: um `curl.exe -I https://certificado.analisegroup.cnt.br/entrar/microsoft/retorno`
(sem parâmetros) deve responder uma página de erro do portal, sem `cf-cache-status: HIT`
e sem desafio da Cloudflare.

## Caminho de volta

Apagar as variáveis `MICROSOFT_*` (`nssm edit`, aba Environment; ou só `MICROSOFT_CLIENT_SECRET`) e
reiniciar:

```powershell
nssm restart certguard
```

O botão some e o login volta a ser o de hoje para todos, inclusive a obrigação
dos domínios. A migration **não precisa ser desfeita**: as colunas ficam sem
uso. Contas desativadas pela conferência **continuam desativadas**; reativar
em Usuários.

Para só **parar de desativar**, sem desligar o login: `MICROSOFT_CONFERENCIA`
volta a `simular` (ou é apagada) e reiniciar.

## Quando o segredo vencer

Um mês antes da data guardada no cofre do TI: Entra → o aplicativo →
Certificados e segredos → **novo segredo** (24 meses). Colocar o Valor novo em
`MICROSOFT_CLIENT_SECRET`, reiniciar, entrar pelo botão para testar, e só
então apagar o segredo antigo. Anotar a data nova no cofre.

Segredo vencido ou errado: a troca do código falha e a conferência trava (erro
do aplicativo): **ninguém é desativado**, o TI recebe o aviso "Conferência da
Microsoft travada", e os administradores entram pela porta reserva (senha +
app) até a troca.

## Erros que o log mostra

No `logs\portal_stderr.log` do serviço, linhas `Microsoft: ...` com o código:

| Código | O que é | O que fazer |
|---|---|---|
| `AADSTS50011` | O endereço de retorno não bate com o cadastrado | No Entra, a URI Web tem de ser exatamente `https://certificado.analisegroup.cnt.br/entrar/microsoft/retorno`; conferir `PORTAL_BASE_URL` |
| `AADSTS7000215` | Segredo do cliente inválido (valor errado, ou foi colado o ID do segredo em vez do Valor) | Gerar segredo novo e colar o **Valor** |
| `AADSTS7000222` | Segredo vencido | Trocar o segredo (seção acima) |
| `AADSTS700016` | Aplicativo não encontrado no diretório | Conferir `MICROSOFT_CLIENT_ID` e `MICROSOFT_TENANT_ID` |
| `AADSTS50057` / `AADSTS50034` | Conta bloqueada ou inexistente: é o que a conferência trata como "desativar" | Esperado no aceite; fora dele, conferir a conta no Entra |

Na conferência de 5 minutos (`renovar`), os três de aplicativo (`7000215`,
`7000222`, `700016`) travam a rodada por completo: ninguém é desativado até
corrigir. No login pelo botão eles aparecem só como falha da entrada (a mensagem
de falha técnica), sem trava.

Sintoma sem código: **todo login falha com "Não foi possível entrar com a
Microsoft agora."** Conferir se `MICROSOFT_TENANT_ID` é o GUID e não o domínio.

## Entrega 2: bandeja pela Microsoft

A bandeja 1.2.0 ganha o botão "Entrar com a Microsoft" na janela de login. O
navegador abre a Microsoft, volta para um ouvinte em `127.0.0.1` (porta
aleatória, um retorno, 300 s) e a bandeja troca o código de uso único (120 s)
pelo registro do computador. A URI de retorno no Entra **não muda**. Depois que
todas as bandejas ativas estiverem na 1.2.0, a senha deixa de valer na bandeja
para os quatro domínios (a "virada").

Ordem de produção:

1. **Push + `atualizar-portal`.** Aplica `20261106100000_bandeja_pela_microsoft.sql`
   (pelo `db/aplicar_schema.py`; nunca à mão). Conferir na saída
   `  ok   20261106100000_bandeja_pela_microsoft.sql`. Nada muda para ninguém: a
   virada só vale com a Microsoft configurada e com dispositivos na 1.2.0.
2. **Publicar a 1.2.0** pelo Robério, na máquina de build, com
   `scripts/versoes_certguard.py publicar --instalador dist_estacao\Instalador_CertguardAnalise_1.2.0.exe`
   e depois `deploy\publicar-certguard.ps1`. A atualização automática leva as
   bandejas à 1.2.0. Na primeira estação, conferir à mão que a janela abre com o
   botão e que, num portal sem as variáveis `MICROSOFT_*`, o botão some.
3. **Acompanhar Usuários › Computadores.** Ver as versões `certguard-x.y.z`
   subindo. Só contam dispositivos não revogados vistos nos últimos 30 dias.
4. **A virada acontece sozinha** quando nenhum dispositivo desses estiver abaixo
   da 1.2.0 (e houver ao menos um na nova). O portal manda e-mail ao TI. Daí em
   diante, e-mail dos domínios na bandeja recebe 403 "Use Entrar com a
   Microsoft.", com a senha certa ou errada.
5. **Voltar a senha para todos:** tirar as variáveis `MICROSOFT_*` e reiniciar, a
   mesma chave geral da entrega 1. Com as variáveis de volta, a virada volta a
   valer.

Limite do loopback: o ouvinte atende só estações com a pessoa na própria sessão
do Windows, uma pessoa por sessão. Servidor de terminal com várias sessões
simultâneas não é caso suportado.
