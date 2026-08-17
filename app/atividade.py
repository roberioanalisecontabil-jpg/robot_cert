"""Registro de atividade do usuário — o que `install_log` não cobre.

**Isto não é um cronômetro, e é de propósito.**

O pedido original era "tempo de uso do portal por usuário". A instrumentação
para isso não existia, mas o problema maior era outro: tempo é a métrica errada
aqui. A tarefa do usuário final dura menos de um minuto — entrar, achar o
certificado, baixar o `.exe`. Sessão longa neste portal não significa
engajamento; significa que a pessoa **não achou o que queria**. Otimizar para o
número subir seria otimizar para a ferramenta piorar.

A pergunta real é *quem está usando e quem travou*, e ela se responde com
eventos discretos: entrou, pediu, conseguiu. Sem cronômetro, sem heartbeat, sem
rastrear navegação — o que também mantém a coleta proporcional, que importa
porque isto é dado pessoal de funcionário.

**Por que uma tabela nova e não uma coluna em `users`:** `last_login` diria
"esteve aqui" e nada mais. A pergunta "quem travou" precisa da sequência.

**Por que não duplica `install_log`:** aquela tabela já registra quem instalou o
quê, quando, e com que desfecho. Repetir os mesmos eventos aqui criaria duas
fontes de verdade sobre o mesmo fato — e é assim que elas divergem. Esta tabela
guarda só o que não estava registrado em lugar nenhum; a leitura do dashboard
junta as duas.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Vocabulário fechado. Texto livre viraria uma sopa de grafias em três meses, e
# a agregação passaria a mentir por diferença de acento.
EVENTO_LOGIN = "login"
EVENTO_LOGIN_NEGADO = "login_negado"
# Redefinição pelo próprio usuário, via código enviado por e-mail. Fica na
# trilha porque é o único caminho em que alguém troca a senha de uma conta sem
# estar autenticado nela — se aparecer sem a pessoa ter pedido, é incidente.
EVENTO_SENHA_REDEFINIDA = "senha_redefinida"
EVENTOS_VALIDOS = (EVENTO_LOGIN, EVENTO_LOGIN_NEGADO, EVENTO_SENHA_REDEFINIDA)


def registrar(
    evento: str,
    user_id: Optional[str],
    user_email: str,
    client_ip: Optional[str] = None,
    contexto: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Grava um evento de atividade. **Nunca levanta.**

    Chamada do caminho de login: uma falha aqui não pode impedir alguém de
    entrar no portal. Telemetria que derruba a funcionalidade que observa é pior
    que telemetria nenhuma.
    """
    if evento not in EVENTOS_VALIDOS:
        logger.warning("Evento de atividade desconhecido ignorado: %s", evento)
        return

    try:
        from app.settings_state import _supabase

        client = _supabase()
        if not client:
            return
        client.table("user_activity").insert(
            {
                "user_id": user_id,
                "user_email": (user_email or "").strip().lower(),
                "evento": evento,
                "client_ip": client_ip,
                "contexto": contexto or {},
            }
        ).execute()
    except Exception:  # noqa: BLE001
        logger.exception("Falha ao registrar atividade (%s) — seguindo mesmo assim", evento)


def expurgar(dias: Optional[int] = None) -> Dict[str, Any]:
    """
    Apaga atividade mais antiga que a retenção configurada.

    Mesma retenção de `install_log`, e por isso o ajuste se chama
    `trilha_retencao_dias`: são o mesmo tipo de dado (quem fez o quê, quando),
    com a mesma justificativa e o mesmo prazo. Dois botões de retenção para a
    mesma categoria de dado seria convite a configurar um e esquecer o outro.
    """
    if dias is None:
        try:
            from app.settings_state import load_settings

            dias = int(load_settings().trilha_retencao_dias or 0)
        except Exception as e:  # noqa: BLE001
            logger.exception("Falha ao ler a retenção configurada")
            return {"executado": False, "motivo": f"configuração ilegível: {e}"}

    if not dias or dias <= 0:
        return {"executado": False, "motivo": "retenção desligada (0 = guardar tudo)"}

    try:
        from app.settings_state import _supabase

        client = _supabase()
        if not client:
            return {"executado": False, "motivo": "Supabase não configurado"}

        corte = (datetime.now(timezone.utc) - timedelta(days=dias)).isoformat()
        r = client.table("user_activity").delete().lt("ocorrido_em", corte).execute()
        apagados = len(r.data or [])
        logger.info("Expurgo de user_activity: %s registros anteriores a %s", apagados, corte)
        return {"executado": True, "apagados": apagados, "corte": corte, "retencao_dias": dias}
    except Exception as e:  # noqa: BLE001
        logger.exception("Falha no expurgo de user_activity")
        return {"executado": False, "motivo": str(e)}
