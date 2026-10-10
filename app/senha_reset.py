"""
Recuperação de senha por código de 6 dígitos.

Até 17/08/2026 quem esquecia a senha não tinha saída pela interface: dependia
de um admin abrir `/usuarios` e redefinir por ele (achado A8 da auditoria de
UI/UX de 02/08).

── Código, e não link ────────────────────────────────────────────────────

O e-mail leva um código que a pessoa digita no portal. Um link exigiria URL
absoluta, e montá-la a partir do cabeçalho `Host` — que quem chama controla —
permitiria pedir recuperação para a vítima com um Host forjado: ela receberia
um e-mail legítimo do portal e entregaria o token ao atacante ao clicar. É
*host header injection*, e some inteira quando não há link.

── O que de fato protege ─────────────────────────────────────────────────

Seis dígitos são 1 milhão de combinações. O hash em repouso protege **pouco**:
quem tivesse leitura da tabela reverteria um sha256 de 6 dígitos em segundos.
Ele entra como defesa em profundidade — impede leitura casual pelo Studio —
mas a segurança real é a soma dos limites abaixo, e por isso nenhum deles é
opcional:

  * `VALIDADE_MIN`      — janela curta
  * `MAX_TENTATIVAS`    — o código QUEIMA no terceiro erro, não fica adivinhável
  * `MAX_PEDIDOS_HORA`  — sem teto, 3 tentativas por código não valem nada:
                          bastaria pedir mil códigos para ter três mil chances
    (por conta E endereço de origem; `MAX_PEDIDOS_HORA_CONTA` por conta)
  * pedido novo invalida os anteriores, senão as tentativas se acumulam

── Concorrência (auditoria de 10/10/2026) ────────────────────────────────

Cada `execute()` é uma instrução em autocommit, então "ler, decidir, gravar"
em três instruções não é atômico: pedidos simultâneos leem o mesmo estado.
Os limites acima só valem se a decisão estiver DENTRO da instrução que grava:

  * tentativa: reservada por compare-and-swap (`UPDATE ... WHERE tentativas
    = <lido>`) ANTES de comparar o palpite — quem perde a corrida relê;
  * teto de pedidos: conta-se DEPOIS de inserir, e quem passou do teto apaga
    a própria linha — dois pedidos no limite não passam os dois.

Residual aceito: um anônimo que saiba o e-mail ainda pode invalidar o código
da vítima pedindo outro (até o teto do endereço dele) ou queimá-lo com 3
erros. Não ganha acesso, só atrasa; o envio pelo administrador (`pelo_admin`)
fica fora dos tetos anônimos e continua sendo a saída.

É o oposto do `install_token`, onde 32 bytes aleatórios carregavam a garantia
sozinhos.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

TABELA = "password_reset_codigo"

DIGITOS = 6
VALIDADE_MIN = 15
MAX_TENTATIVAS = 3
# Por conta e endereço de origem. Por conta só, um anônimo que soubesse o
# e-mail esgotava o teto da vítima com 3 pedidos e a recuperação dela parava.
MAX_PEDIDOS_HORA = 3
# Por conta, somando os endereços: segura quem troca de IP. 10 códigos x 3
# tentativas = 30 palpites/hora em 10^6, e o admin continua enviando por fora.
MAX_PEDIDOS_HORA_CONTA = 10

# Para quê o código serve. Um código de LOGIN nunca redefine senha, e vice-versa:
# cada propósito tem as próprias linhas, a própria conferência e os próprios
# tetos (login com código, 10/10/2026). Linhas antigas são `senha` (DEFAULT).
SENHA, LOGIN = "senha", "login"
# (por conta e endereço, por conta) — o login pede mais códigos ao longo do dia.
TETOS = {SENHA: (MAX_PEDIDOS_HORA, MAX_PEDIDOS_HORA_CONTA), LOGIN: (5, 15)}
# Releituras quando outro pedido mexe na mesma linha entre a leitura e a escrita.
_MAX_CORRIDAS = 5


class LimiteDePedidos(RuntimeError):
    """A conta já pediu códigos demais na última hora."""


def _banco():
    from app.settings_state import _banco as _sb

    return _sb()


PREFIXO_HASH = "v2$"


def _segredo() -> bytes:
    """A chave do HMAC é o segredo do JWT: já é o segredo do servidor que o
    login exige, e não há motivo para um segundo."""
    s = (os.getenv("JWT_SECRET_KEY") or "").strip()
    if not s:
        raise RuntimeError("JWT_SECRET_KEY não configurada no ambiente.")
    return s.encode("utf-8")


def _hash(codigo: str, sal: Optional[str] = None) -> str:
    """`v2$<sal>$<hmac>` — HMAC-SHA256 com o segredo do servidor e sal por linha
    (SECURITY_AUDIT #56, lote 8).

    O SHA-256 puro de 6 dígitos era uma tabela de 10^6 entradas: quem lesse a
    coluna revertia TODOS os códigos pendentes de uma vez. Com sal por linha
    a tabela vale para uma linha só, e com o HMAC ela nem se monta sem o
    segredo do servidor. Os limites (validade, 3 tentativas, 3 pedidos/hora)
    continuam sendo a proteção principal — isto é defesa em profundidade.
    """
    sal = sal or secrets.token_hex(8)
    mac = hmac.new(_segredo(), (sal + codigo.strip()).encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{PREFIXO_HASH}{sal}${mac}"


def _hash_legado(codigo: str) -> str:
    return hashlib.sha256(codigo.strip().encode("utf-8")).hexdigest()


def _confere(guardado: str, codigo: str) -> bool:
    """O código bate com o hash guardado, no formato que ele tiver.

    Formato antigo (sha256 puro) continua aceito: um código pedido antes do
    deploy vale 15 minutos e tem de funcionar. A janela se fecha sozinha —
    nenhum hash novo nasce no formato antigo — e o aceite fica no log.
    """
    guardado = str(guardado or "")
    if guardado.startswith(PREFIXO_HASH):
        partes = guardado.split("$", 2)
        if len(partes) != 3:
            return False
        return hmac.compare_digest(guardado, _hash(codigo, sal=partes[1]))
    ok = hmac.compare_digest(guardado, _hash_legado(codigo))
    if ok:
        logger.warning("Código de redefinição aceito no formato antigo (sha256 sem sal); "
                       "some sozinho quando os códigos pendentes expirarem.")
    return ok


def gerar_codigo() -> str:
    """
    Seis dígitos, com zeros à esquerda preservados.

    `secrets.randbelow`, e não `random`: o módulo `random` é um Mersenne
    Twister previsível a partir de saídas observadas, e aqui a saída vai por
    e-mail para alguém que pode ser o atacante pedindo o próprio código.
    """
    return f"{secrets.randbelow(10 ** DIGITOS):0{DIGITOS}d}"


def _agora() -> datetime:
    return datetime.now(timezone.utc)


def criar_codigo(user_id: str, client_ip: Optional[str] = None, *, pelo_admin: bool = False,
                 proposito: str = SENHA) -> str:
    """
    Invalida os códigos anteriores da conta e devolve um novo, em claro.

    O valor em claro só existe aqui e no e-mail: a tabela guarda o hash.

    Levanta `LimiteDePedidos` se o pedido passou de `MAX_PEDIDOS_HORA` para a
    conta naquele endereço de origem, ou de `MAX_PEDIDOS_HORA_CONTA` para a
    conta. Até 10/10/2026 o teto era só por conta: um anônimo que soubesse o
    e-mail o esgotava com 3 pedidos, e nem a vítima nem o administrador
    conseguiam mais gerar código naquela hora.

    `pelo_admin` (envio pela tela Usuários) não passa pelos tetos: a rota é
    autenticada e tem limite próprio, e é a saída que sobra à vítima quando um
    anônimo está gastando os pedidos dela.
    """
    sb = _banco()
    if not sb:
        raise RuntimeError("Banco não configurado")

    agora = _agora()
    desde = (agora - timedelta(hours=1)).isoformat()

    codigo = gerar_codigo()
    inserida = sb.table(TABELA).insert(
        {
            "user_id": user_id,
            "codigo_hash": _hash(codigo),
            # `created_at` explícito, e não deixado para o DEFAULT da coluna: é
            # por ele que o teto de pedidos conta e que o código mais novo
            # vence. Linha sem `created_at` não casaria com o filtro `> uma
            # hora atrás`, e o limitador passaria a contar zero — abrindo
            # exatamente o buraco que ele fecha, sem nenhum sintoma.
            "created_at": agora.isoformat(),
            "expires_at": (agora + timedelta(minutes=VALIDADE_MIN)).isoformat(),
            "client_ip": client_ip,
            # Explícito como o `created_at`: o compare-and-swap de `conferir`
            # parte deste valor, e não pode depender do DEFAULT da coluna.
            "tentativas": 0,
            "proposito": proposito,
        }
    ).execute()
    nova_id = ((inserida.data or [{}])[0]).get("id")

    # O teto conta DEPOIS de inserir, incluindo a própria linha. Contado antes,
    # dois pedidos simultâneos viam o mesmo número abaixo do teto e passavam os
    # dois. Assim, quem chega por último enxerga o outro e fica de fora. A
    # linha recusada é APAGADA, não queimada: queimada continuaria contando, e
    # pedidos recusados encheriam o teto da conta para quem pede de outro lugar.
    if not pelo_admin:
        recentes = (
            sb.table(TABELA).select("id, client_ip").eq("user_id", user_id).eq("proposito", proposito)
            .gt("created_at", desde).execute()
        ).data or []
        do_endereco = [x for x in recentes if (x.get("client_ip") or None) == (client_ip or None)]
        teto_endereco, teto_conta = TETOS.get(proposito, TETOS[SENHA])
        if len(recentes) > teto_conta or len(do_endereco) > teto_endereco:
            if nova_id is not None:
                sb.table(TABELA).delete().eq("id", nova_id).execute()
            raise LimiteDePedidos(user_id)

    # Queima o que estava pendente. Sem isto, os códigos antigos continuariam
    # válidos e as 3 tentativas de cada um se somariam — o teto de tentativas
    # viraria "3 vezes o número de pedidos". Só os MAIS ANTIGOS que este: um
    # pedido simultâneo que também passou queima o mais velho dos dois, e não
    # os dois um ao outro.
    pendentes = (
        sb.table(TABELA).select("id, created_at").eq("user_id", user_id).eq("proposito", proposito)
        .is_("consumed_at", "null").execute()
    ).data or []
    for p in pendentes:
        if p.get("id") != nova_id and str(p.get("created_at") or "") < agora.isoformat():
            sb.table(TABELA).update({"consumed_at": agora.isoformat()}).eq("id", p["id"]).is_(
                "consumed_at", "null"
            ).execute()
    return codigo


def _vigente(sb, user_id: str, proposito: str = SENHA) -> Optional[Dict[str, Any]]:
    """O código não consumido e não expirado mais novo da conta, se houver.

    Normalmente há um só. Se uma corrida deixar dois vivos por um instante,
    vale o mais novo — o que a pessoa acabou de receber — e a escolha não pode
    depender da ordem em que o banco devolve as linhas.
    """
    r = (
        sb.table(TABELA)
        .select("id, codigo_hash, tentativas, expires_at, created_at")
        .eq("user_id", user_id)
        .eq("proposito", proposito)
        .is_("consumed_at", "null")
        .gt("expires_at", _agora().isoformat())
        .execute()
    )
    linhas = r.data or []
    if not linhas:
        return None
    return max(linhas, key=lambda x: str(x.get("created_at") or ""))


def conferir(user_id: str, codigo: str, proposito: str = SENHA) -> Tuple[bool, Optional[str]]:
    """
    O código bate? Devolve (ok, id_da_linha).

    **Sempre escopado por `user_id`.** Seis dígitos colidem entre pessoas —
    procurar só pelo código faria alguém digitar um número qualquer e cair na
    conta de outra pessoa.

    Erro incrementa `tentativas` e, no terceiro, QUEIMA o código: `consumed_at`
    é carimbado. Sem queimar, o atacante que errou três vezes pediria outro
    código e o anterior continuaria adivinhável.

    Não distingue "não existe", "expirou", "já foi usado" e "está errado" para
    o chamador — a distinção viraria oráculo.

    A tentativa é RESERVADA no banco antes de o palpite ser comparado, por
    compare-and-swap no valor lido (`tentativas = <lido>` no WHERE). Até
    10/10/2026 a ordem era ler, comparar e só então gravar `lido + 1`:
    palpites simultâneos liam todos zero e eram todos comparados, e o limite
    de 3 virava "quantos pedidos cabem na janela". Quem perde a corrida relê
    a linha; acertar devolve a tentativa, para o código certo no /verificar e
    de novo no /redefinir não gastar o que é de quem errou um dígito.
    """
    sb = _banco()
    if not sb:
        return False, None

    for _ in range(_MAX_CORRIDAS):
        linha = _vigente(sb, user_id, proposito)
        if not linha:
            return False, None
        usadas = int(linha.get("tentativas") or 0)
        if usadas >= MAX_TENTATIVAS:
            return False, None

        reservada = (
            sb.table(TABELA)
            .update({"tentativas": usadas + 1})
            .eq("id", linha["id"])
            .eq("tentativas", usadas)
            .is_("consumed_at", "null")
            .execute()
        )
        if not (reservada.data or []):
            continue  # outro pedido mexeu na linha entre a leitura e a escrita

        # `compare_digest` em vez de `==`: comparação de string sai cedo no
        # primeiro byte diferente, e o tempo de resposta vaza quantos dígitos
        # iniciais estavam certos. Com 6 dígitos e 3 tentativas isso é margem
        # estreita, mas o custo de fechar é uma linha.
        if _confere(str(linha.get("codigo_hash") or ""), codigo):
            sb.table(TABELA).update({"tentativas": usadas}).eq("id", linha["id"]).eq(
                "tentativas", usadas + 1
            ).execute()
            return True, str(linha["id"])

        if usadas + 1 >= MAX_TENTATIVAS:
            sb.table(TABELA).update({"consumed_at": _agora().isoformat()}).eq(
                "id", linha["id"]
            ).is_("consumed_at", "null").execute()
            logger.info("Código de redefinição queimado após %d erros.", usadas + 1)
        return False, None

    logger.warning("Conferência de código desistiu após %d corridas na mesma linha.", _MAX_CORRIDAS)
    return False, None


def consumir(user_id: str, codigo: str, proposito: str = SENHA) -> bool:
    """
    Confere e consome, de uma vez. É o passo final da redefinição.

    O consumo é um compare-and-swap: o UPDATE traz `consumed_at IS NULL` na
    própria cláusula WHERE. O Postgres serializa UPDATEs concorrentes na mesma
    linha, então exatamente um deles encontra a condição verdadeira e escreve;
    o outro casa com zero linhas. Sem isso, "uso único" seria só intenção —
    dois envios simultâneos passariam ambos pela leitura antes de qualquer
    escrita.
    """
    sb = _banco()
    if not sb:
        return False

    ok, linha_id = conferir(user_id, codigo, proposito)
    if not ok or not linha_id:
        return False

    r = (
        sb.table(TABELA)
        .update({"consumed_at": _agora().isoformat()})
        .eq("id", linha_id)
        .is_("consumed_at", "null")
        .execute()
    )
    if not (r.data or []):
        logger.info("Consumo de código recusado (corrida ou já consumido).")
        return False
    return True


def limpar_expirados(dias: int = 7) -> int:
    """Remove códigos vencidos há mais de `dias`. Não guardamos o que não serve."""
    sb = _banco()
    if not sb:
        return 0
    corte = (_agora() - timedelta(days=dias)).isoformat()
    try:
        r = sb.table(TABELA).delete().lt("expires_at", corte).execute()
        return len(r.data or [])
    except Exception:  # noqa: BLE001
        logger.exception("Falha ao limpar códigos de redefinição expirados")
        return 0
