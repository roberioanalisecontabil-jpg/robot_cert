# Auditoria de UI/UX — Analise CertiDigital

**Data:** 2026-08-02
**Base normativa:** `skills/00-core.md` … `skills/09-ai-behavior.md`
**Escopo auditado:** `templates/*.html` (8 arquivos, 4.201 linhas), `static/style.css` (1.880 linhas), `static/ui-common.js` (703 linhas)
**Método:** verificação linha a linha contra os checklists de cada skill; contrastes calculados por luminância relativa (WCAG 2.x), não por inspeção visual.

**Legenda de severidade:** 🔴 Crítico · 🟠 Alto · 🟡 Médio · 🔵 Baixo

---

## Sumário executivo

O projeto já tem uma base sólida: tokens CSS em `:root`, `:focus-visible` global, skip-link, `aria-live` na toolbar, paginação com `aria-current`, debounce na busca e drawer mobile. As Fases 1–4 do plano anterior entregaram infraestrutura real.

O problema central não é ausência de recursos — é que **três dos recursos entregues na Fase 3 nunca foram conectados às telas**. `showToast()`, `renderEmptyState()` e `.skeleton-cell` existem, estão bem escritos, e têm **zero chamadas** em todo o código. Enquanto isso, há **17 chamadas de `alert()`** nativas — exatamente o padrão que os toasts foram criados para substituir.

Além disso, dois defeitos funcionais reais foram identificados: o tema escuro automático está quebrado e o menu mobile quebra para usuários com `prefers-reduced-motion`.

| Skill | Conformidade | Achados |
|---|---|---|
| 00 · Core | Parcial | 2 |
| 01 · UX Foundations | ⚠️ Baixa | 5 |
| 02 · Design System | Parcial | 6 |
| 03 · Responsive | Parcial | 3 |
| 04 · Accessibility | ⚠️ Baixa | 7 |
| 07 · Design Patterns | ⚠️ Baixa | 5 |
| 08 · Front-end Standards | Parcial | 6 |

**Total: 34 achados** — 3 críticos, 9 altos, 14 médios, 8 baixos.

---

## 🔴 CRÍTICO

### C1 · Toasts, empty states e skeletons entregues mas nunca usados ✅ CORRIGIDO
**Skill:** `07 §15`, `07 §3`, `01 §9` (feedback ausente)

O commit `9f73371` declara "concluir Fases 2, 3 e 4 (toasts, empty states, skeleton loaders)". As três funções existem e estão corretas:

| Recurso | Definido em | Usos no projeto |
|---|---|---|
| `showToast()` | `static/ui-common.js:204` | **0** |
| `renderEmptyState()` | `static/ui-common.js:255` | **0** |
| `.skeleton-cell` | `static/style.css:1865` | **0** |

Em paralelo, o projeto usa 17 `alert()` bloqueantes:

```
templates/colaborador_certificados.html:389, 395
templates/configuracao.html:593
templates/historico.html:240, 253, 281
templates/index.html:441, 454, 487
templates/usuarios.html:300, 315, 318, 328, 399
templates/vencidos.html:380, 412, 438
```

E a tabela do dashboard, quando não há dados, fica simplesmente em branco — `index.html:379` faz `tb.innerHTML = items.map(...)`, que com array vazio produz string vazia. Sem título, sem explicação, sem ação. Viola diretamente `01 §10` ("Todos os estados foram desenhados: vazio, carregando, erro, sucesso?").

**Correção:** substituir os 17 `alert()` por `showToast(msg, 'error'|'success')`; chamar `renderEmptyState()` quando `items.length === 0` nas 5 telas com tabela; trocar o overlay de loading por skeleton rows no primeiro carregamento (o overlay ainda faz sentido em exportações).

**Esforço:** ~3h · **Impacto:** alto — é o achado com melhor relação custo/benefício de toda a auditoria.

---

### C2 · Tema escuro automático não funciona ✅ CORRIGIDO
**Skill:** `02 §1.2` ("definir a paleta em modo claro e escuro desde o início")

`ui-common.js:442` executa em todo carregamento de página:

```js
applyTheme(localStorage.getItem("cert_robot_theme"));
```

Quando o usuário nunca clicou no toggle, `getItem()` retorna `null`. Em `applyTheme()` (`ui-common.js:395`), `null !== "dark"`, então cai no `else` e força `data-theme="light"` no `<html>`.

Consequência: o bloco `@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) { … } }` em `style.css:113-152` **nunca é ativado** — o seletor `:not([data-theme="light"])` deixa de casar no exato momento em que o JS roda. São 40 linhas de CSS permanentemente mortas, e todo usuário com sistema em modo escuro recebe a interface clara até descobrir o botão de tema.

**Correção:** em `applyTheme`, quando o valor é `null`/ausente, **remover** o atributo em vez de setar `"light"`:

```js
function applyTheme(theme) {
  if (theme === "dark" || theme === "light") {
    document.documentElement.setAttribute("data-theme", theme);
  } else {
    document.documentElement.removeAttribute("data-theme"); // devolve o controle ao SO
  }
  // …ícone do botão passa a considerar matchMedia quando theme é null
}
```

**Esforço:** ~20min

---

### C3 · `prefers-reduced-motion` quebra o menu mobile ✅ CORRIGIDO
**Skill:** `02 §11`, `04 §10`, `03 §1`

`style.css:1361-1371` aplica ao seletor universal:

```css
@media (prefers-reduced-motion: reduce) {
  * {
    transform: none !important;   /* ← aqui */
    …
  }
}
```

Mas `transform` não é só animação — é **layout** neste projeto. Em `style.css:1638-1643`:

```css
@media (max-width: 768px) {
  .sidebar { transform: translateX(-100%); }   /* esconde o drawer */
}
body.sidebar-open .sidebar { transform: translateX(0); }
```

Para qualquer usuário com "reduzir movimento" ativo (comum em iOS/Android por acessibilidade vestibular), o `!important` anula o `translateX(-100%)` e **a sidebar de 270px fica permanentemente aberta sobre o conteúdo em telas < 768px**, sem forma de fechar. A ironia é que o defeito atinge exatamente o público que a regra pretendia proteger.

O mesmo `transform: none !important` também neutraliza `.dashboard-card:hover { transform: translateY(-3px) }` (benigno) e `.toast-item { transform: translateY(16px) }` (o toast aparece sem transição — aceitável).

**Correção:** nunca zerar `transform` globalmente. Substituir por:

```css
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
    scroll-behavior: auto !important;
  }
}
```

`0.01ms` em vez de `0s` é a recomendação do WCAG WG — mantém o disparo de `transitionend`, do qual `removeToast()` (`ui-common.js:245`) depende para remover o nó do DOM. Com `0s` em alguns navegadores o evento não dispara e **os toasts vazam no DOM indefinidamente**.

