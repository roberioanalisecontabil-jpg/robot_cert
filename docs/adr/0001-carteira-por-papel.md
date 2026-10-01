---
status: accepted
date: 2026-10-01
---

# Carteira por Papel: Atribuições para o Operador, Exceções para o Gestor, e Gestor derivado da liderança

O alcance sobre certificados mudou três vezes em dois dias (29 e 30/09/2026): primeiro o
Gestor via tudo, depois uma flag `users.acesso_restrito` o limitava, depois a carteira dele
era preenchida com todo o inventário no momento da promoção (origem `regra:gestor`) e o
Administrador retirava à mão. Nenhuma versão respondia bem a "o Gestor vê todos os
certificados, mas o Administrador pode limitar" quando um cliente novo entra no inventário.

Decidimos que a Carteira tem comportamento diferente por Papel. A do **Operador** é uma lista
positiva de **Atribuições**: nasce vazia e só alcança o que o Gestor do seu Departamento ou o
Administrador atribuiu. A do **Gestor** é uma lista negativa de **Exceções**: alcança todo o
Inventário, inclusive o que entrar depois, menos os Documentos que o Administrador retirou.
Decidimos também que o Papel **Gestor deriva da liderança de Departamento**: nomear alguém
Gestor de um Departamento o torna Gestor; perder a última liderança o rebaixa a Operador. Só o
Papel Administrador é escolhido à mão, e um Administrador pode liderar um Departamento sem
perder o alcance total.

## Opções consideradas

- **Flag `acesso_restrito` no usuário** (manhã de 30/09): binária, não dizia *o que* estava
  restrito; o Administrador precisaria montar a carteira do Gestor do zero. Descartada e a
  coluna removida (`20260930130000_users_acesso_restrito_drop.sql`).
- **Foto na promoção** (tarde de 30/09, origem `regra:gestor`): cliente novo não chegava a
  nenhum Gestor até alguém rodar a reaplicação manual, e a reaplicação devolvia tudo que o
  Administrador tinha retirado. Contradizia "o Gestor vê todos".
- **Gestor e Líder independentes** (modelo de 18/08): qualquer pessoa ativa podia liderar um
  Departamento, inclusive um Operador, que então editava a carteira dos colegas; e um Gestor
  podia não liderar nada. A regra de negócio falada é "o gestor do setor", um conceito só.
- **Validar coerência em vez de derivar** (dois campos, Papel e liderança, com validação
  cruzada): descartada porque permite estados inconsistentes que só são barrados no salvar;
  derivar elimina o estado em vez de proibi-lo.

## Consequências

- Atribuições e Exceções são por **Documento** (CNPJ/CPF), nunca por certificado: a renovação
  do mesmo CNPJ herda o alcance sozinha.
- O Gestor só atribui Documentos que estão no **próprio Alcance**. Uma Exceção registrada
  para o Gestor também o impede de dar aquele Documento a seus Operadores; só o Administrador
  o faz.
- Ver e instalar continuam **um direito só**; a mesma função de alcance serve às duas
  barreiras.
- **Departamento é obrigatório** no cadastro de Usuário; o Gestor é definido na tela de
  Departamento, não no cadastro do Usuário. O campo Papel deixa de ser editável para
  Gestor/Operador.
- A Carteira **nunca guarda estado dormente**: mudar de Papel ou Desativar a esvazia. Um
  Operador promovido perde as Atribuições; um Gestor rebaixado fica com a carteira vazia e o
  Gestor do seu Departamento (ou o Administrador) refaz.
- Departamento sem Gestor é aceitável: suas carteiras são cuidadas só pelo Administrador, com
  sinalização na tela.
- Somem a origem `regra:gestor`, a rota de reaplicação manual e a soma das carteiras dos
  membros no alcance do Gestor (ele já alcança tudo).
- **Transição** dos dados em produção, aplicada uma vez pela regra: todo líder atual vira
  Gestor; todo Gestor sem liderança vira Operador com carteira vazia; as linhas `regra:gestor`
  são apagadas. Usuário sem Departamento não trava o login: fica sem Gestor, com aviso ao
  Administrador, até ser enquadrado.
- Docstrings e comentários em `cert_installer.py` e `main.py` que ainda descrevem "admin e
  gestor têm alcance total" ou "gestores limitados" devem ser atualizados junto com o código.

Vocabulário em [GLOSSARY.md](../../GLOSSARY.md).
