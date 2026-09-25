import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent

CERT_SOURCE_DIR = Path(
    os.getenv("CERT_SOURCE_DIR", str(ROOT / "certificados"))
).resolve()

CERT_EXPIRED_DIR = Path(
    os.getenv("CERT_EXPIRED_DIR", str(ROOT / "certificados_vencidos"))
).resolve()

# Banco (só no servidor): PostgreSQL, por `app.db_pg`. Ex.:
#   postgresql://certguard:senha@127.0.0.1:5432/certguard
# Até 05/09/2026 aqui moravam SUPABASE_URL/SUPABASE_SERVICE_KEY; o portal não
# roda mais no Supabase (ver `app/db_pg.py`). Sem DATABASE_URL o portal sobe
# em modo local (arquivos), como sempre fez sem banco.
DATABASE_URL = (os.getenv("DATABASE_URL") or "").strip()
_SUPABASE_LEGADO = bool((os.getenv("SUPABASE_URL") or "").strip())

# Se definida, todas as rotas /api/* exigem o header X-API-Key (exceto se documentado)
API_KEY = (os.getenv("API_KEY") or "").strip()


def _env_bool(name: str, default: bool) -> bool:
    raw = (os.getenv(name) or "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on", "sim")


# A X-API-Key COMPARTILHADA ainda autentica o agente? É o legado em transição
# (Frente 1): cada estação deveria ter a própria credencial de máquina
# (`app/machine_credentials.py`). Padrão: aceita em dev, recusa em produção
# (lote 2 da auditoria de 24/09/2026). Ligue (=1) só enquanto houver estação
# não migrada — o WARNING em `require_auth` diz quais. Mesmo ligada, a chave
# compartilhada NUNCA puxa fila nem resgata token: sem identidade de máquina
# não há como saber de quem é a fila ou o token (achados #3 e #21).
ACEITAR_API_KEY_COMPARTILHADA = _env_bool(
    "ACEITAR_API_KEY_COMPARTILHADA", default=not bool(DATABASE_URL)
)

# /claim exige credencial de MÁQUINA deste portal? Hoje quem resgata é o
# agente do INVENT, que não tem credencial aqui — ele manda só o token. Ligar
# antes de o agente do INVENT passar a apresentar uma credencial pararia toda
# instalação. Desligada, o /claim confere o `X-Machine-Id` quando o agente o
# manda e avisa no log quando não manda (janela do achado #21).
CLAIM_EXIGE_CREDENCIAL_DE_MAQUINA = _env_bool("CLAIM_EXIGE_CREDENCIAL_DE_MAQUINA", default=False)

# Se `/docs`, `/redoc` e `/openapi.json` ficam públicos. Desligado por padrão:
# em produção o schema das ~97 rotas só ajuda quem está mapeando a API — era o
# único dado que um visitante anônimo levava do portal (levantamento de
# 01/09/2026). Ligue com ENABLE_DOCS=1 em desenvolvimento. Mesmo desenho (e
# mesma variável) do INVENT, para os dois portais se configurarem igual.
ENABLE_DOCS = (os.getenv("ENABLE_DOCS") or "").strip().lower() in ("1", "true", "yes", "on")


def _env_int(name: str, default: int, lo: int, hi: int) -> int:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        v = int(raw)
    except ValueError:
        return default
    return max(lo, min(hi, v))


# Quantos proxies de confiança há entre a internet e este processo. É o que
# decide QUAL valor do X-Forwarded-For é o cliente: cada proxy anexa o IP de
# quem falou com ele ao FIM do cabeçalho, então só os N últimos valores foram
# escritos por alguém em quem se confia — o resto é o que o cliente mandou.
# Ler o primeiro valor (como se fazia até o lote 1 da auditoria de 24/09/2026)
# deixava qualquer um escolher a chave do próprio rate limit. Padrão 1: o Caddy
# do ANALISESRV. Zero desliga o cabeçalho e usa o socket (dev, testes).
NUM_PROXIES_CONFIAVEIS = _env_int("NUM_PROXIES_CONFIAVEIS", default=1, lo=0, hi=5)

