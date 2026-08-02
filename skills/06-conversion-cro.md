# 06 · Conversion & CRO (Conversion Rate Optimization)

Diretrizes para desenhar interfaces com objetivo explícito de conversão (cadastro, compra, lead, upgrade), sempre dentro dos limites éticos definidos em `00-core.md`.

## 1. CTAs (Call to Action)

- **Um CTA primário por tela/seção** — múltiplos CTAs de mesmo peso visual competem entre si e reduzem a taxa de conversão de ambos.
- Texto do botão deve descrever o **resultado**, não a ação genérica: "Começar teste grátis" em vez de "Enviar"; "Ver meu orçamento" em vez de "Continuar".
- Contraste de cor do CTA principal deve ser o mais alto da tela (ver Von Restorff, `05-psychology.md`).
- Tamanho e posição seguem Lei de Fitts — CTA principal maior e na área de fácil alcance (mobile: terço inferior da tela).
- CTAs secundários (ex.: "Voltar", "Talvez depois") devem ter peso visual claramente menor — nunca o mesmo botão style que o primário.

## 2. Landing Pages

Estrutura recomendada (não é regra rígida, mas ponto de partida validado):

1. **Hero** — proposta de valor clara em até 8 palavras + subheadline explicando o "como" + CTA primário visível sem scroll.
2. **Prova social** — logos de clientes, número de usuários, avaliações.
3. **Benefícios (não apenas features)** — traduzir cada funcionalidade em resultado para o usuário.
4. **Como funciona** — 3-4 passos simples, reduz incerteza (Doherty/Cognitive Load).
5. **Objeções/FAQ** — antecipar e responder as dúvidas que impedem a conversão.
6. **CTA final** — repetir a oferta ao fim da página para quem leu tudo antes de decidir.

## 3. Funis

- Mapear cada etapa do funil (awareness → interest → decision → action) e medir taxa de abandono específica de cada etapa, não só a conversão total.
- Cada etapa do funil deve pedir o mínimo de informação necessária para avançar — pedir tudo de uma vez aumenta abandono (ver progressive disclosure em `01-ux-foundations.md`).
- Sempre desenhar o que acontece no abandono (ex.: e-mail de carrinho abandonado, retomada de formulário salvo) como parte do funil, não como afterthought.

## 4. Hero Sections

- Proposta de valor específica ao público-alvo, não genérica ("A melhor solução do mercado" não diz nada).
- Imagem/vídeo de apoio deve reforçar a proposta, não ser apenas decorativo (ex.: mostrar o produto em uso real).
- Evitar mais de 1 CTA de mesmo peso no hero — CTA primário claro, secundário (se houver) discreto (ex.: link de texto "ou veja uma demo").

## 5. Formulários (foco em conversão)

- Cada campo removido aumenta a taxa de conclusão — questionar a real necessidade de cada campo (nome completo vs. só primeiro nome; telefone só se de fato usado).
- Autofill/autocomplete habilitado sempre que possível.
- Validação inline (campo a campo) em vez de erros só ao submeter tudo.
- Multi-step forms para formulários longos, com indicador de progresso (Zeigarnik) — cada etapa deve parecer curta e gerenciável.
- Botão de submit deve indicar claramente o que acontece a seguir ("Criar minha conta" em vez de "Enviar").

## 6. Gatilhos mentais (uso ético)

Aplicação prática dos princípios de `05-psychology.md` em contexto de conversão:

- **Urgência real** — prazo de promoção genuíno, com data/hora clara.
- **Escassez real** — estoque/vagas reais, nunca contadores fictícios.
- **Autoridade** — certificações, prêmios, especialistas reais associados ao produto.
- **Reciprocidade** — oferecer valor genuíno antes de pedir algo (conteúdo gratuito, teste sem cartão de crédito).
- **Compromisso e consistência** — pequenos "sins" incrementais (ex.: começar um quiz/calculadora) aumentam a chance de completar a ação maior — desde que o valor entregue seja real em cada etapa.

## 7. Provas sociais

Hierarquia de força persuasiva (da mais fraca à mais forte):

1. Número genérico ("+10.000 clientes").
2. Selo/badge de terceiros (avaliação verificada, certificação).
3. Depoimento em texto com nome e foto/empresa reais.
4. Case de sucesso com números específicos e verificáveis.
5. Vídeo depoimento de cliente real.

Sempre priorizar prova social específica ao contexto da página (ex.: depoimento de cliente do mesmo segmento do visitante) sobre prova social genérica.

## 8. Redução de atrito

- Cada clique/campo/decisão extra é uma oportunidade de abandono — mapear e eliminar passos que não agregam valor real à decisão do usuário.
- Oferecer login social (Google/Apple) além de e-mail/senha reduz fricção de cadastro.
- Mostrar preço total (sem taxas escondidas reveladas só no final) — fricção por surpresa negativa é uma das maiores causas de abandono de carrinho.
- Checkout como convidado (guest checkout) sempre disponível como opção, sem forçar criação de conta antes da compra.

## 9. Microcopy

- Cada texto de interface é uma oportunidade de reduzir ansiedade ou reforçar confiança: "Você pode cancelar quando quiser" perto de um CTA de assinatura reduz a percepção de risco.
- Mensagens de erro devem ser específicas e não-culpabilizantes ("Não conseguimos processar o pagamento, verifique os dados do cartão" em vez de "Erro").
- Tom de voz consistente com a marca, mas sempre priorizando clareza sobre criatividade em pontos críticos de conversão (checkout, pagamento).

## 10. Onboarding

- Objetivo do onboarding é levar o usuário ao **"aha moment"** (o momento em que ele percebe o valor real do produto) o mais rápido possível — não é ensinar todas as features.
- Progressive disclosure: mostrar funcionalidades avançadas apenas quando relevantes ao contexto de uso, não tudo de uma vez na primeira sessão.
- Checklist de progresso (Zeigarnik) aumenta a taxa de conclusão do onboarding.
- Permitir pular etapas não essenciais — forçar onboarding completo sem saída é fricção desnecessária.

## 11. Dark Patterns — proibidos nesta skill

A IA nunca deve propor, mesmo que solicitado, os seguintes padrões. Se o usuário pedir explicitamente, a IA deve explicar o risco (ético, legal, reputacional) e oferecer alternativa que atinja o objetivo de negócio de forma legítima.

| Dark pattern | Descrição | Alternativa ética |
|---|---|---|
| Roach motel | Fácil entrar, difícil sair (cancelamento escondido) | Cancelamento tão simples quanto a assinatura |
| Confirmshaming | Culpar o usuário na opção de recusa ("Não, prefiro pagar mais depois") | Linguagem neutra em ambas as opções |
| Contador falso | Urgência/escassez fabricada | Usar apenas dados reais |
| Opt-out escondido | Pré-marcar caixas de assinatura de newsletter/upsell | Opt-in explícito e visível |
| Drip pricing | Revelar taxas só no fim do checkout | Preço total visível desde o início |
| Bait and switch | Anunciar uma coisa, entregar outra | Transparência total na oferta |
| Nagging | Interromper repetidamente com o mesmo pedido já recusado | Respeitar a recusa, perguntar de novo só após intervalo razoável |

## 12. Checklist de CRO

- [ ] Existe apenas um CTA primário por tela/seção?
- [ ] O texto do CTA descreve o resultado, não uma ação genérica?
- [ ] Todo gatilho de urgência/escassez usado tem lastro real?
- [ ] O formulário pede apenas os campos estritamente necessários?
- [ ] O preço/custo total é visível antes da etapa final de confirmação?
- [ ] Nenhum dos 7 dark patterns da seção 11 está presente?
