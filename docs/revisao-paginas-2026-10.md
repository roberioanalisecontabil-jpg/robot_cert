# Revisão página a página — outubro de 2026

Revisão de lógica e funcionamento do portal, uma página por vez, antes da
entrada em produção do modelo de acesso do [ADR 0001](adr/0001-carteira-por-papel.md).
Vocabulário: [GLOSSARY.md](../GLOSSARY.md).

**Régua** (a mesma para toda página): para que a página existe; quem vê e quem
edita, por papel, e isso bate com a matriz de permissões; cada ação da tela
(o que valida, o que grava, o que mostra depois); os quatro estados (vazio,
carregando, erro, sem permissão) com texto que diz a consequência; vocabulário
conforme o glossário.

**Método**: um levantamento factual do código por página, depois decisões do
usuário sobre o que estava indefinido ou contraditório. Defeitos claros são
corrigidos na hora; decisões ficam registradas aqui e, quando mudam o modelo,
no glossário ou num ADR.

**Ordem**: Usuários → Carteiras → Início → Instalador → Acompanhamento →
Dashboard, Histórico, Vencidos, Duplicidades → Configuração, Login.

A granularidade de permissões (por usuário; "apagar" separado de "editar"),
pendência antiga do `PLANO_niveis_de_acesso.md`, entra nesta revisão por
decisão de 01/10/2026, na aba Níveis de acesso.

---

## 1. Usuários (01/10/2026)

**Para que existe**: cadastrar e administrar quem entra no portal — contas,
departamentos (e seus gestores) e níveis de acesso por papel.

**Quem vê**: só o Administrador (decisão U1). A rota HTML não tem guarda; a
tela expulsa quem não é admin e todas as APIs exigem `require_admin`.

### Decisões

| # | Pergunta | Decisão | Motivo |
|---|----------|---------|--------|
| U1 | A matriz permitia dar "Usuários: ler/editar" a Gestor, mas a tela expulsava quem não é admin. | **Só Administrador.** `usuarios` saiu da matriz configurável (`MODULOS_SO_ADMIN`); linha antiga no banco é ignorada. | É aqui que se nomeia Gestor e Administrador; quem concede papéis tem de estar acima dos papéis. |
| U2 | Campo "Gestor responsável" (`gestor_id`): informativo, não autorizava nada, não importado por CSV, perdido no cadastro. | **Removido** da tela e do servidor. Coluna fica no banco até migration futura. | Com Departamento obrigatório e Gestores por departamento, dois lugares dizendo "a quem responde" divergiriam. |
| U3 | Desativar um Gestor mantinha a liderança: departamento parecia atendido; reativar devolvia gestor vendo tudo. | **Desativar tira as lideranças**, o que o rebaixa a Operador pela regra; reativar volta como Operador. | Gestor que não entra no portal não libera nada. "Reativação do zero" é o que o glossário já promete. |
| U4 | Rota `DELETE /api/users/{id}` existia sem botão, e tokens/logs de instalação apontam para o usuário sem regra de exclusão. | **Rota removida.** Desativar é o caminho. | Apagar perderia a trilha de quem instalou o quê. |
| U5 | Importação por CSV contava "ignoradas" sem dizer quais. | **Listar as ignoradas com motivo** ("já existe", "campo vazio: …"), junto dos erros. | Quem importa 40 linhas e lê "3 ignoradas" abre a planilha para adivinhar. |
| U6 | "Pessoas" do departamento contava ativos e inativos; decidia o aviso ao apagar. | **Contar só ativos**, inativos à parte. | A pergunta da coluna é "quem fica sem gestor se eu apagar". |

### Defeitos corrigidos