**Esforço:** ~15min

---

## 🟠 ALTO

### A1 · Badges de status reprovam em contraste ✅ CORRIGIDO
**Skill:** `04 §2` (tabela de contraste), `00 §7`

Os badges usam texto colorido de 11px `font-weight: 600` sobre fundo tonal da mesma cor. Como 11px < 18px, o mínimo AA é **4.5:1**.

> **Correção do diagnóstico inicial.** A primeira versão desta auditoria tratou o problema como global. Ao recalcular os fundos **efetivos** do tema escuro (os `--*-bg` escuros são `rgba(…, 0.15)`, que compõem com `--surface: #2C2C2E`), o quadro mudou: no escuro, `badge-ok` e `badge-warning` **já passavam**. Escurecer o texto globalmente teria quebrado os dois.

| Badge | Tema claro (antes → depois) | Tema escuro (antes → depois) |
|---|---|---|
| `.badge-ok` "Ativo" | 2.04:1 ❌ → **4.95:1** ✅ | 5.16:1 ✅ → mantido |
| `.badge-warning` "Expirando" | 1.93:1 ❌ → **6.01:1** ✅ | 5.09:1 ✅ → mantido |
| `.badge-expired` "Vencido" | 3.24:1 ❌ → **5.68:1** ✅ | 3.48:1 ❌ → **5.81:1** ✅ |

O badge "Expirando" a 1,93:1 era praticamente ilegível — e é justamente o alerta mais acionável do produto (`README`: "Alerta visual para certificados que vão expirar nos próximos 30 dias").

**Implementado:** tokens de texto separados dos tokens de identidade visual. `--ok`/`--warning`/`--expired` continuam definindo ícones, bordas e preenchimentos (elementos gráficos, mínimo 3:1); os novos `--ok-text`/`--warning-text`/`--expired-text` servem só ao texto, que exige 4.5:1. No tema escuro os dois primeiros apontam para a cor original, preservando a identidade Apple.

Pendente (fora do Sprint 1): `.card-erros` ícone `#ea580c`/`#fff7ed` a 3.35:1 — passa como componente de UI (3:1), tratado em **M2**.

---

### A2 · Status transmitido apenas por cor ⚠️ ACHADO SUPERDIMENSIONADO
**Skill:** `04 §9` ("nunca usar cor como único diferenciador"), `02 §1.1`

Os badges se distinguem por cor + texto ("Ativo"/"Expirando"/"Vencido") — o texto salva a acessibilidade **na tabela**. Mas nos cards do dashboard (`index.html:85-145`) a única diferenciação entre Total/Ativo/Expirando/Erro/Falha é a cor do `.card-icon`. Com deuteranopia (~8% dos homens), verde e laranja convergem.

**Correção:** os ícones já são distintos por forma (check, relógio, alerta) — está parcialmente resolvido. Falta adicionar forma/padrão nos badges: `✓` para Ativo, `⚠` para Expirando, `✕` para Vencido, com `aria-hidden="true"` no glifo.

---

### A3 · Sticky headers não funcionam ✅ CORRIGIDO
**Skill:** `07 §7` ("header fixo (sticky) com labels de coluna")

`style.css:1874-1880` define:

```css
.table-container table thead th { position: sticky; top: 0; … }
```

Mas a tabela está dentro de `<div style="overflow-x: auto">` (`index.html:176`). Pela especificação CSS, quando `overflow-x: auto` e `overflow-y: visible`, o `overflow-y` é computado como `auto` — o div vira um **scroll container**. `position: sticky` resolve contra o scrollport mais próximo, que passa a ser esse div. Como o div tem altura automática (= altura total da tabela), ele nunca rola verticalmente, e o header **nunca gruda**. O usuário rola a página, o header sai de vista, e o recurso da Fase 4 não produz efeito nenhum.

**Correção:** dar altura máxima ao wrapper e deixá-lo rolar de fato:

```css
.table-scroll { overflow: auto; max-height: 70vh; }
```
…e mover os estilos inline do `<div style="overflow-x: auto">` para essa classe nas 5 telas. Alternativa mais simples: remover o wrapper em desktop e deixar o sticky resolver contra a viewport.

---

### A4 · Inputs e selects sem `<label>` associado ✅ CORRIGIDO
**Skill:** `04 §7` ("nunca apenas `placeholder` como substituto de label")

43 `<input>`/`<select>` nas telas, 27 `<label>`. O caso mais visível é a toolbar do dashboard (`index.html:156-169`): o `#filtro-status` e o `#busca-cert` têm apenas `title` e `placeholder`. Leitor de tela anuncia "caixa de edição, em branco" ou lê o placeholder — que desaparece assim que o usuário digita.

**Correção:** `<label for="busca-cert" class="cg-sr-only">Buscar certificado</label>` — a classe `.cg-sr-only` já existe em `style.css:1186` e está sendo usada corretamente em `index.html:216`. É só replicar o padrão.

---

### A5 · Dropdown de notificações sem `aria-expanded` nem gestão de foco ✅ CORRIGIDO
**Skill:** `04 §6`, `04 §4`

O sino (`ui-common.js:518`) tem `aria-label`, mas **`aria-expanded` aparece 0 vezes em todo o projeto**. Leitor de tela não anuncia se o painel está aberto ou fechado. Além disso o dropdown abre sem mover o foco, não tem navegação por setas, e ao fechar com `Esc` (`ui-common.js:697`) o foco não retorna ao botão que o abriu.

**Correção:**
```js
toggleBtn.setAttribute("aria-expanded", String(!isVisible));
toggleBtn.setAttribute("aria-haspopup", "true");
// no handler de Esc:
document.getElementById("btn-notifications-toggle")?.focus();
```

---

### A6 · Alvos de toque abaixo do mínimo ✅ CORRIGIDO
**Skill:** `03 §9` (44×44px), `04 §10` (WCAG 2.5.8 — mínimo 24×24px)

| Elemento | Tamanho computado | 44px | 24px |
|---|---|---|---|
| `.toast-close` (`style.css:1781`) | ~20×17px | ❌ | ❌ **falha WCAG AA** |
| `.cg-page-link` (`style.css:1253`) | 36px altura | ❌ | ✅ |
| `.sidebar-toggle-btn` | 40×40px | ❌ | ✅ |

O `.toast-close` é o único que reprova no critério normativo 2.5.8 (`font-size: 1.25rem; line-height: 1; padding: 0 0.25rem` produz ~20px de altura).

**Correção:** `.toast-close { min-width: 44px; min-height: 44px; display: inline-flex; align-items: center; justify-content: center; }` e `.cg-page-link { min-height: 44px; }`.

---

### A7 · Tabela força scroll horizontal no mobile ✅ CORRIGIDO
**Skill:** `07 §7` ("em mobile, transformar em cards empilhados com labels inline em vez de scroll horizontal forçado")

