<#
.SYNOPSIS
    Testar se a porta do servidor esta acessivel externamente.
    Rodar nesta maquina (dev/local) APOS configurar o servidor.
#>

$IP_SERVIDOR = Read-Host "Digite o IP externo do servidor (ou dominio)"
$PORTA = 8020
$TIMEOUT = 5

Write-Host ""
Write-Host "Testando conexao com $IP_SERVIDOR`:$PORTA ..." -ForegroundColor Cyan

$tcp = New-Object System.Net.Sockets.TcpClient
$conexao = $tcp.BeginConnect($IP_SERVIDOR, $PORTA, $null, $null)
$aguardou = $conexao.AsyncWaitHandle.WaitOne([TimeSpan]::FromSeconds($TIMEOUT), $false)

if ($aguardou -and $tcp.Connected) {
    $tcp.EndConnect($conexao)
    $tcp.Close()
    Write-Host ""
    Write-Host "  [OK] PORTA ACESSIVEL!" -ForegroundColor Green
    Write-Host "  O servidor esta respondendo em http://$IP_SERVIDOR`:$PORTA" -ForegroundColor Green
    Write-Host ""
    Write-Host "  Agora tente abrir no navegador:" -ForegroundColor Yellow
    Write-Host "  http://$IP_SERVIDOR`:$PORTA" -ForegroundColor Yellow
} else {
    $tcp.Close()
    Write-Host ""
    Write-Host "  [FALHA] Porta NAO acessivel de fora." -ForegroundColor Red
    Write-Host ""
    Write-Host "  Verifique:" -ForegroundColor Yellow
    Write-Host "  1. Firewall do Windows Server - regra AnaliseCertiDigital-Portal criada?" -ForegroundColor White
    Write-Host "  2. Port Forwarding no roteador - porta $PORTA apontando para o IP interno?" -ForegroundColor White
    Write-Host "  3. O portal esta rodando? (uvicorn iniciado?)" -ForegroundColor White
    Write-Host "  4. O IP digitado esta correto?" -ForegroundColor White
}

Write-Host ""
Read-Host "Pressione ENTER para fechar"
