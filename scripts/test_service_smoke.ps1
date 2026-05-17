param(
    [string]$PythonExe = "python",
    [string]$DistPath = ".\dist_smoke",
    [string]$WorkPath = ".\build_smoke",
    [switch]$SkipBuild,
    [switch]$Cleanup
)

$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $false
$serviceName = "AnaliseCertiDigitalSmokeSvc"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $repoRoot

function Write-Log {
    param([string]$Message)
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss.fff"
    Write-Host "[$ts] $Message"
}

function Invoke-CmdChecked {
    param(
        [string]$FilePath,
        [string[]]$Arguments
    )
    Write-Log ("EXEC: {0} {1}" -f $FilePath, ($Arguments -join " "))
    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Falha ao executar comando: $FilePath $($Arguments -join ' ') (exit=$LASTEXITCODE)"
    }
}

function Test-ServiceExists {
    param([string]$Name)
    $null = & sc.exe query $Name 2>$null
    return ($LASTEXITCODE -eq 0)
}

function Remove-SmokeServiceIfExists {
    Write-Log "Limpando serviço smoke (se existir)"
    $null = & sc.exe stop $serviceName 2>$null
    Start-Sleep -Seconds 1
    $null = & sc.exe delete $serviceName 2>$null
    $null = & cmd.exe /c "taskkill /F /IM AnaliseCertiDigital_Smoke_Service.exe >nul 2>&1"
    Start-Sleep -Seconds 1
}

Remove-SmokeServiceIfExists

if (-not $SkipBuild) {
    Write-Log "Buildando smoke service (PyInstaller)"
    if (Test-Path $DistPath) {
        Write-Log ("Removendo dist anterior: {0}" -f $DistPath)
        Remove-Item -Recurse -Force $DistPath
    }
    if (Test-Path $WorkPath) {
        Write-Log ("Removendo work anterior: {0}" -f $WorkPath)
        Remove-Item -Recurse -Force $WorkPath
    }
    Invoke-CmdChecked -FilePath $PythonExe -Arguments @(
        "-m", "PyInstaller",
        "--noconfirm",
        "--distpath", $DistPath,
        "--workpath", $WorkPath,
        ".\Smoke_Service.spec"
    )
}

$serviceExe = Join-Path $repoRoot (Join-Path $DistPath "AnaliseCertiDigital_Smoke_Service\AnaliseCertiDigital_Smoke_Service.exe")
if (-not (Test-Path $serviceExe)) {
    throw "Executável smoke não encontrado: $serviceExe"
}

Write-Log "Registrando serviço smoke"
Invoke-CmdChecked -FilePath $serviceExe -Arguments @("--startup", "auto", "install")
if (-not (Test-ServiceExists -Name $serviceName)) {
    throw "Servico '$serviceName' nao foi registrado. Execute este script em PowerShell Administrador."
}

Write-Log "Iniciando serviço smoke"
Invoke-CmdChecked -FilePath "sc.exe" -Arguments @("start", $serviceName)

Start-Sleep -Seconds 3

Write-Log "Status do serviço smoke"
& sc.exe query $serviceName

$logPath = Join-Path $env:ProgramData "Analise CertiDigital Service Smoke\smoke_service.log"
if (Test-Path $logPath) {
    Write-Log ("Log encontrado: {0}" -f $logPath)
} else {
    Write-Log "Log em ProgramData não encontrado (pode estar no TEMP, conforme fallback)."
}

if ($Cleanup) {
    Remove-SmokeServiceIfExists
    Write-Log "Cleanup concluído."
}

Write-Log "Smoke test finalizado."
