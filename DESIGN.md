---
name: Analise CertiDigital
description: Portal de custódia e instalação de certificados digitais sobre o Águia Design System — grafite quente sobre off-white, ouro só como acento, cor só para estado.
colors:
  gold-500: "#C9A06A"
  gold-600: "#B88157"
  gold-700: "#9A6A3D"
  gold-300: "#E0C08A"
  gold-200: "#ECD6AC"
  gold-glow: "rgba(201, 160, 106, 0.14)"
  grad-gold: "linear-gradient(135deg, #B07545 0%, #C9A06A 46%, #E4CC8F 100%)"
  ink-950: "#171717"
  ink-900: "#212121"
  ink-800: "#2C2B29"
  ink-700: "#3D3B38"
  ink-600: "#52504C"
  ink-500: "#6B6863"
  ink-400: "#8C8983"
  ink-300: "#B4B0A9"
  ink-200: "#D8D4CC"
  ink-150: "#E7E3DB"
  ink-100: "#EFEBE3"
  ink-50: "#F7F4EE"
  white: "#FFFFFF"
  success-50: "#E6F4EC"
  success-500: "#2F855A"
  success-700: "#22633F"
  warning-50: "#FBF0DC"
  warning-500: "#B7791F"
  warning-700: "#8A5A12"
  danger-50: "#FBE9E9"
  danger-500: "#C53030"
  danger-700: "#9B2323"
  info-50: "#E7F0FA"
  info-500: "#2B6CB0"
  info-700: "#1F5185"
  row-hover: "color-mix(in srgb, #C9A06A 6%, transparent)"
typography:
  display:
    fontFamily: "'Exo', system-ui, sans-serif"
    fontSize: "2rem"
    fontWeight: 700
    lineHeight: 1.1
    letterSpacing: "-0.01em"
  metric:
    fontFamily: "'Exo', system-ui, sans-serif"
    fontSize: "2rem"
    fontWeight: 700
    lineHeight: 1.1
    letterSpacing: "-0.01em"
    fontVariation: "tabular-nums"
  title:
    fontFamily: "'Exo', system-ui, sans-serif"
    fontSize: "1.125rem"
    fontWeight: 700
    lineHeight: 1.25
    letterSpacing: "0"
  button:
    fontFamily: "'Exo', system-ui, sans-serif"
    fontSize: "0.875rem"
    fontWeight: 700
    lineHeight: 1
    letterSpacing: "0.01em"
  overline:
    fontFamily: "'Exo', system-ui, sans-serif"
    fontSize: "0.75rem"
    fontWeight: 700
    lineHeight: 1.4
    letterSpacing: "0.12em"
  table-head:
    fontFamily: "'Exo', system-ui, sans-serif"
    fontSize: "0.75rem"
    fontWeight: 700
    lineHeight: 1.4
    letterSpacing: "0.04em"
  body:
    fontFamily: "'Inter', system-ui, -apple-system, 'Segoe UI', sans-serif"
    fontSize: "1rem"
    fontWeight: 400
    lineHeight: 1.5
    letterSpacing: "0"
  body-sm:
    fontFamily: "'Inter', system-ui, -apple-system, 'Segoe UI', sans-serif"
    fontSize: "0.875rem"
    fontWeight: 400
    lineHeight: 1.5
    letterSpacing: "0"
  body-xs:
    fontFamily: "'Inter', system-ui, -apple-system, 'Segoe UI', sans-serif"
    fontSize: "0.8125rem"
    fontWeight: 400
    lineHeight: 1.5
    letterSpacing: "0"
  label:
    fontFamily: "'Inter', system-ui, -apple-system, 'Segoe UI', sans-serif"
    fontSize: "0.8125rem"
    fontWeight: 600
    lineHeight: 1.5
    letterSpacing: "0"
  badge:
    fontFamily: "'Inter', system-ui, -apple-system, 'Segoe UI', sans-serif"
    fontSize: "0.8125rem"
    fontWeight: 600
    lineHeight: 1.4
    letterSpacing: "0"
  mono:
    fontFamily: "'JetBrains Mono', 'SFMono-Regular', Consolas, monospace"
    fontSize: "0.875rem"
    fontWeight: 400
    lineHeight: 1.5
    letterSpacing: "0"
    fontVariation: "tabular-nums"
rounded:
  xs: "4px"
  sm: "6px"
  md: "10px"
  lg: "14px"
  xl: "20px"
  pill: "999px"
  circle: "50%"
spacing:
  space-1: "0.25rem"
  space-2: "0.5rem"
  space-3: "0.75rem"
  space-4: "1rem"
  space-5: "1.25rem"
  space-6: "1.5rem"
  space-8: "2rem"
  space-10: "2.5rem"
  space-12: "3rem"
  space-16: "4rem"
