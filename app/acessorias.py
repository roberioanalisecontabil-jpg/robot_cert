"""
Carteira sincronizada pelo Acessórias (ADR 0005, 18/10/2026).

Quem é responsável por uma empresa no Acessórias ganha o certificado dela
aqui, e quem deixa de ser perde, sem aprovação. Este módulo faz a busca, o
cálculo do que muda e a aplicação.

── As três etapas ─────────────────────────────────────────────────────────

1. **Ler** (`ler_acessorias`): a busca é sempre completa — empresas com os
   departamentos e responsáveis, usuários e departamentos. Só leitura; o
   portal nunca escreve no Acessórias. No máximo 30 chamadas por minuto: o
   limite de 100 é dividido com o DIARIO2.0.
2. **Calcular** (`calcular_plano`): regra pura, sem banco. O que o Acessórias
   dá menos os bloqueios, contra a carteira de hoje.
3. **Aplicar** (`_aplicar`): numa transação só, refazendo o cálculo contra o
   estado do momento. Cópia local, carteira e histórico mudam juntos.

── A trava (`motivo_para_confirmar`) ──────────────────────────────────────

Uma busca incompleta nunca é aplicada (estado `erro`). Uma completa espera a
confirmação do Administrador (estado `aguardando`, dados guardados) quando é
a primeira aplicação, quando tiraria mais de 10% dos acessos ou quando veio
com bem menos empresas que a última aplicada. Uma busca nova substitui a que
aguardava.

── Contas (`calcular_contas`) ─────────────────────────────────────────────

Usuário ativo do Acessórias sem conta ganha uma (Operador, sem senha, convite
de 7 dias por e-mail); a conta vinda de lá é desativada e reativada com ele.
Administrador e conta manual nunca mudam.

── O que fica para as etapas seguintes do ADR ─────────────────────────────

Ligar departamentos pela chave "trazer" e pôr cada pessoa no seu; o novo
alcance do Gestor.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Iterable, List, Optional, Set, Tuple

import httpx
from psycopg.rows import dict_row

from app import config
from app.cert_installer import so_digitos

logger = logging.getLogger(__name__)

# 100 por minuto divididos com o DIARIO2.0 (ADR 0005): o portal fica com 30.
INTERVALO = 2.0
TENTATIVAS_429 = 3
LIMITE_SAIDAS = 0.10
LIMITE_QUEDA_EMPRESAS = 0.90
# Uma busca leva cerca de 1 minuto. 'rodando' mais velha que isto morreu com o
# processo e não pode prender o índice de "uma rodando por vez".
RODANDO_ABANDONADA = timedelta(minutes=15)

AUTOR = "Acessórias (sincronização)"
# Validade do código do convite da conta nova (ADR 0005).
CONVITE_MIN = 7 * 24 * 60
# Papéis que recebem carteira. Administrador alcança tudo e não precisa.
PAPEIS_COM_CARTEIRA = ("user", "gestor")
# Só um aplicador por vez, mesmo com a busca automática e o botão juntos.
_TRAVA_APLICACAO = 20261018


class ErroAcessorias(Exception):
    pass


# ──────────────────────────────────────────────────────────────────────────
# 1. Leitura
# ──────────────────────────────────────────────────────────────────────────

class Api:
    def __init__(self, token: str, url: str = "", http: Optional[httpx.Client] = None,
                 dormir: Callable[[float], None] = time.sleep) -> None:
        if not token:
            raise ErroAcessorias("ACESSORIAS_API_TOKEN não configurado")
        self._url = (url or config.ACESSORIAS_API_URL).rstrip("/")
        self._http = http or httpx.Client(timeout=60)
        self._cabecalhos = {"Authorization": f"Bearer {token}", "User-Agent": "certguard/acessorias"}
        self._dormir = dormir
        self.chamadas = 0

    def _get(self, caminho: str, parametros: Dict[str, Any]) -> List[dict]:
        for tentativa in range(TENTATIVAS_429 + 1):
            self._dormir(INTERVALO)
            self.chamadas += 1
            r = self._http.get(self._url + caminho, params=parametros, headers=self._cabecalhos)
            if r.status_code == 429:
                self._dormir(15 * (tentativa + 1))
                continue
            if r.status_code == 204:
                return []
            if r.status_code == 401:
                raise ErroAcessorias("token do Acessórias recusado (401)")
            if r.status_code != 200:
                raise ErroAcessorias(f"Acessórias respondeu {r.status_code} em {caminho}")
            corpo = r.json() if r.content else []
            if isinstance(corpo, dict):
                if "Erro" in corpo:
                    raise ErroAcessorias(f"Acessórias: {corpo['Erro']}")
                return [corpo]
            if not isinstance(corpo, list):
                raise ErroAcessorias(f"resposta inesperada em {caminho}")
            return corpo
        raise ErroAcessorias("Acessórias continuou limitando as chamadas (429)")

    def listar(self, caminho: str, parametros: Optional[Dict[str, Any]] = None) -> List[dict]:
        """Todas as páginas, até a vazia. Erro em qualquer uma derruba a lista inteira."""
        saida: List[dict] = []
        pagina = 1
        while True:
            lote = self._get(caminho, {**(parametros or {}), "Pagina": pagina})
            if not lote:
                return saida
            saida.extend(x for x in lote if isinstance(x, dict))
            pagina += 1


def _texto(v: Any) -> str:
    return str(v or "").strip()


def _inteiro(v: Any) -> Optional[int]:
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return None


def converter_empresa(item: dict) -> Optional[dict]:
    """Só CNPJ: CPF e CAEPF não vêm do Acessórias para a carteira (ADR 0005)."""
    cnpj = so_digitos(item.get("Identificador"))
    if len(cnpj) != 14:
        return None
    departamentos: Dict[int, dict] = {}
    for d in item.get("Departamentos") or []:
        if not isinstance(d, dict):
            continue
        dep_id = _inteiro(d.get("ID"))
        if dep_id is None or dep_id in departamentos:
            continue
        departamentos[dep_id] = {
            "id": dep_id,
            "nome": _texto(d.get("Nome")),
            "resp_nome": _texto(d.get("RespNome")),
            "resp_email": _texto(d.get("RespEmail")).lower(),
        }
    return {
        "cnpj": cnpj,
        "razao": _texto(item.get("Razao")),
        "ativa": _texto(item.get("Status")).lower().startswith("ativ"),
        "departamentos": list(departamentos.values()),
    }


def converter_usuario(item: dict) -> Optional[dict]:
    uid = _inteiro(item.get("id") if "id" in item else item.get("ID"))
    if uid is None:
        return None
    return {
        "id": uid,
        "nome": _texto(item.get("nome") or item.get("Nome")),
        "email": _texto(item.get("email") or item.get("Email")).lower(),
        "ativo": _texto(item.get("status") or item.get("Status")).lower() == "ativo",
    }


def ler_acessorias(api: Api) -> dict:
    """A busca inteira. Levanta ErroAcessorias se qualquer página falhar."""
    empresas: Dict[str, dict] = {}
    for item in api.listar("/companies/ListAll", {"departments": ""}):
        e = converter_empresa(item)
        if e and e["cnpj"] not in empresas:
            empresas[e["cnpj"]] = e
    usuarios: Dict[int, dict] = {}
    for item in api.listar("/users/ListAll"):
        u = converter_usuario(item)
        if u:
            usuarios[u["id"]] = u
    departamentos: Dict[int, str] = {}
    for item in api.listar("/departments/ListAll"):
        dep_id = _inteiro(item.get("ID"))
        if dep_id is not None:
            departamentos[dep_id] = _texto(item.get("Nome"))
    for e in empresas.values():
        for d in e["departamentos"]:
            departamentos.setdefault(d["id"], d["nome"])
    if not empresas:
        raise ErroAcessorias("a busca não trouxe nenhuma empresa")
    return {
        "empresas": list(empresas.values()),
        "usuarios": list(usuarios.values()),
        "departamentos": [{"id": k, "nome": v} for k, v in sorted(departamentos.items())],
    }


# ──────────────────────────────────────────────────────────────────────────
# 2. Cálculo (puro)
# ──────────────────────────────────────────────────────────────────────────

def _dv_cnpj(base: str) -> str:
    """Os dois dígitos verificadores de um CNPJ a partir dos 12 primeiros."""
    def digito(numeros: str, pesos: List[int]) -> str:
        resto = sum(int(n) * p for n, p in zip(numeros, pesos)) % 11
        return "0" if resto < 2 else str(11 - resto)

    d1 = digito(base, [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])
    d2 = digito(base + d1, [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])
    return d1 + d2


def cnpj_matriz(cnpj: str) -> str:
    base = cnpj[:8] + "0001"
    return base + _dv_cnpj(base)


def documento_da_empresa(cnpj: str, com_certificado: Set[str]) -> str:
    """CNPJ exato; se ele não tem certificado e a matriz tem, o da matriz.

    Sem certificado nenhum, fica o exato: a carteira é por documento, então o
    certificado que chegar depois já nasce com dono (ADR 0001).
    """
    if cnpj in com_certificado:
        return cnpj
    matriz = cnpj_matriz(cnpj)
    if matriz != cnpj and matriz in com_certificado:
        return matriz
    return cnpj


Par = Tuple[str, str]  # (user_id, documento)


@dataclass
class Estado:
    """O que o cálculo precisa do banco, lido de uma vez."""
    # e-mail em minúsculas -> {id, email, role, ativo, origem, acessorias_id}
    contas: Dict[str, dict]
    carteira: Dict[Par, str]                    # par -> origem
    bloqueios: Set[Par] = field(default_factory=set)
    trazer: Set[int] = field(default_factory=set)
    com_certificado: Set[str] = field(default_factory=set)
    ja_aplicou: bool = False
    empresas_ultima_aplicada: Optional[int] = None


PREFIXO_NOVA = "nova:"  # id provisório da conta que esta aplicação vai criar


def calcular_contas(usuarios: List[dict], contas: Dict[str, dict]) -> dict:
    """Contas do portal a partir dos usuários do Acessórias, ligados pelo e-mail.

    - Usuário ativo lá sem conta aqui: conta nova (Operador, sem senha).
    - Conta que veio do Acessórias (`origem = acessorias`): desativa quando o
      usuário fica inativo ou some de lá, reativa quando volta.
    - Administrador e conta manual nunca mudam; só ganham o id do Acessórias
      quando o e-mail casa, para a tela mostrar a ligação.
    """
    por_id = {u["id"]: u for u in usuarios}
    criar: List[dict] = []
    desativar: List[str] = []
    reativar: List[str] = []
    ligar: List[Tuple[str, int]] = []
    ids_em_uso = {c.get("acessorias_id") for c in contas.values() if c.get("acessorias_id") is not None}
    vistos: Set[str] = set()
    for u in usuarios:
        if not u["email"] or u["email"] in vistos:
            continue
        vistos.add(u["email"])
        conta = contas.get(u["email"])
        if conta is None:
            if u["ativo"]:
                criar.append(u)
            continue
        if conta.get("acessorias_id") != u["id"] and u["id"] not in ids_em_uso:
            ligar.append((conta["id"], u["id"]))
            ids_em_uso.add(u["id"])
        if conta.get("origem") != "acessorias" or conta["role"] == "admin":
            continue
        if u["ativo"] and not conta["ativo"]:
            reativar.append(conta["id"])
        elif not u["ativo"] and conta["ativo"]:
            desativar.append(conta["id"])
    # Conta vinda do Acessórias cujo usuário sumiu de lá (busca inteira):
    # é o mesmo que inativo.
    for c in contas.values():
        aid = c.get("acessorias_id")
        if (c.get("origem") == "acessorias" and c["ativo"] and c["role"] != "admin"
                and aid is not None and aid not in por_id and c["id"] not in desativar):
            desativar.append(c["id"])
    return {"criar": criar, "desativar": sorted(desativar), "reativar": sorted(reativar), "ligar": ligar}


def calcular_plano(dados: dict, estado: Estado) -> dict:
    contas = calcular_contas(dados["usuarios"], estado.contas)
    # As contas como ficarão depois desta aplicação: a conta criada agora já
    # recebe a carteira, e a desativada perde a dela inteira.
    efetivas = {email: dict(c) for email, c in estado.contas.items()}
    por_id = {c["id"]: c for c in efetivas.values()}
    for uid in contas["desativar"]:
        por_id[uid]["ativo"] = False
    for uid in contas["reativar"]:
        por_id[uid]["ativo"] = True
    for u in contas["criar"]:
        efetivas[u["email"]] = {"id": f"{PREFIXO_NOVA}{u['id']}", "email": u["email"], "role": "user",
                                "ativo": True, "origem": "acessorias", "acessorias_id": u["id"]}
    desativadas = set(contas["desativar"])

    desejado: Set[Par] = set()
    for e in dados["empresas"]:
        if not e["ativa"]:
            continue
        doc = documento_da_empresa(e["cnpj"], estado.com_certificado)
        for d in e["departamentos"]:
            if d["id"] not in estado.trazer or not d["resp_email"]:
                continue
            conta = efetivas.get(d["resp_email"])
            if conta and conta["ativo"] and conta["role"] in PAPEIS_COM_CARTEIRA:
                desejado.add((conta["id"], doc))
    desejado -= estado.bloqueios

    atuais = estado.carteira
    entradas = sorted(desejado - atuais.keys())
    conversoes = sorted(p for p in desejado & atuais.keys() if atuais[p] != "acessorias")
    # Na virada (primeira aplicação), a carteira manual que o Acessórias não
    # confirma também sai (ADR 0005). Exceto e-CPF: ele nunca vem do
    # Acessórias, e tirá-lo só obrigaria a liberar de novo à mão. Conta
    # desativada perde tudo, de qualquer origem (ADR 0001: sem estado dormente).
    saidas = sorted(
        p for p, origem in atuais.items()
        if p not in desejado
        and (origem == "acessorias" or p[0] in desativadas or (not estado.ja_aplicou and len(p[1]) == 14))
    )
    return {
        "contas": contas,
        "entradas": entradas,
        "conversoes": conversoes,
        "saidas": saidas,
        "resumo": {
            "contas_novas": len(contas["criar"]),
            "contas_desativadas": len(contas["desativar"]),
            "contas_reativadas": len(contas["reativar"]),
            "empresas": len(dados["empresas"]),
            "usuarios": len(dados["usuarios"]),
            "acessos_atuais": len(atuais),
            "entradas": len(entradas),
            "saidas": len(saidas),
            "conversoes": len(conversoes),
            "pessoas_afetadas": len({p[0] for p in entradas} | {p[0] for p in saidas}),
        },
    }


def chave_de_nome(nome: str) -> str:
    """Nome comparável: sem acento, minúsculo, espaços simples ("Contábil" = "contabil")."""
    import unicodedata

    s = unicodedata.normalize("NFKD", nome or "").encode("ascii", "ignore").decode().lower()
    return " ".join(s.split())


def contar_responsabilidades(dados: dict) -> Dict[str, Dict[int, int]]:
    """e-mail -> {departamento do Acessórias: empresas ativas pelas quais responde}."""
    contagem: Dict[str, Dict[int, int]] = {}
    for e in dados["empresas"]:
        if not e["ativa"]:
            continue
        for d in e["departamentos"]:
            if d["resp_email"]:
                por_dep = contagem.setdefault(d["resp_email"], {})
                por_dep[d["id"]] = por_dep.get(d["id"], 0) + 1
    return contagem


def sugestao_de_departamento(contagem: Dict[int, int], mapa: Dict[int, str]) -> Optional[str]:
    """O departamento do portal da pessoa, ou None ("decidir à mão").

    Adendo do ADR 0004, mantido no 0005: o departamento do Acessórias em que a
    pessoa mais aparece como responsável, se aparecer nele pelo menos 3 vezes
    mais que no segundo, e se ele estiver ligado a um do portal.
    """
    if not contagem:
        return None
    ordem = sorted(contagem.items(), key=lambda kv: (-kv[1], kv[0]))
    primeiro, n1 = ordem[0]
    n2 = ordem[1][1] if len(ordem) > 1 else 0
    if n1 < 3 * n2:
        return None
    return mapa.get(primeiro)


def motivo_para_confirmar(plano: dict, estado: Estado) -> str:
    """Vazio = pode aplicar sozinha. Texto = espera o Administrador."""
    r = plano["resumo"]
    if not estado.ja_aplicou:
        return "primeira aplicação"
    atuais = r["acessos_atuais"]
    if r["saidas"] and r["saidas"] > LIMITE_SAIDAS * max(atuais, 1):
        return f"tiraria {r['saidas']} de {atuais} acessos (mais de 10%)"
    anterior = estado.empresas_ultima_aplicada
    if anterior and r["empresas"] < LIMITE_QUEDA_EMPRESAS * anterior:
        return f"veio com {r['empresas']} empresas; a última aplicada tinha {anterior}"
    return ""


def proxima_espera(agora: datetime) -> float:
    """Segundos até a próxima busca: 5 min das 7h às 20h, 1 h no resto."""
    if 7 <= agora.hour < 20:
        return 300.0
    return 3600.0


# ──────────────────────────────────────────────────────────────────────────
# 3. Banco
# ──────────────────────────────────────────────────────────────────────────

def _cliente():
    from app.settings_state import _banco

    c = _banco()
    # Transação e advisory lock pedem a conexão direta do db_pg; os clientes
    # falsos dos testes só imitam a cadeia table().select().
    if not c or not hasattr(c, "conexao"):
        raise ErroAcessorias("banco não configurado")
    return c


def carregar_estado(cur) -> Estado:
    cur.execute(
        "SELECT id::text AS id, lower(email) AS email, role, ativo, origem, acessorias_id FROM public.users"
    )
    contas = {r["email"]: r for r in cur.fetchall()}
    cur.execute("SELECT user_id::text AS user_id, documento, origem FROM public.carteira")
    carteira = {(r["user_id"], r["documento"]): r["origem"] for r in cur.fetchall()}
    cur.execute("SELECT user_id::text AS user_id, documento FROM public.carteira_bloqueio")
    bloqueios = {(r["user_id"], r["documento"]) for r in cur.fetchall()}
    cur.execute("SELECT id FROM public.acessorias_departamento WHERE conta_para_carteira")
    trazer = {r["id"] for r in cur.fetchall()}
    cur.execute(
        "SELECT regexp_replace(coalesce(documento, ''), '\\D', '', 'g') AS d FROM public.cert_pfx_store "
        "UNION SELECT regexp_replace(coalesce(documento_numero, ''), '\\D', '', 'g') FROM public.cert_history"
    )
    com_certificado = {r["d"] for r in cur.fetchall() if r["d"]}
    cur.execute(
        "SELECT empresas FROM public.acessorias_busca WHERE aplicada_em IS NOT NULL "
        "ORDER BY aplicada_em DESC LIMIT 1"
    )
    ultima = cur.fetchone()
    return Estado(
        contas=contas, carteira=carteira, bloqueios=bloqueios, trazer=trazer,
        com_certificado=com_certificado, ja_aplicou=ultima is not None,
        empresas_ultima_aplicada=ultima["empresas"] if ultima else None,
    )


def _gravar_copia(cur, dados: dict) -> None:
    """Cópia local do que foi aplicado: é o que as telas leem."""
    agora = datetime.now(timezone.utc)
    for d in dados["departamentos"]:
        cur.execute(
            "INSERT INTO public.acessorias_departamento (id, nome, visto_em) VALUES (%s, %s, %s) "
            "ON CONFLICT (id) DO UPDATE SET nome = EXCLUDED.nome, visto_em = EXCLUDED.visto_em",
            (d["id"], d["nome"], agora),
        )
    for e in dados["empresas"]:
        cur.execute(
            "INSERT INTO public.acessorias_empresa (cnpj, razao_social, ativa, vista_em) VALUES (%s, %s, %s, %s) "
            "ON CONFLICT (cnpj) DO UPDATE SET razao_social = EXCLUDED.razao_social, "
            "ativa = EXCLUDED.ativa, vista_em = EXCLUDED.vista_em",
            (e["cnpj"], e["razao"], e["ativa"], agora),
        )
    cnpjs = [e["cnpj"] for e in dados["empresas"]]
    # Empresa que não veio numa busca inteira foi removida no Acessórias.
    cur.execute("DELETE FROM public.acessorias_empresa WHERE NOT (cnpj = ANY(%s))", (cnpjs,))
    cur.execute("DELETE FROM public.acessorias_responsavel")
    for e in dados["empresas"]:
        for d in e["departamentos"]:
            if d["resp_email"] or d["resp_nome"]:
                cur.execute(
                    "INSERT INTO public.acessorias_responsavel (cnpj, departamento_acessorias_id, nome, email) "
                    "VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING",
                    (e["cnpj"], d["id"], d["resp_nome"], d["resp_email"]),
                )
    for u in dados["usuarios"]:
        cur.execute(
            "INSERT INTO public.acessorias_usuario (id, nome, email, ativo, vista_em) VALUES (%s, %s, %s, %s, %s) "
            "ON CONFLICT (id) DO UPDATE SET nome = EXCLUDED.nome, email = EXCLUDED.email, "
            "ativo = EXCLUDED.ativo, vista_em = EXCLUDED.vista_em",
            (u["id"], u["nome"], u["email"], u["ativo"], agora),
        )
    ids = [u["id"] for u in dados["usuarios"]]
    cur.execute("DELETE FROM public.acessorias_usuario WHERE NOT (id = ANY(%s))", (ids,))


def _historico(cur, pares: Iterable[Par], movimento: str, emails: Dict[str, str], feito_por_email: str,
               desativadas: Set[str] = frozenset()) -> None:
    for uid, doc in pares:
        cur.execute(
            "INSERT INTO public.carteira_historico "
            "(user_id, user_email, documento, movimento, origem, feito_por, feito_por_email) "
            "VALUES (%s, %s, %s, %s, %s, NULL, %s)",
            (uid, emails.get(uid, ""), doc, movimento,
             "desativacao" if uid in desativadas else "acessorias", feito_por_email),
        )


def _ligar_departamentos(cur, so_estes: Optional[Iterable[int]] = None) -> Dict[str, int]:
    """Liga cada departamento do Acessórias ao do portal de mesmo nome; cria no
    portal o que está com "trazer" e não tem par (ADR 0005).

    Ligado não se desfaz aqui: trocar a ligação é decisão do Administrador na
    tela. Departamento arquivado não recebe ligação automática.
    """
    cur.execute("SELECT id, nome, departamento_id::text AS departamento_id, conta_para_carteira "
                "FROM public.acessorias_departamento ORDER BY id")
    deps = cur.fetchall()
    if so_estes is not None:
        alvo = set(so_estes)
        deps = [d for d in deps if d["id"] in alvo]
    cur.execute("SELECT id::text AS id, nome, arquivado FROM public.departamento")
    portal = cur.fetchall()
    cur.execute("SELECT departamento_id::text AS d FROM public.acessorias_departamento WHERE departamento_id IS NOT NULL")
    usados = {r["d"] for r in cur.fetchall()}
    livres = {chave_de_nome(p["nome"]): p["id"] for p in portal if not p["arquivado"] and p["id"] not in usados}
    ligados = criados = 0
    for d in deps:
        if d["departamento_id"]:
            continue
        pid = livres.pop(chave_de_nome(d["nome"]), None)
        if pid is None and d["conta_para_carteira"] and d["nome"].strip():
            cur.execute("INSERT INTO public.departamento (nome) VALUES (%s) ON CONFLICT DO NOTHING RETURNING id::text AS id",
                        (d["nome"].strip(),))
            linha = cur.fetchone()
            pid = linha["id"] if linha else None
            criados += 1 if linha else 0
        elif pid is not None:
            ligados += 1
        if pid is not None:
            cur.execute("UPDATE public.acessorias_departamento SET departamento_id = %s WHERE id = %s", (pid, d["id"]))
    return {"departamentos_criados": criados, "departamentos_ligados": ligados}


def _mapa_de_departamentos(cur) -> Dict[int, str]:
    cur.execute("SELECT id, departamento_id::text AS d FROM public.acessorias_departamento WHERE departamento_id IS NOT NULL")
    return {r["id"]: r["d"] for r in cur.fetchall()}


def _distribuir_pessoas(cur, contagem: Dict[str, Dict[int, int]]) -> Dict[str, int]:
    """Põe cada pessoa no departamento sugerido, salvo quando o Administrador
    já escolheu outro para a mesma sugestão (a mudança manual vence)."""
    mapa = _mapa_de_departamentos(cur)
    cur.execute("SELECT user_id::text AS u, chave FROM public.acessorias_recusa WHERE tipo = 'departamento'")
    recusas = {(r["u"], r["chave"]) for r in cur.fetchall()}
    cur.execute("SELECT id::text AS id, lower(email) AS email, departamento_id::text AS departamento_id "
                "FROM public.users WHERE ativo AND role <> 'admin'")
    movidas = a_decidir = 0
    for c in cur.fetchall():
        cont = contagem.get(c["email"])
        if not cont:
            continue
        sug = sugestao_de_departamento(cont, mapa)
        # A recusa vale só para a sugestão em que foi feita: se o Acessórias
        # mudar a pessoa, a sugestão nova é outra e a recusa velha sai.
        cur.execute("DELETE FROM public.acessorias_recusa WHERE tipo = 'departamento' AND user_id = %s "
                    "AND chave IS DISTINCT FROM %s", (c["id"], sug))
        if sug is None:
            a_decidir += 1
            continue
        if sug != c["departamento_id"] and (c["id"], sug) not in recusas:
            cur.execute("UPDATE public.users SET departamento_id = %s WHERE id = %s", (sug, c["id"]))
            movidas += 1
    return {"pessoas_movidas": movidas, "pessoas_a_decidir": a_decidir}


def _hash_sem_senha() -> str:
    """Hash bcrypt de um segredo aleatório que ninguém guarda.

    A conta nasce "sem senha" (ADR 0005), mas `password_hash` é NOT NULL e o
    login precisa custar o mesmo tempo para ela: um marcador inválido faria o
    bcrypt falhar na hora e entregaria, pelo tempo de resposta, quem ainda não
    definiu a senha. Um hash por aplicação, calculado fora da transação.
    """
    import secrets

    from app import auth

    return auth.get_password_hash(secrets.token_urlsafe(32))


def _aplicar(conn, dados: dict, feito_por_email: str) -> dict:
    """Aplica numa transação, recalculando contra o estado do momento.

    Recalcular, e não reaproveitar o plano da leitura, porque entre a leitura e
    a confirmação do Administrador alguém pode ter bloqueado ou liberado à mão.

    Devolve o resumo e, em "_depois", o que precisa rodar fora da transação
    (`depois_de_aplicar`): sessões, bandeja e tokens de quem foi desativado,
    papel de quem perdeu liderança, convite de quem ganhou conta.
    """
    hash_sem_senha = _hash_sem_senha()
    with conn.transaction(), conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT pg_advisory_xact_lock(%s)", (_TRAVA_APLICACAO,))
        estado = carregar_estado(cur)
        plano = calcular_plano(dados, estado)
        contas = plano["contas"]
        emails = {c["id"]: c["email"] for c in estado.contas.values()}
        _gravar_copia(cur, dados)

        # Contas novas primeiro: a carteira delas usa o id que nasce aqui.
        ids_novos: Dict[str, str] = {}
        novas: List[dict] = []
        for u in contas["criar"]:
            cur.execute(
                "INSERT INTO public.users (email, password_hash, full_name, role, ativo, origem, acessorias_id) "
                "VALUES (%s, %s, %s, 'user', true, 'acessorias', %s) ON CONFLICT DO NOTHING RETURNING id::text AS id",
                (u["email"], hash_sem_senha, u["nome"] or None, u["id"]),
            )
            linha = cur.fetchone()
            if linha:  # e-mail criado à mão no meio do caminho: fica para a próxima busca
                ids_novos[f"{PREFIXO_NOVA}{u['id']}"] = linha["id"]
                emails[linha["id"]] = u["email"]
                novas.append({"id": linha["id"], "email": u["email"], "full_name": u["nome"]})
        for uid, aid in contas["ligar"]:
            cur.execute("UPDATE public.users SET acessorias_id = %s WHERE id = %s", (aid, uid))
        for uid in contas["reativar"]:
            cur.execute("UPDATE public.users SET ativo = true WHERE id = %s", (uid,))
        for uid in contas["desativar"]:
            # O resto da desativação manual (deactivate_user): lideranças e
            # exceções saem aqui; sessões, bandeja e tokens em depois_de_aplicar.
            cur.execute("UPDATE public.users SET ativo = false WHERE id = %s", (uid,))
            cur.execute("DELETE FROM public.departamento_lider WHERE user_id = %s", (uid,))
            cur.execute("DELETE FROM public.carteira_excecao WHERE user_id = %s", (uid,))

        # Departamentos depois das contas: a conta nova já nasce no seu.
        deps = {**_ligar_departamentos(cur), **_distribuir_pessoas(cur, contar_responsabilidades(dados))}

        def real(par: Par) -> Optional[Par]:
            uid = ids_novos.get(par[0], par[0])
            return None if uid.startswith(PREFIXO_NOVA) else (uid, par[1])

        entradas = [p for p in map(real, plano["entradas"]) if p]
        desativadas = set(contas["desativar"])
        for uid, doc in entradas:
            cur.execute(
                "INSERT INTO public.carteira (user_id, documento, atribuido_por, atribuido_por_email, origem) "
                "VALUES (%s, %s, NULL, %s, 'acessorias') ON CONFLICT (user_id, documento) DO NOTHING",
                (uid, doc, AUTOR),
            )
        for uid, doc in plano["conversoes"]:
            cur.execute(
                "UPDATE public.carteira SET origem = 'acessorias' WHERE user_id = %s AND documento = %s",
                (uid, doc),
            )
        for uid, doc in plano["saidas"]:
            cur.execute("DELETE FROM public.carteira WHERE user_id = %s AND documento = %s", (uid, doc))
        _historico(cur, entradas, "entrada", emails, feito_por_email)
        _historico(cur, plano["saidas"], "saida", emails, feito_por_email, desativadas)
    return {**plano["resumo"], **deps, "_depois": {"novas": novas, "desativadas": sorted(desativadas)}}


def _enviar_convite(conta: dict, codigo: str) -> None:
    """E-mail "defina sua senha" da conta criada pelo Acessórias (ADR 0005)."""
    import html
    import os
    from urllib.parse import quote

    from app import correio
    from app.settings_state import load_settings

    s = load_settings()
    if not correio.configurado(s):
        raise RuntimeError("Envio de e-mail não configurado")
    # Link só se o endereço vier de configuração, nunca do cabeçalho Host
    # (mesma regra do código de senha em app/rotas/usuarios.py).
    base = (os.getenv("PORTAL_BASE_URL") or "").strip().rstrip("/")
    link = (f'<p style="margin:16px 0 0;"><a href="{base}/login?definir={quote(conta["email"])}">'
            "Definir minha senha</a></p>") if base else ""
    nome = html.escape(str(conta.get("full_name") or "").strip() or "Olá")
    correio.send_smtp_email(
        host=s.smtp_host, port=s.smtp_port, user=s.smtp_user, password_enc=s.smtp_password_encrypted,
        use_tls=s.smtp_use_tls, use_ssl=s.smtp_use_ssl, from_email=s.smtp_from_email,
        to_email=str(conta["email"]), settings=s,
        subject="Seu acesso ao Monitor de Certificados",
        html_content=(
            f"<p>{nome},</p>"
            "<p>Sua conta no Monitor de Certificados foi criada a partir do seu cadastro no "
            "Acessórias. Com ela você vê e instala os certificados das empresas pelas quais é "
            "responsável lá.</p>"
            "<p>Para definir sua senha, abra o portal em <strong>Esqueci minha senha › já tenho "
            "um código</strong> (ou use o link abaixo) e informe este código:</p>"
            f'<p style="font-size:28px;letter-spacing:6px;font-weight:700;margin:24px 0;">{codigo}</p>'
            "<p>Ele vale por 7 dias e só pode ser usado uma vez. Depois disso, peça um novo em "
            "<strong>Esqueci minha senha</strong>.</p>"
            f"{link}"
        ),
    )


def depois_de_aplicar(depois: dict) -> dict:
    """O que não cabe na transação. Nunca levanta: a aplicação já foi gravada.

    Desativadas: o mesmo que `deactivate_user` faz depois de gravar (sessões,
    bandeja da estação, tokens de instalação) e o papel rederivado sem as
    lideranças. Novas: código de 7 dias e o e-mail de convite.
    """
    from app import cert_installer, computadores, papeis, senha_reset
    from app.settings_state import _banco

    sb = _banco()
    falhas = 0
    for uid in depois.get("desativadas") or []:
        try:
            papeis.derrubar_sessoes(sb, uid)
            computadores.sair_de_tudo(uid, "conta desativada pelo Acessórias")
            cert_installer.revogar_tokens_pendentes(uid)
            papeis.rederivar(sb, [uid])
        except Exception:  # noqa: BLE001
            falhas += 1
            logger.exception("Conta %s desativada pelo Acessórias, mas a limpeza depois falhou", uid)
    enviados = 0
    for conta in depois.get("novas") or []:
        try:
            codigo = senha_reset.criar_codigo(conta["id"], pelo_admin=True, validade_min=CONVITE_MIN)
            _enviar_convite(conta, codigo)
            enviados += 1
        except Exception:  # noqa: BLE001
            falhas += 1
            # ERROR: a pessoa tem conta e não sabe. O Administrador reenvia
            # pelo "Enviar código" da tela Usuários.
            logger.exception("Conta %s criada pelo Acessórias, mas o convite NÃO foi enviado", conta["id"])
    return {"convites": enviados, "falhas": falhas}


def _abrir_busca(cur, origem: str, por_email: str) -> Optional[int]:
    cur.execute(
        "UPDATE public.acessorias_busca SET estado = 'erro', terminada_em = now(), "
        "erro = 'interrompida (o processo parou durante a busca)' "
        "WHERE estado = 'rodando' AND iniciada_em < now() - %s",
        (RODANDO_ABANDONADA,),
    )
    cur.execute(
        "INSERT INTO public.acessorias_busca (origem, disparada_por_email) VALUES (%s, %s) "
        "ON CONFLICT DO NOTHING RETURNING id",
        (origem, por_email),
    )
    linha = cur.fetchone()
    return linha["id"] if linha else None


def buscar(origem: str = "agendada", por_email: str = "", api: Optional[Api] = None) -> dict:
    """Uma busca inteira: lê, calcula, aplica ou guarda para confirmação.

    Devolve {"id", "estado", "resumo", "motivo"}; {"estado": "ocupada"} se já
    há uma rodando.
    """
    cliente = _cliente()
    # O pool é pequeno (6) e a leitura leva um minuto: a conexão não fica
    # presa enquanto a API responde. O pool já trabalha em autocommit.
    with cliente.conexao() as conn, conn.cursor(row_factory=dict_row) as cur:
        busca_id = _abrir_busca(cur, origem, por_email)
    if busca_id is None:
        return {"estado": "ocupada"}
    try:
        api = api or Api(config.ACESSORIAS_API_TOKEN)
        dados = ler_acessorias(api)
        paginas = api.chamadas
    except Exception as e:  # noqa: BLE001 — qualquer falha deixa a busca incompleta
        msg = str(e)[:500] if isinstance(e, ErroAcessorias) else f"{type(e).__name__}: {str(e)[:400]}"
        logger.warning("Busca do Acessórias %s incompleta: %s", busca_id, msg)
        with cliente.conexao() as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE public.acessorias_busca SET estado = 'erro', terminada_em = now(), erro = %s WHERE id = %s",
                (msg, busca_id),
            )
        return {"id": busca_id, "estado": "erro", "erro": msg}

    with cliente.conexao() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            estado = carregar_estado(cur)
        plano = calcular_plano(dados, estado)
        motivo = motivo_para_confirmar(plano, estado)
        resumo = {**plano["resumo"], "motivo": motivo}
        with conn.cursor() as cur:
            # Uma busca nova, inteira, substitui a que aguardava: o Administrador
            # confirma sempre o retrato mais recente do Acessórias.
            cur.execute(
                "UPDATE public.acessorias_busca SET estado = 'descartada', plano = '{}'::jsonb, "
                "decidida_por_email = 'substituida', decidida_em = now() WHERE estado = 'aguardando'"
            )
            if motivo:
                cur.execute(
                    "UPDATE public.acessorias_busca SET estado = 'aguardando', terminada_em = now(), "
                    "paginas = %s, empresas = %s, plano = %s, resumo = %s WHERE id = %s",
                    (paginas, resumo["empresas"], json.dumps({"dados": dados}), json.dumps(resumo), busca_id),
                )
                return {"id": busca_id, "estado": "aguardando", "resumo": resumo, "motivo": motivo}

        resumo_aplicado = _aplicar(conn, dados, AUTOR)
        depois = resumo_aplicado.pop("_depois")
        resumo = {**resumo_aplicado, "motivo": ""}
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE public.acessorias_busca SET estado = 'ok', terminada_em = now(), aplicada_em = now(), "
                "paginas = %s, empresas = %s, resumo = %s WHERE id = %s",
                (paginas, resumo["empresas"], json.dumps(resumo), busca_id),
            )
    # Só depois do commit: virada que não gravou não vira o Gestor.
    _sincronizado.update(valor=True)
    resumo["pos"] = depois_de_aplicar(depois)
    return {"id": busca_id, "estado": "ok", "resumo": resumo, "motivo": ""}


def confirmar(busca_id: int, por_email: str) -> dict:
    """O Administrador confirma a busca que aguardava. Só a mais nova vale."""
    cliente = _cliente()
    with cliente.conexao() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT id, plano, estado FROM public.acessorias_busca WHERE id = %s", (busca_id,)
            )
            linha = cur.fetchone()
        if not linha or linha["estado"] != "aguardando":
            raise ErroAcessorias("esta busca não está aguardando confirmação (outra mais nova a substituiu?)")
        dados = (linha["plano"] or {}).get("dados")
        if not dados:
            raise ErroAcessorias("a busca não guardou os dados; rode Buscar agora")
        resumo = {**_aplicar(conn, dados, por_email), "motivo": ""}
        depois = resumo.pop("_depois")
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE public.acessorias_busca SET estado = 'ok', aplicada_em = now(), plano = '{}'::jsonb, "
                "decidida_por_email = %s, decidida_em = now(), resumo = resumo || %s WHERE id = %s",
                (por_email, json.dumps({"aplicado": resumo}), busca_id),
            )
    _sincronizado.update(valor=True)
    resumo["pos"] = depois_de_aplicar(depois)
    return {"id": busca_id, "estado": "ok", "resumo": resumo}


def descartar(busca_id: int, por_email: str) -> None:
    cliente = _cliente()
    with cliente.conexao() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE public.acessorias_busca SET estado = 'descartada', plano = '{}'::jsonb, "
                "decidida_por_email = %s, decidida_em = now() WHERE id = %s AND estado = 'aguardando'",
                (por_email, busca_id),
            )
            if cur.rowcount == 0:
                raise ErroAcessorias("esta busca não está aguardando confirmação")


def situacao(limite: int = 10) -> dict:
    """Para a tela: as últimas buscas (sem os dados guardados) e a que aguarda."""
    cliente = _cliente()
    with cliente.conexao() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT id, origem, disparada_por_email, iniciada_em, terminada_em, estado, paginas, empresas, "
            "erro, resumo, aplicada_em, decidida_por_email, decidida_em "
            "FROM public.acessorias_busca ORDER BY iniciada_em DESC LIMIT %s",
            (limite,),
        )
        buscas = cur.fetchall()
    for b in buscas:
        for k in ("iniciada_em", "terminada_em", "aplicada_em", "decidida_em"):
            if b.get(k) is not None:
                b[k] = b[k].isoformat()
    return {
        "configurado": bool(config.ACESSORIAS_API_TOKEN),
        "buscas": buscas,
        "aguardando": next((b for b in buscas if b["estado"] == "aguardando"), None),
        "ultima_aplicada": next((b for b in buscas if b.get("aplicada_em")), None),
    }


# ──────────────────────────────────────────────────────────────────────────
# 4. Departamentos (tela Configuração › Acessórias)
# ──────────────────────────────────────────────────────────────────────────

def _contagem_da_copia(cur, email: Optional[str] = None) -> Dict[str, Dict[int, int]]:
    """A mesma contagem de `contar_responsabilidades`, lida da cópia aplicada."""
    sql = ("SELECT r.email, r.departamento_acessorias_id AS d, count(*) AS n "
           "FROM public.acessorias_responsavel r JOIN public.acessorias_empresa e ON e.cnpj = r.cnpj AND e.ativa "
           "WHERE r.email <> ''" + (" AND r.email = %s" if email else "") + " GROUP BY 1, 2")
    cur.execute(sql, (email,) if email else None)
    contagem: Dict[str, Dict[int, int]] = {}
    for r in cur.fetchall():
        contagem.setdefault(r["email"], {})[r["d"]] = r["n"]
    return contagem


def departamentos_situacao() -> dict:
    cliente = _cliente()
    with cliente.conexao() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT a.id, a.nome, a.conta_para_carteira AS trazer, a.departamento_id::text AS departamento_id, "
            "d.nome AS departamento_nome, "
            "(SELECT count(DISTINCT r.email) FROM public.acessorias_responsavel r WHERE r.departamento_acessorias_id = a.id "
            " AND r.email <> '') AS responsaveis, "
            "(SELECT count(*) FROM public.acessorias_responsavel r WHERE r.departamento_acessorias_id = a.id "
            " AND r.email <> '') AS empresas "
            "FROM public.acessorias_departamento a LEFT JOIN public.departamento d ON d.id = a.departamento_id "
            "ORDER BY (a.conta_para_carteira) DESC, responsaveis DESC, a.nome"
        )
        acessorias_deps = cur.fetchall()
        cur.execute(
            "SELECT d.id::text AS id, d.nome, d.arquivado, "
            "(SELECT count(*) FROM public.users u WHERE u.departamento_id = d.id AND u.ativo) AS membros "
            "FROM public.departamento d WHERE NOT EXISTS "
            "(SELECT 1 FROM public.acessorias_departamento a WHERE a.departamento_id = d.id) ORDER BY d.arquivado, d.nome"
        )
        sem_par = cur.fetchall()
        mapa = _mapa_de_departamentos(cur)
        nomes_acess = {d["id"]: d["nome"] for d in acessorias_deps}
        cur.execute("SELECT id::text AS id, lower(email) AS email, full_name, departamento_id::text AS departamento_id "
                    "FROM public.users WHERE ativo AND role <> 'admin'")
        contas = cur.fetchall()
        contagem = _contagem_da_copia(cur)
    a_decidir = []
    for c in contas:
        cont = contagem.get(c["email"])
        if cont and sugestao_de_departamento(cont, mapa) is None:
            a_decidir.append({
                "id": c["id"], "email": c["email"], "nome": c["full_name"] or c["email"],
                "departamento_id": c["departamento_id"],
                "contagem": [{"departamento": nomes_acess.get(k, str(k)), "empresas": n}
                             for k, n in sorted(cont.items(), key=lambda kv: -kv[1])],
            })
    return {"acessorias": acessorias_deps, "portal_sem_par": sem_par,
            "a_decidir": sorted(a_decidir, key=lambda x: x["nome"].lower())}


def configurar_departamento(acessorias_id: int, trazer: Optional[bool] = None,
                            departamento_id: Optional[str] = None, desligar_par: bool = False) -> dict:
    """Chave "trazer" e a ligação com o departamento do portal.

    Ligar "trazer" já cria (ou liga pelo nome) o departamento no portal.
    Desligar não tira nada agora: os acessos vindos dele saem na próxima
    busca, passando pela trava.
    """
    cliente = _cliente()
    with cliente.conexao() as conn, conn.transaction(), conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT pg_advisory_xact_lock(%s)", (_TRAVA_APLICACAO,))
        cur.execute("SELECT id FROM public.acessorias_departamento WHERE id = %s", (acessorias_id,))
        if not cur.fetchone():
            raise ErroAcessorias("departamento do Acessórias não encontrado")
        if desligar_par:
            cur.execute("UPDATE public.acessorias_departamento SET departamento_id = NULL WHERE id = %s", (acessorias_id,))
        elif departamento_id:
            departamento_id = _uuid(departamento_id)
            cur.execute("SELECT arquivado FROM public.departamento WHERE id = %s", (departamento_id,))
            alvo = cur.fetchone()
            if not alvo:
                raise ErroAcessorias("esse departamento do portal não existe mais")
            cur.execute("SELECT id, nome FROM public.acessorias_departamento WHERE departamento_id = %s AND id <> %s",
                        (departamento_id, acessorias_id))
            outro = cur.fetchone()
            if outro:
                raise ErroAcessorias(f"esse departamento do portal já está ligado a {outro['nome']} do Acessórias")
            cur.execute("UPDATE public.acessorias_departamento SET departamento_id = %s WHERE id = %s",
                        (departamento_id, acessorias_id))
            cur.execute("UPDATE public.departamento SET arquivado = false WHERE id = %s", (departamento_id,))
        if trazer is not None:
            cur.execute("UPDATE public.acessorias_departamento SET conta_para_carteira = %s WHERE id = %s",
                        (trazer, acessorias_id))
        res = _ligar_departamentos(cur, so_estes=[acessorias_id]) if trazer else {}
    return {"ok": True, **res}


def _uuid(valor: str) -> str:
    import uuid

    try:
        return str(uuid.UUID(str(valor)))
    except ValueError:
        raise ErroAcessorias("departamento não encontrado") from None


def arquivar_departamento(departamento_id: str, arquivado: bool) -> None:
    departamento_id = _uuid(departamento_id)
    cliente = _cliente()
    with cliente.conexao() as conn, conn.cursor() as cur:
        cur.execute("UPDATE public.departamento SET arquivado = %s WHERE id = %s", (arquivado, departamento_id))
        if cur.rowcount == 0:
            raise ErroAcessorias("departamento não encontrado")


def registrar_mudanca_manual(user_id: str, novo_departamento: str, por_email: str) -> None:
    """O Administrador pôs a pessoa num departamento: se for diferente do que o
    Acessórias sugere, a sugestão vira recusa e a busca não a desfaz. Se for o
    sugerido, a recusa antiga sai. Nunca levanta: é anotação, não barreira."""
    try:
        cliente = _cliente()
        with cliente.conexao() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT lower(email) AS email FROM public.users WHERE id = %s", (user_id,))
            conta = cur.fetchone()
            if not conta:
                return
            cont = _contagem_da_copia(cur, conta["email"]).get(conta["email"])
            sug = sugestao_de_departamento(cont or {}, _mapa_de_departamentos(cur))
            cur.execute("DELETE FROM public.acessorias_recusa WHERE tipo = 'departamento' AND user_id = %s", (user_id,))
            if sug and sug != novo_departamento:
                cur.execute(
                    "INSERT INTO public.acessorias_recusa (tipo, user_id, chave, motivo, recusado_por_email) "
                    "VALUES ('departamento', %s, %s, 'mudanca_manual', %s)",
                    (user_id, sug, por_email),
                )
    except ErroAcessorias:
        return
    except Exception:  # noqa: BLE001
        logger.exception("Mudança manual de departamento de %s não foi anotada para o Acessórias", user_id)


# ──────────────────────────────────────────────────────────────────────────
# 5. A virada (ADR 0005)
# ──────────────────────────────────────────────────────────────────────────

_sincronizado = {"valor": False, "em": -1e9}


def sincronizado() -> bool:
    """A virada já aconteceu (alguma busca foi aplicada)?

    Depois dela a carteira do Operador segue o Acessórias e retirar vira
    bloqueio. O Gestor continua "tudo menos as Exceções" (adendo de 23/10 ao
    ADR 0005). A virada é de mão única: verdadeiro uma vez, verdadeiro para
    sempre no processo. Falso é conferido de novo a cada 30 s.

    Sem a conexão direta do db_pg (os clientes falsos dos testes) responde
    falso; erro do banco de verdade sobe, para o alcance virar 503 e nunca
    cair no modelo mais largo por engano.
    """
    if _sincronizado["valor"]:
        return True
    if time.monotonic() - _sincronizado["em"] < 30:
        return False
    try:
        cliente = _cliente()
    except ErroAcessorias:
        return False
    with cliente.conexao() as conn, conn.cursor() as cur:
        cur.execute("SELECT EXISTS (SELECT 1 FROM public.acessorias_busca WHERE aplicada_em IS NOT NULL)")
        valor = bool(cur.fetchone()[0])
    _sincronizado.update(valor=valor, em=time.monotonic())
    return valor


# ──────────────────────────────────────────────────────────────────────────
# 6. Bloqueio e liberação manual (ADR 0005)
# ──────────────────────────────────────────────────────────────────────────

def retirar(user_id: str, documento: str, por_id: Optional[str], por_email: str) -> bool:
    """Tira o documento da carteira depois da virada. Devolve se bloqueou.

    O que veio do Acessórias voltaria na busca seguinte; por isso retirar é
    bloquear (a busca respeita o bloqueio). Liberado à mão só sai. A trava
    é a da aplicação: uma busca no meio não lê a carteira sem o bloqueio.
    """
    doc = so_digitos(documento)
    cliente = _cliente()
    with cliente.conexao() as conn, conn.transaction(), conn.cursor() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(%s)", (_TRAVA_APLICACAO,))
        cur.execute(
            "DELETE FROM public.carteira WHERE user_id = %s AND documento = %s RETURNING origem",
            (user_id, doc),
        )
        linha = cur.fetchone()
        if not linha or linha[0] != "acessorias":
            return False
        cur.execute(
            "INSERT INTO public.carteira_bloqueio (user_id, documento, bloqueado_por, bloqueado_por_email) "
            "VALUES (%s, %s, %s, %s) ON CONFLICT (user_id, documento) DO NOTHING",
            (user_id, doc, por_id, por_email),
        )
        cur.execute("SELECT email FROM public.users WHERE id = %s", (user_id,))
        email = (cur.fetchone() or [""])[0] or ""
        cur.execute(
            "INSERT INTO public.carteira_historico "
            "(user_id, user_email, documento, movimento, origem, feito_por, feito_por_email) "
            "VALUES (%s, %s, %s, 'saida', 'bloqueio', %s, %s)",
            (user_id, email, doc, por_id, por_email),
        )
    return True


def desbloquear(user_id: str, documentos: Iterable[str]) -> int:
    """Atribuir à mão desfaz o bloqueio daquele documento para aquela pessoa."""
    docs = [d for d in (so_digitos(x) for x in documentos) if d]
    if not docs:
        return 0
    cliente = _cliente()
    with cliente.conexao() as conn, conn.cursor() as cur:
        cur.execute(
            "DELETE FROM public.carteira_bloqueio WHERE user_id = %s AND documento = ANY(%s)",
            (user_id, docs),
        )
        return cur.rowcount


def bloqueios(user_id: str) -> List[Dict[str, Any]]:
    """Os bloqueios da pessoa, com quem bloqueou e quando (para a tela)."""
    cliente = _cliente()
    with cliente.conexao() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT documento, bloqueado_por_email, bloqueado_em FROM public.carteira_bloqueio "
            "WHERE user_id = %s ORDER BY documento",
            (user_id,),
        )
        return [
            {"documento": l["documento"], "bloqueado_por": l["bloqueado_por_email"],
             "bloqueado_em": l["bloqueado_em"].isoformat() if l["bloqueado_em"] else None}
            for l in cur.fetchall()
        ]
