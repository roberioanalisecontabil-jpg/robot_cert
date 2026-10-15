# Publicação do portal de certificados na internet

Decidido em 14/10/2026:

- **Só `certificado.analisegroup.cnt.br`.** `hardlyze.` e `eficacia.` continuam só na rede da empresa e na VPN.
- **Proxy da Cloudflare na frente** (nuvem laranja). Todo mundo passa por ela, de dentro ou de fora da empresa.
- **Item 14 da auditoria run-2** (rajada de logins) tratado só na Cloudflare.

Acrescentado em 15/10/2026: entrada pela **porta 2053** do IP público, com o firewall aceitando só os IPs da Cloudflare, e o portal **só para acessos do Brasil**, por uma regra na Cloudflare.

O robô do próprio servidor (envio de PFX, fila do agente) acessa o portal pelo nome `certificado.analisegroup.cnt.br`. Para ele não depender da internet nem da Cloudflare, o `hosts` do ANALISESRV aponta esse nome para `10.200.0.4` (ver o passo 4).

## Onde o servidor está

O ANALISESRV (10.200.0.4) é uma máquina virtual na **Oracle Cloud**, num ambiente administrado pelo provedor. Não fica atrás do pfSense do escritório: o pfSense alcança a rede 10.200.0.0/24 por um túnel WireGuard.

- **IP público do ambiente: 147.15.37.38.** É por ele que a intranet já está publicada pela Cloudflare.
- **O encaminhamento de portas desse IP é feito no pfSense da nuvem**, pelo suporte (com chamado ao pessoal da nuvem para a WAN), não por nós.
- **A intranet roda no próprio ANALISESRV**: Django com Waitress na porta 8191, em HTTP. A zona está em modo **Flexível** e uma Origin Rule manda a Cloudflare para a porta **8191** do IP público, em HTTP. Essa porta responde também a quem vai direto ao IP, sem passar pela Cloudflare: vale pedir ao suporte o mesmo filtro só-Cloudflare da 2053.
- **O `gest.` não passa por aqui**: está em outro IP (136.248.112.200, porta 8087, por Origin Rule). Ou seja, o trecho entre a Cloudflare e o servidor não é cifrado. Fica para depois, fora deste roteiro: passar a intranet pelo Caddy, com HTTPS de ponta a ponta.

## O que o `deploy/Caddyfile` já faz

1. **IP verdadeiro.** Confia no `CF-Connecting-IP` só quando quem conecta é a Cloudflare (`trusted_proxies`), e entrega ao portal um único `X-Forwarded-For` com o IP real. Sem isso, os limites por endereço (login, código, bandeja) seriam contados por IP da Cloudflare e compartilhados por todo mundo. Quando quem não é a Cloudflare forja o cabeçalho, ele é ignorado.
2. **`certificado.` só pela Cloudflare ou pela rede interna.** Quem for direto ao IP público tem a conexão encerrada sem resposta. A rede interna continua aceita: a troca do DNS não derruba ninguém no meio, e o portal segue alcançável por dentro se a internet cair.
3. **`hardlyze.` e `eficacia.` só pela rede interna e pela VPN.** A porta é uma só para os três sites; sem essa recusa, bastaria pedir o nome certo ao IP público.

Testado em 14/10 com Caddy 2.11.7 e uma cópia local do arquivo:
- rede interna: passa;
- `CF-Connecting-IP` forjado: ignorado;
- conexão direta de fora: recusada;
- vindo da Cloudflare: chega o IP real.

## Passo a passo

A ordem importa. O DNS é o último passo, porque é ele que abre a porta para o público.

### 1. Cloudflare: regras só para `certificado.` (FEITO em 14/10)

A zona `analisegroup.cnt.br` serve outros sites pelo proxy (a raiz, `bi.`, `gest.`, `intranet.`) em modo **Flexível** e com a ofuscação de e-mail ligada. **Nada da zona foi mudado**: trocar o modo SSL ou esses interruptores derrubaria ou alteraria esses sites. Em vez disso, há três regras que valem só para `certificado.analisegroup.cnt.br`:

- **Rules › Configuration Rules › `certificado`** (`http.host eq "certificado.analisegroup.cnt.br"`):
  - **SSL: Estrito (Full strict).** O Caddy tem certificado Let's Encrypt válido. "Flexível" mandaria tudo em HTTP até o servidor, e o portal redirecionaria em laço.
  - **Ofuscação de e-mail: desligada.** Ela injeta um script na página, que a política de segurança (CSP) do portal bloqueia.
  - **Rocket Loader: desligado**, pelo mesmo motivo.
  - **Verificação de integridade do navegador: desligada.** Ela desafia clientes que não são navegador, e as bandejas das estações (Certguard Análise) e o Hardlyze 2.x são programas.