Todas as tabelas usam `overflow-x: auto`. Em 375px de largura, uma tabela de 5 colunas (Status/Nome/Emissão/Vencimento/CNPJ) obriga o usuário a rolar lateralmente e perde o contexto da coluna ao fazê-lo — o header não acompanha.

**Correção:** abaixo de 768px, converter linhas em cards com `data-label` via CSS:

```css
@media (max-width: 768px) {
  .table-container thead { position: absolute; left: -9999px; }
  .table-container tr { display: block; border: 1px solid var(--border);
                        border-radius: var(--radius-md); margin-bottom: var(--sp-3); padding: var(--sp-3); }
  .table-container td { display: flex; justify-content: space-between; border: 0; padding: var(--sp-2) 0; }
  .table-container td::before { content: attr(data-label); font-weight: 600; color: var(--text-muted); }
}
```
Exige adicionar `data-label="Vencimento"` etc. nos `<td>` gerados em `renderTabela()`.

---

### A8 · Tela de login sem recuperação de senha nem toggle de visibilidade ✅ CORRIGIDO
**Skill:** `07 §1` (estrutura e problemas comuns do padrão Login)

`templates/login.html` acerta o essencial (`autocomplete="username"`/`"current-password"`, `role="alert"`, erro genérico que não revela qual campo falhou — `07 §1` cumprido). Faltam dois itens que a skill lista explicitamente como **problemas comuns**:

- **Sem "Esqueci minha senha"** — o usuário que perde a senha não tem saída na interface; depende de um admin em `/usuarios`. Viola também `01 §1.3` (controle e liberdade do usuário).
- **Sem toggle mostrar/ocultar senha** — listado como problema comum em `07 §1`.

Menor, mas relacionado: o botão diz "Entrar" (`login.html:125`). `06 §1` pede que o CTA descreva o resultado — "Acessar o painel" seria mais alinhado.

---

### A9 · Fonte carregada por `@import` (render-blocking em cascata) ✅ CORRIGIDO
**Skill:** `08 §7` (fontes, Core Web Vitals)

`style.css:1`:
```css
@import url('https://fonts.googleapis.com/css2?family=Inter:…&display=swap');
```

`@import` dentro de CSS cria uma **cadeia serial**: o browser baixa `style.css`, só então descobre o `@import`, e só então busca a fonte. Piora o LCP em relação a um `<link>` no `<head>`, que dispara em paralelo. A skill pede explicitamente `preload` da fonte crítica.

Agravante: o `:root` em `style.css:5` lista `-apple-system, BlinkMacSystemFont, "Inter", …` — **as fontes do sistema vêm antes da Inter na cascata**. Em macOS/iOS a Inter nunca é aplicada; em Windows, `-apple-system` e `BlinkMacSystemFont` não resolvem, então a Inter entra. Ou seja: o download é pago em todas as plataformas, mas só é usado em algumas. Ou a Inter é a fonte de marca (e deve vir primeiro), ou é dispensável (e o `@import` deve sair).

**Correção:** decidir a intenção. Se a Inter é a marca:
```html
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="preload" as="style" href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap">
<link rel="stylesheet" href="…" >
```
e reordenar para `font-family: "Inter", -apple-system, …`. Se não é, remover o `@import` (economiza ~40KB e uma requisição de terceiro).

---

## 🟡 MÉDIO

### M1 · Tokens de cor duplicados em dois blocos ✅ RESOLVIDO 17/08 — **por trava, não por desduplicação.**

A duplicação continua: o tema escuro é declarado em `:root[data-theme="dark"]` e de novo dentro de `@media (prefers-color-scheme: dark)`. Desduplicar exigiria mexer na cascata dos dois seletores, com risco visual que a suíte não consegue ver — ela lê o CSS e nunca renderiza. O que machuca não é a duplicação, é a **divergência**: quem escolhe "escuro" no seletor veria uma cor e quem segue o sistema veria outra, sem erro em nenhum dos dois caminhos. `test_os_dois_blocos_de_tema_escuro_definem_os_mesmos_tokens` trava isso.
**Skill:** `02 §5` (arquitetura de tokens em 3 camadas)

`style.css:74-111` (`:root[data-theme="dark"]`) e `style.css:113-152` (`@media prefers-color-scheme: dark`) são **40 linhas idênticas copiadas**. Qualquer ajuste de cor no escuro precisa ser feito em dois lugares — e um deles (C2) nem está ativo hoje.

**Correção:** extrair para uma classe única e aplicá-la nos dois seletores:
```css
:root[data-theme="dark"],
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) { … } }
```
Não é possível agrupar seletor e media query diretamente; a saída limpa é declarar os tokens escuros em `.theme-dark` e aplicar essa classe via JS + fallback CSS, ou aceitar a duplicação com um comentário `/* MANTER SINCRONIZADO COM linha 74 */`. Recomendo a segunda para o porte deste projeto — refatorar tokens tem custo alto e ganho baixo aqui.

---

### M2 · Cores hardcoded que quebram no modo escuro ✅ CORRIGIDO — **em duas etapas.**

A primeira (02/08) limpou os templates. Faltou o próprio `style.css`, e a varredura da época não olhou lá. Fechado em 17/08: `.tag` tinha fundo claro FIXO com `color: var(--text-muted)` — texto claro sobre fundo claro no tema escuro, etiqueta ilegível; `.path-value` virava um retângulo branco na página escura; e `.card-erros` usava cor de mão enquanto o cartão ao lado já usava tokens. Entraram `--fora-padrao-bg`/`--fora-padrao-text` para o roxo de "fora do padrão", que não tinha par no escuro. Restam três literais, todas legítimas: `#ffffff` do `.skip-to-content` (texto em botão preenchido) e o `.cmd-pre`, bloco de código escuro nos dois temas.
**Skill:** `02 §5`, `08 §2` ("nunca hardcode de cores repetido em múltiplos lugares")

12 declarações fora dos tokens, todas assumindo fundo claro:

| Linha | Regra | Problema no escuro |
|---|---|---|
| `480-481` | `.card-erros .card-icon` `#fff7ed` / `#ea580c` | fundo claro sobre card escuro |
| `485-486` | `.card-sem-padrao .card-icon` `#f5f3ff` / `#7c3aed` | idem |
| `656` | `.error-cell` `#b91c1c` | vermelho escuro sobre fundo escuro |
| `766-772` | `.path-value` `#f3f4f6` / `#1f2937` | bloco claro |
| `778-779` | `.tag` `#f3f4f6` | idem |
| `794-795` | `.hint-warn` `#fecaca` / `#991b1b` | idem |
| `942` | `.dup-igual-status` `#b45309` | contraste insuficiente |
| `index.html:153` | `#panel-hint` inline `color:#f59e0b` | **2.15:1 no claro** — reprova AA |
| `index.html:373` | `.error-cell` inline `color:#ef4444` | inline sobrescreve o CSS |
| `index.html:67` | link "Sair" inline `color:#dc2626` | **3.52:1** sobre a sidebar |

