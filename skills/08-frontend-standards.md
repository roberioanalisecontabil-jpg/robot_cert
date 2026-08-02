# 08 · Front-end Standards

Padrões técnicos para geração de código de interface. A IA deve seguir estas diretrizes sempre que produzir HTML, CSS ou JavaScript, além do conteúdo de design em si.

## 1. HTML5 semântico

- Usar elementos com significado (`<header>`, `<nav>`, `<main>`, `<section>`, `<article>`, `<aside>`, `<footer>`) em vez de `<div>` genérico para tudo.
- Um único `<h1>` por página; hierarquia de headings sequencial (não pular de `<h2>` para `<h4>`).
- `<button>` para ações, `<a>` para navegação — nunca `<div onclick>` (quebra acessibilidade e semântica).
- Atributos `lang` no `<html>`, `viewport` meta tag correta (`width=device-width, initial-scale=1`), `charset="utf-8"`.

## 2. CSS

- Preferir CSS moderno nativo (Grid, Flexbox, custom properties/variáveis, `clamp()`, `gap`) a soluções antigas (floats para layout, `!important` como regra geral).
- Metodologia de nomenclatura consistente quando não usar utility-first (ex.: BEM — `bloco__elemento--modificador`) para evitar CSS global conflitante.
- Variáveis CSS (`:root { --token: valor }`) para tokens do design system — nunca hardcode de cores/espaçamentos repetido em múltiplos lugares.
- Mobile-first: escrever estilos base para mobile, sobrescrever com `min-width` media queries para telas maiores.

## 3. Grid e Flexbox (aplicação em código)

```css
/* Grid para layout bidimensional */
.dashboard {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: var(--space-6);
}

/* Flexbox para distribuição em uma dimensão */
.button-group {
  display: flex;
  gap: var(--space-3);
  align-items: center;
}
```

## 4. Tailwind CSS

- Preferir classes utilitárias diretamente no markup para componentes simples; extrair para `@apply`/componente quando o mesmo conjunto de classes se repete 3+ vezes.
- Usar o arquivo de configuração (`tailwind.config`) para registrar os tokens do design system (cores, espaçamentos, tipografia) em vez de usar valores arbitrários (`w-[123px]`) com frequência.
- Respeitar prefixos responsivos mobile-first (`sm:`, `md:`, `lg:`) partindo do estilo base sem prefixo para mobile.
- Usar `dark:` variant de forma consistente para suportar tema escuro desde o início, não como retrofit.

## 5. Bootstrap (quando for a stack do projeto)

- Usar o sistema de grid nativo (`container`/`row`/`col-*`) em vez de recriar grid customizado por cima.
- Sobrescrever variáveis Sass/CSS custom properties do Bootstrap para aplicar o design system, em vez de sobrescrever classes com `!important`.
- Preferir componentes nativos (modal, dropdown, tooltip) e customizar via variáveis, reduzindo JS customizado duplicado.

## 6. JavaScript

- Vanilla JS moderno (ES2020+) ou o framework do projeto — nunca misturar jQuery com framework moderno sem necessidade.
- Progressive enhancement: funcionalidade essencial deve degradar graciosamente se o JS falhar/demorar a carregar (ex.: formulário com `action` nativo além do handler JS).
- Debounce em inputs de busca/filtro para evitar excesso de requisições.
- Sempre limpar event listeners e timers ao desmontar componentes (evitar memory leaks em SPAs).

## 7. Performance

- **Imagens:** formatos modernos (WebP/AVIF) com fallback, `loading="lazy"` para imagens fora da viewport inicial, `width`/`height` explícitos para evitar layout shift (CLS).
- **Fontes:** `font-display: swap`, subsetting quando possível, preload da fonte crítica (`<link rel="preload" as="font">`).
- **JS/CSS:** code splitting, carregar apenas o necessário para a rota atual; `defer`/`async` em scripts não críticos.
- **Core Web Vitals como referência:** LCP < 2.5s, INP < 200ms, CLS < 0.1.
- Minimizar requisições de terceiros (analytics, chat widgets) que bloqueiam renderização — carregar de forma assíncrona.

## 8. SEO (quando aplicável — páginas públicas)

- `<title>` único e descritivo por página, `<meta name="description">` específico.
- Estrutura de heading semântica (um `<h1>`, hierarquia lógica) também ajuda SEO, não só acessibilidade.
- URLs legíveis e estáveis; `rel="canonical"` quando há conteúdo duplicado/similar.
- Dados estruturados (schema.org/JSON-LD) para conteúdo relevante (produtos, artigos, FAQ).
- Imagens com `alt` descritivo também contribuem para SEO de imagens.

## 9. Semântica e estrutura de arquivos

Estrutura de referência para projetos de front-end de porte médio:

```
src/
├── components/       (componentes reutilizáveis, um por pasta com estilo colocalizado)
├── pages/ ou routes/  (telas/rotas da aplicação)
├── styles/
│   ├── tokens.css     (variáveis do design system)
│   └── globals.css
├── hooks/ ou composables/
├── utils/ ou lib/
└── assets/
```

- Componentes devem ser pequenos e focados em uma responsabilidade (Single Responsibility também se aplica a UI).
- Nomenclatura de arquivos e componentes em PascalCase (componentes) e kebab-case (arquivos de estilo/utilitários), consistente com a convenção do framework usado.

## 10. Lighthouse (metas de referência)

| Categoria | Meta mínima aceitável | Meta ideal |
|---|---|---|
| Performance | ≥ 80 | ≥ 90 |
| Acessibilidade | ≥ 90 | 100 |
| Best Practices | ≥ 90 | 100 |
| SEO | ≥ 90 | 100 |

Rodar auditoria Lighthouse (ou equivalente) antes de considerar uma entrega de front-end pronta, especialmente para páginas públicas voltadas a conversão.

## 11. Como a IA deve escrever código (diretrizes de estilo)

- Comentar o **porquê**, não o óbvio (`// centraliza o modal na viewport` em vez de `// margin auto`).
- Nomear classes/variáveis por função, não por aparência (`.btn-primary` em vez de `.btn-blue`, pois a cor pode mudar com o tema).
- Sempre entregar código já responsivo e acessível por padrão, sem que o usuário precise pedir separadamente (ver `03-responsive-design.md` e `04-accessibility.md`).
- Evitar dependências desnecessárias para funcionalidade simples que CSS/JS nativo já resolve.

## 12. Checklist de Front-end

- [ ] HTML semântico, com hierarquia de headings correta e um único `<h1>`?
- [ ] CSS usando tokens/variáveis do design system, mobile-first?
- [ ] Imagens com lazy loading, dimensões explícitas e formato moderno?
- [ ] JS com progressive enhancement e sem vazamento de listeners?
- [ ] Metas de Core Web Vitals e Lighthouse consideradas antes da entrega?
