"""Agente Windows do Analise CertiDigital.

Este arquivo existe para que `agent` seja um pacote regular, e não um namespace
package implícito. No desenvolvimento os dois funcionam igual, porque a raiz do
repositório está no sys.path. No executável do PyInstaller não: namespace
packages dependem da varredura de diretórios, que não existe dentro do archive,
e `from agent.installer_client import ...` — feito tarde, dentro das funções de
run_agent — podia simplesmente não resolver.

O sintoma seria mudo: o agente empacotado rodaria normalmente, faria os scans,
e a instalação remota nunca aconteceria.
"""

# Fonte única da versão do agente. O instalador declara a dele em
# `agent_setup.iss` (AppVersion), que o Inno não consegue ler daqui — um teste
# em tests/test_versao_agente.py garante que as duas não divirjam.
__version__ = "1.2.0"
