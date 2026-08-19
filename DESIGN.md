---
name: Analise Certificado
description: Portal de custódia e monitoramento de certificados digitais — uma superfície por vez, nada na tela que não seja a tarefa.
colors:
  system-blue: "#0071E3"
  system-blue-hover: "#0051A2"
  system-blue-text: "#0066CC"
  bg: "#F5F5F7"
  surface: "#FFFFFF"
  text: "#1D1D1F"
  text-muted: "#6E6E73"
  border: "rgba(0, 0, 0, 0.08)"
  sidebar-bg: "#1C1C1E"
  sidebar-text: "#8E8E93"
  sidebar-text-active: "#FFFFFF"
  sidebar-danger: "#FF6B6B"
  total: "#007AFF"
  total-bg: "#E8F0FE"
  ok: "#34C759"
  ok-bg: "#EAF9EE"
  ok-text: "#1D7A3A"
  warning: "#FF9F0A"
  warning-bg: "#FFF7EB"
  warning-text: "#8A5200"
  expired: "#FF3B30"
  expired-bg: "#FDF2F2"
  expired-text: "#C1121C"
  expired-solid: "#C1121C"
  fora-padrao-bg: "#F5F3FF"
  fora-padrao-text: "#6D28D9"
  row-hover: "rgba(0, 113, 227, 0.04)"
  row-tint-danger: "#FEF2F2"
  row-tint-warning: "#FFFBEB"
typography:
  display:
    fontFamily: "-apple-system, BlinkMacSystemFont, Inter, 'SF Pro Text', 'Helvetica Neue', Helvetica, Arial, sans-serif"
    fontSize: "56px"
    fontWeight: 700
    lineHeight: 1.15
    letterSpacing: "-0.04em"
  headline:
    fontSize: "32px"
    fontWeight: 600
    lineHeight: 1.25
    letterSpacing: "-0.03em"
  title1:
    fontSize: "22px"
    fontWeight: 600
    lineHeight: 1.3
    letterSpacing: "-0.02em"
  title2:
    fontSize: "18px"
    fontWeight: 500
    lineHeight: 1.35
    letterSpacing: "-0.01em"
  body:
    fontSize: "16px"
    fontWeight: 400
    lineHeight: 1.6
    letterSpacing: "0"
  caption:
    fontSize: "12px"
    fontWeight: 400
    lineHeight: 1.4
    letterSpacing: "0.02em"
  label:
    fontSize: "11px"
    fontWeight: 600
    lineHeight: 1.4
    letterSpacing: "0.10em"
  mono:
    fontFamily: "ui-monospace, 'Cascadia Code', Consolas, monospace"
    fontSize: "0.8rem"
    fontWeight: 400
    lineHeight: 1.35
    letterSpacing: "0"
rounded:
  xs: "4px"
  sm: "8px"
  md: "12px"
  lg: "18px"
  pill: "980px"
spacing:
  sp-1: "4px"
  sp-2: "8px"
  sp-3: "12px"
  sp-4: "16px"
  sp-5: "20px"
  sp-6: "24px"
  sp-8: "32px"
  sp-10: "40px"
  sp-12: "48px"
  sp-16: "64px"
