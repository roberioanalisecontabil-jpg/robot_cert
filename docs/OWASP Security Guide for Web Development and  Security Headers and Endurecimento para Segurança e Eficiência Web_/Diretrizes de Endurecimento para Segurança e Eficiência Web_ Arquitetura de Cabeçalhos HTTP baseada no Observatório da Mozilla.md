# **Guia Prático de Implementação: Cabeçalhos de Segurança HTTP**
Este guia descreve os passos técnicos necessários para corrigir as vulnerabilidades apontadas pelo Observatório HTTP da Mozilla <sup>1</sup>, estabelecendo uma postura de segurança baseada no princípio de privilégio mínimo na entrega de recursos web.<sup>2</sup>
## -----**1. Resumo da Auditoria e Modificadores de Nota**
O Observatório HTTP utiliza uma arquitetura baseada em Node.js (@mdn/mdn-http-observatory) para avaliar a presença de mecanismos de defesa em profundidade.<sup>4</sup> Falhas em diretivas críticas penalizam de forma agressiva a nota final do servidor.<sup>2</sup>

|**Teste de Cabeçalho**|**Status da Auditoria**|**Modificador de Nota**|**Comportamento Detectado / Solução Recomendada**|
| :- | :- | :- | :- |
|**Content Security Policy (CSP)**|Falhou (Não implementado) <sup>2</sup>|-25 <sup>2</sup>|Ausência de política de restrição de carregamento; requer definição de origens confiáveis. <sup>2</sup>|
|**Referrer Policy**|Falhou (Não implementado) <sup>2</sup>|0 <sup>2</sup>|Vazamento potencial de caminhos confidenciais; requer configuração de strict-origin-when-cross-origin. <sup>2</sup>|
|**X-Content-Type-Options**|Falhou (Não implementado) <sup>2</sup>|-5 <sup>2</sup>|Vulnerabilidade a ataques de farejamento de MIME; requer ativação da diretiva nosniff. <sup>8</sup>|
|**X-Frame-Options (XFO)**|Falhou (Não implementado) <sup>2</sup>|-20 <sup>2</sup>|Exposição ao risco de sequestro de cliques; requer o uso de frame-ancestors ou redundância de XFO.|
|**Strict Transport Security (HSTS)**|Passou (Mínimo de 6 meses) <sup>2</sup>|0 <sup>2</sup>|Proteção básica de criptografia ativa; para bonificação de +5, exige pré-carregamento global. <sup>2</sup>|
|**Subresource Integrity (SRI)**|Não implementado <sup>2</sup>|0 <sup>2</sup>|Dependência de arquivos externos sem hash; adicionar SRI para ganho de pontos de bonificação. <sup>2</sup>|
|**Cookies**|Nenhum detectado <sup>2</sup>|0 <sup>2</sup>|Sem cookies de sessão ativos; caso implementados, requerem HttpOnly, Secure e SameSite.|
## -----**2. Passo a Passo para Correção das Vulnerabilidades**
### **Passo 2.1: Implementar a Content Security Policy (CSP)**
A CSP mitiga ataques de Cross-Site Scripting (XSS) e injeções de dados maliciosos restringindo a execução e o carregamento de scripts.<sup>3</sup>

1. **Adote o Privilégio Mínimo**: Use default-src 'none' como fallback global para bloquear qualquer tipo de recurso não especificado.<sup>2</sup>
1. **Evite Práticas Inseguras**: Não utilize as diretivas 'unsafe-inline' ou 'unsafe-eval'. Se o uso de scripts inline for estritamente obrigatório, gere hashes criptográficos ou utilize identificadores dinâmicos (*nonces*) associados a cada requisição.
1. **Configure Monitoramento e Relatórios**: Adote a nova especificação baseada no cabeçalho Reporting-Endpoints e na diretiva report-to.<sup>5</sup>
1. **Fase de Testes (Transição)**: Use o cabeçalho Content-Security-Policy-Report-Only antes de aplicar bloqueios severos no ambiente de produção.
### -----**Passo 2.2: Proteger os Metadados com Referrer-Policy**
A ausência de controle do referrer expõe parâmetros, caminhos confidenciais e tokens contidos em URLs de sua aplicação.<sup>6</sup>

