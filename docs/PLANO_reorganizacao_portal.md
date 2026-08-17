# Plano — reorganização do portal: Início, Dashboard, Instalador e gestão

> **Status: TODAS as etapas (0 a 5) aplicadas em 2026-08-15.**
> Modelo de custódia e carteira definido pelo cliente em 15/08 — ver §3.
> Elaborado em 2026-08-15. Todos os números deste documento foram medidos
> contra o banco de produção na data, não estimados.

---

## 0. O que a medição mostrou antes de qualquer decisão

Cinco fatos apurados no banco e no código que **contradizem ou limitam** partes
do pedido original. Eles vêm primeiro porque mudam o escopo, não porque são
detalhe de implementação.

### 0.1 "Tempo de uso do portal por usuário" não tem dado nenhum hoje

Não é questão de agregar melhor — **a instrumentação não existe**:

- `/api/login` (`app/main.py:533`) devolve o token e **não grava nada**
- `users` não tem `last_login`, `last_seen` nem equivalente
- não há tabela de sessão; o JWT é stateless com 24h (`auth.py:11`)
- não há log de navegação, nem de requisição por usuário

E, mesmo instrumentado, **"tempo de uso" é a métrica errada para este portal**.
A tarefa do usuário final dura menos de um minuto: entrar, achar o certificado,
baixar o `.exe`. Tempo de sessão alto aqui não significa engajamento — significa
que a pessoa **não achou o que queria**. Otimizar para o número subir é otimizar
para a ferramenta piorar.

Soma-se o peso de LGPD: o projeto já tem `20260517193000_rls_lgpd.sql`, e
`install_log` já guarda `client_ip` por usuário, sem política de expurgo.
Cronometrar presença de funcionário é exatamente o tipo de coleta que precisa de
justificativa, e aqui ela não existe.

**Contraproposta (§5.3):** medir **atividade**, não permanência. Última
atividade, ações no período, taxa de conclusão por usuário. Responde a pergunta
real — *quem está usando e quem travou?* — com evento discreto em vez de
cronômetro, e alimenta direto a etapa de gestor/operador.

### 0.2 `cert_history` não é histórico

O nome engana. A gravação é `upsert(on_conflict="file_name")`: **uma linha por
arquivo, com o estado atual**. As 1.029 linhas são ~1.029 arquivos, não 1.029
eventos ao longo do tempo. Quem construir "certificados renovados" em cima dela
obtém zero, porque o valor anterior foi sobrescrito.

**O histórico real é `cert_snapshots`:** 317 varreduras entre 24/04 e 15/08, cada
uma com a lista completa de certificados (`items`, 560 no último snapshot, com
`fingerprint_sha256`, `not_before`, `not_after`, `documento_numero`, `status`).
É de lá que sai renovação, tendência e saúde do agente.

### 0.3 O `.exe` é propositalmente idêntico em todo download

`app/main.py:2462` é explícito: o binário não é recompilado por download, e isso
é **decisão de segurança, não preguiça** — é o que permite assiná-lo uma vez e
acumular reputação no SmartScreen. Um executável inédito a cada clique dispara
"aplicativo não reconhecido" justamente no fluxo que deveria ser de um clique.

Consequência direta para o painel de configuração pedido:

| Pedido | Realidade |
|---|---|
| **ícone do exe** | assado em build (`Instalar_Certificado.spec:81` → `ico/icone.ico`). Trocar exige **recompilar e reassinar**. Não é configuração de runtime. |
| **nome do configurável** | **já existe** — `?nome=` (`main.py:2463`), sanitizado para `[A-Za-z0-9 _-]`, 60 chars. Dá para virar template configurável. |

### 0.4 A sidebar está copiada em 8 templates

Não há `{% extends %}`, `{% include %}` nem `{% block %}` em `templates/`. Oito
dos nove arquivos têm cada um sua cópia do `<nav class="sidebar-nav">` — o
`login.html` não tem menu, e é a única exceção legítima.

Renomear *Dashboard* → *Início* e acrescentar um *Dashboard* novo = editar 8
arquivos. A etapa de gestor/operador acrescenta mais itens = 8 de novo. **É por
isso que a seção 1 é pré-requisito, não arrumação opcional.**

### 0.5 Achado colateral: login com senha errada devolve 500

Confirmado contra produção:

```
POST /api/login  {"email":"...invalido","password":"x"}
→ HTTP 500  {"detail":"401: E-mail ou senha incorretos."}
```

O `except Exception as e` de `main.py:551` engole o próprio
`HTTPException(401)` levantado três linhas acima e o reembala como 500. A
mensagem certa chega com o status errado — e todo tratamento de erro no front
que olhe o código vê "erro do servidor" onde houve credencial inválida.

Fora do escopo do pedido, mas **a etapa 5 constrói hierarquia em cima deste
mesmo handler**. Consertar antes custa uma linha; depois, custa rever o que já
foi construído em cima.

---

## 1. Etapa 0 — Sidebar em partial ✅ *(aplicada em 2026-08-15)*

Sem isto, toda etapa seguinte pagaria pedágio de 8 arquivos.

- `templates/_sidebar.html` com a navegação única
- cada página passa `pagina_ativa` no contexto; o partial marca o `class="active"`
- os itens `display:none` de admin (`nav-installer`, `nav-users`, `nav-config`)
  continuam como estão — a decisão de visibilidade é do JS, não do servidor
- `tests/test_sidebar_partial.py`, 14 testes

**O risco de divergência foi verificado antes de extrair, não presumido.** As 8
cópias tinham **o mesmo SHA-256** depois de normalizar espaços e o marcador de
página atual: mesmos itens, mesmos rótulos, mesma ordem, mesmos ícones. Nenhuma
havia divergido *ainda* — o custo era o próximo item, não um estrago já feito.

**Verificação de equivalência:** cada uma das 8 páginas foi renderizada e o menu
comparado com o do `HEAD`. Idênticos em todas. O refactor não muda um pixel.