components:
  button-primary:
    backgroundColor: "{colors.gold-500}"
    textColor: "{colors.ink-900}"
    typography: "{typography.button}"
    rounded: "{rounded.pill}"
    padding: "11px 22px"
    height: "44px"
  button-primary-hover:
    backgroundColor: "{colors.gold-600}"
    textColor: "{colors.ink-900}"
  button-primary-pressed:
    backgroundColor: "{colors.gold-glow}"
    textColor: "{colors.gold-700}"
    rounded: "{rounded.pill}"
    padding: "11px 22px"
  button-outline:
    backgroundColor: "transparent"
    textColor: "{colors.ink-900}"
    typography: "{typography.button}"
    rounded: "{rounded.pill}"
    padding: "11px 22px"
    height: "44px"
  button-outline-hover:
    backgroundColor: "{colors.gold-glow}"
    textColor: "{colors.gold-700}"
  button-ghost:
    backgroundColor: "transparent"
    textColor: "{colors.ink-600}"
    typography: "{typography.button}"
    rounded: "{rounded.pill}"
    padding: "11px 22px"
  button-ghost-hover:
    backgroundColor: "{colors.ink-100}"
    textColor: "{colors.ink-900}"
  button-sm:
    backgroundColor: "transparent"
    textColor: "{colors.ink-600}"
    rounded: "{rounded.pill}"
    padding: "8px 16px"
    height: "36px"
  button-legacy-solid:
    backgroundColor: "{colors.ink-900}"
    textColor: "{colors.white}"
    rounded: "{rounded.pill}"
  input-field:
    backgroundColor: "{colors.white}"
    textColor: "{colors.ink-900}"
    typography: "{typography.body-sm}"
    rounded: "{rounded.md}"
    padding: "10px 14px"
    height: "44px"
  input-field-focus:
    backgroundColor: "{colors.white}"
    textColor: "{colors.ink-900}"
  card:
    backgroundColor: "{colors.white}"
    textColor: "{colors.ink-900}"
    rounded: "{rounded.xl}"
  card-head:
    backgroundColor: "{colors.white}"
    textColor: "{colors.ink-900}"
    typography: "{typography.title}"
    padding: "{spacing.space-5} {spacing.space-6}"
  kpi:
    backgroundColor: "{colors.white}"
    textColor: "{colors.ink-900}"
    typography: "{typography.metric}"
    rounded: "{rounded.xl}"
    padding: "{spacing.space-6}"
  kpi-atencao:
    backgroundColor: "{colors.warning-50}"
    textColor: "{colors.ink-900}"
    typography: "{typography.metric}"
    rounded: "{rounded.xl}"
    padding: "{spacing.space-6}"
  kpi-icon:
    backgroundColor: "{colors.ink-100}"
    textColor: "{colors.ink-600}"
    rounded: "{rounded.md}"
    size: "40px"
  badge-success:
    backgroundColor: "{colors.success-50}"
    textColor: "{colors.success-700}"
    typography: "{typography.badge}"
    rounded: "{rounded.pill}"
    padding: "3px 10px"
  badge-warning:
    backgroundColor: "{colors.warning-50}"
    textColor: "{colors.warning-700}"
    typography: "{typography.badge}"
    rounded: "{rounded.pill}"
    padding: "3px 10px"
  badge-danger:
    backgroundColor: "{colors.danger-50}"
    textColor: "{colors.danger-700}"
    typography: "{typography.badge}"
    rounded: "{rounded.pill}"
    padding: "3px 10px"
  badge-neutral:
    backgroundColor: "{colors.ink-100}"
    textColor: "{colors.ink-600}"
    typography: "{typography.badge}"
    rounded: "{rounded.pill}"
    padding: "3px 10px"
  table-head:
    backgroundColor: "{colors.ink-100}"
    textColor: "{colors.ink-600}"
    typography: "{typography.table-head}"
    padding: "12px 16px"
    height: "44px"
  table-cell:
    backgroundColor: "{colors.white}"
    textColor: "{colors.ink-900}"
    typography: "{typography.body-sm}"
    padding: "12px 16px"
    height: "44px"
  table-row-hover:
    backgroundColor: "{colors.row-hover}"
    textColor: "{colors.ink-900}"
  table-wrap:
    backgroundColor: "{colors.white}"
    textColor: "{colors.ink-900}"
    rounded: "{rounded.lg}"
  row-card-mobile:
    backgroundColor: "{colors.white}"
    textColor: "{colors.ink-900}"
    rounded: "{rounded.lg}"
    padding: "{spacing.space-3} {spacing.space-4}"
  sidebar:
    backgroundColor: "{colors.ink-900}"
    textColor: "{colors.ink-400}"
    width: "250px"
  sidebar-item-active:
    backgroundColor: "{colors.gold-glow}"
    textColor: "{colors.gold-300}"
  selection-bar:
    backgroundColor: "{colors.white}"
    textColor: "{colors.ink-900}"
    rounded: "{rounded.lg}"
  dropdown-menu:
    backgroundColor: "{colors.white}"
    textColor: "{colors.ink-900}"
    rounded: "{rounded.md}"
---

# Design System: Analise CertiDigital

