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

### A2 · Status transmitido apenas por cor
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

### A4 · Inputs e selects sem `<label>` associado
**Skill:** `04 §7` ("nunca apenas `placeholder` como substituto de label")

43 `<input>`/`<select>` nas telas, 27 `<label>`. O caso mais visível é a toolbar do dashboard (`index.html:156-169`): o `#filtro-status` e o `#busca-cert` têm apenas `title` e `placeholder`. Leitor de tela anuncia "caixa de edição, em branco" ou lê o placeholder — que desaparece assim que o usuário digita.

**Correção:** `<label for="busca-cert" class="cg-sr-only">Buscar certificado</label>` — a classe `.cg-sr-only` já existe em `style.css:1186` e está sendo usada corretamente em `index.html:216`. É só replicar o padrão.

---

### A5 · Dropdown de notificações sem `aria-expanded` nem gestão de foco
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

### A6 · Alvos de toque abaixo do mínimo
**Skill:** `03 §9` (44×44px), `04 §10` (WCAG 2.5.8 — mínimo 24×24px)

| Elemento | Tamanho computado | 44px | 24px |
|---|---|---|---|
| `.toast-close` (`style.css:1781`) | ~20×17px | ❌ | ❌ **falha WCAG AA** |
| `.cg-page-link` (`style.css:1253`) | 36px altura | ❌ | ✅ |
| `.sidebar-toggle-btn` | 40×40px | ❌ | ✅ |

O `.toast-close` é o único que reprova no critério normativo 2.5.8 (`font-size: 1.25rem; line-height: 1; padding: 0 0.25rem` produz ~20px de altura).

**Correção:** `.toast-close { min-width: 44px; min-height: 44px; display: inline-flex; align-items: center; justify-content: center; }` e `.cg-page-link { min-height: 44px; }`.

---

### A7 · Tabela força scroll horizontal no mobile
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

### A8 · Tela de login sem recuperação de senha nem toggle de visibilidade
**Skill:** `07 §1` (estrutura e problemas comuns do padrão Login)

`templates/login.html` acerta o essencial (`autocomplete="username"`/`"current-password"`, `role="alert"`, erro genérico que não revela qual campo falhou — `07 §1` cumprido). Faltam dois itens que a skill lista explicitamente como **problemas comuns**:

- **Sem "Esqueci minha senha"** — o usuário que perde a senha não tem saída na interface; depende de um admin em `/usuarios`. Viola também `01 §1.3` (controle e liberdade do usuário).
- **Sem toggle mostrar/ocultar senha** — listado como problema comum em `07 §1`.

Menor, mas relacionado: o botão diz "Entrar" (`login.html:125`). `06 §1` pede que o CTA descreva o resultado — "Acessar o painel" seria mais alinhado.

---

### A9 · Fonte carregada por `@import` (render-blocking em cascata)
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

### M1 · Tokens de cor duplicados em dois blocos
**Skill:** `02 §5` (arquitetura de tokens em 3 camadas)

`style.css:74-111` (`:root[data-theme="dark"]`) e `style.css:113-152` (`@media prefers-color-scheme: dark`) são **40 linhas idênticas copiadas**. Qualquer ajuste de cor no escuro precisa ser feito em dois lugares — e um deles (C2) nem está ativo hoje.

**Correção:** extrair para uma classe única e aplicá-la nos dois seletores:
```css
:root[data-theme="dark"],
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) { … } }
```
Não é possível agrupar seletor e media query diretamente; a saída limpa é declarar os tokens escuros em `.theme-dark` e aplicar essa classe via JS + fallback CSS, ou aceitar a duplicação com um comentário `/* MANTER SINCRONIZADO COM linha 74 */`. Recomendo a segunda para o porte deste projeto — refatorar tokens tem custo alto e ganho baixo aqui.

---

### M2 · Cores hardcoded que quebram no modo escuro
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

### M3 · `will-change` aplicado em massa
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

### M8 · `innerHTML` com dados do servidor sem escape
**Skill:** `08 §6`

`ui-common.js:481-490` monta notificações interpolando `it.mensagem` e `it.documento` direto em template string; `showToast()` (`:225`) e `renderEmptyState()` (`:259`) fazem o mesmo com seus parâmetros. Como esses dados derivam do CN de certificados (controlado por quem gera o `.pfx`), um CN com markup é injetável.

O risco prático está **mitigado pela CSP com nonce** (`{{ request.state.nonce }}` presente em todos os templates), que bloqueia tanto `<script>` inline quanto handlers `onerror=`. Por isso classifiquei como médio e não alto. Ainda assim, o dashboard já tem a função certa — `esc()` em `index.html:304` — e ela deveria estar em `ui-common.js` e ser usada nesses três pontos.

