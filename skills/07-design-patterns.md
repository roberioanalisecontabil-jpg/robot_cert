# 07 · Design Patterns

Biblioteca de padrões de tela/componente. Cada item segue a estrutura: **Objetivo · Quando usar · Quando evitar · Estrutura · Melhores práticas · Problemas comuns · Exemplo**.

---

## 1. Login

**Objetivo:** autenticar um usuário já cadastrado com o mínimo de fricção.

**Quando usar:** qualquer produto com conta de usuário persistente.

**Quando evitar:** ferramentas de uso único/anônimo não precisam forçar login antes de entregar valor (deixar para converter depois do "aha moment").

**Estrutura:** logo/marca → campo e-mail → campo senha (com toggle mostrar/ocultar) → "esqueci minha senha" → CTA primário "Entrar" → login social (opcional) → link para cadastro.

**Melhores práticas:**
- Autocomplete correto (`autocomplete="email"`, `"current-password"`).
- Erro genérico de segurança ("e-mail ou senha incorretos", nunca revelar qual dos dois está errado).
- Suporte a gerenciadores de senha e preenchimento automático.
- Oferecer 2FA/passkeys quando o produto lida com dados sensíveis.

**Problemas comuns:** senha sem toggle de visibilidade; erro de login sem indicar próximo passo; captcha excessivamente difícil que barra usuários legítimos.

**Exemplo:** tela centralizada, card com max-width 400px, campos empilhados, CTA de largura total.

---

## 2. Cadastro (Sign up)

**Objetivo:** converter um visitante em usuário com o menor atrito possível, sem perder dados essenciais para operação.

**Quando usar:** todo produto que exige conta.

**Quando evitar:** pedir cadastro completo antes de entregar qualquer valor (preferir cadastro progressivo).

**Estrutura:** campos essenciais primeiro (e-mail/senha ou login social) → confirmação/verificação → completar perfil depois, em contexto (progressive profiling).

**Melhores práticas:**
- Validação de força de senha em tempo real, com critérios visíveis (não só "senha fraca").
- Login social como atalho.
- Nunca pedir informação que não será usada imediatamente.
- Comunicar claramente termos de uso/privacidade sem forçar leitura completa (link visível, checkbox de aceite separado do CTA principal).

**Problemas comuns:** formulário longo demais de uma vez; falta de feedback sobre por que uma senha foi rejeitada; e-mail de confirmação que demora ou vai para spam sem aviso.

**Exemplo:** mesmo layout do login, com campo adicional de confirmação de senha ou nome.

---

## 3. Dashboard

**Objetivo:** dar visão consolidada de métricas/estado do sistema para suportar decisão rápida.

**Quando usar:** produtos analíticos, admin panels, visão geral de conta.

**Quando evitar:** quando o usuário só precisa de uma ação específica (não forçar dashboard como página inicial de tarefas simples).

**Estrutura:** header com filtros globais (período, segmento) → KPIs principais em destaque (topo) → gráficos de tendência → tabelas de detalhe → ações rápidas.

**Melhores práticas:**
- Hierarquia clara: métricas mais importantes maiores/mais acima (F-pattern/Z-pattern).
- Máximo de 5-7 KPIs simultâneos visíveis (Lei de Miller).
- Skeleton loaders durante carregamento de dados, nunca tela em branco.
- Estado vazio bem desenhado para quando não há dados ainda (ex.: conta nova).

**Problemas comuns:** poluição visual (muitos gráficos sem hierarquia); gráficos sem contexto (sem comparação com período anterior); cores de gráfico sem considerar daltonismo.

**Exemplo:** grid de cards de KPI no topo (4 colunas desktop / 2 tablet / 1 mobile), gráfico principal abaixo ocupando 2/3 da largura, painel lateral com ranking/lista.

---

## 4. ERP (Enterprise Resource Planning)

**Objetivo:** suportar operações complexas e de alto volume de dados (financeiro, estoque, produção) com precisão e eficiência para usuários especialistas.

**Quando usar:** usuários avançados que operam o sistema muitas horas por dia.

**Quando evitar:** não aplicar padrões de app consumer (excesso de whitespace, ilustrações) — usuário ERP prioriza densidade de informação e velocidade sobre estética.