components:
  button-secondary:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.text}"
    rounded: "{rounded.pill}"
    padding: "0.5rem 1.1rem"
  button-secondary-hover:
    backgroundColor: "{colors.bg}"
    textColor: "{colors.text}"
  button-primary:
    backgroundColor: "{colors.system-blue}"
    textColor: "#FFFFFF"
    rounded: "{rounded.pill}"
    padding: "0.5rem 1.1rem"
  button-primary-hover:
    backgroundColor: "{colors.system-blue-hover}"
    textColor: "#FFFFFF"
  button-danger:
    backgroundColor: "{colors.expired-bg}"
    textColor: "{colors.expired-text}"
    rounded: "{rounded.pill}"
    padding: "0.5rem 1.1rem"
  input-field:
    backgroundColor: "{colors.bg}"
    textColor: "{colors.text}"
    rounded: "{rounded.md}"
    padding: "0.6rem 0.9rem"
  input-field-focus:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.text}"
  card-metric:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.text}"
    rounded: "{rounded.lg}"
    padding: "0.85rem 0.95rem"
  card-surface:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.text}"
    rounded: "{rounded.lg}"
    padding: "{spacing.sp-6}"
  badge-ok:
    backgroundColor: "{colors.ok-bg}"
    textColor: "{colors.ok-text}"
    typography: "{typography.label}"
    rounded: "{rounded.pill}"
    padding: "0.25rem 0.75rem"
  badge-warning:
    backgroundColor: "{colors.warning-bg}"
    textColor: "{colors.warning-text}"
    typography: "{typography.label}"
    rounded: "{rounded.pill}"
    padding: "0.25rem 0.75rem"
  badge-expired:
    backgroundColor: "{colors.expired-bg}"
    textColor: "{colors.expired-text}"
    typography: "{typography.label}"
    rounded: "{rounded.pill}"
    padding: "0.25rem 0.75rem"
  badge-bad:
    backgroundColor: "transparent"
    textColor: "{colors.text}"
    typography: "{typography.label}"
    rounded: "{rounded.pill}"
    padding: "0.25rem 0.75rem"
  nav-item:
    backgroundColor: "transparent"
    textColor: "{colors.sidebar-text}"
    rounded: "{rounded.sm}"
    padding: "0.65rem 1rem"
  nav-item-active:
    backgroundColor: "{colors.system-blue}"
    textColor: "{colors.sidebar-text-active}"
    rounded: "{rounded.sm}"
    padding: "0.65rem 1rem"
  page-link:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.text}"
    padding: "0 0.85rem"
    height: "44px"
  page-link-current:
    backgroundColor: "{colors.total-bg}"
    textColor: "{colors.system-blue-text}"
    height: "44px"
  toast:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.text}"
    rounded: "{rounded.md}"
    padding: "0.85rem 1.15rem"
    width: "400px"
  modal:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.text}"
    rounded: "{rounded.lg}"
    width: "460px"
  notification-dropdown:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.text}"
    rounded: "{rounded.md}"
    width: "320px"
    height: "400px"
  notification-item-expired:
    backgroundColor: "{colors.expired-bg}"
    textColor: "{colors.text}"
    rounded: "{rounded.sm}"
    padding: "0.75rem"
  notification-item-expiring:
    backgroundColor: "{colors.warning-bg}"
    textColor: "{colors.text}"
    rounded: "{rounded.sm}"
    padding: "0.75rem"
  notification-badge:
    backgroundColor: "{colors.expired-solid}"
    textColor: "#FFFFFF"
    rounded: "{rounded.pill}"
    padding: "0.15rem 0.35rem"
    height: "18px"
  dup-tooltip:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.text}"
    rounded: "{rounded.md}"
    padding: "0.7rem 0.85rem 0.75rem"
    width: "36rem"
  dup-tooltip-path:
    backgroundColor: "{colors.bg}"
    textColor: "{colors.text}"
    typography: "{typography.mono}"
    rounded: "{rounded.xs}"
    padding: "0.28rem 0.45rem"
---

# Design System: Analise Certificado

## Overview

**Creative North Star: "A Mesa Limpa"**

Uma superfície por vez, nada na tela que não seja a tarefa. O usuário primário
entra para achar um certificado, baixar o instalador e sair — a visita dura
menos de um minuto, e o sistema é desenhado para acabar rápido, não para
prender. Tudo que não serve àquela tarefa está arquivado: fora da tela, atrás de
um item de menu que o papel do usuário nem revela, ou dentro de um modal que
fecha quando termina.

O caráter é **preciso e silencioso, confiável e institucional**. Isso não é
decoração: os certificados custodiados são ICP-Brasil, de clientes do
escritório, e a interface responde por chave privada de terceiros. O sistema
transmite isso por rigor, não por drama — sem cadeado ilustrado, sem cofre
desenhado, sem vermelho de alarme onde um vermelho de estado basta. A seriedade
vive no fato de que cada token de cor carrega sua razão de contraste medida no
comentário ao lado, e nada entra no sistema sem ela.

A moldura é o contraste entre a sidebar escura permanente (`#1C1C1E`) e o campo
claro de trabalho (`#F5F5F7` com folhas brancas). A navegação é grave e fixa; o
conteúdo é leve e trocável. Esse par é a assinatura visual do produto e a única
composição verdadeiramente global.

**Anti-referência confirmada:** o SaaS genérico de gradiente — degradê roxo-azul,
ilustração isométrica, cantos gordos de 24px, herói de landing page. Este produto
é ferramenta interna de custódia, não pitch de startup. Um gradiente decorativo
em qualquer superfície é defeito, não gosto.

**Key Characteristics:**

- Sidebar escura fixa de 250px + conteúdo claro com teto de 1280px.
- Paleta de sistema Apple, com quatro estados de certificado em trio tonal (identidade / fundo / texto).
- Toda cor de texto vem com razão de contraste medida e comentada no CSS.
- Botões em pílula (980px), folhas de conteúdo em 18px, campos em 12px.
- Separação tonal primeiro, sombra como reforço — nunca o contrário.
- Dois temas completos, com o sistema como padrão e escolha explícita gravada em `data-theme`.
- Movimento curto e funcional: `fadeUp` de 400ms na entrada, `translateY(-3px)` no hover do card, nada mais.

## Colors

Paleta de sistema — os tons de referência do vocabulário Apple, escolhidos para
que a cor de marca não dispute atenção com a cor de estado. O certificado é que
tem cor; o portal é cinza, branco e grafite.

### Primary

- **Azul de Sistema** (`#0071E3` claro / `#0A84FF` escuro): assume a herança do
  azul funcional do SO sem disfarce. É a única cor de marca da tela e cobre
  exclusivamente **navegação e interação**: item ativo da sidebar, botão
  primário, anel de foco, borda de campo focado, página atual da paginação,
  link. Nunca diz nada sobre o estado de um certificado.