Nenhuma delas tem variante escura. Duas (`#f59e0b`, `#dc2626`) já reprovam em contraste no tema claro.

**Correção:** promover os dois pares de ícone de card a tokens semânticos (`--erro-bg`/`--erro-fg`, `--falha-bg`/`--falha-fg`) com valores nos três blocos de tema; trocar `#f59e0b` por `var(--warning-text)` do achado A1; usar `#FF6B6B` para o "Sair" (4.6:1 sobre `#1C1C1E`).

---

### M3 · `will-change` aplicado em massa ✅ CORRIGIDO
**Skill:** `08 §7` (performance)

`style.css:1353-1358` declara `will-change: background-color, border-color, transform, box-shadow` para **todos** os `button`, `.path-input`, `select` e `.sidebar-nav a` da aplicação — permanentemente, não só durante a interação. Cada elemento com `will-change` ganha uma camada de composição própria na GPU. Numa tela como `/duplicidades` (937 linhas, dezenas de botões de paginação), isso é consumo de memória de vídeo sem contrapartida — as transições envolvidas são de cor, que nem se beneficiam de promoção de camada.

**Correção:** remover o bloco. Se houver jank comprovado em algum componente específico, aplicar `will-change` pontualmente no `:hover` do pai, e nunca em `background-color`.

---

### M4 · Escala tipográfica não segue razão modular
**Skill:** `02 §2` ("usar razão modular em vez de valores arbitrários")

As classes `.text-*` (`style.css:203-251`) usam 56 / 32 / 22 / 18 / 16 / 12 / 11px. As razões entre passos: 1.75, 1.45, 1.22, 1.13, 1.33, 1.09 — sem progressão consistente. Fora isso, valores soltos aparecem espalhados: `10.5px` (`.card-title`), `0.7rem`, `0.82rem`, `0.85rem`, `0.875rem`, `0.8125rem`, `0.95rem`.

O `10.5px` do `.card-title` (`style.css:416`) merece atenção à parte: uppercase, `letter-spacing: 0.03em`, em `--text-muted`. Tecnicamente passa em contraste (5.07:1), mas 10,5px é pequeno demais para o rótulo que identifica o KPI.

**Correção:** adotar 1.25 (major third) a partir de 16px → 12.8 / 16 / 20 / 25 / 31 / 39 / 49px, registrar como `--font-size-*` e substituir os valores soltos. Elevar `.card-title` para 12px.

---

### M5 · Border-radius fora da escala
**Skill:** `02 §10` ("componentes do mesmo nível devem compartilhar o mesmo radius")

Existem `--radius-xs/sm/md/lg/pill`, mas há 20 declarações com pixels literais: `12px` (`.panel--nested`, `.side-card`), `10px` (`.dup-crypto-table-wrap`, `.dup-path-tooltip`), `8px` (`.sidebar-toggle-btn` na 1ª definição, `.card-icon`, `.cmd-pre`, `.hint-warn`), `6px`, `4px`. Cards nominalmente do mesmo nível hierárquico (`.dashboard-card` com `--radius-lg` = 18px vs `.side-card` com 12px literal) têm cantos visivelmente diferentes.

---

### M6 · Regras CSS duplicadas
**Skill:** `08 §2`

`.topbar-actions` é definida duas vezes — `style.css:821` e `style.css:1608` — com `justify-content` conflitante (`flex-start` implícito vs `space-between`). `.sidebar-toggle-btn` idem: `style.css:828` (40×36px, `border-radius: 8px`) e `style.css:1616` (40×40px, `var(--radius-md)`). A segunda vence pela ordem da cascata, deixando ~35 linhas mortas que confundem manutenção futura.

---

### M7 · Exportações usam `alert()` para avisar sobre truncamento ✅ CORRIGIDO
**Skill:** `01 §1.9`, `07 §16` (alertas/banners)

`index.html:454`, `historico.html:253`, `vencidos.html:412`: quando o servidor trunca a lista, o usuário recebe um `alert()` bloqueante **depois** que o download já começou. A informação é importante (o arquivo está incompleto) — e por isso mesmo `07 §15` diz que informação crítica não deve ser toast, mas sim alerta persistente.

**Correção:** banner persistente no topo da tabela (`.hint-warn` já existe) informando o limite **antes** da exportação, quando o total filtrado excede o limite do servidor. Prevenção > mensagem de erro (`01 §1.5`).

---

### M8 · `innerHTML` com dados do servidor sem escape ✅ CORRIGIDO

Os três pontos citados foram resolvidos por caminhos diferentes, e o melhor deles não é escapar: `showToast` e a lista de notificações passaram a montar o DOM com `textContent`, que não interpreta markup nenhum. `renderEmptyState`, que precisa de HTML, usa `esc()` em cada interpolação. A função vive em `ui-common.js` e é usada por 9 templates.
**Skill:** `08 §6`

`ui-common.js:481-490` monta notificações interpolando `it.mensagem` e `it.documento` direto em template string; `showToast()` (`:225`) e `renderEmptyState()` (`:259`) fazem o mesmo com seus parâmetros. Como esses dados derivam do CN de certificados (controlado por quem gera o `.pfx`), um CN com markup é injetável.

O risco prático está **mitigado pela CSP com nonce** (`{{ request.state.nonce }}` presente em todos os templates), que bloqueia tanto `<script>` inline quanto handlers `onerror=`. Por isso classifiquei como médio e não alto. Ainda assim, o dashboard já tem a função certa — `esc()` em `index.html:304` — e ela deveria estar em `ui-common.js` e ser usada nesses três pontos.

---

### M9 · `setInterval` de notificações nunca é limpo ✅ CORRIGIDO
**Skill:** `08 §6` ("sempre limpar event listeners e timers")

`ui-common.js:562`: `setInterval(fetchNotifications, 60000)` roda indefinidamente, inclusive com a aba em segundo plano. Em navegação de dia inteiro com a aba aberta, são ~480 requisições autenticadas desnecessárias.

**Correção:** pausar com `document.visibilityState`:
```js
let notifTimer = setInterval(fetchNotifications, 60000);
document.addEventListener("visibilitychange", () => {
  clearInterval(notifTimer);
  if (document.visibilityState === "visible") {
    fetchNotifications();
    notifTimer = setInterval(fetchNotifications, 60000);
  }
});
```

---

### M10 · Grid de cards travado em 5 colunas ✅ CORRIGIDO
**Skill:** `03 §8`, `08 §3`

