# Compila o instalador avulso (o .exe que o usuario baixa do portal).
#
#   .\scripts\build_instalador_avulso.ps1                        # aponta para producao
#   .\scripts\build_instalador_avulso.ps1 -PortalBase http://127.0.0.1:8020
#
# O endereco do portal e gravado em agent/_build_config.py e vai DENTRO do
# binario: o executavel roda na maquina do usuario, onde nao existe .env nosso.

param(
    [string] $PortalBase = "https://certificado.analisegroup.cnt.br",
    [string] $PythonExe = ".\.venv\Scripts\python.exe"
)

$ErrorActionPreference = "Stop"

$raiz = Split-Path -Parent $PSScriptRoot
Set-Location $raiz

$PortalBase = $PortalBase.TrimEnd("/")
Write-Host "Portal alvo: $PortalBase" -ForegroundColor Cyan

# Gerado pelo build; nao editar a mao (esta no .gitignore).
$conteudo = @"
# Gerado por scripts/build_instalador_avulso.ps1 - NAO EDITAR.
# Endereco do portal gravado no executavel em tempo de compilacao.
PORTAL_BASE = "$PortalBase"
"@
Set-Content -Path ".\agent\_build_config.py" -Value $conteudo -Encoding utf8

# O PyInstaller escreve o progresso (INFO) em stderr. No Windows PowerShell 5.1
# isso vira NativeCommandError e, com ErrorActionPreference=Stop, aborta um build
# que esta indo bem. Quem decide sucesso aqui e o codigo de saida.
$anterior = $ErrorActionPreference
$ErrorActionPreference = "Continue"
& $PythonExe -m PyInstaller --noconfirm --clean ".\Instalar_Certificado.spec"
$codigo = $LASTEXITCODE
$ErrorActionPreference = $anterior
if ($codigo -ne 0) { throw "PyInstaller falhou com codigo $codigo" }

$exe = ".\dist\Instalar_Certificado.exe"
if (-not (Test-Path $exe)) { throw "Executavel nao foi gerado em $exe" }

$tamanho = [math]::Round((Get-Item $exe).Length / 1MB, 1)
Write-Host "OK: $exe ($tamanho MB)" -ForegroundColor Green
Write-Host "O portal serve este arquivo em /instalador/baixar/{token}." -ForegroundColor Gray