- **A Recomendação**: Defina o valor strict-origin-when-cross-origin.<sup>6</sup>
- **O Mecanismo**:
  - Se a navegação ocorrer no mesmo domínio, envia-se a URL completa (útil para telemetria e analytics internos).
  - Se for uma requisição externa e mantiver o mesmo protocolo seguro (HTTPS para HTTPS), o navegador envia somente a raiz do domínio (ocultando caminhos internos).<sup>6</sup>
  - Se houver um rebaixamento de segurança (HTTPS para HTTP inseguro), o envio do cabeçalho é omitido por completo.<sup>6</sup>
### -----**Passo 2.3: Blindar o Navegador contra Sniffing de MIME e Clickjacking**
Ações focadas na integridade de renderização e enquadramento evitam ataques visuais e injeção de scripts ocultos.<sup>8</sup>

1. **MIME Sniffing (X-Content-Type-Options)**: Configure o valor nosniff.<sup>13</sup> Isso impede que navegadores deduzam um formato de arquivo diferente daquele explicitado no cabeçalho Content-Type do servidor.<sup>8</sup>
1. **Proteção contra Clickjacking (X-Frame-Options e CSP)**: Impeça a renderização invisível do seu domínio dentro de <iframe> controlados por terceiros. Embora o cabeçalho X-Frame-Options: DENY (ou SAMEORIGIN) seja mantido por retrocompatibilidade, prefira a diretiva moderna frame-ancestors 'none' incorporada na CSP.
1. **Observação Importante**: O cabeçalho legado X-XSS-Protection foi descontinuado e não deve ser implementado (ou configurado como 0 para desativação explícita), pois seus métodos heurísticos antigos podiam introduzir falhas exploráveis adicionais.<sup>8</sup>
## -----**3. Isolamento e Controle de Origem Cruzada (Spectre Mitigações)**
Para responder a ataques físicos de canal lateral a nível de CPU (como Spectre e Meltdown), a aplicação deve restringir o compartilhamento de recursos em memória no ambiente do cliente.<sup>14</sup>

|**Cabeçalho HTTP**|**Valores Disponíveis**|**Escopo de Atuação e Proteção**|**Relação com Outros Mecanismos**|
| :- | :- | :- | :- |
|**Cross-Origin-Resource-Policy (CORP)** <sup>14</sup>|same-origin, same-site, cross-origin <sup>15</sup>|Controla quais origens podem carregar o recurso físico em requisições de modo no-cors. <sup>15</sup>|Impede o carregamento não autorizado de mídias e scripts em contextos externos. <sup>14</sup>|
|**Cross-Origin-Opener-Policy (COOP)** <sup>17</sup>|unsafe-none, same-origin, same-origin-allow-popups <sup>13</sup>|Corta referências programáticas (window.opener) entre documentos de origens distintas. <sup>18</sup>|Cria um Grupo de Contexto de Navegação (BCG) isolado para a aplicação. <sup>17</sup>|
|**Cross-Origin-Embedder-Policy (COEP)** <sup>19</sup>|unsafe-none, require-corp, credentialless <sup>19</sup>|Exige que recursos externos incorporem explicitamente cabeçalhos CORP ou CORS para carregamento. <sup>19</sup>|Pré-requisito técnico para habilitar o estado de Isolamento de Origem Cruzada. <sup>19</sup>|
|**Cross-Origin Resource Sharing (CORS)** <sup>21</sup>|Access-Control-Allow-Origin: <origin> <sup>21</sup>|Controla o acesso de leitura programática de dados via requisições de rede complexas. <sup>21</sup>|Exige requisições de verificação prévia (OPTIONS preflight) antes de operações de gravação. <sup>21</sup>|

**Atenção**: O uso de Cross-Origin-Resource-Policy: same-origin impede o carregamento indevido de mídias e ativos por outros domínios.<sup>14</sup> Contudo, há um bug documentado no Google Chrome em que a ativação dessa política em arquivos PDF impossibilita a leitura do documento após a primeira página.<sup>14</sup> Crie regras de exceção nos cabeçalhos de sua rota de PDFs para contornar essa falha de engenharia.<sup>14</sup>
## -----**4. Integridade de Subrecursos (SRI)**
A Integridade de Subrecursos (SRI) garante que arquivos estáticos consumidos por meio de CDNs externos não tenham sido modificados maliciosamente.<sup>22</sup> O navegador realiza uma verificação criptográfica baseada em hashes fortes como SHA-384.<sup>22</sup> A barreira matemática imposta por esse nível de hash apresenta uma complexidade expressa por:

