# Identidade da estação pela chave da máquina — plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fazer o `machine_id` de uma estação ficar o mesmo para sempre, mesmo que surja ou mude um adaptador de rede (WSL, Hyper-V, VPN, placa nova).

**Architecture:**
- **O problema.** O `machine_id` é o primeiro MAC em ordem alfabética, recalculado a cada uso. Um adaptador novo passa à frente, a máquina vira outra para o portal, e o portal responde 403 "Chave da máquina não confere". Na TI-002, em 20/11/2026, o `vEthernet (WSL)` (`00:15:5d:6d:93:6f`) passou à frente do `00:ff:fd:03:61:24`.
- **Na estação.** O `machine_id` passa a ser fixado num arquivo em `ProgramData`, ao lado da chave, e lido de lá.
- **No portal.** Quem diz qual `machine_id` fixar é o portal, por uma rota nova: a estação mostra a chave e o portal devolve o `machine_id` a que aquela chave está fixada.
- **O que não muda.** O portal continua usando `machine_id` em todo lugar: vínculos, histórico, remoção e uso, em 27 arquivos. Nenhuma tabela muda.

**Tech Stack:** Python 3, FastAPI e pydantic (portal); PostgreSQL via `app/db_pg.py`; `httpx` (estação); PyInstaller e Inno Setup.

**Spec:** não há documento de design. As decisões foram tomadas no chat de 20/11/2026 e estão em "Decisões" abaixo.

## Decisões (chat de 20/11/2026)

- **Nenhum MAC serve de identidade, nem um MAC "escolhido".** Na troca de placa, ele também muda (observação do Robério). A identidade é a chave da máquina (`chave_maquina`), que já existe, não sai da máquina e já é conferida pelo portal.
- **O `machine_id` gravado é só cache da resposta do portal.**
  - Se o portal conhece a chave, a resposta dele vence o arquivo.
  - Se o portal não conhece a chave (404), vale o arquivo.
  - Sem arquivo, vale o cálculo antigo do MAC, que é então gravado.
- **Windows reinstalado** gera chave nova, e a máquina pede aprovação de novo. Esse é o comportamento certo.
- **Máquina sem chave fixada no portal** (TI-135, TI-017, TI-019 e TI-001: vínculos de 08–09/10, anteriores à chave) continua precisando de uma nova aprovação. O plano não resolve isso.

## Global Constraints

- Arquivo: `%ProgramData%\CertguardAnalise\machine_id.txt`, em `caminhos.pasta_maquina()`. Não fica na pasta trancada, porque a bandeja roda como a pessoa e precisa ler.
- Conteúdo: um MAC em minúsculas, no formato `^[0-9a-f]{2}(:[0-9a-f]{2}){5}$`. Qualquer outro conteúdo é ignorado e vale o cálculo antigo.
- Quem grava: só o instalador (`--preparar-chave`, administrador) e a tarefa SYSTEM (`--atualizacao`). A bandeja só lê.
- Rota nova: `POST /api/estacao/identidade`, corpo `{"chave": str}`.
  - 200 `{"machine_id": "<mac>"}` quando a chave está fixada.
  - 404 quando não está, e 422 quando a chave vem fora do formato (`hash_da_chave` devolve None).
  - Limite: `_limitar(request, "identidade", (30, 600))`.
- Duas linhas de `maquina_chave` com o mesmo `chave_hash`: vale a de `fixada_em` mais recente.
- Versão da estação: `1.5.3`. Ordem de entrega: portal primeiro, estação depois.
- Cada mudança no servidor e cada publicação da estação só com autorização do Robério no chat, a cada vez.
- Commit: a correção e o `git commit -F` vão em comandos separados, porque o hook de pré-commit roda a suíte.

## Review Focus

1. **Arquivo plantado por quem não é administrador.** Em `ProgramData`, um usuário comum pode criar o arquivo antes do SYSTEM. Com o portal no ar, a tarefa sobrescreve o arquivo com a resposta do portal. Teste: `test_portal_vence_o_arquivo` (Task 2).
2. **Portal fora do ar na instalação.** O `--preparar-chave` não pode falhar nem travar a instalação. Sem resposta do portal, grava o cálculo antigo só se ainda não houver arquivo. Teste: `test_portal_fora_mantem_o_arquivo` (Task 2).
3. **Chave que o portal não conhece (404) com arquivo já gravado.** Mantém o arquivo; não volta para o cálculo antigo. Teste: `test_404_mantem_o_arquivo` (Task 2).
4. **Arquivo corrompido ou vazio** (`""`, `"lixo"`, MAC em maiúsculas com `-`). A leitura cai no cálculo antigo e não estoura. Teste: `test_arquivo_invalido_cai_no_mac` (Task 2).
5. **Mesma chave fixada em dois `machine_id`.** Vale o de `fixada_em` mais recente. Teste: `test_chave_em_duas_maquinas_vale_a_mais_recente` (Task 1).