`style.css:384-388` força `repeat(5, 1fr) !important` acima de 960px. Funciona hoje porque há exatamente 5 cards — mas `style.css:1350` já prevê um `:nth-child(6)` com delay de animação, sinalizando que um 6º card foi planejado. Quando ele chegar, o layout quebra em 5+1 órfão. O `auto-fit`/`minmax` da linha 379 (que a skill `03 §8` recomenda explicitamente) já resolveria sozinho, sem `!important`.

**Correção:** `grid-template-columns: repeat(auto-fit, minmax(180px, 1fr))` e remover a media query. Se o requisito é mesmo "5 em linha no 1440px", usar `repeat(auto-fit, minmax(min(180px, 100%), 1fr))` com `max-width` no container.

---

### M11 · `body { display: flex }` redundante com sidebar `position: fixed`
**Skill:** `08 §2`

`style.css:165` põe o body em flex, mas `.sidebar` é `position: fixed` (`:262`) — fora do fluxo, portanto não participa do flex. O alinhamento vem de `margin-left: 250px` no `.main-content` (`:351`). O `display: flex` não faz nada além de tornar o layout mais difícil de raciocinar. Em `login.html:10-18` o body é redeclarado como flex centralizado, e depois há um `<main>` com `display:flex` inline fazendo a mesma centralização — três camadas para centrar um card.

---

### M12 · Nenhum estado `:active` nem `:disabled` visual nos botões ✅ CORRIGIDO
**Skill:** `02 §8` ("todo componente interativo precisa definir Default, Hover, Focus, Active, Disabled, Loading, Error")

`button` tem `:hover` (`style.css:532`) e `:focus-visible` (global). Não tem `:active` (exceto `.sidebar-toggle-btn:active`) nem `:disabled`. O `.cg-page-link` é a exceção que fez certo (`:disabled { opacity: 0.45; cursor: not-allowed }` — `style.css:1276`). O botão "Entrar" do login desabilita durante o request (`login.html:140`) mas sem nenhuma pista visual além do texto mudar.

**Correção:** generalizar o padrão que já existe no `.cg-page-link` para o seletor `button`.

---

## 🔵 BAIXO

| # | Achado | Skill | Local |
|---|---|---|---|
| B1 | 16 usos de `!important` no CSS — a skill pede evitá-lo como regra geral | `08 §2` | `style.css` |
| B2 | ~~115 atributos `style=` inline~~ ⚖️ **MEDIDO E DESACONSELHADO em 17/08.** São 201 hoje, mas **um único** tem cor literal — o M2 já limpou. O resto é layout (`font-size`, `margin`, `display`). Converter seria churn caro sem melhorar o tema escuro em nada. | `08 §2` | `templates/*` |
| B3 | ~~Logo sem `width`/`height`~~ ✅ **CORRIGIDO 17/08, com a premissa corrigida junto.** Não eram 8 telas: a sidebar virou partial na Etapa 0, então havia **duas** `<img>` no projeto. E não há CLS — `.brand-icon` e `.login-logo` já reservam a caixa por CSS. Os atributos entraram por outro motivo: se o `style.css` não carregar, o PNG de 512px renderiza em tamanho natural. | `08 §7` | `_sidebar.html`, `login.html` |
| B4 | Sem `<meta name="description">` (páginas são privadas, então o impacto de SEO é nulo — só relevante se `/login` for indexável) | `08 §8` | todos os templates |
| B5 | ~~`.cg-page-link:focus` usa `:focus` puro~~ ✅ **CORRIGIDO 17/08.** Virou `:focus-visible`. As demais regras `:focus` do arquivo ficam: realçam o CAMPO (borda/sombra ao clicar dentro), não desenham anel. `.skip-to-content:focus` precisa de `:focus` mesmo. | `04 §5` | `style.css` |
| B6 | ~~`cursor: help` sem `aria-describedby`~~ ✅ **CORRIGIDO 17/08, e era maior que isto.** Não faltava rótulo: o balão de caminhos só respondia a `mouseover`, então quem navega por teclado nunca chegava à informação. As linhas ganharam `tabindex`, `aria-describedby`, tratamento de foco e Esc (WCAG 2.2 §1.4.13). Vale para os dois balões. | `01 §9` | `duplicidades.html`, `style.css` |
| B7 | ~~Toast com `duration = 4000` fixo~~ ✅ **JÁ ESTAVA CORRIGIDO** (constatado em 17/08, item estava desatualizado). `_toastDuracao()` escala de 4s a 12s por tamanho da mensagem. | `07 §15` | `ui-common.js` |
| B8 | ~~Textos de UI misturam pt-BR e pt-PT~~ ✅ **CORRIGIDO 17/08.** 38 trocas em 12 arquivos, travado por `test_ui_nao_mistura_pt_br_com_pt_pt`. | `01 §10` (linguagem do usuário) | vários |

O B8 aparece em pelo menos 8 pontos e é o mais visível para o usuário final desta lista.

---

## Plano de ação priorizado

### ✅ Sprint 1 — Correções funcionais — CONCLUÍDO em 2026-08-02

1. ✅ **C3** — `prefers-reduced-motion` não zera mais `transform` globalmente
2. ✅ **C2** — tema do sistema detectado; `data-theme` removido no modo "seguir o sistema"
3. ✅ **A1** — tokens de texto de status, validados nos dois temas
4. ✅ **A3** — sticky headers funcionando em 9 tabelas de 6 telas
5. ✅ **M2** — `#f59e0b`, `#dc2626`, `#ef4444` e `#b91c1c` substituídos por tokens

**Arquivos alterados:** `static/style.css`, `static/ui-common.js`, 8 templates.

**Refinamentos incorporados durante a implementação** (não previstos no plano original):

- **Cache buster obrigatório.** O HTML novo depende do CSS/JS novos (`.table-scroll` sem estilo = sem sticky e sem altura máxima). Sem trocar o `?v=`, todo usuário com cache quente receberia HTML novo com CSS velho. `?v=cg-v2-fluid` e `?v=cg-nav-2` → `?v=s1-a11y-2026-08` nas 15 referências.
- **Âncora do loading separada da área que rola.** `.table-scroll` virou um container de rolagem; se o overlay de loading fosse ancorado nele, `inset: 0` resolveria contra a altura **total** do conteúdo e o spinner cairia fora da parte visível em tabelas longas. Daí a estrutura em dois níveis: `.table-scroll-anchor` (não rola, ancora o overlay) > `.table-scroll` (rola). `setTableLoading()` foi atualizado para preferir a âncora.
- **`setTableLoading` dependia do estilo inline removido.** O seletor era `div[style*="overflow-x"]`. Ao converter os inline styles em classe, ele deixaria de casar. Corrigido com uma cadeia de fallback explícita.
- **`tabindex` condicional.** Área rolável precisa ser focável por teclado (WCAG 2.1.1), mas com 10 linhas por página a tabela cabe inteira e o `tabindex="0"` viraria uma parada de tabulação inútil, além de poluir a lista de regiões do leitor de tela. `initRegioesRolaveis()` liga/desliga `tabindex` e `role` via `ResizeObserver`, conforme a tabela realmente transborde.
- **Toggle de tema volta a seguir o sistema.** Quando o usuário alterna para o tema que já coincide com o do SO, a preferência é apagada em vez de congelada — assim ele volta a acompanhar o modo noturno automático. Um listener de `matchMedia` aplica a troca em tempo real.
- **Ícone do botão reflete o tema em vigor.** Antes, no modo "seguir o sistema" com SO escuro, o botão ofereceria "ativar modo escuro" — o tema que já estava ativo.
- **`transition-duration: 0.01ms` em vez de `0s`** no bloco de reduced-motion: `0s` impede o disparo de `transitionend`, do qual `removeToast()` depende para remover o nó do DOM — os toasts vazariam.