![](Aspose.Words.92d83033-f81d-4b40-9fdf-20e4421d428a.001.png)
### **Script 4.1: Automação de Geração de Hashes no Build (Node.js)**
Incorpore esta rotina ao pipeline de integração contínua (CI) para catalogar de forma automática os hashes dos ativos gerados <sup>24</sup>:

JavaScript


import { createHash } from 'node:crypto';\
import { readFileSync, writeFileSync } from 'node:fs';\
import { globby } from 'globby';\
\
function gerarSRI(arquivo) {\
`  `const conteudo = readFileSync(arquivo);\
`  `const hash = createHash('sha384').update(conteudo).digest('base64');\
`  `return `sha384-${hash}`;\
}\
\
const ativos = await globby(['dist/\*\*/\*.js', 'dist/\*\*/\*.css']);\
const mapaSRI = Object.fromEntries(ativos.map((f) =>));\
writeFileSync('sri-hashes.json', JSON.stringify(mapaSRI, null, 2));
### **Script 4.2: Validação Dinâmica de SRI via Web Crypto API**
Se necessário realizar a validação programática de integridade em tempo de execução, use a Web Crypto API no cliente <sup>24</sup>:

JavaScript


async function gerarHashWebCrypto(url) {\
`  `const resposta = await fetch(url);\
`  `const buffer = await resposta.arrayBuffer();\
`  `const hashBuffer = await crypto.subtle.digest('SHA-384', buffer);\
`  `const hashArray = Array.from(new Uint8Array(hashBuffer));\
`  `const stringBinaria = String.fromCharCode.apply(null, hashArray);\
`  `const base64Hash = btoa(stringBinaria);\
`  `return `sha384-${base64Hash}`;\
}
## -----**5. Criptografia no Transporte e Tratamento de Sessão**
- **Endurecimento de HSTS**: Seu redirecionamento básico para HTTPS passou na auditoria, mas é crítico estender a proteção.<sup>2</sup> Eleve o tempo mínimo de persistência de HSTS para dois anos (T\_HSTS = 63.072.000 segundos) e adicione as diretivas includeSubDomains e preload para solicitar a inclusão definitiva do domínio na lista de pré-carregamento dos navegadores (hstspreload.org).
- **Configuração Segura de Cookies**: Caso sua aplicação passe a utilizar cookies de sessão no futuro, emita obrigatoriamente as flags HttpOnly (impede a leitura das credenciais via JavaScript DOM, mitigando o vazamento em cenários de XSS), Secure (força o tráfego restrito ao canal criptografado HTTPS) e SameSite=Lax ou SameSite=Strict (proteção primária contra Cross-Site Request Forgery).
## -----**6. Modelos de Configuração para Servidores de Borda**
Abaixo estão descritas as diretivas consolidadas para cada servidor de borda, incluindo também a desativação de assinaturas de software e versões (Information Disclosure).<sup>25</sup>
### **Tabela 3: Diretivas de Configuração de Servidores de Borda**

|**Cabeçalho HTTP**|**Diretiva de Configuração no Nginx**|**Diretiva de Configuração no Apache**|**Diretiva de Configuração no IIS (web.config)**|
| :- | :- | :- | :- |
|**HSTS**|add\_header Strict-Transport-Security "max-age=63072000; includeSubDomains; preload" always;|Header always set Strict-Transport-Security "max-age=63072000; includeSubDomains; preload"|<add name="Strict-Transport-Security" value="max-age=63072000; includeSubDomains; preload" />|
|**CSP**|add\_header Content-Security-Policy "default-src 'self'; frame-ancestors 'none';" always;|Header always set Content-Security-Policy "default-src 'self'; frame-ancestors 'none';"|<add name="Content-Security-Policy" value="default-src 'self'; frame-ancestors 'none';" />|
|**Referrer-Policy**|add\_header Referrer-Policy "strict-origin-when-cross-origin" always;|Header always set Referrer-Policy "strict-origin-when-cross-origin"|<add name="Referrer-Policy" value="strict-origin-when-cross-origin" />|
|**X-Content-Type**|add\_header X-Content-Type-Options "nosniff" always;|Header set X-Content-Type-Options "nosniff"|<add name="X-Content-Type-Options" value="nosniff" />|
|**X-Frame-Options**|add\_header X-Frame-Options "DENY" always;|Header always append X-Frame-Options "DENY"|<add name="X-Frame-Options" value="DENY" />|
### -----**Configuração Completa por Servidor**
#### **A. Nginx (Arquivo de Configuração do Bloco server)**
Remova informações de versão globalmente e adicione a pilha de segurança no bloco HTTPS (listen 443 ssl):