# Raízes em que as pastas de certificados podem estar (separadas por `;` no
# Windows e `:` no Linux — `os.pathsep`). Vazio = qualquer pasta local, como
# sempre foi (janela do lote 6, com aviso em `verificar_ambiente`); UNC e
# caminhos que resolvem para fora da raiz são recusados sempre que a lista
# existe. É o que impede `source_folder=C:\` ou `\\atacante\share` vindos
# da tela de Configuração (SECURITY_AUDIT #16).
PASTAS_PERMITIDAS = [
    Path(p.strip()).resolve()
    for p in (os.getenv("PASTAS_PERMITIDAS") or "").split(os.pathsep)
    if p.strip()
]

# Servidores SMTP em rede PRIVADA que o portal pode usar (nomes ou IPs,
# separados por vírgula). Endereço de rede interna só é aceito se estiver
# aqui; link-local, multicast e reservado nunca; localhost sempre (é o
# "servidor local" do lote 1). Fecha o SSRF pela tela de SMTP (#33).
SMTP_HOSTS_PERMITIDOS = [
    h.strip().lower()
    for h in (os.getenv("SMTP_HOSTS_PERMITIDOS") or "").split(",")
    if h.strip()
]

# Nomes de host que este portal atende (sem porta, separados por vírgula).
# Vazio = aceita qualquer Host, como sempre aceitou — é a janela de
# compatibilidade, com aviso em `verificar_ambiente`. Preenchido, um Host fora
# da lista recebe 400 antes de chegar a qualquer rota.
HOSTS_PERMITIDOS = [
    h.strip().lower()
    for h in (os.getenv("HOSTS_PERMITIDOS") or "").split(",")
    if h.strip()
]


# Máximo de linhas lidas na tabela cert_snapshots ao agregar histórico/vencidos (RAM ~ proporcional ao lote).


HISTORICO_LIMITE_SNAPSHOTS = _env_int(
    "HISTORICO_LIMITE_SNAPSHOTS",
    default=500,
    lo=1,
    hi=2000,
)

# Cache em RAM da agregação histórico/vencidos (segundos). 0 = desativado.


HISTORICO_CACHE_TTL_SEC = _env_int(
    "HISTORICO_CACHE_TTL_SEC",
    default=60,
    lo=0,
    hi=86400,
)

# ── Módulo Instalador de Certificados ──────────────────────────────────
# Chave AES-256 para cifrar/decifrar PFX em repouso no banco (hex, 64 chars = 32 bytes).
# Gere com: python -c "import secrets; print(secrets.token_hex(32))"
CERT_ENCRYPTION_KEY = (os.getenv("CERT_ENCRYPTION_KEY") or "").strip()

# Chaves de versões anteriores (CERT_ENCRYPTION_KEY_V1, _V2, ...). Cada linha de
# cert_pfx_store grava a versão sob a qual foi cifrada, e o decrypt busca a chave
# dessa versão aqui — é o que permite trocar a chave em vigor sem tornar ilegível
# o que já está no cofre. Carregadas por varredura do ambiente para que uma nova
# rotação não exija editar este arquivo.
_PREFIXO_CHAVE_ANTERIOR = "CERT_ENCRYPTION_KEY_V"
_PREFIXO_CHAVE_SENHA_ANTERIOR = "CERT_PASSWORD_ENCRYPTION_KEY_V"
globals().update(
    {
        nome: (valor or "").strip()
        for nome, valor in os.environ.items()
        if any(
            nome.startswith(p) and nome[len(p):].isdigit()
            for p in (_PREFIXO_CHAVE_ANTERIOR, _PREFIXO_CHAVE_SENHA_ANTERIOR)
        )
    }
)

