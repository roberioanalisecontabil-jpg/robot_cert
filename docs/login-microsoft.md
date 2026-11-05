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

1. **Ensaiar a migration numa cópia do banco** (passo 1). Antes de qualquer
   coisa no servidor.
2. **Cadastrar o aplicativo no Entra** (passo 2) e **os administradores
   cadastrarem o app autenticador** (passo 3).
3. **Código no servidor**: `atualizar-portal.ps1` (passo 4).
4. **Migration** no psql do ANALISESRV (passo 5).
5. **Variáveis** no serviço (passo 6), com `MICROSOFT_CONFERENCIA=simular`.
6. **Reiniciar** o serviço (passo 7) e conferir.
7. **Aceite** em simulação (passo 8).
8. **Avisar as pessoas** dos quatro domínios (passo 9).
9. **Virar para `aplicar`** (passos 10 e 11).

Os passos 8 e 9 podem andar juntos. O aviso deve sair antes da virada.

## 1. Ensaiar a migration numa cópia

Arquivo: `supabase/migrations/20261105100000_login_microsoft.sql`. Ela é
aditiva (colunas novas, nulas ou com valor padrão), e o código de hoje não
conhece nenhuma delas. Mesmo assim, ela troca duas restrições (`users_origem_valida`
e `user_activity_evento_valido`), e uma restrição que não aceita o que já está
gravado falha no servidor, não na cópia errada.

Na máquina de desenvolvimento ou numa cópia do banco do ANALISESRV (`pg_dump`
do banco de produção, restaurado num banco de teste):

1. Rodar a migration **duas vezes seguidas**. A segunda tem de terminar sem
   erro (ela é idempotente).
2. No passo **6a** (o `SELECT evento, count(*) ...`), o resultado tem de ser
   **nenhuma linha**. Se aparecer alguma, algum evento já gravado não está na
   lista nova e o `ADD CONSTRAINT` do 6b falharia. Na cópia isso mostra o
   problema sem custo. No servidor, pare e avise o desenvolvimento.
3. Rodar os três `SELECT` da seção "Conferência" no fim do arquivo: 5 colunas
   em `users`, o índice `users_microsoft_oid_unico`, e as duas restrições com
   os valores novos (`microsoft` em `users_origem_valida`).

**Estado em 04/11/2026: o ensaio ainda não foi feito.** A máquina de
desenvolvimento não tinha Postgres funcionando. Não aplique no servidor antes
de ele ser feito.

## 2. Aplicativo no Entra

Aplicativo **novo, só do CertGuard**. Não reaproveitar o do CRM nem o do envio
de e-mail (`docs/envio-microsoft-365.md`): aquele tem `Mail.Send` de
aplicativo, e este não deve herdar nada disso.

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

## 4. Código: atualizar-portal.ps1

Ramo `feat/login-microsoft` revisado e mesclado, depois o `atualizar-portal.ps1`
no ANALISESRV, como em qualquer atualização do portal.

Neste ponto nada muda para ninguém: sem as variáveis o botão não aparece. **Não teste o botão** antes da migration (passo 5): o código novo lê colunas
que ainda não existem.

## 5. Migration no ANALISESRV

Só o Robério aplica. No psql do servidor (porta 5433; fora do PATH, usar o
caminho completo do `psql.exe`), **em passos**, colando o arquivo em blocos:

1. Colunas, índice e comentário (seções 1 a 4 do arquivo).
2. Origem `microsoft` (seção 5).
3. Eventos de atividade: **6a primeiro**. Tem de voltar **sem linhas**. Se
   voltar alguma, pare e não rode o 6b. Só então o **6b**.
4. Os `SELECT` da seção "Conferência". Conferir: 5 colunas em `users`; o
   índice `users_microsoft_oid_unico`; `users_origem_valida` com `microsoft`;
   `user_activity_evento_valido` com `conta_criada_microsoft`,
   `desativada_microsoft` e `microsoft_desligada`.

O cabeçalho do arquivo diz que o `atualizacao_push.ps1` aplica as migrations.
Vale para o fluxo antigo; para esta, o combinado é o psql, em passos, depois
do ensaio (passo 1).

## 6. Variáveis no ambiente do serviço

No ANALISESRV, no serviço `AnaliseCertiDigital` (NSSM). Em PowerShell como
administrador, **uma linha de cada vez**. O `+` acrescenta ao ambiente que já
existe; sem ele o NSSM **troca tudo** e o portal perde as outras variáveis.

