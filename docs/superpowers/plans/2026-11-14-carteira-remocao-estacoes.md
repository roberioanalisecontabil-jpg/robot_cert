# Remoção de certificados nas estações (Frente B) — plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** a bandeja tira do `CurrentUser\My` os certificados do acervo que a pessoa (ou o último dono do perfil) não pode mais ter, com modo só relatório antes de remover de verdade.

**Architecture:** o portal decide e a bandeja executa. A bandeja manda os SHA-256 do `CurrentUser\My` e o portal devolve quais remover. Uma tabela nova (`remocao_estacao`) guarda o estado por máquina, usuário do Windows e certificado: o relatório do TI, o relógio dos 7 dias e o resultado. Duas chaves na Configuração (`desligado`/`relatorio`/`ligado`) mandam em tudo.

**Tech Stack:** FastAPI, PostgreSQL 17 (cliente `_banco()` estilo Supabase), pytest. Na bandeja: Python, httpx, PowerShell (`Cert:\CurrentUser\My`).

**Spec:** `docs/superpowers/specs/2026-11-13-carteira-certificados-remocao-uso-design.md` (seção "Frente B" e subseções).

## Global Constraints

- **Escopo:** só certificados do acervo, ou seja, fingerprint (SHA-256 do DER, hex minúsculo) presente em `cert_pfx_store`. Certificado fora do acervo nunca é tocado.
- **Documento nulo:** item do cofre com `documento` nulo nunca é removido.
- **Falha de leitura nunca remove:** falha ao ler a carteira, o cofre ou o vínculo (`CarteiraIndisponivel` ou qualquer exceção do banco) devolve 503, e a bandeja não remove nada.
- **Carteira em vigor** = `cert_installer.documentos_ao_alcance(user_id, role)`. Admin nunca perde nada. Gestor perde só as Exceções. Operador perde o que está fora da carteira em vigor, inclusive pelo prazo.
- **Onde remover:** só o `CurrentUser\My` do perfil logado. Remove o certificado **e a chave privada**.
- **Modos:** `desligado`, `relatorio` e `ligado`.
  - Chave `remocao_carteira_modo`: regra da carteira, conta desativada, vínculo recusado ou desvinculado, e empréstimo vencido.
  - Chave `remocao_sem_login_modo`: perfil sem login.
  - Valor vazio vale `relatorio`. Só o Admin grava (o `PUT /api/settings` já é `require_admin`).
- **Prazo de aviso:** 7 dias. O aviso de vencimento do prazo sai 3 dias antes, no máximo uma vez por dia, e só para liberação manual com prazo.
- **Frequência da conferência:** no logon e depois a cada 5 minutos (300 s). As instalações continuam a cada 20 s.
- **Textos (pt-BR):**
  - Ao remover: "Certificado {nome} removido: saiu da sua carteira."
  - Perfil sem login: "Entre na bandeja do CertGuard. Sem login, os certificados da empresa serão retirados deste computador em {N} dias."
  - Vencimento: "O acesso ao certificado {nome} vence em {N} dias. Fale com seu gestor."
- **Versão da bandeja:** `estacao/__init__.py` passa de `VERSAO = "1.2.0"` para `VERSAO = "1.3.0"`.
- **Regras da casa:**
  - commits com `git commit -F <arquivo>`;
  - não editar arquivo por PowerShell;
  - a migration é aplicada só pelo deploy (`atualizar-portal`), nunca à mão;
  - o hook de pré-commit roda a suíte, e a correção e o commit vão em comandos separados.

## Rulings (decisões deste plano sobre o que o spec deixou aberto)

