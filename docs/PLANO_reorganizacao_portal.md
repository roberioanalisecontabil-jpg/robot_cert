# Plano — reorganização do portal: Início, Dashboard, Instalador e gestão

> **Status: Etapas 0, 1, 2 (a–d), 3a e 3b aplicadas em 2026-08-15. Falta 3c, 4 e 5.**
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
2. **Expurgo por vencimento.** Certificado que venceu sai do cofre. Sem isso o
   acervo só cresce, e cresce em chave privada.
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
> - **3c** — trilha e limpeza: pontos **1, 6, 8** e a saída da operação.
>
> **A seção "2 · Instalar Certificados" NÃO foi removida ainda.** O download
> mudou-se para o Início na etapa 2d, mas o "Enviar para Estação" (instalação
> via agente, com `target_machine`) não tem destino lá. Removê-la agora seria
> tirar uma capacidade sem substituto — fica para a 3c, junto com o destino.

Hoje a página tem três seções: autorizar ao cofre, instalar, e trilha de
auditoria. As de operação saem para o Início. O que fica, e o que falta:

### 1. Ícone do `.exe` — declarar que é entrada de *build*, não de runtime

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

### 6. Log de instalação — cadeia por token, não lista plana

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

### 8. Opt-in do cofre — agora explicitamente **por estação**

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
| 7 | **Acervo ilegível** | `cert_history.status_ultimo` | 41 `erro` + 36 `fora_do_padrao` = **77 arquivos** |
| 8 | **Alertas enviados** | `sent_alerts` | 11 — fecha o ciclo "avisamos → renovou?" |

Os painéis 2, 3 e 7 são os que apontam para trabalho concreto. O painel 2 vale
sozinho a etapa: **as seis falhas de produção têm causa única, provavelmente já
resolvida pelo rescan de 15/08 — e ninguém tem como saber.**

### 5.3 Não construível: "tempo de uso" → **atividade por usuário**

Ver §0.1. A contraproposta, que é também o pré-requisito da etapa 5:

- tabela `user_activity` (`user_id`, `evento`, `ocorrido_em`, contexto)
- eventos discretos: login, download solicitado, instalação concluída/falhou
- o dashboard mostra **última atividade, ações no período, taxa de conclusão por
  usuário** — não cronômetro
- retenção definida **junto com a criação da tabela**, não depois (§4.7)

### 5.4 Maior risco técnico: agregação

`cert_snapshots` são 317 linhas × ~560 itens. Varrer isso a cada carga de página
numa função serverless da Vercel **vai estourar o tempo** — e piora sozinho a
cada varredura do agente. Os painéis 4, 5 e 6 exigem agregação prévia: tabela de
métricas diária alimentada de forma incremental, ou view materializada. **Decidir
isso antes de escrever o primeiro endpoint**, porque é o que define o formato de
todos eles.

---

## 6. Etapa 5 — Gestor / operador: a UI de gestão

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

### 6.3 Liberação de certificados: ver §3.3

A carteira foi detalhada na etapa 2. O que fica aqui é a tela do gestor —
atribuir e revogar documentos por operador — e a **trilha**, que deixou de ser
opcional: com o gestor podendo atribuir qualquer cliente do acervo (decisão de
15/08), quem atribuiu o quê a quem e quando é a única forma de reconstruir o que
aconteceu se uma conta de gestor for comprometida.

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
Etapa 3  /instalador só configuração   ← recebe o painel de desativação (§3.2c)
   ↓
Etapa 4  /dashboard novo               ← decidir agregação ANTES do 1º endpoint (§5.4)
         + tabela user_activity
   ↓
Etapa 5  UI do gestor + trilha         ← trilha obrigatória pelo alcance total (§6.3)
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
2. `colaborador_cert_selecoes` chaveada por `user_id` — enquanto é 1 linha

**Aberto, descoberto na 2a:** o JWT dura 24h e é stateless, então desativar
alguém **não invalida o token que já está no navegador dele** — o acesso cai só
na expiração. Era irrelevante quando desativar era raro; com a hierarquia, passa
a ser a operação de revogação principal. Resolver exige checagem por requisição
ou versionamento de token, e merece etapa própria.

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
