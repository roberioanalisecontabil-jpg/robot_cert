# Publicação do portal de certificados na internet

Decidido em 14/10/2026:

- **Só `certificado.analisegroup.cnt.br`.** `hardlyze.` e `eficacia.` continuam só na rede da empresa e na VPN.
- **Porta 443 aberta** no firewall da empresa para o ANALISESRV (10.200.0.4), com o **proxy da Cloudflare** na frente.
- **Todo mundo passa pela Cloudflare**, de dentro ou de fora da empresa.
- **Item 14 da auditoria run-2** (rajada de logins) tratado só na Cloudflare.

O agente do servidor fala com o portal por `http://127.0.0.1:8020` e não passa por nada disso.

## O que o `deploy/Caddyfile` já faz

1. **IP verdadeiro.** Confia no `CF-Connecting-IP` só quando quem conecta é a Cloudflare (`trusted_proxies`), e entrega ao portal um único `X-Forwarded-For` com o IP real. Sem isso, os limites por endereço (login, código, bandeja) seriam contados por IP da Cloudflare e compartilhados por todo mundo. Quando quem não é a Cloudflare forja o cabeçalho, ele é ignorado.
2. **`certificado.` só pela Cloudflare ou pela rede interna.** Quem for direto ao IP público tem a conexão encerrada sem resposta. A rede interna continua aceita: a troca do DNS não derruba ninguém no meio, e o portal segue alcançável por dentro se a internet cair.
3. **`hardlyze.` e `eficacia.` só pela rede interna e pela VPN.** A porta 443 é uma só para os três sites; sem essa recusa, bastaria pedir o nome certo ao IP público.

Testado em 14/10 com Caddy 2.11.7 e uma cópia local do arquivo:
- rede interna: passa;
- `CF-Connecting-IP` forjado: ignorado;
- conexão direta de fora: recusada;
- vindo da Cloudflare: chega o IP real.

## Passo a passo

A ordem importa. O DNS é o último passo, porque é ele que abre a porta para o público.

### 1. Cloudflare: configurações da zona `analisegroup.cnt.br`

- **SSL/TLS › Overview:** modo **Full (strict)**. O Caddy tem certificado Let's Encrypt válido. "Flexible" mandaria tudo em HTTP até o servidor, e o portal redirecionaria em laço.
- **SSL/TLS › Edge Certificates:** **Always Use HTTPS** ligado.
- **Scrape Shield › Email Address Obfuscation:** **desligado**. Ele injeta um script na página, que a política de segurança (CSP) do portal bloqueia.
- **Speed › Optimization:** **Rocket Loader desligado**, pelo mesmo motivo.
- **Security › Bots:** **Bot Fight Mode desligado.** Ele desafia clientes que não são navegador, e as bandejas das estações (Certguard Análise) e o Hardlyze 2.x são programas: parariam de falar com o portal.
- **Security › WAF › Rate limiting rules** (o plano grátis permite uma regra), item 14:
  - Nome: `login`.
  - Se: *URI Path* *contains* `/api/login` **e** *Request Method* *equals* `POST`.
  - Contar por: IP. Limite: **10 requisições em 10 segundos**.
  - Ação: **Block** por 10 segundos.

  Uma pessoa digitando nunca chega perto disso. O portal tem os próprios limites, por baixo.

### 2. Firewall/roteador da empresa

- Encaminhar **TCP 443** do IP público para **10.200.0.4:443**.
- Se o equipamento permitir, aceitar nessa regra **só os IPs da Cloudflare** (lista em https://www.cloudflare.com/ips). O Caddy já recusa o resto; no firewall, a recusa acontece antes.
- **O encaminhamento não pode trocar o IP de origem** (SNAT/masquerade na regra de entrada). Se trocar, todos os acessos vão parecer vir do roteador, um IP interno. Aí a Cloudflare deixa de ser reconhecida e os limites por endereço viram um só para todo mundo. O passo 5 confere isso.
- A porta 80 não precisa ser aberta: a Cloudflare atende o HTTP e redireciona.

O firewall do Windows no ANALISESRV já aceita a 443 (regra `AnaliseCertiDigital-Proxy-HTTPS`, perfis Domínio e Privado). O tráfego encaminhado chega pela placa da rede local, que é do perfil Domínio.

### 3. ANALISESRV: Caddyfile novo

No PowerShell como administrador:

```powershell
cd C:\Apps\robot_cert            # (o clone do repositório no servidor)
git pull
Copy-Item C:\Apps\Caddyfile C:\Apps\Caddyfile.antes-da-web
Copy-Item .\deploy\Caddyfile C:\Apps\Caddyfile
C:\Apps\caddy.exe validate --config C:\Apps\Caddyfile --adapter caddyfile
Get-Service *caddy* | Restart-Service
```

O `validate` precisa da variável `CLOUDFLARE_API_TOKEN`. Se reclamar do token, rode o `validate` com ela definida na sessão, ou pule direto para o `Restart-Service` e confira o log do Caddy. Se o Caddy não subir, volte o `Caddyfile.antes-da-web` e reinicie.

Neste ponto nada mudou para ninguém: o DNS ainda aponta para 10.200.0.4.

### 4. Cloudflare: DNS

- **DNS › Records › `certificado`:** trocar o conteúdo de `10.200.0.4` para o **IP público da empresa** e ligar o **proxy (nuvem laranja)**.
- **Não mexer** em `hardlyze` e `eficacia`: continuam em 10.200.0.4, nuvem cinza.

A troca chega em poucos minutos. Algumas máquinas guardam o endereço antigo por um tempo; `ipconfig /flushdns` resolve.

### 5. Conferência

- **De fora da empresa** (celular no 4G): abrir `https://certificado.analisegroup.cnt.br`. A tela de login aparece, e o login com código funciona.
- **Do PC (eu confiro):**
  - o nome resolve para IPs da Cloudflare;
  - a resposta traz o cabeçalho `cf-ray`;
  - um login falso dá 401 rápido;
  - o hardlyze continua respondendo só por dentro.
- **No log do Caddy** (`C:\Apps\caddy\logs\acesso-8020.log`): numa requisição de fora, `remote_ip` tem de ser um IP da Cloudflare e `client_ip` o IP de quem acessou. Se `remote_ip` for um IP interno (ex.: 10.200.0.1), o roteador está trocando a origem (ver o passo 2).
- **Numa estação:** pedir pelo portal a instalação de um certificado. A bandeja instala como antes, agora pela Cloudflare.

### Voltar atrás

Em qualquer passo: na Cloudflare, `certificado` volta para `10.200.0.4` com **nuvem cinza**, e o firewall fecha a 443. O Caddyfile novo pode ficar: ele aceita a rede interna.