**Estrutura:** navegação lateral persistente por módulo → tabelas densas com múltiplas colunas configuráveis → filtros avançados persistentes → ações em lote (bulk actions).

**Melhores práticas:**
- Priorizar atalhos de teclado e navegação sem mouse para usuários power-user.
- Densidade de informação alta é aceitável e até desejável (menos scroll, mais dados visíveis).
- Auditoria/histórico de alterações sempre visível para dados críticos (financeiro, estoque).

**Problemas comuns:** aplicar espaçamento "consumer-friendly" que reduz densidade útil; esconder funcionalidades avançadas atrás de níveis demais de navegação.

**Exemplo:** sidebar fixa com ícones+labels, tabela com colunas configuráveis, paginação server-side, barra de ações em lote fixa ao selecionar linhas.

---

## 5. CRM (Customer Relationship Management)

**Objetivo:** gerenciar relacionamento e histórico de interação com clientes/leads.

**Quando usar:** times de vendas, sucesso do cliente, suporte.

**Estrutura:** lista/pipeline de contatos (kanban ou tabela) → perfil detalhado do contato (timeline de interações) → ações rápidas (ligar, e-mail, agendar).

**Melhores práticas:**
- Visão de pipeline (kanban) para vendas, visão de lista/tabela para gestão operacional — oferecer ambas quando possível.
- Timeline de interações unificada (e-mails, calls, notas) em ordem cronológica clara.
- Busca e filtro rápidos, já que o volume de contatos cresce continuamente.

**Problemas comuns:** perfil de contato sobrecarregado sem hierarquia; falta de indicação clara do próximo passo/ação recomendada.

**Exemplo:** kanban de pipeline com colunas por estágio, cards de contato com avatar+nome+valor, painel lateral de detalhe ao clicar num card.

---

## 6. Agenda / Calendário

**Objetivo:** visualizar e gerenciar compromissos ao longo do tempo.

**Quando usar:** agendamento de reuniões, gestão de tarefas com prazo, escalas.

**Estrutura:** seletor de visão (dia/semana/mês/lista) → grade temporal → eventos como blocos coloridos → detalhe do evento ao clicar.

**Melhores práticas:**
- Visão padrão deve refletir o uso mais comum (semana para agendas de trabalho, mês para planejamento).
- Cores de eventos com significado consistente (por categoria/calendário), nunca aleatórias.
- Drag-and-drop para reagendar, com confirmação para mudanças que afetam terceiros (convidados).
- Sempre indicar fuso horário quando há participantes remotos.

**Problemas comuns:** eventos sobrepostos ilegíveis em telas pequenas; falta de indicação clara de conflito de horário; grade densa demais em mobile sem visão alternativa em lista.

**Exemplo:** visão semana em grid de 7 colunas x 24 linhas (horas), com bloco de evento colorido; em mobile, colapsar para visão de lista por dia.

---

## 7. Tabelas

**Objetivo:** apresentar dados estruturados para leitura, comparação e ação em lote.

**Quando usar:** qualquer conjunto de dados tabular com mais de ~5 linhas e necessidade de comparação entre registros.

**Quando evitar:** listas simples sem necessidade de comparação de múltiplos atributos (usar cards/lista simples).

**Estrutura:** header fixo (sticky) com labels de coluna → linhas com zebra striping opcional → ações por linha (à direita) → paginação ou scroll virtual → estado vazio e de carregamento.

**Melhores práticas:**
- Alinhamento: texto à esquerda, números à direita, para facilitar comparação vertical de valores.
- Ordenação por coluna com indicador visual claro da direção ativa.
- Colunas configuráveis/ocultáveis quando o dataset tem muitos atributos.
- Ações em lote via checkbox na primeira coluna, com barra de ações contextual ao selecionar.
- Responsivo: em mobile, transformar em cards empilhados com labels inline em vez de scroll horizontal forçado.

**Problemas comuns:** tabela sem estado vazio desenhado; excesso de colunas sem priorização; falta de feedback ao ordenar/filtrar (parece que não fez nada).

**Exemplo:** tabela com checkbox + avatar+nome + 3-4 colunas de dado + coluna de ações (ícone de menu "...") à direita.

