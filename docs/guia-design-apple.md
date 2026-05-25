# Guia de Design no Estilo Apple

> Design não é apenas como uma coisa parece — é como ela funciona. — Steve Jobs

---

## Sumário

1. [Os 5 Pilares do Design Apple](#1-os-5-pilares-do-design-apple)
2. [Sistema de Cores](#2-sistema-de-cores)
3. [Tipografia](#3-tipografia)
4. [Componentes](#4-componentes)
5. [Espaçamento e Border Radius](#5-espaçamento-e-border-radius)
6. [Layout](#6-layout)
7. [Animações e Movimento](#7-animações-e-movimento)
8. [Checklist de Lançamento](#8-checklist-de-lançamento)

---

## 1. Os 5 Pilares do Design Apple

### ✦ Clareza absoluta
O texto é legível. Os ícones são precisos. O espaço negativo respira. Nunca sacrifique legibilidade por estética. Cada elemento deve comunicar algo com clareza imediata.

### ⬡ Deferência ao conteúdo
A interface desaparece. O conteúdo é a estrela. Evite ornamentos que não carregam significado. Se um elemento pode ser removido sem prejudicar função ou beleza — remova-o.

### ◎ Profundidade com camadas
Use sombras sutis, vidro fosco (glassmorphism) e translucidez. Crie a sensação de profundidade física sem exagero. O `backdrop-filter: blur()` é o material digital da Apple.

### → Movimento com propósito
Cada animação guia a atenção ou confirma uma ação. Nada anima por capricho. Transições devem parecer físicas — como se os elementos tivessem peso e inércia.

### ◈ Consistência sistêmica
Tokens de design reutilizáveis: raios, sombras, paleta e tipografia aplicados de forma disciplinada em todo o projeto. Um único sistema serve toda a interface.

---

> **A regra de ouro:** Se um elemento pode ser removido sem prejudicar a função ou a beleza, remova-o. Menos é mais — mas o "menos" deve ser perfeitamente executado.

---

## 2. Sistema de Cores

### Proporção de uso

| Categoria       | Proporção | Uso |
|----------------|-----------|-----|
| Neutros        | 80%       | Fundos, textos, bordas |
| Tons de suporte | 15%      | Cards, seções, separadores |
| Cor de ação    | 5%        | CTAs, links, estados ativos |

---

### Paleta neutra — base de tudo

| Nome         | Hex       | Uso |
|-------------|-----------|-----|
| Branco puro  | `#FFFFFF` | Superfícies principais |
| Cinza suave  | `#F5F5F7` | Background de página |
| Cinza claro  | `#E8E8ED` | Cards secundários |
| Cinza texto  | `#6E6E73` | Texto secundário / muted |
| Preto Apple  | `#1D1D1F` | Texto principal |

---

### Cor de ação — use com disciplina

| Nome         | Hex       | Uso |
|-------------|-----------|-----|
| Azul suave   | `#E8F0FE` | Fundo de badges, hover |
| Azul médio   | `#3B82F6` | Links, ícones |
| Azul Apple   | `#0071E3` | Botão CTA principal |
| Azul escuro  | `#0051A2` | Hover do CTA |

---

### Dark mode — modo escuro

| Nome          | Hex       | Uso |
|--------------|-----------|-----|
| BG primário   | `#1C1C1E` | Background de página |
| BG cards      | `#2C2C2E` | Superfície de cards |
| BG elevado    | `#3A3A3C` | Elementos elevados |
| Bordas        | `#48484A` | Separadores, outline |
| Texto         | `#F5F5F7` | Texto principal |

---

### Cores de status (semânticas)

| Status  | Hex       |
|---------|-----------|
| Sucesso | `#34C759` |
| Atenção | `#FF9F0A` |
| Erro    | `#FF3B30` |
| Info    | `#007AFF` |

---

### CSS — variáveis de cor

```css
:root {
  /* Neutros */
  --color-bg:          #F5F5F7;
  --color-surface:     #FFFFFF;
  --color-text:        #1D1D1F;
  --color-text-muted:  #6E6E73;
  --color-border:      rgba(0, 0, 0, 0.08);

  /* Ação */
  --color-blue:        #0071E3;
  --color-blue-light:  #E8F0FE;
  --color-blue-dark:   #0051A2;

  /* Status */
  --color-success:     #34C759;
  --color-warning:     #FF9F0A;
  --color-danger:      #FF3B30;

  /* Sombras */
  --shadow-sm:  0 1px 4px rgba(0,0,0,0.06);
  --shadow-md:  0 2px 20px rgba(0,0,0,0.07), 0 1px 4px rgba(0,0,0,0.04);
  --shadow-lg:  0 8px 32px rgba(0,0,0,0.10), 0 2px 8px rgba(0,0,0,0.06);
}

@media (prefers-color-scheme: dark) {
  :root {
    --color-bg:         #1C1C1E;
    --color-surface:    #2C2C2E;
    --color-text:       #F5F5F7;
    --color-text-muted: #AEAEB2;
    --color-border:     rgba(255, 255, 255, 0.10);
    --color-blue-light: #1C3050;
  }
}
```

---

## 3. Tipografia

A Apple usa **SF Pro** como fonte principal. Para projetos web, use a stack a seguir para garantir a fonte nativa do sistema:

```css
font-family: -apple-system, BlinkMacSystemFont, "SF Pro Display",
             "Helvetica Neue", "Inter", sans-serif;
```

### Escala tipográfica

| Nível       | Tamanho | Peso | Letter-spacing | Uso |
|------------|---------|------|----------------|-----|
| Display    | 56px    | 700  | `-0.04em`      | Hero, manchetes de impacto |
| Headline   | 32px    | 600  | `-0.03em`      | Títulos de seção principais |
| Title 1    | 22px    | 600  | `-0.02em`      | Títulos de card e modal |
| Title 2    | 18px    | 500  | `-0.01em`      | Subtítulos e grupos |
| Body       | 16px    | 400  | `0`            | Texto de leitura |
| Caption    | 12px    | 400  | `+0.02em`      | Metadados, datas, rótulos |
| Label      | 11px    | 600  | `+0.10em`      | Categorias em caixa alta |

---

### Regras tipográficas

- **Tracking negativo em títulos grandes:** quanto maior o tamanho, mais negativo o `letter-spacing`
- **Line-height no body:** use `1.6` para conforto de leitura
- **Nunca use Arial puro** — prefira a stack com `-apple-system`
- **Máximo 2 pesos** por página: regular (400) e semibold/bold (500–700)

---

### CSS de referência

```css
/* Display */
.text-display {
  font-size: 56px;
  font-weight: 700;
  letter-spacing: -0.04em;
  line-height: 1.05;
}

/* Headline */
.text-headline {
  font-size: 32px;
  font-weight: 600;
  letter-spacing: -0.03em;
  line-height: 1.1;
}

/* Body */
.text-body {
  font-size: 16px;
  font-weight: 400;
  line-height: 1.6;
}

/* Label / Eyebrow */
.text-label {
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.10em;
  text-transform: uppercase;
}
```

---

## 4. Componentes

### Botão primário (CTA)

```css
.btn-primary {
  background: #0071E3;
  color: #FFFFFF;
  border: none;
  padding: 12px 24px;
  border-radius: 980px;        /* Pill */
  font-size: 15px;
  font-weight: 500;
  cursor: pointer;
  transition: opacity 150ms ease;
}

.btn-primary:hover { opacity: 0.85; }
```

---

### Botão secundário (outline)

```css
.btn-secondary {
  background: transparent;
  color: #0071E3;
  border: 1.5px solid #0071E3;
  padding: 11px 24px;
  border-radius: 980px;
  font-size: 15px;
  font-weight: 500;
  cursor: pointer;
  transition: background 150ms ease;
}

.btn-secondary:hover { background: #E8F0FE; }
```

---

### Input refinado

```css
.input {
  width: 100%;
  padding: 12px 16px;
  border-radius: 12px;
  border: 1.5px solid rgba(0,0,0,0.08);
  background: #F5F5F7;
  font-size: 15px;
  color: #1D1D1F;
  outline: none;
  transition: border-color 200ms ease;
}

.input:focus { border-color: #0071E3; }
```

---

### Card com elevação

```css
.card {
  background: #FFFFFF;
  border-radius: 18px;
  padding: 20px;
  border: 0.5px solid rgba(0,0,0,0.08);
  box-shadow: 0 2px 20px rgba(0,0,0,0.07), 0 1px 4px rgba(0,0,0,0.04);
  transition: transform 200ms ease, box-shadow 200ms ease;
}

.card:hover {
  transform: translateY(-2px);
  box-shadow: 0 8px 32px rgba(0,0,0,0.10);
}
```

---

### Navbar com glassmorphism

```css
.navbar {
  position: sticky;
  top: 0;
  z-index: 100;
  background: rgba(255, 255, 255, 0.72);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  border-bottom: 0.5px solid rgba(0,0,0,0.08);
  padding: 12px 24px;
  display: flex;
  align-items: center;
  justify-content: space-between;
}

@media (prefers-color-scheme: dark) {
  .navbar {
    background: rgba(28, 28, 30, 0.72);
    border-bottom-color: rgba(255,255,255,0.10);
  }
}
```

---

### Badge / Pill

```css
.badge {
  display: inline-block;
  padding: 4px 12px;
  border-radius: 20px;
  font-size: 12px;
  font-weight: 500;
}

/* Variações */
.badge-blue    { background: #E8F0FE; color: #0051A2; }
.badge-green   { background: #EAF5EE; color: #1A7F3C; }
.badge-orange  { background: #FFF3E8; color: #B45309; }
.badge-purple  { background: #F5EEF8; color: #7C3AED; }
.badge-gray    { background: #F0F0F5; color: #6E6E73; }
```

---

## 5. Espaçamento e Border Radius

### Escala de espaçamento (múltiplos de 4pt)

| Token    | Valor | Uso típico |
|---------|-------|-----------|
| `--sp-1` | 4px  | Gap entre ícone e texto |
| `--sp-2` | 8px  | Padding interno pequeno |
| `--sp-3` | 12px | Gap entre elementos inline |
| `--sp-4` | 16px | Padding base de cards |
| `--sp-5` | 20px | Gap entre cards |
| `--sp-6` | 24px | Padding generoso |
| `--sp-8` | 32px | Espaço entre seções |
| `--sp-10`| 40px | Margem de seção |
| `--sp-16`| 64px | Separação de blocos grandes |

```css
:root {
  --sp-1:  4px;
  --sp-2:  8px;
  --sp-3:  12px;
  --sp-4:  16px;
  --sp-5:  20px;
  --sp-6:  24px;
  --sp-8:  32px;
  --sp-10: 40px;
  --sp-16: 64px;
}
```

---

### Border Radius

| Nome      | Valor  | Uso |
|----------|--------|-----|
| Micro     | `4px`  | Tags, chips pequenos |
| Input     | `8px`  | Campos de formulário |
| Card      | `12px` | Cards e painéis internos |
| Painel    | `18px` | Cards principais, modais |
| App icon  | `22%`  | Ícones no estilo iOS |
| Pill      | `980px`| Botões, badges |

```css
:root {
  --radius-xs:   4px;
  --radius-sm:   8px;
  --radius-md:   12px;
  --radius-lg:   18px;
  --radius-pill: 980px;
}
```

---

## 6. Layout

### Estrutura de página Apple

```
┌─────────────────────────────────────────┐
│  NAVBAR  (sticky, glassmorphism)        │
├─────────────────────────────────────────┤
│                                         │
│         HERO  (texto + CTA)             │
│         max-width: 680px centrado       │
│                                         │
├─────────────────────────────────────────┤
│                                         │
│   GRID DE FEATURES  (2–3 colunas)      │
│   gap: 20px, cards com sombra          │
│                                         │
├─────────────────────────────────────────┤
│         CTA ISOLADA                     │
│         Fundo diferenciado              │
├─────────────────────────────────────────┤
│  FOOTER  (links + marca)                │
└─────────────────────────────────────────┘
```

---

### CSS de layout base

```css
/* Container principal */
.container {
  width: 100%;
  max-width: 1200px;
  margin: 0 auto;
  padding: 0 24px;
}

/* Hero */
.hero {
  text-align: center;
  padding: 80px 24px;
}

.hero-content {
  max-width: 680px;
  margin: 0 auto;
}

/* Grid de features */
.features-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 20px;
  padding: 60px 0;
}

/* Mobile first */
@media (max-width: 768px) {
  .container { padding: 0 16px; }
  .hero { padding: 48px 16px; }
  .features-grid { grid-template-columns: 1fr; gap: 14px; }
}
```

---

### Proporções de padding lateral

| Breakpoint | Padding lateral |
|-----------|----------------|
| Mobile (< 768px)  | `16–20px` |
| Tablet (768–1024px) | `32–48px` |
| Desktop (> 1024px) | `80–120px` |

---

## 7. Animações e Movimento

### Princípios

- Transições de hover: **150ms**
- Modais e transições de tela: **300ms**
- Animações de entrada de página: **500ms**
- Sempre use `will-change: transform` para performance
- Respeite sempre `prefers-reduced-motion`

---

### Easing values — curvas Apple

```css
:root {
  --ease-spring:  cubic-bezier(0.175, 0.885, 0.32, 1.275);
  --ease-out:     cubic-bezier(0.25, 0.46, 0.45, 0.94);
  --ease-in-out:  cubic-bezier(0.645, 0.045, 0.355, 1.0);
  --ease-default: cubic-bezier(0.4, 0.0, 0.2, 1);

  --duration-fast:   150ms;
  --duration-normal: 300ms;
  --duration-slow:   500ms;
}
```

---

### Animações de entrada — fade up

```css
@keyframes fadeUp {
  from {
    opacity: 0;
    transform: translateY(16px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

/* Uso com stagger */
.card:nth-child(1) { animation: fadeUp 0.5s var(--ease-out) 0.0s both; }
.card:nth-child(2) { animation: fadeUp 0.5s var(--ease-out) 0.1s both; }
.card:nth-child(3) { animation: fadeUp 0.5s var(--ease-out) 0.2s both; }
```

---

### Hover em cards

```css
.card {
  transition: transform 200ms var(--ease-out),
              box-shadow 200ms var(--ease-out);
}

.card:hover {
  transform: translateY(-3px);
  box-shadow: 0 12px 40px rgba(0,0,0,0.12);
}
```

---

### Respeitar preferência do usuário

```css
@media (prefers-reduced-motion: reduce) {
  *,
  *::before,
  *::after {
    animation-duration: 0.01ms !important;
    transition-duration: 0.01ms !important;
  }
}
```

---

## 8. Checklist de Lançamento

### Fundamentos visuais

- [ ] Dark mode implementado com `prefers-color-scheme`
- [ ] Variáveis CSS definidas para todas as cores e tokens
- [ ] Tipografia com SF Pro stack e escala correta
- [ ] Letter-spacing negativo nos títulos grandes
- [ ] Bordas de `0.5px` ao invés de `1px` nos cards

### Componentes

- [ ] Navbar com `backdrop-filter: blur(20px)` e `position: sticky`
- [ ] Botões com border-radius pill (`980px`)
- [ ] Inputs com foco azul (`#0071E3`) e transição suave
- [ ] Cards com sombra sutil e hover com `translateY`
- [ ] Badges com cores semânticas corretas

### Layout

- [ ] Container com `max-width: 1200px` e auto nas laterais
- [ ] Hero centralizado com `max-width: 680px` para o texto
- [ ] Grid de features com `auto-fit` e `minmax(280px, 1fr)`
- [ ] Padding lateral responsivo por breakpoint
- [ ] Espaçamento baseado em múltiplos de 4pt

### Acessibilidade

- [ ] Contraste mínimo WCAG AA (4.5:1 para texto, 3:1 para UI)
- [ ] Focus ring visível em todos os elementos interativos
- [ ] ARIA labels em ícones e botões sem texto
- [ ] Navegação por teclado funcional
- [ ] `alt` em todas as imagens relevantes

### Performance e animações

- [ ] `prefers-reduced-motion` respeitado
- [ ] `will-change: transform` nos elementos animados
- [ ] Imagens em formato WebP ou AVIF com `loading="lazy"`
- [ ] Fontes com `font-display: swap`
- [ ] Core Web Vitals: LCP < 2.5s, CLS < 0.1, FID < 100ms

---

## Referências e recursos

| Recurso | URL |
|---------|-----|
| Apple Human Interface Guidelines | https://developer.apple.com/design/human-interface-guidelines |
| SF Pro (uso em apps Apple) | https://developer.apple.com/fonts |
| Inter (alternativa gratuita) | https://rsms.me/inter |
| Geist Sans (Vercel) | https://vercel.com/font |
| Color contrast checker | https://webaim.org/resources/contrastchecker |
| Cubic bezier visualizer | https://cubic-bezier.com |

---

*Guia criado com base nos princípios de design da Apple — HIG, macOS, iOS e apple.com.*
