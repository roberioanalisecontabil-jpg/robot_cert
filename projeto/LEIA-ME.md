# CertGuard Análise (repositório robot_cert) — LEIA-ME

Contexto para uma nova sessão de IA retomar o sistema. Factual; o que não foi confirmado está marcado `A confirmar:`.

## O que é

Portal web que inventaria os certificados digitais (PFX/P12) de clientes da Análise Group guardados no servidor, mostra validade e histórico, alerta vencimentos e instala o certificado certo na estação da pessoa certa. Nomes já usados: "Robot Cert", "Analise CertiDigital" e, desde 23/10/2026, **CertGuard Análise** (só o nome visível mudou; os identificadores internos continuam `robot_cert`, `certguard`, `AnaliseCertiDigital`).

Peças do sistema:
- **Portal** (FastAPI, `app/`, `templates/`, `static/`): painel, carteiras, acompanhamento, histórico, configuração, usuários, wiki.
- **Agente do servidor** (`agent/`): roda no servidor dos portais, varre a pasta de certificados, processa a Entrada e envia ao portal.
- **Bandeja das estações** (`estacao/`, instalador `estacao_setup.iss`): programa por estação, login (inclusive Microsoft), instalação do certificado, atualização automática.

## Usuários

Time de contabilidade/legalização da Análise Group (Operador, Gestor, Administrador) e o TIC. Líder de negócio e líder técnico na IA First: Roberio França.

## Onde roda

- URL: https://certificado.analisegroup.cnt.br (rede interna e internet, atrás da Cloudflare).
- Servidor: 10.200.0.4 (hostname DEVANALISE). Atenção: o nome ANALISESRV resolve para 10.200.0.2, que é OUTRA máquina.
- Serviço NSSM `certguard`, porta 8020 em loopback; Caddy na frente (80/443 e 2053 para a Cloudflare). Arquivo versionado: `deploy/Caddyfile`.
- Banco: PostgreSQL 17, porta 5433, banco `certguard`. Sem Supabase desde 05–07/09/2026 (módulo próprio `app/db_pg.py`).
- Pasta no servidor: `C:\Apps\robot_cert`.

## Repositório

- `C:\Users\Roberio\projetos_PY\robot_cert`, ramo `main`, remoto no GitHub (conta do Robério).
- Último commit lido em 11/11/2026: `5fb4154` (07/11/2026). Em produção confirmado pelas memórias: `518b217` (06/11/2026). `A confirmar:` se 5fb4154 já foi para o servidor (conferir com `git -C C:\Apps\robot_cert log --oneline -1`).
- Havia alterações não commitadas em `static/aguia-dashboard.css` e `templates/dashboard.html` em 11/11/2026.
- Suíte de testes: pytest, 2049 testes em 04/11/2026; hook de pré-commit roda a suíte.

## Como atualizar

1. Commit e push na `main` (o Claude pode fazer o push com autorização do Robério no chat).
2. No servidor: `C:\Apps\deploy\atualizar-portal.ps1 -Portal robot_cert`. Ele roda `db/aplicar_schema.py` (migrations) e reinicia o serviço.
3. Conferir: `git -C C:\Apps\robot_cert log --oneline -1` e o horário dos `python.exe` do repo.
4. Sonda de deploy sem segredo: `GET` numa rota nova que só aceita `POST` (401 = registrada, 404 = ausente), mais `POST /api/login` com credencial falsa (401 rápido = banco ok).
- Servidor é produção: ler e conferir pode; atualizar, reiniciar ou mudar algo exige pedido do Robério a cada vez.
- Bandeja: o instalador é publicado por `deploy/publicar-certguard.ps1` (atualização automática, assinatura Ed25519 própria). Versão da bandeja no código: 1.2.0 (publicada em 07/11/2026). A primeira instalação é máquina a máquina pelo TIC.

## Decisões (ADRs em `docs/adr/`)

- 0001 (01/10/2026): carteira por papel. Operador = Atribuições; Gestor = Exceções (deriva da liderança de Departamento); Administrador = alcance total.
- 0002 (07/10/2026): vínculo pessoa–computador no próprio portal (Principal ou Empréstimo), sem login de pessoa no Hardlyze.
- 0003 (12/10/2026): agente de certificados próprio nas estações, separado do Hardlyze.
- 0004 (16/10/2026): carteira sugerida pelo Acessórias (superado em parte pelo 0005).
- 0005 (18/10/2026): carteira, departamentos e contas sincronizados pelo Acessórias, com trava de 10%.
- Vocabulário de negócio em `GLOSSARY.md`; design em `DESIGN.md` e `PRODUCT.md`.
- Login pela Microsoft (04–07/11/2026): domínios liberados no `.env` (`MICROSOFT_DOMINIOS`); spec em `docs/superpowers/specs/`.
- Publicação na internet (14–15/10/2026): só `certificado.`, Cloudflare na frente, só IPs do Brasil. Roteiro em `docs/publicacao-na-web.md`.

## Pendências abertas

- `A confirmar:` aplicação em produção dos commits posteriores a `518b217`.
- Coexistência de duas estações no cofre (passo 5 de `docs/PLANO_chave_composta_cofre.md`): inaplicável hoje (cofre com 1 máquina).
- Revogação na AC do .p12 real de cliente (3175a05): histórico git já limpo em 30/09; revogar só se houver dúvida (decisão do Robério).
- Itens 12 e 14 da auditoria run-2: 14 tratado só na Cloudflare; 12 `A confirmar:`.

## Armadilhas

- O `.env` local NÃO espelha produção: `API_KEY` e `CERT_ENCRYPTION_KEY` locais são outros. Segredos ficam no `.env` do servidor (`C:\Apps\robot_cert\.env`); nunca versionar.
- O cofre `cert_pfx_store` é derivado: reconstrói-se dos PFX da pasta de origem; perder a chave não perde dado.
- Migration não se roda à mão: vai pelo `atualizar-portal.ps1` (`db/aplicar_schema.py`). Ensaiar numa cópia antes.
- O acervo de certificados é um compartilhamento UNC no 10.200.0.2; UNC só funciona sob `PASTAS_PERMITIDAS`.
- O `?v=` do `style.css` é escrito à mão: não prova que o deploy chegou quando só o Python mudou.
- Hook de commit barra o comando inteiro: faça a correção e o `git commit` em comandos separados.
- Windows/PowerShell: scripts `.ps1` só em ASCII; mensagem de commit por arquivo (`git commit -F`).
- `tests` não devem alcançar banco de produção (`TEST_DATABASE_URL` aponta para `certguard_test`).
