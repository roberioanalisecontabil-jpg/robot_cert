# CHANGELOG_DEV — Diário Técnico de Desenvolvimento
> **Analise CertiDigital** (`robot_cert`) — Roberio França | AnaliseGroupTI
>
> ⚠️ **LEIA ESTE ARQUIVO PRIMEIRO** antes de iniciar qualquer sessão de desenvolvimento.
> Ele registra o histórico real de mudanças, decisões técnicas e o estado atual do projeto.

---

## 📌 Estado Atual do Projeto (Atualizar a cada sessão)

| Campo              | Valor                                      |
|--------------------|--------------------------------------------|
| **Data da última atualização** | 2026-08-08                  |
| **Branch ativa**   | main                                       |
| **Versão/Build**   | Deploy Vercel ativo em produção            |
| **Última tarefa concluída** | Opt-in do cofre vinculado ao `machine_id` na tela e na barreira do upload + cobertura do circuito (136 testes) |
| **Próxima tarefa** | Validação com agente Windows real (transporte ECDH/AES e instalação na estação) |

---

## 🏗️ Arquitetura Resumida (Referência Rápida)

```
robot_cert/
├── api/            → Entrypoint Serverless para Vercel (api/index.py)
├── app/            → Portal Web (FastAPI) — backend principal
│   ├── main.py         → Entry point, rotas principais
│   └── notification_service.py → Serviço de alertas (SMTP, etc.)
├── agent/          → Agente Windows (scanner local de certificados)
├── templates/      → Jinja2 HTML templates do portal
├── static/         → CSS, JS, imagens
├── vercel.json     → Configuração de Serverless Function e empacotamento Vercel
├── supabase/       → Migrations SQL do banco Supabase
├── tests/          → Testes automatizados (pytest)
├── scripts/        → Scripts utilitários/auxiliares
└── .env            → Variáveis de ambiente (não versionado)
```

**Stack:** Python 3.11+, FastAPI, Uvicorn, Supabase (PostgreSQL), Vercel Serverless

---

## 📋 Registro de Sessões de Desenvolvimento

---

### 🗓️ 2026-08-08 — Painel de Opt-in do Cofre: correção do `machine_id` e testes de regressão

**Objetivo da sessão:** Validar o painel de opt-in recém-commitado (`c28f98a`) e fechar as pendências de infraestrutura de teste.

**Bug encontrado e corrigido (falha silenciosa, severidade alta):**

O painel gravava a autorização com `machine_id: cert.machine_id || "default"`. Mas em `fonte=auto` o portal devolve o `machine_id` na **raiz** do payload de `/api/certificados` (`app/main.py:334-342`), não em cada item — então `cert.machine_id` era sempre `undefined` e **toda autorização ia para o literal `"default"`**.

Do outro lado, o agente consulta filtrando pelo machine_id dele (`agent/installer_client.py:57`) e `listar_optin_fingerprints` aplica `.eq("machine_id", ...)` (`app/cert_installer.py:332`). O `_machine_id()` do agente (`agent/run_agent.py:335`) resolve de `MACHINE_ID` → config local → settings → `"default"`.

Resultado: em qualquer instalação cujo machine_id não fosse literalmente `"default"`, o admin clicava "Autorizar", o badge ficava verde, e o agente **nunca recebia o certificado**. Nenhum erro em lugar nenhum. O GET sem filtro de máquina agravava, mostrando o opt-in de todas as máquinas e mascarando a divergência.

**Arquivos modificados:**
- `templates/instalador.html` → `_optinMachineId` lido da raiz do payload; POST usa ele; GET de `/vault-optin` passa `?machine_id=`; busca do inventário virou sequencial (o machine_id precisa sair dela antes); máquina exibida no resumo do painel

**Arquivos criados:**
- `pytest.ini` → `testpaths = tests` + `norecursedirs`. Sem isto, `pytest` sem argumentos varria `robot_cert-main/` (backup do zip antigo) e quebrava com `ImportPathMismatchError`
- `tests/test_instalador_optin_machine_id.py` → 4 testes de invariante do painel (lado da tela)
- `tests/test_cert_installer_optin_e2e.py` → 8 testes do circuito completo pelo HTTP real (lado do servidor), com fake de Supabase em memória

