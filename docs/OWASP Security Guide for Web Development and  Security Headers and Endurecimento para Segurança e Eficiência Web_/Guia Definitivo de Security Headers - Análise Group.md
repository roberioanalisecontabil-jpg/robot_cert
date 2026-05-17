# **Guia Definitivo de Security Headers: Como Alcançar a Nota Máxima (A+) em Suas Aplicações e Portais**
Este guia prático foi desenvolvido para orientar a implementação de cabeçalhos de segurança (Security Headers) robustos em servidores web e aplicações do ecossistema de portais. Ao configurar corretamente esses cabeçalhos, sua aplicação mitiga uma vasta gama de ataques (como Cross-Site Scripting - XSS, Clickjacking, Sniffing de MIME-type e vazamento de dados via Referrer) e alcança a pontuação máxima (**Grade A+**) no ecossistema de auditoria do **Security Headers**.


## **Sumário**
1. Os 6 Cabeçalhos Críticos para a Nota A+
1. Detalhamento Técnica e Configurações Recomendadas
1. Exemplos Práticos de Implementação por Servidor (Nginx, Apache, IIS e Web.config)
1. Estratégia de Homologação e Testes (Evitando Quebras)
1. Checklist de Auditoria Rápida


## **1. Os 6 Cabeçalhos Críticos para a Nota A+**
Para obter a nota máxima, o mecanismo de validação exige a presença e a configuração estrita de seis cabeçalhos fundamentais. Abaixo está a visão geral do papel de cada um:

|Cabeçalho de Segurança|Função Principal|<p>Impacto de Ausência</p><p> </p>|
| :- | :- | :- |
|Content-Security-Policy (CSP)|Restringe a origem de scripts, estilos e mídias executáveis na página.|Alto risco de ataques XSS e injeção de código malicioso.|
|Strict-Transport-Security (HSTS)|Força o navegador a utilizar exclusivamente conexões HTTPS em canais criptografados.|Vulnerabilidade a ataques de interceptação (Man-in-the-Middle) e Downgrade.|
|X-Content-Type-Options|Impede o navegador de tentar adivinhar o tipo de arquivo (MIME sniffing).|Execução inadvertida de scripts mascarados como imagens/textos.|
|X-Frame-Options|Controla se a página pode ser renderizada dentro de iframes.|Exposição a ataques de Clickjacking (sequestro de clique).|
|Referrer-Policy|Gerencia quanta informação de navegação (URL de origem) é enviada ao clicar em links externos.|Vazamento de dados sensíveis presentes em strings de consulta (query strings).|
|Permissions-Policy|Restringe o acesso a recursos de hardware do dispositivo (Câmera, Microfone, Geolocalização).|Uso indevido de APIs nativas do navegador por scripts de terceiros integrados.|


## **2. Detalhamento Técnico e Configurações Recomendadas**
### **2.1 Content-Security-Policy (CSP)**
O CSP é o cabeçalho mais complexo e o mais valorizado nas auditorias de segurança. Uma política rígida bloqueia a execução de códigos não autorizados.

**Configuração Restrita Recomendada (Baseline A+):**

Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; frame-ancestors 'self'; block-all-mixed-content; upgrade-insecure-requests;

**Dica Prática:** Se seu portal consome APIs ou scripts externos (como Google Analytics, fontes ou frameworks low-code), você deve mapear os domínios explicitamente:

Content-Security-Policy: default-src 'self'; script-src 'self' https://www.google-analytics.com; style-src 'self' https://fonts.googleapis.com 'unsafe-inline'; font-src 'self' https://fonts.gstatic.com; img-src 'self' data:; frame-ancestors 'self';
### **2.2 Strict-Transport-Security (HSTS)**
Informa ao navegador que o site só deve ser acessado por HTTPS pelos próximos meses, incluindo subdomínios.

**Configuração Recomendada:**

Strict-Transport-Security: max-age=63072000; includeSubDomains; preload

**Atenção:** O valor max-age=63072000 equivale a 2 anos (requisito ideal para o ecossistema de segurança). Certifique-se de que o certificado SSL de todos os seus subdomínios esteja válido antes de incluir a flag includeSubDomains.
### **2.3 X-Content-Type-Options**
Elimina a brecha de segurança onde atacantes tentam mascarar arquivos executáveis maliciosos em formatos estáticos.

**Configuração Recomendada:**

X-Content-Type-Options: nosniff
### **2.4 X-Frame-Options**
Protege seus portais internos e páginas operacionais contra a incorporação em sites maliciosos que simulam a interface do usuário para capturar cliques legítimos.

**Configuração Recomendada:**

X-Frame-Options: SAMEORIGIN

*Nota:* Se sua aplicação for puramente API ou nunca precisar ser embedada por ninguém (nem por você mesmo), utilize DENY.
### **2.5 Referrer-Policy**
Controla a quantidade de dados passados no cabeçalho HTTP Referer quando o usuário navega a partir do seu site.

**Configuração Recomendada:**

Referrer-Policy: strict-origin-when-cross-origin

*Explicação:* Envia a URL completa quando a navegação ocorre no próprio site, envia apenas a origem (domínio) para links externos HTTPS, e não envia nada para destinos inseguros (HTTP).
### **2.6 Permissions-Policy**
Substituto moderno do antigo Feature-Policy. Limita o que o navegador pode executar em termos de hardware e APIs da API do browser.

