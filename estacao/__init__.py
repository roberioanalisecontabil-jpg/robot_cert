"""CertGuard Análise — o agente de certificados das estações (ADR 0003).

Programa próprio, separado do Hardlyze: a bandeja da pessoa entra com a conta
deste portal, recebe os pedidos de instalação e importa o certificado no
repositório dela. Não é o `agent/` (que roda só no ANALISESRV, lendo a pasta
dos PFX).

A 1.0 faz só o que a bandeja de certificados do Hardlyze 2.2.0 fazia (adendo de
14/10/2026 do ADR 0003): o código veio de lá, com os nomes e as pastas novas.
"""

NOME = "CertGuard Análise"
VERSAO = "1.1.1"
# O que vai no X-Agent-Version: a aba Computadores mostra lado a lado bandejas
# do Hardlyze (2.x) e deste programa durante a troca, e "1.0.0" sozinho
# pareceria um Hardlyze muito antigo.
VERSAO_REPORTADA = f"certguard-{VERSAO}"