- **Tabela própria em vez de eventos no `install_log`:** `install_log.user_id` é NOT NULL, e o perfil sem login não tem pessoa. O estado (`removeria`, `aviso`, `remover`, `removido`, `falhou`) mora em `remocao_estacao`. Só o `REMOVIDO` com pessoa conhecida também vai ao `install_log` (event `REMOVIDO`, `detail` = motivo), e por isso aparece na trilha.
- **O relógio dos 7 dias do perfil sem login começa só com o modo `ligado`:** em `relatorio` ninguém recebe aviso. Se o relógio corresse no relatório, ligar a chave removeria sem aviso nenhum.
- **"Sair da conta" na bandeja não apaga mais o `conta.dat`:** ele fica marcado como encerrado e vira o último dono. Apagar faria o perfil cair na regra do perfil sem login e perder tudo em 7 dias, o anti-objetivo do spec.
- **Desvínculo é identificado pelo `motivo`:** um vínculo `encerrado` cujo `motivo` começa com `"Desvinculado por"` conta como desvinculado. O que `computadores.desvincular` grava hoje é `f"Desvinculado por {por}."`. Outros encerramentos ("entrou em outra máquina", "substituída") seguem a regra da carteira.
- **Empréstimo vencido:** é o vínculo `encerrado` com `motivo == "Prazo do empréstimo terminou."`. O relógio conta do `expira_em` dele.
- **Na tela, "a carteira e o painel mostram isso"** fica coberto pela aba Remoção da Configuração e pelo `REMOVIDO` na trilha. Uma linha na ficha da pessoa em Carteiras fica para depois do relatório.

## Review Focus

1. **Banco ou cofre fora do ar no meio da conferência:** a rota devolve 503 e a bandeja não remove nada (Task 3 e Task 5).
2. **O portal manda remover um SHA-256 que a bandeja não informou, ou que já sumiu do repositório:** a bandeja ignora (Task 7).
3. **A chave muda de `relatorio` para `ligado` com perfis sem login já listados:** ninguém perde certificado antes de 7 dias de aviso (Task 4).
4. **A máquina é aceita de novo dentro dos 7 dias depois de uma recusa:** o aviso some e vale a carteira (Task 3).
5. **Admin logado:** nada sai. **Gestor:** só as Exceções saem (Task 3).

---

### Task 1: Migration `remocao_estacao`

**Files:**
- Create: `supabase/migrations/20261114100000_remocao_estacao.sql`
- Test: `tests/test_migration_remocao_estacao.py` (mesmo estilo de `tests/test_migration_carteira_prazo.py`)

**Interfaces:**
- Produces: a tabela `public.remocao_estacao` com estas colunas:
  - `id bigserial PK`;
  - `machine_id text NOT NULL`;
  - `usuario_windows text NOT NULL`;
  - `user_id uuid NULL REFERENCES users(id) ON DELETE SET NULL`;
  - `fingerprint char(64) NOT NULL`;
  - `documento text`;
  - `regra text NOT NULL CHECK (regra IN ('carteira','desativada','vinculo','emprestimo','sem_login'))`;
  - `motivo text NOT NULL DEFAULT ''`;
  - `estado text NOT NULL CHECK (estado IN ('removeria','aviso','remover','removido','falhou'))`;
  - `aviso_desde timestamptz`;
  - `detalhe text NOT NULL DEFAULT ''`;
  - `atualizado_em timestamptz NOT NULL DEFAULT now()`;
  - `UNIQUE (machine_id, usuario_windows, fingerprint)`.

  Índices em `(estado, atualizado_em DESC)` e em `(user_id)`.

- [ ] **Step 1:** escrever os testes:
  - `test_tabela_idempotente`: `CREATE TABLE IF NOT EXISTS public.remocao_estacao`;
  - `test_checks_de_regra_e_estado`: os cinco valores de cada CHECK aparecem;
  - `test_unica_por_maquina_usuario_certificado`: aparece `UNIQUE (machine_id, usuario_windows, fingerprint)`;
  - `test_indices_idempotentes`: todo `CREATE INDEX` usa `IF NOT EXISTS`.
- [ ] **Step 2:** `pytest tests/test_migration_remocao_estacao.py -v`. Esperado: FAIL (arquivo ausente).
- [ ] **Step 3:** escrever o SQL, com um comentário de cabeçalho que cite o spec.
- [ ] **Step 4:** rodar de novo. Esperado: PASS.
- [ ] **Step 5:** commit, `feat(remocao): tabela remocao_estacao`.

### Task 2: As duas chaves na Configuração (backend)

**Files:**
- Modify: `app/settings_state.py` (`PortalSettings`: `remocao_carteira_modo: str = ""` e `remocao_sem_login_modo: str = ""`).
- Modify: `app/rotas/configuracao.py`:
  - `SettingsBody`: os dois campos como `Optional[str] = Field(default=None, max_length=16)`, com `None` = não mexe;
  - no `put_settings`, um valor fora de `("", "desligado", "relatorio", "ligado")` recebe 422.