**Validação executada:**

| Verificação | Resultado |
|---|---|
| Contraste WCAG nos dois temas | 12/12 passam (antes: 6 falhas) |
| Balanço de tags `<div>` nos 8 templates | 8/8 equilibrados |
| Compilação Jinja2 dos 8 templates | 8/8 OK |
| Sintaxe JS (`node --check`) | OK |
| Chaves CSS (278 abrem / 278 fecham) | OK |
| Portal servindo as 7 rotas | 7/7 HTTP 200 |
| Assets com o novo `?v=` | 200 (42 KB CSS / 28 KB JS) |
| Markup novo no HTML renderizado | confirmado |
| Resíduos de cor hardcoded | 0 |
| `pytest tests/` | **41 passed** |

**Não validado automaticamente** — depende de inspeção visual no navegador:
- Sticky header grudando de fato ao rolar uma tabela com 100 linhas por página
- Drawer mobile abrindo/fechando com `prefers-reduced-motion: reduce` ativo
- Aparência dos badges recoloridos nos dois temas

### ✅ Sprint 2 — Fechar a Fase 3 — CONCLUÍDO em 2026-08-02

6. ✅ **C1a** — os 17 `alert()` eliminados (restam 0 no código)
7. ✅ **C1b** — estados vazios em 6 tabelas, 18 pontos de chamada
8. ✅ **C1c** — skeleton loaders no primeiro carregamento de 3 telas
9. ✅ **M7** — banner de limite exibido **antes** da exportação

**Arquivos alterados:** `app/main.py`, `static/ui-common.js`, `static/style.css`, 8 templates.

**Decisão de arquitetura: `renderEmptyState()` não servia para tabelas.**
A função entregue na Fase 3 substitui o `innerHTML` do container — numa tabela isso destruiria o `<thead>`, e o usuário perderia a referência de quais colunas existem. Foi criada `renderEmptyRow(tbody, colspan, opts)`, que insere o estado vazio como uma linha única com `colspan`, preservando o cabeçalho. `renderEmptyState()` continua disponível para containers que não sejam tabela.

**Mudança de backend necessária para o M7.**
O plano pedia avisar sobre truncamento *antes* de exportar, mas `LISTAGEM_EXPORT_MAX = 5000` era constante interna de `app/main.py`, invisível ao cliente — que só descobria o truncamento pelo campo `lista_truncada`, depois que o arquivo já havia sido gerado incompleto. Foi adicionado `export_max` ao objeto `paginacao` das três rotas de listagem (`/api/certificados`, `/historico`, `/vencidos`). Zero requisições extras: o valor chega junto com os dados que a tabela já busca. O banner agora aparece assim que o filtro ultrapassa o limite, e o toast pós-exportação ficou como confirmação do que de fato saiu.

**Refinamentos incorporados:**

- **Estado vazio sensível ao contexto.** "Sem resultado" e "sem dado" são situações diferentes e recebem textos diferentes. Sem filtro ativo, o dashboard explica que o agente ainda não enviou dados; com filtro, oferece um botão **Limpar filtros**. Em `/vencidos`, zero resultados sem filtro é tratado como bom resultado ("Todos os certificados monitorados estão dentro da validade", ícone ✅), não como falha.
- **Toast que sobrevive ao redirecionamento.** Em `configuracao.html` e `usuarios.html`, o `alert()` de acesso negado era seguido de `window.location.href`. Um toast comum sumiria junto com a página. `showToastAfterRedirect()` grava em `sessionStorage` e o toast é exibido na página de destino.
- **Skeleton só no primeiro carregamento.** Nas recargas (filtro, paginação) o overlay é mantido, preservando a tabela anterior visível. Trocar tudo por blocos cinzentos a cada tecla digitada na busca seria mais agitado, não mais informativo.
- **Toasts seguem `07 §15`.** Duração proporcional ao texto (~55ms/caractere, mínimo 4s, teto 12s) e no máximo 3 empilhados, substituindo os mais antigos — dois requisitos explícitos da skill que a implementação original não atendia.
- **Erros agora deixam a tabela em estado recuperável.** Antes, um erro só trocava o texto de status e a tabela ficava com o conteúdo antigo (ou, com skeleton, travada em blocos cinzentos para sempre). Agora cada ramo de erro — HTTP, JSON inválido, falha de conexão — renderiza um estado com botão **Tentar novamente**.
- **Helpers montam DOM com `textContent`, não `innerHTML`.** Mensagens carregam nome/CN do titular do certificado, que é conteúdo de terceiros. Fecha parte do **M8** antes do previsto.
- **`removeToast` com rede de segurança.** O `transitionend` não dispara com a aba oculta; sem isso os toasts vazariam no DOM.

**Validação executada:**

| Verificação | Resultado |
|---|---|
| `alert()` remanescentes | **0** (eram 17) |
| Sintaxe dos 8 blocos `<script>` inline | 8/8 compilam |
| `node --check` em `ui-common.js` | OK |
| Referências a helpers resolvem | 38 usos, 0 indefinidos |
| Ordem de carga (ui-common antes do inline) | 7/7 correta |
| `colspan` × nº real de colunas | 18/18 conferem |
| Testes unitários dos helpers (shim de DOM) | **20/20 passam** |
| `export_max` nas 3 rotas | 3/3 retornam 5000 |
| Portal servindo as rotas | 8/8 HTTP 200 |
| `pytest tests/` | **41 passed** |

**Fora do escopo, encontrado durante a implementação:**

`usuarios.html` usa 4 `prompt()` nativos para editar usuário e redefinir senha (linhas 287, 289, 292, 312). É pior que o `alert()` que acabamos de remover: `prompt()` não valida, não permite cancelar campo a campo, e no caso da senha exibe o valor digitado em texto claro. O `confirm()` de desativação (linha 327) foi **mantido de propósito** — é acessível, tem focus trap nativo do navegador, e substituí-lo por um modal caseiro sem focus trap seria uma regressão (`07 §14`). Recomendo tratar os `prompt()` num sprint próprio, com formulário inline ou modal adequado.

