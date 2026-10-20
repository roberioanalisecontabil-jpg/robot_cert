# Gera o instalador do Certguard Analise (estacao/, ADR 0003).
# Uso, na raiz do repositorio:
#   powershell -ExecutionPolicy Bypass -File .\scripts\build_estacao.ps1
# Saida: dist_estacao\Instalador_CertguardAnalise_<versao>.exe, copiado para a Area de Trabalho.
# Arquivo so ASCII: o PowerShell 5.1 le UTF-8 sem BOM como ANSI.
param(
    [string]$PythonExe = ".\.venv\Scripts\python.exe",
    [string]$InnoCompiler = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
)

$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

function Rodar([string]$Exe, [string[]]$Argumentos) {
    & $Exe @Argumentos
    if ($LASTEXITCODE -ne 0) { throw "$Exe terminou com codigo $LASTEXITCODE" }
}

Write-Host "1/4 Testes do estacao/"
Rodar $PythonExe @("-m", "pytest", "tests/test_estacao.py", "tests/test_estacao_manifesto.py", "tests/test_estacao_atualizador.py", "tests/test_estacao_atualizacao_automatica.py", "-q")

Write-Host "2/4 PyInstaller"
Rodar $PythonExe @("-m", "PyInstaller", "--noconfirm", "--clean", "--distpath", "dist_estacao", "--workpath", "build_estacao", "CertguardAnalise.spec")
$exe = "dist_estacao\certguard_analise.exe"
if ((Get-Item $exe).Length -lt 5MB) { throw "$exe pequeno demais; o build saiu incompleto." }

Write-Host "3/4 Inno Setup"
if (-not (Test-Path $InnoCompiler)) { throw "ISCC nao encontrado em $InnoCompiler" }
Rodar $InnoCompiler @("estacao_setup.iss")

$versao = (& $PythonExe -c "import estacao; print(estacao.VERSAO)").Trim()
$instalador = "dist_estacao\Instalador_CertguardAnalise_$versao.exe"
if (-not (Test-Path $instalador)) { throw "Instalador nao gerado: $instalador" }

Write-Host "4/4 Copia para a Area de Trabalho"
$desktop = [Environment]::GetFolderPath("Desktop")
Copy-Item $instalador $desktop -Force
$hash = (Get-FileHash $instalador -Algorithm SHA256).Hash
Write-Host "Pronto: $desktop\$(Split-Path -Leaf $instalador)"
Write-Host "SHA-256: $hash"