---

### M9 · `setInterval` de notificações nunca é limpo
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

### M10 · Grid de cards travado em 5 colunas
**Skill:** `03 §8`, `08 §3`

`style.css:384-388` força `repeat(5, 1fr) !important` acima de 960px. Funciona hoje porque há exatamente 5 cards — mas `style.css:1350` já prevê um `:nth-child(6)` com delay de animação, sinalizando que um 6º card foi planejado. Quando ele chegar, o layout quebra em 5+1 órfão. O `auto-fit`/`minmax` da linha 379 (que a skill `03 §8` recomenda explicitamente) já resolveria sozinho, sem `!important`.

**Correção:** `grid-template-columns: repeat(auto-fit, minmax(180px, 1fr))` e remover a media query. Se o requisito é mesmo "5 em linha no 1440px", usar `repeat(auto-fit, minmax(min(180px, 100%), 1fr))` com `max-width` no container.

---

### M11 · `body { display: flex }` redundante com sidebar `position: fixed`
**Skill:** `08 §2`

`style.css:165` põe o body em flex, mas `.sidebar` é `position: fixed` (`:262`) — fora do fluxo, portanto não participa do flex. O alinhamento vem de `margin-left: 250px` no `.main-content` (`:351`). O `display: flex` não faz nada além de tornar o layout mais difícil de raciocinar. Em `login.html:10-18` o body é redeclarado como flex centralizado, e depois há um `<main>` com `display:flex` inline fazendo a mesma centralização — três camadas para centrar um card.

---

### M12 · Nenhum estado `:active` nem `:disabled` visual nos botões
**Skill:** `02 §8` ("todo componente interativo precisa definir Default, Hover, Focus, Active, Disabled, Loading, Error")

`button` tem `:hover` (`style.css:532`) e `:focus-visible` (global). Não tem `:active` (exceto `.sidebar-toggle-btn:active`) nem `:disabled`. O `.cg-page-link` é a exceção que fez certo (`:disabled { opacity: 0.45; cursor: not-allowed }` — `style.css:1276`). O botão "Entrar" do login desabilita durante o request (`login.html:140`) mas sem nenhuma pista visual além do texto mudar.

**Correção:** generalizar o padrão que já existe no `.cg-page-link` para o seletor `button`.

---

## 🔵 BAIXO

| # | Achado | Skill | Local |
|---|---|---|---|
| B1 | 16 usos de `!important` no CSS — a skill pede evitá-lo como regra geral | `08 §2` | `style.css` |
| B2 | 115 atributos `style=` inline nos templates, incluindo cores e paddings que já são tokens | `08 §2` | `templates/*` |
| B3 | Logo sem `width`/`height` explícitos nas 8 telas → risco de CLS | `08 §7` | todos os templates |
| B4 | Sem `<meta name="description">` (páginas são privadas, então o impacto de SEO é nulo — só relevante se `/login` for indexável) | `08 §8` | todos os templates |
| B5 | `.cg-page-link:focus` usa `:focus` puro (`style.css:1270`) enquanto o resto do projeto usa `:focus-visible` — anel aparece em clique de mouse | `04 §5` | `style.css:1270` |
| B6 | Ícone de status usa `cursor: help` em `.dup-igual-row` sem `title` ou `aria-describedby` correspondente em todas as linhas | `01 §9` | `style.css:933` |
| B7 | Toast tem `duration = 4000` como padrão — no limite mínimo da skill; mensagens longas de erro precisam de mais | `07 §15` | `ui-common.js:204` |
| B8 | Textos de UI misturam pt-BR e pt-PT ("registos", "ficheiro", "separador" vs "registros", "arquivo", "aba") | `01 §10` (linguagem do usuário) | `index.html:556, 624`, `vencidos.html`, `historico.html` |

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

### Sprint 3 — Acessibilidade AA (~1,5 dia)
10. **A4** — labels `.cg-sr-only` nos 43 inputs/selects (1h30)
11. **A5** — `aria-expanded` + retorno de foco no dropdown (45min)
12. **A6** — alvos de toque ≥44px (30min)
13. **A2** — ícone/forma nos badges além da cor (45min)
14. **M12** — estados `:active`/`:disabled` nos botões (30min)

### Sprint 4 — Mobile e performance (~1,5 dia)
15. **A7** — tabelas → cards empilhados < 768px (3h)
16. **A9** — decidir e corrigir o carregamento da Inter (45min)
17. **M3** — remover `will-change` em massa (10min)
18. **M9** — pausar polling com `visibilitychange` (20min)
19. **M10** — grid fluido sem `!important` (20min)

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
