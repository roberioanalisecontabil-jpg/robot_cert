# Entrar com a Microsoft no CertGuard — design

Data: 04/11/2026. Decidido em conversa com o Robério (TI). Onde está escrito
**decisão do construtor**, a escolha não foi discutida com ele e pode ser
revista no plano.

Referência de origem: o roteiro `login-microsoft.md` do portal do CRM
(`crm.analisegroup.cnt.br`, Django). O CertGuard é outro sistema (FastAPI,
login com senha + código por e-mail + app autenticador, ver
`app/login_codigo.py`, `app/totp.py`, `app/rotas/usuarios.py:214`), então o
comportamento é o mesmo em espírito, o código é novo.

## Por quê

As pessoas da Análise Group já têm conta Microsoft 365. Entrar no CertGuard
com ela tira a senha separada, e — o ponto principal — quem é bloqueado na
Microsoft no desligamento perde o CertGuard junto, sem depender de alguém
lembrar de desativar a conta aqui.

## O que é

### Domínios

Lista de domínios **que entram** (não lista dos que não entram), guardada no
ambiente do servidor:

- `analisegroup.cnt.br`
- `analisecontabil.cnt.br`
- `ndevolution.com.br`
- `analisegestao.com.br`

`varejoconectado` fica de fora. Domínio acrescentado ao Microsoft 365 no futuro
fica de fora até alguém pôr na lista. Só **membros** do locatário entram;
convidado (B2B) é recusado mesmo com e-mail de domínio liberado.

### Quem entra e como

| Situação | O que acontece |
|---|---|
| E-mail de domínio liberado, já tem conta no CertGuard | Entra pela Microsoft; sessão abre direto, **sem código** |
| E-mail de domínio liberado, sem conta | Conta criada no 1º acesso: Operador, sem departamento, carteira vazia, sem senha. Entra logo e usa a ferramenta nos limites do perfil (na prática não vê clientes). Administradores avisados |
| E-mail de fora (ex.: `@gmail.com`) | Login de hoje, senha + código por e-mail/app. Sem botão Microsoft para ele (a conta Microsoft dele não é do locatário) |
| Conta desativada no CertGuard | Não entra nem pela Microsoft |

**Obrigação:** no site, contas dos quatro domínios entram **só pela
Microsoft**. E-mail + senha delas é recusado com "Entre pela Microsoft".
Única exceção: a porta reserva dos administradores (abaixo).

**Ligação da conta:** na 1ª entrada, pelo e-mail que a Microsoft informa; a
partir daí, pelo identificador fixo da pessoa na Microsoft (`oid` +
locatário). E-mail trocado lá não troca a conta aqui. Uma conta já ligada a um
`oid` não se liga a outro.

**Senha antiga:** não é apagada (a porta reserva precisa dela). Só é recusada.

### Porta reserva: só administradores

Administrador de um dos quatro domínios pode entrar também com **senha + app
autenticador** (nunca código por e-mail, que chega pelo Outlook e cai junto
com a Microsoft). Vale só para administrador que **já entrou pela Microsoft ao
menos uma vez** (está na conferência abaixo). Serve para quando a Microsoft
cai, o segredo do aplicativo vence ou o aplicativo some do Entra. Fica aberta
o tempo todo, não é chave de emergência. Auditoria registra "Entrou com senha
e app autenticador".

Não haverá variável de emergência `MICROSOFT_OBRIGATORIO` — descartada em
favor da porta reserva.

### Perda de acesso quando bloqueado na Microsoft: opção "chave de renovação"

Sem permissão de administrador global (`User.Read.All` descartada).

- No login pela Microsoft, pedir `offline_access` e guardar a chave de
  renovação (refresh token) **cifrada** no banco.
- A cada 5 minutos, um serviço tenta renovar a chave de cada conta ligada.
- **Desativa a conta inteira** (senha, sessões, bandeja — o mesmo caminho do
  Desativar de hoje, que chama `derrubar_sessoes`) **só** quando a Microsoft
  responde que a conta foi bloqueada ou apagada.
- Outras recusas (senha trocada na Microsoft, chave vencida por falta de uso,
  sessões revogadas) **não desativam**: a conta fica marcada "sem conferência"
  até a pessoa entrar pela Microsoft de novo. Sem isso, trocar a senha do
  Outlook trancaria a pessoa aqui.
- Travas: Microsoft fora do ar / segredo inválido → ninguém é desativado, TI
  avisado. Mais de 5 contas de uma vez → serviço para tudo e avisa o TI.
- Reativação só pelo admin, em Usuários.
- Auditoria: "Desativado: conta bloqueada na Microsoft".

No desligamento, o TI hoje **bloqueia a entrada** no Entra (não só tira a
licença) — é isso que a conferência percebe. Tirar só a licença não é
percebido.

Buraco conhecido e aceito: conta de domínio liberado que nunca entrou pela
Microsoft não tem chave guardada. Com a obrigação no site, ela só entra no
site passando pela Microsoft, então o buraco fica só na **bandeja** até a
entrega 2.

### Aviso ao admin

E-mail aos administradores pelo SMTP já usado pelo CertGuard ("Conta nova pela
Microsoft: fulano — falta configurar") e destaque em Usuários para contas
criadas pela Microsoft ainda sem departamento.

### Auditoria

"Entrou pela Microsoft", "Entrou com a senha", "Entrou com senha e app
autenticador", "Conta criada pela Microsoft", "Desativado: conta bloqueada na
Microsoft", e cada recusa com o motivo (domínio fora da lista, convidado,
conta desativada, `oid` diferente).

