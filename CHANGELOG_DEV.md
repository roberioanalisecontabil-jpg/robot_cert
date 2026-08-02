# CHANGELOG_DEV — Diário Técnico de Desenvolvimento
> **Analise CertiDigital** (`robot_cert`) — Roberio França | AnaliseGroupTI
>
> ⚠️ **LEIA ESTE ARQUIVO PRIMEIRO** antes de iniciar qualquer sessão de desenvolvimento.
> Ele registra o histórico real de mudanças, decisões técnicas e o estado atual do projeto.

---

## 📌 Estado Atual do Projeto (Atualizar a cada sessão)

| Campo              | Valor                                      |
|--------------------|--------------------------------------------|
| **Data da última atualização** | 2026-08-02                  |
| **Branch ativa**   | main                                       |
| **Versão/Build**   | Configuração Vercel Serverless pronta      |
| **Última tarefa concluída** | Verificação + Estrutura para Vercel (api/index.py + vercel.json) |
| **Próxima tarefa** | Importar repositório no Vercel e configurar Env Vars |

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

### 🗓️ 2026-08-02 — Configuração Completa e Verificação para Deploy no Vercel

**Objetivo da sessão:** Preparar e verificar o projeto FastAPI para rodar nativamente como Serverless Function no Vercel.

**Ações realizadas:**
- Criado o arquivo `api/index.py` importando `app` de `app.main` para padrão nativo Vercel Python.
- Criado `vercel.json` configurado com `@vercel/python`, rotas genéricas (`/(.*)` -> `api/index.py`) e empacotamento explícito dos assets (`templates/**`, `static/**`).
- Protegidos os hooks de inicialização e salvamento (`app/main.py` e `app/settings_state.py`) com blocos `try...except OSError` para imunidade contra o sistema de arquivos read-only do Vercel.
- Validada a importação limpa da aplicação via `api/index.py`.

**Arquivos criados / modificados:**
- `api/index.py` → Entrypoint da função serverless
- `vercel.json` → Arquivo de rotas e build Vercel
- `app/main.py` → Proteção `OSError` na startup hook
- `app/settings_state.py` → Proteção `OSError` na `_save_file`

**Próximos passos (Ação do Usuário):**
- [ ] Conectar conta GitHub no Vercel (https://vercel.com)
- [ ] Importar o repositório `roberioanalisecontabil-jpg/robot_cert`
- [ ] Definir as variáveis de ambiente: `JWT_SECRET_KEY`, `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `API_KEY`
- [ ] Fazer o deploy e testar a URL `.vercel.app`

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
| 1 | (Registrar aqui conforme identificado) | — | Aberto |

---

*Arquivo mantido manualmente a cada sessão de desenvolvimento com o assistente de IA.*
