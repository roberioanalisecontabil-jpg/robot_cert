# Detalhes do certificado e inclusão no SIEG

Decidido em 06/10/2026 (grill sobre o pedido do modal e do interruptor). Duas
entregas; a segunda espera o processo de inclusão via API do SIEG.

## Entrega 1 — modal de detalhes no Início

- Fora do modo **Selecionar**, clicar na linha abre o modal; o nome é um botão
  ("Ver detalhes de …") para teclado e leitor de tela. No modo de seleção o
  clique continua marcando a caixa.
- Campos: Nome (CN), Tipo (e-CNPJ / e-CPF), Validade ("Válido · vence em N
  dias"), documento com máscara, **Cadeia** (o `O=` do sujeito — a planilha de
  exemplo chamava de "Empresa", mas ICP-Brasil é a cadeia), Emissão e
  Vencimento com hora, Emissor (CN do emissor), Número de série em
  maiúsculas; Responsável, CPF, Data de nascimento (dd/mm/aaaa) e E-mail; No
  cofre; Arquivo (só administrador).
- **Dados pessoais** (responsável, CPF, nascimento, e-mail) só saem pela rota
  `GET /api/certificados/{fingerprint}/detalhes`, com o mesmo alcance da lista
  e da instalação ("ver e instalar são um direito só"); fora dele, 404.
  `settings_state.get_latest_snapshot()` devolve o inventário **sem** esses
  campos por padrão — só a rota de detalhes pede `com_dados_pessoais=True`.
  `tests/test_detalhes_certificado.py` chama todas as rotas GET da API e
  reprova se o CPF sair por qualquer uma.
- **De onde vêm:** o agente 1.7.0 lê os otherName ICP-Brasil do
  SubjectAltName (DOC-ICP-04) em `app/cert_scanner.campos_icp`:
  `2.16.76.1.3.2` (nome do responsável, e-CNPJ), `2.16.76.1.3.4` (nascimento
  DDMMAAAA + CPF do responsável, e-CNPJ), `2.16.76.1.3.1` (os mesmos do
  titular, e-CPF) e o `rfc822Name` (e-mail). Campo zerado = ausente.
  Conferido em 06/10/2026 contra 9 certificados reais de SAFEWEB, SERPRO,
  SyngularID e ALTERNATIVE.
- Ordem de implantação: portal primeiro (o modal mostra "—" e a nota "Estes
  dados aparecem depois da próxima varredura do agente 1.7.0"; emissor e
  cadeia já saem do texto do emissor/sujeito), depois o instalador 1.7.0 no
  ANALISESRV.

## Entrega 2 — "Incluir no SIEG" (aguarda o processo)

- Interruptor **por certificado** (fingerprint): a renovação nasce desligada.
- Quem liga: a regra da instalação (carteira / alcance), conferida no
  servidor; quem só tem "Só ver" vê o estado e não liga.
- Desabilitado para vencido e ilegível, com o motivo escrito.
- Confirmação em modal do DS: "Esta ação não pode ser desfeita".
- Até o processo chegar grava **Solicitado** (quem, quando). Com o processo,
  a inclusão é uma chamada à API do SIEG na hora: o estado vira **No SIEG** ou
  mostra o erro; ninguém precisa ser avisado depois.
- Ninguém desliga. O administrador tem a **reconciliação**: consulta o SIEG;
  existe e está ativo → mantém; não existe → desliga e pode ser religado. Tudo
  em trilha.
- Lista: selo só para Solicitado e No SIEG; filtro "SIEG: Todos · Solicitado ·
  No SIEG · Fora do SIEG", com o estado na URL.
- Banco: tabela nova (estado + trilha). A mesma migration apaga as duas
  tabelas `sieg_*` mortas desde junho (depois de conferir que ninguém as lê) e
  tira da fila os comandos `sieg_*` pendentes.

Contexto: o SIEG já existiu aqui (automação Playwright em app.sieg.com,
`agent/sieg_worker.py`) e foi removido; não sobrou fonte.

**Em aberto até o processo:** a chamada de inclusão, a consulta da
reconciliação e se é preciso estar no cofre.
