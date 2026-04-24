# Inicia o API FastAPI (uvicorn) a partir da raiz do repositório robot_cert.
# Uso:
#   .\scripts\servir.ps1              # porta 8020 (padrão — evita conflito com 8000)
#   .\scripts\servir.ps1 -Port 9000
param(
    [int] $Port = 8020,
    [string] $Host = "127.0.0.1"
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

Write-Host "A servir em http://${Host}:$Port/  | configuracao: http://${Host}:$Port/configuracao" -ForegroundColor Cyan
Write-Host "Ctrl+C para parar." -ForegroundColor DarkGray
python -m uvicorn app.main:app --host $Host --port $Port --reload