Nginx


\# Ocultar versão de software nos cabeçalhos de erro\
server\_tokens off;\
\
server {\
`    `listen 443 ssl http2;\
`    `server\_name seu-dominio.com.br;\
\
`    `# Certificados SSL e parâmetros aqui\
\
`    `# Pilha de Cabeçalhos de Endurecimento\
`    `add\_header Strict-Transport-Security "max-age=63072000; includeSubDomains; preload" always;\
`    `add\_header X-Content-Type-Options "nosniff" always;\
`    `add\_header X-Frame-Options "DENY" always;\
`    `add\_header Referrer-Policy "strict-origin-when-cross-origin" always;\
`    `add\_header Content-Security-Policy "default-src 'self'; frame-ancestors 'none'; object-src 'none';" always;\
`    `add\_header Cross-Origin-Resource-Policy "same-origin" always;\
}
#### -----**B. Apache (Arquivo .htaccess ou Configuração do VirtualHost)**
Garanta a presença do módulo mod\_headers ativo no servidor Apache:

Apache


\# Ocultar informações de versão no arquivo principal de configuração httpd.conf\
ServerTokens ProductOnly\
ServerSignature Off\
\
<IfModule mod\_headers.c>\
`    `# Pilha de Cabeçalhos de Endurecimento\
`    `Header always set Strict-Transport-Security "max-age=63072000; includeSubDomains; preload"\
`    `Header set X-Content-Type-Options "nosniff"\
`    `Header always append X-Frame-Options "DENY"\
`    `Header always set Referrer-Policy "strict-origin-when-cross-origin"\
`    `Header always set Content-Security-Policy "default-src 'self'; frame-ancestors 'none'; object-src 'none';"\
`    `Header always set Cross-Origin-Resource-Policy "same-origin"\
</IfModule>
#### -----**C. IIS (Arquivo de Configuração web.config)**
Use o arquivo web.config no diretório raiz do IIS para inserir os cabeçalhos de resposta, remover cabeçalhos técnicos nativos do ecossistema Microsoft e desativar métodos inseguros por meio de regras de redirecionamento (URL Rewrite) <sup>25</sup>:

XML