- Modify: `app/comum.py` (`_settings_dict` expõe os dois).
- Create: `app/remocao.py` (só os modos nesta task).
- Test: `tests/test_remocao_modos.py`

**Interfaces:**
- Produces, em `app/remocao.py`:
  - `MODOS = ("desligado", "relatorio", "ligado")`;
  - `modo_carteira() -> str` e `modo_sem_login() -> str`: leem `load_settings()`, e vazio ou inválido vale `"relatorio"`.

- [ ] **Step 1:** testes:
  - `test_vazio_vale_relatorio`;
  - `test_put_grava_e_get_devolve` (Admin);
  - `test_put_valor_invalido_422`;
  - `test_put_sem_os_campos_preserva` (salvar as pastas não zera as chaves).

  Seguir o estilo de `tests/test_pagina_config_login.py` ou do teste que já cobre `alertas_novos_modo`.
- [ ] **Step 2:** rodar. Esperado: FAIL.
- [ ] **Step 3:** implementar.
- [ ] **Step 4:** rodar. Esperado: PASS.
- [ ] **Step 5:** commit, `feat(remocao): chaves de modo na configuracao`.

### Task 3: Decisão do portal (`app/remocao.py`)

**Files:**
- Modify: `app/remocao.py`
- Modify: `app/agent_devices.py` (nova `dono_do_segredo`)
- Test: `tests/test_remocao_decisao.py` (stubs com monkeypatch nas funções de leitura; banco falso só onde precisar, no estilo de `tests/test_carteira_prazo.py`)

**Interfaces:**
- Consumes:
  - `cert_installer.documentos_ao_alcance(user_id, role)` (`None` = total, `in` para conferir);
  - `cert_installer.CarteiraIndisponivel`;
  - `computadores._vinculos(**filtros)` e `computadores.mac`;
  - a tabela `carteira_historico` (`movimento`, `origem`, `feito_por_email`, `feito_em`);
  - `conta_ativa(row)` de `app.sessao`.
- Produces:
  - `@dataclass Decisao(fingerprint: str, documento: str | None, regra: str, motivo: str, remover_em: datetime | None)`. `remover_em` `None` = remover já. Data futura = só aviso até lá.
  - `do_acervo(fingerprints: list[str]) -> dict[str, str | None]`: fingerprint → documento, só os presentes em `cert_pfx_store`. Erro do banco levanta `CarteiraIndisponivel`.
  - `situacao_do_vinculo(user_id: str, machine_id: str, agora: datetime) -> tuple[str, datetime | None]`. Devolve `("carteira", None)`, `("vinculo", desde)` ou `("emprestimo", desde)`:
    - existe vínculo `ativo` em vigor ou `pendente` para o par: `"carteira"`;
    - senão, o vínculo mais recente do par está `recusado` (desde `decidido_em`) ou `encerrado` com motivo que começa com `"Desvinculado por"` (desde `encerrado_em`): `"vinculo"`;
    - encerrado com `"Prazo do empréstimo terminou."`: `"emprestimo"`, desde `expira_em`;
    - qualquer outro caso: `"carteira"`.
  - `motivo_da_saida(user_id: str, documento: str) -> str`: a última linha `saida` do histórico para o par, traduzida assim:
    - `prazo`: "prazo vencido";
    - `manual` ou `bloqueio`: "retirado por {feito_por_email}";
    - `acessorias`: "saiu no Acessórias";
    - `papel`: "mudou de papel";
    - `desativacao`: "conta desativada";
    - sem linha: "fora da carteira".
  - `decidir_pessoa(user: dict, machine_id: str, fingerprints: list[str], agora: datetime) -> list[Decisao]`. `user` traz `id`, `role` e `ativo`.
    - Conta inativa (`not conta_ativa(user)`): todo item do acervo com documento, regra `desativada`, motivo "conta desativada", `remover_em=None`.
    - Senão, pelo `situacao_do_vinculo`:
      - `vinculo` ou `emprestimo`: todo item do acervo com documento, `remover_em = desde + 7 dias`. Motivo "computador recusado ou desvinculado" ou "empréstimo do computador vencido";
      - `carteira`: os documentos fora de `documentos_ao_alcance`, regra `carteira`, motivo de `motivo_da_saida`, `remover_em=None`.
  - `decidir_sem_login(fingerprints: list[str]) -> list[Decisao]`: todo item do acervo com documento, regra `sem_login`, motivo "perfil sem login na bandeja", `remover_em=None`. O relógio é aplicado na Task 4.
  - `vencendo(user_id: str, hoje: date) -> list[dict]`: linhas `carteira` com `origem == "manual"` e `valido_ate` entre `hoje` e `hoje + 3 dias`, como `{documento, vence_em}`.
  - `agent_devices.dono_do_segredo(segredo: str) -> dict | None`: a linha de `agent_devices` pelo hash, **revogada ou não**. Sem carimbar `visto_em`; usa `compare_digest`.