- "setor" (4 textos) e "líderes" (2 mensagens do servidor) → departamento, gestores.
- Lead prometia "remova membros"; não há remover. Texto diz que quem sai é desativado.
- Erro de carregamento nas abas Usuários e Departamentos era silencioso (só console). Agora aparece na tabela com "Recarregar".
- Ao salvar os gestores de um departamento ou apagar um departamento, o servidor devolvia quem mudou de papel e a tela ignorava. Agora anuncia: "X virou gestor" / "X voltou a operador, com a carteira vazia".
- Modal de senha dizia "a sessão aberta dela não cai"; o servidor carimba `senha_alterada_em` e derruba. O código está certo; o texto foi corrigido.
- Aba Níveis de acesso mostrava Usuários como "ainda não governado por esta tela"; agora diz "só o administrador: aqui se nomeiam gestores e administradores".

### Fica como está (visto, sem mudança)

- A rota HTML `/usuarios` continua sem guarda no servidor; quem barra é a API e o redirecionamento no JS. Todas as outras páginas seguem o mesmo padrão; revisar junto na página Login.
- Filtro de status padrão "Ativo" faz o estado vazio dizer "Nada encontrado com esses filtros" mesmo sem filtro escolhido. Aceitável: o link "Limpar filtros" resolve.
- `inicio` não é governado pela matriz (todo papel vê o Início).

### Aba Níveis de acesso (decisões N1 a N3)

| # | Pergunta | Decisão | Motivo |
|---|----------|---------|--------|
| N1 | Separar "apagar" de "editar"? | **Não.** | Sob a matriz só há dois DELETE (tirar documento da carteira; tirar certificado da custódia), e os dois desfazem uma inclusão do mesmo módulo. Quem pode atribuir e não pode retirar deixaria erros sem conserto. |
| N2 | Permissão por usuário? | **Não.** Continua por papel. | Com três papéis e departamentos, cada exceção pessoal vira uma investigação. A pendência existia desde agosto e ninguém precisou. Se precisar: papel novo ou revisão do padrão do papel. |
| N3 | Início fora da matriz? | **Fica.** Texto da linha passa a "todos os papéis entram: é a tela de instalação". | É a tela de instalação; todo papel entra. |

Fecha a §5 do `PLANO_niveis_de_acesso.md`.

### Testes

`tests/test_pagina_usuarios.py` cobre U2 a U6, vocabulário e estados; `tests/test_permissoes.py` cobre U1.

---

## 2. Carteiras (01/10/2026)

**Para que existe**: definir o Alcance de cada pessoa sobre os Clientes — as
Atribuições de um Operador e as Exceções de um Gestor.

**Quem vê**: pela matriz (`carteiras`: Gestor edita, Operador não entra) e pela
liderança (`require_admin_ou_gestor`). O Gestor só edita Operadores dos
departamentos que lidera; o Administrador edita qualquer carteira, inclusive as
Exceções dos Gestores. A rota HTML não tem guarda (padrão de todas as páginas,
a rever em Login).

### Decisões

| # | Pergunta | Decisão | Motivo |
|---|----------|---------|--------|
| C1 | Botões "Liberar"/"Remover" para todo alvo. | **Pelo glossário**: Atribuir/Retirar (Operador); Devolver/Retirar (Gestor). Textos, toasts e confirmações acompanham. | "Liberar" é o verbo da era em que o gestor liberava tudo para todos. "Atribuir" é o que o modelo faz e o que a trilha já grava. |
| C2 | "Cliente" na tela vs Documento no glossário. | **"Cliente" fica na tela** para o titular. Glossário ganha a entrada Cliente e distingue da chave. | Quem opera pensa em cliente, não em CNPJ. |
| C3 | Histórico de instalações só para administrador. | **Gestor vê as instalações dos Operadores dos departamentos que lidera**, por `GET /api/carteira/{id}/instalacoes`, com o alcance da carteira; IP só para o administrador. | A pergunta "o fulano instalou o que eu atribuí?" é do Gestor. |
| C4 | Atribuir um não confirma; lote e retirar confirmam. | **Fica.** | Retirar tira acesso; atribuir um é desfazível em um clique. |
| C5 | Dashboard contava "sem carteira" com outro critério. | **Alinhado ao de Carteiras**: só Operadores ativos; linha de carteira de inativo ou ex-operador não conta. | Dois números diferentes para a mesma pergunta. |

