# Separação do agente: o que sai do Hardlyze e como trocar nas estações

Par do adendo de 14/10/2026 ao ADR 0003. O agente de certificados das estações
agora é o **Certguard Análise** (`estacao/` deste repositório, instalador
`Instalador_CertguardAnalise_1.0.0.exe`). Esta nota é para a sessão do INVENT: o
repositório do Hardlyze não é mexido daqui.

## 1. O que sai do Hardlyze (INVENT)

O Certguard Análise 1.0 faz tudo o que a bandeja de certificados do Hardlyze
2.2.0 fazia. Numa versão do Hardlyze sem certificados (a numeração é de lá):

- **Módulos** em `core/`: `conta_certificados.py`, `instalador_certificado.py`,
  `chave_maquina.py`, `janela_login.py`. Em `janela_status.py`, a linha
  "Certificados" e o menu Conta (entrar/sair do portal de certificados).
- **`main.py`**:
  - `texto_certificados`, `_autorizacao_anterior`, `_conta_certificados_conectada`,
    `certificados_loop`, `verificar_instalacoes_do_portal`, `on_sair_certificados`,
    `on_login`, e a thread `certificados_loop` no modo tray-only;
  - os itens do menu da bandeja: a linha de status de certificados, "Entrar no
    portal de certificados…", "Sair da conta de certificados";
  - o pedido automático de login na partida da bandeja;
  - `chave_maquina.garantir()` na partida do serviço: o Hardlyze **não gera mais**
    a `chave_certificados.dat`. Se continuasse, recriaria uma chave que ninguém usa
    depois que o instalador do Certguard Análise apaga a original;
  - `cert_portal_url` (recebido no agendamento) deixa de ter uso.
- **`hardlyze.spec`**: os hiddenimports `core.conta_certificados`,
  `core.chave_maquina`, `core.janela_login`, `core.instalador_certificado`.
- **Testes**: `test_conta_certificados.py`, `test_chave_maquina.py`, e as partes de
  `test_instalacao_na_estacao.py`, `test_identidade_do_agente.py` (janela de
  login) e `test_janela_status.py` que tratam de certificado.
- **`docs/decisoes-proximas-frentes.md`**: a seção A diz que o agente novo tem
  serviço e que o serviço copia a chave; a seção B e a "Ordem de execução" põem a
  atualização automática antes do agente de certificados. As duas coisas mudaram
  em 14/10 (ver o adendo do ADR 0003 aqui).

O desinstalador do Hardlyze **não** deve passar a apagar
`%ProgramData%\InventAgent` nem `%LOCALAPPDATA%\InventAgent`: é de lá que o
Certguard Análise copia a chave da máquina e a conta da pessoa.

## 2. Troca em cada estação (manual)

A ordem importa. Instalando o Certguard Análise com a bandeja antiga do Hardlyze
ainda aberta, a conta da pessoa é trazida e apagada do Hardlyze, e a bandeja
antiga passa a pedir login.

1. Desinstalar o Hardlyze atual (Aplicativos instalados).
2. Instalar o Hardlyze sem certificados.
3. Instalar o `Instalador_CertguardAnalise_1.0.0.exe` (pede administrador). Ele:
   - copia `C:\ProgramData\InventAgent\chave_certificados.dat` para
     `C:\ProgramData\CertguardAnalise\chave_maquina.dat` e apaga a original
     (sem chave antiga, gera uma nova, e a máquina vai pedir sua autorização);
   - registra a bandeja para abrir no logon de qualquer pessoa e já a abre.
4. Com a pessoa logada no Windows: a bandeja abre **sem pedir login** (traz a
   conta de `%LOCALAPPDATA%\InventAgent\certificados.dat` e apaga a original). O
   item de status diz "computador autorizado".
5. Conferir no portal (Usuários › Computadores) que a máquina continua
   autorizada e que a versão mostrada é `certguard-1.0.0`.

Onde olhar se algo der errado:

- instalação da chave: `C:\ProgramData\CertguardAnalise\logs\instalacao.log`;
- bandeja: `%LOCALAPPDATA%\CertguardAnalise\logs\bandeja.log`, ou duplo clique
  no ícone (Status e histórico).

Em outras pessoas da mesma estação, a conta é trazida quando a bandeja abre no
logon delas. Quem nunca entrou pelo Hardlyze recebe a janela de login.

## 3. Ensaio antes das estações

Na máquina de teste, nesta ordem: Hardlyze 2.2.0 instalado e logado no portal
de certificados → passos 1 a 5 acima → pedir pelo portal a instalação de um
certificado de teste para essa máquina → conferir que ele aparece em
`certmgr.msc` (Pessoal) da pessoa, e no histórico da bandeja.