---

## 8. Kanban

**Objetivo:** visualizar fluxo de trabalho por estágio, facilitando gestão visual de progresso.

**Quando usar:** gestão de tarefas/pipeline com estágios discretos (a fazer/fazendo/feito; pipeline de vendas).

**Quando evitar:** quando a quantidade de itens é muito alta (>50 por coluna) — nesse caso tabela com filtro por status é mais eficiente.

**Estrutura:** colunas por estágio (header com contagem) → cards arrastáveis → detalhe do card em painel lateral ou modal.

**Melhores práticas:**
- Limitar WIP (work in progress) visualmente quando relevante (ex.: alerta se uma coluna excede um limite definido).
- Card deve mostrar apenas informação essencial (título, responsável, prazo, tag) — detalhe completo só ao abrir.
- Drag-and-drop com feedback visual claro de onde o item vai ser solto.

**Problemas comuns:** colunas com scroll horizontal mal sinalizado; cards sobrecarregados de informação; falta de indicação de overdue/atrasado.

**Exemplo:** 3-5 colunas visíveis, cards com barra de cor lateral indicando prioridade/categoria.

---

## 9. Cards

**Objetivo:** agrupar informação relacionada em um container visualmente distinto e escaneável.

**Quando usar:** listagens de itens com atributos mistos (imagem+título+metadados), grids de produtos/conteúdo.

**Estrutura:** container com sombra/borda sutil → mídia (opcional, topo) → título → metadados/descrição → ação (rodapé).

**Melhores práticas:**
- Manter altura consistente entre cards da mesma listagem (grid alinhado) — usar `line-clamp` para truncar textos de tamanho variável.
- Área de clique do card inteiro deve ser óbvia (cursor pointer, hover state) quando o card inteiro é clicável.
- Evitar mais de uma ação primária por card.

**Problemas comuns:** cards com alturas desiguais quebrando o grid; múltiplos elementos clicáveis sobrepostos dentro do mesmo card gerando ambiguidade de clique.

---

## 10. Timeline

**Objetivo:** apresentar eventos/atividades em ordem cronológica.

**Quando usar:** histórico de atividades, status de pedido/entrega, changelog.

**Estrutura:** linha vertical (ou horizontal) conectando marcadores de evento → cada marcador com data/hora, ícone/status, descrição.

**Melhores práticas:**
- Diferenciar visualmente eventos passados (completos), atual (em destaque) e futuros (esmaecidos).
- Ordem cronológica clara (mais recente no topo é convenção comum em feeds; mais recente embaixo é convenção comum em progresso sequencial tipo "status do pedido").

**Problemas comuns:** ambiguidade sobre a direção do tempo; eventos sem timestamp claro.

---

## 11. Chat

**Objetivo:** suportar comunicação em tempo real ou assíncrona entre usuários (ou usuário e IA).

**Estrutura:** lista de conversas (sidebar) → área de mensagens (bolhas alinhadas por remetente) → input de mensagem fixo no rodapé.

**Melhores práticas:**
- Mensagens do próprio usuário alinhadas à direita, do interlocutor à esquerda (convenção universal).
- Indicador de "digitando..." e status de entrega/leitura quando relevante.
- Scroll automático para a última mensagem, mas permitir que o usuário suba sem ser puxado de volta para baixo a cada nova mensagem.
- Input sempre acessível (fixo), nunca exigir scroll para encontrá-lo.

**Problemas comuns:** falta de indicação de mensagem não lida; scroll automático que atrapalha leitura de histórico; timestamps ausentes.

---

## 12. Sidebar

**Objetivo:** navegação persistente entre seções principais do produto.

**Estrutura:** logo/marca (topo) → itens de navegação principal → separador → itens secundários/configurações → perfil do usuário (rodapé).

**Melhores práticas:**
- Item ativo com destaque visual claro (cor de fundo, borda lateral ou ambos — nunca só mudança sutil de cor de texto).
- Colapsável (ícones apenas) para telas menores/preferência do usuário, mantendo `aria-label` nos ícones quando colapsado.
- Em mobile, converter para menu off-canvas (drawer) ou bottom navigation, nunca manter sidebar fixa ocupando espaço da tela pequena.

