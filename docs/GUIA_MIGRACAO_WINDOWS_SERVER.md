# 🖥️ Guia de Migração: Render → Windows Server
> **Analise CertiDigital** (`robot_cert`)
> Última atualização: 2026-08-01

---

## 📋 Visão Geral

O portal (FastAPI + Gunicorn/Uvicorn) será migrado do Render para um Windows Server
self-hosted. O banco de dados (Supabase) continua na nuvem — apenas o processo Python
muda de host.

```
ANTES:  Render Cloud ──HTTP──> Supabase (nuvem)
DEPOIS: Windows Server ──HTTP──> Supabase (nuvem)
           └─ Agente local também roda aqui (opcional)
```

---

## ✅ Pré-requisitos no Windows Server

- [ ] Windows Server 2016/2019/2022 (ou Windows 10/11 Pro também funciona)
- [ ] Python 3.11+ instalado (baixar em python.org, marcar "Add to PATH")
- [ ] Git instalado (opcional, para clonar o repo)
- [ ] Acesso de Administrador na máquina
- [ ] IP externo fixo OU DDNS configurado (ex.: No-IP, DuckDNS)

---

## 🚀 PARTE 1 — Instalar o Projeto no Servidor

### 1.1 Clonar ou copiar o projeto

```powershell
# Opção A: via Git
git clone https://github.com/RoberioMelo/robot_cert.git C:\Apps\robot_cert

# Opção B: copiar a pasta manualmente para
# C:\Apps\robot_cert
```

### 1.2 Criar o ambiente virtual e instalar dependências

```powershell
cd C:\Apps\robot_cert

# Criar .venv
python -m venv .venv

# Ativar
.venv\Scripts\Activate.ps1

# Instalar dependências (gunicorn NÃO funciona nativamente no Windows!)
# Use waitress como substituto de gunicorn no Windows:
pip install -r requirements.txt
pip install waitress
```

> ⚠️ **ATENÇÃO — Gunicorn no Windows:**
> O `gunicorn` (usado no Render) **NÃO funciona no Windows** nativamente.
> No Windows Server, use `waitress` OU `uvicorn` diretamente.

### 1.3 Criar o arquivo .env

```powershell
# Copiar o exemplo e editar com os valores reais
Copy-Item .env.example .env
notepad .env
```

Preencher no `.env`:
```env
# Obrigatórias
SUPABASE_URL=https://xxxx.supabase.co
SUPABASE_SERVICE_KEY=eyJ...
API_KEY=sua_chave_secreta_aqui
JWT_SECRET_KEY=uma_string_longa_e_aleatoria

# URL que o agente vai usar para chamar este servidor
CERT_ROBOT_BASE_URL=http://SEU_IP_OU_DOMINIO:8020
CERT_ROBOT_API_KEY=sua_chave_secreta_aqui
```

---

## 🔌 PARTE 2 — Firewall: só as portas do proxy TLS