---

### Task 1: Portal — de quem é esta chave

**Files:**
- Modify: `app/computadores.py` (perto de `chave_fixada`, `:249`)
- Modify: `app/rotas/uso_estacao.py` (rota nova, abaixo de `registrar`)
- Test: `tests/test_identidade_rotas.py` (novo; reusa `client`, `banco`, `_chave`, `PC_SOL`, `PC_FIS` de `tests/test_computadores_rotas.py` e `_fixar` de `tests/test_remocao_rotas.py`, como `tests/test_uso_rotas.py` faz)

**Interfaces:**
- Produces: `computadores.maquina_da_chave(chave_hash: str) -> Optional[str]`, o `machine_id` (via `mac()`) da linha de `maquina_chave` com esse `chave_hash` e o `fixada_em` mais recente, ou None.
- Produces: `POST /api/estacao/identidade`, conforme os Global Constraints.

- [ ] **Step 1: Escrever os testes que falham**

```python
def test_identidade_devolve_a_maquina_da_chave(client, banco):
    _fixar(banco, PC_SOL)
    r = client.post("/api/estacao/identidade", json={"chave": _chave(PC_SOL)})
    assert r.status_code == 200 and r.json() == {"machine_id": PC_SOL}

def test_identidade_chave_desconhecida_404(client, banco):
    r = client.post("/api/estacao/identidade", json={"chave": "x" * 43})
    assert r.status_code == 404

def test_identidade_chave_fora_do_formato_422(client, banco):
    assert client.post("/api/estacao/identidade", json={"chave": "curta"}).status_code == 422

def test_chave_em_duas_maquinas_vale_a_mais_recente(banco):
    # duas linhas com o mesmo chave_hash; fixada_em 2026-10-01 (PC_FIS) e 2026-11-01 (PC_SOL)
    assert computadores.maquina_da_chave(h) == PC_SOL
```

- [ ] **Step 2: Rodar** `pytest tests/test_identidade_rotas.py -v`. Esperado: FAIL (404 da rota inexistente e `maquina_da_chave` não definida).
- [ ] **Step 3: Implementar `maquina_da_chave` e a rota.** Ler com `.select("machine_id, fixada_em").eq("chave_hash", h)` e ordenar em Python, porque o `_Fake` dos testes pode não ter `order`. Banco fora: 503 `_FORA`, como em `registrar`. A rota nunca devolve o hash nem outra coisa além do `machine_id`.
- [ ] **Step 4: Rodar de novo** e também `pytest tests/test_uso_rotas.py tests/test_computadores_rotas.py -q`. Esperado: PASS.
- [ ] **Step 5: Commit** — `feat(portal): rota de identidade da estacao pela chave da maquina`.

### Task 2: Estação — `machine_id` fixado

**Files:**
- Create: `estacao/identidade.py`
- Modify: `estacao/bandeja.py:43-61`: `machine_id()` passa a devolver `identidade.machine_id()`. O cálculo antigo se muda para `identidade.mac_calculado()`, com a docstring sobre o Hardlyze junto.
- Test: `tests/test_estacao_identidade.py` (novo)

**Interfaces:**
- Consumes: `POST /api/estacao/identidade` (Task 1); `chave_maquina.ler() -> str | None`; `tarefa.portal() -> str`.
- Produces:
  - `identidade.ARQUIVO = "machine_id.txt"` e `identidade.caminho() -> Path`.
  - `identidade.mac_calculado() -> str`: o cálculo de hoje, sem mudar nada.
  - `identidade.machine_id() -> str`: o arquivo, se válido; senão `mac_calculado()`.
  - `identidade.fixar(http) -> str`: pergunta ao portal e grava conforme as Decisões. Devolve o `machine_id` em vigor e nunca levanta exceção (erros vão para o log).
  - `bandeja.machine_id()` continua existindo, porque os testes de `uso` e `conferencia` o substituem com `monkeypatch`.

- [ ] **Step 1: Escrever os testes que falham.** Use `monkeypatch` em `caminhos.pasta_maquina` (com `tmp_path`), em `chave_maquina.ler` e em `identidade.mac_calculado` (devolvendo `"00:15:5d:6d:93:6f"`), mais um `_Http` falso com `post` como em `tests/test_estacao_uso.py`.

