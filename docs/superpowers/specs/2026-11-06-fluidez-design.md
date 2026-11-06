# Fluidez entre resoluções — design

Data: 06/11/2026. Aprovado na conversa a partir da versão 2 da prévia (v2). A referência visual está em `docs/superpowers/specs/2026-11-06-fluidez-spike/`.

## Intenção

O Robério gosta do visual do portal, mas sente as telas "espremidas" no notebook. O notebook tem 1920×1080 com escala de 125%, o que dá 1536×730 px úteis no navegador.

Os dois sentidos incomodam:

- **Altura:** é preciso rolar para chegar aos dados. No Início, a primeira linha da tabela começa em 46% da altura, cabem 6 linhas e a página ainda rola.
- **Largura:** as colunas ficam apertadas e há registros com 3 ou mais linhas de texto.

Nas palavras dele, o que conta é: "quando a tabela central está com mais espaço lateral e com mais dados apresentados sem letras enormes limitando a visão, colabora muito para uma vista de excelência".

Ele escolheu a v2, que fez "um pouco dos dois": a tabela ficou mais larga **e** ganhou mais respiro dos lados. Esse espaço saiu do menu.

## Objetivos

1. No notebook (1536×730):
   - a tabela fica mais larga do que hoje;
   - a tabela tem mais respiro entre ela e o menu, e entre ela e a borda da janela;
   - cabem mais linhas na tela;
   - a página não rola: só a tabela rola.
2. No monitor de 1920×1080, nada piora. O menu continua aberto como hoje.
3. As mesmas regras valem para **todas** as páginas internas, inclusive as que a prévia não mediu: Trilha, SIEG, Computadores, Movimentos, Custódia, Acompanhamento, Duplicidades, Configuração e Usuários.
4. Nenhum registro de tabela ganha 3 ou mais linhas de texto por falta de largura, se houver como evitar (ver "Colunas apertadas").

## Fora do escopo

- Cores, família de fonte, raios, sombras e ícones do Águia DS.
- O desenho de cada página: ordem dos blocos, textos e quais colunas existem.
- A tela de login e a página de retorno da bandeja.
- A Wiki (largura fixa de 60rem): fica como está.

## O que não pode acontecer, mesmo que o resto funcione

- Letra maior do que hoje, em qualquer lugar.
- Rolagem dupla, com a página e a tabela rolando juntas, em janela de 769×560 ou maior nas páginas de lista.
- Rolagem lateral da **página** em qualquer janela de 1093 px ou mais. Rolagem lateral dentro da moldura da tabela é aceitável como último recurso.
- O monitor de 1920 ficar com a tabela visivelmente mais estreita ou com menos linhas do que hoje.
- Mexer em `templates/dashboard.html` ou `static/aguia-dashboard.css`. Os dois têm mudanças locais do Robério ainda não commitadas, e ele mandou deixar como estão. O Dashboard recebe só o que vier das regras compartilhadas.

## Restrições

- **CSP:** o portal não aceita `<script>` inline. Qualquer JS vai em arquivo de `static/`.
- **Medidas do navegador:** são px CSS, depois da escala do Windows. As janelas de teste são as da memória do projeto: 1536×730 com dpr 1,25 (o notebook), 1366×657, 1280×600, 1093×526, 390×700 (celular) e 1920×1080.
- **Commits:** o hook de pré-commit roda a suíte inteira.
- **Validação de interface no navegador:** axe pelo `/static`, transições congeladas antes de trocar o tema.

## O que foi decidido (v2)

Os valores vêm de `proposta-v2.css`, que foi medida. A tabela de "regra de hoje → arquivo:linha" está em `mudancas.md`, na mesma pasta.

### 1. Menu

- **Abaixo de 1600 px de largura** (e acima de 768), quando a pessoa ainda não escolheu, o menu começa **recolhido**: só ícones, num trilho de **72 px**. Hoje o recolhido tem 76 px.
  - O nome do item aparece no balão que já existe (`initSidebarDicas`) e no `title`.
  - O botão redondo continua abrindo o menu e grava a escolha.
- **A partir de 1600 px**, quando a pessoa não escolheu, o menu fica aberto, como hoje.
- **Menu aberto:** largura de `clamp(212px, 13.02vw, 250px)`. Dá 212 px no notebook e 250 px a 1920. A marca fica numa linha só, e o subtítulo usa reticências se não couber.
- **A escolha salva continua valendo.** Mas, para todo mundo ver o novo comportamento uma vez, a chave do `localStorage` muda de nome. A escolha antiga é ignorada **uma vez**; daí em diante o portal volta a lembrar. Decisão minha, que o Robério viu e não contestou.
- **Onde fica a regra:** `applySidebarState` em `static/ui-common.js:212-217`, mais a constante `SIDEBAR_COLLAPSED_STORAGE` na linha 18. A regra fica assim:

  ```js
  const salvo = localStorage.getItem(SIDEBAR_COLLAPSED_STORAGE);
  const collapsed = salvo === null ? window.innerWidth < 1600 : salvo === "1";
  ```