**Sobre os testes:** as quatro mutações abaixo foram aplicadas e todas derrubaram
a suíte — o arquivo não é decorativo.

| Mutação | Detectada por |
|---|---|
| template volta a copiar a sidebar | `test_apenas_o_partial_declara_a_navegacao` |
| `pagina_ativa` com erro de digitação | `test_rota_acende_exatamente_o_seu_item` |
| marcador `active` fixo sobrevive no partial | `test_partial_nao_tem_marcador_fixo` |
| página nova sem `pagina_ativa` | `test_todas_as_rotas_de_pagina_estao_cobertas` |

A última é a que importa para as etapas seguintes: uma rota nova que esqueça a
chave **não levanta exceção** — o menu só renderiza sem nada aceso. O teste varre
as rotas HTML declaradas na aplicação e exige que cada uma esteja coberta, em vez
de confiar numa lista escrita à mão.

---

## 2. Etapa 1 — `Dashboard` → `Início` ✅ *(aplicada em 2026-08-15)*

- **A rota `/` não mudou.** Renomear a URL quebraria favoritos e o link interno
  da tela de configuração.
- Rótulo trocado no partial (um arquivo, graças à etapa 0). Além dele, só havia
  **um** texto visível citando o nome — a mensagem "Volte ao Dashboard e atualize
  a tabela" em `configuracao.html`.
- Três **comentários de código** que nomeavam a página também foram atualizados.
  Não é cosmética: quando o Dashboard de verdade existir (etapa 4), um comentário
  dizendo "modelo Dashboard/Histórico/Vencidos" vai apontar para a página errada.
- **`LS_PER_PAGE_DASH = "cg_per_page_dashboard"` foi preservada**, e agora há
  teste que falha se alguém a renomear junto com o rótulo. É chave de
  `localStorage`: mudá-la descartaria a preferência de itens por página de todo
  usuário existente — sem aviso e sem erro, porque ler chave inexistente devolve
  `null` e a tela cai no padrão. Nome interno e rótulo não precisam concordar.

**Decisão que o pedido não continha: o ícone.** O item de `/` usava a grade 2×2,
que é o ícone canônico de *dashboard*. Mantê-lo em "Início" deixaria o menu
dizendo "dashboard" em desenho enquanto diz "Início" em texto — e, pior, o
Dashboard da etapa 4 chegaria sem o ícone que é dele. Trocado por uma casa; a
grade fica reservada.

**Crítica que permanece em aberto para a etapa 4:** "Início" e "Dashboard" lado a
lado prometem os dois "a visão geral". A distinção tem de ficar clara na ordem e
no ícone — **Início = operação** (é onde se faz), **Dashboard = análise** (é onde
se olha). Se ficar confuso na tela, o problema não será o rótulo: será ter duas
páginas competindo pelo mesmo papel.

---

## 3. Etapa 2 — Custódia, carteira e a seleção no Início

> **Revisto em 2026-08-15** depois da definição do modelo pelo cliente. A versão
> anterior desta seção supunha que o opt-in continuaria como está; não continua.

### 3.1 Um flag hoje decide duas coisas diferentes

`cert_vault_optin` responde, com um único registro, a duas perguntas que têm
donos, defaults e riscos distintos:

| Pergunta | Quem decide | Default definido |
|---|---|---|
| **Custódia** — o PFX sai do ANALISESRV e fica guardado no servidor? | admin | **ligado**, admin desativa pontualmente |
| **Acesso** — quem pode instalar este certificado? | gestor | **desligado**, gestor concede por carteira |

Separar as duas é o que torna o modelo pedido coerente. Enquanto forem o mesmo
flag, "liberar para o operador instalar" e "copiar a chave privada para a nuvem"
são o mesmo clique — e não deveriam ser.

### 3.2 Custódia: o opt-in vira opt-out

Hoje o cofre tem 33 de 560 (**6%**), porque cada certificado exige autorização
explícita. Passa a ser o contrário: entra por padrão, o admin desativa o que não
quer.

**Isto inverte uma decisão tomada de propósito**, e há dois efeitos a tratar —
nenhum deles é armazenamento (560 PFX ≈ **5,7 MB**; não é problema).

#### (a) A falha precisa continuar fechando — e ela inverte sozinha

`listar_optin_fingerprints` devolve lista vazia quando a consulta falha, e o
código diz por quê: *"Falha fechada: na dúvida, não copiar chave privada para o
servidor."*

No modelo invertido, a tradução ingênua é consultar os **desativados** — e aí
lista vazia por erro passa a significar **"nada foi desativado, mande tudo"**. É
fail-closed virando fail-open numa mudança de três linhas que parece inofensiva,
e o sintoma é o oposto de um erro: tudo funciona, e chaves demais sobem.

**Requisito estrutural, não convenção:** a resposta precisa carregar a afirmação
de completude — algo como `{"modo": "opt-out", "desativados": [...]}` — e o
agente recusa enviar quando não conseguiu obtê-la. Distinguir *"nenhum
desativado"* de *"não consegui saber"* é a coisa toda.

#### (b) O raio de exposição vai de 33 para ~490 chaves privadas

São certificados ICP-Brasil de **clientes** do escritório, não do escritório.
Um vazamento de banco somado à chave de cifragem deixa de comprometer 33
assinaturas juridicamente válidas e passa a comprometer quase quinhentas.
Mitigações, em ordem de custo-benefício:

1. **Não guardar o que não instala.** Do inventário atual: 16 vencidos, 21 com
   erro de leitura, 31 fora do padrão — **68 certificados** que são passivo puro,
   sem utilidade nenhuma. "Tudo por padrão" deve significar **todo certificado
   válido e legível**, não todo arquivo da pasta.