### Defeitos corrigidos

- Universo oferecido ao Gestor não era recortado pelas Exceções dele: selecionava o que receberia 403, e "Todos" falhava inteiro. Agora `/api/carteira/documentos` devolve só o alcance de quem pergunta.
- Atribuir e registrar Exceção pela tela não validavam inventário (a planilha validava). Agora 422 "Fora do inventário". Retirar atribuição de documento que saiu do inventário continua livre.
- Planilha aceitava atribuir a conta inativa. Linha recusada com motivo.
- Administrador aberto por `?operador=<id>` mostrava carteira de Atribuições. Agora 422: alcance total, sem carteira.
- Badges "Gestor" e "Conta inativa" sumiam do cabeçalho depois de atribuir ou retirar.
- Exceção de documento fora do inventário contava em "menos N exceções" mas não aparecia no painel; agora aparece marcada "fora do inventário atual".
- Resumo "N operadores" da tela contava gestores; passa a usar o resumo do servidor.
- Gestor inativo aparecia como "carteira a limpar" porque `documentos` dele é o inventário; o critério passou a ser as exceções.
- Texto do modal de importação falava de "departamentos que você lidera" ao administrador; agora por papel.
- Mensagens do servidor com "liberar" (porta de Carteiras, departamento obrigatório, fora do alcance) → "atribuir".
- Variáveis mortas (`souAdmin`) e comentários desatualizados sobre rolagem (template e CSS).

### Fica como está

- Card da lista chama-se "Pessoas" para o administrador (vê gestores e operadores); o resumo do servidor conta só Operadores.
- Documento atribuído que saiu do inventário continua na carteira, marcado; é decisão antiga e certa (a atribuição é uma decisão, e sumir com ela esconderia acesso a algo que pode voltar).
- `atribuidos` da planilha conta linhas enviadas ao upsert, inclusive as que já existiam. Pequeno; anotado.

### Testes

`tests/test_pagina_carteiras.py`.

---

## 3. Início (01/10/2026)

**Para que existe**: ver os Certificados dos Clientes no Alcance e instalá-los
na Estação da pessoa, em três toques (selecionar, marcar, instalar).

**Quem vê**: todo papel (o módulo `inicio` fica fora da matriz, decisão N3). O
recorte é do servidor: Administrador tudo, Gestor tudo menos Exceções,
Operador as Atribuições. Item sem documento só aparece ao Administrador.

### Decisões

| # | Pergunta | Decisão | Motivo |
|---|----------|---------|--------|
| I1 | Vencidos na lista sem filtro nem KPI; Total ≠ Ativo + Expirando. | **Vencidos saem do Início** (`ocultar_vencidos`), com "N vencidos não listados — ver Vencidos" na linha de status. | Vencido não se instala e tem página própria. |
| I2 | Instalação ia para a primeira estação da pessoa, em silêncio; texto "nesta máquina". | **Uma Estação por pessoa: a atual** (agente vivo) é a padrão. Textos passam a nomear a estação. Glossário ganha Estação. | É assim que a operação funciona: cada pessoa num computador. |
| I3 | Seção "Meus computadores" lia tabela dormente e nunca aparecia; duas fontes de "estação". | **Removida.** Estações são do Hardlyze. | Duas fontes de estação foi o que gerou o defeito da instalabilidade. |
| I4 | Sino: expirando/vencidos pela seleção de Acompanhamento; novos pelo Alcance. | **Mantido.** O sino é preferência de aviso, não acesso. A seleção fica dentro do Alcance (a conferir em Acompanhamento). | Gestor com 400 clientes não quer 400 avisos. |
| I5 | Sino dependia do módulo Acompanhamento na matriz. | **Sino sempre disponível** a quem está logado (`require_auth`); só a página Acompanhamento segue a matriz. | O sino está em toda página. |

### Defeitos corrigidos

