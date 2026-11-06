# Spike de layout fluido: o que `proposta.css` muda

`proposta.css` é carregado por último, por `add_style_tag`, só na captura. Não muda nenhum arquivo do repositório. As linhas citadas abaixo são do commit `HEAD` dd72220.

| # | Mudança | Regra de hoje que ela sobrepõe |
|---|---|---|
| 1 | Menu com `clamp(212px, 13.02vw, 250px)`: 212 px no notebook, 250 px a 1920. O `margin-left` do main acompanha. | `.sidebar { width: 250px }` em `static/style.css:421`; `.main-content { margin-left: 250px }` em `static/style.css:539` |
| 1b | Marca numa linha só (15 a 18 px) e subtítulo com reticências. | `.brand-text h2` em `static/style.css:466`; `.brand-text span` em `static/style.css:474` |
| 1c | Respiro lateral dos itens do menu um pouco menor. | `.sidebar-nav a` em `static/style.css:507` (`padding: .65rem 1rem`) |
| 2 | Respiro do main fluido: cerca de 17 px no notebook, 22 px a 1920. | `.main-content { padding: 1.5rem }` em `static/style.css:540` |
| 2b | Distância entre blocos fluida: cerca de 12 px a 16 px. | `.cg-painel > * + *` em `static/aguia-listas.css:13`; `.ag-page__head { margin-bottom }` em `static/aguia-components.css:37` |
| 3 | Sino e tema saem da fila própria e vão para a linha do título, em posição absoluta no canto. O cabeçalho reserva 7,5rem à direita para eles. | `.topbar-actions { margin-bottom: 1.5rem }` em `static/style.css:2562-2571`. A barra é criada por `static/ui-common.js:247-252`. |
| 4 | Título fluido: `clamp(1.375rem, 1.5625vw + 2px, 2rem)`, cerca de 26 px no notebook e 32 px a 1920. | `.ag-page__title` em `static/aguia-components.css:41`. O token é `--fs-title` em `static/aguia-ponte.css:76`. |
| 4b | O texto de introdução pode ir até 90 caracteres por linha (era 62). | `.ag-page__lead { max-width: 62ch }` em `static/aguia-components.css:53` |
| 5 | Cartão de número compacto: o número fica ao lado da frase e a altura cai de cerca de 176 px para cerca de 100 px. As cores não mudam. | `.ag-kpi` em `static/aguia-components.css:313`; `.ag-kpi__value` em `static/aguia-components.css:343`; `.cg-kpi__icone` em `static/aguia-listas.css:28` |
| 5b | Os quatro números ficam numa linha até 769 px (antes passavam para 2×2 abaixo de 1100 px). | `.cg-kpis--quatro` em `static/aguia-listas.css:87-88` |
| 6 | Célula da tabela: letra de 13 a 14 px e espaço interno de 4 a 6 px por 8 a 12 px, tudo fluido. | `.ag-table` em `static/aguia-components.css:498`; `.ag-table th` em `static/aguia-components.css:504`; `.ag-table td` em `static/aguia-components.css:518` |
| 6b | Cartão da tabela e linha "Atualizado em" com menos respiro. | `.cg-tabela-card` em `static/aguia-listas.css:102`; `.cg-status` em `static/aguia-listas.css:360` |
| 6c | Paginação numa linha só: contagem à esquerda, páginas à direita. Antes era uma coluna centrada com cerca de 80 px de altura. | `.cg-page-nav` em `static/style.css:1909`; `.cg-page-link` em `static/style.css:1999` |
| 7 | A tabela ocupa a altura que sobra: o main vira uma coluna de `100vh` e só a tabela rola, com o cabeçalho grudado no topo. O piso é de 18rem. Vale a partir de 769 × 560 px. | Substitui, para Início e Histórico, `.table-container--cheia` (só valia com `min-height: 800px`) em `static/style.css:3253` e o teto `min(68vh, 760px)` em `static/style.css:3213` |
| 8 | Carteiras: a lista de pessoas ocupa `minmax(20rem, 30%)`, antes `minmax(18rem, 22rem)`. | `.cg-cart-layout` em `static/aguia-carteiras.css:17` |
| 8b | Carteiras: a lista vai até perto do fim da janela, com `calc(100vh - 21rem)` em vez de `- 30rem`. | `.cg-op-rolagem` em `static/aguia-carteiras.css:39` e `:42` |
| 8c | Carteiras: o selo e a contagem descem para baixo do nome quando não cabem, em vez de espremer o nome em 3 linhas. | `.cg-op-item` em `static/aguia-carteiras.css:72` |

