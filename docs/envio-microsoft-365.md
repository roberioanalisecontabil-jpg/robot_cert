# Envio de e-mail pelo Microsoft 365 (Graph)

Decidido em 03/10/2026 (grill "feche o que falta", Leva B). O portal passa a
ter duas formas de envio, escolhidas em Configuração › Alertas por e-mail:

| Forma | Quando usar | O que fica no servidor |
|---|---|---|
| SMTP | servidor próprio ou provedor que aceite usuário e senha | host, usuário, senha cifrada |
| Microsoft 365 (Graph) | caixa no tenant da empresa | tenant, id do app, segredo cifrado, caixa de envio |

Por que Graph: a Microsoft desliga o SMTP básico por padrão no fim de 2026 e
anuncia a remoção em 2027; com MFA, o SMTP básico já depende de exceção. Pelo
Graph o aplicativo autentica sozinho (client credentials) e nenhuma senha de
caixa fica no servidor.

## Endereços

- **Caixa de envio (remetente)**: `noreply@analisegroup.cnt.br`, caixa
  **compartilhada** (até 50 GB não precisa de licença; ninguém faz login nela).
- **Responder para**: `certificados@analisegroup.cnt.br`. É um grupo, fica
  como está; o Graph não envia "como grupo", então a resposta de quem recebe
  é que cai nele.

## O que é feito no Microsoft 365 (uma vez)

Feito pelo administrador do tenant, com o assistente na extensão do navegador
acompanhando, em 03/10/2026 ou na data combinada.

### 1. Caixa compartilhada

Centro de administração do Exchange → Destinatários → Caixas de correio →
**Adicionar caixa compartilhada**: nome "Análise CertiDigital (não responda)",
e-mail `noreply@analisegroup.cnt.br`. Sem membros.

### 2. Registro do aplicativo (Entra)

Entra admin center → Identidade → Aplicativos → **Registros de aplicativo** →
Novo registro:

- Nome: `Analise CertiDigital - envio de e-mail`
- Tipos de conta: somente este diretório (locatário único)
- URI de redirecionamento: nenhum

Anotar da visão geral: **ID do aplicativo (cliente)** e **ID do diretório
(locatário)**.

### 3. Permissão

Permissões de API → Adicionar permissão → Microsoft Graph → **Permissões de
aplicativo** → `Mail.Send` → Adicionar. Depois **Conceder consentimento do
administrador** para o tenant.

### 4. Segredo

Certificados e segredos → **Novo segredo do cliente** → descrição "portal
certificado", validade **24 meses**. Copiar o **Valor** na hora (não aparece
de novo) e anotar a **data de validade**: ela vai para o campo "Segredo vence
em" da Configuração, e o sino do administrador avisa 30 dias antes.

### 5. Restringir o app à caixa de envio (Exchange Online PowerShell)

`Mail.Send` de aplicativo vale para toda caixa do tenant. A política abaixo
limita o app à caixa de envio; sem ela, o app poderia mandar e-mail como
qualquer pessoa da empresa.

```powershell
Install-Module ExchangeOnlineManagement -Scope CurrentUser   # uma vez
Connect-ExchangeOnline -UserPrincipalName ti@analisegroup.cnt.br

# Grupo de segurança habilitado para e-mail que contém SÓ a caixa de envio:
New-DistributionGroup -Name "App CertiDigital - caixas permitidas" -Type Security -PrimarySmtpAddress app-certidigital@analisegroup.cnt.br
Add-DistributionGroupMember -Identity "App CertiDigital - caixas permitidas" -Member noreply@analisegroup.cnt.br

New-ApplicationAccessPolicy -AppId <ID do aplicativo> -PolicyScopeGroupId app-certidigital@analisegroup.cnt.br -AccessRight RestrictAccess -Description "Portal certificado: so a caixa noreply"

# Conferir: Granted para a caixa de envio, Denied para qualquer outra
Test-ApplicationAccessPolicy -AppId <ID do aplicativo> -Identity noreply@analisegroup.cnt.br
Test-ApplicationAccessPolicy -AppId <ID do aplicativo> -Identity ti@analisegroup.cnt.br
```

A política leva até 30 minutos para valer.

## O que é feito no portal

Configuração › Alertas por e-mail › **Forma de envio: Microsoft 365 (Graph)**:

| Campo | Valor |
|---|---|
| ID do tenant | ID do diretório (locatário) |
| ID do aplicativo | ID do aplicativo (cliente) |
| Segredo do aplicativo | o Valor copiado no passo 4 (fica cifrado; a tela só diz "segredo guardado") |
| Caixa de envio | `noreply@analisegroup.cnt.br` |
| Responder para | `certificados@analisegroup.cnt.br` |
| Segredo vence em | a data do passo 4 |

Salvar, depois **Enviar teste** para o próprio e-mail. As classes de erro que
a tela distingue: credenciais recusadas (tenant, app ou segredo), sem
permissão (consentimento ou política de acesso), caixa ou destinatário
recusados, e sem conexão com a Microsoft.

## Deploy

1. Migration `supabase/migrations/20261003120000_envio_microsoft_graph.sql`
   no psql do ANALISESRV (cópia no Desktop). Antes do deploy, ou logo depois:
   até rodar, salvar a Configuração responde 503.
2. `atualizacao_push.ps1`.
3. Sonda: `GET /api/settings` (com sessão de administrador) traz
   `email_transporte`.
4. Preencher a Configuração e enviar o teste.

## Quando o segredo vencer

Entra → o app → Certificados e segredos → novo segredo; colar na Configuração
com a data nova. O antigo pode ser apagado depois do teste. O aviso no sino
começa 30 dias antes da data cadastrada e some quando a data é atualizada.
