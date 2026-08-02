#Requires -RunAsAdministrator
<#
.SYNOPSIS
    Setup e verificacao de porta para o portal Analise CertiDigital
    Executar como ADMINISTRADOR no Windows Server de destino.
#>

$PORTA = 8020
$NOME_REGRA = "AnaliseCertiDigital-Portal"
$LOG = "$PSScriptRoot\resultado_porta.txt"

function Write-Log {
    param($Msg, $Cor = "White")
    $linha = "[$(Get-Date -Format 'HH:mm:ss')] $Msg"
    Write-Host $linha -ForegroundColor $Cor
    Add-Content -Path $LOG -Value $linha
}

Clear-Host
"" | Set-Content $LOG
Write-Log "========================================" "Cyan"
Write-Log "  SETUP DE PORTA - ANALISE CERTIDIGITAL " "Cyan"
Write-Log "  Porta alvo: $PORTA                    " "Cyan"
Write-Log "========================================" "Cyan"
Write-Log ""

# -------------------------------------------------------
# PASSO 1: Informacoes da maquina
# -------------------------------------------------------
Write-Log "--- [1/5] INFORMACOES DA MAQUINA ---" "Yellow"

$ip_local = (Get-NetIPAddress -AddressFamily IPv4 |
    Where-Object { $_.InterfaceAlias -notlike "*Loopback*" -and $_.PrefixOrigin -ne "WellKnown" } |
    Select-Object -First 1).IPAddress

try {
    $ip_externo = (Invoke-WebRequest -Uri "https://api.ipify.org" -UseBasicParsing -TimeoutSec 10).Content
} catch {
    $ip_externo = "Nao foi possivel obter (sem internet?)"
}

$hostname = $env:COMPUTERNAME
$os = (Get-WmiObject Win32_OperatingSystem).Caption

Write-Log "  Hostname   : $hostname"
Write-Log "  Sistema    : $os"
Write-Log "  IP Local   : $ip_local"
Write-Log "  IP Externo : $ip_externo"
Write-Log ""

# -------------------------------------------------------
# PASSO 2: Verificar se a porta ja esta em uso
# -------------------------------------------------------
Write-Log "--- [2/5] VERIFICANDO SE PORTA $PORTA JA ESTA EM USO ---" "Yellow"

$porta_em_uso = Get-NetTCPConnection -LocalPort $PORTA -ErrorAction SilentlyContinue
if ($porta_em_uso) {
    $pid_dono = $porta_em_uso.OwningProcess | Select-Object -First 1
    $processo = Get-Process -Id $pid_dono -ErrorAction SilentlyContinue
    Write-Log "  ATENCAO: Porta $PORTA ja esta sendo usada!" "Red"
    Write-Log "  PID: $pid_dono | Processo: $($processo.Name)" "Red"
    Write-Log "  Se for uma instancia antiga do portal, encerre com: Stop-Process -Id $pid_dono"
} else {
    Write-Log "  OK - Porta $PORTA disponivel (nenhum processo usando)" "Green"
}
Write-Log ""

# -------------------------------------------------------
# PASSO 3: Criar/Atualizar regra de Firewall
# -------------------------------------------------------
Write-Log "--- [3/5] CONFIGURANDO FIREWALL ---" "Yellow"

$regra_existente = Get-NetFirewallRule -DisplayName $NOME_REGRA -ErrorAction SilentlyContinue

if ($regra_existente) {
    Write-Log "  Regra existente encontrada. Removendo para recriar limpa..." "Magenta"
    Remove-NetFirewallRule -DisplayName $NOME_REGRA
}

try {
    New-NetFirewallRule `
        -DisplayName $NOME_REGRA `
        -Description "Portal FastAPI de monitoramento de certificados digitais" `
        -Direction Inbound `
        -Protocol TCP `
        -LocalPort $PORTA `
        -Action Allow `
        -Profile Any `
        -Enabled True | Out-Null

    Write-Log "  OK - Regra de firewall criada com sucesso!" "Green"
    Write-Log "  Nome   : $NOME_REGRA"
    Write-Log "  Porta  : $PORTA/TCP"
    Write-Log "  Perfis : Dominio, Privado, Publico"
    Write-Log "  Acao   : Permitir"
} catch {
    Write-Log "  ERRO ao criar regra: $_" "Red"
}
Write-Log ""

# -------------------------------------------------------
# PASSO 4: Verificar se Python esta instalado
# -------------------------------------------------------
Write-Log "--- [4/5] VERIFICANDO PYTHON ---" "Yellow"

$python = Get-Command python -ErrorAction SilentlyContinue
if ($python) {
    $versao = python --version 2>&1
    Write-Log "  OK - Python encontrado: $versao" "Green"
    Write-Log "  Caminho: $($python.Source)"
} else {
    Write-Log "  ATENCAO: Python NAO encontrado no PATH!" "Red"
    Write-Log "  Baixe em: https://www.python.org/downloads/ (marcar 'Add to PATH')"
}
Write-Log ""

# -------------------------------------------------------
# PASSO 5: Teste de conectividade local
# -------------------------------------------------------
Write-Log "--- [5/5] TESTE RAPIDO DE CONECTIVIDADE LOCAL ---" "Yellow"

$tcp = New-Object System.Net.Sockets.TcpClient
try {
    $tcp.Connect("127.0.0.1", $PORTA)
    Write-Log "  OK - Porta $PORTA respondendo localmente (servico ja esta rodando!)" "Green"
    $tcp.Close()
} catch {
    Write-Log "  INFO: Porta $PORTA nao esta respondendo localmente" "Magenta"
    Write-Log "  (Normal se o portal ainda nao foi iniciado)"
}
Write-Log ""

# -------------------------------------------------------
# RESUMO FINAL
# -------------------------------------------------------
Write-Log "========================================" "Cyan"
Write-Log "  RESUMO PARA CONFIGURAR O ROTEADOR    " "Cyan"
Write-Log "========================================" "Cyan"
Write-Log ""
Write-Log "  Para acesso EXTERNO, configure no roteador:" "White"
Write-Log "  Protocolo   : TCP" "White"
Write-Log "  Porta Ext.  : $PORTA" "White"
Write-Log "  IP Interno  : $ip_local" "White"
Write-Log "  Porta Int.  : $PORTA" "White"
Write-Log ""
Write-Log "  URL de acesso externo sera:" "White"
Write-Log "  http://$ip_externo`:$PORTA" "Green"
Write-Log ""
Write-Log "  Log salvo em: $LOG" "Cyan"
Write-Log "========================================" "Cyan"

Write-Host ""
Write-Host "Pressione ENTER para fechar..." -ForegroundColor DarkGray
Read-Host
