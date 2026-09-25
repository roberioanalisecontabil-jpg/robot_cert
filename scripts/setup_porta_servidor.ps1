#Requires -RunAsAdministrator
<#
.SYNOPSIS
    Setup e verificacao de portas para o portal Analise CertiDigital.
    Executar como ADMINISTRADOR no Windows Server de destino.

.DESCRIPTION
    Desenho (SECURITY_AUDIT #37/#38, lote 9): a aplicacao (uvicorn) faz bind
    SO em 127.0.0.1:8020 e quem atende a rede e o Caddy (deploy/Caddyfile),
    com TLS e redirecionamento de 80 para 443. Portanto o firewall abre 80 e
    443 -- as portas do proxy -- e NUNCA a 8020. Este script:

      1. informa a maquina;
      2. confere que a 8020 esta ouvindo apenas em loopback (se ja subiu);
      3. cria/atualiza a regra de firewall para 80 e 443 (TCP, entrada);
      4. remove uma regra antiga que abria a 8020 para fora, se existir;
      5. confere o Python e testa a resposta local da aplicacao.
#>

$PORTA_APP = 8020
$PORTAS_PROXY = @(80, 443)
$NOME_REGRA = "AnaliseCertiDigital-Proxy-HTTPS"
$NOME_REGRA_ANTIGA = "AnaliseCertiDigital-Portal"
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
Write-Log "  SETUP DE PORTAS - ANALISE CERTIDIGITAL" "Cyan"
Write-Log "  Aplicacao: 127.0.0.1:$PORTA_APP (loopback)" "Cyan"
Write-Log "  Proxy TLS: portas $($PORTAS_PROXY -join ', ')" "Cyan"
Write-Log "========================================" "Cyan"
Write-Log ""

# -------------------------------------------------------
# PASSO 1: Informacoes da maquina
# -------------------------------------------------------
Write-Log "--- [1/5] INFORMACOES DA MAQUINA ---" "Yellow"

$ip_local = (Get-NetIPAddress -AddressFamily IPv4 |
    Where-Object { $_.InterfaceAlias -notlike "*Loopback*" -and $_.PrefixOrigin -ne "WellKnown" } |
    Select-Object -First 1).IPAddress
$hostname = $env:COMPUTERNAME
$os = (Get-CimInstance Win32_OperatingSystem).Caption

Write-Log "  Hostname   : $hostname"
Write-Log "  Sistema    : $os"
Write-Log "  IP Local   : $ip_local"
Write-Log ""

# -------------------------------------------------------
# PASSO 2: A aplicacao so pode ouvir em loopback
# -------------------------------------------------------
Write-Log "--- [2/5] BIND DA APLICACAO NA PORTA $PORTA_APP ---" "Yellow"

$escutas = Get-NetTCPConnection -LocalPort $PORTA_APP -State Listen -ErrorAction SilentlyContinue
if (-not $escutas) {
    Write-Log "  INFO: nada ouvindo na $PORTA_APP (normal se o portal ainda nao subiu)" "Magenta"
} else {
    foreach ($e in $escutas) {
        if ($e.LocalAddress -eq "127.0.0.1" -or $e.LocalAddress -eq "::1") {
            Write-Log "  OK - $($e.LocalAddress):$PORTA_APP (loopback, como deve ser)" "Green"
        } else {
            Write-Log "  ATENCAO: $($e.LocalAddress):$PORTA_APP esta exposta na rede em HTTP puro!" "Red"
            Write-Log "  Corrija o servico (NSSM/uvicorn) para --host 127.0.0.1 e reinicie." "Red"
        }
    }
}
Write-Log ""

# -------------------------------------------------------
# PASSO 3: Firewall - portas do proxy (80 e 443)
# -------------------------------------------------------
Write-Log "--- [3/5] CONFIGURANDO FIREWALL ($($PORTAS_PROXY -join ', ')) ---" "Yellow"

$regra_existente = Get-NetFirewallRule -DisplayName $NOME_REGRA -ErrorAction SilentlyContinue
if ($regra_existente) {
    Write-Log "  Regra existente encontrada. Removendo para recriar limpa..." "Magenta"
    Remove-NetFirewallRule -DisplayName $NOME_REGRA
}

try {
    New-NetFirewallRule `
        -DisplayName $NOME_REGRA `
        -Description "Caddy (TLS) na frente dos portais Analise CertiDigital e Hardlyze" `
        -Direction Inbound `
        -Protocol TCP `
        -LocalPort $PORTAS_PROXY `
        -Action Allow `
        -Profile Domain,Private `
        -Enabled True | Out-Null

    Write-Log "  OK - Regra de firewall criada!" "Green"
    Write-Log "  Nome   : $NOME_REGRA"
    Write-Log "  Portas : $($PORTAS_PROXY -join ', ')/TCP"
    Write-Log "  Perfis : Dominio, Privado (a rede e privada + VPN; nada vai para a internet)"
} catch {
    Write-Log "  ERRO ao criar regra: $_" "Red"
}

# -------------------------------------------------------
# PASSO 4: Fechar a porta da aplicacao, se algum dia foi aberta
# -------------------------------------------------------
Write-Log "--- [4/5] REGRA ANTIGA DA PORTA $PORTA_APP ---" "Yellow"
$antiga = Get-NetFirewallRule -DisplayName $NOME_REGRA_ANTIGA -ErrorAction SilentlyContinue
if ($antiga) {
    Remove-NetFirewallRule -DisplayName $NOME_REGRA_ANTIGA
    Write-Log "  Removida a regra '$NOME_REGRA_ANTIGA' que abria a $PORTA_APP para a rede." "Magenta"
} else {
    Write-Log "  OK - nenhuma regra abrindo a $PORTA_APP para fora." "Green"
}
Write-Log ""

# -------------------------------------------------------
# PASSO 5: Python e resposta local
# -------------------------------------------------------
Write-Log "--- [5/5] PYTHON E RESPOSTA LOCAL ---" "Yellow"

$python = Get-Command python -ErrorAction SilentlyContinue
if ($python) {
    $versao = & python --version
    Write-Log "  OK - Python encontrado: $versao" "Green"
} else {
    Write-Log "  ATENCAO: Python NAO encontrado no PATH!" "Red"
}

$tcp = New-Object System.Net.Sockets.TcpClient
try {
    $tcp.Connect("127.0.0.1", $PORTA_APP)
    Write-Log "  OK - aplicacao respondendo em 127.0.0.1:$PORTA_APP" "Green"
    $tcp.Close()
} catch {
    Write-Log "  INFO: 127.0.0.1:$PORTA_APP nao responde (normal se o portal ainda nao foi iniciado)" "Magenta"
}
Write-Log ""

Write-Log "========================================" "Cyan"
Write-Log "  RESUMO" "Cyan"
Write-Log "========================================" "Cyan"
Write-Log "  Acesso: https://certificado.analisegroup.cnt.br (via Caddy, 443)" "White"
Write-Log "  A porta $PORTA_APP NAO deve ser encaminhada em roteador nenhum." "White"
Write-Log "  Log salvo em: $LOG" "Cyan"

Write-Host ""
Write-Host "Pressione ENTER para fechar..." -ForegroundColor DarkGray
Read-Host
