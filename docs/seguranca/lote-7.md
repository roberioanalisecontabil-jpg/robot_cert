# Lote 7 — Agente Windows (#18, #39, #43, #44, #45, #46)

Fonte: `SECURITY_AUDIT.md` (auditoria de 24/09/2026). Branch `seguranca/lote-7`, empilhado sobre `seguranca/lote-6`. **Exige nova versão do agente: 1.4.0.**

Método: os 24 testes de `tests/test_seguranca_lote7.py` foram escritos antes da correção e rodados contra `7232219` (fim do lote 6): **18 falharam e 6 erraram** (módulo `agent.chave_api` e funções que ainda não existiam), 0 passaram. Depois das correções os 24 passam, e a suíte inteira fecha verde: **1290 passam, 9 pulados, 0 falhas em 1 min 27** (`pytest`, 25/09/2026). O DPAPI e o `icacls` são substituídos nos testes: a suíte roda em qualquer máquina e prova o fluxo, não o Windows. Um teste antigo (`tests/test_instalacao_pfx.py`) descrevia a chamada ao `certutil` e foi adaptado ao PowerShell; as garantias que ele fixava (PFX temporário zerado e apagado, inclusive no erro e no timeout) continuam todas.

## Achados tratados

| # | Achado | O que mudou |
|---|---|---|
| 18 | X-API-Key em claro em `agent_config.json`, na pasta do programa, legível por qualquer usuário da estação | Novo `agent/chave_api.py`: a chave mora em `%ProgramData%\Analise CertiDigital Agent\chave_api.dat`, cifrada com DPAPI de escopo **máquina** e ACL só para SYSTEM e Administradores — o mesmo maquinário de `maquina.dat` (`identidade_maquina.proteger`/`_aplicar_acl`). Sem ACL não fica arquivo. Ordem de resolução (`chave_api.resolver`): variável de ambiente do serviço `CERT_ROBOT_API_KEY` → cofre → JSON antigo, que é **migrado** (chave vai para o cofre, JSON reescrito sem ela, WARNING no log). Entrada pelo instalador: página nova do assistente pede a chave, grava em `{tmp}\chave.txt` e chama `AnaliseCertiDigital_Agent.exe --guardar-chave <arquivo>`; o agente cifra, restringe, zera e apaga o arquivo. A chave não passa pela linha de comando. `agent_config.example.json` não tem mais o campo. |
| 46 | A tela de Configuração guardava a X-API-Key no `localStorage` do navegador (sob a mesma chave do JWT) e a embutia no `agent_config.json` baixado | Aba "Chave API" sem campo nem botão "Guardar no navegador": explica que a chave é credencial de **estação** e como entra (instalador / `--guardar-chave`). O arquivo baixado vai sem `cert_robot_api_key`. Nenhum `localStorage.setItem` da chave na tela; só o login grava o JWT. Textos de 401 falam de sessão, não de chave. |
| 39 | O cliente HTTP do agente seguia redirect para outro host levando a X-API-Key; `base_url` aceitava `http://` | `run_agent._novo_http_client(base_url)` ganha hook de requisição que **remove `X-API-Key` quando o host da requisição difere do host do portal** (o httpx só faz isso com `Authorization`); mesmo host com troca http→https mantém. `normalizar_base_url` reescreve `http://` para `https://` fora de `localhost`/`127.0.0.1`/`::1`, com WARNING — a primeira requisição não sai mais em claro com a chave à espera do 308. |
| 43 | Senha do PFX na linha de comando do `certutil -p`, visível na tabela de processos (`wmic process get CommandLine`, Sysmon, EDR) | `installer_client._import_pfx_non_exportable` usa `powershell.exe -Command -` com o script pelo **stdin**: `Import-PfxCertificate -FilePath … -CertStoreLocation Cert:\CurrentUser\My -Password (SecureString)` **sem `-Exportable`** (equivalente ao `NoExport`). Senha e caminho vão entre aspas simples com `'` duplicado. PFX sem senha não passa `-Password`. Mensagem de erro "Importação falhou: …". |
| 44 | O agente logava o token de instalação inteiro | `process_install_command` loga só `token[:8]…` em todos os pontos (o WARNING de bundle vazio ainda levava o token completo). |
| 45 | O instalador dava `users-modify` na pasta inteira que guarda `maquina.dat` (Modify inclui "excluir subpastas e arquivos", que passa por cima da ACL própria do `.dat`) | `[Dirs]`: a raiz `{commonappdata}\Analise CertiDigital Agent` fica sem `Permissions`; a **subpasta `pedidos`** é a única com `users-modify`, e `_command_file_path()` passa a `…\pedidos\agent_command.json`. Na atualização de uma 1.3.0 o Inno não retira a ACE antiga, então `RestringirPastaDaCredencial` roda `icacls … /remove:g *S-1-5-32-545` na raiz (só a ACE explícita de Users; a leitura herdada do ProgramData fica, é o que o tray precisa para `agent_status.json`). |

