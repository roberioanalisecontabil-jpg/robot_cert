# Revisão página a página — outubro de 2026

Revisão de lógica e funcionamento do portal, uma página por vez, antes da
entrada em produção do modelo de acesso do [ADR 0001](adr/0001-carteira-por-papel.md).
Vocabulário: [GLOSSARY.md](../GLOSSARY.md).

**Régua** (a mesma para toda página): para que a página existe; quem vê e quem
edita, por papel, e isso bate com a matriz de permissões; cada ação da tela
(o que valida, o que grava, o que mostra depois); os quatro estados (vazio,
carregando, erro, sem permissão) com texto que diz a consequência; vocabulário
conforme o glossário.

**Método**: um levantamento factual do código por página, depois decisões do
usuário sobre o que estava indefinido ou contraditório. Defeitos claros são
corrigidos na hora; decisões ficam registradas aqui e, quando mudam o modelo,
no glossário ou num ADR.

**Ordem**: Usuários → Carteiras → Início → Instalador → Acompanhamento →
Dashboard, Histórico, Vencidos, Duplicidades → Configuração, Login.

A granularidade de permissões (por usuário; "apagar" separado de "editar"),
pendência antiga do `PLANO_niveis_de_acesso.md`, entra nesta revisão por
decisão de 01/10/2026, na aba Níveis de acesso.

---

## 1. Usuários (01/10/2026)

**Para que existe**: cadastrar e administrar quem entra no portal — contas,
departamentos (e seus gestores) e níveis de acesso por papel.

**Quem vê**: só o Administrador (decisão U1). A rota HTML não tem guarda; a
tela expulsa quem não é admin e todas as APIs exigem `require_admin`.

### Decisões

| # | Pergunta | Decisão | Motivo |
|---|----------|---------|--------|
| U1 | A matriz permitia dar "Usuários: ler/editar" a Gestor, mas a tela expulsava quem não é admin. | **Só Administrador.** `usuarios` saiu da matriz configurável (`MODULOS_SO_ADMIN`); linha antiga no banco é ignorada. | É aqui que se nomeia Gestor e Administrador; quem concede papéis tem de estar acima dos papéis. |
| U2 | Campo "Gestor responsável" (`gestor_id`): informativo, não autorizava nada, não importado por CSV, perdido no cadastro. | **Removido** da tela e do servidor. Coluna fica no banco até migration futura. | Com Departamento obrigatório e Gestores por departamento, dois lugares dizendo "a quem responde" divergiriam. |
| U3 | Desativar um Gestor mantinha a liderança: departamento parecia atendido; reativar devolvia gestor vendo tudo. | **Desativar tira as lideranças**, o que o rebaixa a Operador pela regra; reativar volta como Operador. | Gestor que não entra no portal não libera nada. "Reativação do zero" é o que o glossário já promete. |
| U4 | Rota `DELETE /api/users/{id}` existia sem botão, e tokens/logs de instalação apontam para o usuário sem regra de exclusão. | **Rota removida.** Desativar é o caminho. | Apagar perderia a trilha de quem instalou o quê. |
| U5 | Importação por CSV contava "ignoradas" sem dizer quais. | **Listar as ignoradas com motivo** ("já existe", "campo vazio: …"), junto dos erros. | Quem importa 40 linhas e lê "3 ignoradas" abre a planilha para adivinhar. |
| U6 | "Pessoas" do departamento contava ativos e inativos; decidia o aviso ao apagar. | **Contar só ativos**, inativos à parte. | A pergunta da coluna é "quem fica sem gestor se eu apagar". |

### Defeitos corrigidos

- "setor" (4 textos) e "líderes" (2 mensagens do servidor) → departamento, gestores.
- Lead prometia "remova membros"; não há remover. Texto diz que quem sai é desativado.
- Erro de carregamento nas abas Usuários e Departamentos era silencioso (só console). Agora aparece na tabela com "Recarregar".
- Ao salvar os gestores de um departamento ou apagar um departamento, o servidor devolvia quem mudou de papel e a tela ignorava. Agora anuncia: "X virou gestor" / "X voltou a operador, com a carteira vazia".
- Modal de senha dizia "a sessão aberta dela não cai"; o servidor carimba `senha_alterada_em` e derruba. O código está certo; o texto foi corrigido.
- Aba Níveis de acesso mostrava Usuários como "ainda não governado por esta tela"; agora diz "só o administrador: aqui se nomeiam gestores e administradores".

### Fica como está (visto, sem mudança)

- A rota HTML `/usuarios` continua sem guarda no servidor; quem barra é a API e o redirecionamento no JS. Todas as outras páginas seguem o mesmo padrão; revisar junto na página Login.
- Filtro de status padrão "Ativo" faz o estado vazio dizer "Nada encontrado com esses filtros" mesmo sem filtro escolhido. Aceitável: o link "Limpar filtros" resolve.
- `inicio` não é governado pela matriz (todo papel vê o Início).

### Pendente nesta página

- Aba Níveis de acesso: granularidade (por usuário; "apagar" separado de "editar") — a grelhar.

### Testes

`tests/test_pagina_usuarios.py` cobre U2 a U6, vocabulário e estados; `tests/test_permissoes.py` cobre U1.
