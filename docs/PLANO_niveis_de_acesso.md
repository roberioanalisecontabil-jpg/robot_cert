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

### 0.3 Só existem três papéis, e nenhum eixo de leitura × escrita

`auth.py:PAPEIS_VALIDOS` = `("admin", "gestor", "user")`. As 66 rotas de API se
distribuem em quatro guardas:

| Guarda | Rotas |
|---|---|
| `require_admin` | 31 |
| `require_auth` (qualquer autenticado) | 19 |
| pública (por desenho — ver §0.4) | 13 |
| `require_agent_or_admin` | 3 |

Não há nada entre "qualquer autenticado" e "admin". **Um gestor tem exatamente
os mesmos poderes de API que um operador comum**, exceto onde a própria rota
checa liderança de departamento por dentro.

E não existe distinção de **ler vs. escrever** em lugar nenhum: `require_auth`
guarda igualmente um `GET /api/certificados` e um `POST /api/agent/commands`.

**Consequência:** o eixo "editar ou só visualizar" do pedido **não tem onde
morar**. É a parte cara, e é a que dá valor real.

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
| `carteiras` | 3 | 3 | pública, admin |
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
3. **`carteiras` mistura pública e admin** — a importação por planilha checa
   liderança por dentro, o que funciona mas não aparece no mapa de guardas.
4. **`gestor` não tem poder de API nenhum** que o operador também não tenha.

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

**Etapa 2 — dar poder ao `gestor` (sem tela).**
Hoje o papel existe e não concede nada além do menu de Carteiras. Definir o que
um gestor deve alcançar, e aplicar. Sem isso, "configurar o que o gestor pode"
configura um papel vazio.

**Etapa 3 — a matriz em banco.**
Tabela `permissoes(papel, modulo, nivel)`, com os valores atuais como semente —
assim o comportamento não muda no dia do deploy. Uma dependência
`require_modulo("usuarios", "editar")` substituindo `require_admin` rota a rota.

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