2. **Expurgo por vencimento** ✅ *(aplicado em 16/08)*. Certificado que venceu
   sai do cofre; sem isso o acervo só crescia, e crescia em chave privada.
   Confirmado antes de implementar: dois certificados vencidos em 15/08 seguiam
   guardados no dia seguinte.

   Junto veio o segundo gatilho — **removido da pasta** —, e ele tem risco
   oposto. Vencido é seguro (a data está na própria linha). Ausência no
   inventário **não é**: uma varredura que falhe pela metade apagaria chaves em
   massa, que é a armadilha de falha-aberta da §3.2a na direção destrutiva.

   Daí três guardas e um prazo de carência (`ausente_desde`): só age sobre
   varredura de menos de 36h, recusa inventário vazio (pasta inacessível
   reporta zero **sem erro**), recusa queda de mais de 30% entre varreduras
   seguidas, e a ausência precisa persistir 3 dias. Reaparecer zera o relógio.
   O expurgo relata o que fez **e o que se recusou a fazer, com o motivo** —
   recusar em silêncio seria indistinguível de estar quebrado.
3. As chaves distintas para PFX e senha já existem (feito em 11/08).

#### (c) O painel de desativação é do admin, e fica na configuração

É a inversão do "Passo 1" atual, e continua fora do Início: desativar custódia é
decisão de segurança, não rotina de operação (§4.8).

#### (d) Consequência de volume, aplicada mas não resolvida

O agente reenvia **tudo o que está autorizado a cada ciclo** — não há verificação
de "já está no cofre e não mudou". Com 33 certificados isso era invisível; com
~490 passam a ser ~490 requisições e ~5,7 MB por varredura, todo dia, contra uma
função serverless. Não quebra nada hoje, mas é desperdício de 15× e merece uma
etapa própria: o agente pular o que já está gravado com o mesmo fingerprint.

### 3.3 Acesso: a carteira

**Já existe meia implementação.** `colaborador_cert_selecoes` (`user_email` →
lista de documentos) é exatamente uma carteira — hoje usada para decidir quem
recebe alerta de qual certificado. O conceito já está validado no produto; falta
aplicá-lo a instalação.

**Granularidade: documento (CNPJ/CPF)**, como já é nos alertas. O universo atual
é de **488 documentos distintos** entre 508 certificados que têm documento.

**Decisões tomadas pelo cliente em 15/08:**

| Decisão | Escolha | Consequência a mitigar |
|---|---|---|
| Alcance do gestor | pode atribuir **qualquer** cliente do acervo | conta de gestor comprometida alcança tudo → **trilha obrigatória** de quem atribuiu o quê, a quem e quando |
| Visão do operador | **vê todos**, instala só os da carteira | a relação de clientes do escritório fica visível a todo operador; se isso incomodar depois, mascarar o documento das linhas bloqueadas resolve sem mudar o modelo |

**Os 52 certificados sem documento** não podem ser atribuídos por CNPJ. Precisam
de regra explícita — a mais simples é mantê-los acessíveis só a admin, já que
sem documento não há como saber de quem são.

**Tabela nova, não estender a existente.** `colaborador_cert_selecoes` está
chaveada por `user_email` (e-mail muda, e a liberação se desprenderia da pessoa
em silêncio) e serve a outro propósito — receber alerta não é o mesmo que poder
instalar. A carteira nova nasce por `user_id`, com `atribuido_por` e
`atribuido_em` para a trilha exigida acima.

### 3.4 A tela do Início

O problema original desta etapa — *560 listados, 33 instaláveis* — **muda de
natureza, não desaparece**. Com o opt-out, quase tudo estará no cofre; o filtro
que passa a mandar é a carteira. E como o operador vê todos, a lista continua
tendo linhas que ele não pode instalar.

1. **Estado de instalabilidade por linha**, agora com motivos diferentes: *fora
   da sua carteira* (o caso comum), *custódia desativada pelo admin*, *ainda não
   enviado pelo agente*, *vencido*.
2. **Checkbox desabilitado com o motivo visível.** Deixar marcar e falhar depois
   entrega o erro na máquina do usuário, longe da causa.
3. **A barra flutuante mostra os dois números** — "12 selecionados · 3
   instaláveis" — e age só sobre os instaláveis.
4. **Falta o mapa `fingerprint` → `id`.** `prepare-install` recebe
   `certificate_ids` (UUID de `cert_pfx_store`); a tela tem fingerprints do
   inventário. Uma chamada a `list_available_pfx` na carga resolve, e é a mesma
   fonte do estado do item 1.
5. **A carteira tem de ser aplicada no servidor, não só na tela.** Esconder ou
   desabilitar no HTML é conveniência; a barreira real vai em `prepare-install`,
   que hoje não sabe o que é carteira. Sem isso, basta forjar a chamada.
6. **`target_machine` não pode ser campo de texto livre para o usuário final.**
   No modelo Ninite o `.exe` roda na máquina de quem baixou; **verificar se ainda
   tem função nesse fluxo** antes de expor ou remover.
7. **Definir teto de certificados por token** e recusar acima dele com mensagem
   clara — melhor que um download de tamanho imprevisível.
8. **A barra flutuante não pode tapar a paginação** no mobile.

**Aplicado em 15/08.** Duas decisões que o plano não previa:

- **A seleção não vive nos checkboxes.** A tabela pagina no servidor e o tbody é
  reconstruído a cada página; marcar três na página 1 e ir para a 2 apagaria
  tudo, sem aviso. Ela vive num `Map` por fingerprint, e os checkboxes são a
  projeção dela na página visível.
- **O teto vem do servidor para a tela** (`max_certificados` no contexto). O
  número escrito nos dois lugares divergiria na primeira mudança, e o sintoma
  seria o pior: a tela deixa marcar 60, o download falha com 422 no fim.

E o "selecionar todos" alcança só a página visível — marcar 489 de uma vez com
teto de 50 seria armadilha, não atalho.

### 3.5 Consequência de ordem: a carteira deixou de ser "futuro"