- [ ] **Step 1:** testes, um por regra:
  - `test_admin_nao_perde_nada`;
  - `test_gestor_perde_so_excecao`;
  - `test_operador_perde_fora_da_carteira_com_motivo_do_historico`;
  - `test_documento_nulo_nunca_sai`;
  - `test_fora_do_acervo_nunca_aparece`;
  - `test_conta_desativada_tira_tudo_ja`;
  - `test_recusado_da_7_dias_contados_da_recusa`;
  - `test_desvinculado_da_7_dias`;
  - `test_aceito_de_novo_volta_a_carteira` (recusado antigo mais um vínculo ativo novo: `"carteira"`);
  - `test_emprestimo_vencido_conta_do_expira_em`;
  - `test_outra_maquina_segue_carteira` (encerrado com "A pessoa entrou em outra máquina.");
  - `test_carteira_indisponivel_propaga` (`decidir_pessoa` levanta, não devolve vazio);
  - `test_vencendo_so_manual_com_prazo_em_3_dias`;
  - `test_dono_do_segredo_acha_revogado`.
- [ ] **Step 2:** rodar. Esperado: FAIL.
- [ ] **Step 3:** implementar.
- [ ] **Step 4:** rodar. Esperado: PASS.
- [ ] **Step 5:** commit, `feat(remocao): decisao do portal por pessoa e por perfil sem login`.

### Task 4: Aplicar o modo e gravar o estado

**Files:**
- Modify: `app/remocao.py`
- Test: `tests/test_remocao_aplicar.py` (banco falso com a tabela `remocao_estacao` em memória)

**Interfaces:**
- Consumes: `Decisao`, `modo_carteira()` e `modo_sem_login()`.
- Produces:
  - `aplicar(machine_id: str, usuario_windows: str, user_id: str | None, decisoes: list[Decisao], modo: str, agora: datetime) -> dict`.
    - Devolve `{"remover": [{fingerprint, documento, motivo}], "avisos": [{fingerprint, documento, motivo, dias}]}`.
    - `modo == "desligado"`: devolve listas vazias e não grava nada.
    - `relatorio`: grava cada decisão com `estado='removeria'` e devolve listas vazias.
    - `ligado`:
      - a regra `sem_login` usa `aviso_desde`: o da linha existente com a mesma regra, ou `agora` se a linha é nova; então `remover_em = aviso_desde + 7 dias`;
      - `remover_em` maior que `agora`: `estado='aviso'` e item em `avisos` com `dias = ceil(dias restantes)`;
      - senão: `estado='remover'` e item em `remover`.
    - As linhas do par (`machine_id`, `usuario_windows`) que não estão nas decisões e não estão em `removido` ou `falhou` são apagadas. Assim o aviso some quando a situação se resolve.
    - Upsert por `(machine_id, usuario_windows, fingerprint)`, com `atualizado_em = agora`.
  - `registrar_resultado(machine_id: str, usuario_windows: str, user_id: str | None, user_email: str | None, resultados: list[dict]) -> None`.
    - Cada `{fingerprint, ok: bool, erro: str}` vira `estado='removido'` ou `'falhou'` (com o `detalhe`), mas só para linhas que estavam em `remover`.
    - Com `user_id`, `ok` grava `cert_installer.log_event("REMOVIDO", user_id, user_email, fingerprint=..., target_machine=machine_id, status="OK", detail=motivo)`.