**Por que dois arquivos de teste:** o bug sobreviveu porque *cada lado, isolado, estava correto* — a tela gravava um machine_id válido, o servidor filtrava corretamente por machine_id. O que faltava era um teste **atravessando a fronteira**: autorizar na máquina A e verificar que o agente da A vê e o da B não vê. O fake de Supabase é um banco de brinquedo, não mock de asserção, para exercitar a lógica de filtro real em vez de conferir que uma chamada aconteceu.

**Decisões técnicas tomadas:**
- O `Promise.all` do carregamento do painel foi desfeito **de propósito**: o machine_id sai do inventário e precisa entrar na consulta de autorizações. Reintroduzir o paralelismo volta a perder o filtro — está documentado no código e coberto por teste.
- `robot_cert-main/` **não foi apagado** (é backup, gitignored, 0,7 MB). Resolvido por config em vez de remoção.

**Validações executadas:**
- Suíte: **136 passed** (123 anteriores + 4 do painel + 9 do circuito), `pytest` puro já funciona
- Teste de mutação em ambos os arquivos novos — não são testes decorativos:
  - reintroduzindo cada metade do bug no template: 1 e 2 falhas
  - removendo `.eq("machine_id", ...)` de `listar_optin_fingerprints`: 2 falhas
  - fazendo `revogar_do_cofre` não apagar o PFX: 1 falha
  - devolvendo a barreira do `/upload-pfx` ao estado global: 1 falha
- Portal no ar em `127.0.0.1:8020`: `/api/health` respondeu com os campos novos, `/instalador` renderizou HTTP 200 com todos os marcadores do painel
- Os 6 helpers JS usados pelo painel conferidos em `static/ui-common.js`

**Segundo achado, corrigido na mesma sessão — barreira global no `/upload-pfx`:**

`app/main.py` chamava `cert_installer.listar_optin_fingerprints()` **sem `machine_id`**, embora `body.machine_id` estivesse disponível na requisição. A barreira de servidor do upload era portanto global: bastava o fingerprint estar autorizado em qualquer máquina.

O agente bem-comportado nunca esbarrava nisso — só envia o que a consulta filtrada dele devolveu. Mas a barreira existe justamente para o agente "desatualizado (ou adulterado)", e contra esse é que ela não olhava a máquina: declarando-se da estação B, ele gravava o PFX de um certificado autorizado só na A e, como `upsert_pfx` usa `on_conflict="fingerprint"`, sobrescrevia o registro legítimo — o mesmo vetor já descrito em `require_agent_or_admin`, por outro caminho.

Passou a ser `listar_optin_fingerprints(body.machine_id)`. Verificado antes de aplicar que o caminho legítimo não quebra: `agent/installer_client.py` usa a **mesma** variável `machine_id` na consulta (linha 84) e no payload do upload (linha 108).

