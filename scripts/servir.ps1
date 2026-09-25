# Inicia o API FastAPI (uvicorn) a partir da raiz do repositorio robot_cert.
# Uso:
#   .\scripts\servir.ps1              # porta 8020 (padrao - evita conflito com 8000), sem reload
#   .\scripts\servir.ps1 -Dev         # desenvolvimento: recarrega ao salvar arquivo
#   .\scripts\servir.ps1 -Port 9000
#
# Bind em 127.0.0.1 por padrao: em producao o TLS e o acesso de fora sao do
# Caddy (deploy/Caddyfile), que fala com a aplicacao por loopback. Servir em
# 0.0.0.0 exporia HTTP puro na rede (SECURITY_AUDIT #37/#38).
param(
    [int] $Port = 8020,
    [string] $Host = "127.0.0.1",
    [switch] $Dev
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

Write-Host "A servir em http://${Host}:$Port/  | configuracao: http://${Host}:$Port/configuracao" -ForegroundColor Cyan
Write-Host "Ctrl+C para parar." -ForegroundColor DarkGray

# --no-server-header: o uvicorn escreve `server: uvicorn` DEPOIS do middleware
# da aplicacao, entao apaga-lo em app/main.py nao tinha efeito (SECURITY_AUDIT
# #50). Anunciar o servidor so ajuda quem procura CVE por versao.
$argumentos = @("-m", "uvicorn", "app.main:app", "--host", $Host, "--port", $Port, "--no-server-header")

# --reload SO em desenvolvimento (SECURITY_AUDIT #59): o watcher de arquivos
# consome CPU e reinicia o processo a qualquer escrita na pasta -- inclusive
# um log ou um .pfx chegando. Em producao o servico e reiniciado pelo
# atualizar-portal.ps1, nunca por watcher.
if ($Dev) {
    $argumentos += "--reload"
    Write-Host "Modo desenvolvimento: --reload ligado." -ForegroundColor Yellow
}

& python @argumentos
