# Plano — níveis de acesso por papel

> **Status: levantamento. Nada implementado.**
> Elaborado em 2026-08-19. Todos os números vieram de `app/main.py` e
> `static/ui-common.js` na data, contados por script, não estimados.

Pedido original: *"uma aba com os níveis de acesso, para definir quais acessos o
gestor e o usuário podem ter — quais páginas vão aparecer (módulo), e se é
possível editar ou só visualizar."*

Este documento é o mapa que precisa existir **antes** da tela. Sem ele, qualquer
interface de permissões chuta a granularidade — e uma granularidade errada é
mais cara de desfazer do que de acertar.

---

## 0. O que a medição mostrou

Quatro fatos que mudam o escopo do pedido.

### 0.1 As páginas não são protegidas no servidor — e não precisam ser, hoje

As **13 rotas HTML** (`/`, `/dashboard`, `/usuarios`, `/carteiras`,
`/instalador`, …) não têm guarda nenhuma. Qualquer requisição recebe o HTML.

Mas o HTML não carrega dado. As 11 chamadas de `TemplateResponse` passam
**exclusivamente** `{"pagina_ativa": "..."}` — o valor que acende o item do
menu. Nenhuma passa usuário, certificado, carteira ou configuração.

| | |
|---|---|
| Páginas servidas sem guarda | 13 |
| Dessas, que carregam algum dado | **0** |

Ou seja: hoje o portal é **dado protegido, casca pública**. Um operador que
digitar `/usuarios` recebe a página, o JS chama `/api/users`, o servidor
responde 403, e ele vê uma tabela vazia. Constrangedor, não vazamento.

**Consequência para o pedido:** "definir quais páginas aparecem" é hoje uma
questão de **ergonomia e clareza**, não de fechar um buraco. Isso é bom — o
trabalho é menor do que parece. Mas também significa que uma tela que só
esconde itens de menu **não acrescenta segurança nenhuma**, e não deve ser
vendida como se acrescentasse.

### 0.2 A revelação do menu já é centralizada — e o código já admite o que ela é

`static/ui-common.js:62` tem a lista inteira, em cinco linhas:

```js
const porPapel = {
  admin:  ["nav-users", "nav-config", "nav-installer", "nav-dashboard", "nav-carteiras"],
  gestor: ["nav-carteiras"],
};
```

O comentário acima dela é explícito: *"O servidor confere de novo em cada API:
isto é conveniência, não barreira."*

**Consequência:** a parte "quais páginas aparecem" já tem um ponto único de
verdade. Torná-la configurável é trocar esse literal por dado vindo da API —
trabalho pequeno. O que não existe é o resto.

### 0.3 Quatro guardas, e o gestor já tem alcance real

> **Corrigido em 19/08, depois da primeira versão deste documento.** A versão
> original afirmava que existiam quatro guardas e que *"um gestor tem exatamente
> os mesmos poderes de API que um operador comum"*. **As duas coisas eram
> falsas**, e a causa foi um erro de método meu: o censo procurava as strings
> `require_admin`, `require_auth` e `require_agent_or_admin` — e `require_admin`
> é **substring** de `require_admin_ou_lider`, então as 5 rotas de carteira do
> gestor foram contadas como admin puro e a quarta guarda desapareceu da tabela.
> Fica registrado porque o erro é sutil e reincidente: censo por substring
> mistura o específico com o geral sempre que um nome contém o outro.

`auth.py:PAPEIS_VALIDOS` = `("admin", "gestor", "user")`. As 66 rotas de API se
distribuem em **quatro** guardas mais as rotas deliberadamente públicas
(contagem de 19/08, já com a Etapa 1 aplicada):