## Overview

**Creative North Star: "A Mesa de Cartório"**

A superfície de trabalho é um tampo off-white quente (`ink-50`) sobre o qual
folhas brancas assentam com um fio de sombra de tinta sépia; o texto é grafite
quente, não preto; e o ouro da Análise Group aparece como um selo aplicado com
parcimônia — um filete no alto de cada indicador, um único botão preenchido, o
anel de foco. É o mundo do **Águia Design System** da Análise Group (documento
`systemdesign.html`, Desktop/migracao-supabase, revisão de 17/08/2026), adotado
pelo portal a partir de 22/09/2026. O Início (`templates/index.html`) é a
primeira tela nele; as demais ainda vestem o mundo anterior ("A Mesa Limpa",
acento azul derivado da Apple) e migram uma a uma. **Este arquivo descreve o
sistema de agora em diante, e não o legado.**

O caráter é **institucional, quente e contido**. A custódia é de chave privada
de terceiros (certificados ICP-Brasil de clientes do escritório), e a
interface responde por isso com rigor, não com drama: a única cor que grita é
cor de estado, e mesmo ela aparece lavada (fundo a 50) com o texto no degrau 700
do mesmo matiz. A hierarquia nasce de três famílias tipográficas com papéis
fixos — Exo para o que se lê de longe (título, número grande, botão, cabeçalho
de tabela), Inter para o que se lê de perto, JetBrains Mono para o que se
confere dígito a dígito (CNPJ/CPF).

O sistema é **de ponte**: os tokens do Águia chegam verbatim em
`aguia-tokens.css` e nunca são editados no projeto; os primitivos `.ag-*`
vivem em `aguia-components.css`; e `painel-certificados.css` liga os nomes de
token que o portal legado usa (`--bg`, `--surface`, `--text`, `--accent`,
`--sidebar-*`, `--fs-*`, `--sp-*`) aos do Águia. Por isso sidebar, toasts,
estado vazio, paginação e barra de seleção — escritos em `style.css` com os
nomes antigos — pintam no Águia nesta tela sem que `style.css` mude, e as
outras telas ficam como estão até carregarem os três arquivos.

**Anti-referências confirmadas:** o SaaS de gradiente (degradê roxo-azul, herói
de landing, cantos de 24px) e o "dashboard dourado" — ouro em área grande,
texto branco sobre ouro, borda dourada em todo card. O ouro é acento precioso
porque é raro.

**Key Characteristics:**

- Duas famílias de cor por tela: grafite quente + ouro. Verde, âmbar e vermelho entram só como estado de certificado, sempre lavados.
- Ouro em no máximo ~10% da tela e nunca como fundo de área: filete de 3px no KPI, um botão primário por vez, anel de foco, texto de marca.
- Rótulo grafite (`ink-900`) sobre ouro; branco sobre ouro é a violação mais comum do DS e está proibida.
- Três fontes com papéis fixos (Exo / Inter / JetBrains Mono), servidas pelo próprio portal em `static/fonts` porque o portal vive numa VPN.
- Sombras de tinta quente `rgba(45,32,20,…)`, nunca preto puro; foco de 3px em ouro a 50%.
- Todo clicável com 44px de alvo; estado nunca só por cor (glifo Lucide no badge, palavra ao lado, borda no toggle).
- Tema escuro por token (`html.dark`, `data-theme="dark"` ou sistema com guarda `:root:not([data-theme="light"])`), nunca por regra de componente.
- Texto em sentence case pt-BR; caixa alta só em overline e cabeçalho de tabela; nenhum emoji.

## Colors

Grafite quente sobre off-white, ouro como selo, semânticas lavadas para estado —
a paleta é a do Águia DS, copiada sem alteração; o projeto escolhe quais degraus
usa, nunca os valores.

### Primary

- **Ouro Águia** (`gold-500`): o único acento de marca. Fundo do botão primário
  (com rótulo grafite), borda de campo focado, base do anel de foco e da
  `--border-brand`. Vira `gold-600` no hover do primário, no `accent-color`
  do checkbox e na borda do contorno em hover; `gold-700` é o **texto de
  marca** no tema claro (coluna ordenada ativa, botão de contorno em hover,
  primário "ligado"), e `gold-300` o texto de marca no escuro (também o item
  ativo da sidebar).
- **Lavado dourado** (`gold-glow`, ouro a 14% no claro / 12% no escuro): o
  único ouro que pode cobrir área — fundo do item ativo e do hover da sidebar,
  fundo do botão de contorno em hover e do primário em `aria-pressed`. Nunca
  `gold-50` ou `gold-100` como fundo de bloco.
- **Filete** (`grad-gold`, 135°, `#B07545 → #C9A06A → #E4CC8F`): exclusivo da
  linha de 3px no topo do KPI. É o único gradiente do sistema e não cresce.
- **Seleção de texto** (`gold-200` com texto `ink-900` no claro; `gold-700`
  com `ink-50` no escuro).

