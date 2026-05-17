param(
    [string]$InstallerPath = ".\dist\installer\Instalador_AnaliseCertiDigital_Agente.exe",
    [string]$InstallDir = "${env:ProgramFiles}\Analise CertiDigital Agent",
    [string]$TaskName = "Analise CertiDigital Agent (Tray)",
    [string]$ServiceName = "AnaliseCertiDigitalAgent",
    [switch]$Cleanup
)

$ErrorActionPreference = "Stop"

function Write-Log {
    param(
        [ValidateSet("INFO", "WARN", "ERROR")]
        [string]$Level,
        [string]$Message
    )

    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss.fff"
    Write-Host ("[{0}] [{1}] {2}" -f $ts, $Level, $Message)
}

function Assert-IsAdmin {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw "Execute este script em PowerShell elevado (Administrador)."
    }
}

function Assert-PathExists {
    param(
        [string]$PathToCheck,
        [string]$ErrorMessage
    )

    if (-not (Test-Path $PathToCheck)) {
        throw $ErrorMessage
    }
}

function Get-TaskXml {
    param([string]$Name)

    $xmlRaw = & schtasks /Query /TN $Name /XML 2>$null
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($xmlRaw)) {
        throw "Nao foi possivel consultar a tarefa '$Name' via schtasks."
    }

    return [xml]($xmlRaw -join [Environment]::NewLine)
}

