# Plano de Ação para Segurança do Portal (Baseado no Guia OWASP 2025)

Este plano de ação foi estruturado utilizando como guia principal as diretrizes do documento **OWASP Security Guide for Web Development**. As tarefas foram categorizadas por nível de criticidade e impacto na postura de segurança do portal, começando pelas ações de maior urgência (mitigação de riscos imediatos) até as melhorias de nível baixo e contínuo.

---

## 🔴 Nível Crítico (Prioridade Máxima)
*Ações que mitigam os riscos de maior impacto e frequentes (ex: injeção, controle de acesso quebrado, sequestro de contas).*

- [ ] **1. Fortalecimento da Autenticação e Senhas (OWASP A01 / A07):**
  - Migrar o armazenamento de senhas para algoritmos de hash robustos como **Argon2id** ou **bcrypt** (com fator de custo adequado).
  - Implementar verificação de entropia de senhas no cadastro/alteração.
  - Remover restrições artificiais de complexidade e focar no comprimento (mínimo 8 caracteres com MFA, 15 sem MFA).
  - Garantir a validação de senhas em *tempo constante* (constant-time verification) para evitar ataques de temporização.

- [ ] **2. Controle Seguro de Sessões e Cookies:**
  - Configurar todos os cookies de sessão com as flags obrigatórias: `Secure`, `HttpOnly`, e `SameSite=Lax` (ou `Strict`).
  - Utilizar os prefixos de host (`__Host-` ou `__Secure-`) para os nomes dos cookies.
  - Implementar invalidação forçada de sessão caso haja variação extrema no User-Agent ou IP (Contexto de Conexão).

- [ ] **3. Endurecimento de Tokens JWT (Se aplicável na API):**
  - Rejeitar de forma estrita o algoritmo `"alg": "none"`.
  - Validar obrigatoriamente as declarações (claims) de emissor (`iss`), público-alvo (`aud`), expiração (`exp`) e não antes de (`nbf`).

- [ ] **4. Prevenção a XSS e Manipulação do DOM:**
  - Implementar sanitização robusta no client-side usando bibliotecas como **DOMPurify** (restringindo atributos perigosos e prevenindo DOM Clobbering).
  - Aplicar codificação de saída (Output Encoding) de acordo com o contexto (HTML, Atributo, JS, URL).

---

## 🟠 Nível Alto (Prioridade Alta)
*Ações focadas na proteção da infraestrutura, gerenciamento de segredos e higienização de dados.*

- [ ] **5. Sanitização e Validação Estrita de Entradas (OWASP A05):**
  - Implementar validação baseada em "Listas de Permissões" (Allowlist) em todas as camadas (Gateway, Backend).
  - Revisar todas as Expressões Regulares (RegEx) para que possuam âncoras (`^` e `$`) e limites rígidos de caracteres, prevenindo ataques de **ReDoS** (Negação de Serviço por RegEx).

- [ ] **6. Defesa contra Falsificação de Solicitação (CSRF):**
  - Implementar o padrão de *Synchronizer Token* para formulários e requisições que alterem estado (POST, PUT, DELETE).
  - Garantir que o token não seja exposto em URLs e que seja validado rigorosamente no servidor.

- [ ] **7. Segurança no Upload de Arquivos (OWASP A08):**
  - Estabelecer um pipeline de validação de 5 etapas: 
    1. Limite de tamanho; 
    2. Validação por *Magic Bytes* (assinatura real do arquivo); 
    3. Sanitização de nome; 
    4. Varredura antivírus; 
    5. Renomeação com UUID (jamais manter o nome original).
  - Armazenar uploads em pastas isoladas sem permissão de execução de scripts (fora do root web).

- [ ] **8. Gestão de Segredos e Envelope Criptográfico (OWASP A04):**
  - Remover quaisquer credenciais (senhas de banco, chaves de API) do código fonte e variáveis de ambiente desprotegidas.
  - Utilizar cofres de chaves (como HashiCorp Vault) ou injeção efêmera de segredos (via tmpfs em orquestradores de contêineres).
  - Implementar criptografia de *Envelope Criptográfico* (DEK / KEK) para dados altamente sensíveis armazenados no banco de dados.

---

## 🟡 Nível Médio (Melhorias Arquiteturais e Observabilidade)
*Práticas fundamentais para rastreamento forense e garantia de estabilidade nas regras de negócio.*

- [ ] **9. Autenticação e Autorização Transacional (OWASP A06 - Insecure Design):**
  - Impedir que usuários pulem etapas de formulários ou processos no sistema executando requisições diretas na API (Out-of-order execution).
  - O Backend deve checar o estado atual antes de aprovar uma mudança para o próximo passo.

- [ ] **10. Observabilidade, Logging e Trilha de Auditoria (OWASP A09):**
  - Gravar logs obrigatoriamente no formato **JSON estruturado** para evitar vulnerabilidades de "Log Injection" via manipulação de CRLF.
  - Padronizar o vocabulário de logs (ex: `authn_login_fail`, `authz_fail`).
  - Implementar bloqueios no sistema de log para **NUNCA** gravar senhas, tokens de sessão, e dados PII (Privacidade de Dados Pessoais).

- [ ] **11. Configuração de Cabeçalhos de Segurança (Security Headers):**
  - Implementar de maneira estrita os cabeçalhos de proteção, com destaque para a criação de uma política forte de **Content Security Policy (CSP)** (`default-src 'self'`), proibindo a execução de `unsafe-inline` e limitando recursos externos.

---

## 🟢 Nível Baixo / Ações Contínuas (Endurecimento Fino e Privacidade)
*Foco na blindagem do cliente final, garantias de privacidade contínuas e cultura DevSecOps.*

- [ ] **12. Salvaguardas de Privacidade do Usuário (IP Leakage):**
  - Se o portal carregar avatares ou mídias externas, utilizar um Proxy de Conteúdo local para ocultar o IP do usuário da fonte original (Third-Party).
  - Fornecer opção de bloqueio/consentimento de mídias externas no painel do usuário.
  - Fornecer opção de finalização de sessão de emergência ("Panic Mode") e revogação remota de sessões em outros dispositivos.

- [ ] **13. Governança e Cadeia de Suprimentos (OWASP A03):**
  - Executar varreduras periódicas em bibliotecas de terceiros usadas pelo frontend e backend para identificar e atualizar dependências com vulnerabilidades (CVEs) conhecidas.

- [ ] **14. Cultura "Secure by Design":**
  - Exigir modelagem de ameaças para cada nova funcionalidade crítica.
  - Integrar os testes automatizados descritos neste plano diretamente nas pipelines de CI/CD.