### Neutral

Doze degraus de tinta quente (`ink-950` a `ink-50`) mais branco. Papéis fixos:

- **Página** (`ink-50` claro / `ink-950` escuro): o tampo. Nunca recebe texto
  corrido diretamente — exceto no celular, onde o card da tabela dissolve e
  os cartões de linha assentam direto nele.
- **Folha** (`white` claro / `ink-900` escuro): card, KPI, campo, moldura de
  tabela, barra de seleção, menu suspenso.
- **Folha alternativa** (`ink-100` claro / `ink-800` escuro): cabeçalho de
  tabela, caixa do ícone do KPI, badge neutro, hover do botão fantasma.
- **Texto primário** (`ink-900` / `ink-50`), **secundário** (`ink-600` /
  `ink-300`: frase de abertura, rótulo de campo, cabeçalho de tabela, ícone
  do KPI, subtexto de célula) e **apagado** (`ink-500` / `ink-400`: rótulo do
  KPI, delta, placeholder, linha de status, prefixo "Emitido"/"Vence").
- **Bordas** em três pesos: sutil (`ink-150` / `ink-800`: divisória entre
  linhas e sob o cabeçalho de card), padrão (`ink-200` / `ink-700`: contorno
  de card, KPI, campo, moldura de tabela) e forte (`ink-300` / `ink-600`:
  botão de contorno e hover de campo).
- **Sidebar** (`ink-900` em ambos os temas, texto `ink-400`): a moldura grave
  do portal legado passa a usar o grafite do DS; o item ativo é lavado
  dourado com texto `gold-300`, no lugar do azul sólido de antes.

### Estados do certificado

Cada família semântica tem três degraus e os três se usam juntos: **50** é o
fundo lavado, **500** a identidade (borda, ícone, barra de toast), **700** o
texto sobre o lavado.

- **Ativo** — `success-50` / `success-500` / `success-700`.
- **Expirando** — `warning-50` / `warning-500` / `warning-700`. É também a
  família que lava o KPI de urgência inteiro.
- **Vencido** — `danger-50` / `danger-500` / `danger-700`. O contador do sino,
  texto branco sobre sólido, usa `danger-700` no claro e, no escuro,
  `danger-500` misturado a 55% com `ink-950` — porque os degraus escuros do
  DS são todos claros, feitos para texto sobre grafite.
- **Erro / Falha / Não encontrado** — badge neutro (`ink-100` / `ink-600`):
  não é pior nem melhor que vencido, é outra categoria, e o glifo diz qual.
- **Informação** — `info-50` / `info-500` / `info-700` existe na paleta e na
  ponte (`--info`), mas nenhum badge do Início a emite; fica disponível para
  toast e aviso.

No tema escuro os fundos `-50` viram o matiz a 16% de alfa e os degraus 500 /
700 clareiam; a regra de trio continua valendo.

### Named Rules

**A Regra das Duas Famílias.** Uma tela usa grafite e ouro; qualquer terceira
cor é cor de estado e só aparece onde há estado. O azul do portal legado não
entra nas telas do Águia: a ponte já redireciona `--accent` para `gold-600` e
`--accent-solid` para `ink-900`.

**A Regra do Ouro Raro.** Ouro cobre no máximo ~10% da tela e nunca é fundo
de bloco. Um botão primário preenchido por vez, e ele é a ação do momento:
no Início, "Instalar selecionados (N)" só existe com algo marcado; o
alternador "Selecionar / Cancelar" é de contorno e liga por `aria-pressed`
(lavado + borda `gold-600` + texto de marca).

**A Regra do Rótulo Grafite.** Texto sobre ouro é `ink-900`
(`--text-on-brand`), nunca branco. Onde o legado carrega texto branco sobre
`--accent-solid` (skip-link, `.primary` do estado vazio), a ponte faz o sólido
ser grafite.

**A Regra do Trio Semântico.** Fundo `-50` sempre com texto `-700` e
identidade `-500` na borda ou no ícone. Texto de estado nunca sai de
`--text-muted` nem da própria cor `-500`.

**A Regra do Token Verbatim.** `aguia-tokens.css` é cópia fiel do documento
do DS e não se edita aqui. Valor novo se pede no documento e se recopia. O que
o projeto precisa e o DS não dá (o modo "seguir o sistema", o vermelho sólido
escuro do contador) se deriva por `color-mix()` ou por guarda, no arquivo do
projeto.

## Typography

**Fonte de display:** Exo (600 / 700), com `system-ui` como reserva.
**Fonte de corpo:** Inter (400 / 500 / 600 / 700), com `system-ui`, `-apple-system`, `Segoe UI`.
**Fonte mono:** JetBrains Mono (400 / 600), com `SFMono-Regular`, `Consolas`.

As três são servidas pelo próprio portal (`static/aguia-fontes.css` +
`static/fonts/*.woff2`, subconjuntos latin e latin-ext, `font-display: swap`).
O portal roda numa VPN; uma estação sem internet cairia em `system-ui`, que é
o rosto que o DS recusa.