Era a etapa 5. Não é mais: **é a carteira que torna o Início correto para quem
não é admin**. Construir a seleção supondo "admin vê e instala tudo" e só depois
introduzir carteira significa refazer a tela e o endpoint.

A etapa 2 nasce ciente de carteira, ainda que a carteira comece rasa — admin vê
tudo, operador sem atribuição não instala nada — e a UI de gestão do gestor venha
depois (§6).

---

## 4. Etapa 3 — `/instalador` vira só configuração: **os 10 pontos**

> **Dividida em três levas.** Dez pontos com backend e tela em um commit só
> seria impossível de revisar e pior ainda de reverter.
>
> - **3a ✅ (15/08)** — diagnóstico: pontos **3, 4, 9 e 10**. Só leitura, sem
>   migration, e é o grupo que faltou no incidente da chave desta manhã.
> - **3b ✅ (15/08)** — configuração: pontos **2, 5 e 7**, com colunas novas em
>   `portal_settings` e rota de gravação parcial.
> - **3c ✅ (15/08)** — trilha e limpeza: pontos **1, 6, 8** e a saída da operação.
>
> **A seção "2 · Instalar Certificados" saiu na 3c**, e o "Enviar para Estação"
> foi **removido de vez em 16/08**, a pedido do cliente: no modelo dele o
> operador baixa o `.exe` e instala na própria máquina, e instalar no servidor
> via agente não tem uso. A rota `POST /api/cert-installer/prepare` saiu junto —
> endpoint que emite token de instalação sem ninguém usar é superfície de ataque
> sem contrapartida, porque um token **é** a entrega da chave privada.
>
> O agente continua entendendo o comando `instalar_certificados`. Mexer nele
> exigiria recompilar e reinstalar o `.exe` no ANALISESRV: custo operacional
> real por zero benefício, já que sem quem enfileire o comando ele nunca chega.

Hoje a página tem três seções: autorizar ao cofre, instalar, e trilha de
auditoria. As de operação saem para o Início. O que fica, e o que falta:

### 1. Ícone do `.exe` — declarar que é entrada de *build*, não de runtime ✅

O campo pode existir, mas **mentir sobre ele é o pior erro possível nesta
página**. Deve mostrar o ícone em uso, de qual arquivo veio, e o aviso de que
trocar exige recompilar e reassinar (seção 0.3). Um seletor que parece aplicar
na hora e não aplica gera um chamado de suporte por uso.

### 2. Nome do arquivo baixado — template com o `{token}` protegido ✅

Já existe (`?nome=`). Virar template configurável, ex. `Instalar {nome} -{token}.exe`.
**Validação obrigatória:** o token no nome é **funcional** — o instalador o lê do
próprio `argv[0]`. Um template que perca o `{token}` quebra toda instalação, e o
sintoma aparece na máquina do usuário. A validação recusa salvar sem ele.

### 3. Estado do binário no servidor ✅

`INSTALADOR_AVULSO_EXE.is_file()` hoje só é consultado no clique, e a falha vira
503 com a mensagem "rode `scripts/build_instalador_avulso.ps1`" — instrução
inútil para quem está na Vercel, onde o FS é read-only e o exe vem no bundle
(`e0581d5`). A página deve mostrar: **existe? tamanho? SHA-256? data? de qual
build veio?** Sem isso, "o download não funciona" é investigação de log.

### 4. Assinatura de código — estado real, não booleano otimista ✅

Pendência declarada em 11/08: adiada, com mitigação por diretiva de grupo
(domínio na zona Intranet Local) e **"não verificado em máquina real"**. A página
deve exibir o que o binário realmente tem — subject, validade, timestamp — ou
dizer que não está assinado. Enquanto for "não verificado", a tela é o lugar de
essa dívida ficar visível em vez de dormir num changelog.

### 5. Validade do token de instalação ✅

`install_token.expires_at` é constante no código. Vira configuração, **com o
trade-off na própria tela**: curto demais e o usuário perde a janela e volta a
pedir; longo demais e o link fica vivo numa caixa de e-mail. Número sem o
trade-off ao lado é convite para alguém pôr 30 dias.

### 6. Log de instalação — cadeia por token, não lista plana ✅

O que foi pedido, mas a forma importa. Hoje `install_log` tem 25 linhas, 3 dias,
um usuário, sem filtro nenhum. Precisa de filtro (período, usuário, status,
máquina) e, principalmente, **exibir a cadeia `SOLICITADO → REDIMIDO →
CONCLUIDO/ERRO` agrupada por token**. O valor está em ver **onde a cadeia
quebrou**, e os números atuais mostram exatamente por quê:

```
SOLICITADO  9   →   REDIMIDO  8   →   CONCLUIDO  2
                                      ERRO       6
```

### 7. Retenção do log — LGPD ✅

`install_log` guarda `client_ip` e `user_email` e **não tem política de
expurgo**. Cresce para sempre com dado pessoal. Configuração de retenção + rotina
de expurgo. Deixar para depois significa decidir sobre dado que já se acumulou.

### 8. Opt-in do cofre — agora explicitamente **por estação** ✅

Continua aqui: é decisão de segurança, não operação. Mas desde a chave composta
`(machine_id, fingerprint)` de 15/08, autorizar e revogar valem **para uma
máquina**. Hoje a máquina aparece num hint discreto (`instalador.html:339`).
Precisa ser elemento de primeira classe da tela — quem revoga tem de saber que
não está revogando nas outras.

### 9. Saúde do cofre — o painel que faltou em 15/08 ✅

Quantos PFX, por máquina, qual `key_version` de cada, quantos ainda sob chave
antiga, quando foi o último upload. **Foi exatamente o que faltou nesta data:** a
`CERT_ENCRYPTION_KEY` foi trocada sem rotação, o cofre inteiro virou lixo
cifrado, e nada na interface disse isso — descobriu-se por `InvalidTag` numa
investigação manual. Deve ter botão "revalidar", que tenta decifrar um PFX de
cada `key_version` e reporta.