| Guarda | Rotas | Quem passa |
|---|---:|---|
| `require_admin` | 29 | só admin |
| `require_auth` | 14 | qualquer autenticado |
| _(sem guarda, por desenho — ver §0.4)_ | 13 | qualquer um |
| `require_agent_or_admin` | 5 | o agente (X-API-Key) e admin; recusa identidade anônima |
| `require_admin_ou_lider` | 5 | admin, ou gestor que lidera ao menos um departamento |

**O modelo de gestor já existe e é mais fino do que "papel".** Desde 18/08 são
duas camadas:

1. `require_admin_ou_lider` — o papel abre a porta. Gestor **sem liderança
   nenhuma** é recusado ali mesmo; deixá-lo entrar numa tela onde toda ação
   falha depois transformaria o sintoma em "não consigo salvar nada".
2. `_exigir_alcance` — a liderança define **até onde**. Presente em 5 rotas,
   confere o alvo com `cert_installer.pode_gerir`: um líder do Fiscal não monta
   a carteira de alguém do Contábil trocando o `user_id` na chamada.

E há um detalhe que vale copiar para qualquer permissão futura: falha de
verificação responde **503, não 403**. *"Não consegui verificar"* não é *"você
não pode"* — um 403 ali faria o líder acreditar que perdeu a permissão.

**O que continua verdadeiro:** não existe distinção de **ler vs. escrever** em
lugar nenhum. `require_auth` guarda igualmente um `GET /api/certificados` e um
`POST` de escrita. O eixo "editar ou só visualizar" do pedido segue sem onde
morar — essa parte da §0.3 original estava certa, e continua sendo a cara.

### 0.4 As 13 rotas públicas são públicas de propósito

Verifiquei uma a uma; nenhuma é descuido:

- `/api/login`, `/api/senha/{codigo,verificar,redefinir}` — precisam ser
  alcançáveis por quem ainda não tem sessão.
- `/api/health`, `/api/cron/alerts` — a segunda valida `CRON_SECRET`.
- `/api/cert-installer/claim` e `/report-avulso` — **o token é a credencial**,
  com rate limit por IP e resposta única que não distingue token inválido de
  expirado, para não virar oráculo. Está documentado na própria função.
- `/instalador/baixar/{token}` — serve um binário idêntico para todos, que não
  contém segredo; o certificado só sai depois, pelo `claim`.
- As demais de `cert-installer` e `carteira/importar` checam autorização no
  corpo, não no decorador.

**Não mexer nelas.** Uma tela de permissões que resolva "toda rota precisa de
papel" quebraria o login e o instalador avulso.

---

## 1. O mapa: módulo × o que existe hoje

Contagem por módulo, separando leitura de escrita — que é o eixo que o pedido
quer configurar e que hoje não existe.

| Módulo | Rotas de leitura | Rotas de escrita | Guarda hoje |
|---|---:|---:|---|
| `usuarios` (+ departamentos) | 3 | 12 | admin, auth |
| `instalador` | 6 | 12 | pública, admin, agent_or_admin, auth |
| `carteiras` | 3 | 3 | admin_ou_lider (+ alcance por pessoa) |
| `configuracao` | 1 | 3 | admin, auth |
| `conta` (login/senha) | 0 | 5 | pública, auth |
| `acompanhamento` | 4 | 1 | auth |
| `certificados` | 4 | 0 | auth |
| `agente` | 2 | 1 | auth |
| `dashboard` | 2 | 0 | admin |
| `ingest` | 0 | 1 | auth |
| `mover-vencidos` | 0 | 1 | auth |
| `sistema` (health/cron) | 2 | 0 | pública |

**Onde está a dívida, em ordem de risco:**

1. **`agente` e `ingest` sob `require_auth`.** Qualquer usuário autenticado pode
   enfileirar comando para o agente e mandar inventário. São 3 rotas.
2. **`mover-vencidos` sob `require_auth`.** Move arquivo de certificado no
   servidor. Uma rota.
3. **`carteiras/importar` não declara guarda no decorador** — checa liderança
   por dentro. Funciona, mas não aparece em nenhum censo de guardas, que é
   exatamente como a quarta guarda escapou da primeira versão deste documento.