**Pendências / Próximos passos:**
- [ ] Validação com agente Windows real — o circuito lógico está coberto, mas o transporte ECDH/AES e a instalação na estação não
- [ ] Definir `ENCRYPTION_KEY` nos ambientes (ver dívida técnica #2)

---

### 🗓️ 2026-08-03 — Módulo Instalador Remoto de Certificados

**Objetivo da sessão:** Implementar instalação remota de certificados na estação do usuário via agente Windows, e endurecer o módulo após revisão.

**Commits:** `fce8c4a` (implementação) e `f2557aa` (endurecimento + testes)

**Entregue:**
- Transporte cifrado ponta a ponta: **AES-256-GCM + ECDH** entre portal e agente
- Cofre de PFX no servidor (`cert_pfx_store`) com material cifrado em repouso e `key_version` gravado por registro, permitindo rotação incremental de chave
- Tabela `cert_vault_optin` + **RLS no Supabase** (`REVOKE` de `anon`/`authenticated`, acesso só via `service_role`)
- Suíte de **123 testes** automatizados

**Cinco decisões do endurecimento** (documentadas em `tests/test_cert_installer_hardening.py`):
1. **Opt-in do cofre** — o agente enviava TODOS os certificados lidos a cada ciclo; numa base de 1.028, mil chaves privadas copiadas ao servidor sem decisão explícita
2. **Token de instalação** era gerado no `/prepare` e nunca chegava ao agente — a instalação nunca completava
3. **`key_version` gravado** — sem ele, rotacionar a chave exigiria recifrar tudo
4. **Senha do PFX não é mais armazenada** — era cifrada com a MESMA chave do PFX
5. **Limite de upload** reduzido de 50 MB para 1 MB

**Migrations criadas:**
- `20260803_cert_installer.sql`, `20260803120000_cert_installer_rls.sql`, `20260803130000_cert_installer_hardening.sql`

**Nota:** a UI do opt-in ficou pendente nesta sessão e foi entregue em `c28f98a` — com o bug de `machine_id` corrigido em 08/08.

---

### 🗓️ 2026-08-02 — Configuração Completa e Deploy de Sucesso no Vercel

**Objetivo da sessão:** Preparar e verificar o projeto FastAPI para rodar nativamente como Serverless Function no Vercel e colocar o portal no ar.

**Ações realizadas:**
- Criado o arquivo `api/index.py` importando `app` de `app.main` para padrão nativo Vercel Python.
- Criado `vercel.json` configurado com `@vercel/python`, rotas genéricas (`/(.*)` -> `api/index.py`) e empacotamento explícito dos assets (`templates/**`, `static/**`).
- Protegidos os hooks de inicialização e salvamento (`app/main.py` e `app/settings_state.py`) com blocos `try...except OSError` para imunidade contra o sistema de arquivos read-only do Vercel.
- Validada a importação limpa da aplicação via `api/index.py`.
- **Deploy realizado com sucesso no Vercel!** O portal web agora está operando em produção no ambiente serverless.

**Arquivos criados / modificados:**
- `api/index.py` → Entrypoint da função serverless
- `vercel.json` → Arquivo de rotas e build Vercel
- `app/main.py` → Proteção `OSError` na startup hook
- `app/settings_state.py` → Proteção `OSError` na `_save_file`

**Status do Deploy:**
- [x] Conectar conta GitHub no Vercel
- [x] Importar o repositório `roberioanalisecontabil-jpg/robot_cert`
- [x] Definir variáveis de ambiente (`JWT_SECRET_KEY`, `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `API_KEY`)
- [x] Deploy concluído e portal funcionando no Vercel.

---

### 🗓️ 2026-08-01 — Scripts de Liberação e Teste de Porta

**Objetivo da sessão:** Criar scripts PowerShell para configurar o firewall e validar acesso externo.

**Contexto:** Servidor de destino é uma **máquina Windows separada** com acesso via RDP/TeamViewer.

**Arquivos criados:**
- `scripts/setup_porta_servidor.ps1` → Rodar **no servidor** (como Admin): configura firewall, exibe IPs, valida Python
- `scripts/testar_porta_externa.ps1` → Rodar **nesta máquina** (dev): testa se a porta ficou acessível externamente

**Plano de execução (ordem):**
1. Copiar `scripts/setup_porta_servidor.ps1` para o servidor via RDP
2. Rodar como Administrador → anota o IP local e externo exibidos
3. Configurar Port Forwarding no roteador usando o IP local exibido
4. Voltar para esta máquina e rodar `scripts/testar_porta_externa.ps1`
5. Se OK → prosseguir com a migração do portal

**Decisões técnicas tomadas:**
- Banco (Supabase) permanece na nuvem por ora → migração do banco fica para fase 2
- Servidor de destino confirmado: máquina Windows separada (acesso RDP)

**Pendências / Próximos passos:**
- [ ] Executar `setup_porta_servidor.ps1` no servidor Windows
- [ ] Configurar Port Forwarding no roteador
- [ ] Validar com `testar_porta_externa.ps1`
- [ ] Iniciar migração do portal (copiar projeto, .env, instalar deps, NSSM)

---

### 🗓️ 2026-08-01 — Planejamento: Migração Render → Windows Server

**Objetivo da sessão:** Planejar e documentar a migração do portal do Render para Windows Server self-hosted.

**Contexto:** O Render reduziu o plano gratuito, causando instabilidade. A solução é hospedar o portal em servidor Windows próprio.

**Arquivos criados:**
- `docs/GUIA_MIGRACAO_WINDOWS_SERVER.md` → Guia completo passo a passo da migração

**Decisões técnicas tomadas:**
- `gunicorn` NÃO funciona no Windows nativamente → usar `uvicorn` diretamente ou `waitress`
- Usar **NSSM** para registrar o portal como serviço Windows (auto-start, logs automáticos)
- Porta escolhida: **8020** (mesma já usada no projeto)
- Nginx como proxy reverso opcional se quiser HTTPS com domínio

**Pendências / Próximos passos:**
- [ ] Instalar Python 3.11+ no Windows Server
- [ ] Clonar/copiar projeto para `C:\Apps\robot_cert`
- [ ] Criar `.env` com variáveis de produção
- [ ] Abrir porta 8020 no Firewall do Windows (comando NSSM pronto no guia)
- [ ] Configurar Port Forwarding no roteador (se servidor em rede local)
- [ ] Instalar NSSM e registrar serviço
- [ ] Atualizar `CERT_ROBOT_BASE_URL` no `.env` dos agentes locais
- [ ] Testar acesso externo antes de desligar o Render

---

### 🗓️ 2026-08-01 — Sessão Inicial / Setup do Changelog

**Objetivo da sessão:** Criar estrutura de rastreamento contínuo para o projeto.

**Arquivos criados:**
- `CHANGELOG_DEV.md` ← este arquivo, na raiz do projeto

**Arquivos em foco (abertos no editor):**
- `tests/test_smtp_alerts.py`
- `app/notification_service.py`
- `supabase/migrations/20260620_add_smtp_settings.sql`
- `tests/test_api_routes.py`
- `scratch/delete_test_user.py`
- `app/main.py`

**Contexto identificado:**
- O projeto está em fase ativa de desenvolvimento do módulo de **alertas SMTP**.
- Existe uma migration SQL para configurações SMTP (`20260620_add_smtp_settings.sql`).
- Testes estão sendo escritos para as rotas de API e para os alertas SMTP.

**Decisões técnicas tomadas:**
- Nenhuma nesta sessão (apenas setup).

**Pendências / Próximos passos:**
- [ ] Definir e registrar o escopo da próxima tarefa de desenvolvimento.

---

## 📐 Template para Nova Sessão

> Copie e cole este bloco ao iniciar cada nova sessão:

```
### 🗓️ YYYY-MM-DD — [Título da Sessão]

**Objetivo da sessão:** 

**Arquivos modificados:**
- `caminho/arquivo.py` → descrição da mudança

**Arquivos criados:**
- `caminho/novo_arquivo.py` → propósito

**Arquivos removidos:**
- (nenhum)

**Decisões técnicas tomadas:**
- 

**Bugs corrigidos:**
- 

**Pendências / Próximos passos:**
- [ ] 
```

---

## 🔑 Convenções do Projeto

| Convenção              | Detalhe                                          |
|------------------------|--------------------------------------------------|
| API Key header         | `X-API-Key`                                      |
| Banco de dados         | Supabase (PostgreSQL via REST)                   |
| Porta do portal local  | `8020`                                           |
| Ambiente virtual       | `.venv/` na raiz                                 |
| Testes                 | `pytest` em `tests/`                             |
| Agente                 | `agent/run_agent.py`                             |
| Variáveis de ambiente  | `.env` (não versionado), exemplo em `.env.example` |

---

## ⚠️ Dívidas Técnicas / Riscos Conhecidos

| # | Descrição | Severidade | Status |
|---|-----------|------------|--------|
| 1 | `robot_cert-main/` é uma cópia inteira do projeto dentro dele mesmo (backup do zip de 25/05, gitignored, 0,7 MB). Contornado por `pytest.ini`, mas continua confundindo buscas e ferramentas | Baixa | Contornado |
| 2 | `ENCRYPTION_KEY` não definida (`/api/health` → `smtp_key_dedicada: false`). Sem ela a chave do SMTP é derivada da `JWT_SECRET_KEY` — se a JWT diferir entre ambientes, a senha SMTP para de descriptografar | Média | Aberto |
| 3 | Instalação fim-a-fim: o circuito do opt-in passou a ter cobertura (`test_cert_installer_optin_e2e.py`); falta o transporte ECDH/AES e a instalação na estação, que dependem de agente Windows real | Média | Parcial |
| 6 | Barreira de servidor do `/upload-pfx` era global — não conferia o `machine_id` do agente contra o da autorização. Agente adulterado podia sobrescrever `cert_pfx_store` de outra máquina | Média | **Resolvido em 08/08** |
| 4 | `autorizar_no_cofre` usa `on_conflict="fingerprint"` — o mesmo certificado não pode estar autorizado em duas máquinas ao mesmo tempo; a segunda autorização move a primeira | Baixa | Aberto |
| 5 | `app/main.py` usa `@app.on_event("startup")`, deprecado no FastAPI (avisos na suíte). Migrar para lifespan handlers | Baixa | Aberto |

---

*Arquivo mantido manualmente a cada sessão de desenvolvimento com o assistente de IA.*