> **Desenho (auditoria de 24/09/2026, achados #37 e #38):** a aplicação (uvicorn) faz bind **só em `127.0.0.1:8020`**. Quem atende a rede é o **Caddy** (`deploy/Caddyfile`), com TLS (Let's Encrypt por DNS na Cloudflare) e redirecionamento automático de 80 para 443. O firewall abre **80 e 443**; a **8020 nunca** é aberta para fora — HTTP puro na rede entregaria JWT, X-API-Key e o cofre em claro.

### 2.1 Via script (recomendado)

```powershell
# Como Administrador. Cria a regra para 80/443, remove uma regra antiga que
# abrisse a 8020 e confere que a 8020 só ouve em loopback.
.\scripts\setup_porta_servidor.ps1
```

### 2.2 Via PowerShell, à mão

```powershell
New-NetFirewallRule `
  -DisplayName "AnaliseCertiDigital-Proxy-HTTPS" `
  -Direction Inbound `
  -Protocol TCP `
  -LocalPort 80,443 `
  -Action Allow `
  -Profile Domain,Private

# Se existir, remova a regra antiga que abria a 8020:
Remove-NetFirewallRule -DisplayName "AnaliseCertiDigital-Portal" -ErrorAction SilentlyContinue
```

### 2.3 Verificar o bind da aplicação

```powershell
# Depois de iniciar o servidor: TEM de aparecer 127.0.0.1:8020, nunca [::]:8020 nem o IP da máquina.
netstat -ano | findstr :8020
```

---

## 🌐 PARTE 3 — Acesso de fora

Os portais são atendidos **só na rede interna e pela VPN** (os nomes `certificado.analisegroup.cnt.br` e `hardlyze.analisegroup.cnt.br` resolvem para `10.200.0.4`). Não há encaminhamento de porta no roteador, e não deve haver um para a 8020 em hipótese nenhuma. Se um dia for preciso expor à internet, o que se encaminha é a **443 para o Caddy**, e o Caddyfile passa a exigir revisão de cabeçalhos e limites — não a aplicação.

### Descobrir o IP local do servidor:
```powershell
ipconfig | findstr "IPv4"
```

---

## ▶️ PARTE 4 — Iniciar o Servidor

### 4.1 Modo de teste (manual, via PowerShell)

```powershell
cd C:\Apps\robot_cert
.venv\Scripts\Activate.ps1

# Bind em 127.0.0.1: a rede é do Caddy (Parte 6). Sem --reload em produção.
uvicorn app.main:app --host 127.0.0.1 --port 8020 --workers 2 --no-server-header

# Ou pelo script do repositório (mesmo bind; -Dev liga o --reload só em desenvolvimento)
.\scripts\servir.ps1
```

### 4.2 Script de inicialização conveniente

Criar arquivo `start_portal.bat` na raiz:
```batch
@echo off
cd /d C:\Apps\robot_cert
call .venv\Scripts\activate.bat
uvicorn app.main:app --host 127.0.0.1 --port 8020 --workers 2 --no-server-header
pause
```

---

## 🔄 PARTE 5 — Rodar como Serviço Windows (Produção)

Para que o portal inicie automaticamente com o Windows e rode em background, usar o **NSSM** (Non-Sucking Service Manager).

### 5.1 Instalar NSSM

```powershell
# Baixar NSSM
Invoke-WebRequest -Uri "https://nssm.cc/release/nssm-2.24.zip" -OutFile "C:\Apps\nssm.zip"
Expand-Archive "C:\Apps\nssm.zip" -DestinationPath "C:\Apps\nssm"
# Copiar para PATH
Copy-Item "C:\Apps\nssm\nssm-2.24\win64\nssm.exe" "C:\Windows\System32\"
```

### 5.2 Registrar o portal como serviço

```powershell
# Abrir PowerShell como ADMINISTRADOR

nssm install AnaliseCertiDigital

# Na janela que abre, preencher:
# Path:            C:\Apps\robot_cert\.venv\Scripts\uvicorn.exe
# Startup dir:     C:\Apps\robot_cert
# Arguments:       app.main:app --host 127.0.0.1 --port 8020 --workers 2 --no-server-header
```

### 5.3 Ou instalar via linha de comando (sem GUI)

```powershell
nssm install AnaliseCertiDigital "C:\Apps\robot_cert\.venv\Scripts\uvicorn.exe"
nssm set AnaliseCertiDigital AppParameters "app.main:app --host 127.0.0.1 --port 8020 --no-server-header"
nssm set AnaliseCertiDigital AppDirectory "C:\Apps\robot_cert"
nssm set AnaliseCertiDigital DisplayName "Analise CertiDigital Portal"
nssm set AnaliseCertiDigital Description "Portal FastAPI de monitoramento de certificados"
nssm set AnaliseCertiDigital Start SERVICE_AUTO_START
nssm set AnaliseCertiDigital AppStdout "C:\Apps\robot_cert\logs\portal_stdout.log"
nssm set AnaliseCertiDigital AppStderr "C:\Apps\robot_cert\logs\portal_stderr.log"

# Criar pasta de logs
New-Item -ItemType Directory -Force "C:\Apps\robot_cert\logs"

# Iniciar o serviço
nssm start AnaliseCertiDigital

# Verificar status
nssm status AnaliseCertiDigital
```

### 5.4 Comandos úteis do serviço

```powershell
nssm start AnaliseCertiDigital      # iniciar
nssm stop AnaliseCertiDigital       # parar
nssm restart AnaliseCertiDigital    # reiniciar
nssm remove AnaliseCertiDigital     # remover serviço
Get-Service AnaliseCertiDigital     # status via PowerShell nativo
```

---

## 🔒 PARTE 6 — HTTPS com Caddy (obrigatório)

O portal emite `Strict-Transport-Security`, então **precisa** estar atrás de TLS: quem faz a terminação e o redirecionamento HTTP→HTTPS é o Caddy. A configuração de referência está versionada em **`deploy/Caddyfile`** (reverse proxy para `127.0.0.1:8020` e `127.0.0.1:8021`, certificados Let's Encrypt por desafio DNS na Cloudflare). O binário e o instalador (`caddy.exe` com o plugin Cloudflare, `instalar-caddy.ps1`) ficam na pasta `Apps` do servidor, fora do repositório.

### 6.1 Instalar

```powershell
# Como Administrador, na pasta Apps copiada para o servidor:
.\instalar-caddy.ps1 -Token <token da API Cloudflare, só Zona > DNS > Editar>
# O token vai para a variável de ambiente CLOUDFLARE_API_TOKEN do serviço; NUNCA para o Caddyfile.
```

### 6.2 Conferir

```powershell
# 80 redireciona para 443 (é o que o HSTS pressupõe):
curl.exe -I http://certificado.analisegroup.cnt.br/     # esperado: 308 + Location: https://...
# TLS válido e o portal respondendo:
curl.exe -I https://certificado.analisegroup.cnt.br/api/health
```

Cabeçalhos: o Caddy acrescenta `X-Forwarded-For` e `X-Forwarded-Proto`; o portal confia em **um** proxy (`NUM_PROXIES_CONFIAVEIS=1`) e, com `HOSTS_PERMITIDOS` definido, recusa `Host` fora da lista.

---

## ✅ PARTE 7 — Checklist Final de Validação

```
[ ] Python instalado e no PATH
[ ] .venv criado e dependências instaladas
[ ] .env configurado com todas as chaves
[ ] Firewall: 80 e 443 abertas (scripts/setup_porta_servidor.ps1); 8020 fechada para fora
[ ] netstat mostra a aplicação só em 127.0.0.1:8020
[ ] Servidor inicia sem erros (testar manualmente primeiro)
[ ] Caddy instalado; http:// redireciona (308) para https:// e o certificado é válido
[ ] Serviço NSSM configurado e iniciando automaticamente
[ ] Logs sendo gravados em C:\Apps\robot_cert\logs\
[ ] Atualizar CERT_ROBOT_BASE_URL no .env dos agentes locais
[ ] Testar que os agentes estão comunicando com o novo endereço
```

---

## 🔧 Troubleshooting Comum

| Problema | Causa Provável | Solução |
|---|---|---|
| `Connection refused` de outra máquina | 80/443 fechadas no firewall, ou Caddy parado | Rever Parte 2 e `Get-Service caddy` |
| `gunicorn: command not found` / erro | Gunicorn não funciona no Windows | Usar `uvicorn` ou `waitress` |
| `ImportError` ao iniciar | `.venv` não ativado ou dependência faltando | Ativar .venv e `pip install -r requirements.txt` |
| Site cai após alguns minutos | Sessão PowerShell encerrou | Configurar serviço NSSM (Parte 5) |
| `Address already in use` | Outra instância rodando na porta 8020 | `Get-Process -Id (Get-NetTCPConnection -LocalPort 8020).OwningProcess` |
| Aplicação exposta em `[::]:8020` | Serviço subiu ouvindo em todas as interfaces | Corrigir o `AppParameters` do NSSM para `--host 127.0.0.1` |
| Agente não consegue conectar | URL desatualizada no .env do agente | Atualizar `CERT_ROBOT_BASE_URL` |

---

*Gerado em 2026-08-01 | Analise CertiDigital — Windows Server Migration Guide*
