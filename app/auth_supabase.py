"""
Login unificado: o robot_cert passa a aceitar contas do Supabase Auth.

Fase 3 do plano do agente único. Hoje este portal tem contas próprias — `users`
com `password_hash` em bcrypt e JWT emitido aqui. O INVENT usa Supabase Auth. A
decisão foi ter **uma lista só de pessoas**, e ela fica no projeto do INVENT.

── Por que isto é pequeno ────────────────────────────────────────────────

Porque `main._sessao_do_token` já resolve a conta **pelo e-mail** e reconstrói
papel, `user_id` e `deve_trocar_senha` a partir da linha em `users` — nunca do
token. O comentário de lá diz: "Reconstruído a partir da linha, nunca do token:
é o ponto inteiro daqui."

Então o token só precisa provar UM E-MAIL CONFIÁVEL. Matriz de permissões,
carteiras, revogação de sessão e senha provisória continuam exatamente como
estão. Este módulo só acrescenta uma segunda maneira de provar o e-mail.

── Não é sincronização ───────────────────────────────────────────────────

Nada é copiado entre os dois bancos. A tabela `users` daqui continua existindo
e mandando no que a pessoa PODE fazer; ela só deixa de guardar a senha. Duas
listas de pessoas divergiriam, e a que divergisse para o lado permissivo —
alguém desligado que continuou ativo de um lado — não daria sintoma nenhum.

── A transição aceita os dois ────────────────────────────────────────────

`require_auth` tenta primeiro o JWT deste portal e, se não for, tenta este
caminho. Os tokens não se confundem: os daqui trazem `iss=robot_cert_portal` e
`aud=robot_cert_users`, e a validação do outro é feita contra o servidor do
Supabase. Um nunca passa por engano no lugar do outro.

Recusar o token antigo no deploy deslogaria as 9 pessoas ativas de uma vez,
sem aviso. A mesma razão pela qual o token compartilhado do agente continuou
aceito na fase 2.

── Cache ────────────────────────────────────────────────────────────────

Validar exige ida ao Supabase. Sem cache seria uma chamada de rede POR
REQUISIÇÃO autenticada — o portal ficaria mais lento que o banco. Sessenta
segundos é o mesmo valor que o INVENT usa, e é curto o bastante para uma conta
desativada perder o acesso rápido; o corte definitivo continua sendo o
`_sessao_do_token`, que lê `users` a cada requisição e já derruba quem foi
desativado aqui.
"""

from __future__ import annotations

import logging
import os
import time
from threading import Lock
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

# O projeto Supabase que guarda as CONTAS. É o do INVENT, e de propósito não é
# o mesmo de `SUPABASE_URL` (que aqui aponta para os dados deste portal: cofre,
# certificados, snapshots). Separar os dois é o que mantém o cofre fora do
# alcance de qualquer código que só precise saber quem é a pessoa.
AUTH_SUPABASE_URL = (os.getenv("AUTH_SUPABASE_URL") or "").strip()
AUTH_SUPABASE_KEY = (os.getenv("AUTH_SUPABASE_KEY") or "").strip()

CACHE_TTL_SEG = 60.0

# email -> (validado_em, email)
_cache: dict[str, Tuple[float, str]] = {}
_lock = Lock()
_cliente = None


def configurado() -> bool:
    """Há projeto de contas apontado? Sem isto, só o login local funciona."""
    return bool(AUTH_SUPABASE_URL and AUTH_SUPABASE_KEY)


def _client():
    """Cliente do projeto de CONTAS, criado uma vez.

    Singleton pelo mesmo motivo de `settings_state._supabase`: cada
    `create_client` custa ~15-25 MB, e uma requisição autenticada não pode
    pagar isso.
    """
    global _cliente
    if _cliente is None:
        from supabase import create_client  # type: ignore[import-untyped]

        _cliente = create_client(AUTH_SUPABASE_URL, AUTH_SUPABASE_KEY)
    return _cliente


def _parece_jwt(token: str) -> bool:
    """Filtro barato de forma — evita ida à rede para lixo óbvio."""
    return token.count(".") == 2 and len(token) > 40


def email_do_token(token: str) -> Optional[str]:
    """
    O e-mail de quem apresentou este token do Supabase Auth, ou None.

    Devolve None — e não levanta — para token inválido, expirado ou de outro
    emissor: quem chama é `require_auth`, e ali "não é deste tipo" tem de
    continuar para a próxima tentativa em vez de virar erro.
    """
    token = (token or "").strip()
    if not token or not _parece_jwt(token) or not configurado():
        return None

    agora = time.monotonic()
    with _lock:
        guardado = _cache.get(token)
        if guardado and (agora - guardado[0]) < CACHE_TTL_SEG:
            return guardado[1]

    try:
        r = _client().auth.get_user(token)
        usuario = getattr(r, "user", None)
        email = (getattr(usuario, "email", None) or "").strip().lower()
    except Exception:  # noqa: BLE001
        # Token inválido é o caso comum e esperado aqui — não é erro do
        # servidor. Fica em debug para não encher o log com tentativa de
        # navegador que ainda carrega um token antigo.
        logger.debug("Token não validado pelo Supabase Auth", exc_info=True)
        return None

    if not email:
        return None

    with _lock:
        # Poda simples: sem teto, um portal com muita gente acumularia entradas
        # por 60s cada. Mil é folgado para a escala deste sistema e evita o
        # cache virar vazamento.
        if len(_cache) > 1000:
            _cache.clear()
        _cache[token] = (agora, email)
    return email


def entrar(email: str, senha: str) -> Optional[str]:
    """
    Autentica no Supabase Auth e devolve o `access_token`, ou None.

    Usado por `/api/login`: o portal continua sendo quem recebe o formulário,
    então o front não muda — ele guarda no `localStorage` o token que vier, sem
    saber quem o emitiu.

    None cobre credencial errada E indisponibilidade, de propósito: quem chama
    decide o que fazer (hoje: cair no login local durante a transição). O
    motivo real vai para o log, senão um problema de configuração apareceria
    para todo mundo como senha errada.
    """
    if not configurado():
        return None
    try:
        r = _client().auth.sign_in_with_password(
            {"email": (email or "").strip().lower(), "password": senha}
        )
        sessao = getattr(r, "session", None)
        return getattr(sessao, "access_token", None)
    except Exception as e:  # noqa: BLE001
        logger.warning("Supabase Auth recusou o login: %s", type(e).__name__)
        return None


def limpar_cache() -> None:
    """Usado pelos testes; e por quem precisar forçar revalidação."""
    with _lock:
        _cache.clear()