- **Azul de Sistema — texto** (`#0066CC` claro / `#5AA9FF` escuro): o par de
  texto corrido. Existe porque o azul de identidade passa 4.70:1 sobre a folha
  branca mas reprova sobre `total-bg`, onde a paginação e o selo de sincronismo
  o usam como texto. Bordas, ícones e anéis usam a identidade; texto usa este.

### Secondary

Não existe cor secundária de marca, e a ausência é deliberada. O segundo eixo
cromático do sistema é o **estado do certificado**, abaixo — dar-lhe um
concorrente de marca tornaria a tabela ilegível.

### Tertiary

- **Violeta Fora-de-Padrão** (`#6D28D9` sobre `#F5F3FF`): o quinto estado, para
  o arquivo que existe mas não segue a convenção de nome. Fica fora da escala
  verde-âmbar-vermelho de propósito — não é pior nem melhor que vencido, é outra
  categoria de problema, e o olho precisa separá-la sem ler.

### Neutral

- **Cinza de Mesa** (`#F5F5F7` claro / `#1C1C1E` escuro): o fundo da área de
  trabalho. Nunca recebe conteúdo diretamente; serve para a folha branca ter de
  onde se destacar.
- **Folha** (`#FFFFFF` claro / `#2C2C2E` escuro): toda superfície que carrega
  conteúdo — card, tabela, modal, toast, painel lateral.
- **Grafite** (`#1D1D1F` claro / `#F5F5F7` escuro): texto corrido e números.
- **Cinza Legível** (`#6E6E73` claro / `#98989D` escuro): rótulo, legenda,
  cabeçalho de tabela, texto de apoio. O tom escuro foi escolhido em 4.85:1
  sobre a folha — é o mínimo que este sistema aceita, não uma aproximação.
- **Fio** (`rgba(0,0,0,0.08)` claro / `rgba(255,255,255,0.08)` escuro): toda
  borda e divisória, aplicada em `0.5px` nas superfícies e `1.5px` nos controles.
- **Grafite de Moldura** (`#1C1C1E` claro / `#111112` escuro): fundo da sidebar.
  Note a inversão deliberada: no tema escuro a sidebar fica **mais escura** que
  o conteúdo, mantendo a hierarquia de moldura em vez de fundi-la com o fundo.

### Estados do certificado

Quatro estados, cada um em trio: identidade (ícone, barra, borda), fundo tonal e
texto legível sobre esse fundo.

- **Válido** — identidade `#34C759`, fundo `#EAF9EE`, texto `#1D7A3A` (4.95:1).
- **Expirando** — identidade `#FF9F0A`, fundo `#FFF7EB`, texto `#8A5200` (6.01:1).
- **Vencido** — identidade `#FF3B30`, fundo `#FDF2F2`, texto `#C1121C` (5.68:1).
  O sólido `#C1121C` existe à parte para o badge de contagem, onde o branco
  precisa de 4.5:1 e o vermelho de identidade só entrega 3.54:1.
- **Total** — identidade `#007AFF`, fundo `#E8F0FE`: contagem, não estado.

Há ainda dois **tons de linha** (`#FEF2F2` e `#FFFBEB` no claro; os mesmos
matizes a 10% de alfa no escuro) para pintar a linha inteira da tabela quando ela
está vencida ou expirando. São mais claros que os fundos de badge de propósito:
a linha é grande, o badge é pequeno, e a mesma intensidade nos dois faria a
tabela vibrar.

E um **véu de hover** (`--row-hover`, o azul do sistema a 4% no claro e a 6% no
escuro), o único token que é deliberadamente translúcido: ele precisa compor com
o tom de linha que estiver por baixo, e uma cor sólida apagaria o estado do
certificado justamente ao passar o mouse sobre ele.

### Named Rules

**A Regra do Contraste Comentado.** Nenhum token de cor de texto entra no sistema
sem sua razão de contraste medida, escrita em comentário ao lado do valor, e o
fundo contra o qual foi medida. `--ok-text: #1D7A3A; /* 4.95:1 sobre --ok-bg */`
é o formato. Um token novo sem essa linha é um token não verificado.

**A Regra do Sinal Único.** Azul é navegação; verde, âmbar, vermelho e violeta
são estado. As duas famílias nunca trocam de papel. Um botão vermelho de ação
destrutiva usa o trio *vencido* porque destruir e vencer compartilham o mesmo
alarme — mas um link jamais fica verde para dizer "tudo certo".

**A Regra da Guarda de Tema.** Toda regra sensível ao tema escuro se escreve
`@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) { ... } }`
— nunca a media query crua. Sem a guarda, quem escolheu tema claro num sistema
escuro recebe o valor escuro, e o seletor de tema mente. Na prática: resolva por
token na camada de tema, e nenhuma regra de componente precisará da media query.

**A Regra do Par Tonal.** Cor de estado nunca aparece sozinha. Toda vez que um
fundo tonal é usado, o texto sobre ele vem do token `-text` correspondente,
nunca de `--text-muted` e nunca da própria cor de identidade.

## Typography

