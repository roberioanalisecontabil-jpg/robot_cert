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
  * pedido novo invalida os anteriores, senão as tentativas se acumulam

É o oposto do `install_token`, onde 32 bytes aleatórios carregavam a garantia
sozinhos.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

TABELA = "password_reset_codigo"

DIGITOS = 6
VALIDADE_MIN = 15
MAX_TENTATIVAS = 3
MAX_PEDIDOS_HORA = 3


class LimiteDePedidos(RuntimeError):
    """A conta já pediu códigos demais na última hora."""


def _supabase():
    from app.settings_state import _supabase as _sb

    return _sb()


def _hash(codigo: str) -> str:
    return hashlib.sha256(codigo.strip().encode("utf-8")).hexdigest()


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


def criar_codigo(user_id: str, client_ip: Optional[str] = None) -> str:
    """
    Invalida os códigos anteriores da conta e devolve um novo, em claro.

    O valor em claro só existe aqui e no e-mail: a tabela guarda o hash.

    Levanta `LimiteDePedidos` se a conta estourou `MAX_PEDIDOS_HORA`. O teto é
    por CONTA, e não por IP: quem ataca troca de IP com facilidade, mas o alvo
    continua sendo a mesma conta.
    """
    sb = _supabase()
    if not sb:
        raise RuntimeError("Supabase não configurado")

    agora = _agora()
    desde = (agora - timedelta(hours=1)).isoformat()

    recentes = (
        sb.table(TABELA)
        .select("id")
        .eq("user_id", user_id)
        .gt("created_at", desde)
        .execute()
    )
    if len(recentes.data or []) >= MAX_PEDIDOS_HORA:
        raise LimiteDePedidos(user_id)

    # Queima o que estava pendente ANTES de criar o novo. Sem isto, os códigos
    # antigos continuariam válidos e as 3 tentativas de cada um se somariam —
    # o teto de tentativas viraria "3 vezes o número de pedidos".
    sb.table(TABELA).update({"consumed_at": agora.isoformat()}).eq(
        "user_id", user_id
    ).is_("consumed_at", "null").execute()

    codigo = gerar_codigo()
    sb.table(TABELA).insert(
        {
            "user_id": user_id,
            "codigo_hash": _hash(codigo),
            # `created_at` explícito, e não deixado para o DEFAULT da coluna: é
            # por ele que o teto de pedidos conta. Linha sem `created_at` não
            # casaria com o filtro `> uma hora atrás`, e o limitador passaria a
            # contar zero — abrindo exatamente o buraco que ele fecha, sem
            # nenhum sintoma. O DEFAULT continua na tabela como rede.
            "created_at": agora.isoformat(),
            "expires_at": (agora + timedelta(minutes=VALIDADE_MIN)).isoformat(),
            "client_ip": client_ip,
        }
    ).execute()
    return codigo


def _vigente(sb, user_id: str) -> Optional[Dict[str, Any]]:
    """O código não consumido e não expirado da conta, se houver."""
    r = (
        sb.table(TABELA)
        .select("id, codigo_hash, tentativas, expires_at")
        .eq("user_id", user_id)
        .is_("consumed_at", "null")
        .gt("expires_at", _agora().isoformat())
        .execute()
    )
    linhas = r.data or []
    return linhas[0] if linhas else None


def conferir(user_id: str, codigo: str) -> Tuple[bool, Optional[str]]:
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
    """
    sb = _supabase()
    if not sb:
        return False, None

    linha = _vigente(sb, user_id)
    if not linha:
        return False, None

    # `compare_digest` em vez de `==`: comparação de string sai cedo no
    # primeiro byte diferente, e o tempo de resposta vaza quantos dígitos
    # iniciais estavam certos. Com 6 dígitos e 3 tentativas isso é margem
    # estreita, mas o custo de fechar é uma linha.
    if hmac.compare_digest(str(linha.get("codigo_hash") or ""), _hash(codigo)):
        return True, str(linha["id"])

    tentativas = int(linha.get("tentativas") or 0) + 1
    campos: Dict[str, Any] = {"tentativas": tentativas}
    if tentativas >= MAX_TENTATIVAS:
        campos["consumed_at"] = _agora().isoformat()
        logger.info("Código de redefinição queimado após %d erros.", tentativas)
    sb.table(TABELA).update(campos).eq("id", linha["id"]).execute()
    return False, None


def consumir(user_id: str, codigo: str) -> bool:
    """
    Confere e consome, de uma vez. É o passo final da redefinição.

    O consumo é um compare-and-swap: o UPDATE traz `consumed_at IS NULL` na
    própria cláusula WHERE. O Postgres serializa UPDATEs concorrentes na mesma
    linha, então exatamente um deles encontra a condição verdadeira e escreve;
    o outro casa com zero linhas. Sem isso, "uso único" seria só intenção —
    dois envios simultâneos passariam ambos pela leitura antes de qualquer
    escrita.
    """
    sb = _supabase()
    if not sb:
        return False

    ok, linha_id = conferir(user_id, codigo)
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
    sb = _supabase()
    if not sb:
        return 0
    corte = (_agora() - timedelta(days=dias)).isoformat()
    try:
        r = sb.table(TABELA).delete().lt("expires_at", corte).execute()
        return len(r.data or [])
    except Exception:  # noqa: BLE001
        logger.exception("Falha ao limpar códigos de redefinição expirados")
        return 0