### 2. Respiro lateral e cabeçalho

- **Margem lateral do main:** `clamp(2rem, 3vw, 3.5rem)`. Dá cerca de 46 px no notebook e 56 px a 1920.
- **Respiro de cima e de baixo:** `clamp(.75rem, 1.6vw - .5rem, 1.5rem)`.
- **Distância entre blocos:** `clamp(.625rem, 1.04vw - .25rem, 1rem)`.
- **Sino e tema** saem da fila própria (`.topbar-actions`) e vão para a **linha do título**, no canto direito. O cabeçalho reserva o lugar deles. Eles acompanham a borda direita da coluna de 1440 px quando ela está centrada.
- **Título:** `clamp(1.375rem, 1.5625vw + 2px, 2rem)`. Dá cerca de 26 px no notebook e 32 px a 1920. Fica menor, nunca maior.
- **Texto de introdução:** até 90ch por linha (hoje é 62ch).

### 3. Cartões de números (KPI)

- **Versão compacta:** o número fica ao lado da frase, e a altura cai de cerca de 176 px para cerca de 100 px.
  - As cores não mudam.
  - O ícone fica com 32 px.
  - O valor fica entre `clamp(1.375rem, 1.5625vw, 1.875rem)`.
- **Linha de quatro cartões:** continua em 4 colunas até o espaço ficar estreito de verdade. Hoje vira 2×2 em 1100 px de janela, e isso deixa de acontecer.
- **Com o menu aberto no notebook**, o texto do cartão pode ocupar 2 linhas. O que não pode é a palavra ser partida.

### 4. Tabela

- **Letra da célula:** `clamp(.8125rem, .52vw + 5.4px, .875rem)`, ou seja, 13 a 14 px.
- **Espaço interno da célula:** 4 a 6 px na vertical e 8 a 12 px na horizontal, fluido (valores em `proposta-v2.css`, bloco 4).
- **Moldura:** respiro interno de cerca de 20 px dos lados no notebook: `clamp(1rem, 1.3vw, 1.5rem)`.
- **Paginação:** numa linha só, com a contagem à esquerda e as páginas à direita.
- **Altura:** a tabela usa **a altura que sobra da janela**. O main vira uma coluna da altura da tela, só a tabela rola, e o cabeçalho da tabela fica grudado no topo.
  - Vale a partir de 769×560.
  - Piso de 18rem: numa janela mais baixa, a página volta a rolar.
  - Substitui o limiar `min-height: 800px` de `.table-container--cheia` e o teto `min(68vh, 760px)`.

### 5. Carteiras

- **Lista de pessoas:** `minmax(20rem, 30%)`.
- **Altura da lista:** vai até perto do fim da janela, com `max(12rem, calc(100vh - 21rem))`.
- **Selo e contagem:** descem para baixo do nome quando não cabem. O nome não pode ser espremido em 3 linhas.

### 6. Colunas apertadas (páginas fora da prévia, "mesmas regras")

O Robério autorizou estender as regras sem uma nova prévia. Os problemas medidos estão nos achados 4 a 6 do levantamento:

- **Trilha e Computadores:** as molduras com `overflow: visible` (`static/aguia-instalador.css:55`, `static/aguia-usuarios.css:211-213`) voltam a ter `overflow-x: auto`. A página não pode rolar de lado.
- **Breakpoints:** os que medem a janela mas querem medir o espaço da tabela passam a ser `@container` na moldura.
  - `static/aguia-listas.css:383-390` (o modo compacto que esconde CNPJ, hoje com `max-width: 1024px` que nunca dispara).
  - O 2×2 dos KPIs.
  - Hoje o CSS não tem nenhum `@container`.
- **Colunas com largura mínima** (`.cg-col-cert` 12rem e `.cg-col-sieg-msg` 14rem em `static/aguia-instalador.css:132-134`) e **etapas que quebram linha** (`.ag-etapas`, `static/aguia-components.css:1095`): quando o espaço apertar, a coluna secundária cede primeiro.
  - As Etapas podem ficar mais compactas.
  - A mensagem do SIEG pode ser cortada com o texto inteiro no `title`.
- **Ações de Computadores:** os três botões em `nowrap` ocupam 286 px. Abaixo de cerca de 900 px de moldura, podem quebrar ou ficar mais compactos.

## Metas medidas (a prévia v2 atingiu; o produto final não pode ficar abaixo)