```python
def test_portal_vence_o_arquivo(...):          # arquivo "aa:aa:aa:aa:aa:aa", portal 200 "00:ff:fd:03:61:24"
    assert identidade.fixar(http) == "00:ff:fd:03:61:24" == identidade.machine_id()
def test_404_mantem_o_arquivo(...):            # arquivo "aa:aa:...", portal 404 -> continua "aa:aa:..."
def test_404_sem_arquivo_grava_o_mac(...):     # sem arquivo, 404 -> grava e devolve "00:15:5d:6d:93:6f"
def test_portal_fora_mantem_o_arquivo(...):    # post levanta ConnectError -> arquivo intacto, sem exceção
def test_portal_fora_sem_arquivo_grava_o_mac(...)
def test_sem_chave_nao_pergunta_ao_portal(...): # chave_maquina.ler() None -> http.posts == []
def test_arquivo_invalido_cai_no_mac(...):     # "", "lixo", "00-FF-FD-03-61-24" -> mac_calculado()
def test_bandeja_usa_a_identidade(...):        # bandeja.machine_id() == identidade.machine_id()
```

- [ ] **Step 2: Rodar** `pytest tests/test_estacao_identidade.py -v`. Esperado: FAIL (módulo inexistente).
- [ ] **Step 3: Implementar `estacao/identidade.py`.** Gravar por arquivo temporário mais `os.replace`, para que a bandeja nunca leia um arquivo pela metade. Um 200 cujo `machine_id` não casa com o formato é tratado como portal fora.
- [ ] **Step 4: Rodar de novo**, mais `pytest tests/test_estacao.py tests/test_estacao_uso.py tests/test_estacao_conferencia.py -q`. Esperado: PASS.
- [ ] **Step 5: Commit** — `feat(estacao): machine_id fixado pela chave da maquina`.

### Task 3: Quem fixa, e a versão 1.5.3

**Files:**
- Modify: `estacao/__main__.py` (`_preparar_chave`): depois de `chave_maquina.preparar()`, `identidade.fixar(http)` com `tarefa._cliente()`, protegido por `try`. Uma falha só vai ao log e o código de saída continua 0.
- Modify: `estacao/tarefa.py` (`rodar_tarefa`): logo depois de `religar_vigia()`, dentro do `with _cliente() as http`, chamar `identidade.fixar(http)` antes da coleta. Isso vale também fora de estação: o servidor também tem `machine_id`.
- Modify: versão `1.5.3` em `estacao/__init__.py`, `estacao_setup.iss` e nas três asserções de versão dos testes (`tests/test_estacao_atualizacao_automatica.py`, `tests/test_estacao_conferencia.py`, `tests/test_janela_login.py`).
- Test: `tests/test_estacao_uso.py`, com o mesmo estilo dos testes da fixture `rodada`.

**Interfaces:**
- Consumes: `identidade.fixar(http) -> str` (Task 2).

- [ ] **Step 1: Escrever o teste que falha** — `test_tarefa_fixa_a_identidade_antes_da_coleta`: com `monkeypatch` em `identidade.fixar`, `uso.coletar` e `tarefa.buscar_pacote` anotando em `rodada`, conferir `rodada == ["fixar", "coletar", "buscar"]`.
- [ ] **Step 2: Rodar.** Esperado: FAIL.
- [ ] **Step 3: Implementar** nos dois pontos acima e subir a versão.
- [ ] **Step 4: Rodar** os testes da estação (a lista do `scripts/build_estacao.ps1`, mais `tests/test_estacao_uso.py` e `tests/test_estacao_bandeja_protegida.py`). Esperado: PASS.
- [ ] **Step 5: Commit** — `feat(estacao): Certguard Analise 1.5.3 fixa o machine_id`.

### Task 4: Entrega (com o Robério)

- [ ] **Step 1:** PR e merge das Tasks 1 a 3; deploy do portal (`atualizar-portal.ps1 -Portal robot_cert`), **com autorização do Robério**. Conferir com `POST /api/estacao/identidade` usando uma chave inválida: esperado 422.
- [ ] **Step 2:** `scripts\build_estacao.ps1` gera a 1.5.3. O Robério instala na TI-002.
- [ ] **Step 3:** Conferir na TI-002:
  - `C:\ProgramData\CertguardAnalise\machine_id.txt` = `00:ff:fd:03:61:24`, mesmo com o WSL ligado;
  - `vigia.log` sem 403 na coleta seguinte;
  - o uso chegando ao portal.
- [ ] **Step 4:** O Robério publica (`deploy\lancar-certguard.ps1 -Publicar`, no PowerShell dele). Conferir o `vigente.json`, o sha e o download pelo portal. Registrar no plano e na memória.
