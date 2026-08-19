# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

**Usuário primário — o colaborador da AnaliseGroup.** Entra no portal para
achar o certificado digital do cliente que precisa usar, baixar o instalador e
voltar ao trabalho. A visita é curta, esporádica e instrumental: ninguém abre
este portal para explorá-lo. Tempo de sessão alto aqui é sintoma de fracasso,
não de engajamento (medido e argumentado em `docs/PLANO_reorganizacao_portal.md`
§0.1).

Dois papéis secundários, ambos com contas no mesmo portal:

- **Admin (TI da AnaliseGroup)** — opera o inventário: vencidos, duplicidades,
  saúde dos agentes, contas, configuração, custódia dos PFX. É quem usa o portal
  com frequência diária.
- **Gestor de departamento** — monta e acompanha a carteira do seu time e
  concede acesso de instalação por carteira. Não administra contas.

Os papéis no código são exatamente três: `admin`, `gestor`, `user`
(`app/auth.py:PAPEIS_VALIDOS`). Papel e estado da conta (`ativo`) são campos
separados desde 15/08/2026.

## Product Purpose

Impedir que um certificado digital ICP-Brasil vencido ou extraviado pare o
trabalho. O produto mantém um inventário vivo dos arquivos `.pfx`/`.p12`
guardados nos servidores Windows da AnaliseGroup, avisa antes do vencimento, e
entrega ao colaborador certo o certificado certo já pronto para instalar na
estação dele.

Sucesso é o colaborador resolver a instalação em um clique e o admin nunca ser
surpreendido por um vencimento.

## Positioning

Uso interno da AnaliseGroup — não é vendido a terceiros e não há segundo
inquilino. Os certificados custodiados são **de clientes do escritório**, não do
escritório; é essa custódia de terceiros que dá o peso de segurança ao produto.

O mecanismo que um inventário genérico de certificados não copia: um **agente
Windows event-driven** (`watchdog`) que observa a pasta em tempo real e empurra
o estado ao portal a cada mudança, somado a um **cofre de PFX** que separa duas
decisões com donos diferentes — *custódia* (o admin decide se a chave privada
sai do servidor) e *acesso* (o gestor decide quem pode instalar). Enquanto essas
duas eram o mesmo flag, "liberar para instalar" e "copiar chave privada para a
nuvem" eram o mesmo clique.

## Operating Context

- **Estações Windows.** É a plataforma real dos usuários; a instalação do
  certificado acontece na máquina deles, via `.exe`.
- **Servidor de arquivos com os `.pfx`** (hoje `ANALISESRV`), varrido pelo agente
  local. A convenção de nome do arquivo carrega a senha do PFX:
  `Nome legível senha <palavra_passe>.pfx`.
- **O `.exe` de instalação é propositalmente idêntico em todo download**
  (`app/main.py`) — é o que permite assiná-lo uma vez e acumular reputação no
  SmartScreen. Um binário inédito por clique dispararia "aplicativo não
  reconhecido" exatamente no fluxo que deveria ser de um clique. O nome do
  titular é parametrizado por querystring (`?nome=`, sanitizado); o ícone é
  assado em build e trocá-lo exige recompilar e reassinar.
- **Alertas por e-mail (SMTP)** disparam antes do vencimento; há job diário e
  gatilho manual.
- **Carteira** é a lista de clientes (por CNPJ/CPF) atribuída a um colaborador;
  pode ser montada à mão ou importada por planilha `.xlsx`/`.csv` de
  e-mail + CNPJ.
- Superfícies do portal hoje: Início (`/`), Dashboard, Histórico, Vencidos,
  Duplicidades, Acompanhamento, Carteiras, Instalador, Usuários, Configuração,
  Login. A navegação é única (`templates/_sidebar.html`); três itens são
  revelados pelo JS conforme o papel.

## Capabilities and Constraints

**Restrições declaradas como lei pelo usuário (19/08/2026):**

- **Vanilla JS, sem framework e sem build step.** HTML + CSS + JS puro. Nada de
  React/Vue/Tailwind.
- **Português do Brasil, sem i18n.** Não existe camada de tradução e não haverá.
- **Vercel serverless + Supabase (PostgreSQL).** Cold start e limites de função
  serverless condicionam o que pode rodar no servidor.

**Fatos técnicos que trabalhos futuros precisam respeitar:**

- Templates Jinja2 servidos por FastAPI; um único `static/style.css` e um único
  `static/ui-common.js` atendem todas as páginas.