Notebook, 1536×730, dpr 1,25:

| Página | Largura da tabela | Respiro de cada lado | Linhas à vista | A página rola? |
|---|---|---|---|---|
| Início | ≥ 1328 | ≥ 68 | ≥ 9 | não |
| Histórico | ≥ 1328 | ≥ 68 | 10 | não |
| Carteiras (área das listas) | ≥ 1372 | ≥ 46 | ≥ 5 pessoas | não |

No monitor de 1920×1080, com o menu aberto:

- **Início e Histórico:** tabela de cerca de 1388 px (hoje são 1404) e 10 linhas sem rolar a página.
- **Carteiras:** 7 pessoas.

Nas outras janelas:

- **1366×657:** o Início mostra 7 linhas e a página não rola.
- **1280×600:** é aceitável que a página role um pouco. Na prévia, rolou 39 px.

## O que fica com quem construir

- **Onde cada regra mora.** De preferência, nos arquivos e tokens que já existem: `aguia-tokens.css`, `aguia-ponte.css`, `aguia-components.css`, `aguia-listas.css` e `style.css`, e não num arquivo de sobreposição carregado por último como na prévia. A prévia é referência de valores, não de estrutura.
- **O tema escuro e o celular (390×700).** Recebem as mesmas regras. É preciso conferir se nada quebrou; não há meta nova para eles.
- **As páginas sem tabela** (Configuração, Diagnóstico, Dashboard): recebem só o cabeçalho, o respiro e o menu.
- **O valor exato do limiar de `@container`** de cada tabela, medido nas janelas de teste.

## Decisões tomadas depois da revisão (minhas; o Robério confere ao ler)

1. **"Só a tabela rola" fora do Início e do Histórico.** O preenchimento da altura vale para as páginas cujo último bloco do main é **uma** tabela de lista. Para isso, essas páginas passam a usar a mesma moldura (`.cg-tabela-card`) ou uma classe compartilhada equivalente.
   - Páginas com várias tabelas, abas com blocos empilhados ou formulários **não** preenchem a altura. Nelas a página rola normalmente.
   - Elas recebem só o cabeçalho, o respiro, o KPI compacto e as correções de largura.
   - Quem decide qual página entra em qual grupo é quem constrói, olhando o markup. A lista vai no plano.
2. **Menu entre 769 e 900 px.** O comportamento de hoje continua: auto-recolhido, com o botão centralizado (`style.css:2683`). Só o trilho passa de 76 para 72 px, em toda largura acima de 768. A largura fluida do menu **aberto** vale a partir de 901 px, como na prévia.
3. **Páginas sem `.ag-page__head` como filho direto do main.** Nelas, sino e tema ficam na fila própria, como hoje. A regra que os sobe para a linha do título só vale onde esse cabeçalho existe (por exemplo, `.main-content:has(> .ag-page__head)`). Nenhum template do Dashboard é editado.
4. **Dashboard.** Recebe só o que vier das regras compartilhadas. Quem constrói confere o Dashboard nas janelas de teste.
   - Se alguma regra compartilhada estragar o Dashboard, ela é restringida no CSS compartilhado para não alcançá-lo.
   - Nunca se edita `templates/dashboard.html` nem `static/aguia-dashboard.css`.
5. **Nova chave do menu:** `analise_certidigital_sidebar_collapsed_v2`. Só `static/ui-common.js` usa a chave antiga (linhas 18, 214 e 234), conferido em 06/11. A chave antiga pode ser apagada na primeira gravação.
6. **Testes.** Os testes que fixam valores antigos de CSS ou JS (limiar de 800 px, trilho de 76 px, 62ch e semelhantes) são atualizados junto com a mudança. Nenhum teste é apagado para passar.
7. **Aceite das páginas sem meta numérica.** Usar os dados de demonstração de `scripts/wiki_demo/seed_wiki.py` nas janelas de teste. Para cada página, a resposta é sim ou não:
   - a página rola de lado em 1093 px ou mais? (não pode);
   - algum registro tem 3 ou mais linhas de texto no notebook? (não pode).
8. **1280×600 e a rolagem dupla.** Quando a janela é baixa demais para o piso de 18rem, a página rola e a tabela usa o próprio piso. A regra contra rolagem dupla vale quando a janela comporta o piso.

## Riscos conhecidos

- **Menu só com ícones:** Dashboard, Duplicidades e Carteiras ficam parecidos e só se distinguem ao passar o mouse. O Robério viu e aprovou a v2 assim.
- **Uma escolha antiga se perde uma vez,** por causa da troca da chave do menu.
- **No monitor de 1920 a tabela fica 16 px mais estreita.** Isso vem do respiro interno maior da moldura e está dentro do "nada piora".