### Desligável

Sem as variáveis `MICROSOFT_*` no ambiente, o botão não aparece e o login é o
de hoje para todos (inclusive a obrigação não vale). O código pode ir para
produção antes do aplicativo existir no Entra.

## Entregas

1. **Site** — botão, criação de conta, obrigação dos domínios, porta reserva
   dos admins, conferência a cada 5 min, aviso ao admin, auditoria, migration.
2. **Bandeja** — versão nova com "Entrar com a Microsoft": abre o navegador da
   estação na página da Microsoft, a resposta volta para a bandeja e o
   CertGuard confere. Chave da máquina e vínculo pendente (ADR 0002) iguais.
   As estações entram no Windows com o domínio `ANALISE` local, sem ligação
   com a Microsoft: não há entrada automática. Programa separado (ADR 0003).

Entre as entregas, contas dos quatro domínios continuam entrando **na bandeja**
com a senha de hoje. Conta criada pela Microsoft fica sem bandeja até a
entrega 2 (nasce sem carteira, aceitável).

## Aplicativo no Entra

Aplicativo **novo, só do CertGuard**. Não reaproveitar o do CRM nem o do
envio de e-mail (`docs/envio-microsoft-365.md`, tem `Mail.Send` de aplicativo).
Um locatário só. Permissões delegadas `User.Read` + `offline_access` (sem
consentimento de admin). Retornos: Web
`https://certificado.analisegroup.cnt.br/<rota de retorno>` (entrega 1) e
aplicativo de computador `http://localhost` (entrega 2). Segredo de 24 meses,
data no cofre do TI, troca um mês antes (passo 5 do roteiro do CRM).

## Restrições

- Migration roda só pelas mãos do Robério, em passos, ensaiada antes numa
  cópia local (memória do projeto). Ordem: código → migration → `.sql`.
- Mudou `static/*.js`/`.css`: trocar o `?v=` nos templates.
- Hook de pré-commit roda a suíte inteira.
- Revisor independente a cada leva, antes do push.
- Portal está na internet pela Cloudflare (`docs/publicacao-na-web.md`): a rota
  de retorno precisa passar pelas regras de lá.

## Fora do escopo

- `User.Read.All`, consulta de todas as contas, leitura de licenças.
- Webhook da Microsoft.
- Login automático na bandeja pelo Windows.
- Contas de fora dos quatro domínios: nada muda.

## Anti-objetivos (falhou mesmo funcionando)

- Admin trancado fora quando a Microsoft cai.
- Troca de senha no Outlook desativando gente no CertGuard.
- Uma falha da Microsoft desativando muita gente de uma vez.
- Conta tomada porque alguém conseguiu um e-mail parecido / reaproveitado.

## Decisões do construtor (depois da leitura do revisor)

- **Dado que liga a conta na 1ª entrada:** `preferred_username` (UPN) e o
  claim `email`, em minúsculas, comparados por igualdade exata com o e-mail
  cadastrado. Se os dois casarem com contas diferentes, recusa e audita. Se
  nenhum casar, cria a conta. A 1ª entrada de teste confere se o UPN é igual
  ao e-mail principal nos quatro domínios.
- **E-mail reaproveitado:** o admin ganha em Usuários a ação "Desfazer ligação
  com a Microsoft". A próxima entrada por aquele e-mail liga ao `oid` novo.
  Entra na entrega 1.
- **Porta reserva:** vale para admin ativo com `oid` ligado alguma vez, mesmo
  "sem conferência" (não tranca admin por troca de senha no Outlook). Admin
  sem app autenticador fica sem porta reserva. O painel avisa o admin que
  ainda não cadastrou o app.

## Acessórias (decidido pelo Robério, 04/11)

- **Desativação pela Microsoft vence o Acessórias.** O motivo fica gravado na
  conta; `calcular_contas` (`app/acessorias.py`) não reativa conta desativada
  pela Microsoft. Só o admin reativa. Muda a regra do ADR 0005: registrar em
  adendo.
- **Conta criada pela Microsoft é adotada pelo Acessórias** quando o e-mail é
  igual ao de um usuário de lá: passa a ser gerenciada como `origem =
  acessorias` (carteira, departamento, desativação quando sai de lá). E-mail
  diferente: fica com o admin, à mão.
- Conta que já existe pelo Acessórias: o login pela Microsoft só liga o `oid`;
  o Acessórias continua cuidando dela.
- **Convite "defina sua senha" deixa de ser enviado para todos** (inclusive
  contas do Acessórias de fora dos quatro domínios). Quem já tem senha
  continua com ela.
- **Até a entrega 2:** a senha atual continua valendo **só na bandeja**. No
  site, os quatro domínios já são obrigados à Microsoft desde a entrega 1.
  Quem é dos quatro domínios e não tem senha fica sem bandeja até a entrega 2.

## Deixado ao construtor

Nomes de rotas, colunas e variáveis; biblioteca (`msal` ou `httpx` direto, já
instalado); como cifrar a chave de renovação (reaproveitar o esquema do cofre
se couber); onde roda o serviço de 5 min; texto das telas; layout do botão no
Águia DS.
