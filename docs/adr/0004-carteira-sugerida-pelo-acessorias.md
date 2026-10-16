---
status: accepted
date: 2026-10-16
---

# Carteira sugerida pelo Acessórias, aprovada por quem já edita a carteira

Montar a carteira de cada Operador é trabalho manual (tela ou planilha), e a informação já
existe no Acessórias: lá cada empresa tem, por departamento, um responsável do escritório
(nome e e-mail). O DIARIO2.0 já fala com a API do Acessórias, mas só traz a lista de empresas,
sem responsáveis.

Decidimos que o portal **consulta a API do Acessórias por conta própria**, guarda uma cópia
dos responsáveis por empresa e, a partir dela, **sugere** Atribuições. **Nada muda sozinho**:
quem já pode editar a carteira (ADR 0001) aprova ou recusa. Pela ADR 0001 a carteira decide
quem instala o certificado (adendo de 08/10), então uma troca no Acessórias não pode dar ou
tirar acesso a certificado sem alguém olhar.

## Regras

- **Só leitura.** O portal nunca escreve no Acessórias.
- **Busca:** automática toda noite às 02:00 e pelo botão **Buscar agora**.
  - `GET /companies/ListAll?departments&Pagina=N` já traz os departamentos e os responsáveis.
    Em 16/10/2026 foram 30 páginas, 594 empresas (587 ativas), todas com CNPJ.
  - A busca é sempre completa. A data de alteração (`DtLastDH`) não é confiável para troca de
    responsável feita na tela do Acessórias, e a busca inteira custa umas 30 chamadas.
- **Token:** o mesmo do DIARIO2.0, só no `.env` do servidor (`ACESSORIAS_API_TOKEN`). O
  limite de 100 requisições por minuto é compartilhado; os horários não se cruzam (DIARIO2.0
  das 07:30 às 12:00, portal às 02:00 e no botão).
- **Cópia local:** CNPJ, razão social, se está ativa, departamento, nome e e-mail do
  responsável. Honorário e contatos do cliente não entram. As telas leem a cópia; a API só é
  chamada na busca.
- **Pessoa:** o responsável é ligado à conta do portal pelo **e-mail** (sem distinguir
  maiúsculas). Só **Operadores ativos** recebem Atribuições. Quem não tem conta, é Gestor,
  Administrador ou está desativado vai para a lista "responsáveis sem conta de Operador".
- **Departamentos que dão carteira:** lista configurável na tela. Começa com **Contábil**,
  **Fiscal** e **Pessoal** (em 16/10: 30, 24 e 17 pessoas diferentes). Desmarcar um
  departamento gera sugestões de remoção do que veio dele.
- **Documento:** CNPJ exato. Se o CNPJ não tem certificado no inventário, vale o da **matriz**
  (mesma raiz de 8 dígitos, `/0001`). Sem certificado nenhum, nada é sugerido; a próxima busca
  tenta de novo. CAEPF fica de fora.
- **Empresa inativa ou removida** no Acessórias gera sugestão de remoção.
- **Só o que veio do Acessórias é sugerido para remoção.** Atribuições feitas à mão ou por
  planilha ficam e aparecem marcadas como "manual".

## Aprovação

- Sugestões são a diferença entre o Acessórias e a carteira: "+" dá, "−" tira.
- Aprovam o **Administrador** (todas) e o **Gestor** (Operadores dos Departamentos que lidera),
  como na edição manual. Aprovar tudo, por Operador ou item a item.
- **Recusa** fica guardada, e a sugestão não volta enquanto o Acessórias não mudar aquele par
  (Operador, documento). Um filtro "recusadas" permite desfazer.
- Atribuição aprovada grava a origem **Acessórias**, e o autor "Acessórias (sincronização)" com
  o nome de quem aprovou.
- Passa a existir **histórico de entradas e saídas da carteira** para qualquer origem (manual,
  planilha, Acessórias, troca de papel), inclusive remoções, que hoje apagam a linha sem rastro.
- Sem aviso ao Operador na primeira versão.

## Tela

Aba **Acessórias** na página Carteiras: data da última busca e Buscar agora; sugestões por
Operador ("+12 / −2", Aprovar, Ver com ✓/✗ por item, Aprovar todas); responsáveis sem conta de
Operador; departamentos que contam. O Gestor vê só os Operadores dos seus Departamentos.

## Opções consideradas

- **Acessórias manda** (copiar sem aprovação): mudança no Acessórias daria ou tiraria acesso a
  certificado sem ninguém olhar. Descartada; pode voltar depois só para as entradas.
- **Só acrescentar**: a carteira cresceria para sempre, e quem saiu de uma empresa continuaria
  instalando o certificado dela.
- **Ler o banco do DIARIO2.0**: uma integração só, mas o DIARIO2.0 não traz responsáveis e o
  portal passaria a depender de outro sistema estar de pé. Decidido que o portal fala com a API.
- **Pré-atribuição** para empresa sem certificado: tabela a mais para ganhar no máximo um dia;
  a busca diária resolve.
- **Escrever no Acessórias** quando o admin muda a carteira: o Acessórias é o sistema do dia a
  dia do escritório; o portal não mexe nele.

## Consequências

- O DIARIO2.0 não muda.
- Clientes pessoa física (e-CPF de sócios) não vêm do Acessórias: em 16/10 todos os 594
  documentos eram CNPJ. Continuam pela carteira manual.
- Responsáveis com e-mail de outro domínio (analisecontabil.cnt.br, gmail) só casam se a conta
  do portal usar o mesmo e-mail; senão aparecem na lista "sem conta de Operador".
- Ordem de entrega: este ADR → migration (cópia, origem, histórico, recusas, departamentos) →
  busca noturna e Buscar agora → aba Acessórias.