**Character:** Exo é a voz de longe — geométrica, levemente técnica, sempre
em peso 700 — e cobre exatamente o que se lê de relance: o título da página, o
número do KPI, o rótulo do botão, o cabeçalho da tabela e o overline. Inter é
a voz de perto e faz todo o resto. JetBrains Mono entra só onde um dígito
errado importa. A hierarquia vem da troca de família antes do tamanho: um
título de card em Exo 1.125rem lê como título mesmo sendo menor que a frase
de abertura em Inter.

### Hierarchy

- **Display / título de página** (Exo 700, 2rem, 1.1, -0.01em): o `<h1>`. Um por tela.
- **Metric** (Exo 700, 2rem, 1.1, -0.01em, numerais tabulares): o número do
  KPI. Enquanto carrega mostra "—" em `--text-muted` com `aria-busy`; zero e
  "ainda não sei" não são a mesma coisa.
- **Title** (Exo 700, 1.125rem): título de card e contagem da barra de seleção.
- **Button** (Exo 700, 0.875rem, 0.01em, `line-height: 1`): rótulo de botão em sentence case.
- **Overline** (Exo 700, 0.75rem, 0.12em, CAIXA ALTA): rótulo do KPI.
- **Table head** (Exo 700, 0.75rem, 0.04em, CAIXA ALTA): cabeçalho de tabela — meio
  tracking do overline, porque a linha é mais longa.
- **Body** (Inter 400, 1rem, 1.5): texto corrido; no celular, o nome do titular no cartão de linha.
- **Body sm** (Inter, 0.875rem): frase de abertura (máx. 62ch), célula de
  tabela, campo, texto explicativo (máx. 68ch). Peso 500 no nome do titular
  (`.ag-cell-main`).
- **Body xs** (Inter, 0.8125rem): linha de status, delta do KPI, subtexto de
  célula, tipo do documento, datas no celular, aviso da barra.
- **Label** (Inter 600, 0.8125rem, `--text-secondary`): rótulo de campo, sempre visível acima do controle.
- **Badge** (Inter 600, 0.8125rem, 1.4, sem caixa alta): o DS não desce abaixo
  de 0.75rem, e o badge fica um degrau acima disso.
- **Mono** (JetBrains Mono, 0.875rem, tabular): número de CNPJ/CPF, com
  `white-space: nowrap` — "0001-19" partido em duas linhas lê como dois números.

### Named Rules

**A Regra da Voz de Longe.** Exo só nos seis papéis acima e sempre em 700.
Um parágrafo em Exo ou um título em Inter estão errados antes de qualquer
medida.

**A Regra dos Dois Gritos.** Caixa alta existe em overline e cabeçalho de
tabela, e em mais nada. Botão, badge, título e link ficam em sentence case
pt-BR. No celular, o cabeçalho some e os prefixos "Emitido " / "Vence "
entram em sentence case no lugar dele.

**A Regra do Piso de 0.75rem.** Nenhum texto abaixo de 12px. O rótulo de
11px do legado foi religado a `--text-overline` pela ponte.

**A Regra do Mono Comparável.** Mono só para dado que se confere caractere a
caractere — documento, caminho, impressão digital. Texto de interface nunca.

## Layout

**A moldura** continua a do portal: sidebar fixa de 250px (`ink-900`) e
`.main-content` com teto de 1280px. A tela do Início empilha seus blocos com
`space-6` (1.5rem) entre irmãos; no celular, `space-4`.

**Ritmo.** Escala de 4px (`space-1` = 0.25rem até `space-16` = 4rem). Padding
de KPI e de card `space-6`; cabeça de card `space-5 space-6`; gaps de
toolbar `space-3` (linha) e `space-4` (coluna); célula de tabela 12px 16px.

**Grade de KPIs.** `repeat(auto-fit, minmax(min(180px, 100%), 1fr))` com gap
`space-4`. **Divergência registrada:** a referência de componentes do DS usa
200px de piso; aqui é 180px porque num portátil de 1366px a 125% a linha tem
~600px ao lado da sidebar e, a 200px, o terceiro KPI caía sozinho na segunda
linha. O `min(…, 100%)` faz o ponto de quebra ser o espaço real, não a tela.
Abaixo de 640px a grade é uma coluna (gap `space-3`), nunca 2 + 1.

**Toolbar do card.** Grade `minmax(0,1fr) auto` — filtros à esquerda (select
com largura própria, busca ocupando o resto), ações à direita — e não flex
com quebra, porque com flex a busca caía antes das ações. Entre 641 e 1024px a
toolbar vira duas linhas fixas (filtros; depois ações em `1fr auto auto`, com
os contornos no padding compacto de 8px 14px). Abaixo de 640px tudo empilha a
100%.

**Três breakpoints do DS**, com o comportamento que a tela deu a cada um:

| Largura | O que muda |
|---|---|
| ≤ 1024px (`--bp-md`) | Células a 10px, datas em `body-xs`, coluna CNPJ/CPF some e o documento desce para a segunda linha da célula do nome (`.ag-cell-stack`). Toolbar em duas linhas. |
| ≤ 640px (`--bp-sm`) | KPIs em coluna; o card da tabela perde moldura (cartão dentro de cartão custava 32px do nome); a tabela vira lista de cartões de linha; paginação em pílulas soltas que quebram linha. |
| 1280px | Teto do conteúdo, herdado do portal. |

**Densidade.** Linha de tabela com 44px (padding 12px 16px), sem zebra, sem
grade vertical; separação por fio sutil e hover dourado a 6%. O cabeçalho tem
44px de altura com o botão de ordenar ocupando toda ela.

### Named Rules

**A Regra do Rolar Por Dentro.** A página nunca rola de lado. A tabela rola
dentro de `.ag-table-scroll` (focável, `role="region"`), e abaixo de 640px nem
isso: vira cartões.

**A Regra do 44.** Botão, campo, select, checkbox, célula de cabeçalho,
item de menu, link de paginação: 44px de altura ou área mínima. O DS dá 40px
ao botão pelo padding; o `min-height: 44px` fecha o alvo sem mudar o desenho.

## Elevation & Depth

**Híbrido, tom primeiro.** A separação de planos é tonal — `ink-50` da página
contra o branco da folha, `ink-100` do cabeçalho contra a folha — e a sombra
só confirma. Toda sombra é de **tinta quente** (`rgba(45,32,20,…)`), nunca
preto puro: sobre off-white, o preto esfria a página. Card e KPI nascem com
`shadow-sm` em repouso; o que flutua (menu suspenso, barra de seleção) leva
`shadow-lg`; o cartão de linha no celular leva `shadow-xs`, quase só um fio.
O ouro tem sombra própria (`shadow-gold`) que aparece apenas no hover e no
foco do botão primário.

### Shadow Vocabulary

- **shadow-xs** (`0 1px 2px rgba(45,32,20,.06)`): cartão de linha no celular.
- **shadow-sm** (`0 1px 3px rgba(45,32,20,.08), 0 1px 2px rgba(45,32,20,.06)`): repouso de card e KPI.
- **shadow-md** (`0 4px 12px rgba(45,32,20,.10)`): disponível no DS; a tela não o usa.
- **shadow-lg** (`0 12px 28px rgba(45,32,20,.12)`): menu suspenso de exportar, barra de seleção.
- **shadow-xl** (`0 24px 48px rgba(45,32,20,.16)`): reservado a modal.
- **shadow-gold** (`0 10px 30px rgba(184,129,87,.34)`): hover/foco do botão primário, somado ao anel.
- **focus-ring** (`0 0 0 3px rgba(201,160,106,.5)`): anel de foco de tudo que é focável, por `box-shadow` em `:focus-visible` (campos também em `:focus`).

### Named Rules

**A Regra da Tinta Quente.** Nenhuma sombra com `rgba(0,0,0,…)`. Se precisa
de sombra, é um dos sete valores acima.

**A Regra do Foco Substituído.** `outline: none` só aparece na mesma
declaração que `box-shadow: var(--focus-ring)`. Anel de 3px, sempre visível.

## Shapes

Sete raios com significado fixo, todos do DS:

- **Pílula** (999px): botão, badge, link de paginação no celular.
- **20px** (`xl`): card e KPI — a folha grande.
- **14px** (`lg`): moldura de tabela, cartão de linha no celular, barra de seleção.
- **10px** (`md`): campo, select, caixa do ícone do KPI, menu suspenso.
- **4px** (`xs`): anel de foco do checkbox.
- **Círculo** (50%): spinner.
- 6px (`sm`) e 28px (`2xl`) existem no DS e a tela não usa.

**Bordas.** `bw-1` (1px) para card, campo, moldura de tabela e divisória;
`bw-2` (1.5px) para o contorno de botão (transparente no primário e no
fantasma, para a caixa não mudar entre variantes); `bw-3` (2px) para o
spinner. O KPI de urgência troca a cor da borda, não a espessura.

**Filete.** O KPI carrega uma linha de 3px em `grad-gold` no topo, recortada
pelo `overflow: hidden` do card. No KPI de urgência ela vira `warning-500`
sólida: o aviso não compete com a marca.

**Ícones.** Lucide em traço, `stroke-width: 2` (2.4 nos glifos de badge),
`currentColor`, sem preenchimento, inline no HTML ou em `BADGE_GLIFOS`.
18px de padrão, 16px dentro de botão, 20px no KPI (dentro de uma caixa de
40px com raio `md`).

### Named Rules

**A Regra do Raio pelo Papel.** Folha grande 20, moldura interna 14,
controle 10, acionável pílula. Um valor fora desses sete é defeito.

**A Regra do Traço.** Ícone é SVG Lucide em traço, sempre. Nunca emoji,
nunca caractere Unicode, nunca fonte de ícone, nunca `<img>`.

