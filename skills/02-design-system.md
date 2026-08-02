# 02 · Design System

Define os tokens e componentes visuais reutilizáveis que garantem consistência em toda a interface. Consultar ao definir qualquer decisão visual concreta (cor, tipo, espaçamento, componente).

## 1. Cores

### 1.1 Estrutura de paleta
- **Primária** — cor de marca, usada em CTAs principais e elementos de destaque.
- **Secundária** — complementa a primária, usada com moderação.
- **Neutras** — escala de cinza para texto, bordas, fundos (geralmente 8-10 tons).
- **Semânticas** — success (verde), warning (amarelo/laranja), error (vermelho), info (azul). Nunca usar cor sozinha para transmitir significado (acessibilidade — ver `04-accessibility.md`).

### 1.2 Regras de uso
- Nunca mais de 1 cor primária + 1 secundária + neutras + semânticas em uma mesma tela.
- Contraste mínimo AA: 4.5:1 para texto normal, 3:1 para texto grande (≥18px ou 14px bold) e componentes de UI.
- Definir a paleta em modo claro **e** escuro desde o início — não é apenas "inverter" as cores, tons neutros precisam de ajuste de luminância para não cansar a vista.

### 1.3 Escala de cor recomendada (formato token)
```
--color-primary-50 a --color-primary-900   (10 tons, do mais claro ao mais escuro)
--color-neutral-50 a --color-neutral-900
--color-success-500 / --color-warning-500 / --color-error-500 / --color-info-500
```

## 2. Tipografia

- **Família:** no máximo 2 famílias (uma para display/headings, outra para corpo de texto — ou uma única família com múltiplos pesos, mais seguro para performance).
- **Escala tipográfica:** usar razão modular (ex.: 1.25 - "major third" ou 1.333 - "perfect fourth") em vez de valores arbitrários.

```
--font-size-xs:   0.75rem  (12px)
--font-size-sm:   0.875rem (14px)
--font-size-base: 1rem     (16px)
--font-size-lg:   1.125rem (18px)
--font-size-xl:   1.25rem  (20px)
--font-size-2xl:  1.5rem   (24px)
--font-size-3xl:  1.875rem (30px)
--font-size-4xl:  2.25rem  (36px)
```

- **Peso:** regular (400) para corpo, medium (500)/semibold (600) para ênfase, bold (700) para headings — evitar mais de 3 pesos por projeto.
- **Line-height:** 1.4–1.6 para corpo de texto (legibilidade), 1.1–1.3 para headings grandes.
- **Line-length (medida de linha):** 45-75 caracteres por linha para leitura confortável — usar `max-width` em blocos de texto.
- Nunca usar tamanho de fonte abaixo de 16px em inputs (evita zoom automático indesejado em iOS).

## 3. Escalas e espaçamentos

Usar escala baseada em múltiplos de 4px (ou 8px para produtos mais simples), evitando valores arbitrários:

```
--space-1: 4px   --space-2: 8px   --space-3: 12px  --space-4: 16px
--space-5: 20px  --space-6: 24px  --space-8: 32px  --space-10: 40px
--space-12: 48px --space-16: 64px --space-20: 80px --space-24: 96px
```

- Espaçamento interno (padding) de componentes deve ser consistente entre componentes do mesmo "nível" (ex.: todos os botões medium com o mesmo padding vertical/horizontal).
- Espaçamento entre seções deve ser sempre maior que espaçamento entre elementos dentro da mesma seção (hierarquia por proximidade — Gestalt, ver `05-psychology.md`).

## 4. Grid

- Grid de 12 colunas para desktop é o padrão mais flexível (permite divisões em 2, 3, 4 e 6).
- Gutter (espaço entre colunas) tipicamente 16-24px em desktop, 16px em mobile.
- Margens laterais (container) responsivas: 16px mobile, 24-32px tablet, 64-120px+ desktop (dependendo do max-width do container).

## 5. Tokens (arquitetura em 3 camadas)

1. **Global/Reference tokens** — valores brutos (`blue-500: #3B82F6`).
2. **Alias/Semantic tokens** — significado (`color-primary: {blue-500}`, `color-text-danger: {red-600}`).
3. **Component tokens** — aplicação específica (`button-primary-bg: {color-primary}`).

