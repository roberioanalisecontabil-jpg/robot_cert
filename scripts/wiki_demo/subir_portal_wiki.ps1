# Sobe o portal de certificados em modo DEMONSTRACAO (banco certguard_wiki,
# dados ficticios) em http://127.0.0.1:8091 (8090 e do Wondershare).
#
# Uso:
#   .\subir_portal_wiki.ps1            # porta 8091; Ctrl+C para parar
#   .\subir_portal_wiki.ps1 -Port 8091
#
# Antes, uma vez: & .venv\Scripts\python.exe scripts\wiki_demo\seed_wiki.py
# As variaveis (DATABASE_URL, API_KEY, JWT_SECRET_KEY, chaves do cofre,
# ENCRYPTION_KEY, LOGIN_EXIGE_CODIGO=0) vem de ambiente-wiki.env, gerado pelo
# seed com valores aleatorios so para este ambiente. Credenciais em
# credenciais-demo.txt.
param(
    [int] $Port = 8091
)
$ErrorActionPreference = "Stop"
$aqui = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $aqui "..\..\.venv\Scripts\python.exe"

if (-not (Test-Path (Join-Path $aqui "ambiente-wiki.env"))) {
    Write-Host "ambiente-wiki.env nao encontrado. Rode antes: & `"$python`" `"$aqui\seed_wiki.py`"" -ForegroundColor Red
    exit 1
}

Write-Host "Portal DEMO em http://127.0.0.1:$Port/login  (banco certguard_wiki)" -ForegroundColor Cyan
Write-Host "Credenciais: $aqui\credenciais-demo.txt" -ForegroundColor DarkGray
Write-Host "Ctrl+C para parar." -ForegroundColor DarkGray

# O uvicorn loga em stderr; com ErrorActionPreference=Stop o PowerShell 5.1
# trataria a primeira linha de log como erro fatal e derrubaria o servidor.
$ErrorActionPreference = "Continue"
& $python (Join-Path $aqui "servir_wiki.py") $Port
exit $LASTEXITCODE
