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

## Entrega 2 — "Incluir no SIEG" (07/10/2026)

Processo: o script que o usuário validou contra a API em 06/10/2026, portado
para `app/sieg_api.py` (httpx). `POST /api/v1/create-jwt` (X-Client-Id,
X-Secret-Key) → Bearer + `X-Api-Key` (chave da conta) em toda chamada;
`/registrar` e depois **conferência em `/listar`** (a API já respondeu
"sucesso" sem cadastrar); CNPJ existente → `/editar` (só o arquivo) e
`/habilitar` se inativo; `Deletado=true` → `/habilitar`; opção de consulta
recusada → desliga a opção e repete.

- **Onde roda:** no portal, com o PFX e a senha do **cofre** (o agente envia a
  pasta do ANALISESRV para o cofre), em segundo plano: o interruptor mostra
  "Incluindo…" e a tela atualiza para "No SIEG" ou para o erro.
- **Estado por certificado** (`sieg_inclusao`): incluindo, no_sieg, erro,
  substituido, removido. Ninguém desliga; erro oferece "Tentar de novo".
- **Quem liga:** o alcance da carteira (a regra da instalação), no servidor.
  Desabilitado para vencido, ilegível, fora do cofre e SIEG não configurado,
  com o motivo escrito. Confirmação "Esta ação não pode ser desfeita".
- **Renovação:** o novo do mesmo CNPJ atualiza o cadastro no SIEG; o anterior
  vira "Substituído" apontando para o novo.
- **Reconciliação (administrador):** "Conferir no SIEG" no modal — ativo lá →
  mantém; inativo ou ausente → "Fora do SIEG", que pode ser ligado de novo.
- **Sincronizar (administrador, Configuração › SIEG):** marca "No SIEG" o
  certificado vigente de cada cliente que já está na conta. Não envia nada.
- **Trilha** (`sieg_trilha`) e log do servidor: operação, HTTP, mensagem da
  API, opções desligadas e avisos. Nunca senha, PFX, credencial ou token
  (`tests/test_sieg_portal.py` confere).
- **Telas:** seção SIEG no modal do Início; selo na linha (No SIEG,
  incluindo, erro) e filtro "SIEG" com estado na URL (`?sieg=`); aba **SIEG**
  no Instalador (administrador), com as tentativas abrindo na linha; a
  **Trilha** passa a mostrar qual certificado foi instalado; Configuração ›
  **SIEG** com Client ID, Secret Key e API Key cifradas (campo vazio mantém),
  padrões de UF e consultas (os do config.json validado), Testar conexão e
  Sincronizar.
- **Sem lote** por decisão.
- **Migration** `20261007120000_inclusao_no_sieg.sql`: colunas `sieg_*` em
  `portal_settings`, as duas tabelas, `DROP` das tabelas `sieg_*` de junho e
  remoção dos comandos `sieg_*` pendentes da fila.

Contexto: o SIEG já existiu aqui em junho (automação Playwright em
app.sieg.com, `agent/sieg_worker.py`) e foi removido.
