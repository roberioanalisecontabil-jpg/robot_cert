# Publica uma versao do Certguard Analise para a atualizacao automatica.
#
#   .\publicar-certguard.ps1 -Origem C:\Users\<voce>\Desktop\certificados
#
# A Origem e a pasta que scripts\versoes_certguard.py publicar montou na
# maquina de build (instalador + vigente.json, ja assinado). Aqui so se copia:
# primeiro o instalador, depois o vigente.json por troca atomica, para nenhuma
# estacao ler um vigente.json que aponta para um instalador que ainda nao chegou.
# Quem confere a assinatura e a estacao; este script nao tem chave nenhuma.
# Arquivo so com ASCII de proposito (PowerShell 5.1 le UTF-8 sem BOM como ANSI).
param(
    [Parameter(Mandatory = $true)][string]$Origem,
    [string]$Destino = "C:\Apps\robot_cert\atualizacoes\certificados"
)

$ErrorActionPreference = "Stop"

$vigente = Join-Path $Origem "vigente.json"
if (-not (Test-Path $vigente)) { throw "vigente.json nao encontrado em $Origem" }
$pacote = Get-Content $vigente -Raw -Encoding UTF8 | ConvertFrom-Json
$m = $pacote.manifesto
if ($m.produto -ne "certificados") { throw "Pacote de outro produto: $($m.produto)" }
$instalador = Join-Path $Origem $m.arquivo
if (-not (Test-Path $instalador)) { throw "Instalador $($m.arquivo) nao esta em $Origem" }
$hash = (Get-FileHash $instalador -Algorithm SHA256).Hash.ToLower()
if ($hash -ne $m.sha256) { throw "SHA-256 do instalador nao confere com o vigente.json" }

New-Item -ItemType Directory -Force -Path $Destino | Out-Null
Copy-Item $instalador (Join-Path $Destino $m.arquivo) -Force
$temporario = Join-Path $Destino "vigente.json.tmp"
Copy-Item $vigente $temporario -Force
Move-Item $temporario (Join-Path $Destino "vigente.json") -Force

Write-Host "Publicada a versao $($m.versao) do Certguard Analise em $Destino." -ForegroundColor Green
Write-Host "As estacoes atualizam na proxima conferencia (partida do Windows ou a cada 6 h)."