**Configuração Recomendada (Bloqueio Geral Seguro):**

Permissions-Policy: camera=(), microphone=(), geolocation=(), payment=(), usb=()

Se sua aplicação necessitar de algum desses recursos (ex: câmera para leitura de QR Code), altere para permitir apenas a origem local: camera=('self').


## **3. Exemplos Práticos de Implementação por Servidor**
Escolha o ambiente correspondente à sua infraestrutura de deploy:
### **3.1 Nginx**
Adicione as seguintes diretivas dentro do bloco server:

server {\
`    `listen 443 ssl http2;\
`    `server\_name operacao.analisegroup.cnt.br;\
\
`    `# Certificados SSL omitidos para brevidade...\
\
`    `# Configuração de Cabeçalhos de Segurança para Nota A+\
`    `add\_header Strict-Transport-Security "max-age=63072000; includeSubDomains; preload" always;\
`    `add\_header X-Content-Type-Options "nosniff" always;\
`    `add\_header X-Frame-Options "SAMEORIGIN" always;\
`    `add\_header Referrer-Policy "strict-origin-when-cross-origin" always;\
`    `add\_header Permissions-Policy "camera=(), microphone=(), geolocation=(), payment=(), usb=()" always;\
`    `add\_header Content-Security-Policy "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; frame-ancestors 'self'; block-all-mixed-content; upgrade-insecure-requests;" always;\
}
### **3.2 Servidores Windows IIS (web.config)**
Se suas aplicações rodam sob ambiente Microsoft IIS, configure as regras diretamente no arquivo web.config na raiz da aplicação dentro da tag system.webServer:

<configuration>\
`  `<system.webServer>\
`    `<httpProtocol>\
`      `<customHeaders>\
`        `<!-- Limpa cabeçalhos antigos por segurança -->\
`        `<remove name="X-Powered-By" />\
\
`        `<!-- Adiciona os cabeçalhos para Nota A+ -->\
`        `<add name="Strict-Transport-Security" value="max-age=63072000; includeSubDomains; preload" />\
`        `<add name="X-Content-Type-Options" value="nosniff" />\
`        `<add name="X-Frame-Options" value="SAMEORIGIN" />\
`        `<add name="Referrer-Policy" value="strict-origin-when-cross-origin" />\
`        `<add name="Permissions-Policy" value="camera=(), microphone=(), geolocation=(), payment=(), usb=()" />\
`        `<add name="Content-Security-Policy" value="default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; frame-ancestors 'self'; block-all-mixed-content; upgrade-insecure-requests;" />\
`      `</customHeaders>\
`    `</httpProtocol>\
`  `</system.webServer>\
</configuration>
### **3.3 Apache (.htaccess ou VirtualHost)**
Para servidores Apache, certifique-se de que o módulo mod\_headers está ativo (a2enmod headers) e adicione:

<IfModule mod\_headers.c>\
`    `Header always set Strict-Transport-Security "max-age=63072000; includeSubDomains; preload"\
`    `Header always set X-Content-Type-Options "nosniff"\
`    `Header always set X-Frame-Options "SAMEORIGIN"\
`    `Header always set Referrer-Policy "strict-origin-when-cross-origin"\
`    `Header always set Permissions-Policy "camera=(), microphone=(), geolocation=(), payment=(), usb=()"\
`    `Header always set Content-Security-Policy "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; frame-ancestors 'self'; block-all-mixed-content; upgrade-insecure-requests;"\
</IfModule>


## **4. Estratégia de Homologação e Testes (Evitando Quebras)**
Implementar o CSP de forma agressiva pode quebrar layouts ou impedir o funcionamento de scripts legítimos de terceiros (como integrações de automação ou portais dinâmicos). Use esta abordagem segura:

1. **Modo de Relatório (CSP Report-Only):** Antes de aplicar o cabeçalho definitivo, use o cabeçalho de teste. Ele não bloqueia nada, apenas reporta no console do desenvolvedor (F12) o que teria sido bloqueado.
1. **Mapeamento de Dependências:** Acesse o sistema, clique em todas as telas operacionais principais com o painel de Inspeção aberto e verifique se há alertas de violação de CSP. Adicione as exceções necessárias à sua política.
1. **Remoção de Elementos Obsoletos:** Remova cabeçalhos antigos como X-XSS-Protection. Os navegadores modernos descontinuaram seu suporte e manter valores antigos ou incorretos pode penalizar sua nota ou criar falsas sensações de segurança.


## **5. Checklist de Auditoria Rápida**
- Todos os 6 cabeçalhos principais estão presentes na resposta HTTP?
- O HSTS possui max-age maior ou igual a um ano e contém as diretivas includeSubDomains e preload?
- O X-Frame-Options está definido como SAMEORIGIN ou DENY?
- O X-Content-Type-Options está explicitamente definido como nosniff?
- O CSP restringe origens desconhecidas e impede injeção maliciosa?
- Cabeçalhos de rastreamento de servidor (como X-Powered-By ou Server) foram ocultados para evitar fingerprinting de infraestrutura?