- **Instalabilidade consultada com a máquina do snapshot** (o servidor da varredura), não com a Estação da pessoa. Para Operador e Gestor, o vínculo pessoa↔estação era conferido contra o servidor e dava 403, que a tela mostrava como "não foi possível verificar". A rota ganhou `estacao` (destino) separado de `machine_id` (origem do inventário e do cofre); sem `estacao`, confere como antes.
- Operador sem Atribuição via "O agente ainda não enviou dados". Agora `alcance_vazio` e "Sua carteira está vazia… peça ao gestor do seu departamento".
- "Abrir Configuração" oferecido a quem não é administrador.
- Estação indisponível tinha um texto para três motivos (ponte não configurada, Hardlyze fora, sem agente vivo); agora um por motivo.
- Desfecho "desconhecido" do acompanhamento sem texto; "Nao foi possivel"/"instalacao" sem acento; "Planilha (Excel)" que gera CSV; lead "das suas empresas".
- Comentários sobre o download do .exe (que saiu em 23/08) em `main.py`, `config.py` e no template; "líder/setores" em `cert_installer.py`, `novos_certificados.py`, `notification_service.py`.

### Fica como está

- A tela não ramifica por papel; toda diferença é do servidor. Certo: a tela não é barreira.
- Exportação com teto de 5000 e aviso antes de exportar.
- "Selecionar todos" marca só a página atual, com teto de 50 por pedido.
- `/api/cert-installer/available` não é usada pelo Início (é do Instalador).

### Pendências para outras páginas

- Acompanhamento: garantir que a seleção fique dentro do Alcance (I4).
- Login: a rota HTML de toda página é sem guarda no servidor; a barreira é a API e o redirecionamento no JS.

### Testes

`tests/test_pagina_inicio.py`.

---

## 4. Instalador (01/10/2026)

**Para que existe**: diagnóstico do Cofre e das chaves de cifragem, Custódia
dos Certificados por servidor da varredura, trilha de instalações e a
configuração do pedido de instalação. Não instala (o Início instala).

**Quem vê**: só o Administrador (decisão P1). O módulo saiu da matriz, como
Usuários. O agente continua lendo a lista de custódia pela chave de API.

### Decisões

| # | Pergunta | Decisão | Motivo |
|---|----------|---------|--------|
| P1 | Matriz permitia dar Instalador a Gestor; menu aparecia; tela expulsava; escritas exigiam admin. | **Só Administrador** (`MODULOS_SO_ADMIN`). | Cofre, chaves e custódia são operação do portal. A trilha do Gestor mora em Carteiras (C3). |
| P2 | `available`, `logs` e `cleanup` sem chamador. | **Removidas.** | Rota que ninguém chama é superfície sem dono. O agente usa `claim`/`report`. |
| P3 | "Expurgar trilha" também expurgava atividade dos usuários e o cofre; a prévia contava só a trilha. | **O botão expurga só a trilha.** Atividade e cofre seguem no job diário (`cron_alerts`). | Surpresa num lugar onde surpresa custa caro. |

### Defeitos corrigidos

- Vencidos e ilegíveis apareciam na Custódia como "Desativada" com "Reativar" (que apagava um bloqueio inexistente). Agora "Fora da custódia · vencido/ilegível", sem botão.
- Etapa em que a instalação parou nunca ganhava a marca de falha (as duas ramificações davam a mesma classe).
- "link de instalação enviado por e-mail": não há link nem e-mail; o pedido vai ao agente. A validade devolvida pelo pedido passa a ser a configurada na tela, não o padrão do ambiente.
- Trilha cortava em 1000 eventos sem avisar; agora `truncado` e o aviso no resumo.
- "Retenção do log" → "Retenção da trilha"; "Ver últimos 90 dias" só quando o período é menor; cofre indisponível mostra o motivo, não "HTTP 503".
- Vocabulário: "Máquina" → "Estação" (coluna da trilha) e "Servidor" (badge e rodapé da custódia); o 422 do `vault-optin` fala de servidor da varredura.
- Docstrings sobre binário, assinatura, Vercel e "oitava tela"; CSS órfão.

