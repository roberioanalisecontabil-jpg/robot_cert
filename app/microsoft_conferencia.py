"""Conferência da Microsoft a cada 5 minutos: renova a chave de cada conta
ligada e desativa, no CertGuard, quem a Microsoft diz estar bloqueado ou
apagado. Só isso desativa; as demais recusas apenas marcam "sem conferência".

Travas (spec 04/11): erro do NOSSO aplicativo (segredo vencido, app
inexistente) ou mais de MAX_DESATIVACOES_POR_RODADA bloqueadas de uma vez não
desativam ninguém e avisam o TI. Sem MICROSOFT_CONFERENCIA=aplicar, só simula.

Os avisos (uma vez por hora; simulação uma vez por conta por dia) ficam na
memória do processo: reiniciar repete o aviso, o que é aceitável.
"""
from __future__ import annotations

import html
from contextlib import contextmanager
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Iterator, List, Optional

from fastapi import HTTPException

from app import atividade, config, microsoft_entra
from app.smtp_service import decrypt_password, encrypt_password

logger = logging.getLogger(__name__)

MAX_DESATIVACOES_POR_RODADA = 5
_TRAVA_CONFERENCIA = 20261105  # advisory lock; distinta da _TRAVA_APLICACAO do acessorias
_INTERVALO_AVISO = timedelta(hours=1)
# Erro do aplicativo, não da pessoa (os mesmos códigos de microsoft_entra).
_ERRO_DO_APP = {"AADSTS7000215", "AADSTS7000222", "AADSTS700016"}

_avisos_ti: Dict[str, datetime] = {}  # chave do aviso -> quando foi o último
_simulados: Dict[str, str] = {}  # user_id -> dia (ISO) em que a simulação já foi avisada


def _agora() -> datetime:
    return datetime.now(timezone.utc)


def _simulando() -> bool:
    return config.MICROSOFT_CONFERENCIA != "aplicar"


def _enviar_ti(assunto: str, linhas: List[str]) -> bool:
    """E-mail aos administradores ativos. Devolve se algum saiu; nunca levanta."""
    try:
        from app import correio
        from app.alert_state import _get_admin_emails
        from app.settings_state import load_settings

        s = load_settings()
        destinos = _get_admin_emails()
        if not destinos or not correio.configurado(s):
            logger.warning("Aviso ao TI sem destino ou sem e-mail configurado: %s", assunto)
            return False
        corpo = "<ul>" + "".join(f"<li>{html.escape(x)}</li>" for x in linhas) + "</ul>"
        enviou = False
        for para in destinos:
            try:
                correio.send_smtp_email(
                    host=s.smtp_host, port=s.smtp_port, user=s.smtp_user, password_enc=s.smtp_password_encrypted,
                    use_tls=s.smtp_use_tls, use_ssl=s.smtp_use_ssl, from_email=s.smtp_from_email,
                    to_email=para, settings=s, subject=assunto, html_content=corpo,
                )
                enviou = True
            except Exception:  # noqa: BLE001
                logger.exception("Aviso ao TI não enviado a %s", para)
        return enviou
    except Exception:  # noqa: BLE001
        logger.exception("Aviso ao TI falhou: %s", assunto)
        return False


def _avisar_ti(chave: str, assunto: str, linhas: List[str]) -> None:
    """No máximo um aviso por hora por `chave`; só conta como avisado se saiu."""
    agora = _agora()
    ultimo = _avisos_ti.get(chave)
    if ultimo and agora - ultimo < _INTERVALO_AVISO:
        return
    if _enviar_ti(assunto, linhas):
        _avisos_ti[chave] = agora


def _linha(u: Dict[str, Any], codigo: Optional[str]) -> str:
    return f"{u.get('full_name') or '-'} <{u.get('email')}> - {codigo or 'sem código'}"


def desativar_pela_microsoft(sb: Any, user_id: str) -> None:
    """Mesmos efeitos do Desativar de Usuários, carimbado como da Microsoft.
    O último administrador ativo nunca é desativado: só se avisa o TI."""
    from app import cert_installer, computadores, papeis
    from app.rotas.usuarios import _garantir_que_sobra_admin

    uid = str(user_id)
    linhas = sb.table("users").select("id, email, full_name").eq("id", uid).limit(1).execute().data or []
    conta = linhas[0] if linhas else {"id": uid}
    try:
        _garantir_que_sobra_admin(sb, uid, novo_ativo=False)
    except HTTPException as e:
        logger.warning("Conta %s bloqueada na Microsoft, mas não foi desativada: %s", uid, e.detail)
        if e.status_code == 409:  # a regra do último administrador
            _avisar_ti(f"ultimo_admin:{uid}", "Último administrador bloqueado na Microsoft: não foi desativado",
                       [_linha(conta, None)])
        else:  # 503: não deu para ler os usuários; a conta segue ativa e a próxima rodada tenta de novo
            _avisar_ti(f"nao_verificou:{uid}", "Conta bloqueada na Microsoft não pôde ser desativada agora",
                       [_linha(conta, None)])
        return

    sb.table("users").update({"ativo": False, "desativada_pela_microsoft_em": _agora().isoformat()}).eq("id", uid).execute()
    papeis.derrubar_sessoes(sb, uid)
    # Cada passo abaixo é higiene: a conta já caiu e nenhum deles a desfaz.
    for tabela in ("departamento_lider", cert_installer.TABELA_EXCECOES):
        try:  # separados: falhar numa tabela não pode poupar a outra
            sb.table(tabela).delete().eq("user_id", uid).execute()
        except Exception:  # noqa: BLE001
            logger.exception("Conta %s desativada, mas %s não foi esvaziada", uid, tabela)
    papeis.rederivar(sb, [uid])
    computadores.sair_de_tudo(uid, "conta bloqueada na Microsoft")
    try:
        cert_installer.revogar_tokens_pendentes(uid)
    except Exception:  # noqa: BLE001
        logger.exception("Conta %s desativada, mas os tokens pendentes não foram queimados", uid)
    atividade.registrar(atividade.EVENTO_DESATIVADA_MICROSOFT, uid, str(conta.get("email") or ""))