## Arquivos alterados

- `agent/chave_api.py` — novo: `caminho`, `guardar`, `ler`, `apagar`, `migrar_de_config`, `resolver`.
- `agent/run_agent.py` — `normalizar_base_url`, `guardar_chave_de_arquivo`, `--guardar-chave`, `_arquivo_de_config`/`_candidatos_de_config`, `_sem_credencial_fora_do_host`, `_novo_http_client(base_url)`, `_command_file_path` em `pedidos`; `run_agent_application` usa `chave_api.resolver`.
- `agent/installer_client.py` — `_script_de_importacao`; `_import_pfx_non_exportable` via PowerShell/stdin; token abreviado no log.
- `agent/__init__.py` (`1.4.0`), `app/config.py` (`VERSAO_AGENTE_ESPERADA = "1.4.0"`), `agent_setup.iss` (`AppVersion=1.4.0`, `[Dirs]`, `ApiKeyPage`, `GuardarChaveDeApi`, `RestringirPastaDaCredencial`).
- `agent/agent_config.example.json` — sem `cert_robot_api_key`.
- `templates/configuracao.html` — aba Chave API informativa; download sem chave; sem `localStorage` da chave.
- Testes: `tests/test_seguranca_lote7.py` (novo); `tests/test_instalacao_pfx.py` (adaptado ao PowerShell).

## Testes criados (`tests/test_seguranca_lote7.py`)

| Teste | O que prova |
|---|---|
| `test_chave_guardada_cifrada_e_com_acl` | O arquivo não contém a chave em claro; `_aplicar_acl` foi chamado no caminho certo; `ler()` devolve a chave. |
| `test_sem_acl_nao_fica_arquivo_legivel` | ACL falhou → arquivo apagado e `SemCofreLocal` sobe. |
| `test_config_antiga_migra_a_chave_e_reescreve_o_json_sem_ela` | `cert_robot_api_key` no JSON → chave no cofre, JSON reescrito sem o campo (outros campos intactos), WARNING "migrad…". |
| `test_ordem_de_resolucao_da_chave` | Cofre vale; `CERT_ROBOT_API_KEY` do serviço vence o cofre. |
| `test_sem_chave_em_lugar_nenhum_devolve_vazio` | Sem chave → `""`, sem exceção. |
| `test_guardar_chave_de_arquivo_consome_o_arquivo` | `--guardar-chave`: chave (com espaços) vai ao cofre e o arquivo em claro some. |
| `test_cli_aceita_guardar_chave`, `test_run_agent_nao_le_mais_a_chave_direto_do_json`, `test_exemplo_de_config_nao_tem_mais_a_chave` | Superfície do agente sem o campo antigo. |
| `test_tela_nao_guarda_chave_no_navegador_nem_no_arquivo_baixado` | Sem `btn-save-key`, `id="api-key"`, `cert_robot_api_key`, `localStorage.setItem(KEY_STORAGE`; a tela ensina `--guardar-chave`. |
| `test_redirect_para_outro_host_nao_leva_a_x_api_key` | 302 para `outro.exemplo` chega **sem** a chave. |
| `test_redirect_no_mesmo_host_mantem_a_chave` | 308 http→https no mesmo host mantém a chave. |
| `test_base_url_so_https_fora_da_propria_maquina` (×5) | `http://certificado…` → `https://` com aviso; `127.0.0.1`/`localhost` ficam em http; barra final removida. |
| `test_senha_nao_vai_na_linha_de_comando` | `certutil` ausente; senha ausente do `cmd`; presente no stdin com `'` duplicado; `Cert:\CurrentUser\My`; sem `-Exportable`. |
| `test_pfx_temporario_some_depois_da_importacao` | O PFX existe durante a chamada e não depois. |
| `test_token_de_instalacao_nao_vai_inteiro_para_o_log` | Só o prefixo do token no log. |
| `test_instalador_nao_da_escrita_a_usuarios_na_pasta_da_credencial`, `test_pedido_do_tray_vai_para_a_subpasta`, `test_instalador_guarda_a_chave_pelo_agente` | `[Dirs]` raiz sem `users-modify`, `pedidos` com; `_command_file_path().parent.name == "pedidos"`; `.iss` chama `--guardar-chave` e não menciona `cert_robot_api_key`. |
| `test_versao_do_agente_subiu` | `agent.__version__` e `VERSAO_AGENTE_ESPERADA` em 1.4.0 (e `test_versao_agente.py` confere o `AppVersion` do `.iss`). |