### Fica como está

- Reativar custódia sem confirmação (reversível). Recifrar sem confirmação (linha que não decifra fica intocada).
- Nomes de variáveis de ambiente nos problemas do diagnóstico: é tela de administrador e o nome é a ação.
- Retenção sem máximo.

### Testes

`tests/test_pagina_instalador.py`.

---

## 5. Acompanhamento (01/10/2026)

**Para que existe**: a pessoa escolhe, dentro do seu Alcance, quais Clientes
quer acompanhar e como quer ser avisada por e-mail. O sino e o e-mail de
vencimento seguem essa seleção.

**Quem vê**: pela matriz (`acompanhamento`: Gestor e Operador com "editar" por
padrão; "Só ver" acompanha sem escolher). O sino não depende do módulo (I5).

### Decisões

| # | Pergunta | Decisão | Motivo |
|---|----------|---------|--------|
| I4 (fechado) | Seleção gravada sem recorte; sobrevivia a Exceção, Atribuição retirada e troca de Papel. | **Recortada pelo Alcance ao gravar e ao ler**: painel, sino e job de e-mail. A linha não é apagada: se o Alcance voltar, a escolha volta (preferência, não acesso). | É o que I4 prometia; o ADR vale para acesso, a seleção é preferência. |
| A1 | Painel por Cliente (certificado vigente); sino e e-mail por arquivo. Cliente renovado "venceu" no sino. | **Um aviso por Cliente, pelo certificado vigente** (`app/vigencia.py`), no sino e no e-mail, para todo papel. | Aviso de certificado já substituído ensina a ignorar o sino. |
| A2 | E-mail de clientes novos ignorava "Quero receber aviso". | **A preferência vale para todo e-mail pessoal.** Administradores e lista fixa continuam. | Caixa que não desliga o que diz desligar. |
| A3 | KPIs mudavam com a busca. | **KPIs fixos**; a busca filtra só a tabela. | KPI que muda ao digitar vira contagem do filtro. |
| A4 | Administrador vê só a própria seleção no painel; sino dele vê tudo; sem visão por pessoa. | **Mantido** (sem resposta; recomendação). | Decisão de 20/08 continua boa; não há pergunta de negócio por trás da visão alheia. |

### Defeitos corrigidos

- Preferência de quem não tinha linha de seleção dizia "salva" e não gravava (UPDATE sem linha). Agora a linha nasce com seleção vazia.
- Aba Escolher: alcance vazio e erro tinham a mesma mensagem. Agora "Nenhum cliente atribuído a você" e erro com "Tentar de novo" (`alcance_vazio` na resposta das opções).
- "Só ver" mostrava os botões Salvar ativos e falhava com 403 ao clicar; agora desabilitados com o motivo.
- "Empresa" nos cabeçalhos e "das suas empresas" → Cliente.
- Texto "no dia do vencimento" (o aviso sai quando vence) → "quando vencer".
- 403 da matriz sem acento, em todo o portal.
- "Ver instalações" do Dashboard apontava para Acompanhamento; agora para a trilha do Instalador.
- Comentários: PUT "em ler" (exige editar), docstring de "lidas" citando o módulo, "item 56", "500 certificados em 21 páginas".

### Fica como está

- Sem teto de quantidade na seleção; sem conferência de que o documento existe no inventário (a tela só oferece os do Alcance, e o painel marca "Não encontrado no inventário atual").
- Vencidos sempre avisam, independente dos marcos dispensados; só o opt-in desliga.

### Testes

`tests/test_pagina_acompanhamento.py`.

---

## 6. Dashboard, Histórico, Vencidos e Duplicidades (01/10/2026)

**Para que existem**: consulta. Dashboard é a saúde do portal (acervo, agente,
acesso, instalações, cofre, alertas, atividade); Histórico é o registro por
arquivo com a última verificação; Vencidos lista os Clientes com certificado
vigente vencido; Duplicidades aponta arquivos repetidos na pasta.