### 10. Rotação da chave de cifragem — mecanismo sem interface ✅

`CERT_ENCRYPTION_KEY_V<n>` existe, foi consertado em `f96eeec` (o config nunca
expunha as variáveis) e **não tem tela nenhuma**. Mostrar a versão corrente,
quais versões ainda têm linhas vivas, e o caminho de recifrar. Sem isso, rotação
continua sendo um ato de fé no painel da Vercel — que é precisamente como o
incidente de 15/08 aconteceu.

> **11º, que não estava no pedido e vale mais que metade da lista:** um botão
> **"testar o fluxo inteiro"** — gerar token, baixar, e confirmar que o binário
> responde. As seis falhas registradas em produção têm **a mesma causa única**
> ("Senha ausente no cofre"), e ninguém soube até irem procurar.

---

## 5. Etapa 4 — Nova `/dashboard`

### 5.1 Regra que define esta etapa

> **Nenhum gráfico sem dado que o sustente.** Instalação tem 25 eventos, 3 dias,
> **um** usuário. Série temporal com três pontos e um usuário é decoração, e
> decoração num dashboard destrói a confiança em todos os outros números.
> Número grande + funil + tabela agora; série temporal quando houver ≥30 dias.

### 5.2 Construível hoje, com dado real

| # | Painel | Fonte | Estado hoje |
|---|---|---|---|
| 1 | **Funil de instalação** | `install_log` | 9 → 8 → 2 concluídos, 6 erros |
| 2 | **Causa das falhas** | `install_log.detail` | **as 6 são a mesma**: "Senha ausente no cofre" |
| 3 | **Cobertura do cofre** | `cert_pfx_store` ÷ inventário | **33 de 560 = 6%** |
| 4 | **Saúde do agente** | `cert_snapshots.scanned_at` | 2/5/4/4/7/2 varreduras nos últimos dias |
| 5 | **Certificados renovados** | `cert_snapshots` (§0.2) | mesmo `documento_numero` com `not_after` avançando |
| 6 | **Curva de vencimento** | `cert_history.vencimento_certificado` | 923 de 1.029 com data |
| 7 | **Acervo ilegível** | `cert_history.status_ultimo` | 42 `erro` + 41 `fora_do_padrao` = **83 arquivos** |
| 8 | **Alertas enviados** | `sent_alerts` | 11 — fecha o ciclo "avisamos → renovou?" |

Os painéis 2, 3 e 7 são os que apontam para trabalho concreto. O painel 2 vale
sozinho a etapa: **as seis falhas de produção têm causa única, provavelmente já
resolvida pelo rescan de 15/08 — e ninguém tem como saber.**

### 5.3 Não construível: "tempo de uso" → **atividade por usuário** ✅

Ver §0.1. A contraproposta, aplicada na etapa 4b:

- tabela `user_activity` (`user_id`, `user_email`, `evento`, `client_ip`,
  `contexto`, `ocorrido_em`), com o vocabulário de eventos fechado por `CHECK`
- eventos discretos: login e login negado. **Sem cronômetro, sem heartbeat, sem
  rastreio de navegação** — o que mantém a coleta proporcional, e isso importa
  porque é dado pessoal de funcionário
- **não duplica `install_log`.** Aquela já registra quem instalou o quê e com
  que desfecho; repetir aqui criaria duas fontes de verdade sobre o mesmo fato.
  O painel junta as duas na leitura
- retenção definida junto com a tabela, e o ajuste passou a chamar-se
  `trilha_retencao_dias`: cobre `install_log` **e** `user_activity`, que são o
  mesmo tipo de dado com a mesma justificativa. Dois botões seria convite a
  configurar um e esquecer o outro
- o painel responde "quem travou": pediu instalação e não concluiu nenhuma —
  gente provavelmente esperando alguém, sem saber disso

**Decisão registrada:** o registro é chamado do caminho de login e **nunca
levanta**. Telemetria que impede alguém de entrar no portal é pior que
telemetria nenhuma, e é um jeito fácil de uma tabela nova virar indisponibilidade
total. A mutação que a faz levantar derruba a suíte.

### 5.4 Maior risco técnico: agregação ✅ *(resolvido em 15/08, por medição)*

Medido contra produção antes de escrever qualquer endpoint:

| Consulta | Tamanho | Tempo |
|---|---|---|
| snapshots só com `scanned_at` (317) | 24,5 KB | 0,59s |
| **UM** snapshot com `items` | **518,8 KB** | 0,42s |
| `cert_history` (2 colunas, 1.029) | 78,6 KB | 0,28s |
| `cert_pfx_store` (2 colunas, 489) | 54,7 KB | 0,22s |

Varrer os 317 snapshots com `items` daria **~160 MB**. Mas a medição mostrou que
o custo **não está espalhado**: só renovações precisa dos itens, e só de **dois**
snapshots — o de hoje e o de N dias atrás. ~1 MB.

Por isso **não** houve tabela de métricas, view materializada nem job de
pré-cálculo: seriam a resposta certa para um custo espalhado. Dois endpoints
bastaram — os seis painéis baratos numa chamada (~1s) e as renovações em outra,
carregada em separado para o barato não esperar o caro.

### 5.5 O que a medição encontrou de quebra: truncamento silencioso

O PostgREST devolve no máximo **1.000 linhas** por requisição e **não avisa**.
A curva de vencimento reportava 1.000 arquivos de uma tabela com 1.029 — 29
certificados sumindo sem erro nenhum, e o desvio crescendo com o acervo.

**Os números publicados antes deste ponto estavam errados**, inclusive nesta
página: "77 ilegíveis" era 83. Corrigido acima. Toda leitura que pode passar de
mil linhas passou a paginar, e o teto virou explícito onde não vale paginar.

---

## 6. Etapa 5 — Gestor / operador: a UI de gestão ✅ *(aplicada em 2026-08-15)*