<?xml version="1.0" encoding="utf-8"?>\
<configuration>\
`  `<system.webServer>\
`    `<httpProtocol>\
`      `<customHeaders>\
`        `<add name="Strict-Transport-Security" value="max-age=63072000; includeSubDomains; preload" />\
`        `<add name="X-Content-Type-Options" value="nosniff" />\
`        `<add name="X-Frame-Options" value="DENY" />\
`        `<add name="Referrer-Policy" value="strict-origin-when-cross-origin" />\
`        `<add name="Content-Security-Policy" value="default-src 'self'; frame-ancestors 'none'; object-src 'none';" />\
`        `<add name="Cross-Origin-Resource-Policy" value="same-origin" />\
`      `</customHeaders>\
`    `</httpProtocol>\
\
`    `<rewrite>\
`      `<outboundRules>\
`        `<rule name="Remover Server Header">\
`          `<match serverVariable="RESPONSE\_SERVER" pattern=".+" />\
`          `<action type="Rewrite" value="" />\
`        `</rule>\
`        `<rule name="Remover ASPNet Version">\
`          `<match serverVariable="RESPONSE\_X-ASPNET-VERSION" pattern=".+" />\
`          `<action type="Rewrite" value="" />\
`        `</rule>\
`        `<rule name="Remover Powered By">\
`          `<match serverVariable="RESPONSE\_X-POWERED-BY" pattern=".+" />\
`          `<action type="Rewrite" value="" />\
`        `</rule>\
`      `</outboundRules>\
`    `</rewrite>\
\
`    `<security>\
`      `<requestFiltering>\
`        `<verbs>\
`          `<add verb="OPTIONS" allowed="false" />\
`        `</verbs>\
`      `</requestFiltering>\
`    `</security>\
`  `</system.webServer>\
</configuration>
#### **Referências citadas**
1. HTTP Header Security Test - HTTP Observatory - MDN Web Docs - Mozilla, acessado em maio 16, 2026, <https://developer.mozilla.org/en-US/observatory>
1. Tests & Scoring | HTTP Observatory - MDN Web Docs - Mozilla, acessado em maio 16, 2026, <https://developer.mozilla.org/en-US/observatory/docs/tests_and_scoring>
1. Content Security Policy (CSP) - HTTP - MDN Web Docs, acessado em maio 16, 2026, <https://developer.mozilla.org/en-US/docs/Web/HTTP/Guides/CSP>
1. Backend for HTTP Observatory on MDN - GitHub, acessado em maio 16, 2026, <https://github.com/mdn/mdn-http-observatory>
1. Content-Security-Policy (CSP) header - HTTP - MDN Web Docs, acessado em maio 16, 2026, <https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Content-Security-Policy>
1. Understanding Referrer Policy Strict-Origin-When-Cross-Origin | Swetrix, acessado em maio 16, 2026, <https://swetrix.com/blog/referrer-policy-strict-origin-when-cross-origin>
1. Referrer policy configuration - Security - MDN Web Docs, acessado em maio 16, 2026, <https://developer.mozilla.org/en-US/docs/Web/Security/Practical_implementation_guides/Referrer_policy>
1. HTTP Headers - OWASP Cheat Sheet Series, acessado em maio 16, 2026, <https://cheatsheetseries.owasp.org/cheatsheets/HTTP_Headers_Cheat_Sheet.html>
1. Subresource Integrity - Security - MDN Web Docs, acessado em maio 16, 2026, <https://developer.mozilla.org/en-US/docs/Web/Security/Defenses/Subresource_Integrity>
1. Content Security Policy (CSP) - HTTP - MDN Web Docs, acessado em maio 16, 2026, <https://mdn2.netlify.app/en-us/docs/web/http/csp/>
1. Content-Security-Policy-Report-Only header - HTTP - MDN Web Docs, acessado em maio 16, 2026, <https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Content-Security-Policy-Report-Only>
1. Referrer-Policy header - HTTP - MDN Web Docs, acessado em maio 16, 2026, <https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Referrer-Policy>
1. OWASP Secure Headers Project, acessado em maio 16, 2026, <https://owasp.org/www-project-secure-headers/>
1. Cross-Origin Resource Policy (CORP) - HTTP - MDN Web Docs, acessado em maio 16, 2026, <https://developer.mozilla.org/en-US/docs/Web/HTTP/Guides/Cross-Origin_Resource_Policy>
1. Cross-Origin Resource Policy (CORP) implementation - Security - MDN Web Docs, acessado em maio 16, 2026, <https://developer.mozilla.org/en-US/docs/Web/Security/Practical_implementation_guides/CORP>
1. Cross-Origin-Resource-Policy (CORP) header - HTTP - MDN Web Docs, acessado em maio 16, 2026, <https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Cross-Origin-Resource-Policy>
1. Cross-Origin-Opener-Policy (COOP) header - HTTP - MDN Web Docs, acessado em maio 16, 2026, <https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Cross-Origin-Opener-Policy>
1. HTTP Security Response Headers Cheat Sheet, acessado em maio 16, 2026, <https://pentest.y-security.de/OWASP%20Cheat%20Sheet%20Series/HTTP_Headers_Cheat_Sheet/>
1. Cross-Origin-Embedder-Policy (COEP) header - HTTP - MDN Web Docs, acessado em maio 16, 2026, <https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Cross-Origin-Embedder-Policy>
1. content/files/en-us/web/http/reference/headers/cross-origin-embedder-policy/index.md at main - GitHub, acessado em maio 16, 2026, <https://github.com/mdn/content/blob/main/files/en-us/web/http/reference/headers/cross-origin-embedder-policy/index.md?plain=1>
1. Cross-Origin Resource Sharing (CORS) - HTTP - MDN Web Docs, acessado em maio 16, 2026, <https://developer.mozilla.org/en-US/docs/Web/HTTP/Guides/CORS>
1. SRI Hash Generator - Subresource Integrity - Inventive HQ, acessado em maio 16, 2026, <https://inventivehq.com/tools/developer/sri-hash-generator>
1. HTTP headers - MDN Web Docs - Mozilla, acessado em maio 16, 2026, <https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers>
1. Verify CDN integrity with sha384sum in browsers - Transloadit, acessado em maio 16, 2026, <https://transloadit.com/devtips/verify-cdn-integrity-with-sha384sum-in-browsers/>
1. IIS Settings for OWASP, acessado em maio 16, 2026, <https://help.reliasoft.com/xfracas/ig/configure_iis_for_security/iis-settings-overview.htm>
1. Hardening your HTTP response headers - Scott Helme, acessado em maio 16, 2026, <https://scotthelme.co.uk/hardening-your-http-response-headers/>
