# Assina e (opcionalmente) publica uma versao da bandeja Certguard Analise,
# NESTA maquina, com a senha da chave pedida UMA vez. No PowerShell:
#
#   cd C:\Users\Roberio\projetos_PY\robot_cert
#   .\deploy\lancar-certguard.ps1 -Publicar
#
# Sem -Instalador: usa dist_estacao\Instalador_CertguardAnalise_<VERSAO>.exe,
# com a VERSAO de estacao\__init__.py. Com -Gerar: roda antes o
# scripts\build_estacao.ps1 (testes, PyInstaller, Inno Setup).
#
# Assina com a chave do CERTGUARD (%USERPROFILE%\.certguard-chaves), nunca a do
# Hardlyze: as estacoes so aceitam as chaves de estacao\manifesto.py. Quem pede a
# senha e scripts\versoes_certguard.py; ela nunca passa por este script.
#
# Com -Publicar: copia o pacote para o servidor pelo compartilhamento c$
# (o Copy-Item -ToSession do WinRM falha com instaladores deste tamanho),
# primeiro o instalador, depois o vigente.json por troca, para nenhuma estacao
# ler um vigente.json que aponta para um instalador que ainda nao chegou.
# Sem -Publicar, o pacote fica em dist_estacao\publicar\certificados.
#
# Com -PodeVoltar: o manifesto permite a uma versao MENOR substituir a instalada.
#
# Arquivo so com ASCII de proposito: o PowerShell 5.1 le .ps1 sem BOM como ANSI.

param(
    [string]$Instalador = "",
    [switch]$Gerar,
    [switch]$Publicar,
    [switch]$PodeVoltar,
    [string]$Servidor = "\\10.200.0.4\c$\Apps\robot_cert\atualizacoes\certificados",
    [string]$Credencial = (Join-Path $env:USERPROFILE ".servidor-invent.xml")
)

$ErrorActionPreference = "Stop"
$raiz = Split-Path -Parent $PSScriptRoot
$python = Join-Path $raiz ".venv\Scripts\python.exe"
if ($Instalador) { $Instalador = (Resolve-Path $Instalador).Path }
Push-Location $raiz
try {

function Rodar([string]$Exe, [string[]]$Argumentos, [string]$Passo) {
    $anterior = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try { & $Exe @Argumentos } finally { $ErrorActionPreference = $anterior }
    if ($LASTEXITCODE -ne 0) { throw "$Passo falhou (codigo $LASTEXITCODE)." }
}

if ($Gerar) {
    Rodar "powershell" @("-ExecutionPolicy", "Bypass", "-File", (Join-Path $raiz "scripts\build_estacao.ps1")) "Build"
}

if (-not $Instalador) {
    $versao = & $python -c "import estacao; print(estacao.VERSAO)"
    if ($LASTEXITCODE -ne 0 -or -not $versao) { throw "Nao consegui ler estacao.VERSAO." }
    $versao = ([string]($versao | Select-Object -Last 1)).Trim()
    $Instalador = Join-Path $raiz "dist_estacao\Instalador_CertguardAnalise_$versao.exe"
}
if (-not (Test-Path $Instalador)) { throw "Instalador nao encontrado: $Instalador (use -Gerar)" }

Write-Host "Assinando $Instalador (a senha e da chave do Certguard)"
$argsAssinar = @("scripts\versoes_certguard.py", "publicar", "--instalador", $Instalador)
if ($PodeVoltar) { $argsAssinar += "--pode-voltar" }
Rodar $python $argsAssinar "Assinatura"

$pacote = Join-Path $raiz "dist_estacao\publicar\certificados"
$vigente = Join-Path $pacote "vigente.json"
$m = (Get-Content $vigente -Raw -Encoding UTF8 | ConvertFrom-Json).manifesto
if ($m.produto -ne "certificados") { throw "Pacote de outro produto: $($m.produto)" }
$arquivo = Join-Path $pacote $m.arquivo
if ((Get-FileHash $arquivo -Algorithm SHA256).Hash.ToLower() -ne $m.sha256) { throw "SHA-256 do instalador nao confere com o vigente.json" }

if (-not $Publicar) {
    Write-Host "Pacote $($m.versao) pronto em $pacote. Para publicar: repita com -Publicar." -ForegroundColor Green
    return
}

# O PSDrive so abre a sessao SMB com a credencial; os caminhos vao por UNC
# completo (caminho relativo ao PSDrive saiu duplicado num teste em 15/11).
$cred = Import-Clixml $Credencial
New-PSDrive -Name CGPUB -PSProvider FileSystem -Root ($Servidor -replace '^(\\\\[^\\]+\\[^\\]+).*$', '$1') -Credential $cred | Out-Null
try {
    New-Item -ItemType Directory -Force -Path $Servidor | Out-Null
    $remoto = Join-Path $Servidor $m.arquivo
    if (Test-Path -LiteralPath $remoto) {
        # Mesmo nome com outro conteudo: o vigente.json atual pode apontar para ele.
        if ((Get-FileHash -LiteralPath $remoto -Algorithm SHA256).Hash.ToLower() -ne $m.sha256) {
            throw "$($m.arquivo) ja existe no servidor com outro conteudo; gere uma versao nova."
        }
    } else {
        Copy-Item -LiteralPath $arquivo -Destination $remoto
        if ((Get-FileHash -LiteralPath $remoto -Algorithm SHA256).Hash.ToLower() -ne $m.sha256) {
            Remove-Item -LiteralPath $remoto -Force  # nao deixa copia pela metade travando a proxima
            throw "O instalador chegou diferente no servidor; vigente.json NAO foi trocado."
        }
    }
    $tmp = Join-Path $Servidor "vigente.json.tmp"
    Copy-Item -LiteralPath $vigente -Destination $tmp -Force
    Move-Item -LiteralPath $tmp -Destination (Join-Path $Servidor "vigente.json") -Force
} finally {
    Remove-PSDrive CGPUB
}
Write-Host "Publicada a versao $($m.versao) do Certguard Analise em $Servidor." -ForegroundColor Green
Write-Host "As estacoes atualizam na proxima conferencia (partida do Windows ou a cada 6 h)."
} finally {
    Pop-Location
}
