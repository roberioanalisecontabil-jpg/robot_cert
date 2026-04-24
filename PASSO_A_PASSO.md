# Passo a passo — Cert robot (PFX)

## 1. Pré-requisitos

- Python 3.11+ (recomendado)
- Windows (para o agente com pastas locais) ou outro SO para só o servidor API

## 2. Instalar dependências

Na pasta do projeto (`robot_cert`):

```powershell
cd C:\Users\SEU_USUARIO\projetos_PY\robot_cert
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

## 3. Variáveis de ambiente ( `.env` na raiz )

Copie `.env.example` para `.env` e ajuste:

| Variável | Uso |
|----------|-----|
| `API_KEY` | Opcional. Se definir, o painel e o agente devem enviar a mesma chave em `X-API-Key`. |
| `CERT_SOURCE_DIR` / `CERT_EXPIRED_DIR` | Pastas padrão no **servidor** se não preencher no portal. |
| `SUPABASE_URL` / `SUPABASE_SERVICE_KEY` | Opcional: config e snapshots na cloud. Execute `supabase/schema.sql` no projeto Supabase. |
| **Agente** (no mesmo `.env` ou `agent/.env`): `CERT_ROBOT_BASE_URL`, `CERT_ROBOT_API_KEY` (igual a `API_KEY` se existir), `AGENT_SOURCE`, `AGENT_EXPIRED` |

## 4. Subir o servidor API

A porta **8020** é a padrão **deste** projeto (o agente assume `http://127.0.0.1:8020` se não definir `CERT_ROBOT_BASE_URL`), para não colidir com outro serviço na **8000**.

```powershell
.\.venv\Scripts\Activate.ps1
python -m uvicorn app.main:app --host 127.0.0.1 --port 8020 --reload
```

Alternativa: `.\scripts\servir.ps1` (mesma porta por defeito).

Abra no browser:

- **Painel:** http://127.0.0.1:8020/
- **Configuração:** http://127.0.0.1:8020/configuracao

Se tiver `API_KEY` no `.env`, na página **Configuração** cole a mesma chave e use **Guardar chave**.

## 5. Configurar pastas (máquina onde estão os `.pfx`)

Na página **Configuração**, indique:

- Pasta de origem (ficheiros `.pfx`)
- Pasta de destino dos vencidos
- ID da máquina (ex.: `default`) — deve ser o mesmo no agente

Formato do nome do ficheiro:

`Nome legível senha palavra_passe_do_pfx.pfx`

### Exportar configuração pronta para o agente

Na página **Configuração**, use o botão **Baixar agent_config.json**.
Depois copie este arquivo para a pasta onde o `CertGuard_Agent.exe` foi instalado.
O agente passa a usar esse arquivo automaticamente.

## 6. Ver dados no painel

No **Painel**, escolha a **fonte** (automático / local / remoto) e **Atualizar tabela**.

- **Local:** o processo do `uvicorn` lê o disco nas pastas efetivas.
- **Remoto:** precisa do agente a enviar dados (`POST /api/ingest`).

## 7. Agente Windows (opcional, para pastas noutro PC ou leitura remota)

Com o API a correr e acessível (`CERT_ROBOT_BASE_URL`):

```powershell
cd C:\...\robot_cert
.\.venv\Scripts\Activate.ps1
python agent\run_agent.py
```

Para um só ciclo: `python agent\run_agent.py --once`

Comandos remotos (fila) estão na **Configuração**; o agente interroga `/api/agent/next` se `POLL_COMMANDS` não for `0`.

### Gerar executável + instalador (Inno Setup)

Com o Inno Setup 6 instalado, rode:

```powershell
cd C:\...\robot_cert
.\scripts\build_agent_installer.ps1
```

Saídas:

- `dist\CertGuard_Agent.exe` (binário do agente)
- `dist\installer\Instalador_CertGuard_Agente.exe` (instalador)

## 8. Validar com testes automáticos

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m pytest tests -v
```

Todos os testes devem passar (ver `tests/test_api_routes.py` e `tests/test_cert_scanner.py`).

## 9. Problemas frequentes

| Sintoma | O que verificar |
|---------|-----------------|
| 401 nas APIs | Chave no browser = `API_KEY` do `.env`; reiniciar `uvicorn` após mudar `.env`. |
| Tabela vazia | Pastas certas, ficheiros `.pfx` com nome no padrão, fonte “local” ou agente a correr. |
| “Remoto” sem dados | Executar o agente ou mudar fonte para local/automático. |
| Porta errada | Ajustar `CERT_ROBOT_BASE_URL` e a URL no browser. |