**Fonte de interface:** Inter (400 / 500 / 600 / 700), com a fonte nativa do
sistema à frente na pilha — `-apple-system, BlinkMacSystemFont` primeiro, Inter como
alternativa livre. É a Inter que atende Windows, plataforma real dos usuários.

O carregamento é `<link rel="preconnect">` + `<link rel="stylesheet">` no
`<head>` de cada template, nunca `@import` no CSS: o import cria uma cadeia
serial que atrasa o LCP.

**Fonte de dado literal:** `ui-monospace, "Cascadia Code", Consolas, monospace`
— a pilha nativa, sem download. Cobre exclusivamente **caminho de arquivo**
(`C:\Certs\...`) nos balões de duplicidades. É o único lugar do sistema onde a
fonte muda, e o motivo é funcional: caminho se compara caractere a caractere, e
proporcional embaralha essa leitura.

**Character:** uma só família em sete papéis, mais o mono de exceção. A hierarquia vem de peso,
tamanho e *tracking* negativo crescente — quanto maior o texto, mais fechado
(-0.04em no display, 0 no corpo). É a receita de sistema operacional, não de
editorial: nenhum título tem personalidade própria, e a diferença entre um nível
e o seguinte é sempre lida antes de ser notada.

### Hierarchy

- **Display** (700, 56px, 1.15, -0.04em): reservado. Não aparece em nenhuma
  página do portal hoje — existe para uma tela de marca ou um número único que
  precise dominar.
- **Headline** (600, 32px, 1.25, -0.03em): o `<h1>` de cada página. Cai para
  24px abaixo de 768px.
- **Title 1** (600, 22px, 1.3, -0.02em): título de bloco dentro de uma folha.
- **Title 2** (500, 18px, 1.35, -0.01em): subtítulo, cabeçalho de painel lateral.
- **Body** (400, 16px, 1.6): texto corrido. Tabelas descem para 14px e listas
  densas para 13,6px — a tabela é lida em varredura, não em leitura.
- **Caption** (400, 12px, 1.4, 0.02em): dica, nota de rodapé, texto de apoio.
- **Label** (600, 11px, 1.4, 0.10em, CAIXA ALTA): cabeçalho de tabela, título de
  card de métrica, badge.
- **Número de métrica** (700, 26px, 1.1, -0.03em): o valor grande do card de
  dashboard. Cai para 22px abaixo de 768px.
- **Mono** (400, 0.8rem, 1.35): caminho de arquivo, com `word-break: break-all`
  e `white-space: pre-wrap` — o caminho quebra onde precisar e nunca alarga o
  balão que o contém.

### Named Rules

**A Regra do Único Grito.** Caixa alta existe em exatamente um nível — o Label
(11px, peso 600, tracking 0.10em). Cabeçalho de tabela, título de card e badge
usam esse nível e nada mais no sistema é maiúsculo. Botão, link, título e texto
corrido ficam em caixa normal, sempre.

**A Regra do Tracking Invertido.** Tamanho grande fecha o espaçamento, tamanho
pequeno abre. Um título novo de 32px sem `-0.03em` destoa de todos os outros
antes que alguém saiba dizer por quê.

## Layout

**A moldura.** Sidebar fixa de 250px à esquerda, `position: fixed`, e
`.main-content` com `margin-left: 250px` e `flex: 1`. O conteúdo tem
`max-width: 1280px` — sem esse teto, num monitor largo as ações alinhadas à
direita ficavam a ~900px do título e do dado a que se referem.

**Respiro.** Padding de 2,25rem no conteúdo (1,25rem abaixo de 900px, 1,25/1rem
abaixo de 768px). Escala de espaçamento em passos de 4px, de `sp-1` (4px) a
`sp-16` (64px); o passo de trabalho é `sp-6` (24px) para padding de folha e
`sp-4` (16px) entre blocos.

**A grade de métricas.** `repeat(auto-fit, minmax(min(180px, 100%), 1fr))` com
gap de 0,85rem. Sem media query: o `auto-fit` resolve sozinho e os cinco cards
entram em linha a partir de ~960px. O `min(180px, 100%)` é a guarda contra
transbordo em 320px. Abaixo de 768px o mínimo cai para 140px; abaixo de 480px
vira `minmax(0, 1fr) minmax(0, 1fr)` — duas colunas fixas, com o piso em `0` e
não em `auto`, porque `auto` é o min-content e o rótulo "FALHA (SEM PADRÃO)"
alargava a coluna além do viewport.

**Três breakpoints, três comportamentos distintos:**

| Largura | O que muda |
|---|---|
| ≤ 900px | Sidebar colapsa para 76px, só ícones (`font-size: 0` nos rótulos). Conteúdo com `margin-left: 76px`. |
| ≤ 768px | Sidebar vira gaveta: `translateX(-100%)`, aberta por `body.sidebar-open`, com backdrop. Conteúdo sem margem. Toolbar empilha e todo controle vira 100% de largura. |
| ≤ 480px | Grade de métricas em duas colunas fixas, ícones de 36px→32px. |

