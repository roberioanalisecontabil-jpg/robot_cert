# 03 · Responsive Design

Diretrizes para interfaces que se adaptam a diferentes tamanhos de tela e dispositivos. Consultar sempre que o layout precisar funcionar além de um único breakpoint.

## 1. Mobile First vs. Desktop First

- **Mobile First (padrão recomendado):** desenhar e codificar para a menor tela primeiro, adicionar complexidade progressivamente via `min-width`. Força priorização de conteúdo (só cabe o essencial) e resulta em CSS mais enxuto.
- **Desktop First:** parte do layout mais complexo e remove/reorganiza via `max-width`. Só se justifica quando o produto é comprovadamente desktop-only (ex.: ferramenta interna B2B pesada, dashboard analítico complexo).
- Regra prática: se mais de 20-30% do tráfego real (ou esperado) é mobile, sempre mobile-first.

## 2. Breakpoints (referência de mercado)

```
--bp-xs: 0px      (mobile pequeno)
--bp-sm: 640px    (mobile grande / phablet)
--bp-md: 768px    (tablet retrato)
--bp-lg: 1024px   (tablet paisagem / laptop pequeno)
--bp-xl: 1280px   (desktop)
--bp-2xl: 1536px  (desktop grande)
```

Breakpoints devem ser definidos pelo **conteúdo quebrando**, não por dispositivos específicos — usar os valores acima como ponto de partida, mas ajustar quando o layout visivelmente quebra entre eles.

## 3. Grid responsivo

- Mobile: 4 colunas (ou single column com stacking total).
- Tablet: 8 colunas.
- Desktop: 12 colunas.
- Gutter cresce com o breakpoint (16px mobile → 24px desktop).

## 4. Flexbox vs. Grid (CSS)

- **Flexbox:** ideal para distribuição em uma dimensão (linha OU coluna) — barras de navegação, grupos de botões, cards em linha.
- **CSS Grid:** ideal para layout bidimensional (linhas E colunas simultaneamente) — dashboards, galerias, layouts de página completos.
- Regra prática: se você está tentando alinhar itens em duas dimensões com Flexbox usando `flex-wrap` e margins manuais, provavelmente deveria ser Grid.

## 5. `clamp()` para tipografia e espaçamento fluido

Permite valores que escalam suavemente entre um mínimo e um máximo, sem media queries:

```css
font-size: clamp(1.5rem, 1rem + 2vw, 2.5rem);
padding-inline: clamp(1rem, 5vw, 4rem);
```

- Sintaxe: `clamp(mínimo, valor-preferencial-fluido, máximo)`.
- Reduz drasticamente o número de breakpoints necessários para tipografia/espaçamento de heroes e headings.
- Sempre testar o valor mínimo em telas de 320px de largura para garantir legibilidade.

## 6. Layout fluido vs. fixo

- Preferir unidades relativas (`%`, `rem`, `fr`, `vw`/`vh` com moderação) a `px` fixos em containers e larguras de coluna.
- `max-width` no container principal (tipicamente 1280-1440px) evita que o conteúdo estique demais em monitores grandes, prejudicando a leitura (linha de texto muito longa).
- Imagens sempre com `max-width: 100%` e `height: auto` para nunca vazar do container.

## 7. Responsividade avançada

- **Container queries** (`@container`) — permitem que um componente se adapte ao tamanho do seu **container pai**, não da viewport inteira. Essencial para componentes reutilizáveis (ex.: um card que muda de layout dependendo se está numa sidebar estreita ou numa área principal larga).
- **Aspect-ratio** (`aspect-ratio: 16/9`) — evita layout shift em imagens/vídeos antes de carregar.
- **Object-fit** (`cover`/`contain`) — controla como mídia se comporta dentro de containers de proporção fixa.

## 8. Telas ultrawide (21:9, 32:9, monitores 4K+)

- Nunca deixar conteúdo esticar por toda a largura — usar `max-width` no container de conteúdo (leitura) mesmo que o layout de fundo/background ocupe 100%.
- Considerar uso do espaço lateral extra para elementos secundários (sidebar persistente, preview) em vez de simplesmente aumentar margens vazias.
- Grids com `auto-fit`/`auto-fill` + `minmax()` se adaptam melhor a larguras muito variáveis do que breakpoints fixos:
```css
grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
```

## 9. Tablets

- Tratar como classe própria, não como "mobile grande" nem "desktop pequeno" — orientação retrato vs. paisagem muda drasticamente o layout ideal.
- Elementos de toque (botões, links) precisam de área mínima de 44x44px (iOS HIG) ou 48x48px (Material Design), mesmo que visualmente pareçam menores.
- Considerar uso híbrido de mouse/trackpad (iPad com Magic Keyboard) — não assumir touch-only.

## 10. Dispositivos dobráveis (foldables)

- Usar `env(fold-*)` e a API de Viewport Segments quando disponível para detectar a dobra física e evitar que conteúdo crítico (botões, texto) fique exatamente sobre a dobra.
- Testar em modo "livro" (dobra vertical, duas telas lado a lado) e "notebook" (dobra horizontal, tela dividida em cima/embaixo).
- Fallback seguro: tratar como tela única responsiva quando a API de segmentos não está disponível — nunca depender exclusivamente de detecção de dobra.

## 11. Checklist de Responsividade

- [ ] Layout desenhado mobile-first, com breakpoints definidos pelo conteúdo?
- [ ] Container com `max-width` para evitar linhas de texto muito longas em telas grandes?
- [ ] Tipografia e espaçamento de heroes usando `clamp()` em vez de múltiplos breakpoints fixos?
- [ ] Áreas de toque com no mínimo 44x44px em qualquer breakpoint?
- [ ] Imagens e mídia com `max-width: 100%` e `aspect-ratio` definido?
- [ ] Testado em pelo menos: 320px, 768px, 1024px, 1440px e uma resolução ultrawide?