# Versão sob a qual CERT_ENCRYPTION_KEY está em vigor (lote 8 da auditoria,
# achado #42). Até aqui era a constante 1 no código, e por isso a rotação
# documentada nunca funcionou: CERT_ENCRYPTION_KEY_V1 só é consultada para
# linhas com key_version diferente da em vigor, e a em vigor nunca deixava de
# ser 1. Rotação: gerar chave nova em CERT_ENCRYPTION_KEY, mover a antiga para
# CERT_ENCRYPTION_KEY_V<versão antiga>, subir esta variável em 1, reiniciar,
# "Recifrar cofre" no Instalador até zerar, e só então apagar a _V antiga.
CERT_ENCRYPTION_KEY_VERSION = _env_int("CERT_ENCRYPTION_KEY_VERSION", default=1, lo=1, hi=999)

# O mesmo para a chave da SENHA (achado #19): até o lote 8 o ciphertext da
# senha não tinha versão e era sempre decifrado com a chave corrente — trocar
# CERT_PASSWORD_ENCRYPTION_KEY tornava todas as senhas do cofre ilegíveis.
# Linha sem `password_key_version` (anterior à migração) vale 1.
CERT_PASSWORD_ENCRYPTION_KEY_VERSION = _env_int(
    "CERT_PASSWORD_ENCRYPTION_KEY_VERSION", default=1, lo=1, hi=999
)

# O AES-GCM do cofre passou a levar dados associados (máquina|fingerprint|
# versão — achado #55): um ciphertext trocado de linha deixa de decifrar.
# Linhas anteriores (aad_version 0) continuam aceitas enquanto isto estiver
# desligado, com aviso; depois de "Recifrar cofre" zerar as linhas sem AAD,
# ligue (=1) e o envelope antigo passa a ser recusado. Padrão desligado: o
# cofre real tem centenas de linhas no envelope antigo.
COFRE_EXIGE_AAD = _env_bool("COFRE_EXIGE_AAD", default=False)

# Chave AES-256 para a SENHA do PFX (hex, 64 chars). Tem de ser diferente de
# CERT_ENCRYPTION_KEY: o motivo de a senha ter saído do banco em 03/08 foi estar
# cifrada com a MESMA chave do PFX, de modo que um vazamento entregava os dois
# juntos. Ela voltou porque o instalador avulso (máquina do usuário, que não tem
# a pasta de origem) não tem outra forma de obtê-la — mas só faz sentido guardada
# sob chave própria. Idealmente as duas vivem em cofres/ambientes distintos.
CERT_PASSWORD_ENCRYPTION_KEY = (os.getenv("CERT_PASSWORD_ENCRYPTION_KEY") or "").strip()

# TTL (minutos) dos tokens de instalação. Padrão: 5 min.
CERT_INSTALL_TOKEN_TTL_MIN = _env_int(
    "CERT_INSTALL_TOKEN_TTL_MIN",
    default=5,
    lo=1,
    hi=60,
)


# Versão do agente que ESTE deploy espera na frota.
#
# Terceira cópia do mesmo número, e a duplicação é inevitável: `agent/__init__`
# é a fonte que o código do agente lê, `agent_setup.iss` declara AppVersion
# porque o Inno não importa Python, e aqui porque o pacote `agent` não vai no
# bundle da Vercel — `from agent import __version__` no servidor resolveria em
# desenvolvimento e falharia em produção, ou pior, cairia num fallback vazio e
# o portal deixaria de acusar máquina atrasada sem ninguém perceber.
#
# `tests/test_versao_agente.py` guarda as três contra divergência.
VERSAO_AGENTE_ESPERADA = "1.4.0"


# ── Ponte com o portal de inventário (INVENT/Hardlyze) ────────────────────
#
# É por ela que "instalar nesta máquina" chega ao agente: o agente escuta a fila
# do INVENT e mais nada, então este portal precisa PEDIR a ele que enfileire.
#
# Servidor a servidor, com segredo dedicado. Nenhum dos dois ganha acesso ao
# banco do outro — o muro que mantém o cofre fora do alcance do código de
# inventário continua de pé, e essa foi a razão de não unificar os bancos.
#
# Vazio = o botão "instalar nesta máquina" não existe e o portal continua
# entregando o .exe avulso, como sempre fez. Ligar é definir estas duas.
INVENT_API_URL = (os.getenv("INVENT_API_URL") or "").strip().rstrip("/")