function Assert-TaskConfiguration {
    param(
        [xml]$TaskXml,
        [string]$ExpectedInstallDir
    )

    $cmd = $TaskXml.Task.Actions.Exec.Command
    $userId = $TaskXml.Task.Principals.Principal.UserId
    $runLevel = $TaskXml.Task.Principals.Principal.RunLevel
    $logonTrigger = $TaskXml.Task.Triggers.LogonTrigger

    if (-not $cmd) {
        throw "A tarefa nao possui comando configurado."
    }
    if (-not $cmd.ToLowerInvariant().Contains("analise_certidigital_agent.exe")) {
        throw "Comando inesperado na tarefa: $cmd"
    }
    if (-not $cmd.StartsWith($ExpectedInstallDir, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Comando da tarefa nao aponta para diretorio esperado. Esperado inicio: '$ExpectedInstallDir'. Atual: '$cmd'"
    }
    if (-not $userId) {
        throw "RunAs inesperado: tarefa sem UserId."
    }
    if ($runLevel -ne "HighestAvailable") {
        throw "RunLevel inesperado. Esperado 'HighestAvailable', atual '$runLevel'."
    }
    if (-not $logonTrigger) {
        throw "Trigger de logon (LogonTrigger) nao encontrada."
    }
}

function Assert-ServiceConfiguration {
    param([string]$Name)

    $qc = (& sc.exe qc $Name 2>$null) -join [Environment]::NewLine
    if ($LASTEXITCODE -ne 0) {
        throw "Servico '$Name' nao encontrado."
    }
    if ($qc -notmatch "START_TYPE\s+:\s+2\s+AUTO_START") {
        throw "Servico '$Name' nao esta configurado como AUTO_START."
    }

    $query = (& sc.exe query $Name 2>$null) -join [Environment]::NewLine
    if ($LASTEXITCODE -ne 0) {
        throw "Nao foi possivel consultar status do servico '$Name'."
    }
    if ($query -notmatch "STATE\s+:\s+4\s+RUNNING") {
        throw "Servico '$Name' nao esta em execucao."
    }
}

function Stop-AgentIfRunning {
    $null = & taskkill /F /IM "AnaliseCertiDigital_Agent.exe" 2>$null
}

function Remove-TaskIfExists {
    param([string]$Name)
    $null = & schtasks /Delete /TN $Name /F 2>$null
}

function Remove-ServiceIfExists {
    param([string]$Name)
    $null = & sc.exe stop $Name 2>$null
    Start-Sleep -Seconds 1
    $null = & sc.exe delete $Name 2>$null
}

function Run-UninstallIfExists {
    param([string]$Dir)

    $uninstaller = Join-Path $Dir "unins000.exe"
    if (Test-Path $uninstaller) {
        Write-Log -Level "INFO" -Message ("Executando desinstalador: {0}" -f $uninstaller)
        & $uninstaller /VERYSILENT /SUPPRESSMSGBOXES /NORESTART
        if ($LASTEXITCODE -ne 0) {
            throw "Desinstalador retornou codigo $LASTEXITCODE."
        }
    }
}

Assert-IsAdmin

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $repoRoot

$resolvedInstaller = (Resolve-Path $InstallerPath).Path
Assert-PathExists -PathToCheck $resolvedInstaller -ErrorMessage "Instalador nao encontrado: $InstallerPath"

$expectedExePath = Join-Path $InstallDir "AnaliseCertiDigital_Agent.exe"
$installLog = Join-Path $repoRoot "dist\logs\smoke_install.log"

Write-Log -Level "INFO" -Message ("Iniciando smoke test com instalador: {0}" -f $resolvedInstaller)
Write-Log -Level "INFO" -Message ("Diretorio de instalacao esperado: {0}" -f $InstallDir)

Stop-AgentIfRunning
Run-UninstallIfExists -Dir $InstallDir
Remove-TaskIfExists -Name $TaskName
Remove-ServiceIfExists -Name $ServiceName

Write-Log -Level "INFO" -Message "Executando instalacao silenciosa para smoke test"
& $resolvedInstaller /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /TASKS=autostart /LOG="$installLog"
if ($LASTEXITCODE -ne 0) {
    throw "Instalador retornou codigo $LASTEXITCODE. Verifique: $installLog"
}

Assert-PathExists -PathToCheck $expectedExePath -ErrorMessage "Executavel nao encontrado apos instalacao: $expectedExePath"
Write-Log -Level "INFO" -Message ("Executavel validado: {0}" -f $expectedExePath)

$expectedServiceExePath = Join-Path $InstallDir "AnaliseCertiDigital_Agent_Service.exe"
Assert-PathExists -PathToCheck $expectedServiceExePath -ErrorMessage "Executavel do servico nao encontrado apos instalacao: $expectedServiceExePath"
Write-Log -Level "INFO" -Message ("Executavel de servico validado: {0}" -f $expectedServiceExePath)

$taskXml = Get-TaskXml -Name $TaskName
Assert-TaskConfiguration -TaskXml $taskXml -ExpectedInstallDir $InstallDir
Write-Log -Level "INFO" -Message ("Tarefa '{0}' validada com sucesso (LogonTrigger + HighestAvailable)." -f $TaskName)

Assert-ServiceConfiguration -Name $ServiceName
Write-Log -Level "INFO" -Message ("Servico '{0}' validado com sucesso (AUTO_START + RUNNING)." -f $ServiceName)

Write-Log -Level "INFO" -Message "Iniciando processo do agente para validar startup manual"
Start-Process -FilePath $expectedExePath | Out-Null
Start-Sleep -Seconds 3
$agentProcess = Get-Process -Name "AnaliseCertiDigital_Agent" -ErrorAction SilentlyContinue
if (-not $agentProcess) {
    throw "Processo AnaliseCertiDigital_Agent nao subiu apos Start-Process."
}
Write-Log -Level "INFO" -Message ("Processo ativo validado. PID: {0}" -f $agentProcess[0].Id)

Stop-AgentIfRunning

if ($Cleanup) {
    Write-Log -Level "INFO" -Message "Cleanup habilitado: removendo instalacao, tarefa e servico."
    Run-UninstallIfExists -Dir $InstallDir
    Remove-TaskIfExists -Name $TaskName
    Remove-ServiceIfExists -Name $ServiceName
}

Write-Log -Level "INFO" -Message "SMOKE TEST FINALIZADO COM SUCESSO"