`duplicidades.html` não recebeu estado vazio nas 3 tabelas porque já possui o elemento `#sem-dup` cumprindo essa função no nível da página.

### ✅ Sprint 3 — Acessibilidade AA — CONCLUÍDO em 2026-08-02

10. ✅ **A4** — 42 campos, 0 sem rótulo acessível
11. ✅ **A5** — `aria-expanded`, `aria-haspopup`, `aria-controls` e retorno de foco
12. ✅ **A6** — alvos de toque ≥44px
13. ⚠️ **A2** — **achado superdimensionado na auditoria**, ver abaixo
14. ✅ **M12** — estados `:active`/`:disabled` generalizados

**Arquivos alterados:** `static/style.css`, `static/ui-common.js`, 6 templates.

> **Correção do diagnóstico: o A4 contava 43 campos e 27 labels.**
> Era contagem bruta, não análise de cobertura — vários campos já tinham `<label for>` ou `aria-label`. A verificação campo a campo apontou **15 sem rótulo acessível**, não 43. Todos foram corrigidos.

> **Correção do diagnóstico: o A2 estava superdimensionado.**
> A auditoria afirmava que os badges precisavam de forma além da cor. Na verificação, os badges **já carregam texto** ("Ativo", "Expirando", "Vencido") e os 5 cards do dashboard **já têm ícones SVG distintos** mais título em texto — `04 §9` já estava satisfeito nos dois casos.
> Acrescentar um glifo via `::before` teria custo real: leitores de tela anunciam conteúdo de pseudo-elemento, e o usuário ouviria "check Ativo". Seria decoração com prejuízo de acessibilidade, então **não foi feito**.
> O que era real naquela área: os fundos de linha de `colaborador_certificados.html` usavam `#fef2f2`/`#fffbeb` hardcoded — invisíveis no tema escuro. Foram promovidos a `--row-tint-danger`/`--row-tint-warning` com variante escura.

**Achado grave durante a verificação: o Sprint 1 corrigiu apenas metade do problema de contraste.**

A correção anterior tratou `.badge-*` e `.error-cell` no `style.css`. O mesmo padrão — cor de status usada como **texto** sobre seu próprio fundo tonal — estava replicado em **13 outros pontos**, incluindo dois arquivos que a busca do Sprint 1 não cobriu (o `<style>` inline de `usuarios.html` e o de `login.html`):

| Elemento | Arquivo | Antes | Depois |
|---|---|---|---|
| `.role-admin` | `usuarios.html` (inline) | 3.24:1 ❌ | 5.68:1 ✅ |
| `.role-user` | `usuarios.html` (inline) | 2.04:1 ❌ | 4.95:1 ✅ |
| `.btn-danger` | `usuarios.html` (inline) | 3.24:1 ❌ | 5.68:1 ✅ |
| `#login-error` | `login.html` (inline) | 3.24:1 ❌ | 5.68:1 ✅ |
| `#path-sync-msg` | `configuracao.html` | 2.22:1 ❌ | 5.39:1 ✅ |
| `button.danger` | `style.css` | 3.24:1 ❌ | 5.68:1 ✅ |
| `.toast-success .toast-icon` | `style.css` | 2.22:1 ❌ | 5.39:1 ✅ |
| `.toast-error .toast-icon` | `style.css` | 3.55:1 ❌ | 6.23:1 ✅ |
| `.toast-warning .toast-icon` | `style.css` | 2.06:1 ❌ | 6.39:1 ✅ |
| `.notif-expired .notif-badge-type` | `style.css` | 3.24:1 ❌ | 5.68:1 ✅ |
| `.notif-expiring .notif-badge-type` | `style.css` | 1.93:1 ❌ | 6.01:1 ✅ |
| `.card-validos .card-icon` | `style.css` | 2.04:1 ❌ | 4.95:1 ✅ |
| `.card-expirando .card-icon` | `style.css` | 1.93:1 ❌ | 6.01:1 ✅ |

Lição de método: uma busca por `grep` no arquivo de estilo principal não basta neste projeto — 4 dos 8 templates têm bloco `<style>` próprio. Verificações futuras de token precisam varrer `templates/` também.

**Refinamentos incorporados:**

- **Rótulos visíveis no formulário de criação de usuário**, não `.cg-sr-only`. É onde o placeholder-como-label mais atrapalha: ao digitar, o usuário perde a referência de qual campo está preenchendo. Nas toolbars de busca/filtro, o rótulo oculto é suficiente — a função do campo é óbvia pelo contexto e um rótulo visível competiria por espaço.
- **`autocomplete="new-password"` no cadastro de usuário.** Sem isso, o navegador tende a preencher a senha do próprio admin no campo destinado à senha inicial de outra pessoa. Adicionado `autocomplete="off"` em nome e e-mail pelo mesmo motivo, e `minlength="6"` para validar no cliente o que a mensagem já prometia.
- **`Esc` do painel de notificações saiu do handler global.** O handler genérico de teclado fechava o dropdown mas deixava o foco no `<body>` — a navegação por teclado recomeçaria do topo da página. O novo handler vive em `initNotifications()`, único escopo que conhece o botão que abriu o painel, e devolve o foco a ele. A duplicação no handler global foi removida.
- **Abrir/fechar centralizado em `definirDropdownAberto()`.** Havia três caminhos de fechamento (clique no botão, clique fora, `Esc`); com `aria-expanded` a manter em sincronia, três lugares independentes viram três oportunidades de dessincronizar.
- **`.toast-close` com margem negativa.** O alvo foi de ~20×17px para 44×44px, mas a margem negativa evita que o toast inche visualmente — a área clicável cresce, o desenho não.

**Validação executada:**

| Verificação | Resultado |
|---|---|
| Campos sem rótulo acessível | **0 de 42** (eram 15) |
| Contraste dos 13 pontos corrigidos, 2 temas | **13/13 passam** |
| `aria-expanded` no dropdown | presente + sincronizado nos 3 caminhos |
| Retorno de foco no `Esc` | implementado |
| Alvos de toque ≥44px | 6 regras aplicadas |
| Estados `:active`/`:disabled` | generalizados para `button` |
| `node --check` em `ui-common.js` | OK |
| Chaves CSS | 291/291 |
| Balanço de `<div>` nos templates | 8/8 |
| Portal servindo as rotas | 8/8 HTTP 200 |
| `pytest tests/` | **41 passed** |

### ✅ Sprint 4 — Mobile e performance — CONCLUÍDO em 2026-08-02

