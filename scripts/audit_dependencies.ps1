# Script de Auditoria OWASP / SCA para o projeto FastAPI
# Equivalente ao OWASP Dependency-Check (via pip-audit)

Write-Host "Iniciando Auditoria de Dependências (OWASP / Supply Chain)..." -ForegroundColor Cyan

# Verifica se o pip-audit está instalado
if (-not (Get-Command "pip-audit" -ErrorAction SilentlyContinue)) {
    Write-Host "pip-audit não encontrado. Instalando..." -ForegroundColor Yellow
    pip install pip-audit
}

Write-Host "Auditando as dependências do requirements.txt contra o banco de dados de CVEs (PyPI/OSV)..." -ForegroundColor Cyan

# Executa o pip-audit
python -m pip_audit -r requirements.txt -f json -o audit-report.json

if ($LASTEXITCODE -eq 0) {
    Write-Host "SUCESSO: Nenhuma vulnerabilidade conhecida foi detectada nas dependências!" -ForegroundColor Green
} else {
    Write-Host "ATENÇÃO: Vulnerabilidades foram encontradas nas dependências! Verifique o audit-report.json." -ForegroundColor Red
    Write-Host "Consulte o OWASP Dependency-Check Section 3 do guia de segurança para remediação." -ForegroundColor Yellow
}
