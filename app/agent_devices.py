"""
Identidade do agente: quem, e não só qual chave.

Até 22/08/2026 o agente autenticava-se por `X-API-Key` — um segredo ÚNICO para
toda a instalação (`main.require_auth`, ramo 2). Enquanto existiu UM agente, num
servidor sob controlo da operação, isso era proporcional. Distribuí-lo por uma
frota de estações não é: o valor fica no disco de cada máquina, e quem o lê fala
pelo portal inteiro com papel `agent` — que é justamente o papel que `/redeem`
aceita para entregar chave privada.

Aqui cada par (pessoa, máquina) tem segredo próprio, revogável um a um, e o
portal passa a saber DE QUEM é a máquina. É o que permitirá enfileirar um
comando de instalação para "a estação da Ana" sem ninguém escolher `machine_id`
numa lista.

── O agente nunca guarda a senha do portal ───────────────────────────────

`registrar` recebe a senha uma vez, na janela de login, e devolve um segredo de
dispositivo. A senha é descartada ali. Um segredo vazado custa uma revogação; a
senha do portal vazada custa a conta inteira — e ela vale também para o
navegador, onde estão as outras telas.

── Por que sha256, e não bcrypt como `users.password_hash` ───────────────

Duas razões, e a segunda não é preferência:

1. O segredo tem 32 bytes de `secrets.token_urlsafe`. Não é escolhido por
   humano e não cai em dicionário. O fator de custo do bcrypt existe para
   encarecer o palpite; não há palpite a encarecer.

2. O hash precisa ser DETERMINÍSTICO. O agente apresenta só o segredo, e a
   troca por JWT tem de achar a linha por igualdade. Com hash salgado seria
   varrer a tabela inteira a cada renovação, correndo bcrypt em cada linha até
   casar.

É o mesmo raciocínio do `install_token`, e o oposto do de `senha_reset`: lá,
seis dígitos não carregam garantia nenhuma sozinhos e o custo do hash importa.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

TABELA = "agent_devices"

# 32 bytes de entropia. `token_urlsafe` devolve ~43 caracteres do mesmo alfabeto
# do `install_token`, o que o torna seguro de pôr em JSON e em linha de comando.
BYTES_DO_SEGREDO = 32

# O laço do agente roda a cada 10 s (`run_agent.py:1180`). Três minutos são
# dezoito rondas perdidas: quem não apareceu nesse tempo não está lá para
# receber comando nenhum, e enfileirar para ele produziria um pedido que fica
# pendurado sem ninguém consumir.
JANELA_VIVO_SEG = 180

# O JWT que o agente recebe em troca do segredo. Curto de propósito: o segredo
# é que é a credencial durável, e ele está sob revogação. Um token de 24 h como
# o do navegador sobreviveria à revogação por um dia inteiro.
VALIDADE_TOKEN_MIN = 60


class SemBanco(RuntimeError):
    """Supabase não configurado. Dispositivos não têm fallback em arquivo."""


def _supabase():
    from app.settings_state import _supabase as _sb

    return _sb()


def _exigir_banco():
    sb = _supabase()
    if not sb:
        raise SemBanco(
            "Dispositivos do agente exigem Supabase configurado."
        )
    return sb


def _agora() -> datetime:
    return datetime.now(timezone.utc)


def _hash(segredo: str) -> str:
    return hashlib.sha256((segredo or "").strip().encode("utf-8")).hexdigest()


def gerar_segredo() -> str:
    return secrets.token_urlsafe(BYTES_DO_SEGREDO)


def _sem_segredo(linha: Dict[str, Any]) -> Dict[str, Any]:
    """
    A linha sem o `segredo_hash`, para sair pela API.

    Explícito em vez de `select` restrito porque estas linhas chegam por
    caminhos diferentes (registrar devolve o que inseriu, listar devolve o que
    leu) e um `select("*")` esquecido num deles vazaria o hash para a tela.
    """
    return {k: v for k, v in linha.items() if k != "segredo_hash"}


def registrar(user_id: str, machine_id: str, nome: str = "") -> str:
    """
    Cria — ou substitui — o dispositivo desta pessoa nesta máquina.

    Devolve o segredo em claro. É a ÚNICA vez que ele existe fora do agente: o
    banco guarda só o hash, e não há como reemitir sem registrar de novo.

    Registrar de novo na mesma estação substitui o segredo e limpa a revogação.
    A alternativa — recusar quando já existe — deixaria quem perdeu o segredo
    (reinstalação do Windows, perfil novo) sem saída pela interface, que é
    exatamente o buraco que a recuperação de senha veio tapar em 17/08.
    """
    sb = _exigir_banco()
    mid = (machine_id or "").strip() or "default"
    segredo = gerar_segredo()
    linha = {
        "user_id": user_id,
        "machine_id": mid,
        "nome": (nome or "").strip()[:120],
        "segredo_hash": _hash(segredo),
        "revogado_em": None,
    }

    existente = (
        sb.table(TABELA)
        .select("id")
        .eq("user_id", user_id)
        .eq("machine_id", mid)
        .limit(1)
        .execute()
    ).data
    if existente:
        sb.table(TABELA).update(linha).eq("id", existente[0]["id"]).execute()
    else:
        linha["criado_em"] = _agora().isoformat()
        sb.table(TABELA).insert(linha).execute()
    return segredo


def autenticar(segredo: str) -> Optional[Dict[str, Any]]:
    """
    Devolve o dispositivo dono deste segredo, ou None.

    Marca `visto_em` a cada acerto — é o mesmo carimbo que responde depois
    "esta máquina está viva?". Uni-los é de propósito: um heartbeat separado
    poderia continuar batendo com o segredo já inválido, e o portal enfileiraria
    comando para uma máquina que não consegue mais consumi-lo.

    A comparação do hash usa `compare_digest`. O ganho aqui é pequeno — a busca
    é no índice do Postgres, não numa varredura em Python —, mas a linha é
    barata e o dia em que alguém trocar a busca por um laço local ela já está
    no lugar certo.
    """
    if not (segredo or "").strip():
        return None
    sb = _exigir_banco()
    alvo = _hash(segredo)
    r = sb.table(TABELA).select("*").eq("segredo_hash", alvo).limit(1).execute()
    linhas = r.data or []
    if not linhas:
        return None
    linha = linhas[0]
    if not hmac.compare_digest(str(linha.get("segredo_hash") or ""), alvo):
        return None
    if linha.get("revogado_em"):
        return None

    agora = _agora().isoformat()
    try:
        sb.table(TABELA).update({"visto_em": agora}).eq("id", linha["id"]).execute()
        linha["visto_em"] = agora
    except Exception:  # noqa: BLE001
        # Falhar em carimbar não pode negar acesso a quem apresentou segredo
        # válido: o pior efeito é a máquina parecer parada na tela.
        logger.exception("Falha ao carimbar visto_em do dispositivo %s", linha.get("id"))
    return linha


def esta_vivo(linha: Dict[str, Any], agora: Optional[datetime] = None) -> bool:
    """Apareceu dentro da janela e não foi revogado."""
    if linha.get("revogado_em"):
        return False
    visto = linha.get("visto_em")
    if not visto:
        return False
    try:
        quando = datetime.fromisoformat(str(visto).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return False
    if quando.tzinfo is None:
        quando = quando.replace(tzinfo=timezone.utc)
    return (agora or _agora()) - quando <= timedelta(seconds=JANELA_VIVO_SEG)


def listar(user_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Dispositivos, com `vivo` já calculado. Sem `user_id`, devolve todos — quem
    decide o alcance é a rota, não este módulo.
    """
    sb = _exigir_banco()
    q = sb.table(TABELA).select("*")
    if user_id:
        q = q.eq("user_id", user_id)
    linhas = (q.execute()).data or []
    agora = _agora()
    saida = []
    for linha in linhas:
        item = _sem_segredo(linha)
        item["vivo"] = esta_vivo(linha, agora)
        saida.append(item)
    saida.sort(key=lambda d: str(d.get("criado_em") or ""), reverse=True)
    return saida


def vivos_do_usuario(user_id: str) -> List[Dict[str, Any]]:
    """As máquinas desta pessoa que podem receber comando agora."""
    return [d for d in listar(user_id) if d.get("vivo")]


def revogar(device_id: str, user_id: Optional[str] = None) -> bool:
    """
    Invalida o segredo. Com `user_id`, só revoga se o dispositivo for dele — a
    barreira mora aqui e não só na rota, para o dia em que uma segunda rota
    chamar isto.

    Devolve False quando não achou nada para revogar, o que a rota traduz em
    404. Revogar duas vezes é inofensivo e mantém a primeira data.
    """
    sb = _exigir_banco()
    q = sb.table(TABELA).select("*").eq("id", device_id)
    if user_id:
        q = q.eq("user_id", user_id)
    linhas = (q.limit(1).execute()).data or []
    if not linhas:
        return False
    if linhas[0].get("revogado_em"):
        return True
    sb.table(TABELA).update({"revogado_em": _agora().isoformat()}).eq(
        "id", device_id
    ).execute()
    return True
