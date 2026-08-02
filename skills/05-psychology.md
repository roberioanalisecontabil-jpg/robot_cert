# 05 · Psychology (Psicologia Aplicada ao Design)

Arquivo mais denso do conjunto. Reúne as leis e vieses cognitivos que fundamentam decisões de hierarquia, persuasão e usabilidade. Toda justificativa de design relevante deve, sempre que possível, citar um destes princípios.

Para cada item: **definição**, **quando usar**, **quando evitar**, **exemplo prático**.

## 1. Gestalt (princípios de percepção visual)

- **Proximidade** — elementos próximos são percebidos como relacionados. *Usar:* agrupar label+input. *Evitar:* espaçar uniformemente elementos de grupos diferentes (confunde a relação).
- **Similaridade** — elementos com aparência similar são percebidos como parte do mesmo grupo/função. *Usar:* mesmo estilo para todos os links de navegação. *Evitar:* usar o mesmo estilo de botão para ações primárias e destrutivas.
- **Fechamento (Closure)** — o cérebro completa formas incompletas. *Usar:* logotipos e ícones minimalistas. *Evitar:* abusar a ponto de gerar ambiguidade sobre a forma real.
- **Continuidade** — o olho segue linhas/curvas naturalmente. *Usar:* alinhar elementos em grid para guiar o olhar em Z ou F pattern.
- **Figura-fundo** — o que é o objeto de atenção vs. o que é pano de fundo. *Usar:* contraste suficiente entre CTA e fundo. *Evitar:* fundos com padrões que competem com o conteúdo.
- **Lei da Prégnância (boa forma)** — o cérebro prefere interpretar formas de maneira mais simples possível. *Aplicação:* ícones e ilustrações devem buscar a forma mais simples que ainda comunica a ideia.

## 2. Lei de Hick (Hick's Law)

Tempo de decisão aumenta logaritmicamente com o número de opções (`T = b log2(n+1)`).

- **Quando usar:** justificar redução do número de opções visíveis simultaneamente (menus, filtros, escolhas de plano).
- **Quando evitar como desculpa:** não confundir com "sempre menos opções é melhor" — usuários avançados às vezes precisam de mais opções; a solução é progressive disclosure (revelar complexidade sob demanda), não remover funcionalidade.
- **Exemplo:** reduzir um menu de 15 itens para 5 categorias com submenus reduz o tempo de decisão percebido.

## 3. Lei de Fitts (Fitts's Law)

Tempo para atingir um alvo depende da distância até ele e do tamanho do alvo (`T = a + b log2(D/W + 1)`).

- **Quando usar:** dimensionar botões de ação frequente (maiores, mais próximos do fluxo natural do cursor/dedo); posicionar ações destrutivas mais distantes de ações comuns para evitar cliques acidentais.
- **Aplicação mobile:** ações primárias na zona inferior da tela (mais fácil de alcançar com o polegar); bordas e cantos da tela são "alvos infinitos" (ex.: menu no canto).
- **Exemplo:** botão "Finalizar Compra" deve ser maior e mais fácil de clicar que "Continuar Comprando".

## 4. Lei de Miller (7 ± 2)

A memória de curto prazo comporta cerca de 5 a 9 itens simultâneos (revisões mais recentes sugerem números ainda menores, 3-4, para tarefas complexas).

- **Quando usar:** limitar itens de navegação principal (5-7 no máximo), agrupar informações em "chunks" (ex.: formatar telefone em blocos em vez de uma sequência de dígitos).
- **Quando evitar como desculpa:** não é uma regra rígida para todo tipo de lista (ex.: uma lista de resultados de busca pode ter centenas de itens, desde que não exija memorização simultânea).

## 5. Lei de Jakob (Jakob's Law)

Usuários passam a maior parte do tempo em *outros* sites/produtos — logo, preferem que o seu funcione da mesma forma que os que já conhecem.

- **Quando usar:** justificar o uso de padrões estabelecidos (ícone de carrinho para e-commerce, ícone de sino para notificações, hambúrguer para menu mobile) em vez de reinventar.
- **Quando evitar como desculpa:** não impede inovação genuína quando ela resolve um problema real — apenas exige que o padrão novo seja testado, já que tem custo de aprendizado.

## 6. Efeito Von Restorff (Isolation Effect)

Um item que se destaca visualmente do grupo é lembrado com mais facilidade.

- **Quando usar:** destacar a opção recomendada em uma tabela de preços; destacar o CTA principal com cor contrastante em relação aos secundários.
- **Quando evitar:** usar em excesso faz tudo "se destacar" e nada se destacar de fato — reservar para no máximo 1 elemento por tela/seção.

## 7. Peak-End Rule

Pessoas julgam uma experiência principalmente pelo pico (melhor ou pior momento) e pelo final, não pela média de toda a experiência.

- **Quando usar:** investir em uma tela de confirmação/sucesso memorável ao fim de um fluxo (checkout, onboarding); garantir que o momento de erro mais provável (pico negativo) seja tratado com cuidado extra (mensagem gentil, solução clara).
- **Exemplo:** uma tela de "pedido confirmado" com microanimação e clareza sobre próximos passos deixa impressão desproporcionalmente positiva sobre todo o fluxo de checkout.

## 8. Efeito Zeigarnik

Tarefas incompletas são lembradas melhor que tarefas completas — geram tensão cognitiva até serem finalizadas.