**Quem vê**: Dashboard só o Administrador (D2). Histórico, Vencidos e
Duplicidades pela matriz ("ler" para Gestor e Operador por padrão), todos
recortados pelo Alcance — Duplicidades passou a ser.

### Decisões

| # | Pergunta | Decisão | Motivo |
|---|----------|---------|--------|
| D1 | Três números para "vencido": Dashboard (todo arquivo do histórico, sem recorte), Vencidos (por arquivo, status ou data, recortado) e Início/sino (cliente vigente). | **Vencido é o Cliente cujo certificado vigente venceu, no inventário atual.** Vencidos e o card do Dashboard contam assim; cliente renovado sai; arquivo que saiu da pasta sai. | A pergunta operacional é "quem está vencido agora". Arquivo antigo de cliente renovado é assunto de Duplicidades. |
| D2 | Dashboard na matriz: "ler" a Gestor mostraria agregados do portal inteiro, sem recorte. | **Só Administrador** (`MODULOS_SO_ADMIN`). | Os cards são do portal; recortá-los não faz sentido para a maioria. |
| D3 | Histórico por arquivo, cliente renovado em várias linhas. | **Mantido por arquivo**, com a coluna Status que o servidor já mandava. | "Última verificação" é atributo do arquivo. |

### Defeitos corrigidos

- **Duplicidades não recortava pelo Alcance**: operador com carteira vazia via nome, CNPJ, serial e fingerprint de todo o inventário. Agora recorta; o cache vale só para quem tem alcance total.
- Histórico e Vencidos: carteira vazia tinha a mesma mensagem de "sem histórico"/"nenhum vencido" (`alcance_vazio`); "Atualizado em" ficava vazio (`atualizado_em` passa a vir, do snapshot); busca por CNPJ só com dígitos não achava (entra `documento_numero`).
- 403 da matriz com a chave crua ("a historico"); agora com rótulo e artigo ("ao Histórico"), em `permissoes.ROTULO_MODULO`.
- Dashboard: faixas "8 a 30 dias" cobriam 7 a 29 (agora fechadas como os rótulos); "Ver vencidos" num card cujo número é "vence em 30 dias" (agora "Ver os que vencem em 30 dias" → Início filtrado, e "Ver vencidos" como segundo link; o Início aceita `?status=`); "Ver arquivos com erro" e "Ver varreduras" levavam ao Histórico, que não tem nem um nem outro (saíram); erro na primeira carga deixava os cards em "Carregando…"; ponto duplo no erro; Instalações cortava em 1000 eventos sem avisar; "máquina(s) em dia".
- "Planilha (Excel)" gera CSV (Histórico, Vencidos); "Empresa" e "das suas empresas" (Vencidos, Duplicidades); "snapshots" no vazio do Histórico; placeholder com "arquivo".
- Duplicidades: "Tente de novo em instantes" para 403 e 413; 429 dizia "análise em curso" quando é limite por pessoa; "Copiar caminho" copiava só o nome para quem não é administrador (agora "Copiar nome").
- Vencidos: gráfico por ano omitia vencidos sem data sem dizer; nota com a contagem.
- Comentários: chave `file_name`, "outros seis", "Quinta tela".

### Fica como está

- Cofre e Agente no Dashboard misturam/listam por servidor da varredura; há um só em produção.
- Renovações comparam só o servidor ANALISESRV (parâmetro fixo na tela).
- Histórico sem deep link; a busca não vai para a URL.

### Testes

`tests/test_pagina_consulta.py`.

---

## 7. Configuração e Login / sessão (02/10/2026)

**Para que existem**: Configuração é a operação do portal (pastas e agente,
SMTP e alertas, comandos remotos). Login é a porta: entrar, sair, trocar a
senha provisória, recuperar a senha por código.

**Quem vê**: Configuração só o Administrador (L1); o agente lê `/api/settings`
pela chave de API. Login é público.

### Decisões