**Densidade.** A tabela tem células de `0.85rem 0.5rem` e `border-bottom` de
0.5px — sem zebra, sem grade vertical. A separação entre linhas é o fio e o
hover (`rgba(0,113,227,0.04)`); linhas em estado crítico recebem o tom de linha.

### Named Rules

**A Regra do Rolar Por Dentro.** A página nunca rola de lado. Quem rola é o
`.table-scroll`, que existe para isso e é focável por teclado. `min-width: 0` em
todo item flex que contém tabela é obrigatório — sem ele o `min-content` da
tabela empurra o conteúdo além do viewport entre ~900 e ~1050px.

**A Regra do Teto de 1280.** Conteúdo não passa de 1280px de largura, em nenhuma
tela. A distância entre uma ação e o dado a que ela se refere é parte do design.

## Elevation & Depth

**Híbrido, com o tom fazendo o trabalho principal.** A separação entre planos é
antes de tudo tonal — `--bg` cinza contra `--surface` branco. A sombra só
reforça o que o tom já disse, e é deliberadamente sutil no tema claro (alfa de
0.03 a 0.08). No tema escuro a hierarquia é quase inteiramente tonal, porque
sombra preta contra `#1C1C1E` praticamente não aparece; por isso os valores
escuros são bem mais opacos (0.2 a 0.4) — para render o mesmo pouco.

Toda folha nasce com sombra em repouso; este não é um sistema *flat-by-default*.
O que muda com o estado é a profundidade, não a existência.

### Shadow Vocabulary

- **`--shadow-sm`** (`0 1px 2px rgba(0,0,0,0.04)`): item ativo da sidebar,
  botão de paginação. Um fio de sombra, o suficiente para o elemento não parecer
  pintado no fundo.
- **`--shadow-md`** (`0 4px 12px rgba(0,0,0,0.05), 0 1px 3px rgba(0,0,0,0.03)`):
  o repouso de toda folha — card de métrica, container de tabela.
- **`--shadow-lg`** (`0 12px 30px rgba(0,0,0,0.08), 0 4px 12px rgba(0,0,0,0.04)`):
  o que flutua sobre a página — modal, toast, dropdown de notificações, gaveta
  mobile, skip-link. E o hover do card de métrica, que sobe um nível.

O `backdrop-filter: blur(20px)` aparece na sidebar e `blur(2px)` no `::backdrop`
do modal. É o único efeito de material do sistema.

### Named Rules

**A Regra do Tom Primeiro.** Se a separação entre dois planos só funciona com a
sombra, o desenho está errado. Verifique com a sombra desligada: no tema escuro
é quase assim que a pessoa vê.

**A Regra dos Três Degraus.** Existem exatamente três sombras e elas não se
misturam nem se somam. Um elemento novo escolhe um dos três — não inventa um
quarto valor.

## Shapes

Quatro raios, e cada um significa uma categoria de coisa. O raio é como o
sistema diz o que um elemento é, antes de qualquer rótulo.

- **Pílula** (`980px`): tudo que é acionável e efêmero — botão, badge. A forma
  totalmente arredondada é o gesto mais reconhecível do sistema.
- **18px** (`--radius-lg`): a folha. Card de métrica, container de tabela, modal,
  empty state. É o raio grande, e só superfícies de conteúdo o usam.
- **12px** (`--radius-md`): controle de entrada. Campo de texto, select, toast,
  banner.
- **8px** (`--radius-sm`): item de navegação, ícone de card, canto externo de um
  grupo de paginação.
- **4px** (`--radius-xs`): etiqueta pequena (`.tag`), o menor elemento nomeado.

**Bordas.** Duas espessuras, com significados diferentes: `0.5px` para
divisórias e contornos de superfície (folha, linha de tabela, cabeçalho de
sidebar) e `1.5px` para contornos de controle (botão, campo, select). O fio fino
separa; o fio grosso convida ao toque.

A **toolbar** usa `border-bottom: 1px dashed` — o único tracejado do sistema, e
o empty state usa `1px dashed` na borda inteira. Tracejado significa "aqui não
há conteúdo ainda" ou "aqui termina o cabeçalho", nunca decoração.

### Named Rules

**A Regra da Pílula Acionável.** Se é clicável e cabe numa linha, é pílula. Se é
uma superfície que carrega conteúdo, é 18px. Um botão de canto reto ou um card
em pílula quebra a leitura do sistema inteiro.

## Components

### Buttons

Refinados e contidos: reação mínima e imediata, o componente confirma o toque e
volta ao lugar.

- **Shape:** pílula completa (`--radius-pill`, 980px), padding `0.5rem 1.1rem`,
  peso 500, 0,85rem, `inline-flex` com gap de 4px para o ícone.
- **Secundário (padrão):** folha branca, borda de 1.5px em `--border`, texto
  grafite. É a forma base — a maioria dos botões do portal é esta.