**Deixou de ser "futuro" em 15/08.** O modelo de carteira subiu para a etapa 2
(§3.5), porque é ele que torna o Início correto para quem não é admin. O que
sobra aqui é a **interface de gestão** e a hierarquia propriamente dita: o gestor
montando carteiras, e o histórico de instalação por usuário.

Os pré-requisitos abaixo, porém, **antecipam-se junto com a carteira** — não dá
para ter carteira por `user_id` sem resolver o modelo de usuário primeiro.

### 6.1 O modelo de `role` atual não comporta hierarquia

`users.role` é texto livre: `user`(7), `admin`(1), **`disabled`(2)**.

`disabled` como *role* é erro de modelagem — mistura **permissão** com **estado
da conta**. Uma pessoa desativada hoje **perde o registro de qual era o papel
dela**. Acrescentar `gestor` piora: desativar um gestor apaga a informação de que
era gestor.

**Separar `role` de `ativo` (boolean) antes de introduzir hierarquia.** Depois de
existirem gestores, essa migration mexe em vínculos e o risco cresce.

### 6.2 A aresta gestor → operador

`gestor_id UUID REFERENCES users(id)` em `users`. Mais simples que tabela de
associação, e o caso "dois gestores para a mesma pessoa" não existe hoje —
resolver o problema que se tem.

### 6.3 Liberação de certificados: ver §3.3 ✅

A carteira foi detalhada na etapa 2. A tela chegou na 5: `/carteiras`, visível a
admin **e** gestor — montar carteira é a função do gestor, e ele não administra
contas. Por isso `/api/carteira/operadores` existe em vez de reaproveitar
`/api/users`, que é de admin e devolve a linha inteira do usuário.

A **trilha é exibida**, não só guardada: cada documento mostra quem liberou e
quando. Guardar sem mostrar a tornaria decorativa, e ela é a única forma de
reconstruir o que houve se uma conta de gestor for comprometida.

Três decisões da tela que o modelo não determinava:

- **Documento atribuído que saiu do inventário continua na carteira**, marcado
  como tal. A atribuição é uma decisão; sumir com ela esconderia que a pessoa
  volta a ter acesso quando o certificado reaparecer — e ele reaparece, porque o
  agente move vencidos entre pastas.
- **A busca aceita CNPJ pontuado.** Ninguém digita CNPJ sem pontuação, e exigir
  dígitos puros faria a busca parecer quebrada para quem copia do sistema
  contábil.
- **O estado vazio diz a consequência**, não só que está vazio: "esta pessoa não
  consegue instalar nenhum certificado". É o comportamento correto do modelo,
  mas é também o que trava alguém sem que ninguém saiba por quê.

Boa notícia: `install_log` já tem `user_id` preenchido em **25 de 25** linhas. O
histórico por usuário nasce correto.

### 6.4 RLS não vai salvar — e é o ponto mais perigoso desta etapa

`20260517193000_rls_lgpd.sql` cobre 4 tabelas (`portal_settings`,
`cert_snapshots`, `agent_command_queue`, `colaborador_cert_selecoes`) com
políticas **de `service_role`**. Ficam de fora `users`, `install_log`,
`install_token`, `cert_pfx_store`, `cert_vault_optin`, `cert_history`.

E, mais importante: **a aplicação fala com o Supabase usando o service key**, que
ignora RLS. Toda autorização real está no FastAPI (`require_admin`). Ou seja:

> Com gestor/operador, **cada rota nova tem de lembrar de filtrar pelo escopo do
> gestor**. Uma única rota que esqueça devolve o acervo inteiro. Não há rede de
> proteção no banco.

A mitigação tem de ser estrutural — dependência de escopo obrigatória, no molde
de `require_admin`, que devolva o filtro em vez de deixá-lo a critério de quem
escreve a rota — e um teste que percorra as rotas e falhe quando alguma não a
declare.

**Feito na etapa 2c, pela metade que dá para fazer hoje.** A barreira é uma
função única (`_assegurar_carteira_ou_403`) que as duas rotas emissoras de token
chamam, e `test_toda_rota_que_cria_token_passa_pela_carteira` lê `app/main.py`
com `ast`: qualquer função que chame `create_install_token` sem chamar a barreira
derruba a suíte. `create_install_token` é o gargalo certo para vigiar — um token
**é** a entrega da chave privada, e sem token não há bundle.

O que continua em aberto: a leitura. Listagens novas que exponham dados de
cliente não passam por esse gargalo, e nenhum teste as vigia ainda.

---

## 7. Ordem de execução e dependências

A definição do modelo em 15/08 reordenou o meio do plano: a carteira, que era a
última etapa, virou pré-requisito da segunda.

```
Etapa 0  sidebar em partial            ✅ aplicada
   ↓
Etapa 1  Dashboard → Início            ✅ aplicada
   ↓
Etapa 2a modelo de usuário             ✅ aplicada — role vs ativo + gestor_id
   ↓
Etapa 2b custódia: opt-in → opt-out    ✅ aplicada — fail-closed estrutural
   ↓
Etapa 2c carteira + barreira no server ✅ aplicada — barreira e teste estrutural
   ↓
Etapa 2d Início: seleção + flutuante   ✅ aplicada — nasceu ciente de carteira
   ↓
Etapa 3  /instalador só configuração   ✅ aplicada — diagnóstico, config e trilha
   ↓
Etapa 4a /dashboard novo               ✅ aplicada — agregação decidida por medição
         4b tabela user_activity        ✅ aplicada — eventos discretos, não cronômetro
   ↓
Etapa 5  UI do gestor + trilha         ✅ aplicada — /carteiras, com a trilha visível
```

**Por que 2a antes de 2b/2c:** a carteira é chaveada por `user_id`, e enquanto
`disabled` for um *papel* em vez de um estado, desativar um gestor apaga o
registro de que era gestor — e junto o sentido das carteiras que ele criou. São
10 usuários hoje; a mesma migration com hierarquia montada é outro problema.