## Ficou de fora do spike

- As colunas com largura mínima que forçam 3 linhas por registro ficam no Instalador: `.cg-col-cert` e `.cg-col-sieg-msg` em `static/aguia-instalador.css:132-134`, e `.ag-etapas` em `static/aguia-components.css:1095`. Também estão em Usuários › Computadores (`static/aguia-usuarios.css:211-213`). Nenhuma dessas telas está entre as três do spike, e Início e Histórico não têm esse problema.
- O modo recolhido do menu e o celular não foram capturados. A especificidade de `body.sidebar-collapsed` (`static/style.css:1508-1513`) deve manter o comportamento de hoje.

## Versão 2 (06/11/2026): `proposta-v2.css` + `proposta-v2.js`

`proposta-v2.css` é a v1 inteira mais um bloco no fim. `proposta.css` não mudou.

| # | Mudança | Regra de hoje que ela sobrepõe |
|---|---|---|
| v2.1 | Abaixo de 1600 px, sem preferência salva, o menu começa recolhido. No produto é uma linha: `const salvo = localStorage.getItem(SIDEBAR_COLLAPSED_STORAGE); const collapsed = salvo === null ? window.innerWidth < 1600 : salvo === "1";`. No spike, `proposta-v2.js` aplica a classe depois do carregamento, porque a CSP do portal barra `<script>` inline. | `applySidebarState` em `static/ui-common.js:212-217` (linha 214) |
| v2.2 | Trilho de ícones com 72 px em vez de 76, e o `margin-left` do main acompanha. O nome do item aparece no balão que já existe (`initSidebarDicas`) e no `title`. O botão redondo continua abrindo o menu (212 px) e grava a escolha. | `body.sidebar-collapsed .sidebar` em `static/style.css:1508`; `body.sidebar-collapsed .main-content` em `static/style.css:1512` |
| v2.3 | Margem lateral do main: `clamp(2rem, 3vw, 3.5rem)`, cerca de 46 px no notebook e 56 px a 1920. O sino e o tema acompanham. | `.main-content { padding }` em `static/style.css:540` (na v1, `--pp-pad`) |
| v2.4 | Respiro interno da moldura da tabela: cerca de 20 px dos lados no notebook (era cerca de 13 na v1 e 16 hoje). | `.cg-tabela-card { padding }` em `static/aguia-listas.css:102` |

### Medidas no notebook (1536×730 a 1,25)

| Tela | Versão | Largura da tabela (Carteiras: área das listas) | Espaço menu → tabela | Espaço tabela → borda | Linhas ou pessoas à vista | A página rola? |
|---|---|---|---|---|---|---|
| Início | Hoje | 1202 | 42 | 42 | 6 | sim (1007 px) |
| Início | v1 | 1263 | 31 | 31 | 8 | não |
| Início | v2 | **1328** | **68** | **68** | **9** | não |
| Histórico | Hoje | 1202 | 42 | 42 | 10 | sim (842 px) |
| Histórico | v1 | 1263 | 31 | 31 | 10 | não |
| Histórico | v2 | **1328** | **68** | **68** | 10 | não |
| Carteiras | Hoje | 1238 | 24 | 24 | 2 pessoas | não |
| Carteiras | v1 | 1291 | 17 | 17 | 5 pessoas | não |
| Carteiras | v2 | **1372** | **46** | **46** | 5 pessoas | não |

### Medidas no monitor, v2 (1920×1080)

- **Início:** tabela de 1388 px (hoje, a 1920×911, são 1404 px), com 141 px de espaço de cada lado. 10 linhas à vista, a página não rola.
- **Histórico:** os mesmos números do Início.
- **Carteiras:** área das listas com 1440 px e 115 px de espaço de cada lado. 7 pessoas à vista.

### Outras janelas, v2

| Janela | Início | Histórico | Carteiras |
|---|---|---|---|
| 1366×657 | tabela de 1173 px, 7 linhas, a página não rola | 10 linhas | 4 pessoas |
| 1280×600 | tabela de 1094 px, 5 linhas, a página rola 39 px | 9 linhas | 3 pessoas |

Nenhuma janela teve rolagem lateral. No teste, o balão "Histórico" apareceu ao passar o mouse, e o botão abriu o menu de 72 px para 212 px.