Essa arquitetura permite trocar tema (claro/escuro, white-label) alterando apenas a camada semântica, sem tocar em componentes.

## 6. Componentes (biblioteca mínima de um design system)

Botões, inputs, select, checkbox/radio, switch, badge/tag, avatar, card, tabela, modal, toast/snackbar, tooltip, dropdown/menu, tabs, accordion, breadcrumb, paginação, progress bar/spinner, skeleton loader, empty state, alerta/banner.

Cada componente deve documentar: anatomia, variantes (primary/secondary/ghost/danger), tamanhos (sm/md/lg), estados (ver seção 9) e regras de uso/não uso.

## 7. Ícones

- Usar uma única biblioteca de ícones consistente (ex.: Lucide, Phosphor, Heroicons) — nunca misturar estilos (outline vs. filled vs. duotone) na mesma interface.
- Tamanho padrão alinhado à escala tipográfica (16/20/24px).
- Ícone sozinho sem rótulo só é aceitável se for universalmente reconhecido (busca, fechar, menu hambúrguer) — caso contrário, sempre acompanhar de texto ou `aria-label`.

## 8. Estados de componentes

Todo componente interativo precisa definir visualmente:

- **Default** (repouso)
- **Hover** (somente desktop/mouse)
- **Focus** (obrigatório, visível — anel de foco, nunca `outline: none` sem substituto)
- **Active/Pressed**
- **Disabled** (contraste reduzido, cursor `not-allowed`, sem remover do DOM se a informação for relevante)
- **Loading** (spinner ou skeleton, nunca travar a UI sem feedback)
- **Error/Invalid** (borda + ícone + mensagem, nunca só cor)

## 9. Sombras (elevation)

Sistema de elevação em camadas para comunicar hierarquia (o que está "mais perto" do usuário):

```
--shadow-sm:  0 1px 2px rgba(0,0,0,0.05)          → cards em repouso
--shadow-md:  0 4px 6px rgba(0,0,0,0.10)          → dropdowns, popovers
--shadow-lg:  0 10px 15px rgba(0,0,0,0.10)        → modais
--shadow-xl:  0 20px 25px rgba(0,0,0,0.15)        → elementos flutuantes de destaque
```

Em modo escuro, sombra pura tem pouco efeito — combinar com borda sutil (1px, cor neutra clara sobre fundo escuro) para comunicar elevação.

## 10. Bordas

- **Border-radius** deve seguir escala consistente (ex.: `--radius-sm: 4px`, `--radius-md: 8px`, `--radius-lg: 12px`, `--radius-full: 9999px` para pills/avatares).
- Componentes do mesmo "nível" de hierarquia devem compartilhar o mesmo radius (ex.: todos os cards com `--radius-lg`).
- Border-width padrão de 1px para divisórias sutis; 2px apenas para estados de foco/erro que precisam de destaque.

## 11. Animações e transições

- **Duração:** 100-200ms para micro-interações (hover, toggle), 200-350ms para transições de tela/modal, nunca acima de 500ms para UI (acima disso, o usuário percebe lentidão).
- **Easing:** `ease-out` para elementos entrando (parecem responsivos), `ease-in` para elementos saindo.
- Sempre respeitar `prefers-reduced-motion: reduce` — desativar ou reduzir drasticamente animações para usuários sensíveis a movimento (ver `04-accessibility.md`).
- Animação deve ter propósito funcional (indicar mudança de estado, guiar atenção) — nunca decorativa sem motivo.

## 12. Checklist de Design System

- [ ] Paleta definida em claro e escuro, com contraste AA validado?
- [ ] Escala tipográfica com no máximo 2 famílias e razão modular definida?
- [ ] Espaçamento em múltiplos de 4/8px, sem valores soltos?
- [ ] Tokens organizados em 3 camadas (global → semântico → componente)?
- [ ] Todos os estados de componentes interativos desenhados (incl. focus visível)?
- [ ] Ícones de uma única biblioteca/estilo?
- [ ] Animações respeitam `prefers-reduced-motion`?
