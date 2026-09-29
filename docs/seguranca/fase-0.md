# Fase 0 — ações humanas da auditoria de 24/09/2026

Estas ações não entram em lote nenhum porque envolvem segredo real, terceiros ou
reescrita do repositório. Nenhuma foi feita pelos lotes 1 a 9. Ordem sugerida
abaixo; cada passo diz o que prova que terminou.

## 1. Revogar o certificado cujo `.p12` está no histórico (#1)

O commit `3175a05` (23/04/2026) adicionou `certificados/AUTO POSTO ALVES DA
SILVA LTDA_18990675000190 SENHA123456.p12`; o nome do arquivo traz a senha.
Apagar do histórico (passo 2) não desfaz o que já foi clonado ou visto: o
certificado tem de ser **revogado na AC** que o emitiu e reemitido para o
cliente. Isso é com o titular e a AC, não com o repositório.

Prova: número de série revogado na LCR/OCSP da AC; certificado novo no
inventário do portal com fingerprint diferente.

## 2. Tirar o `.p12` do histórico (`git filter-repo`)

Reescreve TODOS os commits; quem tiver clone precisa clonar de novo. O clone do
servidor não sofre: o `atualizacao_push.ps1` faz `reset --hard origin/main`.

```powershell
# 1. Clone limpo, só para a reescrita (o filter-repo recusa um clone com trabalho local)
cd C:\Users\Roberio\Desktop
git clone --mirror https://github.com/roberioanalisecontabil-jpg/robot_cert.git robot_cert-reescrita.git
cd robot_cert-reescrita.git

# 2. Remover o arquivo de todos os commits (o venv do projeto tem o git-filter-repo)
C:\Users\Roberio\projetos_PY\robot_cert\.venv\Scripts\git-filter-repo.exe --invert-paths --path "certificados/AUTO POSTO ALVES DA SILVA LTDA_18990675000190 SENHA123456.p12"

# 3. Conferir: nada com .p12 em commit nenhum
git log --all --diff-filter=A --name-only --format="%h" -- "*.p12"     # esperado: vazio

# 4. Publicar por cima (força) — branches e tags
git push --force --all
git push --force --tags

# 5. No GitHub: Settings > Danger zone nao apaga blobs soltos; abra um pedido ao
#    suporte ("remove cached views / dangling commits of 3175a05") ou aceite que
#    o blob pode continuar acessivel por hash ate o GC deles. Por isso o passo 1
#    (revogacao) vem ANTES e nao depende deste.

# 6. Clones locais: apagar e clonar de novo (ou `git fetch` + `git reset --hard origin/main`
#    em cada branch). Os branches seguranca/lote-N ja estao em main; podem ser apagados.
```

Prova: o comando do passo 3 vazio no GitHub (clone novo) e no servidor.

## 3. Rotacionar `API_KEY` (#18, #46)

A chave compartilhada esteve em claro no `agent_config.json` de toda estação
e no navegador de quem usou a tela de Configuração. Com o agente 1.4.x ela só
serve para provisionar credencial de máquina — e o ANALISESRV já tem a sua.

```powershell
# No servidor, gerar a chave nova (não escreva a chave em chat nem em arquivo do repositório)
C:\Apps\robot_cert\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(32))"
# Editar C:\Apps\robot_cert\.env  ->  API_KEY=<valor novo>
Restart-Service certguard
```

Na estação (só o ANALISESRV roda este agente): a credencial de máquina
continua valendo; a chave nova só precisa entrar no cofre local se um dia o
agente tiver de reprovisionar. Grave-a num arquivo temporário e rode, como
administrador:

```powershell
& "C:\Program Files\Analise CertiDigital Agent\AnaliseCertiDigital_Agent.exe" --guardar-chave C:\Temp\chave.txt
```

Prova: `POST /api/ingest` com a chave antiga responde 401; o agente segue
enviando (ele usa a credencial de máquina, não a chave).

## 4. Rotacionar `JWT_SECRET_KEY` (#23)

Todo mundo é deslogado uma vez; nada mais.

```powershell
C:\Apps\robot_cert\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(48))"
# Editar C:\Apps\robot_cert\.env  ->  JWT_SECRET_KEY=<valor novo>
Restart-Service certguard
```

Prova: sessões abertas caem no login; login novo funciona.

## 5. Remover `SUPABASE_SERVICE_KEY` do `.env` local desta estação

O portal não usa mais o Supabase. A chave no `.env` de desenvolvimento só
serve para vazar. Apague a linha; se a organização do Supabase ainda existir,
revogue a chave lá.

## 6. Confirmar no portal

Depois de tudo: Instalador → Diagnóstico (cofre e chaves em ordem), Início
com o inventário atualizado, e `verificar_ambiente` sem fatais no `erro.log`.