- [ ] **Step 1:** testes:
  - `test_desligado_nao_grava_nem_devolve`;
  - `test_relatorio_grava_removeria_e_nao_manda_remover`;
  - `test_ligado_remove_ja_o_que_venceu`;
  - `test_sem_login_relogio_comeca_ao_ligar` (linhas `removeria` do relatório não contam como `aviso_desde`);
  - `test_sem_login_remove_no_oitavo_dia`;
  - `test_situacao_resolvida_apaga_aviso`;
  - `test_resultado_so_vale_para_o_que_foi_mandado`;
  - `test_removido_vai_a_trilha_com_motivo`.
- [ ] **Step 2:** rodar. Esperado: FAIL.
- [ ] **Step 3:** implementar.
- [ ] **Step 4:** rodar. Esperado: PASS.
- [ ] **Step 5:** commit, `feat(remocao): modo relatorio/ligado e estado por estacao`.

### Task 5: Rotas da conferência e do relatório

**Files:**
- Create: `app/rotas/remocao.py`
- Modify: `app/main.py` (incluir o router junto de `_rotas_atualizacao`)
- Test: `tests/test_remocao_rotas.py`

**Interfaces:**
- Consumes:
  - `_dispositivo_da_requisicao` de `app/rotas/computadores.py`;
  - o padrão `_limitar` e `computadores._maquina_provada`/`hash_da_chave`/`chave_fixada` de `app/rotas/atualizacao.py`;
  - as Tasks 3 e 4.
- Corpo comum, `Pydantic Conferencia`:
  - `usuario_windows: str (1..256)`;
  - `certificados: list[constr(pattern="^[0-9a-f]{64}$")]`, até 500;
  - `resultados: list[{fingerprint, ok: bool, erro: str (≤500)}]`, até 500, padrão `[]`.
- Produces:
  - `POST /api/estacao/conferencia`, com o dispositivo logado (`X-Device-Secret` ativo).
    1. Registra os `resultados`.
    2. Decide com `decidir_pessoa` e aplica com `modo_carteira()`.
    3. Acrescenta `vencendo` quando o modo é `ligado`.
    4. Resposta: `{remover, avisos, vencendo, proxima_em: 300}`.
  - `POST /api/estacao/conferencia/sem-conta`.
    - Corpo: `Conferencia` mais `machine_id (1..64)`, `chave (≤256, opcional)` e `segredo (≤256, opcional)`.
    - Teto `_limitar(request, "conferencia", (30, 600))`.
    - Se a máquina tem chave fixada, `hash_da_chave(chave)` tem de conferir; senão, 403 "Chave da máquina não confere.".
    - Com `segredo`: `dono_do_segredo` deve existir e ter `mac(machine_id)` igual; senão, 403. Depois `decidir_pessoa(dono)` com `modo_carteira()`. O dono vem de `users` (id, email, role, ativo).
    - Sem `segredo`: `decidir_sem_login` com `modo_sem_login()`.
    - Resposta igual à da rota logada, mas sem `vencendo`.
  - `GET /api/remocao`, só Admin (`require_admin`).
    - Filtros `estado` (opcional) e `pagina` (50 por página).
    - Devolve as linhas de `remocao_estacao` em ordem de `atualizado_em` decrescente, com o nome da pessoa e do titular, este por `cert_pfx_store.nome_titular`.
  - Nas duas rotas da estação, `CarteiraIndisponivel` ou qualquer exceção de leitura vira **503**, e nada é gravado.

- [ ] **Step 1:** testes:
  - `test_logado_recebe_remover_no_modo_ligado`;
  - `test_logado_relatorio_devolve_vazio`;
  - `test_sem_conta_chave_errada_403`;
  - `test_sem_conta_maquina_sem_chave_aceita`;
  - `test_segredo_revogado_de_outra_maquina_403`;
  - `test_segredo_revogado_so_remove_nao_instala` (com esse segredo, `GET /api/estacao/instalacoes` continua 401);
  - `test_banco_fora_503_e_nada_gravado`;
  - `test_fingerprint_malformado_422`;
  - `test_relatorio_so_admin`.
- [ ] **Step 2:** rodar. Esperado: FAIL.
- [ ] **Step 3:** implementar.
- [ ] **Step 4:** rodar. Esperado: PASS.
- [ ] **Step 5:** commit, `feat(remocao): rotas de conferencia da estacao e relatorio`.