## Janela de compatibilidade

| Mudança | Quem afeta | Janela |
|---|---|---|
| Chave fora do JSON | Estação atualizada para 1.4.0 com `agent_config.json` antigo: a chave é **migrada** para o cofre na primeira subida (WARNING no log) e o JSON é reescrito sem ela. Nada para. Estação nova: a chave entra pelo instalador (página "Chave de API do portal"); em branco, mantém a que já houver no cofre. | Migração automática; sem flag. A variável `CERT_ROBOT_API_KEY` do serviço continua valendo e tem prioridade. |
| Agente 1.3.0 ainda instalado | Continua lendo a chave do JSON e falando com o portal como hoje; o portal acusa "versão atrasada" (`VERSAO_AGENTE_ESPERADA = 1.4.0`). O `agent_command.json` dele fica na raiz e o serviço 1.3.0 lê da raiz — coerente enquanto os dois lados forem 1.3.0. O instalador troca serviço e tray juntos. | Coexistência natural: a frota é atualizada estação a estação, sem passo no servidor. |
| `http://` no `cert_robot_base_url` | Reescrito para `https://` fora da própria máquina, com WARNING. Portal em produção está em HTTPS (Caddy); quem ainda tiver `http://certificado…` no JSON passa a funcionar sem a primeira requisição em claro. Dev local (`127.0.0.1:8020`) inalterado. | Sem flag: o `http://` só chegava ao 308. |
| Redirect para outro host | Nenhum consumidor legítimo: o portal só redireciona http→https no mesmo host. | — |
| `Import-PfxCertificate` no lugar do `certutil` | Exige o módulo PKI do PowerShell (padrão do Windows 8.1/2012 R2 em diante). Comportamento na duplicata muda: o cmdlet substitui o certificado de mesma impressão digital em vez do `-f` do certutil — mesmo resultado prático. **Conferir numa estação real** que a chave importada aparece como não exportável (`certutil -store -user My`). | — |
| `pedidos\agent_command.json` | Só o tray e o serviço da mesma versão trocam esse arquivo. Um pedido pendente na raiz no momento da atualização é perdido (é um "força leitura", reenviável). | — |
| ACL da raiz | Na atualização, a ACE explícita de Users sai da raiz; `agent_status.json` continua legível pelo tray pela herança do ProgramData. Se algum tray não conseguir ler o estado, o log do instalador tem o código do `icacls`. | — |

Nenhuma migração de dados no servidor.

## Pendente e por quê

- **Gerar e distribuir o instalador 1.4.0** (Inno Setup, `agent_setup.iss`) e instalar no ANALISESRV e nas estações. Até lá o portal acusa a frota como atrasada, que é o comportamento desejado.
- **Validação numa estação real**: página do instalador, `--guardar-chave` como administrador, migração de um JSON antigo, importação de um PFX de teste como não exportável, e o tray lendo `agent_status.json` depois do `icacls`. O DPAPI e o `icacls` estão substituídos na suíte.
- **Conta de serviço personalizada** (página "Conta do serviço" do instalador): `maquina.dat` e agora `chave_api.dat` têm ACL só para SYSTEM e Administradores; um serviço rodando com outra conta não os lê. Pré-existente no `maquina.dat`, fora do escopo deste lote; hoje o serviço roda como LocalSystem.
- **Fase 0**: rotacionar a `API_KEY` continua sendo ação humana; este lote só muda onde ela é guardada nas estações.

## Achados novos

- `templates/login.html` grava o JWT em `localStorage` sob o nome `cert_robot_api_key` (`KEY_STORAGE`). É só o nome da chave de armazenamento, mas confunde a leitura e foi o que levou a tela de Configuração a gravar a X-API-Key no mesmo lugar (#46). Renomear exige migrar o valor no navegador de quem já está logado; fica para o lote 9.
- O Inno Setup **não remove** ACEs de versões anteriores quando `Permissions` sai de uma linha de `[Dirs]`; sem o `icacls` explícito o #45 ficaria fechado só em instalação nova. Vale para qualquer futura mudança de ACL no `.iss`.
- Provisionamento em pasta onde um usuário local já criou um `maquina.dat` (herança padrão do ProgramData permite criar arquivos): o `write_bytes` do serviço falharia com PermissionError e ficaria no log; não há troca silenciosa, mas também não há mensagem dedicada. Anotado, não tratado.