- **Quando usar:** barras de progresso de perfil ("80% completo"), onboarding em etapas visíveis, indicadores de "continuar de onde parou".
- **Quando evitar:** abusar gera ansiedade constante (notificações de "tarefas pendentes" em excesso) — usar com moderação e sempre com valor real para o usuário, não apenas para prender engajamento.

## 9. Serial Position Effect

Itens no início (efeito de primazia) e no fim (efeito de recência) de uma lista são lembrados melhor que os do meio.

- **Quando usar:** posicionar a opção/plano que se quer destacar no início ou fim de uma lista de opções, nunca no meio.
- **Aplicação:** em uma navegação horizontal, os itens mais importantes devem ficar nas extremidades, não no centro.

## 10. Lei de Doherty (Doherty Threshold)

Produtividade e engajamento aumentam quando o sistema responde a uma ação em menos de 400ms.

- **Quando usar:** justificar investimento em performance percebida (skeleton screens, optimistic UI, responses instantâneas de microinterações).
- **Aplicação:** se uma ação real demora mais de 400ms, mostrar feedback imediato (loading state) em vez de deixar a tela "congelada".

## 11. Paradoxo da Escolha (Paradox of Choice)

Excesso de opções aumenta ansiedade de decisão e reduz satisfação com a escolha feita, mesmo quando a escolha é boa.

- **Quando usar:** justificar curadoria (ex.: "recomendado para você", planos com no máximo 3-4 opções).
- **Quando evitar como desculpa:** contextos onde o usuário é especialista e quer controle total (ex.: filtros avançados de uma ferramenta profissional) se beneficiam de mais opções, desde que bem organizadas (progressive disclosure).

## 12. Carga Cognitiva (Cognitive Load)

Quantidade de "esforço mental" necessário para processar informação. Divide-se em:

- **Intrínseca** — complexidade inerente à tarefa (não pode ser eliminada, só bem gerenciada).
- **Extrínseca** — complexidade desnecessária introduzida pelo design ruim (pode e deve ser eliminada).
- **Germânica (relevante)** — esforço que efetivamente ajuda o aprendizado/compreensão (deve ser preservada).

**Aplicação:** todo esforço de simplificação de UI deve mirar reduzir a carga extrínseca, não a intrínseca (que exigiria simplificar demais a funcionalidade real).

## 13. Modelos Mentais (Mental Models)

Representação interna que o usuário tem de como algo funciona, baseada em experiências prévias.

- **Quando usar:** desenhar interfaces que correspondam ao modelo mental existente do usuário (ex.: "arrastar para o lixo" para deletar, papel de "pasta" para organização de arquivos).
- **Quando o modelo mental precisa mudar:** ao introduzir um conceito genuinamente novo, investir em onboarding explicativo, pois o custo de quebrar expectativa é alto.

## 14. Escassez (Scarcity)

Percepção de que algo limitado (tempo, quantidade) é mais valioso, aumenta urgência de decisão.

- **Quando usar eticamente:** quando a escassez é real (estoque de fato limitado, prazo real de promoção).
- **Quando é dark pattern (proibido):** contadores falsos, "só restam 2 unidades" sem lastro real. Ver `06-conversion-cro.md`, seção de dark patterns.

## 15. Prova Social (Social Proof)

Pessoas tendem a seguir o comportamento de outras em situação de incerteza.

- **Quando usar:** depoimentos reais, número de usuários/clientes, avaliações verificadas, "outros compraram junto".
- **Quando evitar:** depoimentos falsos ou não verificáveis (antiético e ilegal em diversas jurisdições).

## 16. Aversão à Perda (Loss Aversion)

Psicologicamente, perder algo dói aproximadamente 2x mais do que ganhar o equivalente é prazeroso (Kahneman & Tversky).

- **Quando usar eticamente:** comunicar o que o usuário *perde* ao não agir (ex.: "seu carrinho expira em 15 minutos" quando real), copy de renovação de assinatura mostrando benefícios que serão perdidos.
- **Quando é dark pattern:** gerar medo de perda artificial ou dificultar cancelamento para explorar esse viés (roach motel pattern).

## 17. Efeito Dotação (Endowment Effect)

Pessoas valorizam mais algo que já sentem que "possuem" (mesmo temporariamente) do que algo que ainda não têm.

- **Quando usar eticamente:** free trials que permitem uso real do produto (o usuário "sente posse" e resiste mais a abandonar), personalização (usuário investe tempo customizando, cria senso de propriedade).
- **Cuidado:** não confundir com dark pattern de dificultar o cancelamento — o efeito deve vir do valor genuíno entregue, não de fricção artificial de saída.

## 18. Tabela-resumo de aplicação rápida

| Princípio | Usar para |
|---|---|
| Gestalt | Agrupamento visual e hierarquia |
| Hick | Reduzir opções visíveis simultâneas |
| Fitts | Tamanho/posição de alvos clicáveis |
| Miller | Limitar itens de navegação/memorização |
| Jakob | Justificar uso de padrões conhecidos |
| Von Restorff | Destacar 1 elemento por vez |
| Peak-End | Investir no momento de erro e no final do fluxo |
| Zeigarnik | Progresso visível para tarefas incompletas |
| Serial Position | Posição de itens importantes em listas |
| Doherty | Feedback em <400ms |
| Paradox of Choice | Curadoria de opções |
| Cognitive Load | Reduzir esforço extrínseco, preservar o relevante |
| Mental Models | Alinhar com expectativa prévia do usuário |
| Scarcity/Social Proof/Loss Aversion/Endowment | Persuasão — sempre com lastro real, nunca dark pattern |
