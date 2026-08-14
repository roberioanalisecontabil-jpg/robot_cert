param(
    [string]$PythonExe = "python",
    [string]$InnoCompiler = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    [string]$RequirementsFile = ".\requirements.txt",
    [string]$PyInstallerVersion = "6.11.1",
    [switch]$UpgradePip,
    [switch]$CI,
    [switch]$SkipDependencyInstall
)

$ErrorActionPreference = "Stop"
$MinimumExeSizeBytes = 5MB
$MinimumServiceExeSizeBytes = 5MB
$MinimumInstallerSizeBytes = 5MB
$Script:LogFile = $null
$Script:CIOutput = $false

function Write-Log {
    param(
        [ValidateSet("INFO", "WARN", "ERROR")]
        [string]$Level,
        [string]$Message
    )

    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss.fff"
    $line = "[{0}] [{1}] {2}" -f $timestamp, $Level, $Message
    Write-Host $line
    if ($Script:LogFile) {
        Add-Content -Path $Script:LogFile -Value $line -Encoding UTF8
    }
}

function Write-CIEvent {
    param(
        [string]$Type,
        [hashtable]$Fields
    )

    if (-not $Script:CIOutput) {
        return
    }

    $parts = @()
    foreach ($key in ($Fields.Keys | Sort-Object)) {
        $value = [string]$Fields[$key]
        $value = $value.Replace("\", "\\").Replace("`r", " ").Replace("`n", " ").Replace(" ", "_")
        $parts += ("{0}={1}" -f $key, $value)
    }

    Write-Host ("CI_{0} {1}" -f $Type.ToUpperInvariant(), ($parts -join " "))
}

function Invoke-BuildStep {
    param(
        [string]$StepName,
        [scriptblock]$Action
    )

    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    Write-Log -Level "INFO" -Message ("INICIO etapa='{0}'" -f $StepName)
    Write-CIEvent -Type "STEP_START" -Fields @{ name = $StepName }
    try {
        & $Action
        $sw.Stop()
        Write-Log -Level "INFO" -Message ("FIM etapa='{0}' duracao_ms={1}" -f $StepName, $sw.ElapsedMilliseconds)
        Write-CIEvent -Type "STEP_END" -Fields @{ name = $StepName; status = "success"; duration_ms = $sw.ElapsedMilliseconds }
    }
    catch {
        $sw.Stop()
        Write-Log -Level "ERROR" -Message ("FALHA etapa='{0}' duracao_ms={1} erro='{2}'" -f $StepName, $sw.ElapsedMilliseconds, $_.Exception.Message)
        Write-CIEvent -Type "STEP_END" -Fields @{ name = $StepName; status = "failed"; duration_ms = $sw.ElapsedMilliseconds; error = $_.Exception.Message }
        throw
    }
}

function Invoke-ExternalCommand {
    param(
        [string]$StepName,
        [string]$FilePath,
        [string[]]$Arguments
    )

    $joinedArgs = $Arguments -join " "
    Write-Log -Level "INFO" -Message ("exec etapa='{0}' cmd='{1}' args='{2}'" -f $StepName, $FilePath, $joinedArgs)

    # O PyInstaller escreve o progresso (INFO) em stderr. No Windows PowerShell
    # 5.1 cada linha de stderr de um executavel nativo vira um ErrorRecord
    # (NativeCommandError) e, com ErrorActionPreference=Stop no topo do script,
    # aborta o build na PRIMEIRA linha de log — antes mesmo de chegar ao teste
    # de $LASTEXITCODE abaixo. O sintoma e enganoso: a mensagem de erro e o
    # banner de versao do PyInstaller, como se ele tivesse falhado ao iniciar.
    # Quem decide sucesso aqui e o codigo de saida, entao a preferencia e
    # relaxada so durante a chamada.
    $anterior = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & $FilePath @Arguments
        $codigo = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $anterior
    }

    if ($codigo -ne 0) {
        throw "Comando falhou na etapa '$StepName' com codigo de saida $codigo. Comando: $FilePath $joinedArgs"
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

function Assert-MinFileSize {
    param(
        [string]$PathToCheck,
        [long]$MinSizeBytes,
        [string]$Label
    )

    $file = Get-Item $PathToCheck
    if ($file.Length -lt $MinSizeBytes) {
        throw "$Label invalido: tamanho ${($file.Length)} bytes (minimo esperado: $MinSizeBytes bytes). Arquivo: $PathToCheck"
    }
}

function Show-ArtifactMetadata {
    param(
        [string]$PathToShow,
        [string]$Label
    )

    $item = Get-Item $PathToShow
    $hash = Get-FileHash -Algorithm SHA256 -Path $PathToShow
    $version = [System.Diagnostics.FileVersionInfo]::GetVersionInfo($PathToShow).FileVersion
    $resolvedVersion = if ([string]::IsNullOrWhiteSpace($version)) { "<sem FileVersion>" } else { $version }

    Write-Log -Level "INFO" -Message ("artefato='{0}' caminho='{1}' tamanho_bytes={2} sha256='{3}' versao='{4}'" -f $Label, $item.FullName, $item.Length, $hash.Hash, $resolvedVersion)
    Write-CIEvent -Type "ARTIFACT" -Fields @{
        label = $Label
        path = $item.FullName
        size_bytes = $item.Length
        sha256 = $hash.Hash
        version = $resolvedVersion
    }
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $repoRoot

$logDir = Join-Path $repoRoot "dist\logs"
if (-not (Test-Path $logDir)) {
    New-Item -Path $logDir -ItemType Directory | Out-Null
}
$Script:LogFile = Join-Path $logDir ("build_agent_installer_{0}.log" -f (Get-Date -Format "yyyyMMdd_HHmmss"))
$buildSw = [System.Diagnostics.Stopwatch]::StartNew()

try {
    if ($CI) {
        $Script:CIOutput = $true
        $env:PIP_DISABLE_PIP_VERSION_CHECK = "1"
        $env:PYTHONHASHSEED = "0"
        $UpgradePip = $false
        Write-Log -Level "INFO" -Message "modo_ci=true configuracoes_aplicadas='pip_version_check_off, pythonhashseed=0, upgrade_pip=false'"
        Write-CIEvent -Type "BUILD_META" -Fields @{ ci = $true; repo = $repoRoot; log_file = $Script:LogFile }
    }

    Write-Log -Level "INFO" -Message ("projeto='{0}'" -f $repoRoot)
    Write-Log -Level "INFO" -Message ("parametros python='{0}' inno='{1}' requirements='{2}' pyinstaller_version='{3}' upgrade_pip={4} ci={5} skip_dependency_install={6}" -f $PythonExe, $InnoCompiler, $RequirementsFile, $PyInstallerVersion, [bool]$UpgradePip, [bool]$CI, [bool]$SkipDependencyInstall)

    Invoke-BuildStep -StepName "validar_requirements" -Action {
        Assert-PathExists -PathToCheck $RequirementsFile -ErrorMessage "Arquivo de dependencias nao encontrado: $RequirementsFile"
    }

    if (-not $SkipDependencyInstall) {
        Invoke-BuildStep -StepName "instalar_dependencias" -Action {
            if ($UpgradePip) {
                Invoke-ExternalCommand -StepName "pip_upgrade" -FilePath $PythonExe -Arguments @("-m", "pip", "install", "--upgrade", "pip")
            }
            Invoke-ExternalCommand -StepName "pip_requirements" -FilePath $PythonExe -Arguments @("-m", "pip", "install", "-r", $RequirementsFile)
            Invoke-ExternalCommand -StepName "pip_pyinstaller" -FilePath $PythonExe -Arguments @("-m", "pip", "install", "pyinstaller==$PyInstallerVersion")
        }
    }
    else {
        Write-Log -Level "WARN" -Message "etapa='instalar_dependencias' status='ignorada' motivo='skip_dependency_install=true'"
    }

    Invoke-BuildStep -StepName "build_pyinstaller" -Action {
        Invoke-ExternalCommand -StepName "pyinstaller" -FilePath $PythonExe -Arguments @("-m", "PyInstaller", "--noconfirm", ".\AnaliseCertiDigital_Agent.spec")
    }

    $exePath = Join-Path $repoRoot "dist\AnaliseCertiDigital_Agent.exe"
    Invoke-BuildStep -StepName "validar_executavel" -Action {
        Assert-PathExists -PathToCheck $exePath -ErrorMessage "Executavel nao encontrado em: $exePath"
        Assert-MinFileSize -PathToCheck $exePath -MinSizeBytes $MinimumExeSizeBytes -Label "Executavel"
        Show-ArtifactMetadata -PathToShow $exePath -Label "Executavel"
    }

    Invoke-BuildStep -StepName "build_pyinstaller_service" -Action {
        Invoke-ExternalCommand -StepName "pyinstaller_service" -FilePath $PythonExe -Arguments @("-m", "PyInstaller", "--noconfirm", ".\AnaliseCertiDigital_Service.spec")
    }

    $serviceExePath = Join-Path $repoRoot "dist\AnaliseCertiDigital_Agent_Service\AnaliseCertiDigital_Agent_Service.exe"
    Invoke-BuildStep -StepName "validar_executavel_servico" -Action {
        Assert-PathExists -PathToCheck $serviceExePath -ErrorMessage "Executavel de servico nao encontrado em: $serviceExePath"
        Assert-MinFileSize -PathToCheck $serviceExePath -MinSizeBytes $MinimumServiceExeSizeBytes -Label "ExecutavelServico"
        Show-ArtifactMetadata -PathToShow $serviceExePath -Label "ExecutavelServico"
    }

    Invoke-BuildStep -StepName "validar_inno_compiler" -Action {
        Assert-PathExists -PathToCheck $InnoCompiler -ErrorMessage "ISCC.exe nao encontrado. Instale Inno Setup 6 ou informe -InnoCompiler com o caminho correto."
    }

    Invoke-BuildStep -StepName "build_instalador_inno" -Action {
        Invoke-ExternalCommand -StepName "iscc" -FilePath $InnoCompiler -Arguments @(".\agent_setup.iss")
    }

    $installerDir = Join-Path $repoRoot "dist\installer"
    $installerPath = Join-Path $installerDir "Instalador_AnaliseCertiDigital_Agente.exe"
    Invoke-BuildStep -StepName "validar_instalador" -Action {
        Assert-PathExists -PathToCheck $installerDir -ErrorMessage "Diretorio de instalador nao encontrado: $installerDir"
        Assert-PathExists -PathToCheck $installerPath -ErrorMessage "Instalador nao encontrado em: $installerPath"
        Assert-MinFileSize -PathToCheck $installerPath -MinSizeBytes $MinimumInstallerSizeBytes -Label "Instalador"
        Show-ArtifactMetadata -PathToShow $installerPath -Label "Instalador"
    }

    $buildSw.Stop()
    Write-Log -Level "INFO" -Message ("BUILD_SUCESSO duracao_total_ms={0}" -f $buildSw.ElapsedMilliseconds)
    Write-Log -Level "INFO" -Message ("saida executavel='{0}' servico='{1}' instalador='{2}'" -f $exePath, $serviceExePath, $installerPath)
    Write-CIEvent -Type "BUILD_RESULT" -Fields @{ status = "success"; duration_ms = $buildSw.ElapsedMilliseconds; executable = $exePath; service_executable = $serviceExePath; installer = $installerPath; log_file = $Script:LogFile }
}
catch {
    $buildSw.Stop()
    Write-Log -Level "ERROR" -Message ("BUILD_FALHOU duracao_total_ms={0} erro='{1}'" -f $buildSw.ElapsedMilliseconds, $_.Exception.Message)
    Write-CIEvent -Type "BUILD_RESULT" -Fields @{ status = "failed"; duration_ms = $buildSw.ElapsedMilliseconds; error = $_.Exception.Message; log_file = $Script:LogFile }
    throw
}
finally {
    if ($Script:LogFile) {
        Write-Host ""
        Write-Host ("Log de build: {0}" -f $Script:LogFile)
    }
}