**Problemas comuns:** hierarquia de navegação profunda demais (mais de 2 níveis exige repensar a IA); item ativo pouco perceptível.

---

## 13. Wizard (fluxo em etapas)

**Objetivo:** guiar o usuário por uma tarefa complexa dividida em passos gerenciáveis.

**Quando usar:** onboarding, configuração inicial, checkout multi-etapa.

**Estrutura:** indicador de progresso (steps) → conteúdo do passo atual → navegação anterior/próximo → resumo final antes de confirmar.

**Melhores práticas:**
- Permitir voltar sem perder dados já preenchidos.
- Validar cada etapa antes de avançar (não empilhar erros para o final).
- Indicar quantos passos faltam (reduz ansiedade — Doherty/Zeigarnik).

**Problemas comuns:** wizard sem opção de voltar; perda de dados ao navegar entre etapas; etapa final sem resumo do que foi preenchido.

---

## 14. Modal

**Objetivo:** capturar atenção total do usuário para uma decisão ou informação específica, sem navegar para outra tela.

**Quando usar:** confirmações críticas, formulários curtos e contextuais, exibição de detalhe rápido.

**Quando evitar:** conteúdo longo/complexo (preferir página dedicada); múltiplos modais empilhados.

**Estrutura:** overlay (dimming do fundo) → container centralizado → header com título+fechar → corpo → rodapé com ações (cancelar + confirmar).

**Melhores práticas:**
- Focus trap obrigatório (ver `04-accessibility.md`) + fechamento via `Esc` e clique no overlay.
- Ação destrutiva nunca deve ser a opção com maior destaque visual por padrão (evitar clique acidental em "excluir").
- Devolver foco ao elemento que abriu o modal ao fechar.

**Problemas comuns:** modal sem `aria-modal`/focus trap; modal de confirmação com botão "confirmar" mais destacado que "cancelar" em ações destrutivas; modais aninhados.

---

## 15. Toast / Snackbar

**Objetivo:** feedback breve e não bloqueante sobre o resultado de uma ação.

**Quando usar:** confirmação de ação bem-sucedida (salvo, copiado, enviado).

**Quando evitar:** informação crítica que exige ação do usuário (usar modal/alerta persistente em vez disso).

**Estrutura:** posição consistente (geralmente canto superior/inferior direito ou centro-inferior em mobile) → ícone de status → mensagem curta → ação opcional (ex.: "Desfazer") → auto-dismiss.

**Melhores práticas:**
- Duração de exibição proporcional ao tamanho da mensagem (mínimo ~4s), nunca tão rápido que o usuário não consiga ler.
- `aria-live="polite"` para leitores de tela.
- Empilhar no máximo 2-3 toasts simultâneos, substituindo os mais antigos.

**Problemas comuns:** toast que desaparece rápido demais; posição inconsistente entre telas; toast bloqueando elemento interativo importante.

---

## 16. Alertas / Banners

**Objetivo:** comunicar informação de status/sistema persistente até que seja resolvida ou dispensada.

**Estrutura:** ícone semântico (info/sucesso/atenção/erro) → mensagem → ação opcional → botão de dispensar (quando aplicável).

**Melhores práticas:**
- Cor + ícone + texto (nunca só cor) para diferenciar severidade (ver acessibilidade e daltonismo).
- Alertas de erro crítico do sistema não devem ser dispensáveis sem que o problema seja resolvido.
- Posição no topo da página/seção relevante, não escondido onde o usuário não vai olhar.

**Problemas comuns:** banners que empurram todo o layout de forma abrupta (usar transição suave); múltiplos banners acumulados sem hierarquia de severidade.

---

## Checklist geral de Design Patterns

- [ ] O padrão escolhido é o que o usuário já espera para este tipo de tarefa (Lei de Jakob)?
- [ ] Todos os estados (vazio, carregando, erro, sucesso) foram desenhados para o componente?
- [ ] O componente foi validado contra a versão responsiva (mobile) descrita em `03-responsive-design.md`?
- [ ] O componente segue os tokens do design system (`02-design-system.md`)?
- [ ] Acessibilidade do padrão (foco, ARIA, contraste) foi verificada?