- Autenticação JWT stateless de 24h; troca de senha derruba sessões abertas via
  comparação `iat` × `users.senha_alterada_em`. Senha definida por terceiro
  (`deve_trocar_senha`) bloqueia todas as rotas até a troca.
- `X-API-Key` autentica o agente, que não tem conta no portal.
- Regras de falha do cofre são estruturais, não convenção: a resposta de custódia
  carrega afirmação de completude e o agente **recusa enviar** quando não
  conseguiu obtê-la. Distinguir "nada desativado" de "não consegui saber" é o
  ponto inteiro.
- `cert_history` guarda uma linha por arquivo com o estado **atual** (upsert por
  `file_name`) — não é histórico. O histórico real são os snapshots
  (`cert_snapshots`).
- Chave do cofre é composta: `(machine_id, fingerprint)`.
- LGPD é peso real: `install_log` guarda `client_ip` por usuário e já existe
  migration de RLS. Cronometrar presença de funcionário foi recusado de
  propósito — mede-se **atividade** (última ação, ações no período, conclusão),
  não permanência.

**Fora do portal web, no mesmo repositório:** um agente Windows com ícone de
bandeja e janela de status (`agent/`), empacotado por PyInstaller/Inno Setup.
Não é uma superfície web e não está coberto por este registro; tratá-lo exige
combinar escopo antes.

## Brand Commitments

- Nome exibido no portal: **Analise Certificado** / "Monitor de Certificados".
  Nome do produto na documentação: **Analise CertiDigital** (anteriormente
  *Robot Cert*, ainda o nome do repositório).
- Autoria: **Roberio França | AnaliseGroupTI**.
- Marca visual existente: `static/logo.png` (512×512, quadrado), servido em
  36×36 na sidebar.
- Voz: português do Brasil, direta, sem jargão de marketing. Os comentários do
  código e os documentos de planejamento seguem a mesma voz — explicam *por quê*,
  não *o quê*.

**Decisão em aberto, deliberadamente:** a linguagem visual atual (tokens
derivados do vocabulário Apple, tema claro + escuro, contraste documentado) está
implementada em `static/style.css` e descrita em `docs/guia-design-apple.md`,
mas **não foi confirmada como lei**. Ela é evidência do estado atual, não um
compromisso de marca. Preservar, expandir ou substituir esse mundo visual é uma
decisão que ainda não foi tomada.

## Evidence on Hand

Real, medido contra o banco de produção em 15/08/2026 (`docs/PLANO_reorganizacao_portal.md`):

- ~560 certificados no último snapshot; 1.029 arquivos em `cert_history`.
- 317 varreduras registradas entre 24/04 e 15/08/2026.
- 33 de 560 no cofre sob o modelo opt-in antigo (6%); passivo identificado de 68
  certificados sem utilidade (16 vencidos, 21 ilegíveis, 31 fora do padrão).
- Uma única máquina no cofre até 15/08: `ANALISESRV`.
- Diário técnico com histórico real de decisões: `CHANGELOG_DEV.md`.
- Documentos de planejamento com medições, não estimativas: `docs/PLANO_reorganizacao_portal.md`,
  `docs/PLANO_chave_composta_cofre.md`, `docs/Plano_de_Acao_Seguranca_OWASP.md`,
  `docs/Auditoria_UIUX_skills_2026-08-02.md`.
- Suíte de testes pytest (258 testes na última medição registrada), incluindo um
  teste que renderiza todas as rotas de página e exige exatamente um item de menu
  aceso em cada uma.

**Não existe e não deve ser inventado:** depoimento de cliente, benchmark,
preço, licença, logo de cliente, número de usuários ativos, ou qualquer métrica
de tempo de uso — a instrumentação para essa última não existe e foi recusada
por LGPD.

## Product Principles

1. **A tarefa do colaborador dura menos de um minuto.** Todo desenho da página
   Início e do fluxo de instalação é julgado por esse relógio. Retenção não é
   objetivo; saída rápida é.
2. **Custódia e acesso são decisões separadas, com donos separados.** Nenhuma
   interface pode voltar a fundi-las num clique só.
3. **Na dúvida, falha fechada.** Vale para chave privada, para expurgo e para
   qualquer estado que a UI apresente como certo: "não consegui saber" nunca
   pode ser renderizado como "não há nada".
4. **Papel decide o que aparece; o rótulo diz a verdade sobre o que concede.**
   Um item de menu ou campo que sugira poder que ele não dá é defeito.
5. **Medir atividade, nunca permanência.** Qualquer painel sobre pessoas mostra
   o que foi feito e o que travou — não quanto tempo alguém ficou logado.
