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

## 🔌 PARTE 2 — Abrir a Porta no Firewall do Windows

### 2.1 Via PowerShell (como Administrador)

```powershell
# Abrir porta 8020 TCP para entrada (acesso externo ao portal)
New-NetFirewallRule `
  -DisplayName "Analise CertiDigital Portal" `
  -Direction Inbound `
  -Protocol TCP `
  -LocalPort 8020 `
  -Action Allow `
  -Profile Any

# Verificar se a regra foi criada
Get-NetFirewallRule -DisplayName "Analise CertiDigital Portal"
```

### 2.2 Via interface gráfica (alternativa)

1. Abrir **Windows Defender Firewall** → "Configurações avançadas"
2. Clicar em **Regras de Entrada** → "Nova Regra..."
3. Tipo: **Porta** → TCP → Porta específica: `8020`
4. Ação: **Permitir a conexão**
5. Perfis: marcar todos (Domínio, Privado, Público)
6. Nome: `Analise CertiDigital Portal`

### 2.3 Verificar se a porta está ouvindo

```powershell
# Após iniciar o servidor, verificar:
netstat -ano | findstr :8020
```

---

## 🌐 PARTE 3 — Liberar Porta no Roteador (Acesso Externo)

> Necessário somente se o servidor estiver em rede local (não em datacenter com IP direto).

### No roteador/modem:
1. Acessar painel do roteador (geralmente `192.168.1.1` ou `192.168.0.1`)
2. Ir em **Port Forwarding** / **Redirecionamento de Portas** / **NAT**
3. Criar regra:
   ```
   Nome:          Analise CertiDigital
   Protocolo:     TCP
   Porta externa: 8020
   IP interno:    [IP local do Windows Server, ex: 192.168.1.100]
   Porta interna: 8020
   ```
4. Salvar e reiniciar o roteador se necessário

### Descobrir o IP local do servidor:
```powershell
ipconfig | findstr "IPv4"
```

### Descobrir o IP externo:
```powershell
(Invoke-WebRequest -Uri "https://api.ipify.org").Content
```

---

## ▶️ PARTE 4 — Iniciar o Servidor

### 4.1 Modo de teste (manual, via PowerShell)

```powershell
cd C:\Apps\robot_cert
.venv\Scripts\Activate.ps1

# Opção A: Uvicorn direto (mais simples no Windows)
uvicorn app.main:app --host 0.0.0.0 --port 8020 --workers 2

# Opção B: Waitress (mais robusto para produção no Windows)
python -c "from waitress import serve; from app.main import app; serve(app, host='0.0.0.0', port=8020, threads=4)"
```

### 4.2 Script de inicialização conveniente

Criar arquivo `start_portal.bat` na raiz:
```batch
@echo off
cd /d C:\Apps\robot_cert
call .venv\Scripts\activate.bat
uvicorn app.main:app --host 0.0.0.0 --port 8020 --workers 2
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
# Arguments:       app.main:app --host 0.0.0.0 --port 8020 --workers 2
```

### 5.3 Ou instalar via linha de comando (sem GUI)

```powershell
nssm install AnaliseCertiDigital "C:\Apps\robot_cert\.venv\Scripts\uvicorn.exe"
nssm set AnaliseCertiDigital AppParameters "app.main:app --host 0.0.0.0 --port 8020"
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

## 🔒 PARTE 6 — HTTPS com Nginx (Opcional, mas Recomendado)

Se quiser acesso via `https://` com domínio próprio, instalar o **Nginx para Windows** como proxy reverso.

### 6.1 Instalar Nginx

```powershell
# Baixar nginx para Windows em: https://nginx.org/en/download.html
# Extrair para C:\Apps\nginx
```

### 6.2 Configurar nginx.conf

```nginx
# C:\Apps\nginx\conf\nginx.conf
server {
    listen 80;
    server_name seu-dominio.com.br;

    location / {
        proxy_pass         http://127.0.0.1:8020;
        proxy_http_version 1.1;
        proxy_set_header   Upgrade $http_upgrade;
        proxy_set_header   Connection keep-alive;
        proxy_set_header   Host $host;
        proxy_cache_bypass $http_upgrade;
        proxy_set_header   X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;
    }
}
```

---

## ✅ PARTE 7 — Checklist Final de Validação

```
[ ] Python instalado e no PATH
[ ] .venv criado e dependências instaladas
[ ] .env configurado com todas as chaves
[ ] Porta 8020 aberta no Firewall do Windows
[ ] Porta 8020 redirecionada no roteador (se rede local)
[ ] Servidor inicia sem erros (testar manualmente primeiro)
[ ] Acessar http://IP_EXTERNO:8020 de fora da rede ✓
[ ] Serviço NSSM configurado e iniciando automaticamente
[ ] Logs sendo gravados em C:\Apps\robot_cert\logs\
[ ] Atualizar CERT_ROBOT_BASE_URL no .env dos agentes locais
[ ] Testar que os agentes estão comunicando com o novo endereço
```

---

## 🔧 Troubleshooting Comum

| Problema | Causa Provável | Solução |
|---|---|---|
| `Connection refused` externamente | Porta não aberta no Firewall ou roteador | Rever Partes 2 e 3 |
| `gunicorn: command not found` / erro | Gunicorn não funciona no Windows | Usar `uvicorn` ou `waitress` |
| `ImportError` ao iniciar | `.venv` não ativado ou dependência faltando | Ativar .venv e `pip install -r requirements.txt` |
| Site cai após alguns minutos | Sessão PowerShell encerrou | Configurar serviço NSSM (Parte 5) |
| `Address already in use` | Outra instância rodando na porta 8020 | `Get-Process -Id (Get-NetTCPConnection -LocalPort 8020).OwningProcess` |
| Agente não consegue conectar | URL desatualizada no .env do agente | Atualizar `CERT_ROBOT_BASE_URL` |

---

*Gerado em 2026-08-01 | Analise CertiDigital — Windows Server Migration Guide*
