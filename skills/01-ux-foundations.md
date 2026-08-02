# 01 · UX Foundations

Base conceitual para qualquer decisão de fluxo, arquitetura de informação e usabilidade. Deve ser consultado antes de qualquer definição visual.

## 1. Heurísticas de Nielsen (10 princípios de usabilidade)

1. **Visibilidade do status do sistema** — o sistema sempre informa o que está acontecendo (loading states, confirmações, progresso).
2. **Correspondência entre sistema e mundo real** — linguagem, ícones e conceitos familiares ao usuário, não jargão técnico.
3. **Controle e liberdade do usuário** — "saída de emergência" clara: desfazer, cancelar, voltar.
4. **Consistência e padrões** — mesmo elemento, mesmo comportamento, em todo o produto (ver Lei de Jakob em `05-psychology.md`).
5. **Prevenção de erros** — melhor prevenir do que exibir boa mensagem de erro (confirmações, máscaras de input, desabilitar ações inválidas).
6. **Reconhecimento em vez de memorização** — opções visíveis, não exigir que o usuário lembre de informação de uma tela anterior.
7. **Flexibilidade e eficiência de uso** — atalhos para usuários avançados sem atrapalhar iniciantes.
8. **Estética e design minimalista** — cada elemento extra compete por atenção; remover o que não agrega.
9. **Ajudar o usuário a reconhecer, diagnosticar e se recuperar de erros** — mensagens em linguagem clara, sem códigos internos, com solução sugerida.
10. **Ajuda e documentação** — idealmente a interface é autoexplicativa; quando não, ajuda contextual deve ser acessível e específica à tarefa.

**Checklist rápido:** para cada tela, perguntar quais das 10 heurísticas são violadas antes de considerar pronta.

## 2. Human Centered Design (HCD)

Processo iterativo centrado nas necessidades reais do usuário, não nas suposições da equipe:

- **Inspiração** — pesquisa de campo, entrevistas, observação.
- **Ideação** — geração ampla de soluções antes de convergir.
- **Implementação** — prototipagem rápida, teste, iteração.

Princípio-chave: **nunca desenhar para o usuário hipotético "eu"**. Validar suposições com dados reais (analytics, entrevistas, testes de usabilidade) sempre que possível.

## 3. Design Thinking (fases)

1. **Empatizar** — entender profundamente o usuário e seu contexto.
2. **Definir** — sintetizar em um problem statement claro (ex.: "Como podemos ajudar X a fazer Y, apesar de Z?").
3. **Idear** — gerar muitas soluções possíveis sem julgamento prematuro.
4. **Prototipar** — materializar a ideia no menor esforço possível para testar.
5. **Testar** — validar com usuários reais e iterar.

A IA deve replicar esse raciocínio mentalmente mesmo em respostas rápidas: entender o problema antes de desenhar a solução.

## 4. Jornada do usuário (User Journey)

Mapeia a experiência completa do usuário com o produto/serviço ao longo do tempo, não apenas dentro do app:

- **Fases:** consciência → consideração → uso → retenção → advocacia.
- Para cada fase, mapear: ações do usuário, pontos de contato, emoções, pontos de dor, oportunidades.
- Útil para identificar onde a interface atual está isolada de todo o resto da experiência (ex.: e-mail de onboarding desconectado do produto).

## 5. User Flow

Representação sequencial das telas/decisões que um usuário percorre para completar uma tarefa específica.

- Sempre mapear o **caminho feliz** primeiro (happy path), depois os desvios (erros, cancelamentos, estados vazios).
- Cada decisão do fluxo deve ter no máximo 2-3 saídas claras; fluxos com muitas ramificações indicam necessidade de simplificação.
- Ferramenta de validação: contar quantos cliques/passos separam o usuário do objetivo. Menos nem sempre é melhor — o que importa é reduzir **esforço percebido**, não literalmente o número de passos (ver Lei de Hick em `05-psychology.md`).

## 6. Information Architecture (IA)

Organização e rotulagem de conteúdo para que seja encontrável e compreensível.

- **Modelos de organização:** hierárquico (categorias e subcategorias), sequencial (passo a passo), em matriz (múltiplas facetas de filtro), em rede (hipertexto livre).
- **Card sorting** — técnica para descobrir como usuários agrupam conceitos naturalmente, antes de definir menus e categorias.
- **Regra dos 3 cliques** é um mito superestimado — o que importa é que cada clique reduza a incerteza (o usuário sente que está "esquentando").
- Nomenclatura de menus deve usar a linguagem do usuário, validada por testes, não jargão interno da empresa.

## 7. Wireframing

- **Fidelidade baixa (lo-fi):** foco em estrutura e hierarquia, sem cor/tipografia definitivas — para validar fluxo rápido.
- **Fidelidade média (mid-fi):** já indica agrupamentos, espaçamento aproximado e componentes reais.
- **Fidelidade alta (hi-fi):** já é praticamente o design final, usado para testes de usabilidade mais próximos do produto real.
- Regra prática: quanto mais cedo no processo, menor a fidelidade — evita que stakeholders discutam cor de botão antes de validar se o fluxo faz sentido.

## 8. Usabilidade (definição operacional — ISO 9241-11)

Um produto é usável quando permite atingir objetivos com:

- **Eficácia** — o usuário consegue completar a tarefa.
- **Eficiência** — com esforço/tempo razoável.
- **Satisfação** — de forma agradável, sem frustração.

Métricas associadas: taxa de conclusão de tarefa, tempo na tarefa, número de erros, SUS (System Usability Scale), NPS.

## 9. Anti-padrões de UX comuns

- **Falso caminho de saída** — botão de fechar/cancelar difícil de achar ou que na verdade confirma uma ação.
- **Sobrecarga cognitiva** — muitas opções/informações simultâneas sem hierarquia (ver Miller e Cognitive Load em `05-psychology.md`).
- **Feedback ausente** — ação do usuário sem confirmação visual (o usuário clica e não sabe se funcionou).
- **Labels ambíguos** — botões como "OK" ou "Enviar" sem contexto do que realmente acontece.
- **Formulários sem validação inline** — erro só aparece depois de submeter tudo.
- **Modais empilhados** — modal sobre modal, quebrando o modelo mental do usuário.
- **Scroll infinito sem necessidade** — dificulta encontrar conteúdo específico e "perde" o rodapé/footer.
- **Ícones sem rótulo** — ambíguos sem teste prévio de reconhecimento (ex.: ícone de "coração" pode significar curtir, salvar ou favoritar).

## 10. Checklist de UX (aplicar antes de considerar uma tela pronta)

- [ ] O objetivo da tela está claro em até 5 segundos de observação?
- [ ] Existe apenas uma ação primária visualmente dominante por tela?
- [ ] Todos os estados foram desenhados: vazio, carregando, erro, sucesso, parcial?
- [ ] O fluxo tem saída de emergência (cancelar/voltar) em todos os pontos?
- [ ] Rótulos e microcopy usam a linguagem do usuário, não jargão interno?
- [ ] O fluxo foi validado contra pelo menos uma das 10 heurísticas de Nielsen?
- [ ] A arquitetura de informação foi pensada antes da estética?
- [ ] Existe redundância de informação crítica (ex.: preço) sem gerar poluição visual?
