# 04 · Accessibility

Baseado em WCAG 2.2. Não é uma etapa opcional ou posterior — deve ser considerada em paralelo a qualquer decisão visual ou de fluxo (ver `00-core.md`, princípios globais).

## 1. Os 4 princípios do WCAG (POUR)

1. **Perceptível** — a informação deve ser apresentável de formas que o usuário consiga perceber (texto alternativo, contraste, legendas).
2. **Operável** — a interface deve ser utilizável via teclado, sem depender apenas de mouse/toque.
3. **Compreensível** — conteúdo e operação da interface devem ser claros e previsíveis.
4. **Robusto** — o conteúdo deve funcionar de forma confiável com tecnologias assistivas variadas (leitores de tela, switches, etc.).

## 2. Contraste

| Elemento | Nível AA (mínimo) | Nível AAA (ideal) |
|---|---|---|
| Texto normal (< 18px ou < 14px bold) | 4.5:1 | 7:1 |
| Texto grande (≥ 18px ou ≥ 14px bold) | 3:1 | 4.5:1 |
| Componentes de UI e ícones informativos | 3:1 | — |
| Elementos puramente decorativos | sem exigência | — |

- Nunca confiar apenas em preview visual — validar com ferramenta de contraste (ex.: WebAIM Contrast Checker, ou cálculo programático de luminância relativa).
- Modo escuro exige recalcular contraste — não basta inverter as cores do modo claro.

## 3. Leitores de tela

- Usar HTML semântico como base (`<button>`, `<nav>`, `<main>`, `<header>`, `<label>`) — leitores de tela dependem da estrutura, não da aparência.
- `alt` descritivo em imagens informativas; `alt=""` (vazio, não ausente) em imagens puramente decorativas.
- Ícones sem texto visível precisam de `aria-label` ou `aria-labelledby` descrevendo a ação, não a aparência (ex.: `aria-label="Fechar modal"`, não `aria-label="X"`).
- Mudanças dinâmicas de conteúdo (toasts, validação inline, contadores) precisam de `aria-live="polite"` (ou `"assertive"` para erros críticos) para serem anunciadas sem que o foco mude.

## 4. Navegação por teclado

- Toda ação possível via mouse deve ser possível via teclado (Tab, Shift+Tab, Enter, Espaço, Setas, Esc).
- Ordem de tabulação (`tab order`) deve seguir a ordem visual/lógica da tela — evitar `tabindex` positivo manual (quebra a ordem natural); usar `tabindex="0"` para tornar elementos não nativos focáveis e `tabindex="-1"` para remover de fluxo sem esconder.
- **Focus trap** obrigatório em modais (o foco não pode "escapar" para o conteúdo atrás) e deve devolver o foco ao elemento que abriu o modal ao fechar.
- Menus/dropdowns devem ser navegáveis com setas e fechar com `Esc`.
- Nunca desabilitar o scroll/zoom da página (`user-scalable=no`) — prejudica usuários com baixa visão.

## 5. Focus (foco visível)

- Nunca usar `outline: none` sem um substituto visualmente equivalente ou superior (anel de foco customizado com contraste ≥ 3:1 contra o fundo).
- O indicador de foco deve ser visível tanto em modo claro quanto escuro.
- Usar `:focus-visible` em vez de `:focus` puro quando se quer mostrar o anel apenas para navegação via teclado (evita "flash" de foco em cliques de mouse), mas nunca remover completamente para nenhum modo de interação.

## 6. ARIA (Accessible Rich Internet Applications)

- **Regra de ouro:** "No ARIA is better than bad ARIA" — usar HTML semântico nativo sempre que possível antes de recorrer a atributos ARIA.
- Roles comuns: `role="dialog"` + `aria-modal="true"` para modais, `role="alert"` para mensagens críticas, `role="status"` para atualizações não críticas.
- `aria-expanded` em elementos que abrem/fecham (accordions, dropdowns), `aria-current="page"` em navegação para indicar item ativo.
- Nunca sobrescrever a semântica nativa desnecessariamente (ex.: `<div role="button">` quando `<button>` resolveria com muito menos esforço e mais robustez).

## 7. Formulários

- Todo input precisa de `<label>` associado (via `for`/`id`, nunca apenas `placeholder` como substituto de label — placeholder some ao digitar e tem contraste geralmente insuficiente).
- Campos obrigatórios marcados visual e semanticamente (`aria-required="true"` ou atributo `required`), não apenas por asterisco isolado sem legenda explicando o símbolo.
- Agrupar campos relacionados com `<fieldset>` + `<legend>` (ex.: endereço, período de datas).
- Autocomplete apropriado (`autocomplete="email"`, `"tel"`, `"cc-number"`, etc.) para preenchimento assistido e acessibilidade cognitiva.

## 8. Tratamento de erros

- Erro identificado em texto, não apenas cor (ícone + mensagem + borda).
- Mensagem de erro específica e acionável ("O CPF informado tem 10 dígitos, o correto são 11" em vez de "CPF inválido").
- Erros de formulário devem mover o foco (ou ao menos ser anunciados via `aria-live`) para o primeiro campo com problema ao tentar submeter.
- Nunca limpar os dados já preenchidos corretamente ao exibir um erro em outro campo.

## 9. Daltonismo e percepção de cor

- ~8% dos homens e ~0.5% das mulheres têm alguma forma de daltonismo (deuteranopia é a mais comum).
- Nunca usar cor como único diferenciador de significado (gráficos, status, validação) — combinar sempre com forma, ícone, padrão (hachurado/pontilhado) ou texto.
- Testar paletas em simuladores de daltonismo (deuteranopia, protanopia, tritanopia) antes de finalizar, especialmente em dashboards com gráficos.

## 10. Boas práticas adicionais

- Vídeos precisam de legendas (captions) e, idealmente, transcrição.
- Animações com mais de 3 flashes por segundo são proibidas (risco de convulsão fotossensível — critério WCAG 2.3.1).
- Respeitar `prefers-reduced-motion` para usuários sensíveis a movimento/vestibular.
- Textos devem suportar zoom de até 200% sem quebra de layout ou perda de conteúdo/funcionalidade (critério de "reflow").
- Alvos de toque com no mínimo 24x24px (WCAG 2.2, critério 2.5.8), recomendável 44x44px.

## 11. Checklist de Acessibilidade (WCAG 2.2 AA — mínimo aceitável)

- [ ] Contraste de texto e componentes de UI validado (4.5:1 / 3:1)?
- [ ] Toda a interface operável apenas com teclado, com foco sempre visível?
- [ ] HTML semântico usado antes de recorrer a ARIA?
- [ ] Imagens com `alt` apropriado (descritivo ou vazio se decorativo)?
- [ ] Formulários com labels reais, agrupamento lógico e mensagens de erro acionáveis?
- [ ] Nenhuma informação transmitida só por cor?
- [ ] Animações respeitam `prefers-reduced-motion` e não geram flashes perigosos?
- [ ] Interface testada com zoom de 200% sem quebra de layout?