Os itens 1 e 2 valem correção **independente** da tela de permissões: são
guardas coarse demais para a ação que protegem, e o conserto é trocar
`require_auth` por uma guarda de papel nas quatro rotas.

---

## 2. O modelo que o pedido implica

Uma matriz **papel × módulo × nível**, com três níveis:

| Nível | Significado |
|---|---|
| `nenhum` | o módulo não aparece no menu **e** as rotas dele recusam |
| `ler` | aparece; só rotas de leitura passam |
| `editar` | aparece; leitura e escrita passam |

Com 3 papéis × 12 módulos, são 36 células. A matriz cabe numa tela sem rolagem.

**Mas a matriz sozinha é grosseira demais para o que já existe.** O modelo de
carteiras (§0.3) tem um terceiro eixo que uma grade papel × módulo não expressa:
**alcance** — *de quem* o ator pode tratar, derivado da liderança de
departamento. Achatar isso numa célula `gestor × carteiras = editar` **perderia**
a barreira que impede um líder do Fiscal de mexer na carteira do Contábil.

Portanto: a matriz governa **se** o módulo é alcançável e em que profundidade;
o alcance por pessoa continua onde está, em `_exigir_alcance`. A tela não deve
prometer configurar alcance — isso é liderança de departamento, e já tem dono.

**A regra que não pode ser negociada:** o nível governa **as rotas**, e o menu é
consequência. Se for o contrário — o menu esconde e as rotas continuam abertas —
o resultado é uma tela que promete controle sem exercê-lo, que é pior que não
ter tela, porque cria confiança falsa.

---

## 3. Ordem de implementação

Cada etapa entrega valor sozinha e pode parar aí.

**Etapa 1 — fechar as guardas coarse (sem tela, sem migration). ✅ FEITA em 19/08.**

- `POST /api/agent/commands`, `GET /api/agent/queue`, `POST /api/mover-vencidos`
  → `require_admin`. Chamadas só por `configuracao.html` (página de admin); a
  terceira não tem chamador no portal.
- `POST /api/ingest`, `GET /api/agent/next` → `require_agent_or_admin`.

A segunda parte esperava confirmação de que a `API_KEY` está configurada em
produção — `require_agent_or_admin` recusa a identidade anônima que
`require_auth` cria na ausência dela, e apertar sem a chave pararia a ingestão
de inventário em silêncio.

**A confirmação veio por evidência, não por consulta:** o agente já chama
`upload-pfx`, `redeem` e `report`, as três sob `require_agent_or_admin`, e o
cofre de produção tem 491 certificados do ANALISESRV que só chegam por
`upload-pfx`. Se a chave não estivesse lá, essas três já estariam quebradas.

Dois testes de barreira novos, ambos verificados por mutação: afrouxar a guarda
faz o teste falhar.

**Etapa 2 — dar poder ao `gestor`. ✅ JÁ ESTAVA FEITA, em 18/08/2026.**
Descoberto ao investigar, não planejado: `require_admin_ou_lider` +
`_exigir_alcance` já implementam exatamente o que o `PRODUCT.md` registra sobre
o papel — *"monta e acompanha a carteira do seu time; não administra contas"*.
A primeira versão deste plano propunha construir o que já existia.

**Etapa 3 — a matriz em banco. ✅ FEITA em 20/08.**
Tabela `permissoes(papel, modulo, nivel)` aplicada em produção, semeada com o
comportamento de então; a conferência do PASSO 4 bateu com a semente papel por
papel. `app/permissoes.py` resolve a matriz, e `require_modulo(modulo, nivel)`
em `main.py` é a dependência.

**Ligado até agora: `dashboard`, `usuarios`, `historico`, `vencidos`,
`duplicidades` e `acompanhamento`** — 24 rotas. Era `require_admin` e a matriz
dá `nenhum` a gestor e user — comportamento idêntico, que é o motivo de começar
por ele.