### Task 6: Aba "Remoção" na Configuração

**Files:**
- Modify: `templates/configuracao.html`:
  - nova aba `?aba=remocao`, "Remoção nas estações", no `.ag-abas`, seguindo as abas que já existem;
  - a seção traz dois `<select>`, `#sel-remocao-carteira` e `#sel-remocao-sem-login`, com as opções Desligado, Só relatório e Ligado;
  - um Salvar, que manda só esses dois campos no `PUT /api/settings`;
  - a tabela do relatório.
- Create: `static/configuracao-remocao.js`:
  - carrega `GET /api/remocao`, com filtro por estado;
  - colunas Quando, Máquina, Usuário do Windows, Pessoa, Certificado, Regra, Motivo e Estado;
  - estados com rótulo: removeria = "Removeria (relatório)", aviso = "Em aviso", remover = "Remoção pendente", removido = "Removido", falhou = "Falhou".
- Test: `tests/test_pagina_configuracao_remocao.py`:
  - a aba existe;
  - os selects têm os três valores;
  - o JS é servido;
  - o Salvar da aba não manda outros campos.

  Seguir `tests/test_pagina_config_login.py` e `tests/test_js_dos_templates.py`.

- [ ] **Step 1:** testes.
- [ ] **Step 2:** rodar. Esperado: FAIL.
- [ ] **Step 3:** implementar, no Águia DS da tela (mesmas classes `.ag-*` das abas vizinhas).
- [ ] **Step 4:** rodar. Esperado: PASS.
- [ ] **Step 5:** commit, `feat(remocao): aba Remocao na Configuracao`.

### Task 7: Repositório do Windows na bandeja

**Files:**
- Create: `estacao/repositorio.py`
- Test: `tests/test_estacao_repositorio.py`, com um executor falso no lugar do PowerShell

**Interfaces:**
- Produces:
  - `@dataclass Item(sha256: str, thumbprint: str, nome: str)`.
  - `listar(executar=_powershell) -> list[Item]`.
    - Um PowerShell `-NoProfile -NonInteractive` lista `Cert:\CurrentUser\My` como JSON `[{Thumbprint, Subject, Raw: base64 de RawData}]`.
    - O SHA-256 é calculado em Python, com `hashlib.sha256(base64.b64decode(raw)).hexdigest()`.
    - Falha devolve `[]` e registra no log.
  - `remover(item: Item, executar=_powershell) -> tuple[bool, str]`.
    - Comando: `Remove-Item -LiteralPath "Cert:\CurrentUser\My\<thumb>" -DeleteKey -ErrorAction Stop`.
    - O thumbprint passa por `^[0-9A-F]{40}$` antes de entrar no comando; se não passar, devolve `(False, "thumbprint inválido")`.
  - `_powershell(script: str) -> subprocess.CompletedProcess` com `CREATE_NO_WINDOW` (como `instalador_certificado._importar`).

- [ ] **Step 1:** testes:
  - `test_listar_calcula_sha256_do_der`;
  - `test_listar_falha_devolve_vazio`;
  - `test_listar_um_item_so` (o PowerShell devolve objeto e não lista quando há um só);
  - `test_remover_monta_comando_com_delete_key`;
  - `test_remover_thumbprint_invalido_nao_executa`.
- [ ] **Step 2:** rodar. Esperado: FAIL.
- [ ] **Step 3:** implementar.
- [ ] **Step 4:** rodar. Esperado: PASS.
- [ ] **Step 5:** commit, `feat(estacao): listar e remover do CurrentUser\\My`.

### Task 8: Último dono, conferência e laço na bandeja (1.3.0)

**Files:**
- Modify: `estacao/conta.py`
  - `_get`: no 401 **ou 403**, chama `encerrar()` em vez de `apagar()` e levanta `SessaoEncerrada`.
  - `encerrar() -> None`: regrava o `conta.dat` com `"encerrada": True` (segredo, portal, e-mail e machine_id ficam).
  - `ler()` devolve `None` para conta encerrada. Assim `esta_conectado()`, `cabecalhos()` e a janela de status tratam a conta como desconectada.
  - Nova `ultimo_dono() -> dict | None`: a conta encerrada, ou `None`.
  - `guardar()` (login novo) sobrescreve, e isso já tira o `encerrada`.
  - `sair()` avisa o portal e chama `encerrar()` em vez de `apagar()`.