```powershell
nssm get AnaliseCertiDigital AppEnvironmentExtra     # ver o que já existe (e se PORTAL_BASE_URL já está lá)
nssm set AnaliseCertiDigital AppEnvironmentExtra +MICROSOFT_TENANT_ID=<ID do diretório, o GUID>
nssm set AnaliseCertiDigital AppEnvironmentExtra +MICROSOFT_CLIENT_ID=<ID do aplicativo>
nssm set AnaliseCertiDigital AppEnvironmentExtra +MICROSOFT_CLIENT_SECRET=<Valor do segredo>
nssm set AnaliseCertiDigital AppEnvironmentExtra +MICROSOFT_DOMINIOS=analisegroup.cnt.br,analisecontabil.cnt.br,ndevolution.com.br,analisegestao.com.br
nssm set AnaliseCertiDigital AppEnvironmentExtra +MICROSOFT_CONFERENCIA=simular
nssm get AnaliseCertiDigital AppEnvironmentExtra     # conferir
```

`PORTAL_BASE_URL=https://certificado.analisegroup.cnt.br` (sem barra no fim).
O convite do Acessórias já usava essa variável: veja na saída do primeiro
`nssm get` se ela existe. Se existe com esse valor, não acrescente de novo; se
tem outro valor, **pare e avise o desenvolvimento**, porque o retorno da
Microsoft é montado a partir dela.

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
nssm restart AnaliseCertiDigital
```

- A tela de login mostra o botão "Entrar com a Microsoft".
- Pelo botão, um administrador entra, sem código por e-mail. Na primeira
  entrada, conferir em Usuários que o e-mail da conta bate com o que a
  Microsoft informa (o UPN tem de ser igual ao e-mail principal; a primeira
  entrada de teste confere isso nos quatro domínios).
- Auditoria registra "Entrou pela Microsoft".

A conferência de 5 minutos usa uma trava no Postgres por rodada, então é segura
com 1 ou 2 processos (workers) do uvicorn. Nada a fazer.

## 8. Testes de aceite, ainda em simulação

Com uma **conta de teste** que tenha entrado pelo botão uma vez:

1. **Bloqueio.** No Entra, bloqueie a entrada da conta de teste (Usuários →
   a conta → Editar → "Bloquear entrada"; tirar só a licença não é percebido).
   Em até 5 minutos (mais, se o `simular` já avisou hoje), os administradores
   recebem o e-mail "Simulação da conferência da Microsoft: seriam
   desativadas", com a conta e o código `AADSTS50057`. A conta **continua
   ativa** no CertGuard.
2. **Senha trocada.** Desbloqueie a conta, entre pelo botão de novo e troque a
   senha dela no Microsoft 365. A conta **não** deve aparecer na lista de
   simulação: ela só fica marcada "sem conferência" em Usuários, até a pessoa
   entrar pela Microsoft de novo. Trocar a senha do Outlook jamais pode
   desativar alguém.
3. Registrar o resultado. Só com os dois resultados certos siga para o
   passo 10.

O limite de segurança vale também em simulação: com mais de 5 contas
bloqueadas numa rodada, ou com erro do próprio aplicativo (segredo vencido,
ID errado), o serviço não simula nem desativa nada e avisa o TI.

## 9. Avisar as pessoas

Antes da virada, avisar quem tem conta nos quatro domínios (por e-mail ou
pelo canal da empresa):

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

## 10. Virar para `aplicar`

Só depois do aceite do passo 8 e do aviso do passo 9:

O NSSM não troca uma variável isolada. O jeito simples: ler a lista com
`nssm get AnaliseCertiDigital AppEnvironmentExtra`, remover a linha
`MICROSOFT_CONFERENCIA=simular` e regravar tudo com o `nssm set ...
AppEnvironmentExtra "linha1" "linha2" ...`, com `MICROSOFT_CONFERENCIA=aplicar`
no lugar. Ou, pela interface: `nssm edit AnaliseCertiDigital`, aba
**Environment**, trocar a linha. Depois:

```powershell
nssm restart AnaliseCertiDigital
```

## 11. Aceite depois de `aplicar`

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
avisado.

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

Apagar as variáveis `MICROSOFT_*` (ou só `MICROSOFT_CLIENT_SECRET`) e
reiniciar:

```powershell
nssm restart AnaliseCertiDigital
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

Os três de aplicativo (`7000215`, `7000222`, `700016`) travam a conferência por
completo: ninguém é desativado até corrigir.

Sintoma sem código: **todo login falha com "Não foi possível entrar com a
Microsoft agora."** Conferir se `MICROSOFT_TENANT_ID` é o GUID e não o domínio.
