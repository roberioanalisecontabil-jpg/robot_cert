# CertGuard — Monitor de Certificados Digitais

O **CertGuard** (anteriormente Robot Cert) é um sistema completo de gestão e monitoramento de certificados digitais (arquivos `.pfx` e `.p12`). Ele foi projetado para resolver o problema de certificados expirados em servidores Windows, oferecendo uma visão centralizada em um painel web moderno.

## 🚀 Arquitetura do Sistema

O projeto é dividido em dois componentes principais que se comunicam via API HTTP REST:

1. **Portal Web (FastAPI):** O painel de controle central. Exibe o dashboard com os status dos certificados (Válidos, Expirando, Vencidos) e permite disparar comandos remotos. Pode ser hospedado na nuvem (ex: Render) ou localmente.
2. **Agente Windows (Scanner Local):** Um script Python projetado para rodar em *background* nos servidores Windows onde os certificados físicos estão armazenados. O agente utiliza a biblioteca `watchdog` para monitorar a pasta em **tempo real** e envia (via POST) as informações para o Portal sempre que um arquivo é adicionado, alterado ou excluído.

## ✨ Principais Funcionalidades

- **Dashboard Moderno:** Interface de usuário minimalista e responsiva (Tema Claro com Sidebar Escura), exibindo rapidamente certificados problemáticos.
- **Detecção de Vencimento:** Alerta visual na tabela para certificados que vão expirar nos **próximos 30 dias**.
- **Agente Event-Driven:** O agente não precisa ser configurado via `.env` para pastas. Ele puxa as pastas a serem monitoradas dinamicamente do Portal. Mudanças nos arquivos engatilham verificações instantâneas.
- **Fila de Comandos Remotos:** Através do portal, é possível mandar o agente de um servidor Windows específico *forçar uma releitura* (Rescan) ou *mover certificados vencidos* para uma pasta de quarentena.
- **Integração com Supabase (Opcional):** Permite sincronizar os dados e o estado de múltiplos agentes na nuvem (PostgreSQL) garantindo persistência global.

## 🛠️ Stack Tecnológica

- **Backend:** Python 3.11+, FastAPI, Uvicorn, Httpx.
- **Frontend:** HTML5, Vanilla CSS, JavaScript Puro (Sem frameworks pesados para máxima performance).
- **Agente Local:** Python, Watchdog (para monitoramento de File System via SO).
- **Banco de Dados/Cloud:** Supabase (PostgreSQL & REST API).
- **Segurança:** Sistema de `X-API-Key` implementado nas rotas para evitar injeções não autorizadas no portal.

## 📦 Como rodar localmente

### 1. Clonar e Instalar Dependências
```bash
git clone https://github.com/RoberioMelo/robot_cert.git
cd robot_cert
python -m venv .venv
# Ativar o ambiente virtual (Windows PowerShell)
.venv\Scripts\activate
# Instalar as bibliotecas
pip install -r requirements.txt
```

### 2. Configurar o `.env` (Opcional)
Crie um arquivo `.env` na raiz do projeto com as chaves desejadas. Exemplo:
```env
API_KEY=minha_senha_super_secreta
CERT_ROBOT_BASE_URL=http://127.0.0.1:8020
CERT_ROBOT_API_KEY=minha_senha_super_secreta
```

### 3. Iniciar o Portal Web (FastAPI)
```bash
python -m uvicorn app.main:app --host 127.0.0.1 --port 8020
```
> Acesse: [http://127.0.0.1:8020](http://127.0.0.1:8020)

### 4. Iniciar o Agente Windows (Em outro terminal)
Primeiro, acesse a página de **Configuração** no Portal e defina a pasta de "Origem" e "Destino" (Ex: `C:\Certs`). Só então inicie o agente:
```bash
python agent/run_agent.py
```
O agente ficará rodando e escutando mudanças na pasta definida!

---

**Desenvolvido por Roberio França | AnaliseGroupTI**