**Por que 2b antes de 2c:** não faz sentido conceder carteira sobre um cofre que
tem 6% do acervo. Inverter a custódia primeiro faz a carteira nascer sobre um
conjunto realista.

**Consertos pequenos que valem antes de tudo**, porque ficam mais caros depois:

1. ~~Login devolvendo 500 em credencial inválida (§0.5)~~ — feito na etapa 2a,
   que mexia no mesmo handler
2. `colaborador_cert_selecoes` chaveada por `user_id` — ✅ **concluído em
   17/08/2026, em sete passos.** O histórico abaixo fica porque as três
   correções de rota que apareceram no meio valem mais que o resultado.

   Em 16/08 fui atrás disto e o item não era o "conserto pequeno" que esta
   lista supunha. A premissa era o volume de dados ("enquanto é 1 linha"), e
   essa parte era verdadeira; o que tinha crescido era o *código em volta*.
   `_get_todos_colaboradores_selecoes` devolve `email → documentos` e cruza com
   `_emails_ativos()`, um conjunto de e-mails. Rechavear por `user_id` obriga a
   mexer no caminho dos alertas — o mesmo que em 09/08 mandava dado de cliente
   para `certguard.com` e `example.com`, e que hoje é o que impede isso.

   Some-se o sequenciamento: já há uma migration aplicada mas não conferida
   (`users_email_unico`) segurando o push. Empilhar sobre ela um `drop column`
   no caminho dos alertas, sem eu conseguir verificar schema, é onde o erro sai
   caro. E teria de ser em duas fases (adicionar+backfill → subir código →
   remover a coluna), porque o código em produção ainda lê `user_email`.

   **O que foi feito em 16/08:** `_mover_selecoes_de_email`, chamado por
   `update_user` quando o endereço muda. Fechou o defeito concreto sem
   migration e sem tocar no caminho dos alertas — mas é remendo no *chamador*:
   um UPDATE direto, uma rota nova ou uma importação reintroduziriam a órfã.

   **Retomado em 17/08.** ✅ *Fases 1 e 2 aplicadas; faltam a 3 e a 4.*

   | Fase | O quê | Estado |
   |---|---|---|
   | 1 | coluna `user_id` anulável + FK `ON DELETE CASCADE` + backfill + índice único parcial | ✅ 17/08 (`20260817120000`) |
   | 2 | código lê pela identidade e grava nas **duas** colunas | ✅ 17/08 |
   | 3a | SQL: `UNIQUE (user_id)` como *constraint* | ✅ 17/08 |
   | 3b | SQL: `UNIQUE (user_email)` e **remove a chave primária** | ✅ 17/08 |
   | 3b-2 | SQL: `ALTER COLUMN user_email DROP NOT NULL` | ✅ 17/08 |
   | 3c | código para de gravar/ler `user_email`; `on_conflict` → `user_id`; apaga `_mover_selecoes_de_email` | ✅ 17/08 |
   | 3d | SQL: derruba a coluna `user_email`; `user_id` vira `NOT NULL` e PK | ✅ 17/08 |

   **Encerrado em 17/08/2026.** Estado final verificado em produção:
   `PRIMARY KEY (user_id)`, `FOREIGN KEY (user_id) REFERENCES users(id) ON
   DELETE CASCADE`, nenhuma `UNIQUE` avulsa, 1 linha preservada. Com `user_id
   NOT NULL`, **o banco passa a recusar linha sem identidade** — até então isso
   dependia de o código se comportar.

   **Duas correções de rota, no mesmo dia, e vale registrar as duas** — cada
   vez que olhei um nível abaixo apareceu a restrição seguinte:

   1. A primeira versão dizia *"fase 3: `DROP COLUMN user_email`; fase 4:
      código para de gravar"*. Nessa ordem as gravações quebram: o código da
      fase 2 ainda grava `user_email` e a usa como alvo do `on_conflict`.
   2. A segunda esquecia que **`user_email` é a chave primária**, portanto
      `NOT NULL`. O código não pode parar de gravá-la enquanto for assim — o
      `INSERT` violaria o `NOT NULL`. E a PK não pode sair sozinha, porque o
      `on_conflict` do código no ar precisa de constraint única ali. Circular;
      a 3b é o que abre o círculo, pondo o `UNIQUE` **antes** de tirar a PK.

   Daí a 3a existir: o índice da fase 1 é PARCIAL (`WHERE user_id IS NOT
   NULL`), e índice parcial não serve para o `ON CONFLICT` inferir alvo.

   **Terceira correção, e esta foi a verificação fazendo o trabalho dela.** Eu
   escrevi na 3b que, removida a PK, `user_email` ficaria `is_nullable = YES`.
   O passo de verificação devolveu **`NO`**. No PostgreSQL o `NOT NULL` é um
   atributo próprio da coluna (`attnotnull`), que a `PRIMARY KEY` **define** ao
   ser criada mas **não desfaz** ao ser removida — é preciso um
   `ALTER COLUMN ... DROP NOT NULL` explícito. Daí a 3b-2.

   Sem esse passo, a 3b tinha atingido metade do objetivo: `user_email` deixou
   de ser chave, mas continuava obrigatória, então o código ainda não poderia
   parar de gravá-la — exatamente o bloqueio que a 3b existia para abrir. Se a
   verificação fosse só "rodou sem erro", isso teria passado, e o defeito
   apareceria na 3c como falha de gravação em produção.

   **A tabela fica sem chave primária entre a 3b e a 3d**, de propósito.
   `user_id` só vira PK depois de ser `NOT NULL`, e isso só deve ser exigido
   quando o código garantir que sempre a preenche — o que passa a valer na 3c.
   Não afeta o portal: o PostgREST usa os filtros explícitos que o código
   manda, e as duas constraints `UNIQUE` continuam impedindo linha duplicada,
   que é o que de fato protege.

   **A ordem é o ponto inteiro.** O código em produção lê `user_email`; derrubar
   a coluna antes da fase 2 faria a leitura levantar exceção, o `except` cairia
   no fallback de ficheiro — efêmero e vazio na Vercel — e uma rodada de alertas
   sairia **sem destinatário nenhum**, em silêncio.

   O que a fase 2 mudou de fato no caminho dos alertas:
   `_get_todos_colaboradores_selecoes` continua devolvendo `email → documentos`
   (contrato de saída intocado, então quem consome não mudou), mas o endereço
   agora sai de `users` pela identidade, e não da própria linha. E-mail trocado
   depois da escolha deixa de perder o destinatário. `_linhas_ativas()` faz uma
   leitura só e dela saem as duas visões (`_por_id`, `_por_email`).

   Duas coisas deliberadas, que o código não conta sozinho:

   - **A leitura ainda cai para `user_email`** se não achar por `user_id`. Não é
     zelo: entre a fase 1 e o deploy da 2, o código anterior podia criar linha
     sem `user_id`, e sem a queda essa pessoa veria a seleção vazia. Um `save`
     seguinte liga a linha — a transição se resolve com o uso, sem backfill
     manual. A queda some na fase 4.
   - **O `on_conflict` continua `user_email`**, porque o índice sobre `user_id`
     é PARCIAL (`WHERE user_id IS NOT NULL`) e índice parcial não serve para o
     `ON CONFLICT` inferir alvo. Muda na fase 4.

   **Sinal de conclusão:** na fase 4, `_mover_selecoes_de_email` vira código
   morto. Poder apagá-lo é a prova de que o rechaveamento funcionou — enquanto
   ele for necessário, a causa ainda está lá.

   **Ruga conhecida:** o fallback em ficheiro (`_load_colaborador_file_dict`)
   continua chaveado por e-mail. Nesse modo não existe tabela `users`, então
   ali a identidade *é* o endereço. Os dois backends divergem de propósito.

   **Perda consciente na 3c, e é a única.** Antes, a linha de seleção guardava
   o endereço, então uma falha ao ler `users` só tirava o *filtro* — as
   seleções passavam inteiras e o alerta saía. Agora o endereço só existe em
   `users`: sem essa leitura não há para quem mandar. Não é "não sei filtrar",
   é "não sei endereçar", e não há fallback honesto.

   Essa redundância **era** o defeito (endereço que envelhecia junto da linha),
   então perdê-la é o preço do conserto. A contrapartida é que a falha grita:
   `logger.error` com a contagem de seleções lidas, e o job tenta de novo no
   ciclo seguinte. Uma rodada morrendo em silêncio é o pior modo de falhar para
   um sistema cuja função é avisar sobre vencimento — daí o `ERROR`, e daí
   `test_users_ilegivel_deixa_a_rodada_sem_destinatario` exigir a mensagem, e
   não só o `{}`.