@contextmanager
def _trava(sb: Any) -> Iterator[bool]:
    """Trava de sessão do Postgres para a rodada inteira: com mais de um worker,
    duas rodadas juntas poderiam desativar, cada uma, um administrador diferente
    e deixar o portal sem nenhum (a regra do último admin é verificar-e-agir).
    Devolve False se outro processo está conferindo. Cliente sem `conexao`
    (os falsos dos testes) segue sem trava."""
    if not hasattr(sb, "conexao"):
        yield True
        return
    with sb.conexao() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT pg_try_advisory_lock(%s)", (_TRAVA_CONFERENCIA,))
            obteve = bool(cur.fetchone()[0])
        try:
            yield obteve
        finally:
            if obteve:
                try:
                    with conn.cursor() as cur:
                        cur.execute("SELECT pg_advisory_unlock(%s)", (_TRAVA_CONFERENCIA,))
                except Exception:  # noqa: BLE001
                    # Conexão que volta ao pool ainda segurando a trava bloquearia
                    # toda rodada futura: fechar a solta.
                    logger.exception("Trava da conferência da Microsoft não foi solta; fechando a conexão")
                    conn.close()


def conferir_todas(sb: Any = None, renovar: Callable[..., Any] = microsoft_entra.renovar) -> Dict[str, Any]:
    if sb is None:
        from app.settings_state import _banco

        sb = _banco()
    r: Dict[str, Any] = {"ok": 0, "bloqueadas": 0, "sem_conferencia": 0, "falhas": 0,
                         "travado": False, "simulado": _simulando(), "pulada": False}
    if not sb:
        return r
    with _trava(sb) as obteve:
        if not obteve:
            r["pulada"] = True
            return r
        return _rodada(sb, renovar, r)


def _rodada(sb: Any, renovar: Callable[..., Any], r: Dict[str, Any]) -> Dict[str, Any]:
    from app.auth import conta_ativa

    contas = (sb.table("users").select("id, email, full_name, role, ativo, microsoft_refresh_cifrado")
              .order("id").execute().data or [])
    bloqueadas: List[tuple] = []
    erro_do_app = False
    for u in contas:
        if not u.get("microsoft_refresh_cifrado") or not conta_ativa(u):
            continue
        uid = str(u["id"])
        try:
            refresh = decrypt_password(u["microsoft_refresh_cifrado"])
            if not refresh:  # decrypt_password devolve "" se a chave não abre (rotação)
                raise ValueError("chave de renovação ilegível")
            res = renovar(refresh)
            if res.resultado == "ok":
                dados = {"microsoft_conferido_em": _agora().isoformat(), "microsoft_sem_conferencia": False}
                # Sem chave nova, fica a antiga: gravar "" tiraria a conta das próximas rodadas.
                if res.refresh_novo:
                    dados["microsoft_refresh_cifrado"] = encrypt_password(res.refresh_novo)
                sb.table("users").update(dados).eq("id", uid).execute()
                r["ok"] += 1
            elif res.resultado == "sem_conferencia":
                sb.table("users").update({"microsoft_sem_conferencia": True}).eq("id", uid).execute()
                r["sem_conferencia"] += 1
            elif res.resultado == "bloqueada":
                bloqueadas.append((u, res.codigo_aadsts))
                r["bloqueadas"] += 1
            else:
                r["falhas"] += 1
                erro_do_app = erro_do_app or res.codigo_aadsts in _ERRO_DO_APP
        except Exception:  # noqa: BLE001 — uma conta nunca derruba a rodada
            logger.exception("Conferência da Microsoft falhou para %s", uid)
            r["falhas"] += 1

    r["travado"] = erro_do_app or len(bloqueadas) > MAX_DESATIVACOES_POR_RODADA
    lista = [_linha(u, c) for u, c in bloqueadas]
    if r["travado"]:
        motivo = ("erro do aplicativo na Microsoft (segredo/ID)" if erro_do_app
                  else f"mais de {MAX_DESATIVACOES_POR_RODADA} contas bloqueadas de uma vez")
        _avisar_ti("travado", f"Conferência da Microsoft travada: {motivo}. Ninguém foi desativado",
                   lista or ["Nenhuma conta bloqueada nesta rodada."])
    elif r["falhas"]:
        _avisar_ti("falha", "Conferência da Microsoft com falhas",
                   [f"{r['falhas']} conta(s) não puderam ser conferidas nesta rodada; "
                    "falha não desativa ninguém."])
    if r["travado"]:
        return r

    if r["simulado"]:
        hoje = _agora().date().isoformat()
        novas = [(u, c) for u, c in bloqueadas if _simulados.get(str(u["id"])) != hoje]
        if novas and _enviar_ti("Simulação da conferência da Microsoft: seriam desativadas", [_linha(u, c) for u, c in novas]):
            _simulados.update({str(u["id"]): hoje for u, _ in novas})
        return r

    for u, _ in bloqueadas:
        try:
            desativar_pela_microsoft(sb, str(u["id"]))
        except Exception:  # noqa: BLE001
            logger.exception("Desativação de %s pela Microsoft falhou", u.get("id"))
    return r
