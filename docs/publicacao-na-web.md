# Publicação do portal de certificados na internet

Decidido em 14/10/2026:

- **Só `certificado.analisegroup.cnt.br`.** `hardlyze.` e `eficacia.` continuam só na rede da empresa e na VPN.
- **Proxy da Cloudflare na frente** (nuvem laranja). Todo mundo passa por ela, de dentro ou de fora da empresa.
- **Item 14 da auditoria run-2** (rajada de logins) tratado só na Cloudflare.

O agente do servidor fala com o portal por `http://127.0.0.1:8020` e não passa por nada disso.

## Onde o servidor está

O ANALISESRV (10.200.0.4) é uma máquina virtual na **Oracle Cloud**, num ambiente administrado pelo provedor. Não fica atrás do pfSense do escritório: o pfSense alcança a rede 10.200.0.0/24 por um túnel WireGuard.

- **IP público do ambiente: 147.15.37.38.** É por ele que a intranet já está publicada pela Cloudflare.
- **O encaminhamento de portas desse IP é feito pelo provedor**, não por nós. Não há painel desse firewall alcançável pela VPN.
- **A intranet roda no próprio ANALISESRV**: Django com Waitress na porta 8191, em HTTP. A zona está em modo **Flexível**, então a Cloudflare fala com ela em HTTP pela porta 80 do IP público. Ou seja, o trecho entre a Cloudflare e o servidor não é cifrado. Fica para depois, fora deste roteiro: passar a intranet pelo Caddy, com HTTPS de ponta a ponta.

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

O **Bot Fight Mode** está desligado na zona e deve continuar assim: ele não tem exceção por nome e pararia as bandejas.

Enquanto o DNS de `certificado` estiver em nuvem cinza, essas regras não têm efeito.

### 2. Provedor: encaminhamento no IP público

Pedir ao provedor do ambiente na Oracle Cloud:

1. Quais portas do 147.15.37.38 estão encaminhadas hoje, e para onde.
2. **Se a 443 estiver livre** (a intranet, em Flexível, usa a 80): encaminhar **147.15.37.38:443 → 10.200.0.4:443**. **Se não:** **147.15.37.38:8443 → 10.200.0.4:443**.
3. Em ambos os casos: aceitar **só os IPs da Cloudflare** (https://www.cloudflare.com/ips) e **sem NAT de origem** (SNAT/masquerade). Se o provedor trocar a origem, todos os acessos vão parecer vir do firewall dele, um IP interno. Aí a Cloudflare deixa de ser reconhecida e os limites por endereço viram um só para todo mundo. O passo 5 confere isso.

O destino é sempre o **Caddy na 443**, nunca a porta do portal (8020): ela só escuta em 127.0.0.1, e pular o Caddy pularia o TLS, o filtro de origem, o IP real e o teto de corpo.

O firewall do Windows no ANALISESRV já aceita a 443 (regra `AnaliseCertiDigital-Proxy-HTTPS`).

**Se for a 8443:** criar em **Rules › Origin Rules** uma regra para `http.host eq "certificado.analisegroup.cnt.br"` com **porta de destino 8443**. Quem acessa continua usando `https://certificado.analisegroup.cnt.br`, sem porta. A Cloudflare só usa estas portas HTTPS na origem: 443, 2053, 2083, 2087, 2096, 8443. Outros portais do ANALISESRV podem usar o mesmo encaminhamento e a mesma regra (o Caddy separa pelo nome); um servidor diferente precisaria de outra porta dessa lista.

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

### 4. Cloudflare: DNS

- **DNS › Records › `certificado`:** trocar o conteúdo de `10.200.0.4` para **147.15.37.38** e ligar o **proxy (nuvem laranja)**.
- **Não mexer** em `hardlyze` e `eficacia`: continuam em 10.200.0.4, nuvem cinza.

A troca chega em poucos minutos. Algumas máquinas guardam o endereço antigo por um tempo; `ipconfig /flushdns` resolve.

### 5. Conferência

- **De fora da empresa** (celular no 4G): abrir `https://certificado.analisegroup.cnt.br`. A tela de login aparece, e o login com código funciona.
- **Do PC:**
  - o nome resolve para IPs da Cloudflare;
  - a resposta traz o cabeçalho `cf-ray`;
  - um login falso dá 401 rápido;
  - o hardlyze continua respondendo só por dentro.
- **No log do Caddy** (`C:\Apps\caddy\logs\acesso-8020.log`): numa requisição de fora, `remote_ip` tem de ser um IP da Cloudflare e `client_ip` o IP de quem acessou. Se `remote_ip` for um IP interno, o provedor está trocando a origem (ver o passo 2).
- **Numa estação:** pedir pelo portal a instalação de um certificado. A bandeja instala como antes, agora pela Cloudflare.

### Voltar atrás

Em qualquer passo: na Cloudflare, `certificado` volta para `10.200.0.4` com **nuvem cinza**. O encaminhamento no provedor pode ficar: o Caddy recusa quem não é a Cloudflare. O Caddyfile novo também pode ficar: ele aceita a rede interna.