- **Rules › Redirect Rules › `certificado-https`:** `http://certificado.analisegroup.cnt.br/*` → `https://certificado.analisegroup.cnt.br/${1}`, 301, preservando a consulta. Faz o papel do "Sempre usar HTTPS", que está desligado na zona.
- **Security › Regras de segurança › Rate limiting › `login`** (o plano grátis permite uma regra), item 14:
  - Se: host `certificado.analisegroup.cnt.br` **e** caminho contém `/api/login` **e** método `POST`.
  - Contar por IP. Limite: **10 requisições em 10 segundos**. Ação: **Bloquear** por 10 segundos.

  Uma pessoa digitando nunca chega perto disso. O portal tem os próprios limites, por baixo. Para outro portal publicado depois, amplie esta mesma regra (o plano grátis não permite uma segunda).
- **Security › WAF › Custom rules › `certificado-so-brasil`** (FEITO em 15/10):
  - Se: host `certificado.analisegroup.cnt.br` **e** país **diferente de** Brasil (`ip.src.country ne "BR"`).
  - Ação: **Bloquear**, e não Desafio, porque as bandejas são programas e não resolvem desafio.

  É um filtro de ruído: tira a maior parte das varreduras e tentativas de login automáticas antes de chegarem ao servidor. Não é barreira forte, porque um servidor no Brasil passa. Efeito colateral aceito: quem estiver no exterior, ou numa VPN ou roaming com saída fora do país, não entra. Para uma viagem, desligue a regra pelos dias necessários. Nas primeiras semanas, confira em **Security › Events** o que ela barrou. Só a Cloudflare sabe o país: o firewall vê apenas os IPs dela, por isso esta regra não pode ficar no pfSense.

O **Bot Fight Mode** está desligado na zona e deve continuar assim: ele não tem exceção por nome e pararia as bandejas.

Enquanto o DNS de `certificado` estiver em nuvem cinza, essas regras não têm efeito.

### 2. pfSense da nuvem: encaminhamento no IP público (PEDIDO em 15/10, aguardando)

O IP público passa pelo **pfSense da nuvem**, administrado pelo suporte, que abriu chamado com o pessoal da nuvem para liberar a porta na WAN. A 8443 desse pfSense já é usada para acessar a interface dele, e a 443 foi descartada por ser a mais visada. Ficou combinado:

1. **NAT de destino (Port Forward): WAN 147.15.37.38:2053 → 10.200.0.4:2053**, TCP, numa **regra nova**. As regras atuais não mudam, e a intranet continua chegando pela 8191 do mesmo IP. O combinado inicial era → 10.200.0.4:443; em 15/10, com a Cloudflare ainda dando 522, passamos a usar a mesma porta dos dois lados (o Caddy escuta também na 2053).
2. **Origem permitida: só os IPs da Cloudflare** (https://www.cloudflare.com/ips), de preferência num Alias do pfSense. Quem conecta no firewall é sempre a Cloudflare, nunca o usuário: liberar IPs de usuários bloquearia todo mundo. A lista conferida em 15/10 é a mesma do `trusted_proxies` do Caddyfile.
3. **Sem NAT de origem** (outbound NAT/SNAT/masquerade) nesse caminho. Com ele, o remetente vira o pfSense, um IP interno: o Caddy deixa de reconhecer a Cloudflare, o portal perde o IP real e os limites por endereço viram um só para todo mundo. Pode acontecer sem ninguém querer, se o pfSense alcançar 10.200.0.0/24 por uma interface com NAT de origem automático. O passo 5 confere isso. Se o NAT de origem não puder sair (por exemplo, porque a resposta do servidor não voltaria pelo mesmo pfSense), a saída é pôr o IP interno do pfSense no `trusted_proxies` do Caddyfile. Isso é seguro só porque o firewall deixa apenas a Cloudflare chegar na 2053.

O destino é sempre o **Caddy** (2053, ou 443 pela rede interna), nunca a porta do portal (8020): ela só escuta em 127.0.0.1, e pular o Caddy pularia o TLS, o filtro de origem, o IP real e o teto de corpo. O certificado é renovado pela API da Cloudflare, não por conexão de entrada.

O firewall do Windows no ANALISESRV já aceita a 443 (regra `AnaliseCertiDigital-Proxy-HTTPS`). A 2053 precisa de uma regra própria (passo 3).

**Na Cloudflare (FEITO em 15/10):** em **Rules › Origin Rules**, a regra `certificado-porta-2053` (`http.host eq "certificado.analisegroup.cnt.br"` → **porta de destino 2053**), e a regra `certificado-so-brasil` do passo 1. Quem acessa continua usando `https://certificado.analisegroup.cnt.br`, sem porta. A lista de portas HTTPS da Cloudflare (443, 2053, 2083, 2087, 2096, 8443) vale para a porta que o **visitante** usa; com Origin Rule, a porta de destino na origem pode ser qualquer uma. Outros sites do ANALISESRV usam o mesmo encaminhamento: basta acrescentar o nome à Origin Rule e um endereço `:2053` no Caddyfile.

### 3. ANALISESRV: Caddyfile novo (FEITO em 14/10)

No PowerShell como administrador, **uma linha de cada vez**:

```powershell
cd C:\Apps\robot_cert
git pull
Copy-Item C:\Apps\Caddyfile C:\Apps\Caddyfile.antes-da-web
Copy-Item .\deploy\Caddyfile C:\Apps\Caddyfile
$env:CLOUDFLARE_API_TOKEN = ((Get-ItemProperty HKLM:\SYSTEM\CurrentControlSet\Services\caddy\Parameters).AppEnvironmentExtra | Where-Object { $_ -like 'CLOUDFLARE_API_TOKEN=*' }) -replace '^CLOUDFLARE_API_TOKEN=',''
C:\Apps\caddy.exe validate --config C:\Apps\Caddyfile --adapter caddyfile
Restart-Service caddy
```

O `validate` precisa do token, que o NSSM guarda na configuração do serviço; a quinta linha o lê sem mostrar. Só reinicie depois de "Valid configuration". Se o Caddy não subir, volte o `Caddyfile.antes-da-web` e reinicie.

Neste ponto nada mudou para ninguém: o DNS ainda aponta para 10.200.0.4.

**Porta 2053 (15/10).** Os mesmos comandos acima (`git pull` em diante) trazem o Caddyfile que escuta também na 2053. Antes do `Restart-Service caddy`, abra a porta no firewall do Windows:

```powershell
New-NetFirewallRule -DisplayName "AnaliseCertiDigital-Proxy-2053" -Direction Inbound -Protocol TCP -LocalPort 2053 -Action Allow -Profile Any
```

Para conferir de uma máquina da rede: `curl.exe -I --resolve certificado.analisegroup.cnt.br:2053:10.200.0.4 https://certificado.analisegroup.cnt.br:2053/login` responde 200.

### 4. Cloudflare: DNS

- **DNS › Records › `certificado`:** trocar o conteúdo de `10.200.0.4` para **147.15.37.38** e ligar o **proxy (nuvem laranja)**.
- **Não mexer** em `hardlyze` e `eficacia`: continuam em 10.200.0.4, nuvem cinza.
- **Antes, no ANALISESRV** (como administrador): `Add-Content -Path C:\Windows\System32\drivers\etc\hosts -Value "10.200.0.4 certificado.analisegroup.cnt.br"` e `ipconfig /flushdns`. O robô do servidor usa esse nome e segue pela rede interna.

A troca chega em poucos minutos. Algumas máquinas guardam o endereço antigo por um tempo; `ipconfig /flushdns` resolve.

### 5. Conferência

- **De fora da empresa** (celular no 4G): abrir `https://certificado.analisegroup.cnt.br`. A tela de login aparece, e o login com código funciona.
- **Do PC:**
  - o nome resolve para IPs da Cloudflare;
  - a resposta traz o cabeçalho `cf-ray`;
  - um login falso dá 401 rápido;
  - o hardlyze continua respondendo só por dentro.
- **No log do Caddy** (`C:\Apps\caddy\logs\acesso-8020.log`): numa requisição de fora, `remote_ip` tem de ser um IP da Cloudflare e `client_ip` o IP de quem acessou. Se `remote_ip` for um IP interno, o pfSense está trocando a origem (ver o passo 2).
- **Brasil:** em **Security › Events**, a regra `certificado-so-brasil` aparece barrando acessos de fora. Ninguém daqui deve aparecer nela.
- **Intranet e gest:** continuam abrindo como antes.
- **Numa estação:** pedir pelo portal a instalação de um certificado. A bandeja instala como antes, agora pela Cloudflare.

### Voltar atrás

Em qualquer passo: na Cloudflare, `certificado` volta para `10.200.0.4` com **nuvem cinza**. O encaminhamento no provedor pode ficar: o Caddy recusa quem não é a Cloudflare. O Caddyfile novo também pode ficar: ele aceita a rede interna.