- **Primário:** `--accent-solid` (#0071E3) com texto branco, sempre o mesmo azul
  nos dois temas. O token não muda entre temas de propósito: o `#0A84FF` do tema
  escuro com branco dá 3.65:1 e reprovaria.
- **Perigo:** fundo `--expired-bg`, texto `--expired-text`, borda
  `rgba(255,59,48,0.25)`. Vermelho tonal, não vermelho sólido — a ação
  destrutiva é séria, não estridente.
- **Hover:** fundo desce para `--bg` (ou `--accent-hover` no primário), opacidade
  0,9. **Active:** `translateY(1px)` + `brightness(0.96)` — o botão afunda.
  **Focus:** anel de 2px em `--accent` com offset de 2px, via `:focus-visible`.
- **Disabled:** opacidade 0,45, cursor `not-allowed`, e **permanece no DOM e
  legível** — a informação de que a ação existe é relevante.

### Inputs / Fields

- **Style:** fundo `--bg` (mais escuro que a folha em que está — o campo é uma
  depressão, não uma elevação), borda de 1.5px, raio de 12px, padding
  `0.6rem 0.9rem`.
- **Focus:** a borda vira `--border-focus` **e o fundo sobe para `--surface`** —
  o campo acende de dentro. Somado a um halo de `0 0 0 4px rgba(0,113,227,0.15)`.
- **Rótulo sempre visível.** `placeholder` não substitui `label`: ele some assim
  que a pessoa digita, e o contraste é insuficiente. `.form-field` é
  `flex-column` com gap de 8px justamente para isso.

### Badges

- **Style:** pílula, 11px, peso 600, sem borda; fundo tonal + texto do trio de
  estado.
- **Glifo de forma:** todo badge carrega um glifo antes do texto (`.badge-glifo`,
  peso 700, `min-width: 1em`, `aria-hidden`), herdando `currentColor`. Numa
  tabela de centenas de linhas a forma se reconhece antes da palavra, e com
  deuteranopia o verde e o âmbar convergem.
- **`badge-bad`** é a exceção: transparente com contorno e texto pleno, porque
  aparece sobre os tons de linha, onde `--text-muted` cai a 4.0–4.4:1 no escuro.

### Cards / Containers

- **Card de métrica:** folha de 18px, borda de 0.5px, `--shadow-md`, padding
  `0.85rem 0.95rem`. Layout `flex` com o bloco de texto à esquerda e um ícone
  de 36px (raio 8px) à direita, pintado com o par fundo/texto do estado. O
  rótulo é caixa alta de 10,5px; o número é 26px peso 700.
- **Hover:** `translateY(-3px)` + `--shadow-lg`, em 250ms com `--ease-spring`.
  É o único `will-change` do projeto, e é intencional: aplicá-lo em massa
  promovia dezenas de camadas ociosas na GPU.
- **Container de tabela:** mesma folha, padding `--sp-6`, margem inferior
  `--sp-8`.

### Navigation

- **Sidebar:** 250px, `#1C1C1E`, fixa, `backdrop-filter: blur(20px)`, borda
  direita de 0.5px branca a 8%.
- **Item:** `flex` com ícone de 1,3rem e gap de 0,75rem, padding `0.65rem 1rem`,
  raio de 8px, peso 500, 0,95rem, cor `--sidebar-text`.
- **Hover:** fundo branco a 8%, texto branco pleno. **Ativo:** fundo
  `--sidebar-active-bg` (#0071E3 nos dois temas) + `--shadow-sm`.
- **Ícones:** Heroicons outline, `stroke-width: 1.5`, `currentColor`, inline no
  template. Nunca `<img>`, nunca icon font.
- **Mobile (≤768px):** gaveta de 270px com `translateX(-100%)`, backdrop
  escuro, transição de 0,3s.

### Paginação

O componente mais trabalhado do sistema. Fila de botões unidos: cantos externos
arredondados em 8px (`--rounded-s` / `--rounded-e`), miolo quadrado, bordas
sobrepostas com `margin-left: -1px`. Altura mínima de **44px** — paginação é
alvo frequente em uso por toque.

A página atual usa `--total-bg` de fundo com texto `--accent-text` e borda
`--accent`. O foco é `:focus-visible`, nunca `:focus`: o anel é para teclado, e
com `:focus` puro ele aparecia a cada clique de mouse num controle que se clica
o tempo todo.

### Toasts

Canto inferior direito, empilhados com gap de 12px, largura máxima de 400px.
Folha de 12px com `--shadow-lg` e uma **barra de 4px à esquerda** na cor de
identidade do tipo (`--ok`, `--expired`, `--warning`, `--accent`). Entram com
`translateY(16px)` → 0 e opacidade 0 → 1 em 250ms.

O botão de fechar é 44×44px com margem negativa de -0,5rem para não inchar o
toast visualmente — WCAG 2.5.8 exige 24px, as HIG recomendam 44.

### Modais

`<dialog>` nativo. `width: min(92vw, 460px)`, `max-height: min(88vh, 720px)`,
raio de 18px, `--shadow-lg`, backdrop preto a 45% com `blur(2px)`.

Estrutura de três faixas — cabeçalho, corpo rolável, rodapé — separadas por fios
de 0.5px, com o rodapé alinhado à direita. **Erro de servidor aparece dentro do
diálogo** (`.modal__erro`, fundo `--expired-bg`), nunca como toast: o toast fica
atrás do backdrop e some sozinho, e a pessoa perderia a única explicação de por
que a gravação falhou justamente enquanto olha o formulário que a causou.

### Empty states

Folha de 18px com **borda tracejada**, padding `3rem 1.5rem`, centralizado:
ícone de 2,5rem a 80% de opacidade, título de 1,1rem peso 600, descrição de
0,875rem em `--text-muted` com `max-width: 400px`, e um botão de ação.

### Central de notificações

O único componente **glassmorphic** do sistema, e o único que muda de material
conforme o tema explícito.

- **Sino:** botão da topbar, empurrado para a direita por `margin-left: auto`.
  Só um item pode carregar essa margem — se o botão de tema também a tivesse, o
  espaço se dividiria e o sino voltaria ao centro; por isso existe um seletor
  adjacente que desfaz a do tema quando o sino está presente.
- **Badge de contagem:** círculo de 18px em `--expired-solid` (#C1121C) com
  texto branco, ancorado a -4px do canto superior direito do sino, com **anel de
  2px em `--surface`** que o recorta do ícone. Pulsa em `pulse-badge` — um halo
  vermelho que expande de 0 a 6px a cada 2s, infinito. É o único movimento
  perpétuo do portal, e `prefers-reduced-motion` o desliga por completo
  (`animation: none`), não apenas o acelera.
- **Dropdown:** 320px de largura, 400px de altura máxima, ancorado a 42px abaixo
  do sino, raio de 12px com `--shadow-lg`. Entra com `fadeInDown` — 8px de cima
  para baixo em 200ms com `--ease-out`, o inverso do `fadeUp` da página.
- **Material:** a folha vira `rgba(255,255,255,0.85)` no claro e
  `rgba(44,44,46,0.85)` no escuro, ambas com `backdrop-filter: blur(20px)`. A
  regra é aplicada por `:root[data-theme="..."]`, ou seja **só quando o usuário
  escolheu um tema explicitamente**; em "seguir o sistema" o dropdown fica
  opaco. É a mesma família de material da sidebar, e os dois são os únicos.
- **Seções:** o corpo é dividido por títulos de 10px, peso 700, tracking 0.08em,
  caixa alta — meio degrau acima do Label, e a única exceção à Regra do Único
  Grito.
- **Item:** raio de 8px com **barra de 3px à esquerda**, transparente por
  padrão, que assume `--expired` ou `--warning` junto do fundo tonal
  correspondente. O hover soma `translateX(2px)` a um véu de 3% — o item desliza
  para a direita, para o lado onde a barra não está.
- **Estados:** vazio, carregando e erro compartilham o mesmo bloco centrado de
  2rem em `--text-muted`. O carregando desenha seu spinner em `::before` — 14px,
  borda de 2px em `--border` com o topo em `--accent`, girando em 600ms linear.

### Tabelas de duplicidades

A superfície mais densa do portal: três tabelas independentes na mesma página
(assinatura idêntica, mesmo documento, nomes semelhantes), cada uma com sua
própria paginação.

- **Moldura:** `overflow: hidden` sobre folha branca com raio de 12px. A rolagem
  não fica aqui — fica no `.table-scroll` interno, com `max-height:
  min(68vh, 760px)` e `scrollbar-gutter: stable`. Abaixo de 640px de **altura**
  o teto sai, senão sobrariam pouquíssimas linhas visíveis.
- **Cabeçalho grudado:** `position: sticky; top: 0` com fundo `--surface` e
  `box-shadow: 0 1px 0 var(--border)` — a linha inferior é sombra, não borda,
  porque borda em `<th>` sticky se descola ao rolar.
- **Região focável:** o `.table-scroll` tem `tabindex="0"` e
  `role="region"` com `aria-label`, e o anel de foco usa `outline-offset: -2px`
  para desenhar por dentro da moldura em vez de vazar. Região rolável precisa
  ser alcançável por teclado (WCAG 2.1.1).
- **Célula:** padding `0.5rem 0.65rem` e `vertical-align: top` — mais apertada
  que a tabela padrão (`0.85rem 0.5rem`) e alinhada ao topo, porque a coluna de
  nome quebra em várias linhas e a de documento não.
- **Linha que fala:** as linhas com detalhe extra recebem `cursor: help`,
  `tabindex="0"` e `aria-describedby` apontando para o balão. O balão existe
  para quem chega por Tab, não só por mouse — e por isso a tinta de destaque
  responde a `:hover` **e** `:focus-visible`.
- **Balão de caminhos:** `position: fixed`, `z-index: 2000`,
  `max-width: min(92vw, 36rem)`. Cabeçalho em `--accent-text` com ícone de
  0.95rem, lista com marcadores em `--border`, e cada caminho num bloco mono
  sobre `--bg` com borda e raio de 4px, quebrando por `break-all`.
- **Linha de estado:** quando não há duplicidades, o corpo recebe uma única
  linha `hint-only` com `colspan`, padding de `0.9rem 0.75rem` e sem borda
  inferior — a mensagem ocupa a tabela em vez de fingir ser um registro.

**Reconciliado em 19/08/2026.** Este bloco carregava cinco desvios — um azul de
outra paleta no hover, raios de 10px e 6px fora da escala, uma sombra própria em
`rgba(15,23,42,…)`, uma transição de `0.12s ease` e uma segunda pilha mono. Todos
passaram a usar token. A correção do hover trouxe junto um defeito do próprio
sistema: `tbody tr:hover` resolvia o tema por `@media (prefers-color-scheme:
dark)` **sem** a guarda `:root:not([data-theme="light"])` que a camada de tokens
usa, então quem forçava tema claro num sistema escuro recebia o hover escuro.
Com `--row-hover` a media query desapareceu e o defeito com ela.

### Motion

- **Entrada de página:** `fadeUp` (16px + opacidade) em 400ms com `--ease-spring`,
  aplicado a todo filho direto de `.main-content`. Sempre `backwards`, **nunca
  `both`** — com `both` o `translateY(0)` final fica aplicado para sempre,
  criando um contexto de empilhamento em cada filho e prendendo o dropdown de
  notificações atrás dos cards.
- **Stagger:** os cards de métrica entram em cascata de 50ms (0,05s a 0,30s).
- **Vocabulário de easing:** `--ease-spring` `cubic-bezier(0.25,1,0.5,1)` para
  entrada e movimento; `--ease-out` `cubic-bezier(0.16,1,0.3,1)` para mudança de
  estado; durações de 150 / 250 / 400ms.
- **`prefers-reduced-motion`:** zera duração (0,01ms, não 0s — o
  `transitionend` do toast depende do disparo) e remove o movimento decorativo.
  **Não zera `transform`**, porque aqui transform também é layout: a gaveta
  mobile se esconde com `translateX(-100%)`, e um `transform: none !important`
  global deixava a sidebar aberta sobre o conteúdo exatamente para quem a regra
  deveria proteger.

## Do's and Don'ts

### Do:

- **Do** escrever a razão de contraste medida em comentário ao lado de todo token
  de cor de texto novo, com o fundo contra o qual foi medida.
- **Do** usar o trio completo de estado: fundo tonal + o token `-text`
  correspondente. Texto de estado nunca sai de `--text-muted`.
- **Do** acompanhar toda cor de estado de um segundo canal — glifo no badge,
  palavra no texto, ícone no card. Cor sozinha nunca carrega a informação.
- **Do** dar 44px de altura mínima a qualquer alvo de toque frequente
  (paginação, fechar toast, ações de linha).
- **Do** usar `:focus-visible` para anéis de foco e `:focus` apenas quando o
  realce for do próprio campo (borda + sombra) ou for o skip-link.
- **Do** manter `min-width: 0` em todo item flex que contenha tabela.
- **Do** pôr erro de formulário dentro do próprio formulário ou diálogo.
- **Do** revelar item de menu por papel no cliente, com `display: none` no
  template como estado inicial.
- **Do** tornar toda região rolável alcançável por teclado (`tabindex="0"` +
  `role="region"` + `aria-label`), com o anel de foco em `outline-offset: -2px`
  quando ela tiver moldura própria.
- **Do** reservar a fonte mono para dado literal comparável caractere a
  caractere — caminho de arquivo, impressão digital. Nunca para texto de UI.

### Don't:

- **Don't** usar gradiente decorativo, ilustração isométrica ou herói de landing
  page. A anti-referência confirmada é o SaaS genérico de gradiente.
- **Don't** pintar navegação com cor de estado nem estado com o Azul de Sistema.
- **Don't** inventar um quarto nível de sombra, um quinto raio ou um segundo
  nível de caixa alta.
- **Don't** trocar `backwards` por `both` em animação de entrada — cria contexto
  de empilhamento e enterra os elementos flutuantes.
- **Don't** aplicar `will-change` em massa; ele fica reservado aos cards de
  métrica, que animam `transform` de fato.
- **Don't** zerar `transform` dentro de `prefers-reduced-motion`.
- **Don't** carregar fonte com `@import` dentro do CSS; o `<link>` no `<head>`
  dispara em paralelo.
- **Don't** usar `placeholder` como rótulo de campo.
- **Don't** deixar a página rolar horizontalmente para acomodar uma tabela — quem
  rola é o `.table-scroll`.
- **Don't** deixar um botão desabilitado sumir da tela; ele fica visível e
  legível.
- **Don't** escrever cor literal em `rgba()` onde existe token. O véu de hover
  das duplicidades já foi um `rgba(59,130,246,0.06)` — azul de outra paleta, sem
  variante de tema escuro — e é exatamente assim que a deriva começa: um valor
  que parece certo, num arquivo que ninguém relê.
- **Don't** resolver tema com `@media (prefers-color-scheme: dark)` cru numa
  regra de componente; ver A Regra da Guarda de Tema.
- **Don't** repetir o material *glassmorphic*. Ele pertence a exatamente dois
  elementos — a sidebar e o dropdown de notificações — e sua raridade é o que o
  faz funcionar.