15. ✅ **A7** — 9 tabelas viram cards empilhados < 768px, com semântica preservada
16. ✅ **A9** — `@import` → `preconnect` + `link`; peso 800 removido
17. ✅ **M3** — `will-change` em massa removido
18. ✅ **M9** — polling pausado com `visibilitychange`
19. ✅ **M10** — grid fluido, sem media query e sem `!important`

**Arquivos alterados:** `static/style.css`, `static/ui-common.js`, 8 templates.

**A decisão do A9 estava documentada no próprio repositório.**
A auditoria deixou em aberto se a Inter é fonte de marca ou peso morto. `docs/guia-design-apple.md` §3 resolve: *"A Apple usa SF Pro como fonte principal. Para projetos web, use a stack a seguir para garantir a fonte nativa do sistema"* — com a Inter listada por último e descrita como "alternativa gratuita". A ordem atual (`-apple-system` → `BlinkMacSystemFont` → `Inter`) portanto está **correta e intencional**: macOS/iOS recebem SF Pro real, e a Inter atende Windows — plataforma principal deste produto, já que o agente roda em Windows Server. Reordenar teria mudado a aparência no macOS sem ganho.

Só o mecanismo de carga mudou: `@import` (cadeia serial) → `preconnect` + `<link>` no `<head>` (paralelo). Bônus: o peso **800 era baixado e nunca usado** — o projeto só usa 400, 500, 600 e 700. Removido da URL.

A CSP já autorizava `fonts.googleapis.com` em `style-src` e `fonts.gstatic.com` em `font-src` (`app/main.py:133-134`), então a mudança não exigiu ajuste de segurança.

**O A7 tinha uma armadilha de acessibilidade.**
O padrão usual de tabela responsiva aplica `display: block` em `table`/`tr`/`td`. Isso funciona visualmente, mas faz o navegador **descartar os papéis implícitos** de tabela — o leitor de tela perde a associação linha/coluna e passa a ler uma lista solta de valores. Seria uma regressão de acessibilidade disfarçada de melhoria de acessibilidade.

Por isso os papéis foram declarados explicitamente: `role="table"` nas 9 tabelas, `role="rowgroup"` em `thead`/`tbody`, `role="columnheader"` nos 35 `<th>`, e `role="row"`/`role="cell"` nas linhas geradas por JS. Com os papéis explícitos, a semântica sobrevive ao `display: block`. O `<thead>` sai da tela por `clip`, não por `display: none`, para permanecer na árvore de acessibilidade.

**Refinamentos incorporados:**

- **`data-label` conferido contra o cabeçalho de cada coluna.** As 34 etiquetas foram cruzadas com os `<th>` correspondentes, na ordem. Algumas foram encurtadas de propósito para caber em 375px ("Documento (CPF/CNPJ)" → "Documento", "Última data verificada" → "Última verificação").
- **Coluna de ações sem `data-label`.** Em `/usuarios`, a última coluna são botões; um rótulo "Ações" à esquerda deles seria ruído. O CSS trata `td:not([data-label])` alinhando à esquerda, sem prefixo.
- **Regressão evitada no helper do Sprint 1.** Abaixo de 768px o `.table-scroll` vira `overflow: visible`, mas `scrollHeight > clientHeight` continua verdadeiro num elemento que não rola — `initRegioesRolaveis()` teria adicionado `tabindex="0"` a cada tabela, criando paradas de tabulação fantasma no mobile. O helper agora consulta `getComputedStyle` e só considera rolável o que de fato rola.
- **Linhas de estado excluídas do layout de cards.** `renderEmptyRow()` e `renderSkeletonRows()` passaram a marcar `.cg-state-row`; sem isso, o estado vazio viraria um "card" com rótulo de coluna. As linhas `.hint-only` de `/duplicidades` receberam a mesma marca.
- **`aria-label` nos checkboxes de seleção.** Em `/acompanhamento`, a coluna "Selecionar" tinha checkboxes sem nome acessível — no layout de cards, sem o cabeçalho visível, ficariam ainda mais ambíguos. Agora anunciam "Acompanhar «nome do titular»".
- **`min(180px, 100%)` no grid dos cards.** `minmax(180px, 1fr)` puro transbordaria o container em telas de 320px.
- **Busca imediata ao voltar para a aba.** Ao retomar a visibilidade, o polling não espera o próximo ciclo de 60s — o dado pode estar uma hora desatualizado.

**Validação executada:**

| Verificação | Resultado |
|---|---|
| `data-label` × cabeçalho de coluna | **34/34** conferem, na ordem |
| Papéis ARIA aplicados | 9 `table`, 35 `columnheader`, rows/cells no JS |
| `@import` no CSS servido | **0** (era 1) |
| `will-change` em massa | removido; resta 1 uso delimitado |
| Sintaxe dos blocos `<script>` | 8/8 compilam |
| `node --check` em `ui-common.js` | OK |
| Chaves CSS | 300/300 |
| Balanço de `<div>` | 8/8 |
| Portal servindo as rotas | 8/8 HTTP 200 |
| `pytest tests/` | **41 passed** |

### Backlog — Débito técnico (~1 dia)
20. **A8** — recuperação de senha e toggle de visibilidade no login
21. **M4/M5** — escala tipográfica modular e radius tokenizado
22. **M6/M11** — remover CSS duplicado e o flex redundante do body
23. **M8** — `esc()` compartilhado em `ui-common.js`
24. **B8** — padronizar pt-BR

---

## Validação recomendada ao final

Conforme `08 §10` e `04 §11`:

- [ ] Lighthouse ≥ 90 em Acessibilidade nas 5 telas principais
- [ ] Navegação completa por teclado no dashboard (Tab → filtro → busca → tabela → paginação), sem armadilha de foco
- [ ] Contraste revalidado nos **dois** temas (a skill `04 §2` alerta que escuro não é inversão do claro)
- [ ] Teste em 320 / 768 / 1024 / 1440px + uma ultrawide (`03 §11`)
- [ ] Zoom 200% sem quebra de layout (`04 §10` — reflow)
- [ ] Simulador de deuteranopia nos cards e badges (`04 §9`)
- [ ] Teste com `prefers-reduced-motion: reduce` ativo — o drawer mobile abre e fecha?

---

## Nota metodológica

Os contrastes foram calculados por luminância relativa segundo a fórmula do WCAG, não estimados visualmente (`04 §2`: "nunca confiar apenas em preview visual"). Os três achados críticos foram verificados por leitura da cascata CSS e do fluxo de execução do JS — não são inferências de padrão. Os achados C2, C3 e A3 se manifestam apenas em condições específicas (sistema em modo escuro, `prefers-reduced-motion` ativo, tabela mais alta que a viewport) e recomendo reproduzi-los antes de corrigir, para confirmar o diagnóstico.

Conforme `00 §10`, esta auditoria é uma hipótese informada por heurísticas — não substitui teste de usabilidade com os operadores reais do sistema.