## Components

### Buttons

Firmes e curtos: Exo 700, pílula, 44px, `translateY(1px)` no clique, sem
brilho além do que o ouro já traz.

- **Shape:** pílula, padding 11px 22px, borda 1.5px (transparente quando não há contorno), `gap: space-2` para o ícone de 16px.
- **Primário:** `gold-500` com texto `ink-900`. Hover `gold-600` + `shadow-gold`; foco anel + `shadow-gold`. **Ligado** (`aria-pressed="true"`): lavado dourado, borda `gold-600`, texto de marca, sem sombra — o estado se lê pela borda, pelo texto e pelo rótulo que o JS troca.
- **Contorno:** transparente, texto primário, borda `--border-strong`. Hover e ligado: borda `gold-600`, texto de marca, lavado dourado.
- **Fantasma:** transparente, texto secundário. Hover: fundo `ink-100`, texto primário.
- **Pequeno** (`--sm`): 8px 16px, `body-xs`, 36px — só em ação secundária dentro de uma cabeça de card ("Limpar seleção").
- **Enviando:** `.ag-spin` de 14px em `currentColor` no lugar do ícone, mantendo a largura.
- **Disabled:** opacidade 0.55, `cursor: not-allowed`, permanece no DOM.
- **Sólido legado** (`--accent-solid` → `ink-900`, texto branco): só onde `style.css` ainda manda (skip-link, `.primary` do estado vazio). Não é uma variante nova; é a ponte impedindo branco sobre ouro.

### Inputs / Fields

- **Style:** folha branca (não deprimida), borda 1px `--border-default`, raio 10px, padding 10px 14px, 44px, Inter `body-sm`. Placeholder em `--text-muted`.
- **Hover:** borda forte. **Focus:** borda `gold-500` + anel de 3px. O fundo não muda.
- **Rótulo** (`.ag-label`) sempre visível acima, Inter 600 `body-xs` secundário, gap `space-1`. Placeholder não é rótulo.
- **Select:** mantém a seta nativa (desenhar uma exigiria cor literal em data URI); `padding-right: space-8`.
- **Checkbox:** 18px com `accent-color: gold-600`, dentro de um `.ag-check` de 44×44; foco por anel com raio 4px.

### Badges

- **Style:** pílula, Inter 600 `body-xs`, padding 3px 10px, sem borda, sem caixa alta; fundo `-50` + texto `-700` da família.
- **Glifo:** SVG Lucide de `BADGE_GLIFOS` (check, triângulo de alerta, x, círculo com ponto, círculo com interrogação) a 0.95em, `stroke-width: 2.4`, `aria-hidden`, com gap de 5px. Numa tabela de centenas de linhas a forma se reconhece antes da palavra.
- **Emissão:** só por `badgeStatus()` / `badgeAviso()` em `ui-common.js`, que gravam as duas classes (`badge-* ag-badge--*`); montar a string à mão no template é proibido por teste.
- **Variantes usadas:** success (Ativo), warning (Expirando), danger (Vencido), neutral (Erro, Falha, Não encontrado, valor desconhecido). `gold` e `info` existem no CSS e não são emitidas.

### Cards / Containers

- **Card** (`.ag-card`): folha branca, borda 1px padrão, raio 20px, `shadow-sm`. Cabeça `space-5 space-6` com título Exo `title` à esquerda, ações à direita, divisória sutil. É a moldura da tabela, da barra de seleção e de "Meus computadores".
- **KPI** (`.ag-kpi`): mesmo card com padding `space-6`, filete de 3px, rótulo overline apagado, número Exo 2rem tabular, delta `body-xs`; caixa de ícone 40px à direita (`ink-100` / `ink-600`, raio 10px, Lucide 20px). Sem hover, sem elevação.
- **KPI de urgência** (`.cg-kpi--atencao`): o card inteiro lavado em `warning-50`, borda e filete `warning-500`, rótulo e delta `warning-700`, caixa do ícone branca com ícone `warning-700`. **Um por tela** — o que pede ação.
- **Menu suspenso** (`<details>` legado com gatilho `.ag-btn--outline`): lista em folha branca, borda padrão, raio 10px, `shadow-lg`, itens Inter `body-sm` com 44px.

### Tabela

- **Moldura** (`.ag-table-wrap`): borda 1px, raio 14px, `overflow: hidden`, folha branca; rolagem horizontal dentro de `.ag-table-scroll`.
- **Cabeçalho:** `ink-100`, Exo 700 0.75rem caixa alta 0.04em, `--text-secondary`, 44px; botão de ordenar herda tudo e alinha à esquerda como a célula; coluna ativa em texto de marca (o único ouro do cabeçalho).
- **Célula:** 12px 16px, `border-top` sutil, Inter `body-sm`; nome em peso 500; datas em numerais tabulares; documento em `.cg-doc` (tipo em `body-xs` apagado + número em JetBrains Mono, sem quebra no hífen).
- **Hover:** ouro a 6% (`color-mix`), 12% no escuro.
- **Seleção:** coluna de checkbox nasce escondida e aparece com `.is-selecionando` no card; a largura devolvida vai para o nome.
- **Cartão de linha (≤ 640px):** `display: block` na tabela, `thead` oculto acessivelmente, cada `tr` como grade `nome status / emissao / vencimento` (com `sel` à esquerda em 44px no modo de seleção), folha branca, borda padrão, raio 14px, `shadow-xs`, padding `space-3 space-4`, gap `space-1 space-3`. Os `role` explícitos no HTML e no JS mantêm a semântica que `display: block` apaga.