| # | Pergunta | Decisão | Motivo |
|---|----------|---------|--------|
| L1 | Matriz oferecia Configuração a Gestor; tela expulsava; comandos exigiam admin. | **Só Administrador** (`MODULOS_SO_ADMIN`). | Pastas, SMTP, chave e comandos são operação do portal. |
| L2 | Toda página entregava o HTML inteiro e só expulsava no primeiro 401 da API. | **Checagem de token ao carregar** (`exigirSessao` em ui-common.js) com `/login?next=…` e volta à origem. O servidor segue sem guarda nas rotas HTML: o token vive no `localStorage` e não há dado sensível no HTML. Cookie `HttpOnly` fica como possível ADR futuro. | Ganho imediato com custo baixo; a migração de sessão é projeto à parte. |
| L3 | "Fonte dos dados" (auto/remoto/local) e "URL do portal para o agente" só no navegador do administrador. | **Fonte sempre "auto"**; seletor removido. A URL fica só como entrada do `agent_config.json`, rotulada assim. | Configuração que vale para um navegador é surpresa. |
| L4 | "Disparar agora" dizia "resumo" e mandava também os e-mails pessoais; toast contava só os pessoais. | **Dispara tudo, com texto e toast honestos** ("N e-mails pessoais, M resumos"; aviso quando os alertas estão desligados). | É o mesmo envio do horário. |

### Defeitos corrigidos

- Senha mínima: tela dizia 6 (login e modal de troca), servidor exige 12.
- "Sair" com senha provisória não revogava a sessão (`/api/logout` caía no 403 da senha provisória). Entrou na lista de rotas permitidas.
- Remetente SMTP sem validação de formato; agora 422.
- Prévia do e-mail não usava o certificado vigente (A1); agora usa.
- Configuração tratava 401 como "exige administrador" e não tratava 403; agora 403 tem texto próprio e 422/429 do teste de SMTP não ganham o prefixo "recusou".
- Porta SMTP aceitava 1 a 65535 na tela e só 25/465/587/2525 no servidor; agora a tela diz e sugere as quatro.
- "Banco de dados desconectado" quando a leitura de saúde falhava por outro motivo; agora "não verificado".
- Gate de administrador desigual (Usuários e Configuração com aviso, Instalador sem, Dashboard sem) → `data-so-admin` no `<body>` e um gate só em ui-common.js.
- Login: 422 aparecia como "[object Object]"; mensagem de sucesso da redefinição sumia ao voltar à tela de login; emojis; fonte remota do Google (as outras páginas usam fonte local); "Sessão encerrada. Entre novamente." nunca aparecia (agora chega ao login via sessionStorage); `next` após o login.
- "O aviso no dia do vencimento é sempre enviado" → "de que venceu"; "colaborador" e "Máquina alvo" → vocabulário do glossário; "Abrir Configuração" do Início abre na aba Pastas.
- Mensagens sem acento nas permissões; código morto do login por Supabase Auth (`_conta_local_do_email`); comentários Vercel/Render/Supabase em mensagens e docstrings; "três itens" (são cinco); "aguarda print".

### Fica como está

- Rotas HTML sem guarda no servidor (ver L2).
- Login sem tema salvo (não carrega ui-common.js); CSP com nonce por script.
- Intervalo de verificação de alertas oferecido em quatro valores (o servidor aceita 1 a 720 h).
- Fusão de pastas do banco com SMTP do arquivo local em `load_settings` quando o banco tem pastas vazias (comportamento de transição documentado no código).

### Testes

`tests/test_pagina_config_login.py`.

---

## Encerramento (02/10/2026)

As onze páginas foram revistas: Usuários (com Níveis de acesso), Carteiras,
Início, Instalador, Acompanhamento, Dashboard, Histórico, Vencidos,
Duplicidades, Configuração e Login. Todas as decisões estão nas tabelas acima;
os defeitos corrigidos têm teste em `tests/test_pagina_*.py`. Pendências que
saíram desta revisão como possíveis trabalhos futuros: sessão em cookie
`HttpOnly` com guarda das rotas HTML no servidor (L2); permissão por usuário
(N2, decidido não fazer).