# O MESMO valor configurado como CERT_PORTAL_TOKEN do outro lado. Próprio, e não
# um token de admin: dá exatamente uma capacidade — enfileirar uma instalação.
CERT_PORTAL_TOKEN = (os.getenv("CERT_PORTAL_TOKEN") or "").strip()


def ponte_invent_configurada() -> bool:
    return bool(INVENT_API_URL and CERT_PORTAL_TOKEN)


# ── Verificação central do ambiente, na partida ───────────────────────────


def _hex_de_32_bytes(valor: str) -> bool:
    if len(valor) != 64:
        return False
    try:
        bytes.fromhex(valor)
        return True
    except ValueError:
        return False


def verificar_ambiente() -> tuple[list[str], list[str]]:
    """As variáveis críticas, conferidas de uma vez — na subida, não no uso.

    Devolve `(fatais, avisos)`. Antes disto (R9 do diagnóstico de 25/08/2026),
    cada variável falhava só na primeira utilização: chave do cofre errada
    aparecia no primeiro upload de PFX, JWT ausente no primeiro login — erro
    tarde, em produção, desligado da causa. O precedente é a ENCRYPTION_KEY,
    que já falhava no boot de propósito; isto estende a regra às demais.

    O que é FATAL segue dois critérios, e só eles:

    1. Valor PRESENTE mas malformado ou contraditório — nunca é intencional
       (chave do cofre fora do formato, as duas chaves iguais, configuração do
       Supabase sobrando de antes da migração).
    2. Valor AUSENTE num ambiente com cara de produção (banco configurado)
       cuja falta só apareceria no primeiro uso.

    Ausências em ambiente de desenvolvimento viram AVISO: recusar o boot local
    por falta de CRON_SECRET só ensinaria a ignorar a verificação.
    """
    fatais: list[str] = []
    avisos: list[str] = []

    producao = bool(DATABASE_URL)

    # Um .env com SUPABASE_URL e sem DATABASE_URL é o ambiente de antes de
    # 05/09/2026 subindo sem banco nenhum: as rotas de dado cairiam no modo
    # local (arquivos) em silêncio, e o portal pareceria "vazio". Melhor
    # recusar o boot e apontar a migração.
    if _SUPABASE_LEGADO and not DATABASE_URL:
        fatais.append(
            "SUPABASE_URL está definida mas o portal não roda mais no Supabase: "
            "defina DATABASE_URL (PostgreSQL) e remova as variáveis SUPABASE_*."
        )
    if DATABASE_URL and not DATABASE_URL.startswith(("postgresql://", "postgres://")):
        fatais.append("DATABASE_URL precisa começar com postgresql:// (PostgreSQL).")

    # Chaves do cofre: formato conferido sempre que presentes; presença exigida
    # quando há banco (sem banco não há cofre a proteger).
    for nome, valor in (
        ("CERT_ENCRYPTION_KEY", CERT_ENCRYPTION_KEY),
        ("CERT_PASSWORD_ENCRYPTION_KEY", CERT_PASSWORD_ENCRYPTION_KEY),
    ):
        if valor and not _hex_de_32_bytes(valor):
            fatais.append(f"{nome} precisa ser hex de 64 caracteres (32 bytes).")
        elif not valor and producao:
            fatais.append(f"{nome} não definida — o cofre falharia no primeiro PFX.")

    # A separação das chaves é a garantia de 03/08: cifrar senha e certificado
    # com a mesma chave fez um vazamento entregar os dois.
    if (
        CERT_ENCRYPTION_KEY
        and CERT_PASSWORD_ENCRYPTION_KEY
        and CERT_ENCRYPTION_KEY == CERT_PASSWORD_ENCRYPTION_KEY
    ):
        fatais.append(
            "CERT_PASSWORD_ENCRYPTION_KEY não pode ser igual a CERT_ENCRYPTION_KEY."
        )

    # Chave "anterior" com o número da versão em vigor nunca é lida (#42): a
    # em vigor vem de CERT_ENCRYPTION_KEY. Foi assim que a rotação de 15/08
    # pareceu configurada e não estava.
    for prefixo, versao_em_vigor, nome_da_em_vigor in (
        (_PREFIXO_CHAVE_ANTERIOR, CERT_ENCRYPTION_KEY_VERSION, "CERT_ENCRYPTION_KEY"),
        (_PREFIXO_CHAVE_SENHA_ANTERIOR, CERT_PASSWORD_ENCRYPTION_KEY_VERSION, "CERT_PASSWORD_ENCRYPTION_KEY"),
    ):
        nome_v = f"{prefixo}{versao_em_vigor}"
        if (globals().get(nome_v) or "").strip():
            avisos.append(
                f"{nome_v} está definida, mas a versão em vigor é {versao_em_vigor}: ela nunca será "
                f"lida. Para rotacionar, ponha a chave nova em {nome_da_em_vigor}, a antiga em "
                f"{prefixo}{versao_em_vigor} e suba {nome_da_em_vigor}_VERSION para {versao_em_vigor + 1}."
            )
        for nome, valor in list(globals().items()):
            if nome.startswith(prefixo) and nome[len(prefixo):].isdigit() and valor and not _hex_de_32_bytes(valor):
                fatais.append(f"{nome} precisa ser hex de 64 caracteres (32 bytes).")

    if producao and not COFRE_EXIGE_AAD:
        avisos.append(
            "COFRE_EXIGE_AAD desligada — linhas do cofre no envelope antigo (sem dados "
            "associados) ainda são aceitas. Rode 'Recifrar cofre' no Instalador até zerar "
            "as linhas sem AAD e ligue COFRE_EXIGE_AAD=1."
        )

    if not (os.getenv("JWT_SECRET_KEY") or "").strip():
        (fatais if producao else avisos).append(
            "JWT_SECRET_KEY não definida — o login falharia na primeira sessão."
        )

    if not API_KEY:
        # O modo sem API_KEY abre o /api/* com identidade anônima (papel
        # agent). É deliberado em dev; em produção é a porta que o levantamento
        # de 01/09/2026 mandou vigiar (api_key_required no /api/health).
        (fatais if producao else avisos).append(
            "API_KEY não definida — todas as rotas /api/* aceitam identidade "
            "anônima com papel agent (modo aberto)."
        )

    if producao and not PASTAS_PERMITIDAS:
        avisos.append(
            "PASTAS_PERMITIDAS não definida — a tela de Configuração aceita qualquer "
            "pasta local do servidor como origem/destino dos certificados. Defina as "
            "raízes (ex.: F:\\07. CERTIFICADOS)."
        )

    if producao and not HOSTS_PERMITIDOS:
        # Aviso, não fatal: é a janela de compatibilidade do lote 1. Sem a
        # lista o portal atende qualquer Host, como sempre atendeu; com ela,
        # um Host forjado leva 400 antes de qualquer rota.
        avisos.append(
            "HOSTS_PERMITIDOS não definida — o portal aceita qualquer cabeçalho "
            "Host. Defina os nomes atendidos (ex.: certificado.analisegroup.cnt.br,"
            "10.200.0.4,127.0.0.1,localhost)."
        )

    if producao and not (os.getenv("CRON_SECRET") or "").strip():
        # Aviso e não fatal: só o Vercel usa o cron, e a rota já falha fechada
        # (503) sem o segredo. O aviso existe porque o sintoma — alertas que
        # nunca disparam — não aponta para cá.
        avisos.append(
            "CRON_SECRET não definida — no Vercel, o disparo agendado de "
            "alertas responderá 503 e nada será enviado."
        )

    if not ponte_invent_configurada():
        avisos.append(
            "Ponte com o INVENT desligada (INVENT_API_URL/CERT_PORTAL_TOKEN) — "
            "o botão 'instalar nesta máquina' não aparece."
        )

    return fatais, avisos
