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
VERSAO_AGENTE_ESPERADA = "1.2.0"


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