~~**Aberto, descoberto na 2a:** o JWT dura 24h e é stateless, então desativar
alguém **não invalida o token que já está no navegador dele** — o acesso cai só
na expiração.~~ ✅ *(resolvido em 2026-08-16 — checagem por requisição)*

`require_auth` passou a reler a conta em `users` a cada requisição autenticada:
confere se ela ainda existe, aplica `auth.conta_ativa` e monta o `TokenData` com
o papel **do banco**. O papel que vem dentro do token é ignorado.

Ao escrever a etapa apareceu um segundo efeito, pior que o registrado aqui e que
ninguém tinha notado: como `require_admin` decidia com `token.role`, **rebaixar
um administrador também não valia na hora** — ele seguia administrando até o
token expirar. E esse não dava sintoma nenhum, porque a conta continuava ativa.

Escolhas que o código não conta sozinho:

- **Checagem por requisição, não `token_version`.** O versionamento faria a
  mesma leitura em `users` por requisição, e ainda pediria migration. Só ganharia
  se houvesse cache, e não há.
- **401 para sessão morta, 403 para papel insuficiente.** `static/ui-common.js`
  intercepta todo 401 e chama `logout()`; quem foi desativado volta ao login
  sozinho, e quem foi rebaixado continua no portal, apenas sem as rotas de admin.
- **503 quando a leitura falha**, e não 401 nem "deixa passar". Fail-closed, como
  em `CustodiaIndisponivel` — mas sem deslogar meio portal numa oscilação do banco.
- **Sem diretório configurado, vale o token.** É dev e teste; em produção sem
  Supabase o `/api/login` já responde 503 e ninguém obtém token.

**Preço:** uma leitura em `users` por requisição autenticada — em parte já
abatido. `_sessao_do_token` carrega o `id` da conta que acabou de conferir em
`TokenData.user_id`, e as 3 rotas que chamavam `_resolve_user_id(token.email)`
passaram a `_user_id_da_sessao(token)`, que só consulta quando não houve leitura
(sem Supabase, e o agente por X-API-Key). Nessas rotas a revogação saiu de graça:
a consulta que ela adicionou é a que elas já faziam.

`user_id` **não** vem do JWT, e há teste fixando isso. Se um dia passar a ser
lido do token, quem tiver a `JWT_SECRET_KEY` escolhe de quem é a carteira que
vai usar — e `atribuir_carteira` grava esse valor como autor da atribuição.

---

## 8. Se nada disto for feito

O portal continua funcionando para quem já sabe usá-lo. O que não acontece:

- ninguém descobre que **6% do acervo é instalável** pelo portal
- ninguém descobre que **as seis falhas registradas têm causa única**, e
  provavelmente já resolvida
- a próxima rotação de chave repete o incidente de 15/08, porque continua sem
  interface
- e a etapa de gestor/operador, quando vier, será construída sobre `role` em
  texto livre e liberação chaveada por e-mail — as duas coisas que esta ordem
  existe para evitar.