### Navigation

- **Sidebar:** a do portal (`style.css`, 250px, fixa) pintada pela ponte: fundo `ink-900`, texto `ink-400`, hover e ativo em lavado dourado, texto ativo `gold-300`, "Sair" em `danger-500`. Ícones Heroicons outline legados permanecem até a sidebar migrar.
- **Paginação:** o controle segmentado do portal, 44px; no celular, pílulas soltas que quebram linha com gap `space-2`.

### Barra de seleção

Um `.ag-card` no fluxo do `<main>` (não fixo — fixo taparia a paginação no
celular), raio 14px, `shadow-lg`, cabeça com a contagem em `title` à esquerda
e ações à direita ("Limpar seleção" fantasma pequeno; "Instalar nesta máquina"
primário, escondido sem agente ativo). Avisos abaixo em `body-xs`
`warning-700`. Abaixo de 640px a cabeça empilha e os botões esticam.

### Motion

Três durações (`dur-fast` 120ms, `dur-base` 200ms, `dur-slow` 320ms) e uma
curva (`ease-standard`, `cubic-bezier(.2,0,0,1)`); a ponte aponta os nomes
legados (`--ease-out`, `--ease-spring`, `--duration-*`) para elas. Transições
de 120ms em botão e campo; spinner de 0.8s linear; `prefers-reduced-motion`
zera as transições da tela e desacelera o spinner para 1.6s em vez de
escondê-lo.

## Do's and Don'ts

### Do:

- **Do** carregar, em toda tela que migrar, os três arquivos na ordem `aguia-tokens.css` → `aguia-components.css` → o CSS da tela, depois de `style.css` — a ordem é o que faz o Águia vencer os nomes coincidentes.
- **Do** ligar todo nome legado novo (`--algo` de `style.css`) a um token do Águia na ponte da tela, e nunca redefinir um `--gold-*` / `--ink-*` no projeto.
- **Do** manter um só botão primário preenchido por tela: o da ação do momento, que pode nascer escondido e aparecer quando ela existe (como "Instalar selecionados (N)").
- **Do** usar o trio completo de estado: fundo `-50`, texto `-700`, identidade `-500` na borda ou no ícone.
- **Do** acompanhar cor de estado de um segundo canal: glifo no badge, palavra ao lado, borda no toggle.
- **Do** dar 44px a todo clicável e 3px de anel em ouro a todo focável.
- **Do** escolher Exo 700 para o que se lê de longe e Inter para o resto; JetBrains Mono só para dado comparável.
- **Do** emitir badge só por `badgeStatus()` / `badgeAviso()`, com o glifo SVG de `BADGE_GLIFOS`.
- **Do** escrever `color-mix(in srgb, var(--token) N%, …)` quando precisar de uma transparência que o DS não nomeia.
- **Do** manter a rolagem dentro da moldura e, abaixo de 640px, trocar tabela por cartões de linha com `role` explícito.

### Don't:

- **Don't** pintar texto branco sobre ouro, nem usar `gold-*` como fundo de bloco; o lavado é `gold-glow`.
- **Don't** trazer o azul do portal legado para uma tela do Águia, nem uma terceira cor de marca.
- **Don't** editar `aguia-tokens.css` localmente; ele é cópia verbatim do documento do DS.
- **Don't** escrever cor, sombra, raio ou tamanho literal onde existe token; a única exceção declarada é dimensão de glifo.
- **Don't** usar sombra preta; toda sombra é `rgba(45,32,20,…)` ou `shadow-gold`.
- **Don't** usar `outline: none` sem `box-shadow: var(--focus-ring)` na mesma regra.
- **Don't** usar emoji, caractere Unicode ou fonte de ícone como ícone; Lucide em traço, inline.
- **Don't** pôr caixa alta fora de overline e cabeçalho de tabela; rótulo, botão e badge ficam em sentence case pt-BR.
- **Don't** descer abaixo de 0.75rem.
- **Don't** carregar fonte de CDN; as três famílias vivem em `static/fonts`.
- **Don't** resolver tema escuro em regra de componente com `@media (prefers-color-scheme)` cru; o token já muda sob a guarda `:root:not([data-theme="light"])`.
- **Don't** lavar mais de um KPI por tela; o lavado marca o único que pede ação.
- **Don't** usar gradiente fora do filete de 3px do KPI.
