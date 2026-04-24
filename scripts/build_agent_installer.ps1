param(
    [string]$PythonExe = "python",
    # Usar chaves: $env:ProgramFiles(x86) quebra; ${env:ProgramFiles(x86)} e o path correto
    [string]$InnoCompiler = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $repoRoot

Write-Host "==> Projeto: $repoRoot"

Write-Host "==> Instalando dependencias de build"
& $PythonExe -m pip install --upgrade pip
& $PythonExe -m pip install -r .\requirements.txt
& $PythonExe -m pip install --upgrade pyinstaller

Write-Host "==> Gerando executavel do agente"
& $PythonExe -m PyInstaller --noconfirm .\CertGuard_Agent.spec

$exePath = Join-Path $repoRoot "dist\CertGuard_Agent.exe"
if (-not (Test-Path $exePath)) {
    throw "Executavel nao encontrado em: $exePath"
}

if (-not (Test-Path $InnoCompiler)) {
    throw "ISCC.exe nao encontrado. Instale Inno Setup 6 ou informe -InnoCompiler com o caminho correto."
}

Write-Host "==> Gerando instalador Inno Setup"
& $InnoCompiler .\agent_setup.iss

$installerDir = Join-Path $repoRoot "dist\installer"
Write-Host ""
Write-Host "Build finalizado com sucesso."
Write-Host "Executavel: $exePath"
Write-Host "Instalador: $installerDir"