- Create: `estacao/conferencia.py`
  - `conferir(sessao, versao: str, avisar: Callable[[str], None], hoje: date, pendentes: list[dict]) -> list[dict]`.
  - Devolve os resultados das remoções desta rodada, para enviar na próxima.
  - Passos:
    1. `itens = repositorio.listar()`.
    2. Conectado: `POST {portal}/api/estacao/conferencia` com `cabecalhos(versao)`. Senão: `POST {portal}/api/estacao/conferencia/sem-conta` com `machine_id` (o do `ultimo_dono()`, ou `bandeja.machine_id()`), `chave=chave_maquina.ler()` e `segredo` do último dono, se houver. O portal é `portal_da_conta()`; o último dono guarda o dele.
    3. Resposta diferente de 200: não remove nada e devolve `pendentes`.
    4. Remove só os itens cujo `sha256` está em `remover` **e** em `itens`; o resto é ignorado.
    5. Avisa "Certificado {nome} removido: saiu da sua carteira." quando dá certo. Sem conta, o texto inclui que basta entrar na bandeja e pedir de novo no portal.
    6. `avisos` de `sem_login`: o texto do perfil sem login com o maior `dias`. Outros avisos: o texto com o motivo e os dias.
    7. `vencendo`: o texto de vencimento, no máximo uma vez por dia por documento. A data do último aviso fica em memória, num dict do módulo.
- Modify: `estacao/bandeja.py`
  - Nova constante `INTERVALO_CONFERENCIA = 300`.
  - O `laco` chama `conferir` na partida e depois quando passam 300 s desde a última, e guarda os resultados para a próxima rodada.
  - `verificar` deixa de tratar `SessaoEncerrada` como erro genérico (o 403 agora cai lá).
  - `_pronto` (login novo) dispara uma conferência também.
- Modify: `estacao/__init__.py`: `VERSAO = "1.3.0"`.
- Test:
  - `tests/test_estacao_conferencia.py`, com o repositório e o portal falsos (o `_Http` de `tests/test_estacao.py`).
  - `tests/test_estacao.py`: ajustar `test_situacao_instalacoes_e_sessao_encerrada` e `test_sair_avisa_o_portal_e_apaga`, que agora encerram em vez de apagar. Renomear o segundo para `test_sair_avisa_o_portal_e_encerra`.

- [ ] **Step 1:** testes:
  - `test_401_encerra_e_guarda_ultimo_dono`;
  - `test_403_tambem_encerra`;
  - `test_login_novo_substitui_ultimo_dono`;
  - `test_sair_vira_ultimo_dono`;
  - `test_conectado_usa_rota_logada`;
  - `test_ultimo_dono_manda_segredo_e_chave`;
  - `test_sem_conta_nem_dono_manda_so_chave`;
  - `test_so_remove_o_que_informou_e_ainda_existe`;
  - `test_portal_fora_nao_remove_e_guarda_pendentes`;
  - `test_resultado_vai_na_proxima_rodada`;
  - `test_aviso_de_vencimento_uma_vez_por_dia`;
  - `test_versao_1_3_0`.
- [ ] **Step 2:** rodar. Esperado: FAIL.
- [ ] **Step 3:** implementar.
- [ ] **Step 4:** rodar `pytest tests/test_estacao*.py -v`. Esperado: PASS.
- [ ] **Step 5:** suíte inteira, `pytest -q`. Esperado: verde, com os skips de sempre.
- [ ] **Step 6:** commit, `feat(estacao): ultimo dono e conferencia de remocao (1.3.0)`.

---

## Depois do plano (fora das tasks, com o usuário)

1. PR, revisão final e deploy do portal: a migration vai pelo `atualizar-portal`. Com as chaves vazias, tudo fica em `relatorio`.
2. Publicar a bandeja 1.3.0 pela atualização automática. O rollout é do usuário.
3. Uma ou duas semanas de relatório na aba Remoção. O usuário confere e liga a chave da carteira; a do perfil sem login vem depois.
