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

# Supabase (só no servidor; usados para config + snapshots ingeridos pelo agente)
SUPABASE_URL = (os.getenv("SUPABASE_URL") or "").strip()
SUPABASE_SERVICE_KEY = (os.getenv("SUPABASE_SERVICE_KEY") or "").strip()

# Se definida, todas as rotas /api/* exigem o header X-API-Key (exceto se documentado)
API_KEY = (os.getenv("API_KEY") or "").strip()

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
globals().update(
    {
        nome: (valor or "").strip()
        for nome, valor in os.environ.items()
        if nome.startswith(_PREFIXO_CHAVE_ANTERIOR)
        and nome[len(_PREFIXO_CHAVE_ANTERIOR) :].isdigit()
    }
)

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
VERSAO_AGENTE_ESPERADA = "1.3.0"


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
       (chave do cofre fora do formato, as duas chaves iguais, Supabase pela
       metade).
    2. Valor AUSENTE num ambiente com cara de produção (Supabase configurado)
       cuja falta só apareceria no primeiro uso.

    Ausências em ambiente de desenvolvimento viram AVISO: recusar o boot local
    por falta de CRON_SECRET só ensinaria a ignorar a verificação.
    """
    fatais: list[str] = []
    avisos: list[str] = []

    producao = bool(SUPABASE_URL and SUPABASE_SERVICE_KEY)

    # Supabase pela metade nunca é intencional: o portal sobe, e toda rota de
    # dado morre com erro de cliente — longe da causa.
    if bool(SUPABASE_URL) != bool(SUPABASE_SERVICE_KEY):
        fatais.append(
            "SUPABASE_URL e SUPABASE_SERVICE_KEY precisam ser definidas JUNTAS "
            "(uma sem a outra é configuração pela metade)."
        )

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