**Armadilha encontrada ao ligar, que muda a ordem das próximas.** Nem toda rota
de um módulo pode ir para a matriz: `GET /api/settings` pertence a
`configuracao`, mas quem o consome é o **agente**, para saber quais pastas
monitorar. O agente autentica por X-API-Key e recebe papel `agent`, que não está
na matriz e cairia em `nenhum` — ligá-lo pararia a ingestão em produção.

**Três carve-outs que o modelo precisou, e cada uma vale uma regra:**

1. **Rota sobre a própria conta não entra na matriz.** `/api/users/me/export` e
   `/api/users/me/delete` são LGPD; amarrá-las à permissão do módulo Usuários
   tiraria de um operador o direito de exportar os próprios dados. Pelo mesmo
   motivo, o `PUT` de Acompanhamento fica em `ler` e não em `editar`: ele salva
   a seleção do próprio chamador (`token.email`).

2. **`/api/certificados` fica fora.** `scripts/diagnostico.py` a consome com
   X-API-Key — ligá-la faria a ferramenta reportar "-1 itens" em silêncio, e
   quebrar o termômetro é pior que a febre. E `inicio` é onde todo mundo
   aterrissa: desligá-lo para um papel deixaria a pessoa entrar e não ver nada.

3. **Identidade anônima passa; agente de verdade não.** Sem `API_KEY`,
   `require_auth` devolve `anonymous@local` e o portal fica aberto — a
   compatibilidade que ele mesmo documenta. `require_modulo` não pode ser mais
   estrito que ela, senão o portal para em dev. Já `agent@internal` continua
   barrado: o agente não tem o que fazer num módulo de gente. **A distinção é
   por e-mail, não por papel** — os dois chegam com role `agent`.

**Falta ligar:** `carteiras` (5 rotas, compõe com `require_admin_ou_lider`),
`instalador` (18 rotas, 7 tocadas pelo agente) e `configuracao` (4 rotas, 2
tocadas pelo agente). São os três delicados, e por isso ficaram por último.

Regra que sai daí: **rota que uma máquina chama fica com
`require_agent_or_admin`; `require_modulo` é para rota que só gente usa.** Antes
de ligar cada módulo, conferir os chamadores em `agent/`, e não só em
`templates/`.

**Etapa 4 — a tela.**
Aba em `/usuarios`, matriz 3 × 12, alimentada pela API da etapa 3. É a parte
mais visível e a mais barata; vem por último de propósito.

**Etapa 5 — o menu passa a ler da API** em vez do literal de
`ui-common.js:62`, com o mesmo fallback de hoje se a chamada falhar (falha
fechada: menu mínimo, não menu completo).

---

## 4. O que este documento não resolve

- **Permissão por usuário**, e não por papel. O pedido fala em papéis; se
  amanhã for preciso "este gestor específico não vê Configuração", o modelo da
  §2 não serve e a tabela precisa de `user_id`.
- **Granularidade abaixo de módulo.** "Pode editar usuário mas não apagar" não
  cabe em três níveis. Se for necessário, o eixo vira ação e a matriz cresce.
- **LGPD.** Registrar quem mudou qual permissão e quando é auditoria de
  concessão de acesso, e este portal já trata isso com cuidado no cofre. Uma
  tabela de permissões sem trilha seria a única concessão sem rastro.

---

## 5. Decisão pendente

Antes da etapa 3, três perguntas cuja resposta muda a tabela:

1. **Papel ou usuário?** (§4, primeiro item)
2. **Três níveis bastam**, ou `editar` precisa se separar de `apagar`?
3. **O `admin` pode perder acesso a algum módulo**, ou é sempre total? Se for
   sempre total, a matriz tem 2 linhas em vez de 3 e uma classe inteira de
   engano — o admin se trancando para fora — deixa de existir.
