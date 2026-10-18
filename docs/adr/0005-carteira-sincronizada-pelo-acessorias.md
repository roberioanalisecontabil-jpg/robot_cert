---
status: accepted
date: 2026-10-18
supersedes: 0004 (em parte)
---

# Carteira, departamentos e contas sincronizados pelo Acessórias

O ADR 0004 (16/10/2026) fez o Acessórias **sugerir** carteiras e departamentos, com aprovação de
quem já edita a carteira. Em 18/10/2026 a decisão mudou: o trabalho de aprovar cada troca seria
o mesmo trabalho manual de hoje, e a carteira ficaria atrasada em relação ao Acessórias, que é
onde o escritório de fato diz quem cuida de qual empresa.

Decidimos que o **Acessórias manda por padrão**: quem é responsável por uma empresa lá ganha o
certificado dela aqui, e quem deixa de ser perde, sem aprovação. Gestor e Administrador ainda
podem liberar a mais (manual) e bloquear. Ficam do ADR 0004 o que não muda: só leitura da API,
token do `.env`, busca completa, cópia local, CNPJ com recurso à matriz, histórico e a tela de
departamentos.

## Busca

- Completa, por `GET /companies/ListAll?departments&Pagina=N`, como no ADR 0004.
- **A cada 5 minutos das 7h às 20h e a cada hora no resto do dia**, mais o botão **Buscar
  agora**. O Acessórias não avisa mudanças, e o `DtLastDH` não pega troca de responsável.
- **Cota:** o limite de 100 requisições por minuto é dividido com o DIARIO2.0, que roda das
  07:30 às 12:00. O portal faz no máximo **30 por minuto** (a busca leva cerca de 1 minuto), e
  o DIARIO2.0 baixa para 60 por minuto. A mudança no DIARIO2.0 é de um número no cliente
  (`src/diario/acessorias.py`).

## Trava contra apagão

- A busca só é aplicada se veio **inteira**: todas as páginas lidas, sem erro, e com quantidade
  de empresas parecida com a da busca anterior.
- Se ela tiraria **mais de 10% dos acessos** de uma vez, nada é aplicado: o resultado fica
  guardado e o Administrador confirma com um clique, vendo os números.
- **A primeira aplicação sempre pede essa confirmação.**

## Contas

- Cada **usuário ativo do Acessórias** sem conta no portal ganha uma, ligada pelo **e-mail**
  (sem distinguir maiúsculas). A conta nasce **sem senha**, e a pessoa recebe um e-mail "defina
  sua senha" válido por **7 dias**, pelo mesmo mecanismo do `senha_reset`. O login continua
  pedindo código.
- Usuário **inativo** no Acessórias tem a conta **desativada** aqui, o que já esvazia a carteira
  e derruba a sessão. Reativado lá, reativa aqui.
- **Administradores** e contas que **não vieram do Acessórias** (TI, por exemplo) nunca são
  tocados.
- **Quem é Gestor** continua manual (`departamento_lider`, ADR 0001). O Acessórias não sabe quem
  lidera.

## Carteira

- Continua por **documento** (ADR 0001): toda renovação do mesmo CNPJ/CPF herda o acesso.
- **CNPJ exato**; se ele não tem certificado, vale o da **matriz** (mesma raiz, `/0001`).
  **E-CPF** de sócio não vem do Acessórias e só entra manualmente.
- **Origens:**
  - `acessorias`: entra e sai com a busca.
  - `manual`: liberada pelo Gestor ou pelo Administrador; a busca não mexe nela. Se o Acessórias
    passar a trazer o mesmo documento para a mesma pessoa, a linha vira `acessorias` e passa a
    sair com ela.
- **Bloqueio:** o Gestor bloqueia para os Operadores dos departamentos que lidera, e o
  Administrador para qualquer pessoa. A busca respeita o bloqueio e não recria o acesso. O
  bloqueio aparece na carteira com quem bloqueou e quando.
- **Gestor:** alcança a **própria carteira mais todas as empresas que têm responsável, no
  Acessórias, num departamento que ele lidera**. Deixa de ser "tudo menos as Exceções" (ADR
  0001); `carteira_excecao` é apagada na virada.
- **Administrador:** alcança tudo, como hoje.
- **Virada:** a carteira manual que não estiver no Acessórias sai, passando pela trava (a
  primeira aplicação pede confirmação). O que o Administrador quiser manter, libera como manual.
- Todo movimento vai para `carteira_historico`, com a origem.

## Departamentos

- Em **Configuração**, a lista dos departamentos do Acessórias, cada um com uma chave
  **trazer**. Ligar cria (ou liga, se já houver um de mesmo nome) o departamento no portal.
  Desligar faz os acessos vindos dele saírem na próxima busca, com a trava.
- Na virada, cada departamento do portal se liga ao do Acessórias de mesmo nome. Os que não
  tiverem par ficam marcados "sem par no Acessórias", para ligar à mão ou arquivar.
- **Pessoa → departamento:** automático quando a pessoa aparece no departamento pelo menos 3
  vezes mais que no segundo (regra do adendo do ADR 0004). Nos outros casos, o Administrador
  decide e a decisão dele vence até o Acessórias mudar aquela pessoa.

## Opções consideradas

- **Sugerir e aprovar** (ADR 0004): substituída por esta.
- **Gestor não bloqueia**, só corrigindo no Acessórias: descartada; o Gestor precisa poder segurar
  um acesso sem depender de outro sistema.
- **Manter a carteira manual atual na virada** e só somar: a sincronização nunca limparia nada.
- **Relatório "ganharia/perderia" antes de ligar**: dispensado; a trava pede a confirmação com
  os números.
- **Busca a cada 5 minutos o dia todo** ou **a cada 15 minutos**: a primeira gasta cota de
  madrugada; a segunda atrasa demais.
- **Deixar portal e DIARIO2.0 disputarem a cota**: buscas do portal sairiam incompletas e não
  seriam aplicadas.

## Consequências

- A migration de 16/10 (`20261016100000`) foi feita para sugestões: `acessorias_recusa` perde o
  uso nas carteiras (fica para a decisão de departamento) e entram bloqueio, origem da conta e o
  resultado da busca guardado para confirmação. Uma migration nova faz isso.
- No dia da virada os Gestores passam a ver bem menos do que hoje.
- O DIARIO2.0 muda num número (limite por minuto).
- Ordem de entrega: correção do certificado renovado (separada) → este ADR → migration → busca
  e aplicação com trava → contas → tela de departamentos → bloqueio e liberação manual.
