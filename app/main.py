from __future__ import annotations

import logging
import csv
import hmac
import html
import io
import json
import os
import re
import threading
import time
import unicodedata
from collections import defaultdict
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import quote

from fastapi import Depends, FastAPI, File, Header, HTTPException, Query, Request, UploadFile, BackgroundTasks
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app import agent_devices, atividade, auth, config, db_pg, machine_credentials, nome_publico, nomes, permissoes, senha_reset, taxa
from app.historico_agg_cache import get_or_build as _historico_cache_get_or_build
from app.cert_scanner import CertInfo, CertStatus, cert_to_public_dict, move_to_expired, scan_folder
from app.command_queue import COMMANDS, enqueue, list_pending, pop_next_for_agent
from app.config import ROOT
from app import alertas_config
from app import email_modelo
from app import smtp_service
from app.smtp_service import encrypt_password, validate_smtp_config
from app.alert_state import trigger_all_alerts, job_ja_executado_recentemente, previa_do_resumo
from app.notification_service import build_notifications_payload, get_active_alerts
from app.settings_state import (
    GravacaoNaoPersistida,
    PortalSettings,
    carregar_notificacoes_lidas,
    marcar_notificacoes_lidas,
    load_preferencia_alerta,
    save_preferencia_alerta,
    get_latest_snapshot,
    load_colaborador_selecao,
    load_settings,
    save_colaborador_selecao,
    save_settings,
    save_snapshot,
    banco_configurado,
    upsert_cert_history,
)

security = HTTPBearer(auto_error=False)

# Identidade atribuída quando API_KEY não está configurada (ambiente aberto).
# Rotas sensíveis devem recusá-la — é o oposto de "autenticado".
ANONYMOUS_IDENTITY_EMAIL = "anonymous@local"

# Mensagem única para "este token não vale mais". Não distingue conta excluída
# de conta desativada de propósito: quem está do outro lado já perdeu o acesso,
# e a diferença só serviria para dizer a um ex-usuário em que estado a conta
# dele ficou.
SESSAO_ENCERRADA = "Sessão encerrada. Entre novamente."

# Rotas que continuam funcionando com senha provisória. Lista fechada, e
# curta de propósito: tudo o mais é recusado. Fosse uma lista de bloqueio em
# vez de liberação, cada rota nova nasceria acessível por omissão — e o
# esquecimento não daria sintoma nenhum.
ROTAS_COM_SENHA_PROVISORIA = frozenset({"/api/senha/trocar"})

ERRO_SENHA_PROVISORIA = (
    "Sua senha foi definida por outra pessoa. Escolha uma senha própria para "
    "continuar."
)


class ContaIndisponivel(RuntimeError):
    """O diretório de usuários existe, mas não respondeu."""


class ContaInvalida(RuntimeError):
    """A conta que o token nomeia não existe mais no diretório."""


def _conta_local_do_email(email: str) -> Optional[dict]:
    """
    A linha em `users` deste e-mail, ou None. Não levanta.

    Serve ao login por Supabase Auth: lá a identidade já foi provada, e o que
    falta saber é se essa pessoa tem perfil NESTE portal. Entrar na lista comum
    de pessoas não dá acesso aqui — é a diferença entre autenticação e
    autorização, e é o que impede alguém cadastrado só para o inventário de
    passar a listar certificados.

    `_conta_da_sessao` não serve: ela levanta `ContaInvalida` quando não acha, o
    que é certo para uma sessão em curso e errado para uma tentativa de login.
    """
    from app.settings_state import _banco

    sb = _banco()
    if not sb:
        return None
    try:
        r = (
            sb.table("users")
            .select("id, email, role, ativo, deve_trocar_senha")
            .eq("email", (email or "").strip().lower())
            .limit(1)
            .execute()
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("Não foi possível ler a conta local de %s: %s", email, e)
        return None
    return r.data[0] if r.data else None


def _conta_da_sessao(email: str) -> Optional[dict]:
    """
    Relê a conta a cada requisição, para o token não congelar a permissão.

    Devolve `None` quando **não há** diretório de usuários configurado — dev e
    testes sem banco. Aí não existe conta contra a qual conferir, e o token é
    a única informação disponível. Isso não abre brecha em produção: sem
    banco o `/api/login` responde 503 e ninguém chega a ter um token para
    apresentar.

    Levanta `ContaInvalida` quando a conta sumiu — excluída, ou com o e-mail
    alterado, porque aí o `sub` do token deixa de casar com qualquer linha.
    Levanta `ContaIndisponivel` quando a leitura falha. Barrar no segundo caso é
    deliberado: "não consegui verificar" não é "está tudo certo". É a mesma
    escolha já feita em `CustodiaIndisponivel`, e pela mesma razão — a variante
    permissiva não daria sintoma nenhum.
    """
    from app.settings_state import _banco

    sb = _banco()
    if not sb:
        return None
    try:
        r = (
            sb.table("users")
            # `senha_alterada_em` PRECISA estar aqui: é o que
            # `_senha_trocada_depois_do_token` compara. Omiti-la não daria erro
            # — a chave chegaria ausente, seria lida como "nunca trocou", e a
            # invalidação de sessão simplesmente nunca dispararia. Fixado por
            # `test_sessao_le_a_coluna_da_troca_de_senha`, porque o fake dos
            # testes devolve a linha inteira e não pega isto sozinho.
            .select("id, email, role, ativo, senha_alterada_em, deve_trocar_senha")
            .eq("email", email)
            .limit(1)
            .execute()
        )
    except Exception as e:
        logger.warning("Não foi possível verificar a conta da sessão: %s", e)
        raise ContaIndisponivel(str(e)) from e
    if not r.data:
        raise ContaInvalida(email)
    return r.data[0]


def _senha_trocada_depois_do_token(
    conta: dict, token_data: auth.TokenData
) -> bool:
    """
    A senha mudou depois de este token ter sido emitido?

    Devolve False quando falta informação — coluna nula (conta que nunca trocou
    a senha), token sem instante de emissão, ou data ilegível. É o único ponto
    fail-OPEN do `_sessao_do_token`, e é deliberado: um erro de leitura aqui
    deslogaria o portal inteiro de uma vez, e a ausência de dado significa
    literalmente "não houve troca a invalidar".

    A margem de 5s absorve relógios ligeiramente fora de sincronia entre o
    processo que emitiu o token e o que gravou a troca. Sem ela, uma diferença
    de milissegundos poderia derrubar a sessão de quem acabou de entrar.
    """
    marca = conta.get("senha_alterada_em")
    if not marca or not token_data.emitido_em:
        return False
    try:
        trocada = _parse_iso_utc(str(marca))
    except Exception:  # noqa: BLE001
        logger.warning("senha_alterada_em ilegível para %s", conta.get("email"))
        return False
    if trocada is None:
        return False
    return token_data.emitido_em < (trocada - timedelta(seconds=5))


def _sessao_do_token(token_data: auth.TokenData) -> auth.TokenData:
    """
    O papel que vale é o do banco, não o que veio dentro do token.

    Sem isto, `require_admin` decidia com `token.role` — gravado no login e
    válido por 24h (`auth.ACCESS_TOKEN_EXPIRE_MINUTES`). Duas consequências, e a
    segunda é a pior: desativar alguém não derrubava a sessão aberta dele, e
    **rebaixar um administrador não tirava o poder de administrador**; os dois
    efeitos só chegavam quando o token expirasse.

    Era tolerável enquanto desativar era operação rara. Com a hierarquia
    gestor/operador de 15/08, desativar passou a ser a forma principal de
    revogar acesso — e revogação que leva um dia para valer não é revogação.

    Custa uma leitura em `users` por requisição autenticada. É o preço honesto:
    a alternativa por `token_version` faria a mesma leitura, só que precisando
    também de migration.
    """
    try:
        conta = _conta_da_sessao(token_data.email)
    except ContaInvalida:
        raise HTTPException(
            status_code=401,
            detail=SESSAO_ENCERRADA,
            headers={"WWW-Authenticate": "Bearer"},
        )
    except ContaIndisponivel:
        # 503, e não 401: o front derruba a sessão em todo 401
        # (`static/ui-common.js`), e uma instabilidade do banco não deve
        # deslogar quem está trabalhando.
        raise HTTPException(
            status_code=503,
            detail="Não foi possível confirmar a sua sessão. Tente novamente.",
        )

    if conta is None:
        return token_data
    if not auth.conta_ativa(conta):
        raise HTTPException(
            status_code=401,
            detail=SESSAO_ENCERRADA,
            headers={"WWW-Authenticate": "Bearer"},
        )
    if _senha_trocada_depois_do_token(conta, token_data):
        # Trocar a senha derruba as sessões abertas. Sem isto, quem redefine a
        # senha por suspeitar que alguém entrou continuaria com esse alguém
        # dentro por até 24h — exatamente enquanto acredita ter resolvido.
        raise HTTPException(
            status_code=401,
            detail=SESSAO_ENCERRADA,
            headers={"WWW-Authenticate": "Bearer"},
        )
    # Reconstruído a partir da linha, nunca do token: é o ponto inteiro daqui.
    # Com `.get`, e não `[...]`: papel ausente vira None, que `require_admin`
    # reprova. Indexar levantaria KeyError, e a rota responderia 500 — falha
    # aberta na cara do usuário onde cabia uma recusa silenciosa.
    return auth.TokenData(
        email=conta.get("email") or token_data.email,
        role=conta.get("role"),
        user_id=str(conta["id"]) if conta.get("id") is not None else None,
        emitido_em=token_data.emitido_em,
        deve_trocar_senha=bool(conta.get("deve_trocar_senha")),
    )


def _user_id_da_sessao(token: auth.TokenData) -> Optional[str]:
    """
    O UUID de quem está na requisição.

    `_sessao_do_token` já leu a linha inteira em `users` para validar a sessão, e
    o `id` veio junto. Reaproveitá-lo poupa repetir a MESMA consulta poucas
    linhas depois — foi o que pagou a leitura extra que a revogação introduziu.

    O `_resolve_user_id` continua como saída para quando não houve leitura: sem
    banco configurado, e no agente por X-API-Key. Nesses casos ele devolve o
    mesmo `None` de antes, e as rotas seguem respondendo 404 como respondiam.
    """
    return token.user_id or _resolve_user_id(token.email or "")


async def require_auth(
    request: Request,
    auth_creds: Optional[HTTPAuthorizationCredentials] = Depends(security),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
) -> auth.TokenData:
    """
    Dependência híbrida:
    1. Se houver Token JWT (Navegador), valida o usuário.
    2. Se houver X-API-Key (Agente Windows), valida a chave estática.
    """
    # 1. Tentar JWT. Assinatura válida ainda não é sessão válida: `_sessao_do_token`
    #    confere no banco se a conta segue existindo, ativa, e com qual papel.
    if auth_creds:
        token_data = auth.decode_access_token(auth_creds.credentials)

        # 1b. (Até 05/09/2026 havia aqui um segundo caminho: token do Supabase
        #     Auth, a "lista única de pessoas" da fase 3. O portal não roda mais
        #     no Supabase; a lista única, se voltar, será uma tabela no mesmo
        #     PostgreSQL que os dois portais leem — não um emissor externo.)

        if token_data:
            sessao = _sessao_do_token(token_data)
            # A barreira mora AQUI, e não na tela. Um modal pode ser fechado
            # pelo Esc, pelo devtools, ou simplesmente ignorado por quem chama
            # a API direto — e a senha provisória é conhecida por outra pessoa.
            if sessao.deve_trocar_senha and request.url.path not in ROTAS_COM_SENHA_PROVISORIA:
                raise HTTPException(
                    status_code=403,
                    detail=ERRO_SENHA_PROVISORIA,
                    # Cabeçalho, e não texto: o front precisa reconhecer este
                    # caso entre todos os 403 possíveis, e casar por string de
                    # mensagem quebraria ao reescrever a frase.
                    headers={"X-Senha-Provisoria": "1"},
                )
            return sessao

    # 2. Credencial do agente, no header X-API-Key que ele já manda: primeiro a
    #    credencial de MÁQUINA (própria, revogável — app/machine_credentials.py),
    #    depois a chave estática compartilhada, que é o legado em transição.
    #
    #    O TokenData sai IGUAL nos dois caminhos, de propósito: o ganho da
    #    credencial de máquina é rotação e revogação, não privilégio novo — e
    #    qualquer diferença aqui mudaria o alcance de rotas que hoje funcionam.
    if config.API_KEY:
        if x_api_key:
            # Tempo constante (achado #41): `==` em str devolve no primeiro
            # byte diferente, e a diferença de tempo é mensurável pela rede
            # para adivinhar a chave byte a byte. `/api/cron/alerts` já fazia
            # assim; aqui era a única credencial comparada com `==`.
            if hmac.compare_digest(x_api_key.encode("utf-8"), config.API_KEY.encode("utf-8")):
                if not config.ACEITAR_API_KEY_COMPARTILHADA:
                    # Janela fechada (lote 2). 401 SEM o marcador de credencial
                    # inválida: o agente não tem o que descartar — o problema é
                    # a estação não ter migrado, e o log diz isso.
                    logger.warning(
                        "X-API-Key compartilhada RECUSADA (ACEITAR_API_KEY_COMPARTILHADA "
                        "desligada). Provisione a credencial de máquina desta estação."
                    )
                    raise HTTPException(
                        status_code=401,
                        detail="A chave compartilhada não é mais aceita. Use a credencial de máquina.",
                        headers={"WWW-Authenticate": "Bearer"},
                    )
                # WARNING de propósito: é o que permite responder "já dá para
                # desligar a chave compartilhada?" olhando o log, em vez de
                # adivinhar. Some quando o ANALISESRV migrar (R2 fecha aí).
                logger.warning(
                    "Agente autenticou pela X-API-Key compartilhada (legado). "
                    "Estação ainda não migrada para credencial de máquina."
                )
                # Sem `machine_id`: a chave compartilhada não prova estação
                # nenhuma. As rotas que precisam saber DE QUEM é a fila ou o
                # token recusam esta identidade (`_machine_da_credencial`).
                return auth.TokenData(email="agent@internal", role="agent")

            marcar = True
            try:
                maquina = machine_credentials.autenticar(x_api_key)
            except (machine_credentials.SemBanco, machine_credentials.SemTabela):
                # Problema de implantação, não da credencial: sem o marcador,
                # para o agente não descartar um segredo válido por causa de
                # uma migration que falta.
                logger.warning("machine_credentials indisponível; só a X-API-Key vale.")
                maquina, marcar = None, False
            if maquina:
                # A identidade da máquina VIAJA no TokenData: é ela, e não o
                # `machine_id` declarado na requisição, que as rotas do agente
                # usam para decidir fila, custódia e cofre (lote 2, #3/#4).
                return auth.TokenData(
                    email="agent@internal", role="agent",
                    machine_id=str(maquina.get("machine_id") or "").strip().lower() or None,
                )

            # X-API-Key presente e inválida: o marcador diz ao agente que o
            # problema é a CREDENCIAL (descarte e caia na chave compartilhada),
            # não a operação. Protocolo portado do INVENT — casar string de
            # mensagem quebraria em silêncio no dia em que alguém a melhorasse.
            cabecalhos = {"WWW-Authenticate": "Bearer"}
            if marcar:
                cabecalhos[machine_credentials.CABECALHO_CREDENCIAL_INVALIDA] = "1"
            raise HTTPException(
                status_code=401,
                detail="Não autorizado. Faça login ou forneça uma chave de API válida.",
                headers=cabecalhos,
            )
    else:
        # Ambiente aberto (sem API_KEY): mantém compatibilidade para rotas /api/*
        # que usam require_auth, sem elevar privilégios administrativos.
        # ATENÇÃO: esta identidade é anônima. Rotas que manipulam material
        # criptográfico devem recusá-la — ver require_agent_or_admin.
        return auth.TokenData(email=ANONYMOUS_IDENTITY_EMAIL, role="agent")

    raise HTTPException(
        status_code=401, 
        detail="Não autorizado. Faça login ou forneça uma chave de API válida.",
        headers={"WWW-Authenticate": "Bearer"},
    )

# Definidos em `auth` porque o login e o envio de alertas precisam da mesma
# regra; duas cópias divergiriam, e a divergência permissiva não daria sintoma.
PAPEIS_VALIDOS = auth.PAPEIS_VALIDOS
conta_ativa = auth.conta_ativa


async def require_admin(token: auth.TokenData = Depends(require_auth)) -> auth.TokenData:
    if token.role != "admin":
        raise HTTPException(status_code=403, detail="Acesso restrito a administradores.")
    return token


ERRO_ACESSO_MAQUINA = "Acesso restrito ao agente e a administradores."


def require_modulo(
    modulo: str,
    minimo: str = permissoes.NIVEL_LER,
    *,
    permitir_agente: bool = False,
    recusar_anonimo: bool = False,
):
    """
    Guarda por MODULO, lida da matriz de permissoes (`app/permissoes.py`).

    Substitui `require_admin` onde a alcada deixa de ser "so admin" e passa a
    ser configuravel pela tela. O nome do modulo e conferido AQUI, na
    importacao: um erro de digitacao vira erro de partida do servidor, e nao um
    403 silencioso em producao para um modulo que ninguem mexeu.

    `permitir_agente=True` para rota de mao dupla: usada por gente E por maquina.
    `GET /api/settings` e o caso — pertence ao modulo `configuracao`, e a tela de
    Configuracao a consome, mas `agent/run_agent.py` tambem, para saber quais
    pastas monitorar (e `scripts/diagnostico.py` idem).

    Sem essa valvula so haveria escolha ruim: deixar a rota fora da matriz, e ai
    "Nao entra" mentiria (a pessoa continuaria lendo a configuracao), ou liga-la
    sem ressalva e parar o agente em producao. Com ela, o modulo governa a GENTE
    e a maquina segue pelo caminho dela.

    `recusar_anonimo=True` fecha a porta de compatibilidade para rotas que
    entregam material sensivel. `GET /api/cert-installer/vault-optin` diz quais
    certificados estao no cofre, e estava em `require_agent_or_admin` justamente
    porque aquela guarda recusa `anonymous@local` — a identidade que aparece
    quando nao ha API_KEY configurada. Governar o modulo sem esta opcao teria
    AFROUXADO a rota, trocando uma protecao deliberada por uma configuravel.

    Rota EXCLUSIVA de maquina continua com `require_agent_or_admin`.
    """
    if modulo not in permissoes.MODULOS:
        raise ValueError(f"modulo desconhecido em require_modulo: {modulo!r}")
    if minimo not in permissoes.NIVEIS:
        raise ValueError(f"nivel desconhecido em require_modulo: {minimo!r}")

    async def _guarda(token: auth.TokenData = Depends(require_auth)) -> auth.TokenData:
        # Ambiente sem API_KEY: `require_auth` devolve a identidade ANONIMA com
        # papel 'agent' e o portal inteiro fica aberto — compatibilidade
        # documentada no proprio `require_auth`. Esta guarda nao pode ser MAIS
        # estrita que ela nesse modo, senao o portal para de funcionar em dev e
        # em qualquer instalacao que ainda nao configurou a chave.
        #
        # A distincao e por e-mail e nao por papel: o agente DE VERDADE chega
        # como `agent@internal` e continua barrado aqui, porque nao tem o que
        # fazer num modulo de gente. `require_agent_or_admin` faz a mesma
        # separacao, pelo mesmo motivo.
        if token.email == ANONYMOUS_IDENTITY_EMAIL:
            if recusar_anonimo:
                raise HTTPException(status_code=403, detail=ERRO_ACESSO_MAQUINA)
            return token

        # Rota de mao dupla: a maquina passa pelo caminho dela. Papel 'agent' so
        # existe via X-API-Key valida, entao isto nao afrouxa nada para humanos.
        if permitir_agente and (token.role or "") == "agent":
            return token

        try:
            if permissoes.pode(token.role or "", modulo, minimo):
                return token
        except permissoes.PermissoesIndisponiveis:
            # 503, e nao 403: "nao consegui verificar" nao e "voce nao pode".
            # Mesmo criterio de `require_admin_ou_lider` e `_exigir_alcance`.
            raise HTTPException(
                status_code=503,
                detail="Nao foi possivel verificar suas permissoes. Tente de novo.",
            )
        raise HTTPException(
            status_code=403,
            detail=f"Seu perfil nao tem acesso a {modulo}.",
        )

    return _guarda


ERRO_MAQUINA_SEM_IDENTIDADE = (
    "Esta operação exige a credencial de máquina da própria estação. "
    "A chave compartilhada não identifica a estação; provisione a credencial."
)
ERRO_MAQUINA_DIVERGENTE = "machine_id não confere com a credencial desta estação."


def _machine_da_credencial(
    token: auth.TokenData,
    declarado: Optional[str],
    *,
    exigir_identidade: bool = False,
) -> str:
    """A máquina que a credencial PROVA ser — e só ela (achados #3 e #4).

    Admin pode declarar qualquer máquina: é diagnóstico. Credencial de máquina
    só fala por si: declarar outra é 403, e declarar nada vale a própria.

    A X-API-Key compartilhada não tem identidade. Com `exigir_identidade`
    (fila, resgate de token) ela é recusada sempre — não há como saber de quem
    é a fila. Sem ele (inventário, cofre) ela ainda passa com o `machine_id`
    declarado, avisando no log: é a janela para as estações não migradas, e
    `ACEITAR_API_KEY_COMPARTILHADA` desligada a fecha antes de chegar aqui.
    """
    pedido = (declarado or "").strip()
    if (token.role or "").strip().lower() == "admin":
        return pedido
    propria = (token.machine_id or "").strip().lower()
    if not propria:
        if exigir_identidade or token.email == ANONYMOUS_IDENTITY_EMAIL:
            raise HTTPException(status_code=403, detail=ERRO_MAQUINA_SEM_IDENTIDADE)
        logger.warning(
            "Chave compartilhada agindo como a máquina declarada %r (janela de "
            "compatibilidade). Provisione a credencial de máquina desta estação.",
            pedido,
        )
        return pedido
    if pedido and pedido.lower() != propria:
        raise HTTPException(status_code=403, detail=ERRO_MAQUINA_DIVERGENTE)
    return pedido or propria


async def require_agent_or_admin(token: auth.TokenData = Depends(require_auth)) -> auth.TokenData:
    """
    Endpoints da máquina: alimentados pelo agente (X-API-Key -> role 'agent') e
    acessíveis a administradores para diagnóstico.

    Existe porque `require_auth` sozinho é permissivo demais para estas rotas.

    1. Aceita qualquer usuário do portal, inclusive role 'user'. Em /upload-pfx
       isso permitia a um usuário comum enviar um PFX próprio reaproveitando o
       fingerprint de um certificado já armazenado: como `upsert_pfx` usa
       `on_conflict="fingerprint"`, o registro legítimo seria sobrescrito e o
       certificado do atacante acabaria instalado num servidor pelo fluxo
       normal de instalação. `require_admin` não serve como alternativa: o
       agente tem role 'agent', não 'admin'.

    2. Quando API_KEY não está configurada, `require_auth` devolve uma
       identidade ANÔNIMA com role 'agent' para manter compatibilidade. Para as
       rotas antigas isso é aceitável; para estas, que entregam PFX e senhas,
       significaria acesso sem credencial nenhuma. Aqui a identidade anônima é
       recusada explicitamente.
    """
    if token.role not in ("agent", "admin") or token.email == ANONYMOUS_IDENTITY_EMAIL:
        raise HTTPException(status_code=403, detail=ERRO_ACESSO_MAQUINA)
    return token

class SecureJSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        # [OWASP A09] Ocultação de segredos e geração de Log JSON estruturado para prevenir Log Injection
        log_obj = {
            # O replace preserva o sufixo "Z": isoformat() de um datetime aware
            # emite "+00:00", e concatenar "Z" daria "+00:00Z". O formato do log
            # continua byte a byte igual ao de antes.
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        # Filtrar possíveis senhas ou tokens da mensagem bruta
        msg_lower = log_obj["message"].lower()
        if "password" in msg_lower or "token" in msg_lower or "senha" in msg_lower:
            log_obj["message"] = "*** REDACTED SENSITIVE DATA ***"
            
        if record.exc_info:
            log_obj["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(log_obj)

logger = logging.getLogger(__name__)
# Configuração base de logging
_handler = logging.StreamHandler()
_handler.setFormatter(SecureJSONFormatter())
logging.root.handlers = [_handler]
logging.root.setLevel(logging.INFO)

LISTAGEM_EXPORT_MAX = 5000

@asynccontextmanager
async def lifespan(_app: FastAPI):
    """
    Inicialização e encerramento do portal.

    Substitui `@app.on_event("startup")`, deprecado no FastAPI. A ordem é a
    mesma de antes: criar os diretórios locais e só então subir o job de
    alertas.

    O que muda além da deprecação: o `asyncio.create_task` do laço de alertas
    não tinha contrapartida no shutdown — a task ficava pendurada e, em
    reinícios rápidos, um novo laço subia enquanto o anterior ainda dormia. O
    `finally` agora cancela e aguarda o encerramento.
    """
    import asyncio

    # Antes de qualquer outra coisa: sem a chave de cifragem da senha SMTP o
    # portal não sobe. Deliberadamente fatal — o desenho anterior derivava uma
    # chave da JWT_SECRET_KEY e seguia em frente, e a consequência (senha SMTP
    # indecifrável) só aparecia como "os alertas pararam", desligado no tempo e
    # no espaço da causa.
    #
    # ATENÇÃO AO DEPLOY: defina ENCRYPTION_KEY no painel da plataforma
    # (Vercel/Render) ANTES de publicar esta versão. O .env não sobe no deploy.
    smtp_service.verificar_chave_configurada()

    # As demais críticas, conferidas de uma vez (item 12 da Frente 2 — R9):
    # valor malformado ou faltando em produção derruba o boot AQUI, com a lista
    # inteira na mensagem, em vez de uma por vez no primeiro uso de cada rota.
    fatais, avisos = config.verificar_ambiente()
    for aviso in avisos:
        logger.warning("Ambiente: %s", aviso)
    if fatais:
        raise RuntimeError(
            "Ambiente mal configurado — corrija antes de subir:\n- " + "\n- ".join(fatais)
        )

    try:
        config.CERT_SOURCE_DIR.mkdir(parents=True, exist_ok=True)
        config.CERT_EXPIRED_DIR.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        logger.warning(f"Não foi possível criar diretórios locais (ambiente read-only / Vercel): {e}")

    # Job diário de alertas por e-mail.
    #
    # Dois problemas do desenho anterior:
    #
    # 1. `trigger_all_alerts()` é síncrona e era chamada direto no laço async.
    #    Ela faz a varredura completa dos certificados (2,5-3,3s numa base de
    #    mil) e depois N envios SMTP sequenciais — tudo isso travava o event
    #    loop, ou seja, o portal inteiro parava de responder durante o job.
    #    Agora roda em thread separada via run_in_executor.
    #
    # 2. O laço dormia 86400s, mas o Procfile usa `--max-requests 500`: o worker
    #    recicla várias vezes ao dia e o job redisparava em cada boot+60s.
    #    "Diário" nunca foi diário. O marcador em disco (job_ja_executado_
    #    recentemente) torna a cadência real, independente de reinícios.
    async def daily_alerts_job_loop():
        logger.info("Iniciando loop do job diário de alertas")
        await asyncio.sleep(60)  # Deixa o boot terminar antes do primeiro disparo
        loop = asyncio.get_running_loop()
        while True:
            try:
                if job_ja_executado_recentemente():
                    logger.info("Job de alertas ignorado: já executado nas últimas horas.")
                else:
                    logger.info("Executando job de alertas por e-mail...")
                    stats = await loop.run_in_executor(None, trigger_all_alerts)
                    logger.info(f"Job de alertas concluído: {stats}")
            except Exception as e:
                logger.error(f"Erro ao executar job de alertas: {e}")
            # Reavalia de hora em hora: com o marcador de última execução, o
            # trabalho real acontece uma vez por dia mesmo com ciclo curto.
            await asyncio.sleep(3600)

    tarefa_alertas = asyncio.create_task(daily_alerts_job_loop())
    try:
        yield
    finally:
        # O `await` é limitado no tempo de propósito. Esperar a task sem prazo
        # significa que qualquer falha em encerrá-la (um cancel que não chega,
        # um run_in_executor preso num envio SMTP) trava o shutdown do processo
        # para sempre — o worker não recicla e o deploy não termina. Desistir
        # depois de alguns segundos e registrar é melhor que pendurar.
        # `asyncio.wait` em vez de `wait_for` + `except CancelledError`: aquele
        # except engolia qualquer cancelamento, inclusive um dirigido ao próprio
        # lifespan por quem o encerra — o shutdown virava inignorável e a espera
        # pelo prazo cheio passava despercebida. `asyncio.wait` devolve a task
        # pendente sem levantar, e deixa passar um cancelamento externo.
        tarefa_alertas.cancel()
        _, pendentes = await asyncio.wait({tarefa_alertas}, timeout=5)
        if pendentes:
            logger.warning("Job de alertas não encerrou em 5s; seguindo com o shutdown.")


# A documentação só existe onde alguém a ligou (ENABLE_DOCS=1). Em produção o
# /openapi.json descrevia as ~97 rotas — nomes, parâmetros, shapes — para
# qualquer visitante anônimo, e era o único dado que uma visita sem sessão
# levava do portal. O INVENT já nascia assim; isto é a paridade.
app = FastAPI(
    title="Monitor de certificados PFX",
    version="1.2.1",
    lifespan=lifespan,
    docs_url="/docs" if config.ENABLE_DOCS else None,
    redoc_url="/redoc" if config.ENABLE_DOCS else None,
    openapi_url="/openapi.json" if config.ENABLE_DOCS else None,
)

import secrets

@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    # Gera um nonce único por requisição para blindar scripts
    nonce = secrets.token_urlsafe(16)
    request.state.nonce = nonce
    
    response = await call_next(request)
    
    # [Guia Definitivo - A+ / Mozilla Observatory] Headers Críticos
    response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains; preload"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), payment=(), usb=()"
    
    # [Isolamento de Origem Cruzada - Mitigação Spectre]
    response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
    response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    
    # Permissão dev-only para o modo live do Impeccable, cujo picker de variantes
    # é servido em http://localhost:8400. Só existe quando IMPECCABLE_LIVE=1 está
    # no ambiente; a Vercel nunca define essa variável, então o header de produção
    # sai byte a byte igual ao de antes desta linha existir.
    _live = " http://localhost:8400" if os.getenv("IMPECCABLE_LIVE") == "1" else ""

    # CSP Avançado (Removido unsafe-inline/unsafe-eval de script-src e adicionado nonce)
    csp = (
        "default-src 'self'; "
        f"script-src 'self' 'nonce-{nonce}'{_live}; "
        # `connect-src` herdava de `default-src 'self'`. Declarado explicitamente
        # com o mesmo valor para receber a permissão dev acima — com `_live`
        # vazio, herdar e declarar dão exatamente o mesmo resultado.
        f"connect-src 'self'{_live}; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data:; "
        # Sem isto uma tag <base> injetada redirecionaria todos os caminhos
        # relativos (scripts, formulários) para outra origem (achado #49).
        "base-uri 'none'; "
        "object-src 'none'; "
        "form-action 'self'; "
        "frame-ancestors 'none'; "
        "block-all-mixed-content; "
        "upgrade-insecure-requests;"
    )
    response.headers["Content-Security-Policy"] = csp
    
    # Remoção de cabeçalhos de rastreamento/obsoletos
    if "X-XSS-Protection" in response.headers:
        del response.headers["X-XSS-Protection"]
    if "Server" in response.headers:
        del response.headers["Server"]
    if "X-Powered-By" in response.headers:
        del response.headers["X-Powered-By"]

    return response


@app.middleware("http")
async def hosts_permitidos_middleware(request: Request, call_next):
    """Recusa um cabeçalho Host fora de `config.HOSTS_PERMITIDOS` (achado #36).

    Lê a lista a cada requisição, e não na construção do app, para o teste
    poder trocá-la — e porque a lista vazia é a janela de compatibilidade:
    nenhum ambiente tem HOSTS_PERMITIDOS ainda, e sem ela o portal atende
    qualquer Host, como sempre atendeu (`verificar_ambiente` avisa).
    A porta é ignorada de propósito: o mesmo nome chega com e sem `:8020`.
    """
    permitidos = getattr(config, "HOSTS_PERMITIDOS", None) or []
    if permitidos:
        host = (request.headers.get("host") or "").split(":")[0].strip().lower()
        if host not in permitidos:
            return JSONResponse(status_code=400, content={"detail": "Host não atendido por este portal."})
    return await call_next(request)


@app.exception_handler(Exception)
async def _erro_nao_tratado(request: Request, exc: Exception) -> JSONResponse:
    """Erro inesperado sai com uma referência, nunca com o texto (achado #35).

    O texto de uma exceção traz nome de tabela, DSN, caminho de arquivo, às
    vezes o valor que falhou. A referência é o que a pessoa manda para o
    suporte, e o log a liga ao traceback inteiro.
    """
    ref = secrets.token_hex(4)
    logger.error(
        "[%s] Erro não tratado em %s %s", ref, request.method, request.url.path,
        exc_info=exc,
    )
    return JSONResponse(status_code=500, content={"detail": "Erro interno", "ref": ref})

templates = Jinja2Templates(directory=str(ROOT / "templates"))
# `{{ nome | nome_exibicao }}` nos templates: a mesma regra que a API entrega
# em `nome_exibicao`, para tela renderizada no servidor e tela montada por
# JS não divergirem no jeito de escrever um nome.
templates.env.filters["nome_exibicao"] = nomes.nome_exibicao
app.mount("/static", StaticFiles(directory=str(ROOT / "static")), name="static")


# As funções require_api_key foram removidas em favor do require_auth híbrido.


def _painel_busca_normalizada(value: Any) -> str:
    """Mesma ideia que `normalizarTexto` no dashboard (minúsculas, sem acentos)."""
    t = str(value or "").lower()
    t = unicodedata.normalize("NFD", t)
    return "".join(ch for ch in t if unicodedata.category(ch) != "Mn")


def _enrich_cert_item_dashboard_flags(it: dict, now: datetime, thirty_days: datetime) -> dict:
    """Alinha com o painel: vencido pela data `not_after` mesmo que `status` ainda seja ok."""
    row = dict(it)
    expired_by_date = False
    expiring_soon = False
    na = row.get("not_after")
    if na:
        exp = _parse_iso_utc(str(na))
        min_dt = datetime.min.replace(tzinfo=timezone.utc)
        if exp > min_dt:
            if exp < now:
                expired_by_date = True
            elif exp <= thirty_days and exp >= now:
                expiring_soon = True
    row["_isExpiredByDate"] = expired_by_date
    row["_isExpiringSoon"] = expiring_soon
    return row


def _dashboard_filtro_status_match(row: dict, filtro: str) -> bool:
    s = str(row.get("status") or "").lower()
    ed = bool(row.get("_isExpiredByDate"))
    es = bool(row.get("_isExpiringSoon"))
    f = (filtro or "todos").strip().lower()
    if f in ("todos", ""):
        return True
    if f == "validos":
        return s == "ok" and not ed and not es
    if f in ("prestes_vencer", "prestes a vencer"):
        return s == "ok" and es and not ed
    if f == "vencidos":
        return s == "expirado" or ed
    if f in ("erros", "erro"):
        return s == "erro"
    if f in ("sem_padrao", "fora_do_padrao"):
        return s == "fora_do_padrao"
    return True


# Status que significam "o robo NAO conseguiu ler este arquivo": ou a leitura
# falhou (`erro`), ou o nome nao segue a convencao que carrega a senha do PFX
# (`fora_do_padrao`). Nos dois casos o certificado nunca vai ao cofre e nunca e
# instalavel pelo portal — e por isso nao ajuda quem veio buscar um certificado
# para usar.
STATUS_ILEGIVEIS = ("erro", "fora_do_padrao")


def _e_ilegivel(row: dict) -> bool:
    return str(row.get("status") or "").lower() in STATUS_ILEGIVEIS


def _dashboard_busca_match(row: dict, q_raw: str) -> bool:
    if not str(q_raw or "").strip():
        return True
    raw = str(q_raw).strip()
    bt = _painel_busca_normalizada(raw)
    bd = re.sub(r"\D", "", raw)
    nome = _painel_busca_normalizada(row.get("nome") or row.get("display_name") or "")
    doc_f = _painel_busca_normalizada(row.get("documento_formatado") or "")
    doc_n = _painel_busca_normalizada(row.get("documento_numero") or "")
    fn = _painel_busca_normalizada(row.get("nome_publico") or "")
    na_txt = _painel_busca_normalizada(row.get("not_after") or "")
    dd = _digits_only_doc(row.get("documento_numero") or row.get("documento_formatado"))
    nd = _digits_only_doc(str(row.get("not_after") or ""))
    if bt and bt in nome:
        return True
    if bt and bt in doc_f:
        return True
    if bt and bt in doc_n:
        return True
    if bt and bt in fn:
        return True
    if bt and bt in na_txt:
        return True
    if bd and bd in dd:
        return True
    if bd and bd in nd:
        return True
    return False


def _dashboard_resumo_counts(rows: List[dict]) -> dict[str, int]:
    total = len(rows)
    validos = expirando = erros = vencidos = sem_padrao = 0
    for it in rows:
        s = str(it.get("status") or "").lower()
        ed = bool(it.get("_isExpiredByDate"))
        es = bool(it.get("_isExpiringSoon"))
        if s == "erro":
            erros += 1
        elif s == "fora_do_padrao":
            sem_padrao += 1
        elif s == "expirado" or ed:
            vencidos += 1
        elif s == "ok":
            if es:
                expirando += 1
            else:
                validos += 1
    return {
        "total": total,
        "validos": validos,
        "expirando": expirando,
        "erros": erros,
        "vencidos": vencidos,
        "sem_padrao": sem_padrao,
    }


def chave_alfabetica(item: dict) -> tuple:
    """
    Chave de ordenação por titular, insensível a caixa e acento.

    `(1, "")` para quem não tem nome legível: vai para o fim. Ordenar por
    string vazia os jogaria para o topo, e a primeira página da lista seria
    justamente o que o robô não conseguiu ler — o oposto do útil.
    """
    bruto = str(item.get("nome") or item.get("display_name") or item.get("nome_publico") or "").strip()
    if not bruto:
        return (1, "")
    sem_acento = "".join(
        c for c in unicodedata.normalize("NFD", bruto) if unicodedata.category(c) != "Mn"
    )
    return (0, sem_acento.casefold())


# Colunas que a tabela do Inicio deixa ordenar. O valor e a funcao que extrai a
# chave; `None` como primeiro elemento da tupla mantem a regra que ja valia para
# o nome: **o que falta vai para o FIM**, nas duas direcoes.
#
# Isso nao e detalhe. Ordenar por vencimento com os sem-data no topo daria uma
# primeira pagina inteira de arquivos que o robo nao conseguiu ler — o oposto do
# util, que e exatamente o que `chave_alfabetica` ja evitava para o nome.
def _chave_texto(campo: str):
    def chave(it: dict):
        v = str(it.get(campo) or "").strip()
        if not v:
            return (1, "")
        sem_acento = "".join(
            c for c in unicodedata.normalize("NFD", v) if unicodedata.category(c) != "Mn"
        )
        return (0, sem_acento.casefold())
    return chave


def _chave_data(campo: str):
    def chave(it: dict):
        v = str(it.get(campo) or "").strip()
        return (1, "") if not v else (0, v)   # ISO 8601 ordena como texto
    return chave


ORDENACOES = {
    "nome": chave_alfabetica,
    "status": _chave_texto("status"),
    "emissao": _chave_data("not_before"),
    "vencimento": _chave_data("not_after"),
    "documento": _chave_texto("documento_numero"),
}


def _ordenar_listagem(itens: List[dict], coluna: str, direcao: str) -> List[dict]:
    """Ordena por coluna. Coluna desconhecida mantem a ordem que veio.

    Recusar seria pior: a tabela ganharia um estado em que ela simplesmente nao
    carrega, e o sintoma (uma tela vazia) nao diria que o problema e o parametro.
    """
    chave = ORDENACOES.get((coluna or "").strip().lower())
    if chave is None:
        return itens

    # Os SEM valor saem da ordenacao em vez de participar dela.
    #
    # A primeira versao devolvia `(1, "")` para eles e deixava o `reverse` fazer
    # o resto — e o `reverse` inverte tambem o marcador, entao em ordem
    # decrescente os sem-data iam para o TOPO. A primeira pagina virava uma
    # lista de arquivos que o robo nao conseguiu ler, que e o oposto do util e
    # justamente o que `chave_alfabetica` ja evitava para o nome.
    #
    # Descoberto pelo teste que afirmava a invariante nas DUAS direcoes; com uma
    # so teria passado.
    presentes = [it for it in itens if chave(it)[0] == 0]
    ausentes = [it for it in itens if chave(it)[0] != 0]
    ordenados = sorted(presentes, key=chave, reverse=(str(direcao).lower() == "desc"))
    return ordenados + ausentes


def ordenar_por_titular(itens: List[dict]) -> List[dict]:
    """
    Ordena a listagem de certificados pelo nome do titular.

    **Precisa acontecer aqui, no servidor, e antes da paginação.** A tabela
    pagina no servidor: ordenar no navegador ordenaria só os 10 ou 25 itens da
    página visível, e a lista *pareceria* certa enquanto continuasse errada
    entre páginas — que é pior que estar visivelmente errada.

    Não havia ordenação nenhuma antes. A lista saía na ordem em que o agente
    varre o disco, e ele percorre pasta por pasta: o resultado eram vários
    blocos alfabéticos emendados (um por subpasta, mais os vencidos no fim),
    que de longe parece ordem alfabética e de perto não é.
    """
    return sorted(itens, key=chave_alfabetica)


def _list_certificados_payload(
    sets: PortalSettings,
    snap: Optional[dict],
    fonte: str,
) -> dict[str, Any]:
    """Monta o payload base (sem paginação) para GET /api/certificados."""
    if fonte == "local":
        src = sets.effective_source()
        exp = sets.effective_expired()
        itens: List[CertInfo] = scan_folder(src)
        return {
            "source_dir": str(src),
            "expired_dir": str(exp),
            "atualizado_em": datetime.now(timezone.utc).isoformat(),
            "itens": [cert_to_public_dict(c) for c in itens],
            "data_source": "local",
            "machine_id": sets.machine_id,
        }
    # Sanitizado também na SAÍDA, e não só no ingest: um snapshot gravado antes
    # da migração do lote 3 ainda tem o nome do arquivo (com a senha) em cada
    # item, e a resposta da API não pode depender de a migração já ter rodado.
    if fonte == "remoto":
        if not snap:
            raise HTTPException(
                status_code=404,
                detail="Nenhum dado remoto. Configure o agente no Windows para enviar leituras.",
            )
        return {
            "source_dir": str(snap.get("source_folder", "") or ""),
            "expired_dir": str(snap.get("expired_folder", "") or ""),
            "atualizado_em": snap.get("scanned_at", datetime.now(timezone.utc).isoformat()),
            "itens": [nome_publico.sanitizar_item(it) for it in (snap.get("items", []) or [])],
            "data_source": "remoto",
            "machine_id": snap.get("machine_id"),
        }
    # auto
    if snap:
        return {
            "source_dir": str(snap.get("source_folder", "") or ""),
            "expired_dir": str(snap.get("expired_folder", "") or ""),
            "atualizado_em": snap.get("scanned_at", datetime.now(timezone.utc).isoformat()),
            "itens": [nome_publico.sanitizar_item(it) for it in (snap.get("items", []) or [])],
            "data_source": "remoto",
            "machine_id": snap.get("machine_id"),
        }
    src = sets.effective_source()
    exp = sets.effective_expired()
    itens_scan: List[CertInfo] = scan_folder(src)
    return {
        "source_dir": str(src),
        "expired_dir": str(exp),
        "atualizado_em": datetime.now(timezone.utc).isoformat(),
        "itens": [cert_to_public_dict(c) for c in itens_scan],
        "data_source": "local",
        "machine_id": sets.machine_id,
    }


class SettingsBody(BaseModel):
    source_folder: str = Field(default="", description="Pasta de certificados no Windows (caminho completo)")
    expired_folder: str = Field(default="", description="Pasta destino dos vencidos")
    machine_id: str = Field(default="default", description="Identificador lógico da máquina / agente")
    smtp_host: str = Field(default="")
    smtp_port: int = Field(default=587)
    smtp_user: str = Field(default="")
    smtp_password: Optional[str] = Field(default=None)
    smtp_use_tls: bool = Field(default=True)
    smtp_use_ssl: bool = Field(default=False)
    smtp_from_email: str = Field(default="")
    smtp_alerts_enabled: bool = Field(default=False)
    # ── Campos que este PUT não "possui" ───────────────────────────────────
    #
    # `None` = NÃO MEXE; qualquer outro valor grava — inclusive vazio, que aqui
    # significa "voltar ao padrão do código". É a mesma semântica que
    # `smtp_password` já usava neste modelo, agora estendida aos campos que
    # nenhum dos formulários desta tela envia.
    #
    # Sem isso, o PUT remonta o `PortalSettings` inteiro a partir do corpo: os
    # dois formulários de /configuracao mandam 11 campos, e os que faltam
    # voltavam ao default. Salvar as PASTAS apagava o template de nome do
    # instalador, o TTL do token e a retenção da trilha — configurados em outra
    # tela, por outra rota, e zerados aqui sem nenhum aviso.
    #
    # O sintoma aparece longe da causa: o instalador volta a gerar o nome
    # padrão, e nada na tela de Configuração sugere que foi ela.
    install_token_ttl_min: Optional[int] = Field(default=None)
    trilha_retencao_dias: Optional[int] = Field(default=None)
    alertas_destinatarios: Optional[str] = Field(default=None)
    alertas_marcos: Optional[str] = Field(default=None)
    alertas_intervalo_horas: Optional[int] = Field(default=None)
    # Editados por um modal só, e ausentes de todos os outros formulários da
    # tela — `None` aqui é o que impede o Salvar das pastas de apagar o texto
    # do e-mail.
    alerta_email_assunto: Optional[str] = Field(default=None)
    alerta_email_titulo: Optional[str] = Field(default=None)
    alerta_email_abertura: Optional[str] = Field(default=None)
    alerta_email_recado: Optional[str] = Field(default=None)


class IngestBody(BaseModel):
    machine_id: str = "default"
    source_folder: str
    expired_folder: str
    items: List[dict] = Field(default_factory=list)
    scanned_at: Optional[str] = None


class EnqueueCommandBody(BaseModel):
    machine_id: str = "default"
    command: str = Field(..., description="mover_vencidos | rescan | ping")


# A `pagina_ativa` acende o item correspondente em templates/_sidebar.html.
# Rota que esquecer de passa-la renderiza o menu sem nenhum item aceso - falha
# silenciosa, por isso `tests/test_sidebar_partial.py` cobre todas elas.
@app.get("/", response_class=HTMLResponse)
def painel(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "pagina_ativa": "inicio",
            # O teto vem do servidor para não existir em dois lugares. Um número
            # digitado na tela divergiria do que a rota aceita, e o sintoma seria
            # o pior dos dois: a tela deixa marcar 60, o download falha com 422.
            "max_certificados": MAX_CERTIFICADOS_POR_TOKEN,
        },
    )


@app.get("/configuracao", response_class=HTMLResponse)
def pagina_configuracao(request: Request) -> HTMLResponse:
    # As abas são links (?aba=…): sem JavaScript a página abre já na aba pedida.
    aba = request.query_params.get("aba") or "chave"
    if aba not in ("chave", "pastas", "alertas", "comandos"):
        aba = "chave"
    return templates.TemplateResponse(
        request=request, name="configuracao.html", context={"pagina_ativa": "configuracao", "aba": aba}
    )


@app.get("/login", response_class=HTMLResponse)
def pagina_login(request: Request) -> HTMLResponse:
    # Sem sidebar: quem nao entrou ainda nao tem para onde navegar.
    return templates.TemplateResponse(request=request, name="login.html")


@app.get("/usuarios", response_class=HTMLResponse)
def pagina_usuarios(request: Request) -> HTMLResponse:
    # As abas são links (?aba=…): sem JavaScript a página abre já na aba pedida.
    aba = request.query_params.get("aba") or "usuarios"
    if aba not in ("usuarios", "departamentos", "permissoes"):
        aba = "usuarios"
    return templates.TemplateResponse(
        request=request, name="usuarios.html", context={"pagina_ativa": "usuarios", "aba": aba}
    )


@app.get("/historico", response_class=HTMLResponse)
def pagina_historico(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request, name="historico.html", context={"pagina_ativa": "historico"}
    )


@app.get("/vencidos", response_class=HTMLResponse)
def pagina_vencidos(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request, name="vencidos.html", context={"pagina_ativa": "vencidos"}
    )


@app.get("/duplicidades", response_class=HTMLResponse)
def pagina_duplicidades(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request, name="duplicidades.html", context={"pagina_ativa": "duplicidades"}
    )


@app.get("/acompanhamento", response_class=HTMLResponse)
def pagina_colaborador_certificados(request: Request) -> HTMLResponse:
    # As abas são links (?aba=…): sem JavaScript a página recarrega já na
    # aba certa; com JavaScript a troca é local e a URL acompanha.
    aba = request.query_params.get("aba") or "acompanhados"
    if aba not in ("acompanhados", "escolher"):
        aba = "acompanhados"
    return templates.TemplateResponse(
        request=request,
        name="colaborador_certificados.html",
        context={"pagina_ativa": "acompanhamento", "aba": aba},
    )


@app.get("/favicon.ico", include_in_schema=False)
def favicon() -> Response:
    """
    Serve o favicon do projeto quando disponível.
    Fallback 204 para evitar ruído de 404 no log em dev.
    """
    icon_path = ROOT / "ico" / "icone.ico"
    if icon_path.is_file():
        return FileResponse(path=icon_path, media_type="image/x-icon")
    return Response(status_code=204)


class LoginBody(BaseModel):
    email: str
    password: str


def _sb_do_login():
    from app.settings_state import _banco
    sb = _banco()
    if not sb:
        raise HTTPException(status_code=503, detail="Sistema sem banco configurado para login.")
    return sb


def _conferir_credenciais(email: str, senha: str, ip: Optional[str]) -> dict:
    """
    E-mail + senha viram a linha de `users`, ou levantam o HTTP certo.

    Extraído de `login` em 22/08/2026, quando o agente ganhou tela de login:
    passaram a existir dois caminhos que autenticam com senha. O módulo `auth`
    já explica por que uma regra de acesso duplicada é perigosa — a cópia que
    divergisse para o lado permissivo não daria sintoma nenhum. Aqui isso
    significaria conta desativada continuar registrando dispositivo depois de
    já ter perdido o portal.

    Normalizado ANTES da consulta. A coluna guarda tudo em minúsculas (o portal
    grava assim, e o índice único é sobre `lower(email)`), mas a consulta usava
    o valor cru do formulário: quem digitasse "Ana@X.com" não casava com linha
    nenhuma e levava 401 "E-mail ou senha incorretos" — mensagem que manda a
    pessoa caçar a senha por causa de uma maiúscula.

    O `trim` está aqui pelo mesmo motivo: colar o e-mail de um e-mail costuma
    trazer espaço junto.
    """
    email_login = (email or "").strip().lower()
    r = _sb_do_login().table("users").select("*").eq("email", email_login).limit(1).execute()
    user = r.data[0] if r.data else None

    # Sempre paga o bcrypt, exista a conta ou não (achado #26). O `or` que
    # pulava a conferência quando `user` era None respondia em ~0 ms para
    # e-mail inexistente e em ~250 ms para e-mail existente: a mensagem era
    # idêntica, o tempo não — e isso enumerava contas com precisão.
    hash_alvo = user["password_hash"] if user else _hash_falso()
    senha_ok = auth.verify_password(senha, hash_alvo)

    if not user or not senha_ok:
        # Só registra quando a conta EXISTE: e-mail inexistente viraria guardar
        # entrada arbitrária de quem chamou. Com conta existente, o registro
        # responde "alguém está tentando entrar aqui", que é o caso que importa.
        if user:
            atividade.registrar(
                atividade.EVENTO_LOGIN_NEGADO,
                user_id=str(user.get("id") or "") or None,
                user_email=email_login,
                client_ip=ip,
                contexto={"motivo": "senha_incorreta"},
            )
        raise HTTPException(status_code=401, detail=CREDENCIAL_INVALIDA)

    if not conta_ativa(user):
        atividade.registrar(
            atividade.EVENTO_LOGIN_NEGADO,
            user_id=str(user.get("id") or "") or None,
            user_email=email_login,
            client_ip=ip,
            contexto={"motivo": "conta_desativada"},
        )
        # Mesmo 401 da senha errada (achado #27). O 403 "Usuário desativado"
        # só chegava depois de a senha conferir — e confirmava a quem tinha a
        # credencial vazada que a conta existe e em que estado ficou. O motivo
        # fica no registro de atividade, onde o administrador o lê.
        raise HTTPException(status_code=401, detail=CREDENCIAL_INVALIDA)

    return user


CREDENCIAL_INVALIDA = "E-mail ou senha incorretos."

_HASH_FALSO: Optional[str] = None


def _hash_falso() -> str:
    """Um hash bcrypt de custo real para conferir quando a conta não existe.

    Gerado uma vez, sob demanda: custa os mesmos ~250 ms de um hash de
    verdade, e é isso que iguala o tempo dos dois caminhos do login.
    """
    global _HASH_FALSO
    if _HASH_FALSO is None:
        _HASH_FALSO = auth.get_password_hash(secrets.token_urlsafe(32))
    return _HASH_FALSO


@app.post("/api/login")
def login(body: LoginBody, request: Request) -> dict:
    # Teto por IP ANTES de qualquer ida ao banco (junto do item 13 da Frente
    # 2; achado do levantamento de superfície anônima de 01/09/2026): o /claim
    # sempre teve teto e o login não — e login é o alvo clássico de spray de
    # senhas. Vinte por minuto não atrapalha um escritório inteiro atrás de um
    # NAT; adivinhação vira exercício inútil. A janela é a durável de
    # `app/taxa.py`, a mesma do claim — em memória de instância, na Vercel, o
    # teto seria sugestão.
    if not taxa.permitir(f"login:{_ip_do_cliente(request)}", 20, 60):
        raise HTTPException(status_code=429, detail="Muitas tentativas. Aguarde um minuto.")

    load_settings()  # trigger client init
    _sb_do_login()

    ip = request.client.host if request and request.client else None
    try:
        # Login local: `users` + bcrypt + JWT deste portal. (Até 05/09/2026 o
        # Supabase Auth era tentado primeiro, como "lista única de pessoas" da
        # fase 3; o portal não roda mais no Supabase e esse caminho saiu.)
        user = _conferir_credenciais(body.email, body.password, ip)
        atividade.registrar(
            atividade.EVENTO_LOGIN,
            user_id=str(user.get("id") or "") or None,
            user_email=user["email"],
            client_ip=ip,
        )
        token = auth.create_access_token({"sub": user["email"], "role": user["role"]})
        return {"access_token": token, "token_type": "bearer", "role": user["role"]}
    except HTTPException:
        # O `except Exception` abaixo engolia estas: uma senha errada saía como
        # 500 com "401: E-mail ou senha incorretos." no corpo — mensagem certa,
        # status errado, e todo tratamento no front que olhasse o código via
        # "erro do servidor" onde houve credencial inválida.
        raise
    except Exception:
        logger.exception("Erro no login")
        raise HTTPException(status_code=500, detail="Não foi possível concluir o login. Tente de novo.")


# Modulo `usuarios` na matriz de permissoes desde 20/08. Leitura e escrita
# separadas de proposito: e o que torna "so visualizar" configuravel depois. As
# 13 rotas eram `require_admin`, e a matriz da `nenhum` a gestor e user — entao
# o comportamento nao muda hoje.
#
# `/api/users/me/export` e `/api/users/me/delete` NAO entram: sao LGPD sobre a
# propria conta, e amarra-las a permissao do modulo Usuarios tiraria de um
# operador o direito de exportar os proprios dados.
@app.get("/api/users", dependencies=[Depends(require_modulo("usuarios"))])
def list_users() -> List[dict]:
    from app.settings_state import _banco
    sb = _banco()
    if not sb: return []
    r = sb.table("users").select(
        "id, email, full_name, role, ativo, gestor_id, departamento_id, created_at"
    ).execute()
    usuarios = list(r.data or [])
    # Contagem da carteira por pessoa, numa consulta só: a coluna "Carteira"
    # liga esta tela ao cartão "Acesso" do Dashboard e à tela Carteiras.
    quantos: Dict[str, int] = {}
    try:
        for c in sb.table("carteira").select("user_id").execute().data or []:
            k = str(c.get("user_id"))
            quantos[k] = quantos.get(k, 0) + 1
    except Exception:  # noqa: BLE001 — sem a contagem a lista continua servindo
        logger.exception("Falha ao contar carteiras para a lista de usuários")
    from app import texto as _texto
    for u in usuarios:
        n = quantos.get(str(u.get("id")), 0)
        # Só na exibição: "irla" → "Irla", caixa alta → título.
        u["nome_exibicao"] = nomes.nome_pessoa(u.get("full_name")) or str(u.get("email") or "")
        u["carteira"] = n
        u["textos"] = {"carteira": _texto.plural(n, "cliente")}
    return usuarios


class UserCreateBody(BaseModel):
    email: str
    password: str
    full_name: str
    role: str = "user"
    departamento_id: Optional[str] = None


class UserUpdateBody(BaseModel):
    email: str
    full_name: str
    role: str = "user"
    # Omitir mantém o que está gravado. `role: "disabled"` continua aceito como
    # forma antiga de desativar (ver `update_user`), mas não escreve mais em
    # `role` — o papel deixou de ser o lugar onde o estado mora.
    ativo: Optional[bool] = None
    gestor_id: Optional[str] = None
    # Omitir mantém o que está gravado; string vazia limpa. Sem a distinção,
    # não haveria como tirar alguém de um setor sem inventar um valor.
    departamento_id: Optional[str] = None


class UserResetPasswordBody(BaseModel):
    password: str


def _norm_header(v: str) -> str:
    s = unicodedata.normalize("NFD", str(v or "").strip().lower())
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
    return s


@app.post("/api/users/import", dependencies=[Depends(require_modulo("usuarios", permissoes.NIVEL_EDITAR))])
async def import_users(file: UploadFile = File(...), ator: auth.TokenData = Depends(require_auth)) -> dict:
    from app.settings_state import _banco

    sb = _banco()
    if not sb:
        raise HTTPException(status_code=503, detail="Sistema sem banco configurado.")

    name = (file.filename or "").lower()
    if not name.endswith(".csv"):
        raise HTTPException(
            status_code=422,
            detail="Formato inválido. Exporte a planilha como CSV e envie um arquivo .csv.",
        )

    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=422, detail="Arquivo vazio.")
        
    # [OWASP A08] Validação de Limite de Tamanho
    if len(raw) > 5 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Arquivo muito grande (limite de 5MB).")
        
    # [OWASP A08] Validação de Magic Bytes (Assinatura real do arquivo)
    # Rejeita ativamente se for um binário executável ou arquivo restrito disfarçado de CSV
    if raw.startswith(b'MZ') or raw.startswith(b'\x7fELF') or raw.startswith(b'%PDF') or raw.startswith(b'PK'):
        raise HTTPException(status_code=422, detail="Conteúdo do arquivo suspeito. Apenas texto puro (CSV) é permitido.")

    text = raw.decode("utf-8-sig", errors="replace")
    sniffer = csv.Sniffer()
    try:
        dialect = sniffer.sniff(text[:2048], delimiters=",;")
        delim = dialect.delimiter
    except csv.Error:
        delim = ";"

    reader = csv.DictReader(io.StringIO(text), delimiter=delim)
    if not reader.fieldnames:
        raise HTTPException(status_code=422, detail="CSV sem cabeçalho.")

    map_headers = {_norm_header(h): h for h in reader.fieldnames}

    def pick(*aliases: str) -> Optional[str]:
        for a in aliases:
            key = map_headers.get(_norm_header(a))
            if key:
                return key
        return None

    h_nome = pick("nome", "full_name", "nome completo")
    h_email = pick("email", "e-mail")
    h_senha = pick("senha", "password")
    h_role = pick("role", "nivel", "papel", "perfil")
    if not h_nome or not h_email or not h_senha:
        raise HTTPException(
            status_code=422,
            detail="Cabeçalho obrigatório: nome, email, senha.",
        )
    if not h_role:
        raise HTTPException(
            status_code=422,
            detail="Cabeçalho obrigatório também para nível: use 'nivel' ou 'role' com valores 'admin' ou 'user'.",
        )

    criados = 0
    ignorados = 0
    erros: List[dict[str, Any]] = []
    linha = 1
    for row in reader:
        linha += 1
        nome = str(row.get(h_nome) or "").strip()
        email = str(row.get(h_email) or "").strip().lower()
        senha = str(row.get(h_senha) or "").strip()
        role = str(row.get(h_role) or "").strip().lower()

        if not nome or not email or not senha or not role:
            ignorados += 1
            continue
        if role not in PAPEIS_VALIDOS:
            erros.append(
                {
                    "linha": linha,
                    "email": email,
                    "erro": f"Nível inválido. Use exatamente: {', '.join(PAPEIS_VALIDOS)}.",
                }
            )
            continue
        if len(senha) < SENHA_MINIMA:
            erros.append({"linha": linha, "email": email,
                          "erro": f"Senha deve ter no mínimo {SENHA_MINIMA} caracteres."})
            continue
        # A mesma barreira de `create_user`: a planilha não é um caminho
        # paralelo para nascer administrador.
        try:
            _exigir_alcance_de_papel(ator, role)
        except HTTPException as e:
            erros.append({"linha": linha, "email": email, "erro": str(e.detail)})
            continue
        # O CSV era o caminho que escapava de tudo: nem o formulário HTML o
        # cobre, nem a API validava.
        if not _EMAIL_PLAUSIVEL.match(email):
            erros.append({"linha": linha, "email": email, "erro": "E-mail inválido."})
            continue
        try:
            existe = sb.table("users").select("id").eq("email", email).limit(1).execute()
            if existe.data:
                ignorados += 1
                continue
            sb.table("users").insert(
                {
                    "email": email,
                    "password_hash": auth.get_password_hash(senha),
                    "full_name": nome,
                    "role": role,
                    # As mesmas duas colunas que `create_user` grava (achado
                    # #10). A senha do CSV esteve numa planilha que circulou
                    # por e-mail: serve para o primeiro acesso e nada mais.
                    # Sem isto a coluna caía no DEFAULT false e a conta
                    # nascia com uma senha conhecida por terceiros, válida
                    # para sempre.
                    "deve_trocar_senha": True,
                    "ativo": True,
                }
            ).execute()
            criados += 1
        except Exception:  # noqa: BLE001
            # O texto do banco não vai para a planilha de resposta (achado
            # #35): traz nome de tabela, constraint e às vezes o valor.
            logger.exception("Falha ao importar a linha %d", linha)
            erros.append({"linha": linha, "email": email,
                          "erro": "Não foi possível gravar esta linha. Veja o log do servidor."})

    return {"ok": True, "criados": criados, "ignorados": ignorados, "erros": erros}


# Validação deliberadamente frouxa: exige um "@" com algo dos dois lados e um
# ponto no domínio, e nada além disso. Regex de e-mail "completo" rejeita
# endereços válidos e dá falsa sensação de rigor — o que prova que um e-mail
# funciona é uma mensagem chegar nele.
_EMAIL_PLAUSIVEL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]{2,}$")

# O mesmo mínimo que `reset_user_password` já exigia. Antes, criar era mais
# permissivo que redefinir: dava para nascer com senha de um caractere e só
# descobrir o rigor ao trocá-la.
SENHA_MINIMA = 6

SO_ADMIN_CONCEDE_ADMIN = "Só um administrador pode conceder o papel de administrador."
SO_ADMIN_MEXE_EM_ADMIN = "Só um administrador pode alterar a conta de outro administrador."


def _e_admin(ator: auth.TokenData) -> bool:
    return (ator.role or "").strip().lower() in permissoes.PAPEIS_TOTAIS


def _exigir_alcance_de_papel(ator: auth.TokenData, papel_alvo: Optional[str]) -> None:
    """Só admin concede o papel de admin (achado #9).

    Sem isto, `usuarios:editar` é indistinguível de admin: quem edita contas
    cria um administrador novo, ou promove a si mesmo. A matriz de permissões
    oferece esse nível a gestor como se fosse um degrau intermediário — e não
    era. A barreira fica aqui, num lugar só, chamada por criar, editar e
    importar.
    """
    if (papel_alvo or "").strip().lower() not in permissoes.PAPEIS_TOTAIS:
        return
    if not _e_admin(ator):
        raise HTTPException(status_code=403, detail=SO_ADMIN_CONCEDE_ADMIN)


def _exigir_alcance_sobre_conta(sb, ator: auth.TokenData, user_id: str) -> None:
    """Conta de administrador só é alterada por administrador (achado #9).

    Redefinir a senha do admin era o caminho óbvio; trocar o e-mail dele e
    pedir um código de redefinição para o endereço novo era o menos óbvio e
    dava no mesmo. Desativar, reativar e apagar entram pela mesma razão: cada
    um é uma forma de decidir quem administra o portal. Falha fechada — se não
    dá para ler o papel do alvo, não dá para provar que ele não é admin.
    """
    if _e_admin(ator):
        return
    try:
        r = sb.table("users").select("id, role").eq("id", user_id).limit(1).execute()
    except Exception:  # noqa: BLE001
        logger.exception("Falha ao ler o papel da conta alvo")
        raise HTTPException(
            status_code=503,
            detail="Não foi possível verificar a conta. Tente de novo.",
        )
    alvo = (r.data or [None])[0]
    if alvo and (alvo.get("role") or "").strip().lower() in permissoes.PAPEIS_TOTAIS:
        raise HTTPException(status_code=403, detail=SO_ADMIN_MEXE_EM_ADMIN)


def _validar_email(email: str) -> str:
    limpo = (email or "").strip().lower()
    if not _EMAIL_PLAUSIVEL.match(limpo):
        raise HTTPException(status_code=422, detail=f"E-mail inválido: {email!r}")
    return limpo


def _garantir_email_livre(sb: Any, email: str, ignorar_id: Optional[str] = None) -> None:
    """
    Recusa e-mail já usado por outra conta.

    O índice único no banco é quem fecha de verdade — esta checagem tem janela
    de corrida e existe para a mensagem ser legível em vez de um 400 cru do
    PostgREST. As duas camadas servem a coisas diferentes.
    """
    try:
        existentes = sb.table("users").select("id, email").execute().data or []
    except Exception:
        logger.exception("Falha ao verificar e-mail duplicado")
        raise HTTPException(
            status_code=503, detail="Não foi possível verificar o e-mail agora."
        )
    for u in existentes:
        if str(u.get("email") or "").strip().lower() == email and str(u.get("id")) != str(ignorar_id):
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Já existe uma conta com o e-mail {email}. O e-mail identifica "
                    "a pessoa no login — duas contas com o mesmo endereço deixam "
                    "uma delas inacessível."
                ),
            )


@app.post("/api/users", dependencies=[Depends(require_modulo("usuarios", permissoes.NIVEL_EDITAR))])
def create_user(body: UserCreateBody, ator: auth.TokenData = Depends(require_auth)) -> dict:
    from app.settings_state import _banco
    sb = _banco()
    if not sb: raise HTTPException(status_code=503)

    # A validação não existia aqui: qualquer string virava papel. Com o CHECK
    # no banco isso passaria a estourar como 400 genérico do PostgREST, sem
    # dizer qual valor era aceito.
    role = (body.role or "user").strip().lower()
    if role not in PAPEIS_VALIDOS:
        raise HTTPException(
            status_code=422,
            detail=f"Nível inválido. Use: {', '.join(PAPEIS_VALIDOS)}.",
        )
    _exigir_alcance_de_papel(ator, role)

    email = _validar_email(body.email)
    if len((body.password or "").strip()) < SENHA_MINIMA:
        raise HTTPException(
            status_code=422,
            detail=f"A senha precisa ter no mínimo {SENHA_MINIMA} caracteres.",
        )
    _garantir_email_livre(sb, email)

    hash_pw = auth.get_password_hash(body.password)
    try:
        sb.table("users").insert({
            # Quem cadastrou sabe a senha que digitou. Ela serve para o primeiro
            # acesso e nada mais — `require_auth` recusa o resto do portal até a
            # pessoa escolher uma própria.
            "deve_trocar_senha": True,
            "departamento_id": (body.departamento_id or "").strip() or None,
            "email": email,
            "password_hash": hash_pw,
            "full_name": body.full_name,
            "role": role,
            "ativo": True,
        }).execute()
        return {"ok": True}
    except Exception:
        logger.exception("Falha ao criar usuário")
        raise HTTPException(status_code=400, detail="Não foi possível criar o usuário.")


def _garantir_que_sobra_admin(
    sb: Any,
    user_id: str,
    *,
    novo_role: Optional[str] = None,
    novo_ativo: Optional[bool] = None,
    apagar: bool = False,
) -> None:
    """
    Recusa a operação se ela deixaria o portal **sem nenhum administrador ativo**.

    A regra é "tem de sobrar um", e não "não mexa em si mesmo". A segunda
    formulação parece equivalente e não é: com dois admins, um poderia
    rebaixar o outro e depois sair, e nenhuma das duas ações seria sobre si
    mesmo. E com um admin só — que é o caso do portal hoje — a versão correta
    também bloqueia desativar, rebaixar e apagar, que são três caminhos para o
    mesmo buraco.

    O buraco é sem fundo: a tela de Usuários é `require_admin`, então sem admin
    ativo **não há como voltar pela interface**. Só SQL direto no banco.

    Simula a mudança e conta o que restaria — assim as três rotas usam a mesma
    regra e não há como uma delas divergir.
    """
    try:
        us = sb.table("users").select("id, role, ativo").execute().data or []
    except Exception:
        # Não dá para afirmar que sobra admin. Recusar é o lado seguro: o custo
        # é uma operação adiada; o do contrário é um portal sem dono.
        logger.exception("Falha ao verificar administradores restantes")
        raise HTTPException(
            status_code=503,
            detail="Não foi possível verificar os administradores agora. Tente novamente.",
        )

    restantes = 0
    for u in us:
        if str(u.get("id")) == str(user_id):
            if apagar:
                continue
            papel = novo_role if novo_role is not None else (u.get("role") or "")
            ativo = novo_ativo if novo_ativo is not None else u.get("ativo")
            u = {**u, "role": papel, "ativo": ativo}
        if (u.get("role") or "").strip().lower() == "admin" and auth.conta_ativa(u):
            restantes += 1

    if restantes == 0:
        raise HTTPException(
            status_code=409,
            detail=(
                "Esta é a única conta de administrador ativa. Promova outro "
                "administrador antes de desativar, rebaixar ou apagar esta — "
                "sem nenhum admin, não há como voltar pela tela."
            ),
        )


@app.put("/api/users/{user_id}", dependencies=[Depends(require_modulo("usuarios", permissoes.NIVEL_EDITAR))])
def update_user(user_id: str, body: UserUpdateBody, ator: auth.TokenData = Depends(require_auth)) -> dict:
    from app.settings_state import _banco
    sb = _banco()
    if not sb:
        raise HTTPException(status_code=503)
    _exigir_alcance_sobre_conta(sb, ator, user_id)
    role = (body.role or "user").strip().lower()
    ativo = body.ativo

    # Cliente antigo mandando role="disabled" quer dizer "desative" — nunca
    # quis dizer "o papel dele agora é disabled", embora fosse isso que
    # acontecia. Traduz para o estado e preserva o papel gravado.
    if role == "disabled":
        ativo = False
        role = None

    if role is not None and role not in PAPEIS_VALIDOS:
        raise HTTPException(
            status_code=422,
            detail=f"Nível inválido. Use: {', '.join(PAPEIS_VALIDOS)}.",
        )
    _exigir_alcance_de_papel(ator, role)

    email = _validar_email(body.email)
    _garantir_email_livre(sb, email, ignorar_id=user_id)
    _garantir_que_sobra_admin(sb, user_id, novo_role=role, novo_ativo=ativo)

    campos: Dict[str, Any] = {
        "email": email,
        "full_name": body.full_name.strip(),
    }
    if role is not None:
        campos["role"] = role
    if ativo is not None:
        campos["ativo"] = bool(ativo)
    if body.departamento_id is not None:
        did = body.departamento_id.strip()
        campos["departamento_id"] = did or None
    if body.gestor_id is not None:
        gid = body.gestor_id.strip()
        if gid and gid == user_id:
            raise HTTPException(status_code=422, detail="Um usuário não pode ser gestor de si mesmo.")
        campos["gestor_id"] = gid or None

    # Nada a fazer com as seleções de alerta ao trocar o e-mail: desde a fase
    # 3c elas são chaveadas por `user_id`, então a identidade não se move. O
    # `_mover_selecoes_de_email` que existia aqui, e a leitura do endereço
    # anterior que o alimentava, viraram código morto e saíram — poder apagar
    # aquele helper era o sinal de que o rechaveamento tinha terminado.
    try:
        sb.table("users").update(campos).eq("id", user_id).execute()
    except Exception:
        logger.exception("Falha ao atualizar usuário %s", user_id)
        raise HTTPException(status_code=400, detail="Não foi possível salvar o usuário.")
    if ativo is False:
        _revogar_tokens_de_instalacao(user_id)
    return {"ok": True}


@app.post("/api/users/{user_id}/reset-password", dependencies=[Depends(require_modulo("usuarios", permissoes.NIVEL_EDITAR))])
def reset_user_password(user_id: str, body: UserResetPasswordBody, ator: auth.TokenData = Depends(require_auth)) -> dict:
    from app.settings_state import _banco
    sb = _banco()
    if not sb:
        raise HTTPException(status_code=503)
    _exigir_alcance_sobre_conta(sb, ator, user_id)
    new_pw = (body.password or "").strip()
    if len(new_pw) < 6:
        raise HTTPException(status_code=422, detail="Senha deve ter no mínimo 6 caracteres.")
    hash_pw = auth.get_password_hash(new_pw)
    try:
        # Mesma razão do cadastro: o admin conhece a senha que acabou de
        # digitar. Sem isto ela valeria indefinidamente.
        sb.table("users").update(
            {
                "password_hash": hash_pw,
                "deve_trocar_senha": True,
                # Mesmo carimbo de `senha_redefinir` e `senha_trocar` (achado
                # #24): trocar a senha derruba as sessões abertas, venha a
                # troca de quem vier. Sem ele, o token de quem acabou de ter a
                # senha redefinida continuava válido — e a proteção inteira
                # pendurava só em `deve_trocar_senha`.
                "senha_alterada_em": datetime.now(timezone.utc).isoformat(),
            }
        ).eq("id", user_id).execute()
        return {"ok": True}
    except Exception:
        logger.exception("Falha ao redefinir a senha de %s", user_id)
        raise HTTPException(status_code=400, detail="Não foi possível redefinir a senha.")


@app.post("/api/users/{user_id}/deactivate", dependencies=[Depends(require_modulo("usuarios", permissoes.NIVEL_EDITAR))])
def deactivate_user(user_id: str, ator: auth.TokenData = Depends(require_auth)) -> dict:
    """
    Desativa a conta **preservando o papel**.

    Até 15/08 isto gravava `role = "disabled"`, o que apagava o papel: reativar
    um administrador virava adivinhação, e o mesmo teria acontecido com gestor —
    levando junto o sentido das carteiras que ele tivesse criado.
    """
    from app.settings_state import _banco
    sb = _banco()
    if not sb:
        raise HTTPException(status_code=503)
    _exigir_alcance_sobre_conta(sb, ator, user_id)
    _garantir_que_sobra_admin(sb, user_id, novo_ativo=False)
    try:
        sb.table("users").update({"ativo": False}).eq("id", user_id).execute()
    except Exception:
        logger.exception("Falha ao desativar %s", user_id)
        raise HTTPException(status_code=400, detail="Não foi possível desativar a conta.")
    _revogar_tokens_de_instalacao(user_id)

    # A carteira e removida DEPOIS de a conta cair, e nunca antes.
    #
    # Se a ordem fosse inversa e a inativacao falhasse, a pessoa continuaria
    # entrando no portal e teria perdido a carteira — o pior dos dois mundos.
    # Nesta ordem, a falha aqui deixa uma carteira orfa de uma conta que ja nao
    # entra: inofensiva, e visivel na tela de Carteiras para ser limpa a mao.
    #
    # Nao e barreira de seguranca: `require_auth` ja recusa conta inativa com
    # 401, entao a carteira de quem foi inativado nao concede nada mesmo antes
    # disto. E higiene — e uma decisao IRREVERSIVEL, por isso a tela mostra a
    # contagem antes de perguntar.
    removidos = 0
    try:
        alvo = sb.table("carteira").select("user_id").eq("user_id", user_id).execute().data or []
        removidos = len(alvo)
        if removidos:
            sb.table("carteira").delete().eq("user_id", user_id).execute()
    except Exception as e:  # noqa: BLE001
        logger.error(
            "Conta %s desativada, mas a carteira NAO foi limpa (%d vinculo(s)): %s",
            user_id, removidos, e,
        )
        return {"ok": True, "carteira_removida": 0, "carteira_falhou": True}

    return {"ok": True, "carteira_removida": removidos}


@app.get(
    "/api/users/{user_id}/carteira/contagem",
    dependencies=[Depends(require_modulo("usuarios", permissoes.NIVEL_EDITAR))],
)
def contar_carteira_do_usuario(user_id: str) -> dict:
    """Quantos clientes a pessoa tem, para a confirmacao dizer o numero.

    Rota separada, e nao um campo em `/api/users`: aquela lista carrega dezenas
    de linhas em toda abertura da tela, e esta contagem so interessa no
    instante de inativar alguem.
    """
    from app.settings_state import _banco
    sb = _banco()
    if not sb:
        # Sem contagem, a tela pergunta sem o numero — o que ainda e melhor do
        # que travar a inativacao por causa do texto do aviso.
        return {"total": None}
    try:
        linhas = sb.table("carteira").select("user_id").eq("user_id", user_id).execute().data or []
        return {"total": len(linhas)}
    except Exception:  # noqa: BLE001
        logger.warning("Nao foi possivel contar a carteira de %s", user_id)
        return {"total": None}


@app.post("/api/users/{user_id}/reactivate", dependencies=[Depends(require_modulo("usuarios", permissoes.NIVEL_EDITAR))])
def reactivate_user(user_id: str, ator: auth.TokenData = Depends(require_auth)) -> dict:
    """
    Reativa a conta, devolvendo o papel que ela sempre teve.

    Não existia contrapartida para o desativar: o único caminho de volta era
    editar o nível na mão e escolher um papel de memória. Com estado e papel
    separados, reativar deixa de ser uma decisão.

    As contas desativadas ANTES desta separação são a exceção: o papel delas foi
    sobrescrito e a migration as pôs em 'user', o menor privilégio. Se alguma
    era admin, promover é ato explícito — e é assim que deve ser.
    """
    from app.settings_state import _banco
    sb = _banco()
    if not sb:
        raise HTTPException(status_code=503)
    _exigir_alcance_sobre_conta(sb, ator, user_id)
    try:
        sb.table("users").update({"ativo": True}).eq("id", user_id).execute()
        return {"ok": True}
    except Exception:
        logger.exception("Falha ao reativar %s", user_id)
        raise HTTPException(status_code=400, detail="Não foi possível reativar a conta.")


@app.delete("/api/users/{user_id}", dependencies=[Depends(require_modulo("usuarios", permissoes.NIVEL_EDITAR))])
def delete_user(user_id: str, ator: auth.TokenData = Depends(require_auth)) -> dict:
    from app.settings_state import _banco
    sb = _banco()
    if not sb: raise HTTPException(status_code=503)
    _exigir_alcance_sobre_conta(sb, ator, user_id)
    _garantir_que_sobra_admin(sb, user_id, apagar=True)
    # Antes de apagar a linha: a chave estrangeira de `install_token` aponta
    # para ela, e o token pendente é o que ainda entregaria chave privada.
    _revogar_tokens_de_instalacao(user_id)
    sb.table("users").delete().eq("id", user_id).execute()
    return {"ok": True}


def _revogar_tokens_de_instalacao(user_id: str) -> None:
    """Desativar, excluir ou inativar alguém alcança os tokens que ele pediu (#22).

    O comentário antigo em `deactivate_user` dizia que `require_auth` já
    recusava a conta inativa — verdade para o portal, falso para `/claim`,
    que não autentica. O token pendente continuava trocável por chave privada
    até o TTL. Nunca levanta: a conta já foi desativada; falhar aqui não pode
    desfazer isso, só avisar.
    """
    try:
        n = cert_installer.revogar_tokens_pendentes(user_id)
    except Exception:  # noqa: BLE001
        logger.exception("Falha ao revogar tokens de instalação de %s", user_id)
        return
    if n:
        logger.info("Conta %s: %d token(s) de instalação pendente(s) revogado(s).", user_id, n)


# ══════════════════════════════════════════════════════════════════════════
# Departamentos
#
# O departamento recorta quem cada líder pode liberar. Criar, renomear e
# apagar setor é de ADMIN: quem define os setores define, por consequência, o
# alcance de cada líder — deixar isso com o próprio líder o deixaria ampliar o
# próprio alcance criando setores e se pondo neles.
# ══════════════════════════════════════════════════════════════════════════


class DepartamentoBody(BaseModel):
    nome: str


class DepartamentoLideresBody(BaseModel):
    lideres: List[str] = Field(default_factory=list)


def _nome_de_departamento(nome: str) -> str:
    limpo = (nome or "").strip()
    if not limpo:
        raise HTTPException(status_code=422, detail="O nome do departamento é obrigatório.")
    if len(limpo) > 80:
        raise HTTPException(status_code=422, detail="Nome muito longo (máximo 80 caracteres).")
    return limpo


# `require_admin`, e nao `require_admin_ou_lider`: a unica tela que consome
# isto hoje e /usuarios, que ja e de admin. Quando o lider precisar ver os
# proprios setores (etapa 4), a rota certa e outra, escopada a ele -- esta
# devolve TODOS os departamentos, e alcance total nao e o do lider.
@app.get("/api/departamentos", dependencies=[Depends(require_modulo("usuarios"))])
def listar_departamentos() -> List[dict]:
    """
    Setores com os líderes e quantas pessoas têm.

    A contagem vem junto porque é o que responde "posso apagar este?" sem um
    segundo clique — e apagar um setor com gente dentro deixa essas pessoas
    sem departamento, o que ninguém quer descobrir depois.
    """
    from app.settings_state import _banco

    sb = _banco()
    if not sb:
        return []
    try:
        deps = sb.table("departamento").select("id, nome, criado_em").execute().data or []
        lids = sb.table("departamento_lider").select("departamento_id, user_id").execute().data or []
        pessoas = sb.table("users").select("id, full_name, email, departamento_id, ativo, role").execute().data or []
    except Exception:  # noqa: BLE001
        logger.exception("Falha ao listar departamentos")
        raise HTTPException(status_code=503, detail="Não foi possível listar os departamentos.")

    por_id = {str(u["id"]): u for u in pessoas}
    membros: Dict[str, int] = defaultdict(int)
    for u in pessoas:
        if u.get("departamento_id"):
            membros[str(u["departamento_id"])] += 1

    lideres: Dict[str, List[dict]] = defaultdict(list)
    for l in lids:
        u = por_id.get(str(l.get("user_id")))
        if not u:
            continue
        lideres[str(l.get("departamento_id"))].append({
            "id": str(u["id"]),
            "nome": u.get("full_name") or u.get("email"),
            "ativo": bool(conta_ativa(u)),
        })

    saida = []
    for d in deps:
        did = str(d["id"])
        saida.append({
            "id": did,
            "nome": d.get("nome"),
            "criado_em": d.get("criado_em"),
            "lideres": sorted(lideres.get(did, []), key=lambda x: x["nome"] or ""),
            "membros": membros.get(did, 0),
        })
    return sorted(saida, key=lambda x: (x["nome"] or "").lower())


@app.post("/api/departamentos", dependencies=[Depends(require_modulo("usuarios", permissoes.NIVEL_EDITAR))])
def criar_departamento(body: DepartamentoBody) -> dict:
    from app.settings_state import _banco

    sb = _banco()
    if not sb:
        raise HTTPException(status_code=503, detail="Sistema sem banco configurado.")
    nome = _nome_de_departamento(body.nome)
    try:
        r = sb.table("departamento").insert({"nome": nome}).execute()
    except Exception as e:  # noqa: BLE001
        # O índice único é sobre lower(btrim(nome)). A mensagem crua do
        # PostgREST diria "duplicate key value violates unique constraint", que
        # não ajuda quem está olhando um campo de texto.
        if "duplicate" in str(e).lower() or "unique" in str(e).lower():
            raise HTTPException(status_code=409, detail=f"Já existe um departamento chamado {nome}.")
        logger.exception("Falha ao criar departamento")
        raise HTTPException(status_code=400, detail="Não foi possível criar o departamento.")
    return {"ok": True, "id": str((r.data or [{}])[0].get("id", ""))}


@app.put("/api/departamentos/{dep_id}", dependencies=[Depends(require_modulo("usuarios", permissoes.NIVEL_EDITAR))])
def renomear_departamento(dep_id: str, body: DepartamentoBody) -> dict:
    from app.settings_state import _banco

    sb = _banco()
    if not sb:
        raise HTTPException(status_code=503, detail="Sistema sem banco configurado.")
    nome = _nome_de_departamento(body.nome)
    try:
        sb.table("departamento").update({"nome": nome}).eq("id", dep_id).execute()
    except Exception as e:  # noqa: BLE001
        if "duplicate" in str(e).lower() or "unique" in str(e).lower():
            raise HTTPException(status_code=409, detail=f"Já existe um departamento chamado {nome}.")
        logger.exception("Falha ao renomear departamento %s", dep_id)
        raise HTTPException(status_code=400, detail="Não foi possível renomear o departamento.")
    return {"ok": True}


@app.delete("/api/departamentos/{dep_id}", dependencies=[Depends(require_modulo("usuarios", permissoes.NIVEL_EDITAR))])
def apagar_departamento(dep_id: str) -> dict:
    """
    Apaga o setor. As pessoas dele ficam SEM departamento, não são apagadas —
    é o `ON DELETE SET NULL` da migration, e a escolha é deliberada: perder o
    vínculo é corrigível na tela, perder as contas não.

    As lideranças caem junto (`ON DELETE CASCADE`): liderança de um setor que
    não existe mais daria alcance sobre nada e confundiria a leitura.
    """
    from app.settings_state import _banco

    sb = _banco()
    if not sb:
        raise HTTPException(status_code=503, detail="Sistema sem banco configurado.")
    try:
        sb.table("departamento").delete().eq("id", dep_id).execute()
    except Exception:  # noqa: BLE001
        logger.exception("Falha ao apagar departamento %s", dep_id)
        raise HTTPException(status_code=400, detail="Não foi possível apagar o departamento.")
    return {"ok": True}


@app.put("/api/departamentos/{dep_id}/lideres", dependencies=[Depends(require_modulo("usuarios", permissoes.NIVEL_EDITAR))])
def definir_lideres(dep_id: str, body: DepartamentoLideresBody) -> dict:
    """
    Substitui a lista de líderes do setor.

    Substitui em vez de somar porque a tela mostra a lista inteira: se o
    servidor só acrescentasse, tirar alguém exigiria uma rota a mais e a tela
    passaria a mentir sobre o que salvou.
    """
    from app.settings_state import _banco

    sb = _banco()
    if not sb:
        raise HTTPException(status_code=503, detail="Sistema sem banco configurado.")

    ids = [str(x).strip() for x in (body.lideres or []) if str(x).strip()]
    if len(set(ids)) != len(ids):
        raise HTTPException(status_code=422, detail="A mesma pessoa aparece duas vezes na lista.")

    if ids:
        try:
            achados = sb.table("users").select("id, role, ativo").execute().data or []
        except Exception:  # noqa: BLE001
            raise HTTPException(status_code=503, detail="Não foi possível validar os líderes agora.")
        por_id = {str(u["id"]): u for u in achados}
        for uid in ids:
            u = por_id.get(uid)
            if not u:
                raise HTTPException(status_code=422, detail="Um dos líderes escolhidos não existe.")
            if not conta_ativa(u):
                # Líder desativado não entra no portal, então o setor ficaria
                # com um responsável que não consegue liberar nada — a mesma
                # situação de não ter líder, mas parecendo resolvida.
                raise HTTPException(
                    status_code=422,
                    detail="Não é possível designar uma conta desativada como líder.",
                )

    try:
        sb.table("departamento_lider").delete().eq("departamento_id", dep_id).execute()
        if ids:
            sb.table("departamento_lider").insert(
                [{"departamento_id": dep_id, "user_id": uid} for uid in ids]
            ).execute()
    except Exception:  # noqa: BLE001
        logger.exception("Falha ao definir líderes")
        raise HTTPException(status_code=400, detail="Não foi possível gravar os líderes.")
    return {"ok": True, "lideres": len(ids)}


class PermissoesBody(BaseModel):
    matriz: Dict[str, Dict[str, str]]


# `require_admin`, e NAO `require_modulo("usuarios", editar)`. A diferenca e
# elevacao de privilegio: quem edita a matriz pode se dar qualquer acesso, entao
# amarrar isto ao proprio modulo Usuarios deixaria um gestor com escrita em
# Usuarios se autoconceder Configuracao e Instalador. Quem concede tem que estar
# acima do que concede.
@app.get("/api/permissoes/trilha", dependencies=[Depends(require_admin)])
def get_trilha_permissoes(limite: int = Query(30, ge=1, le=200)) -> dict:
    """Histórico de concessão e revogação de acesso.

    `require_admin` pelo mesmo motivo da matriz: a trilha diz quem alcança o
    quê e quem decidiu isso. Gatear pela própria matriz deixaria um gestor com
    escrita em Usuários lendo — e depois reescrevendo — o registro das próprias
    concessões.

    Nunca falha: `ler_trilha` devolve lista vazia quando não há de onde ler. A
    aba de Níveis de acesso não pode parar de funcionar porque o histórico
    ficou indisponível.
    """
    return {"itens": permissoes.ler_trilha(limite)}


@app.get("/api/permissoes", dependencies=[Depends(require_admin)])
def get_permissoes() -> dict:
    """A matriz para a tela: o que cada papel configuravel alcanca hoje."""
    try:
        return {
            "modulos": [
                {
                    "id": m,
                    # Os niveis que ESTE modulo aceita. Sem rota de escrita,
                    # `editar` nao e oferecido — seria configurar uma diferenca
                    # que nao existe.
                    "niveis": list(permissoes.niveis_de_modulo(m)),
                    # Modulo ainda nao ligado a rota nenhuma: a tela precisa
                    # dizer isso, senao oferece um controle que nao governa.
                    "governado": m in permissoes.MODULOS_GOVERNADOS,
                }
                for m in permissoes.MODULOS
            ],
            "niveis": list(permissoes.NIVEIS),
            "papeis": list(permissoes.PAPEIS_CONFIGURAVEIS),
            # Informativo: a tela mostra a coluna de admin travada, para
            # responder "cade o admin?" antes de alguem perguntar.
            "papeis_totais": list(permissoes.PAPEIS_TOTAIS),
            "matriz": {
                papel: permissoes.matriz_para_papel(papel)
                for papel in permissoes.PAPEIS_CONFIGURAVEIS
            },
        }
    except permissoes.PermissoesIndisponiveis as e:
        logger.error("Permissoes indisponiveis: %s", e)
        raise HTTPException(status_code=503, detail="Nao foi possivel ler as permissoes. Tente de novo.")


# `require_auth`, e nao `require_admin`: cada um le a PROPRIA linha, e e o que o
# menu precisa para se montar. Nao expoe a matriz dos outros papeis — quem quer
# ver a matriz inteira usa `GET /api/permissoes`, que exige admin.
@app.get("/api/permissoes/minhas", dependencies=[Depends(require_auth)])
def get_minhas_permissoes(token: auth.TokenData = Depends(require_auth)) -> dict:
    """O que o papel de quem chama alcanca, modulo a modulo."""
    try:
        return {"modulos": permissoes.matriz_para_papel(token.role or "")}
    except permissoes.PermissoesIndisponiveis as e:
        # 503, e nao um dicionario vazio: vazio faria o menu sumir inteiro e
        # parecer que a pessoa perdeu todos os acessos. O front trata o erro
        # mantendo o menu que ja estava.
        logger.error("Permissoes indisponiveis: %s", e)
        raise HTTPException(status_code=503, detail="Nao foi possivel ler suas permissoes. Tente de novo.")


@app.put("/api/permissoes", dependencies=[Depends(require_admin)])
def put_permissoes(body: PermissoesBody, token: auth.TokenData = Depends(require_auth)) -> dict:
    """Grava a matriz inteira. Ver `permissoes.gravar` para o porque de inteira."""
    try:
        salva = permissoes.gravar(body.matriz, alterado_por=(token.email or ""))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except permissoes.PermissoesIndisponiveis as e:
        logger.error("Permissoes indisponiveis ao gravar: %s", e)
        raise HTTPException(status_code=503, detail="Nao foi possivel gravar a matriz. Tente de novo.")
    return {"ok": True, "matriz": salva}


@app.get("/api/health")
def health() -> dict:
    """Sinal de vida, e só.

    Até o lote 1 da auditoria (achado #48) esta rota pública devolvia os
    booleanos de postura do deploy — e `api_key_required: false` dizia a um
    anônimo, numa requisição, que todas as rotas /api/* aceitavam identidade
    anônima. Era o sinal mais valioso do portal para quem faz reconhecimento.
    O detalhe continua existindo, em `/api/health/detalhado`, para admin.
    """
    return {"ok": True}


@app.get("/api/health/detalhado", dependencies=[Depends(require_admin)])
def health_detalhado() -> dict:
    """
    Estado de configuração do ambiente.

    Devolve apenas BOOLEANOS de "está configurado?", nunca valores. Serve para
    conferir um deploy sem descobrir por tentativa e erro: o .env não sobe no
    deploy, então cada ambiente precisa ter suas variáveis definidas.
    `scripts/verificar_deploy.py --token` e a tela de Configuração leem daqui.
    """
    return {
        "ok": True,
        "banco": banco_configurado(),
        "api_key_required": bool(config.API_KEY),
        # Sem esta chave o cofre não funciona: /upload-pfx falha no primeiro
        # certificado que o agente tentar enviar.
        "cert_vault_key_configurada": bool(
            config.CERT_ENCRYPTION_KEY and len(config.CERT_ENCRYPTION_KEY) == 64
        ),
        # Chave da SENHA do PFX. Sem ela — ou igual à do PFX, que a aplicação
        # recusa — `upsert_pfx` levanta e /upload-pfx devolve 500. O sintoma
        # aparece longe daqui: o cofre mantém o registro antigo, sem senha, e o
        # instalador avulso falha na máquina do usuário com "o portal não
        # enviou a senha". Sem estes dois campos, descobrir isso exige ler o
        # agent.log de um servidor.
        "cert_senha_key_configurada": bool(
            config.CERT_PASSWORD_ENCRYPTION_KEY
            and len(config.CERT_PASSWORD_ENCRYPTION_KEY) == 64
        ),
        "cert_senha_key_distinta": bool(
            config.CERT_PASSWORD_ENCRYPTION_KEY
            and config.CERT_PASSWORD_ENCRYPTION_KEY != config.CERT_ENCRYPTION_KEY
        ),
        # Ausente, a chave do SMTP é derivada da JWT_SECRET_KEY — o que faz a
        # senha SMTP parar de descriptografar se a JWT diferir entre ambientes.
        "smtp_key_dedicada": bool(os.getenv("ENCRYPTION_KEY")),
        "jwt_configurado": bool(os.getenv("JWT_SECRET_KEY")),
    }


def _settings_dict(s: PortalSettings) -> dict:
    return {
        "source_folder": s.source_folder,
        "expired_folder": s.expired_folder,
        "machine_id": s.machine_id,
        "effective_source": str(s.effective_source()),
        "effective_expired": str(s.effective_expired()),
        "banco": banco_configurado(),
        "persistence": (
            "banco+data/portal_settings.json"
            if banco_configurado()
            else "data/portal_settings.json"
        ),
        "smtp_host": s.smtp_host,
        "smtp_port": s.smtp_port,
        "smtp_user": s.smtp_user,
        "smtp_password_set": bool(s.smtp_password_encrypted),
        "smtp_use_tls": s.smtp_use_tls,
        "smtp_use_ssl": s.smtp_use_ssl,
        # `efetivo` é o que realmente vale agora, com o padrão já resolvido —
        # a tela precisa mostrar isso, não o campo em branco.
        "install_token_ttl_min": s.install_token_ttl_min,
        "install_token_ttl_efetivo": cert_installer.ttl_do_token(),
        "trilha_retencao_dias": s.trilha_retencao_dias,
        "smtp_from_email": s.smtp_from_email,
        "smtp_alerts_enabled": s.smtp_alerts_enabled,
        # Alertas. O par `campo` + `campo_efetivo` segue o que o instalador já
        # fazia acima: a tela mostra o campo em branco E o que vale de fato,
        # senão "vazio" pareceria "desligado".
        "alertas_destinatarios": s.alertas_destinatarios,
        "alertas_marcos": s.alertas_marcos,
        "alertas_marcos_efetivos": list(
            alertas_config.marcos_efetivos(s.alertas_marcos)
        ),
        "alertas_intervalo_horas": s.alertas_intervalo_horas,
        "alertas_intervalo_efetivo": alertas_config.intervalo_efetivo_horas(
            s.alertas_intervalo_horas
        ),
        # "lista" ou "admins" em vez da lista de admins resolvida: montá-la
        # aqui custaria uma consulta ao banco numa rota que o agente também
        # chama, e que precisa responder mesmo com o banco ruim.
        "alertas_destinatarios_origem": (
            "lista"
            if alertas_config.destinatarios_configurados(s.alertas_destinatarios)
            else "admins"
        ),
        # Texto do e-mail. Mesmo par `campo` + `campo_efetivo`: o modal precisa
        # abrir com o campo EM BRANCO (senão a pessoa não distingue "eu escrevi
        # isto" de "é o padrão") e mostrar o padrão como placeholder.
        "alerta_email": {
            campo: getattr(s, coluna, "")
            for campo, coluna in email_modelo.CAMPO_COLUNA.items()
        },
        "alerta_email_padrao": dict(email_modelo.PADROES),
        "alerta_email_marcadores": list(email_modelo.MARCADORES),
        "alerta_email_limites": dict(email_modelo.LIMITES),
    }


# Mao dupla: a tela de Configuracao le daqui, e o agente tambem — e o que diz
# a ele quais pastas varrer. `permitir_agente` mantem o robo funcionando enquanto
# o modulo passa a governar as pessoas.
@app.get("/api/settings", dependencies=[Depends(require_modulo("configuracao", permitir_agente=True))])
def get_settings() -> dict:
    s = load_settings()
    return _settings_dict(s)


@app.put("/api/settings", dependencies=[Depends(require_modulo("configuracao", permissoes.NIVEL_EDITAR))])
def put_settings(body: SettingsBody) -> dict:
    # Lido ANTES de validar: campo omitido é validado a partir do que já está
    # gravado, e não do default. Validar o default e gravar o valor antigo
    # deixaria os dois em desacordo.
    old = load_settings()

    try:
        validate_smtp_config(
            body.smtp_use_tls, body.smtp_use_ssl,
            host=(body.smtp_host or old.smtp_host),
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    ttl = int(
        (old.install_token_ttl_min if body.install_token_ttl_min is None
         else body.install_token_ttl_min) or 0
    )
    if ttl and not (cert_installer.TTL_TOKEN_MIN <= ttl <= cert_installer.TTL_TOKEN_MAX):
        raise HTTPException(
            status_code=422,
            detail=(
                f"Validade do token: use entre {cert_installer.TTL_TOKEN_MIN} e "
                f"{cert_installer.TTL_TOKEN_MAX} minutos, ou 0 para o padrão."
            ),
        )

    retencao = int(
        (old.trilha_retencao_dias if body.trilha_retencao_dias is None
         else body.trilha_retencao_dias) or 0
    )
    if retencao < 0:
        raise HTTPException(status_code=422, detail="Retenção não pode ser negativa.")

    # Alertas: recusar aqui é a única defesa. O job roda sem ninguém olhando e
    # trata valor ilegível caindo no padrão — o que é a decisão certa PARA O
    # JOB e péssima como resposta à tela, porque a pessoa salvaria "30,15,cinco"
    # e receberia "salvo" enquanto o portal seguisse com 30,15,7,1.
    try:
        marcos = alertas_config.formatar_marcos(
            alertas_config.parse_marcos(
                old.alertas_marcos if body.alertas_marcos is None else body.alertas_marcos
            )
        )
        destinatarios = alertas_config.formatar_destinatarios(
            alertas_config.parse_destinatarios(
                old.alertas_destinatarios
                if body.alertas_destinatarios is None
                else body.alertas_destinatarios
            )
        )
        intervalo = alertas_config.validar_intervalo(
            old.alertas_intervalo_horas
            if body.alertas_intervalo_horas is None
            else body.alertas_intervalo_horas
        )
    except alertas_config.ConfiguracaoInvalida as e:
        raise HTTPException(status_code=422, detail=str(e))

    # Texto do e-mail: mesma assimetria dos marcos, e pelo mesmo motivo. O job
    # cai no padrão diante de um marcador que não existe, porque alerta que não
    # sai é pior que alerta com um `{tota}` literal no meio. Só que "cai no
    # padrão" como resposta à tela seria a pessoa salvar `{tota}`, ler "salvo" e
    # nunca ver o texto que escreveu.
    try:
        modelo = {
            campo: email_modelo.validar_campo(
                campo,
                getattr(old, coluna, "") if getattr(body, coluna) is None
                else getattr(body, coluna),
            )
            for campo, coluna in email_modelo.CAMPO_COLUNA.items()
        }
    except email_modelo.ModeloInvalido as e:
        raise HTTPException(status_code=422, detail=str(e))

    enc_password = old.smtp_password_encrypted
    if body.smtp_password is not None and body.smtp_password.strip() != "":
        try:
            enc_password = encrypt_password(body.smtp_password.strip())
        except Exception as e:
            raise HTTPException(status_code=500, detail="Erro ao criptografar senha SMTP")
            
    s = PortalSettings(
        source_folder=body.source_folder.strip(),
        expired_folder=body.expired_folder.strip(),
        machine_id=body.machine_id.strip() or "default",
        smtp_host=body.smtp_host.strip(),
        smtp_port=body.smtp_port,
        smtp_user=body.smtp_user.strip(),
        smtp_password_encrypted=enc_password,
        smtp_use_tls=body.smtp_use_tls,
        smtp_use_ssl=body.smtp_use_ssl,
        smtp_from_email=body.smtp_from_email.strip(),
        smtp_alerts_enabled=body.smtp_alerts_enabled,
        install_token_ttl_min=ttl,
        trilha_retencao_dias=retencao,
        alertas_destinatarios=destinatarios,
        alertas_marcos=marcos,
        alertas_intervalo_horas=intervalo,
        **{coluna: modelo[campo] for campo, coluna in email_modelo.CAMPO_COLUNA.items()},
    )
    # 503, e não 200: o valor foi para o arquivo local, mas `load_settings`
    # prefere o banco — a próxima leitura devolveria o valor antigo. Dizer
    # "salvo" aqui seria a tela mentindo sobre um dado que ela mesma vai
    # recarregar diferente.
    try:
        save_settings(s, exigir_banco=True)
    except GravacaoNaoPersistida as e:
        # O motivo (código do banco, coluna que falta) vai para o log, onde
        # quem vai consertar o lê; a resposta diz só o que aconteceu (#35).
        logger.error("Gravação da configuração não persistida: %s", e)
        raise HTTPException(
            status_code=503,
            detail=(
                "Não foi possível gravar no banco; nada foi alterado para o portal. "
                "A cópia local ficou guardada. Veja o log do servidor."
            ),
        )
    return _settings_dict(s)


# ══════════════════════════════════════════════════════════════════════════
# Recuperação de senha por código (A8 da auditoria de UI/UX)
# ══════════════════════════════════════════════════════════════════════════

# Resposta única para todos os desfechos do pedido: e-mail inexistente, conta
# desativada, envio bem-sucedido e até estouro do teto de pedidos. Distinguir
# transformaria a tela num detector de quem tem conta no sistema — e a lista de
# quem tem conta aqui é a lista de quem administra certificados de clientes.
RESPOSTA_GENERICA = (
    "Se houver uma conta com esse e-mail, enviamos um código de 6 dígitos. "
    "Ele vale por 15 minutos."
)

CODIGO_INVALIDO = "Código inválido ou expirado. Peça um novo se precisar."
SENHA_NAO_GRAVADA = "Não foi possível gravar a senha nova. Tente de novo em instantes."
ERRO_INTERNO_VEJA_LOG = "A operação falhou no servidor. Veja o log para o detalhe."


class SenhaCodigoBody(BaseModel):
    email: str


class SenhaVerificarBody(BaseModel):
    email: str
    codigo: str


class SenhaRedefinirBody(BaseModel):
    email: str
    codigo: str
    password: str


def _conta_para_reset(sb, email: str) -> Optional[dict]:
    """
    A conta que pode receber código: existe e está ativa.

    Desativada não recebe — redefinir senha não pode ser caminho de volta para
    quem foi removido do portal. De fora não dá para distinguir, porque a
    resposta é a mesma.
    """
    try:
        r = (
            sb.table("users")
            .select("id, email, full_name, role, ativo")
            .eq("email", email)
            .limit(1)
            .execute()
        )
    except Exception:  # noqa: BLE001
        logger.exception("Falha ao procurar conta para recuperação de senha")
        return None
    linhas = r.data or []
    if not linhas:
        return None
    conta = linhas[0]
    return conta if auth.conta_ativa(conta) else None


def _enviar_codigo_por_email(conta: dict, codigo: str) -> None:
    """Manda o código. Levanta se o SMTP falhar — o chamador decide o que fazer."""
    s = load_settings()
    if not s.smtp_host:
        raise RuntimeError("SMTP não configurado")

    base = (os.getenv("PORTAL_BASE_URL") or "").strip().rstrip("/")
    # Link só de conveniência, e só se o endereço vier de configuração. Nunca
    # do cabeçalho `Host`: ele é controlado por quem chama, e um Host forjado
    # faria o portal mandar a própria vítima para o site do atacante.
    atalho = (
        f'<p style="margin:16px 0 0;">'
        f'<a href="{base}/login">Abrir o portal</a></p>' if base else ""
    )
    nome = html.escape(str(conta.get("full_name") or "").strip() or "Olá")

    smtp_service.send_smtp_email(
        host=s.smtp_host,
        port=s.smtp_port,
        user=s.smtp_user,
        password_enc=s.smtp_password_encrypted,
        use_tls=s.smtp_use_tls,
        use_ssl=s.smtp_use_ssl,
        from_email=s.smtp_from_email,
        to_email=str(conta["email"]),
        subject="Código para redefinir sua senha",
        html_content=(
            f"<p>{nome},</p>"
            "<p>Recebemos um pedido para redefinir a senha da sua conta no "
            "Monitor de Certificados. Use o código abaixo:</p>"
            f'<p style="font-size:28px;letter-spacing:6px;font-weight:700;'
            f'margin:24px 0;">{codigo}</p>'
            f"<p>Ele vale por {senha_reset.VALIDADE_MIN} minutos e só pode ser "
            "usado uma vez.</p>"
            "<p><strong>Se não foi você que pediu</strong>, ignore este e-mail: "
            "sua senha continua a mesma. Ninguém consegue trocá-la sem este "
            "código.</p>"
            f"{atalho}"
        ),
    )


def _enviar_codigo_em_segundo_plano(conta: dict, codigo: str) -> None:
    """Corre depois da resposta. Aqui o `except` é obrigatório: uma exceção em
    tarefa de fundo não tem quem a receba, e o log é o único sintoma."""
    try:
        _enviar_codigo_por_email(conta, codigo)
    except Exception:  # noqa: BLE001
        # ERROR e não warning: a pessoa está olhando para uma tela que diz que
        # o código foi enviado, e ele não foi. Sem este log ninguém descobre.
        logger.exception(
            "Código gerado mas NÃO enviado — a pessoa vai esperar um e-mail que não chega."
        )


@app.post("/api/senha/codigo")
def senha_pedir_codigo(body: SenhaCodigoBody, request: Request, background: BackgroundTasks) -> dict:
    """
    Pede um código de redefinição. **Responde sempre a mesma coisa.**

    O 200 genérico é o ponto: qualquer variação de mensagem, status ou tempo
    de resposta entre "existe" e "não existe" vira enumeração de contas.
    """
    from app.settings_state import _banco

    sb = _banco()
    if not sb:
        raise HTTPException(status_code=503, detail="Sistema sem banco configurado.")

    ip = _ip_do_cliente(request)
    # Teto por IP (achado #8). Os tetos de `senha_reset` são por CONTA: com
    # uma lista de endereços, um anônimo disparava 3 e-mails/hora por endereço
    # pelo SMTP da empresa, sem credencial nenhuma. Estourou → 200 genérico, e
    # não 429: um 429 aqui já seria sinal para quem está enumerando.
    if not taxa.permitir(f"reset-ip:{ip}", 5, 3600):
        logger.warning("Teto de pedidos de código por IP atingido.")
        return {"ok": True, "message": RESPOSTA_GENERICA}

    email = (body.email or "").strip().lower()
    if not email:
        return {"ok": True, "message": RESPOSTA_GENERICA}

    conta = _conta_para_reset(sb, email)
    if not conta:
        # Log em nível de info, sem alarde: e-mail digitado errado é o caso
        # comum, e não um incidente.
        logger.info("Pedido de código para e-mail sem conta ativa.")
        return {"ok": True, "message": RESPOSTA_GENERICA}

    try:
        codigo = senha_reset.criar_codigo(str(conta["id"]), client_ip=ip)
    except senha_reset.LimiteDePedidos:
        # Mesma resposta de propósito: dizer "você pediu demais" confirmaria
        # que a conta existe, que é justamente o que o genérico esconde.
        logger.warning(
            "Teto de %d pedidos/hora atingido para uma conta.",
            senha_reset.MAX_PEDIDOS_HORA,
        )
        return {"ok": True, "message": RESPOSTA_GENERICA}
    except Exception:  # noqa: BLE001
        logger.exception("Falha ao criar código de redefinição")
        raise HTTPException(
            status_code=503,
            detail="Não foi possível gerar o código agora. Tente de novo em instantes.",
        )

    # O SMTP sai do caminho da resposta. Dentro dele, fazia duas coisas ruins:
    # segurava o worker por até 10 s (o pool tem 6 conexões), e era o oráculo
    # de timing — conta inexistente respondia na hora, existente esperava o
    # servidor de e-mail. O 200 genérico não escondia nada.
    background.add_task(_enviar_codigo_em_segundo_plano, conta, codigo)

    return {"ok": True, "message": RESPOSTA_GENERICA}


def _exigir_teto_de_conferencia(request: Request) -> None:
    """Teto por IP para conferir ou consumir código (achado #8).

    Responde com o MESMO 400 de código errado: 429 seria uma terceira resposta,
    e o fluxo inteiro foi desenhado para ter só duas.
    """
    if not taxa.permitir(f"reset-verif:{_ip_do_cliente(request)}", 20, 3600):
        logger.warning("Teto de conferências de código por IP atingido.")
        raise HTTPException(status_code=400, detail=CODIGO_INVALIDO)


@app.post("/api/senha/verificar")
def senha_verificar_codigo(body: SenhaVerificarBody, request: Request) -> dict:
    """
    Confere o código **sem consumi-lo**, para a tela avançar antes de a pessoa
    digitar a senha nova.

    Sem este passo, um código errado só apareceria depois de ela preencher a
    senha duas vezes — e já teria queimado uma das três tentativas à toa.
    """
    from app.settings_state import _banco

    sb = _banco()
    if not sb:
        raise HTTPException(status_code=503, detail="Sistema sem banco configurado.")

    _exigir_teto_de_conferencia(request)
    conta = _conta_para_reset(sb, (body.email or "").strip().lower())
    if not conta:
        # Sem conta, não há código. Recusa com a mesma mensagem de código
        # errado, para não distinguir os dois casos.
        raise HTTPException(status_code=400, detail=CODIGO_INVALIDO)

    ok, _ = senha_reset.conferir(str(conta["id"]), body.codigo or "")
    if not ok:
        raise HTTPException(status_code=400, detail=CODIGO_INVALIDO)
    return {"ok": True}


@app.post("/api/senha/redefinir")
def senha_redefinir(body: SenhaRedefinirBody, request: Request) -> dict:
    """
    Consome o código e grava a senha nova.

    Reconfere o código aqui em vez de confiar no `/verificar`: aquele passo é
    conveniência de tela, não credencial. Quem chamar esta rota direto tem de
    apresentar o código do mesmo jeito.
    """
    from app.settings_state import _banco

    sb = _banco()
    if not sb:
        raise HTTPException(status_code=503, detail="Sistema sem banco configurado.")

    nova = (body.password or "").strip()
    if len(nova) < SENHA_MINIMA:
        raise HTTPException(
            status_code=422,
            detail=f"A senha precisa ter no mínimo {SENHA_MINIMA} caracteres.",
        )

    _exigir_teto_de_conferencia(request)
    email = (body.email or "").strip().lower()
    conta = _conta_para_reset(sb, email)
    if not conta:
        raise HTTPException(status_code=400, detail=CODIGO_INVALIDO)

    if not senha_reset.consumir(str(conta["id"]), body.codigo or ""):
        raise HTTPException(status_code=400, detail=CODIGO_INVALIDO)

    agora = datetime.now(timezone.utc).isoformat()
    try:
        sb.table("users").update(
            {
                "password_hash": auth.get_password_hash(nova),
                # Carimbado na MESMA gravação da senha: separá-los abriria uma
                # janela em que a senha já mudou mas as sessões antigas ainda
                # valem — que é exatamente o que esta coluna existe para fechar.
                "senha_alterada_em": agora,
                # Aqui foi a própria pessoa quem escolheu, com um código que só
                # ela recebeu. Não há nada a cobrar depois.
                "deve_trocar_senha": False,
            }
        ).eq("id", conta["id"]).execute()
    except Exception:  # noqa: BLE001
        logger.exception("Falha ao gravar a senha nova")
        raise HTTPException(status_code=400, detail=SENHA_NAO_GRAVADA)

    atividade.registrar(
        atividade.EVENTO_SENHA_REDEFINIDA,
        user_id=str(conta["id"]),
        user_email=email,
        client_ip=request.client.host if request and request.client else None,
    )
    return {
        "ok": True,
        "message": "Senha alterada. Entre com a nova senha.",
    }


class SenhaTrocarBody(BaseModel):
    senha_atual: str
    nova_senha: str


@app.post("/api/senha/trocar")
def senha_trocar(
    body: SenhaTrocarBody,
    request: Request,
    token: auth.TokenData = Depends(require_auth),
) -> dict:
    """
    A própria pessoa troca a senha. É a única rota que responde com senha
    provisória — ver `ROTAS_COM_SENHA_PROVISORIA`.

    Exige a senha atual mesmo já estando autenticada. Parece redundante, e não
    é: com a sessão aberta e a máquina destravada, qualquer um que sente na
    cadeira definiria a senha nova sem saber a antiga, e a pessoa perderia a
    conta para quem passou por ali.
    """
    from app.settings_state import _banco

    sb = _banco()
    if not sb:
        raise HTTPException(status_code=503, detail="Sistema sem banco configurado.")

    nova = (body.nova_senha or "").strip()
    if len(nova) < SENHA_MINIMA:
        raise HTTPException(
            status_code=422,
            detail=f"A senha precisa ter no mínimo {SENHA_MINIMA} caracteres.",
        )

    uid = _user_id_da_sessao(token)
    if not uid:
        raise HTTPException(status_code=401, detail=SESSAO_ENCERRADA)

    try:
        r = sb.table("users").select("password_hash").eq("id", uid).limit(1).execute()
    except Exception:  # noqa: BLE001
        logger.exception("Falha ao ler a conta para troca de senha")
        raise HTTPException(status_code=503, detail="Não foi possível trocar a senha agora.")

    linhas = r.data or []
    if not linhas or not auth.verify_password(body.senha_atual or "", linhas[0]["password_hash"]):
        raise HTTPException(status_code=400, detail="A senha atual não confere.")

    if auth.verify_password(nova, linhas[0]["password_hash"]):
        # Sem isto, "trocar a senha" seria satisfeito repetindo a provisória —
        # e a senha que outra pessoa conhece continuaria valendo, agora com a
        # flag desligada e ninguém mais cobrando a troca.
        raise HTTPException(
            status_code=422,
            detail="A senha nova precisa ser diferente da atual.",
        )

    agora = datetime.now(timezone.utc).isoformat()
    try:
        sb.table("users").update(
            {
                "password_hash": auth.get_password_hash(nova),
                "senha_alterada_em": agora,
                "deve_trocar_senha": False,
            }
        ).eq("id", uid).execute()
    except Exception:  # noqa: BLE001
        logger.exception("Falha ao gravar a senha nova")
        raise HTTPException(status_code=400, detail=SENHA_NAO_GRAVADA)

    atividade.registrar(
        atividade.EVENTO_SENHA_REDEFINIDA,
        user_id=uid,
        user_email=token.email or "",
        client_ip=request.client.host if request and request.client else None,
        contexto={"origem": "troca_propria"},
    )
    # `senha_alterada_em` acabou de ser carimbado, então o token que fez esta
    # chamada morre na requisição seguinte — de propósito, é a mesma regra que
    # derruba sessão aberta em qualquer troca de senha. O front reconhece o 401
    # e manda para o login.
    return {"ok": True, "message": "Senha alterada. Entre novamente com a nova senha."}


class SmtpTestBody(BaseModel):
    target_email: str


@app.post("/api/settings/smtp/test", dependencies=[Depends(require_modulo("configuracao", permissoes.NIVEL_EDITAR))])
def test_smtp_config(body: SmtpTestBody) -> dict:
    s = load_settings()
    if not s.smtp_host:
        raise HTTPException(status_code=400, detail="Servidor SMTP não configurado.")
    try:
        # Qualificado pelo módulo: `send_smtp_email` nunca esteve na lista de
        # imports deste arquivo, então a rota levantava NameError em vez de
        # enviar. Só não aparecia porque ninguém clicava em "Enviar Teste".
        smtp_service.send_smtp_email(
            host=s.smtp_host,
            port=s.smtp_port,
            user=s.smtp_user,
            password_enc=s.smtp_password_encrypted,
            use_tls=s.smtp_use_tls,
            use_ssl=s.smtp_use_ssl,
            from_email=s.smtp_from_email,
            to_email=body.target_email.strip(),
            subject="Monitor de Certificados - E-mail de Teste",
            html_content="<p>Olá! Este é um e-mail de teste enviado a partir do seu <strong>Monitor de Certificados</strong> para validar as configurações de SMTP.</p>"
        )
    # Uma mensagem fixa por CLASSE de falha (achado #35; item 91 da spec de
    # telas). O texto do servidor SMTP trazia o usuário, às vezes o endereço
    # do host resolvido, e a máscara por substring era frágil. O detalhe fica
    # no log do `smtp_service`.
    except ValueError as e:
        # Validação nossa (sem TLS para servidor externo, TLS e SSL juntos):
        # texto curado, escrito para a pessoa que está configurando.
        raise HTTPException(status_code=400, detail=str(e))
    except smtp_service.ErroAutenticacaoSmtp:
        raise HTTPException(status_code=400, detail="O servidor SMTP recusou o usuário ou a senha.")
    except smtp_service.ErroTlsSmtp:
        raise HTTPException(status_code=400, detail=(
            "A conexão segura com o servidor SMTP falhou. Confira a opção de segurança e a porta."))
    except smtp_service.ErroConexaoSmtp:
        raise HTTPException(status_code=400, detail=(
            "Não foi possível conectar ao servidor SMTP. Confira o endereço e a porta."))
    except Exception:
        logger.exception("Falha no e-mail de teste")
        raise HTTPException(status_code=400, detail="Falha ao enviar o e-mail de teste. Veja o log do servidor.")
    return {"ok": True, "message": "E-mail de teste enviado com sucesso!"}


class PreviaEmailBody(BaseModel):
    """O texto que a pessoa está digitando, ainda não salvo.

    `None` em um campo é "usar o que está gravado" — a mesma semântica do
    `SettingsBody`, para a prévia de um campo em branco mostrar o padrão em vez
    de um buraco.
    """
    alerta_email_assunto: Optional[str] = Field(default=None)
    alerta_email_titulo: Optional[str] = Field(default=None)
    alerta_email_abertura: Optional[str] = Field(default=None)
    alerta_email_recado: Optional[str] = Field(default=None)


@app.post("/api/settings/alerts/preview", dependencies=[Depends(require_modulo("configuracao", permissoes.NIVEL_EDITAR))])
def preview_email_alerta(body: PreviaEmailBody) -> dict:
    """O e-mail que sairia agora com este texto, sem salvar nada.

    Valida com a MESMA `validar_campo` do PUT e devolve o mesmo 422. Uma prévia
    mais tolerante que o Salvar deixaria a pessoa aprovar na tela um texto que a
    gravação depois recusa.
    """
    old = load_settings()
    try:
        modelo = {
            campo: email_modelo.validar_campo(
                campo,
                getattr(old, coluna, "") if getattr(body, coluna) is None
                else getattr(body, coluna),
            )
            for campo, coluna in email_modelo.CAMPO_COLUNA.items()
        }
    except email_modelo.ModeloInvalido as e:
        raise HTTPException(status_code=422, detail=str(e))
    return {"ok": True, **previa_do_resumo(old, modelo)}


@app.post("/api/settings/alerts/trigger", dependencies=[Depends(require_modulo("configuracao", permissoes.NIVEL_EDITAR))])
def trigger_alerts_manually() -> dict:
    try:
        stats = trigger_all_alerts()
        return {"ok": True, "stats": stats}
    except Exception:
        logger.exception("Falha no disparo manual de alertas")
        raise HTTPException(status_code=500, detail="O disparo falhou. Veja o log do servidor.")


@app.get("/api/cron/alerts")
def cron_alerts(request: Request) -> dict:
    """
    Disparo agendado dos alertas, chamado pelo Cron do Vercel.

    Existe porque o laço do `lifespan` não roda em serverless: cada requisição
    instancia a função e a encerra, então o `asyncio.create_task` morre antes
    dos 60s do primeiro disparo. No Render, com processo vivo, o laço bastava;
    no Vercel ninguém nunca chamaria `trigger_all_alerts`.

    Autenticação por CRON_SECRET em vez de JWT: o Cron do Vercel não faz login.
    Quando a variável CRON_SECRET existe no projeto, o Vercel envia
    `Authorization: Bearer <CRON_SECRET>` automaticamente em cada chamada.

    Falha FECHADA se a variável não estiver definida: uma rota que dispara
    envio de e-mail em massa não pode ficar aberta a quem descobrir a URL só
    porque alguém esqueceu de configurar o segredo.
    """
    segredo = (os.getenv("CRON_SECRET") or "").strip()
    if not segredo:
        logger.error("CRON_SECRET não configurada — disparo agendado recusado.")
        raise HTTPException(
            status_code=503,
            detail="CRON_SECRET não configurada no ambiente.",
        )

    enviado = (request.headers.get("authorization") or "").strip()
    esperado = f"Bearer {segredo}"
    # compare_digest evita vazar o segredo pelo tempo de resposta.
    if not secrets.compare_digest(enviado, esperado):
        logger.warning("Chamada ao cron de alertas com credencial inválida.")
        raise HTTPException(status_code=401, detail="Não autorizado.")

    try:
        stats = trigger_all_alerts()
        logger.info(f"Cron de alertas concluído: {stats}")
    except Exception:
        logger.exception("Falha no cron de alertas")
        raise HTTPException(status_code=500, detail="O cron de alertas falhou. Veja o log do servidor.")

    # Expurgo do install_log pendurado no mesmo disparo diário, e não num cron
    # próprio: os planos da Vercel limitam o número de crons, e um segundo
    # agendamento poderia simplesmente não ser criado — falha silenciosa numa
    # rotina de LGPD é o pior lugar para tê-la.
    #
    # Try/except próprio de propósito: apagar log é acessório, e não pode
    # derrubar o envio de alertas, que é o motivo de a rota existir. Se falhar,
    # aparece na resposta em vez de sumir.
    try:
        expurgo = {
            "install_log": cert_installer.expurgar_install_log(),
            "user_activity": atividade.expurgar(),
            # O cofre entra no mesmo ciclo: chave privada de certificado
            # vencido ou removido da pasta é passivo puro, e o acervo só
            # crescia porque nada a tirava.
            "cofre": cert_installer.expurgar_cofre(),
        }
    except Exception as e:  # noqa: BLE001
        logger.exception("Falha no expurgo da trilha")
        expurgo = {"executado": False, "motivo": str(e)}

    return {"ok": True, "stats": stats, "expurgo": expurgo}


# Modulo `acompanhamento` na matriz desde 20/08. TODAS as cinco rotas ficam em
# `ler`, inclusive o PUT — e a excecao merece explicacao: aquele PUT salva a
# selecao do PROPRIO chamador (`token.email`), nao dado de outra pessoa. Exigir
# `editar` ali tiraria de um operador o direito de escolher os proprios
# certificados, que e a funcao inteira da tela.
#
# O nivel aqui governa SE a pessoa alcanca o modulo; o que esta dentro e dela.
# Mesma carve-out de `/api/users/me/*`.
@app.get("/api/colaborador/notificacoes", dependencies=[Depends(require_modulo("acompanhamento"))])
def get_user_notifications(token: auth.TokenData = Depends(require_auth)) -> dict:
    try:
        # Devolve lista limitada + totais separados: antes eram 519 itens
        # (167 KB) a cada poll de 60s, com os acionáveis no fim da lista.
        return build_notifications_payload(
            token.email, token.role, _user_id_da_sessao(token)
        )
    except Exception:
        logger.exception("Falha ao montar as notificações")
        raise HTTPException(status_code=500, detail="Não foi possível carregar as notificações.")


# Enfileirar comando para o agente e acao de operacao, e a unica chamadora e
# `configuracao.html` — pagina que so admin ve. Estava sob `require_auth`, que
# aceita QUALQUER autenticado: um operador comum podia mandar o servidor
# reescanear ou mover certificados. Ver docs/PLANO_niveis_de_acesso.md §1.
@app.post("/api/agent/commands", dependencies=[Depends(require_admin)])
def enqueue_agent_command(body: EnqueueCommandBody) -> dict:
    """
    Enfileira um comando para o agente Windows (poll em GET /api/agent/next).
    Comandos: mover_vencidos, rescan, ping. Use machine_id alinhado ao agente (ou * para qualquer um).
    """
    try:
        cid = enqueue(body.machine_id.strip() or "default", body.command.strip())
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    return {"ok": True, "id": cid, "command": body.command.strip()}


@app.get("/api/agent/next")
def agent_next_command(
    machine_id: str = Query("default", description="ID da máquina do agente"),
    token: auth.TokenData = Depends(require_agent_or_admin),
) -> dict:
    """
    O agente chama isto no início de cada ciclo: retira um comando em fila ou null.

    A fila é a da máquina que a credencial prova ser (achado #3, crítico): com
    o `machine_id` vindo só da query, qualquer agente puxava — e consumia — a
    fila de qualquer outra estação, inclusive o token de instalação que ela
    esperava. A chave compartilhada não entra: sem identidade não há fila.
    """
    maquina = _machine_da_credencial(token, machine_id, exigir_identidade=True)
    q = pop_next_for_agent(maquina)
    if not q:
        return {"command": None, "id": None}
    out = {"command": q.command, "id": q.id, "machine_id": q.machine_id}
    # `payload` carrega o token de uso único de instalar_certificados. A linha
    # da fila já foi removida no pop, então o token só trafega uma vez, para o
    # agente autenticado que o solicitou.
    if q.payload:
        out["payload"] = q.payload
    return out


@app.get("/api/agent/queue", dependencies=[Depends(require_admin)])
def agent_queue_list() -> dict:
    """Lista comandos ainda pendentes (monitorização no portal)."""
    return {"pendentes": list_pending(), "comandos_validos": sorted(COMMANDS)}


# ──────────────────────────────────────────────────────────────────────────
# Dispositivos do agente — a identidade deixa de ser uma chave compartilhada
#
# As duas primeiras rotas NÃO usam `require_auth`, e é de propósito: são
# justamente as que criam a credencial. `registrar` autentica com a senha do
# portal (uma vez, na janela de login do agente) e `token` autentica com o
# segredo do dispositivo. Ver `app/agent_devices.py` para o desenho.
# ──────────────────────────────────────────────────────────────────────────


class RegistrarDispositivoBody(BaseModel):
    email: str
    password: str
    machine_id: str
    nome: Optional[str] = None


class TokenDoDispositivoBody(BaseModel):
    segredo: str
    # Reportada pela estação, não medida pelo portal. Opcional porque um agente
    # anterior a esta coluna continua trocando token normalmente — exigir aqui
    # deixaria a frota velha sem acesso no deploy, que é o oposto do objetivo.
    versao: Optional[str] = None


def _erro_sem_banco(e: agent_devices.SemBanco) -> HTTPException:
    return HTTPException(status_code=503, detail=str(e))


@app.post("/api/agent/dispositivos/registrar")
def registrar_dispositivo(body: RegistrarDispositivoBody, request: Request) -> dict:
    """
    Troca a senha do portal por um segredo de dispositivo — uma vez só.

    O agente descarta a senha aqui. É a diferença que importa: segredo vazado
    custa uma revogação; senha do portal vazada custa a conta inteira, e ela
    vale também para o navegador.

    Recusa senha provisória. Quem entrou com senha definida por outra pessoa
    ainda não provou ser quem diz — `require_auth` já barra todas as outras
    rotas nesse estado, e deixar esta passar daria ao portador da senha
    provisória uma credencial durável, que sobreviveria à troca.
    """
    ip = _ip_do_cliente(request)
    # MESMA chave do /api/login (achado #7): esta rota prova a senha do mesmo
    # jeito, e sem teto era a porta por onde o spray de senhas entrava com o
    # teto do login intacto. Chave separada daria 40 tentativas/min a quem
    # alternasse as duas rotas.
    if not taxa.permitir(f"login:{ip}", 20, 60):
        raise HTTPException(status_code=429, detail="Muitas tentativas. Aguarde um minuto.")
    # E um teto por CONTA, que trocar de IP não contorna. Só aqui, e não no
    # login do navegador: lá, dez erros em cinco minutos trancariam a conta de
    # quem está sendo atacado — aqui o registro de dispositivo é ato raro.
    email_alvo = (body.email or "").strip().lower()
    if not taxa.permitir(f"senha:{email_alvo}", 10, 300):
        raise HTTPException(status_code=429, detail="Muitas tentativas nesta conta. Aguarde alguns minutos.")

    user = _conferir_credenciais(body.email, body.password, ip)

    if bool(user.get("deve_trocar_senha")):
        raise HTTPException(
            status_code=403,
            detail="Troque a senha no portal antes de registrar o agente.",
            headers={"X-Senha-Provisoria": "1"},
        )

    machine_id = (body.machine_id or "").strip()
    if not machine_id:
        raise HTTPException(status_code=400, detail="Informe a máquina do agente.")

    try:
        segredo = agent_devices.registrar(
            user_id=str(user["id"]),
            machine_id=machine_id,
            nome=body.nome or machine_id,
        )
    except agent_devices.SemBanco as e:
        raise _erro_sem_banco(e)
    except Exception:
        logger.exception("Falha ao registrar dispositivo do agente")
        raise HTTPException(status_code=500, detail="Erro interno ao registrar o dispositivo.")

    return {
        "segredo": segredo,
        "machine_id": machine_id,
        "email": user["email"],
        "role": user["role"],
        # O agente usa isto para renovar antes de expirar, em vez de descobrir
        # pelo 401 — que chegaria no meio de uma instalação.
        "validade_token_min": agent_devices.VALIDADE_TOKEN_MIN,
    }


@app.post("/api/agent/dispositivos/token")
def token_do_dispositivo(body: TokenDoDispositivoBody) -> dict:
    """
    Segredo do dispositivo vira JWT curto.

    O JWT sai com o papel REAL da pessoa (`user`, `gestor`, `admin`), não com
    `agent`. É o ponto da fase: as rotas passam a poder perguntar "este
    certificado é seu" em vez de "que papel você tem", e a barreira de carteira
    volta a valer para quem opera o agente.

    A contrapartida, que é preciso ter em conta ao instalar o agente: **um
    dispositivo vale o que vale o dono.** O segredo guardado na estação de um
    administrador emite token de administrador. Não é regressão — a chave
    compartilhada de antes dava papel `agent` a QUALQUER máquina que a tivesse,
    e sem revogação individual —, mas troca "todo mundo tem a mesma chave" por
    "cada máquina tem o poder de quem a usa". Agente de admin merece a mesma
    cautela que a sessão de admin no navegador.
    """
    try:
        disp = agent_devices.autenticar(body.segredo, versao=body.versao)
    except agent_devices.SemBanco as e:
        raise _erro_sem_banco(e)

    if not disp:
        # Mesma resposta para segredo inexistente e revogado: distinguir diria a
        # quem tenta se aquele valor já existiu.
        raise HTTPException(status_code=401, detail="Dispositivo não autorizado.")

    sb = _sb_do_login()
    r = sb.table("users").select("*").eq("id", disp["user_id"]).limit(1).execute()
    user = r.data[0] if r.data else None
    # A conta pode ter sido desativada depois do registro. Sem esta conferência,
    # o dispositivo continuaria emitindo token para quem já perdeu o portal.
    if not user or not conta_ativa(user):
        raise HTTPException(status_code=403, detail="Conta sem acesso ao portal.")

    token = auth.create_access_token(
        {"sub": user["email"], "role": user["role"]},
        expires_delta=timedelta(minutes=agent_devices.VALIDADE_TOKEN_MIN),
    )
    return {
        "access_token": token,
        "token_type": "bearer",
        "role": user["role"],
        "machine_id": disp.get("machine_id"),
        "validade_token_min": agent_devices.VALIDADE_TOKEN_MIN,
        # O agente compara com a própria e registra no log quando está atrás.
        # Não atualiza sozinho: distribuir o instalador do agente pelo portal
        # ainda é decisão em aberto — são 33 MB que teriam de entrar no
        # repositório e no pacote da Vercel.
        "versao_esperada": config.VERSAO_AGENTE_ESPERADA,
    }


@app.get("/api/agent/dispositivos")
def listar_dispositivos(token: auth.TokenData = Depends(require_auth)) -> dict:
    """
    Os dispositivos de quem pergunta. Admin vê a frota inteira.

    Não é o módulo `instalador` que governa isto: um operador precisa ver e
    revogar as PRÓPRIAS máquinas mesmo sem permissão nenhuma no menu — é a
    conta dele que está naquela estação. Mesmo raciocínio que mantém
    `/api/users/me/export` fora da matriz.
    """
    try:
        if (token.role or "").strip().lower() == "admin":
            return {"dispositivos": agent_devices.listar(), "alcance": "todos"}
        user_id = _user_id_da_sessao(token)
        if not user_id:
            raise HTTPException(status_code=404, detail="Usuário não encontrado")
        return {"dispositivos": agent_devices.listar(user_id), "alcance": "proprios"}
    except agent_devices.SemBanco as e:
        raise _erro_sem_banco(e)


@app.delete("/api/agent/dispositivos/{device_id}")
def revogar_dispositivo(
    device_id: str, token: auth.TokenData = Depends(require_auth)
) -> dict:
    """
    Revoga o segredo. O dispositivo para de trocar por token no próximo ciclo.

    Tokens já emitidos continuam válidos até expirar — daí `VALIDADE_TOKEN_MIN`
    ser uma hora, e não as 24 h do navegador: é a janela real da revogação.
    """
    admin = (token.role or "").strip().lower() == "admin"
    dono = None if admin else _user_id_da_sessao(token)
    if not admin and not dono:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")

    try:
        ok = agent_devices.revogar(device_id, user_id=dono)
    except agent_devices.SemBanco as e:
        raise _erro_sem_banco(e)

    if not ok:
        # 404 também quando o dispositivo existe mas é de outra pessoa: um 403
        # confirmaria a existência daquele id para quem não devia saber.
        raise HTTPException(status_code=404, detail="Dispositivo não encontrado.")
    return {"status": "revogado", "id": device_id}


# ──────────────────────────────────────────────────────────────────────────
# Credencial de MÁQUINA — a identidade do SERVIÇO deixa a X-API-Key
#
# Par das rotas de dispositivos acima, para o outro objeto: ali é a PESSOA na
# estação (dormente — o serviço não alcança aquele cofre); aqui é a máquina em
# si. Ver `app/machine_credentials.py` para o desenho, e o WARNING de "legado"
# em `require_auth` para saber quando a chave compartilhada pode morrer.
# ──────────────────────────────────────────────────────────────────────────


class ProvisionarMaquinaBody(BaseModel):
    machine_id: str
    versao: Optional[str] = None


def _erro_maquina_indisponivel(e: Exception) -> HTTPException:
    logger.error("Credenciais de máquina indisponíveis: %s", e)
    return HTTPException(
        status_code=503,
        detail="As credenciais de máquina estão indisponíveis. Tente de novo em instantes.",
    )


@app.post("/api/agent/maquinas/provisionar")
def provisionar_maquina(
    body: ProvisionarMaquinaBody,
    token: auth.TokenData = Depends(require_agent_or_admin),
) -> dict:
    """
    Troca a X-API-Key pela credencial própria desta máquina — uma vez só.

    Quem prova posse aqui é a X-API-Key que já autentica o agente hoje (não há
    fluxo de aprovação: é UM consumidor conhecido, o ANALISESRV, e o seeding é
    a primeira subida do serviço). `require_agent_or_admin` e não `require_auth`
    porque a identidade anônima do modo sem API_KEY não pode emitir credencial:
    seria criar um segredo durável a partir de credencial nenhuma.

    Linha existente — até revogada — recusa com 409. Se a emissão pudesse
    reabrir uma revogação, revogar não revogaria nada para quem tem a chave
    compartilhada; o caminho de volta é um admin reemitir.
    """
    mid = (body.machine_id or "").strip()
    if not mid:
        raise HTTPException(status_code=400, detail="Informe a máquina do agente.")
    try:
        segredo = machine_credentials.provisionar(mid, versao=body.versao)
    except machine_credentials.JaProvisionada as e:
        raise HTTPException(status_code=409, detail=str(e))
    except (machine_credentials.SemBanco, machine_credentials.SemTabela) as e:
        raise _erro_maquina_indisponivel(e)
    except Exception:
        logger.exception("Falha ao provisionar credencial de máquina")
        raise HTTPException(status_code=500, detail="Erro interno ao provisionar.")

    # O segredo em claro, pela única vez. Não é logado; quem o guarda é o
    # ProgramData da estação, cifrado com DPAPI de escopo máquina.
    return {"machine_id": mid.strip().lower(), "segredo": segredo}


@app.get("/api/agent/maquinas", dependencies=[Depends(require_admin)])
def listar_maquinas() -> dict:
    """
    As máquinas com credencial própria, com `vivo` calculado.

    Também é o mapa da transição: o ANALISESRV aparecer aqui vivo — e o WARNING
    de X-API-Key sumir do log — é o sinal de que o legado pode ser desligado.
    """
    try:
        return {"maquinas": machine_credentials.listar()}
    except (machine_credentials.SemBanco, machine_credentials.SemTabela) as e:
        raise _erro_maquina_indisponivel(e)


@app.delete("/api/agent/maquinas/{machine_id}", dependencies=[Depends(require_admin)])
def revogar_maquina(machine_id: str) -> dict:
    """
    Revoga a credencial da máquina. Idempotente; a linha fica.

    A linha preservada é a própria garantia: enquanto ela existir, o
    provisionamento NÃO emite segredo novo para este machine_id — revogar
    significa "esta máquina não fala mais", não "pega outra chave na próxima
    subida". O caminho de volta é a reemissão, que é outra decisão.
    """
    try:
        ok = machine_credentials.revogar(machine_id)
    except (machine_credentials.SemBanco, machine_credentials.SemTabela) as e:
        raise _erro_maquina_indisponivel(e)
    if not ok:
        raise HTTPException(status_code=404, detail="Esta máquina não tem credencial.")
    return {"status": "revogado", "machine_id": machine_id.strip().lower()}


@app.post("/api/agent/maquinas/{machine_id}/reemitir", dependencies=[Depends(require_admin)])
def reemitir_maquina(machine_id: str) -> dict:
    """
    Descarta a credencial atual; a próxima subida do serviço emite uma NOVA.

    Para os dois becos que a linha existente cria: revogação que precisa ser
    desfeita, e emissão perdida (o serviço recebeu o segredo e não conseguiu
    guardar). Ato de admin de propósito — é exatamente a decisão que o
    provisionamento não pode tomar sozinho.
    """
    try:
        ok = machine_credentials.reemitir(machine_id)
    except (machine_credentials.SemBanco, machine_credentials.SemTabela) as e:
        raise _erro_maquina_indisponivel(e)
    if not ok:
        raise HTTPException(status_code=404, detail="Esta máquina não tem credencial.")
    return {"status": "descartada", "machine_id": machine_id.strip().lower()}


# `/api/certificados` fica FORA da matriz, de proposito. Duas razoes:
#
# 1. `scripts/diagnostico.py` a consome com X-API-Key. Liga-la faria a
#    ferramenta de diagnostico reportar "-1 itens" em silencio — quebrar o
#    termometro e pior do que a febre.
# 2. `inicio` e onde todo mundo aterrissa depois do login. Desligar esse modulo
#    para um papel deixaria a pessoa entrar e nao ver nada, sem lugar para ir.
#
# As telas de consulta especificas (historico, vencidos, duplicidades) SAO
# governadas pela matriz; so a listagem geral fica aberta a quem esta
# autenticado, como sempre esteve.
@app.get("/api/certificados", dependencies=[Depends(require_auth)])
def listar_certificados(
    fonte: str = Query(
        "auto",
        description="auto | remoto | local",
    ),
    pagina: Optional[int] = Query(None, ge=1, description="Com por_pagina, ativa paginação no servidor"),
    por_pagina: Optional[int] = Query(None, ge=1, le=2000),
    filtro_status: str = Query("todos", description="todos | validos | prestes_vencer | vencidos | erros"),
    busca: Optional[str] = Query(None, max_length=400),
    todas_filtradas: bool = Query(False, description="Exportação: todos os itens do filtro (até LISTAGEM_EXPORT_MAX)"),
    ocultar_ilegiveis: bool = Query(
        False,
        description="Exclui erro e fora_do_padrao da lista, da contagem e da exportação",
    ),
    ordenar: Optional[str] = Query(
        None,
        description="nome | status | emissao | vencimento | documento. Vazio = ordem alfabética por titular",
    ),
    direcao: str = Query("asc", description="asc | desc"),
    token: auth.TokenData = Depends(require_auth),
) -> JSONResponse:
    """
    * auto: usa o último snapshot ingerido se existir; senão leitura local.
    * remoto: só snapshot (404 se vazio).
    * local: sempre leitura no disco do servidor (pastas efetivas da config).

    Com ``pagina`` e ``por_pagina`` na query, devolve ``paginacao`` e ``resumo`` (painel).
    Sem esses parâmetros, mantém o comportamento antigo: lista completa em ``itens``.
    """
    try:
        sets = load_settings()
        snap = get_latest_snapshot()
        base = _list_certificados_payload(sets, snap, fonte)
        base["itens"] = ordenar_por_titular(base.get("itens") or [])
        # A pasta do servidor só para admin (SECURITY_AUDIT #2): o operador
        # precisa do titular e do documento, não da árvore de diretórios.
        if (token.role or "").strip().lower() != "admin":
            base["itens"] = [nome_publico.sem_pasta(it) for it in base["itens"]]
        # Recorte pela carteira ANTES de resumo, paginação e exportação (#5):
        # tudo o que sai desta rota nasce desta lista.
        base["itens"] = _recortar_pela_carteira(base["itens"], _documentos_ao_alcance(token))
        # Caixa alta vira título no servidor (app/nomes.py), num lugar só,
        # para toda tela que lista o inventário (Início, Custódia).
        for it in base["itens"]:
            it["nome_exibicao"] = nomes.nome_exibicao(it.get("nome") or it.get("display_name"))

        paged = pagina is not None and por_pagina is not None
        if not paged and not todas_filtradas:
            return JSONResponse({**base, "banco": banco_configurado()})

        now = datetime.now(timezone.utc)
        thirty = now + timedelta(days=30)
        enriched = [_enrich_cert_item_dashboard_flags(it, now, thirty) for it in (base.get("itens") or [])]
        # A exclusao entra AQUI, junto dos outros filtros, e nao depois: daqui
        # saem a listagem, o `resumo` dos cards, a contagem de paginas e a
        # exportacao. Filtrar mais tarde daria uma pagina de 100 com 91 linhas e
        # cards que nao batem com a tabela.
        #
        # `ocultar_ilegiveis` e OPT-IN. O mesmo endpoint atende o
        # `scripts/diagnostico.py`, que existe justamente para achar arquivo
        # ilegivel — mudar o padrao cegaria a ferramenta de diagnostico.
        filtered = [
            it
            for it in enriched
            if _dashboard_filtro_status_match(it, filtro_status)
            and _dashboard_busca_match(it, busca or "")
            and not (ocultar_ilegiveis and _e_ilegivel(it))
        ]
        # Antes do `resumo` e da paginacao, e pelo mesmo motivo que a ordem
        # alfabetica ja era feita aqui: ordenar no navegador ordenaria so os 25
        # itens da pagina visivel, e a lista PARECERIA certa enquanto
        # continuasse errada entre paginas.
        #
        # Sem `ordenar`, nada muda: a lista ja chega ordenada por titular de
        # `_list_certificados_payload`, e essa continua sendo a ordem de fabrica.
        if ordenar:
            filtered = _ordenar_listagem(filtered, ordenar, direcao)

        resumo = _dashboard_resumo_counts(filtered)

        if todas_filtradas:
            lista_truncada = len(filtered) > LISTAGEM_EXPORT_MAX
            return JSONResponse(
                {
                    **base,
                    "itens": filtered[:LISTAGEM_EXPORT_MAX],
                    "resumo": resumo,
                    "lista_truncada": lista_truncada,
                    "banco": banco_configurado(),
                }
            )

        pp = int(por_pagina or 20)
        total = len(filtered)
        total_pags = max(1, (total + pp - 1) // pp) if total else 1
        pagina_in = min(max(1, int(pagina or 1)), total_pags)
        off = (pagina_in - 1) * pp
        page_items = filtered[off : off + pp]
        return JSONResponse(
            {
                **base,
                "itens": page_items,
                "resumo": resumo,
                "paginacao": {
                    "pagina": pagina_in,
                    "total_paginas": total_pags,
                    "total_itens": total,
                    "por_pagina": pp,
                    # Permite ao portal avisar sobre truncamento ANTES de exportar,
                    # em vez de só depois que o arquivo já foi gerado.
                    "export_max": LISTAGEM_EXPORT_MAX,
                },
                "banco": banco_configurado(),
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Erro em GET /api/certificados (fonte=%s)", fonte)
        raise HTTPException(
            status_code=500,
            detail="Falha ao listar certificados. Veja o log do servidor.",
        ) from e


def _escape_ilike_pattern(val: str) -> str:
    """Evita que % e _ do usuário interfiram com ILIKE."""
    return val.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _parse_iso_utc(iso_value: Optional[str]) -> datetime:
    if not iso_value:
        return datetime.min.replace(tzinfo=timezone.utc)
    s = str(iso_value).strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)


def _normalize_ingest_items_status(items: List[dict], now: datetime) -> List[dict]:
    """
    Alinha gravacao com o criterio do painel: se not_after ja passou (UTC),
    marca status como expirado mesmo quando o agente enviou ok (ex.: relogio local desfasado).
    Nao altera erro, fora_do_padrao nem itens sem not_after valido.
    """
    min_dt = datetime.min.replace(tzinfo=timezone.utc)
    out: List[dict] = []
    for raw in items:
        it = dict(raw)
        s = str(it.get("status") or "").strip().lower()
        if s == CertStatus.OK.value:
            na = it.get("not_after")
            if na:
                exp = _parse_iso_utc(str(na))
                if exp > min_dt and exp < now:
                    it["status"] = CertStatus.EXPIRED.value
        out.append(it)
    return out


def _digits_only_doc(value: Any) -> str:
    return re.sub(r"\D", "", str(value or ""))


def _normalize_name_dup(value: Any) -> str:
    t = str(value or "").strip().lower()
    t = unicodedata.normalize("NFD", t)
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return " ".join(t.split())


def _fingerprint_hex_from_row(row: dict) -> str:
    """SHA-256 (hex) do fingerprint do certificado; aceita chave antiga `cert_sha256` nos snapshots."""
    v = row.get("fingerprint_sha256") or row.get("cert_sha256")
    if v is None or not str(v).strip():
        return ""
    return str(v).strip().lower()


def _item_resumo_duplicidade(it: dict, incluir_pasta: bool = False) -> dict[str, Any]:
    fp = it.get("fingerprint_sha256") or it.get("cert_sha256")
    nome = it.get("nome") or it.get("display_name")
    out = {
        # O nome PÚBLICO do arquivo (SECURITY_AUDIT #2): o nome bruto carrega
        # a senha, e esta tela o mostrava copiável. A pasta só vai para admin
        # — é estrutura do servidor, e é ele quem vai lá apagar a cópia.
        "nome_publico": it.get("nome_publico"),
        "nome": nome,
        # Caixa alta vira título no servidor (app/nomes.py), como no Início e
        # no Vencidos; números e códigos do nome passam intactos.
        "nome_exibicao": nomes.nome_exibicao(nome),
        "documento": it.get("documento_formatado") or it.get("documento_numero"),
        "documento_numero": it.get("documento_numero"),
        "not_after": it.get("not_after"),
        "not_before": it.get("not_before"),
        "status": it.get("status"),
        "subject": it.get("subject"),
        "issuer": it.get("issuer"),
        "serial_number": it.get("serial_number"),
        "fingerprint_sha256": fp,
    }
    if incluir_pasta:
        out["pasta"] = it.get("pasta")
    return out


def _fingerprint_hex_resumo(m: dict) -> str:
    v = m.get("fingerprint_sha256")
    if v is None or not str(v).strip():
        return ""
    return str(v).strip().lower()


def _filtrar_grupo_documento_apos_fingerprint(members: List[dict]) -> List[dict]:
    """
    Remove da lista «mesmo documento» os arquivos que já entram no agrupamento
    por fingerprint (2+ com o mesmo SHA-256). A duplicidade criptográfica é a
    validação definitiva; o grupo por documento fica para CPF/CNPJ igual sem
    fingerprint ou com certificados distintos (ex.: renovação).
    """
    by_fp: dict[str, List[dict]] = defaultdict(list)
    sem_fp: List[dict] = []
    for m in members:
        fp = _fingerprint_hex_resumo(m)
        if not fp:
            sem_fp.append(m)
        else:
            by_fp[fp].append(m)
    kept: List[dict] = []
    kept.extend(sem_fp)
    for _fp, grupo in by_fp.items():
        if len(grupo) < 2:
            kept.extend(grupo)
    return kept


def _agrupar_duplicidades(
    rows: List[dict],
    incluir_pasta: bool = False,
) -> Tuple[List[dict], List[dict], List[dict]]:
    """
    Deteta duplicidades no mesmo inventário (último snapshot ou scan local):
    - mesmo CNPJ/CPF (11+ dígitos) em mais de um arquivo (exceto quando a duplicidade
      já é explicada só por fingerprint — aí fica só em certificados idênticos);
    - certificados idênticos: mesmo fingerprint (SHA-256 do DER) em mais de um arquivo;
    - nomes muito semelhantes (SequenceMatcher) só quando não existe fingerprint
      no inventário (export antigo do agente ou leitura falhou).
    """
    by_doc: dict[str, List[dict]] = defaultdict(list)
    for it in rows:
        d = _digits_only_doc(it.get("documento_numero") or it.get("documento_formatado"))
        if len(d) >= 11:
            by_doc[d].append(_item_resumo_duplicidade(it, incluir_pasta))

    grupos_documento: List[dict] = []
    for doc_digits, members in by_doc.items():
        if len(members) < 2:
            continue
        filtrados = _filtrar_grupo_documento_apos_fingerprint(members)
        if len(filtrados) < 2:
            continue
        exib = next((m.get("documento") for m in filtrados if m.get("documento")), doc_digits)
        grupos_documento.append(
            {
                "tipo": "documento",
                "documento_digitos": doc_digits,
                "documento_exibicao": exib,
                "itens": filtrados,
            }
        )

    by_fp: dict[str, List[dict]] = defaultdict(list)
    for it in rows:
        fp = _fingerprint_hex_from_row(it)
        if not fp:
            continue
        by_fp[fp].append(_item_resumo_duplicidade(it, incluir_pasta))

    grupos_cert_igual: List[dict] = []
    for fp_hex, members in by_fp.items():
        if len(members) < 2:
            continue
        grupos_cert_igual.append(
            {
                "tipo": "certificado_igual",
                "fingerprint_sha256": fp_hex,
                "itens": members,
            }
        )

    n = len(rows)
    parent = list(range(n))

    def find(a: int) -> int:
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for i in range(n):
        for j in range(i + 1, n):
            if _fingerprint_hex_from_row(rows[i]) or _fingerprint_hex_from_row(rows[j]):
                continue
            fi = str(rows[i].get("nome_publico") or "").strip().lower()
            fj = str(rows[j].get("nome_publico") or "").strip().lower()
            if not fi or fi == fj:
                continue
            di = _digits_only_doc(
                rows[i].get("documento_numero") or rows[i].get("documento_formatado")
            )
            dj = _digits_only_doc(
                rows[j].get("documento_numero") or rows[j].get("documento_formatado")
            )
            if len(di) >= 11 and len(dj) >= 11 and di == dj:
                continue
            ni = _normalize_name_dup(
                rows[i].get("nome") or rows[i].get("display_name") or rows[i].get("nome_publico")
            )
            nj = _normalize_name_dup(
                rows[j].get("nome") or rows[j].get("display_name") or rows[j].get("nome_publico")
            )
            if len(ni) < 5 or len(nj) < 5:
                continue
            if SequenceMatcher(None, ni, nj).ratio() >= 0.86:
                union(i, j)

    roots: dict[int, List[int]] = defaultdict(list)
    for i in range(n):
        roots[find(i)].append(i)

    grupos_nome: List[dict] = []
    for _root, idxs in roots.items():
        if len(idxs) < 2:
            continue
        members = [_item_resumo_duplicidade(rows[k], incluir_pasta) for k in idxs]
        nomes_cur = [
            _normalize_name_dup(
                rows[k].get("nome") or rows[k].get("display_name") or rows[k].get("nome_publico")
            )
            for k in idxs
        ]
        rotulo = max(nomes_cur, key=len) if nomes_cur else "—"
        grupos_nome.append({"tipo": "nome_similar", "rotulo": rotulo[:120], "itens": members})

    return grupos_documento, grupos_nome, grupos_cert_igual


def _doc_norm(v: Any) -> str:
    return re.sub(r"\D+", "", str(v or ""))


def _parse_dt_or_min(v: Any) -> datetime:
    return _parse_iso_utc(str(v or ""))


def _status_prioridade(status: str) -> int:
    s = str(status or "").lower()
    if s in ("ok", "valido", "válido"):
        return 3
    if s in ("expirado", "vencido"):
        return 2
    if s in ("erro",):
        return 1
    return 0


def _documentos_ao_alcance(token: auth.TokenData) -> Optional[Set[str]]:
    """O que esta sessão pode LER, em documentos. `None` = tudo.

    Um ponto só para todas as leituras do acervo (achados #5, #32): antes o
    portal impedia INSTALAR fora da carteira e deixava LER a base inteira de
    clientes. Sem banco configurado (modo local de arquivos) não há
    diretório de usuários nem carteira — e nem login que emita sessão — então
    não há por onde recortar; a leitura segue como sempre seguiu.
    """
    from app.settings_state import _banco

    papel = (token.role or "").strip().lower()
    if papel in cert_installer.PAPEIS_COM_ALCANCE_TOTAL or papel == "agent":
        return None
    if not _banco():
        return None
    try:
        return cert_installer.documentos_ao_alcance(_user_id_da_sessao(token) or "", papel)
    except (cert_installer.CarteiraIndisponivel, cert_installer.AlcanceIndisponivel) as e:
        logger.warning("Alcance de leitura indisponível para %s: %s", token.email, e)
        raise HTTPException(status_code=503, detail="Não foi possível verificar sua carteira. Tente de novo.")


def _recortar_pela_carteira(itens: List[dict], alcance: Optional[Set[str]]) -> List[dict]:
    """Só os itens cujo documento está no alcance. Item sem documento não é
    de ninguém e fica de fora para quem não tem alcance total."""
    if alcance is None:
        return itens
    saida = []
    for it in itens:
        doc = cert_installer.so_digitos(it.get("documento_numero") or it.get("documento_digitos") or it.get("documento"))
        if doc and doc in alcance:
            saida.append(it)
    return saida


def _lista_base_docs_historico() -> List[dict]:
    """Um item por DOCUMENTO, escolhendo o certificado que responde a pergunta
    "este cliente esta coberto?".

    Le o INVENTARIO, e nao `cert_history`. A troca corrigiu um defeito que so
    aparecia em cliente que renovou o certificado:

    `cert_history` faz upsert por `arquivo_chave` (nome publico + fingerprint), e o fluxo normal do escritorio
    produz DOIS arquivos com o mesmo nome — o novo na pasta de trabalho e o
    antigo movido para `99.CERTIFICADOS VENCIDOS`. Os dois colidiam numa linha
    so, e sobrava o ultimo processado. Em 22/08 eram 7 nomes repetidos, 5 deles
    com um valido e um vencido: para esses cinco clientes o Acompanhamento
    mostrava VENCIDO existindo certificado valido — e o dano e concreto, porque
    sugere renovar o que acabou de ser renovado.

    A regra de prioridade abaixo ja existia e ja estava certa. Ela nunca chegava
    a ser aplicada porque o valido nao estava na base.
    """
    sets = load_settings()
    snap = get_latest_snapshot()
    payload = _list_certificados_payload(sets, snap, "auto")
    now = datetime.now(timezone.utc)

    grupos: Dict[str, dict] = {}
    for it in (payload.get("itens") or []):
        doc = _doc_norm(it.get("documento_formatado") or it.get("documento_numero"))
        if not doc:
            continue
        venc = it.get("not_after")
        cand = {
            "documento": it.get("documento_formatado") or it.get("documento_numero") or doc,
            "documento_digitos": doc,
            "nome": it.get("nome") or it.get("display_name") or "—",
            "status_ultimo": str(it.get("status") or "").lower(),
            "vencimento_certificado": venc,
            "ultima_data_registrada": venc,
        }
        atual = grupos.get(doc)
        if not atual:
            grupos[doc] = cand
            continue

        pa = _status_prioridade(atual.get("status_ultimo", ""))
        pc = _status_prioridade(cand.get("status_ultimo", ""))
        if pc > pa:
            grupos[doc] = cand
            continue
        if pc == pa:
            # Empate: vence o de validade MAIS DISTANTE.
            #
            # Entre dois validos, e o que diz ate quando o cliente esta coberto.
            # Entre dois vencidos, e o que venceu por ultimo — o mais proximo de
            # ainda valer, e o que a pessoa reconhece.
            da = _parse_dt_or_min(atual.get("vencimento_certificado"))
            dc = _parse_dt_or_min(cand.get("vencimento_certificado"))
            if dc > da:
                grupos[doc] = cand
    return sorted(grupos.values(), key=lambda x: (x.get("nome") or "").lower())


def _painel_docs_selecionados(doc_ids: List[str]) -> List[dict]:
    base = _lista_base_docs_historico()
    by_doc = {str(it.get("documento_digitos")): it for it in base}
    now = datetime.now(timezone.utc)
    out: List[dict] = []
    for d in doc_ids:
        it = by_doc.get(d)
        if not it:
            out.append(
                {
                    "documento_digitos": d,
                    "documento": d,
                    "nome": "Não encontrado no inventário atual",
                    "status": "nao_encontrado",
                    "vencimento_certificado": None,
                    "dias_restantes": None,
                }
            )
            continue
        v_iso = it.get("vencimento_certificado")
        v_dt = _parse_iso_utc(v_iso) if v_iso else datetime.min.replace(tzinfo=timezone.utc)
        dias = (v_dt.date() - now.date()).days if v_iso else None
        
        status_ult = str(it.get("status_ultimo") or "").lower()
        if status_ult == "expirado" or (v_iso and v_dt < now):
            status = "vencido"
        elif status_ult == "erro":
            status = "erro"
        elif status_ult == "fora_do_padrao":
            status = "fora_do_padrao"
        elif v_iso and dias is not None and 0 <= dias <= 30:
            status = "expirando"
        else:
            status = "ativo"

        out.append(
            {
                "documento_digitos": d,
                "documento": it.get("documento") or d,
                "nome": it.get("nome") or "—",
                "status": status,
                "vencimento_certificado": v_iso,
                "dias_restantes": dias,
            }
        )
    out.sort(
        key=lambda x: (
            0 if x.get("status") == "vencido" else 1,
            x.get("dias_restantes") if x.get("dias_restantes") is not None else 10**9,
        )
    )
    return out


class ColaboradorSelecaoBody(BaseModel):
    documentos: List[str] = Field(default_factory=list)


@app.get("/api/colaborador/certificados/opcoes", dependencies=[Depends(require_modulo("acompanhamento"))])
def colaborador_opcoes_certificados(token: auth.TokenData = Depends(require_auth)) -> dict:
    # O universo de clientes ia para todo mundo com `acompanhamento: ler`
    # (padrão de user e gestor) — o mesmo furo do #5 por outro caminho.
    itens = _recortar_pela_carteira(_lista_base_docs_historico(), _documentos_ao_alcance(token))
    now = datetime.now(timezone.utc)
    out = []
    for it in itens:
        v_iso = it.get("vencimento_certificado")
        v_dt = _parse_iso_utc(v_iso) if v_iso else datetime.min.replace(tzinfo=timezone.utc)
        dias = (v_dt.date() - now.date()).days if v_iso else None
        
        status_ult = str(it.get("status_ultimo") or "").lower()
        if status_ult == "expirado" or (v_iso and v_dt < now):
            status = "vencido"
        elif status_ult == "erro":
            status = "erro"
        elif status_ult == "fora_do_padrao":
            status = "fora_do_padrao"
        elif v_iso and dias is not None and 0 <= dias <= 30:
            status = "expirando"
        else:
            status = "ativo"
            
        out.append({
            **it,
            "status": status
        })
    return {"itens": out, "total": len(out)}


@app.get("/api/colaborador/certificados/selecionados", dependencies=[Depends(require_modulo("acompanhamento"))])
def colaborador_get_selecionados(token: auth.TokenData = Depends(require_auth)) -> dict:
    email = (token.email or "").strip().lower()
    docs = load_colaborador_selecao(email, _user_id_da_sessao(token))
    return {"documentos": docs, "total": len(docs)}


@app.put("/api/colaborador/certificados/selecionados", dependencies=[Depends(require_modulo("acompanhamento", permissoes.NIVEL_EDITAR))])
def colaborador_put_selecionados(
    body: ColaboradorSelecaoBody, token: auth.TokenData = Depends(require_auth)
) -> dict:
    email = (token.email or "").strip().lower()
    docs = sorted({_doc_norm(x) for x in body.documentos if _doc_norm(x)})
    save_colaborador_selecao(email, docs, _user_id_da_sessao(token))
    return {"ok": True, "documentos": docs, "total": len(docs)}


@app.get("/api/colaborador/certificados/painel", dependencies=[Depends(require_modulo("acompanhamento"))])
def colaborador_painel_certificados(token: auth.TokenData = Depends(require_auth)) -> dict:
    email = (token.email or "").strip().lower()
    docs = load_colaborador_selecao(email, _user_id_da_sessao(token))
    itens = _painel_docs_selecionados(docs)
    from app import texto as _texto
    for it in itens:
        it["nome_exibicao"] = nomes.nome_exibicao(it.get("nome"))
        d = it.get("dias_restantes")
        # "em 114 dias" / "hoje" / "há 3 dias": a coluna de número solto sai.
        if d is None:
            it["dias_texto"] = ""
        elif d == 0:
            it["dias_texto"] = "vence hoje"
        elif d < 0:
            it["dias_texto"] = "há " + _texto.plural(-d, "dia")
        else:
            it["dias_texto"] = "em " + _texto.plural(d, "dia")
    total = len(itens)
    return {
        "itens": itens,
        "total": total,
        # Com poucos itens a lista inteira cabe na tela e a busca é ruído.
        "mostrar_busca": total > 10,
        "textos": {
            "total": _texto.plural(total, "certificado acompanhado", "certificados acompanhados"),
        },
    }


@app.post(
    "/api/colaborador/notificacoes/lidas",
    dependencies=[Depends(require_modulo("acompanhamento"))],
)
def marcar_notificacoes_como_lidas(token: auth.TokenData = Depends(require_auth)) -> dict:
    """"Li todos": esconde os avisos que estão no sino AGORA.

    O servidor decide o que marcar, e não a tela. Se a lista viesse do cliente,
    um aviso que apareceu entre o carregamento do dropdown e o clique seria
    marcado como lido sem nunca ter sido visto — e some sem deixar rastro.

    `require_modulo("acompanhamento")` no nível de leitura: marcar como lido é
    uma preferência de exibição de quem está lendo, não uma edição de dado do
    portal. Exigir `editar` tiraria o botão de quem só consulta, que é
    justamente quem mais acumula aviso.
    """
    uid = _user_id_da_sessao(token)
    # `get_active_alerts` e não o payload: o payload corta em 50 itens para o
    # dropdown, e marcar só os 50 deixaria o badge aceso depois de "li todos" —
    # o botão pareceria não ter funcionado. O badge conta o acionável inteiro,
    # então é o acionável inteiro que precisa ser marcado.
    alertas = get_active_alerts(token.email or "", token.role or "", uid)
    chaves = [a.get("chave") for a in alertas if a.get("chave") and a.get("acionavel")]
    try:
        marcadas = marcar_notificacoes_lidas(uid, chaves)
    except GravacaoNaoPersistida as e:
        logger.error("Notificações lidas não persistidas: %s", e)
        raise HTTPException(
            status_code=503,
            detail="Não foi possível marcar como lido. Veja o log do servidor.",
        )
    return {"marcadas": marcadas}


class PreferenciaAlertaBody(BaseModel):
    notificar_email: bool = Field(default=True)
    # Marcos que a pessoa DISPENSA. Ver a migration 20260820200000 para o
    # porquê de guardar as recusas em vez das aceitações.
    marcos_ignorados: str = Field(default="")


@app.get(
    "/api/colaborador/alertas/preferencia",
    dependencies=[Depends(require_modulo("acompanhamento"))],
)
def obter_preferencia_alerta(token: auth.TokenData = Depends(require_auth)) -> dict:
    """A preferência da pessoa, mais os marcos que o portal realmente dispara.

    Os dois juntos numa resposta só: a tela monta uma caixa por marco DO
    PORTAL, e não uma lista fixa. Marco que o administrador acrescentar aparece
    para todo mundo, ligado — porque o que se guarda é a recusa.
    """
    pref = load_preferencia_alerta(_user_id_da_sessao(token))
    s = load_settings()
    marcos = alertas_config.marcos_efetivos(s.alertas_marcos)
    ignorados = set(alertas_config.marcos_ignorados(pref["alerta_marcos_ignorados"] or ""))
    efetivos = [m for m in marcos if m not in ignorados]
    # Frase pronta para a tela ("60, 30, 15 e 7 dias antes e no dia do
    # vencimento"): os prazos por extenso, não "4 prazos".
    if efetivos:
        lista = [str(m) for m in efetivos]
        antes = (", ".join(lista[:-1]) + " e " + lista[-1]) if len(lista) > 1 else lista[0]
        frase = antes + (" dia antes" if len(lista) == 1 and efetivos[0] == 1 else " dias antes") + " e no dia do vencimento"
    else:
        frase = "só no dia do vencimento"
    return {
        "notificar_email": pref["notificar_email"],
        "marcos_ignorados": pref["alerta_marcos_ignorados"],
        "marcos_do_portal": list(marcos),
        "marcos_efetivos": efetivos,
        "destinatario": (token.email or "").strip().lower(),
        "texto": frase,
        # Sem SMTP configurado, nenhuma preferência muda nada — e a tela
        # precisa dizer isso em vez de prometer e-mails que não saem.
        "envio_ativo": bool(s.smtp_alerts_enabled and s.smtp_host),
    }


@app.put(
    "/api/colaborador/alertas/preferencia",
    dependencies=[Depends(require_modulo("acompanhamento", permissoes.NIVEL_EDITAR))],
)
def salvar_preferencia_alerta(
    body: PreferenciaAlertaBody, token: auth.TokenData = Depends(require_auth)
) -> dict:
    try:
        ignorados = alertas_config.formatar_marcos(
            alertas_config.parse_marcos(body.marcos_ignorados)
        )
    except alertas_config.ConfiguracaoInvalida as e:
        raise HTTPException(status_code=422, detail=str(e))

    try:
        save_preferencia_alerta(
            _user_id_da_sessao(token), body.notificar_email, ignorados
        )
    except GravacaoNaoPersistida as e:
        logger.error("Preferência de alerta não persistida: %s", e)
        raise HTTPException(
            status_code=503,
            detail="Não foi possível gravar a preferência. Veja o log do servidor.",
        )
    return obter_preferencia_alerta(token)


@app.get("/api/certificados/duplicidades", dependencies=[Depends(require_modulo("duplicidades"))])
def certificados_duplicidades(token: auth.TokenData = Depends(require_auth)) -> dict[str, Any]:
    """
    Analisa o último snapshot recebido (dados atuais do agente) ou, na ausência,
    o scan local no servidor, e devolve grupos de possíveis duplicados.

    Os itens saem com o nome PÚBLICO do arquivo; a pasta só para admin
    (SECURITY_AUDIT #2). Sanitizado na saída porque um snapshot anterior à
    migração do lote 3 ainda carrega o nome com a senha.
    """
    snap = get_latest_snapshot()
    origem = "ultimo_snapshot"
    scanned_at: Optional[str] = None
    if snap and (snap.get("items") or []):
        raw_items: List[dict] = list(snap.get("items") or [])
        scanned_at = str(snap.get("scanned_at") or "") or None
    else:
        sets = load_settings()
        raw_items = [cert_to_public_dict(c) for c in scan_folder(sets.effective_source())]
        origem = "scan_local_servidor"
        scanned_at = datetime.now(timezone.utc).isoformat()

    itens = [nome_publico.sanitizar_item(it) for it in raw_items]
    rows = [it for it in itens if str(it.get("nome_publico") or "").strip()]
    admin = (token.role or "").strip().lower() == "admin"
    gd, gn, gci = _agrupar_duplicidades(rows, incluir_pasta=admin)
    return {
        "origem_dados": origem,
        "scanned_at": scanned_at,
        "total_itens_analisados": len(rows),
        "grupos_documento": gd,
        "grupos_nome_similar": gn,
        "grupos_certificado_igual": gci,
        "total_grupos_documento": len(gd),
        "total_grupos_nome_similar": len(gn),
        "total_grupos_certificado_igual": len(gci),
    }


def _historico_merge_snapshot_into_agregados(snap: dict[str, Any], agregados: Dict[str, dict]) -> None:
    """Acumula itens de um snapshot no mapa por `arquivo_chave` (mantém linha do scan mais recente).

    O item é sanitizado antes: snapshots anteriores à migração do lote 3 ainda
    trazem o nome do arquivo com a senha, e este agregado vai para a API."""
    scanned_at = snap.get("scanned_at") or datetime.now(timezone.utc).isoformat()
    scanned_dt = _parse_iso_utc(scanned_at)
    for bruto in (snap.get("items") or []):
        it = nome_publico.sanitizar_item(bruto)
        nome_pub = str(it.get("nome_publico") or "").strip()
        if not nome_pub:
            continue
        key = it["arquivo_chave"]
        atual = agregados.get(key)
        if (not atual) or (scanned_dt > atual["_dt"]):
            doc_raw = (
                it.get("documento_formatado") or it.get("documento_numero") or it.get("documento")
            )
            agregados[key] = {
                "_dt": scanned_dt,
                "nome_publico": nome_pub,
                "nome": it.get("nome") or it.get("display_name") or nome_pub,
                "status_ultimo": it.get("status"),
                "documento": doc_raw,
                "vencimento_certificado": it.get("not_after"),
                "ultima_data_registrada": scanned_dt.isoformat(),
            }


def _historico_carregar_agregados(limite_snapshots: int) -> Tuple[Dict[str, dict], int]:
    """
    Percorre snapshots (banco em lotes ou arquivo local) e devolve agregação por arquivo_chave.
    Resultado pode vir de cache em RAM (TTL configurável) por (banco ativo, limite).
    """
    from app.settings_state import _banco

    sb = _banco()
    uses_sb = sb is not None

    def _build() -> Tuple[Dict[str, dict], int]:
        agregados: Dict[str, dict] = {}
        snapshots_lidos = 0
        if sb:
            try:
                page_size = 50
                offset = 0
                while snapshots_lidos < limite_snapshots:
                    chunk = min(page_size, limite_snapshots - snapshots_lidos)
                    end = offset + chunk - 1
                    r = (
                        sb.table("cert_snapshots")
                        .select("scanned_at, items")
                        .order("scanned_at", desc=True)
                        .range(offset, end)
                        .execute()
                    )
                    rows = r.data or []
                    if not rows:
                        break
                    for snap in rows:
                        _historico_merge_snapshot_into_agregados(snap, agregados)
                    snapshots_lidos += len(rows)
                    offset += len(rows)
                    if len(rows) < chunk:
                        break
            except Exception as e:  # noqa: BLE001
                logger.exception("Falha ao ler histórico no banco")
                raise HTTPException(status_code=500, detail="Falha ao ler o histórico. Veja o log do servidor.") from e
        else:
            snap = get_latest_snapshot()
            if snap:
                _historico_merge_snapshot_into_agregados(snap, agregados)
                snapshots_lidos = 1
        return agregados, snapshots_lidos

    return _historico_cache_get_or_build(uses_sb, limite_snapshots, _build)


def _historico_itens_visualizacao(agregados: Dict[str, dict]) -> List[dict]:
    linhas = sorted(agregados.values(), key=lambda x: x["_dt"], reverse=True)
    return [{k: v for k, v in row.items() if k != "_dt"} for row in linhas]


def _historico_filtrar_busca(itens: List[dict], busca_raw: str) -> List[dict]:
    q = str(busca_raw or "").strip().lower()
    if not q:
        return itens
    out: List[dict] = []
    for it in itens:
        haystack = (
            f"{it.get('nome_publico') or ''} {it.get('nome') or ''} {it.get('documento') or ''} "
            f"{it.get('ultima_data_registrada') or ''} {it.get('vencimento_certificado') or ''}"
        ).lower()
        if q in haystack:
            out.append(it)
    return out


_RE_DATA = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _data_da_query(valor: Optional[str], nome: str, sufixo: str) -> Optional[datetime]:
    """YYYY-MM-DD de verdade, ou 422. Vazio é "sem filtro"."""
    if not valor:
        return None
    v = valor.strip()
    if not _RE_DATA.match(v):
        raise HTTPException(status_code=422, detail=f"{nome} precisa estar no formato AAAA-MM-DD.")
    try:
        datetime.strptime(v, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=422, detail=f"{nome} não é uma data válida.")
    return _parse_iso_utc(v + sufixo)


def _vencidos_filtrar_busca(rows: List[dict], busca_raw: str) -> List[dict]:
    if not str(busca_raw or "").strip():
        return rows
    raw = str(busca_raw).strip()
    bt = _painel_busca_normalizada(raw)
    bd = re.sub(r"\D", "", raw)
    out: List[dict] = []
    for it in rows:
        nome = _painel_busca_normalizada(it.get("nome") or "")
        doc_txt = _painel_busca_normalizada(it.get("documento") or "")
        doc_d = _digits_only_doc(it.get("documento") or "")
        venc_txt = _painel_busca_normalizada(it.get("vencimento_certificado") or "")
        vn = _digits_only_doc(str(it.get("vencimento_certificado") or ""))
        if bt and bt in nome:
            out.append(it)
            continue
        if bt and bt in doc_txt:
            out.append(it)
            continue
        if bt and bt in venc_txt:
            out.append(it)
            continue
        if bd and bd in doc_d:
            out.append(it)
            continue
        if bd and bd in vn:
            out.append(it)
            continue
    return out


def _cert_history_fetch_all(sb: Any) -> List[dict[str, Any]]:
    """Lê todas as linhas de cert_history (PostgREST limita ~1000 por pedido sem range)."""
    cols = (
        "nome_publico, nome, documento, status_ultimo, "
        "vencimento_certificado, ultima_data_registrada"
    )
    batch = 1000
    out: List[dict[str, Any]] = []
    offset = 0
    while True:
        r = (
            sb.table("cert_history")
            .select(cols)
            .order("ultima_data_registrada", desc=True)
            .range(offset, offset + batch - 1)
            .execute()
        )
        chunk = r.data or []
        out.extend(chunk)
        if len(chunk) < batch:
            break
        offset += batch
    return out


def historico_certificados(
    limite_snapshots: int = 500,
    *,
    offset: Optional[int] = None,
    limit: Optional[int] = None,
    busca: Optional[str] = None,
) -> dict:
    """
    Lista certificados já mapeados em algum momento, com a última data registrada.
    Com ``limit`` definido, lê só uma página de ``cert_history`` (menos carga).

    Chamadas internas devem omitir ``limit`` para obter a lista completa.
    """
    from app.settings_state import _banco

    pagination = limit is not None
    offset = max(0, int(offset or 0))
    page_limit = int(limit) if pagination else None
    busca_txt = str(busca).strip() if busca else ""

    def _normalize_rows(rows_raw: List[dict[str, Any]]) -> List[dict[str, Any]]:
        return [
            {
                "nome_publico":           row.get("nome_publico"),
                "nome":                   row.get("nome"),
                "documento":              row.get("documento"),
                "status_ultimo":          row.get("status_ultimo"),
                "vencimento_certificado": row.get("vencimento_certificado"),
                "ultima_data_registrada": row.get("ultima_data_registrada"),
            }
            for row in rows_raw
        ]

    def _apply_cert_history_or_busca(qb: Any) -> Any:
        if not busca_txt:
            return qb
        pat = "%" + _escape_ilike_pattern(busca_txt) + "%"
        filt = f"nome.ilike.{pat},nome_publico.ilike.{pat},documento.ilike.{pat}"
        return qb.or_(filt)

    sb = _banco()
    if sb:
        _use_history_table = True
        rows_non_paginated: List[dict[str, Any]] = []
        try:
            if pagination and page_limit is not None:
                qc = _apply_cert_history_or_busca(
                    sb.table("cert_history").select("arquivo_chave", count="exact", head=True)
                )
                c_r = qc.execute()
                total_count = c_r.count if c_r.count is not None else 0

                if total_count > 0 or busca_txt:
                    qp = _apply_cert_history_or_busca(
                        sb.table("cert_history")
                        .select(
                            "nome_publico, nome, documento, status_ultimo, "
                            "vencimento_certificado, ultima_data_registrada",
                        )
                        .order("ultima_data_registrada", desc=True)
                    )
                    hi = offset + page_limit - 1
                    p_r = qp.range(offset, hi).execute()
                    return {
                        "itens": _normalize_rows(p_r.data or []),
                        "total": total_count,
                        "offset": offset,
                        "limit": page_limit,
                        "snapshots_lidos": 0,
                        "fonte": "cert_history",
                    }

                # total_count == 0 e sem texto de busca → tentar snapshots (dados legados)
            else:
                rows_non_paginated = _cert_history_fetch_all(sb)
        except Exception as e:  # noqa: BLE001
            err_str = str(e)
            if db_pg.tabela_ausente(e) or "PGRST205" in err_str or "cert_history" in err_str:
                logger.warning(
                    "Tabela cert_history não encontrada; usando fallback de snapshots. "
                    "Aplique supabase/migrations/20260504_cert_history.sql no banco."
                )
                _use_history_table = False
                rows_non_paginated = []
            else:
                logger.exception("Falha inesperada ao ler cert_history no banco")
                raise HTTPException(status_code=500, detail="Falha ao ler o histórico. Veja o log do servidor.") from e

        if _use_history_table and rows_non_paginated and not pagination:
            # A busca vale também aqui (achado #54): este é o caminho da
            # exportação, e ele lia a tabela inteira ignorando o filtro.
            itens = _historico_filtrar_busca(_normalize_rows(rows_non_paginated), busca_txt)
            return {
                "itens": itens,
                "total": len(itens),
                "offset": 0,
                "limit": len(itens),
                "snapshots_lidos": 0,
                "fonte": "cert_history",
            }

    agregados, snapshots_lidos = _historico_carregar_agregados(limite_snapshots)
    itens = _historico_itens_visualizacao(agregados)
    itens = _historico_filtrar_busca(itens, busca_txt)

    if pagination and page_limit is not None:
        total_f = len(itens)
        fatia = itens[offset : offset + page_limit]
        return {
            "itens": fatia,
            "total": total_f,
            "offset": offset,
            "limit": page_limit,
            "snapshots_lidos": snapshots_lidos,
            "fonte": "snapshots",
        }

    return {
        "itens": itens,
        "total": len(itens),
        "offset": 0,
        "limit": len(itens),
        "snapshots_lidos": snapshots_lidos,
        "fonte": "snapshots",
    }


@app.get("/api/certificados/historico", dependencies=[Depends(require_modulo("historico"))])
def historico_certificados_http(
    limite_snapshots: int = Query(
        500,
        ge=1,
        le=2000,
        description="Máximo de snapshots no fallback (quando cert_history está vazio)",
    ),
    pagina: int = Query(1, ge=1, description="Página (1-based)"),
    por_pagina: int = Query(20, ge=1, le=2000, description="Registros por página"),
    todas_filtradas: bool = Query(
        False,
        description="Quando true, devolve toda a lista filtrada (exportação; pode truncar)",
    ),
    busca: Optional[str] = Query(
        None,
        max_length=200,
        description="Filtro parcial em nome, arquivo ou documento",
    ),
    token: auth.TokenData = Depends(require_auth),
) -> dict:
    b = busca.strip() if busca else None
    alcance = _documentos_ao_alcance(token)
    if todas_filtradas:
        raw = historico_certificados(limite_snapshots, offset=None, limit=None, busca=b)
        itens = _recortar_pela_carteira(list(raw.get("itens") or []), alcance)
        lista_truncada = len(itens) > LISTAGEM_EXPORT_MAX
        return {
            "itens": itens[:LISTAGEM_EXPORT_MAX],
            "total": len(itens),
            "snapshots_lidos": raw.get("snapshots_lidos", 0),
            "fonte": raw.get("fonte"),
            "lista_truncada": lista_truncada,
        }

    off = (pagina - 1) * por_pagina
    if alcance is not None:
        # Com recorte, a página é cortada DEPOIS do recorte, aqui: paginar no
        # banco e recortar depois daria páginas com buracos e um total que
        # conta o que a pessoa não pode ver (#5).
        raw = historico_certificados(limite_snapshots, offset=None, limit=None, busca=b)
        recortados = _recortar_pela_carteira(list(raw.get("itens") or []), alcance)
        raw = {**raw, "itens": recortados[off: off + por_pagina], "total": len(recortados),
               "offset": off, "limit": por_pagina}
    else:
        raw = historico_certificados(
            limite_snapshots,
            offset=off,
            limit=por_pagina,
            busca=b,
        )
    total = int(raw.get("total") or 0)
    total_pags = max(1, (total + por_pagina - 1) // por_pagina) if total else 1
    pagina_out = min(max(1, pagina), total_pags)
    out = dict(raw)
    out["paginacao"] = {
        "pagina": pagina_out,
        "total_paginas": total_pags,
        "total_itens": total,
        "por_pagina": por_pagina,
        "export_max": LISTAGEM_EXPORT_MAX,
    }
    return out


@app.get("/api/certificados/vencidos", dependencies=[Depends(require_modulo("vencidos"))])
def vencidos_certificados(
    data_inicio: Optional[str] = Query(None, description="Data inicial (YYYY-MM-DD) pelo vencimento"),
    data_fim: Optional[str] = Query(None, description="Data final (YYYY-MM-DD) pelo vencimento"),
    pagina: int = Query(1, ge=1),
    por_pagina: int = Query(20, ge=1, le=2000),
    todas_filtradas: bool = Query(False, description="Lista completa filtrada (exportação; pode truncar)"),
    busca: Optional[str] = Query(None, max_length=200),
    limite_snapshots: int = Query(500, ge=1, le=2000, description="Quantidade máxima de snapshots lidos"),
    ordem: str = Query("desc", pattern="^(asc|desc)$", description="Ordem pelo vencimento: desc = mais recente primeiro"),
    token: auth.TokenData = Depends(require_auth),
) -> dict:
    # Data inválida é 422, não filtro ignorado (achado #54): `_parse_iso_utc`
    # devolvia `datetime.min` para "abc" e a tela mostrava a lista inteira como
    # se o filtro tivesse valido.
    inicio_dt = _data_da_query(data_inicio, "data_inicio", "T00:00:00+00:00")
    fim_dt = _data_da_query(data_fim, "data_fim", "T23:59:59+00:00")

    # Vencidos precisa de uma agregação tão ampla quanto a do histórico (fallback snapshots).
    lim_hist = max(limite_snapshots, config.HISTORICO_LIMITE_SNAPSHOTS)
    hist = historico_certificados(lim_hist, offset=None, limit=None, busca=None)
    itens_hist = _recortar_pela_carteira(hist.get("itens", []), _documentos_ao_alcance(token))
    busca_txt = str(busca or "").strip() or None

    now_utc = datetime.now(timezone.utc)
    min_dt = datetime.min.replace(tzinfo=timezone.utc)

    def _conta_como_certificado_vencido(it: dict) -> bool:
        """Inclui `expirado`/`vencido` no status ou data de validade já passada (alinha ao painel)."""
        s = str(it.get("status_ultimo") or "").lower()
        if s in ("expirado", "vencido"):
            return True
        venc_dt = _parse_iso_utc(it.get("vencimento_certificado"))
        if venc_dt <= min_dt:
            return False
        return venc_dt < now_utc

    venc_filtrados: List[dict] = []
    for it in itens_hist:
        if not _conta_como_certificado_vencido(it):
            continue
        venc_dt = _parse_iso_utc(it.get("vencimento_certificado"))
        s_low = str(it.get("status_ultimo") or "").lower()
        if inicio_dt or fim_dt:
            if venc_dt <= min_dt:
                if s_low not in ("expirado", "vencido"):
                    continue
            else:
                if inicio_dt and venc_dt < inicio_dt:
                    continue
                if fim_dt and venc_dt > fim_dt:
                    continue
        venc_filtrados.append(it)

    venc_filtrados = _vencidos_filtrar_busca(venc_filtrados, busca_txt or "")

    # Ordem pelo vencimento, mais recente primeiro por padrão: quem abre a
    # tela quer o que acabou de vencer, não o de 2019. Antes a lista vinha na
    # ordem da agregação do histórico, que a pessoa lia como aleatória. Quem
    # não tem data vai para o fim nas duas direções. A ordenação é sobre a
    # lista inteira, antes do corte da página.
    venc_filtrados.sort(
        key=lambda it: _parse_iso_utc(it.get("vencimento_certificado")),
        reverse=(ordem == "desc"),
    )
    if ordem == "asc":
        sem_data = [it for it in venc_filtrados if _parse_iso_utc(it.get("vencimento_certificado")) <= min_dt]
        venc_filtrados = [it for it in venc_filtrados if _parse_iso_utc(it.get("vencimento_certificado")) > min_dt] + sem_data

    # Nome legível decidido aqui, num lugar só (ver app/nomes.py); o original
    # continua em `nome` para busca e exportação.
    venc_filtrados = [{**it, "nome_exibicao": nomes.nome_exibicao(it.get("nome"))} for it in venc_filtrados]

    anos_cnt: defaultdict[int, int] = defaultdict(int)
    for it in venc_filtrados:
        venc_dt = _parse_iso_utc(it.get("vencimento_certificado"))
        y = int(venc_dt.year)
        if y < 1900:
            continue
        anos_cnt[y] += 1
    resumo_anos = [{"ano": ano, "total": anos_cnt[ano]} for ano in sorted(anos_cnt.keys(), reverse=True)]

    total = len(venc_filtrados)
    if todas_filtradas:
        lista_truncada = total > LISTAGEM_EXPORT_MAX
        return {
            "itens": venc_filtrados[:LISTAGEM_EXPORT_MAX],
            "total": total,
            "data_inicio": data_inicio,
            "data_fim": data_fim,
            "snapshots_lidos": hist.get("snapshots_lidos", 0),
            "lista_truncada": lista_truncada,
            "resumo_anos": resumo_anos,
        }

    total_pags = max(1, (total + por_pagina - 1) // por_pagina) if total else 1
    pagina_out = min(max(1, pagina), total_pags)
    off_pg = (pagina_out - 1) * por_pagina
    pagina_slice = venc_filtrados[off_pg : off_pg + por_pagina]

    return {
        "itens": pagina_slice,
        "total": total,
        "data_inicio": data_inicio,
        "data_fim": data_fim,
        "ordem": ordem,
        "snapshots_lidos": hist.get("snapshots_lidos", 0),
        "resumo_anos": resumo_anos,
        "paginacao": {
            "pagina": pagina_out,
            "total_paginas": total_pags,
            "total_itens": total,
            "por_pagina": por_pagina,
            "export_max": LISTAGEM_EXPORT_MAX,
        },
    }


# Ingestao de inventario: quem alimenta e o agente (`agent/run_agent.py`), e
# `require_auth` aceitava qualquer autenticado — um operador comum podia
# sobrescrever o inventario inteiro. `require_agent_or_admin` e a mesma guarda
# que `upload-pfx`, `redeem` e `report` ja usam, e o agente ja passa por ela em
# producao (o cofre tem 491 certificados que so chegaram por `upload-pfx`).
@app.post("/api/ingest")
def ingest(
    body: IngestBody,
    background_tasks: BackgroundTasks,
    token: auth.TokenData = Depends(require_agent_or_admin),
) -> dict:
    """
    Recebe o resultado de um scan feito no Windows (agente em segundo plano).
    Persiste no banco (ou em data/last_ingest.json se o banco não estiver configurado).
    Também faz upsert na tabela materializada cert_history para acelerar o histórico.

    O inventário é o da máquina que a credencial prova ser (achado #4): ele
    alimenta a barreira de custódia do cofre, e um agente que escrevesse o
    inventário de OUTRA estação escolhia o que ela pode enviar.
    """
    machine_id = _machine_da_credencial(token, body.machine_id) or "default"
    scanned = datetime.now(timezone.utc)
    # O nome do arquivo carrega a senha do PFX; ele não entra no banco por
    # nenhum caminho (SECURITY_AUDIT #2). Um agente antigo ainda o manda —
    # aqui ele vira nome público, pasta e chave, e o bruto é descartado.
    items = [nome_publico.sanitizar_item(it) for it in _normalize_ingest_items_status(body.items, scanned)]
    save_snapshot(
        machine_id=machine_id,
        source_folder=body.source_folder.strip(),
        expired_folder=body.expired_folder.strip(),
        items=items,
    )
    # Atualiza a tabela materializada — operação rápida, não bloqueia o retorno
    upsert_cert_history(
        machine_id=machine_id,
        scanned_iso=scanned.isoformat(),
        items=items,
    )
    # Dispara e-mails de alerta em segundo plano para não bloquear a resposta do agente
    background_tasks.add_task(trigger_all_alerts)
    return {
        "ok": True,
        "itens_recebidos": len(body.items),
        "grava_em": "banco" if banco_configurado() else "arquivo local (data/last_ingest.json)",
    }


# Move arquivo de certificado no sistema de arquivos do servidor. Estava sob
# `require_auth` — qualquer autenticado. Nenhum template ou script do portal
# chama esta rota; ela e acionada fora da UI, e quem a aciona e operacao.
@app.post("/api/mover-vencidos", dependencies=[Depends(require_admin)])
def mover_vencidos() -> JSONResponse:
    """
    Só move arquivos no **mesmo** sistema de arquivos que corre o API (servidor acessa as pastas).
    Se a interface mostrar dados "remotos" vindos do agente, use o agendador no Windows
    (agente com --mover) para mover aí o disco local.
    """
    sets = load_settings()
    src = sets.effective_source()
    exp = sets.effective_expired()
    itens: List[CertInfo] = scan_folder(src)
    movidos: List[dict] = []
    erros: List[dict] = []

    for c in itens:
        if c.status != CertStatus.EXPIRED:
            continue
        # Nome público e pasta, nunca o caminho completo: o nome do arquivo
        # carrega a senha do PFX (SECURITY_AUDIT #2).
        rotulo = nome_publico.nome_publico_de_arquivo(c.file_name) or "(sem nome)"
        try:
            novo = move_to_expired(c, exp)
            movidos.append({"arquivo": rotulo, "de": nome_publico.pasta_de(str(c.path)),
                            "para": nome_publico.pasta_de(str(novo))})
        except OSError as e:
            logger.error("Falha ao mover %s: %s", rotulo, e)
            erros.append({"arquivo": rotulo, "erro": "Não foi possível mover o arquivo. Veja o log do servidor."})

    return JSONResponse(
        {
            "movidos": movidos,
            "erros": erros,
            "total_movidos": len(movidos),
        }
    )


# =========================================================================
# LGPD / PRIVACY BY DESIGN - DIREITOS DOS TITULARES
# =========================================================================

@app.get("/api/users/me/export")
def export_my_data(token: auth.TokenData = Depends(require_auth)) -> dict:
    """[LGPD] Portabilidade e Consulta de Dados (Art. 18, incisos II e X)"""
    from app.settings_state import load_colaborador_selecao
    email = token.email
    docs = load_colaborador_selecao(email, _user_id_da_sessao(token))
    
    return {
        "titular": email,
        "vinculo_role": token.role,
        "documentos_monitorados_cnpj_cpf": docs,
        "exportado_em": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "aviso_lgpd": "Este arquivo contém seus dados pessoais conforme registro no sistema."
    }

@app.delete("/api/users/me/delete")
def delete_my_data(token: auth.TokenData = Depends(require_auth)) -> dict:
    """[LGPD] Direito ao Esquecimento / Eliminação (Art. 18, inciso VI)"""
    from app.settings_state import _banco
    email = token.email
    sb = _banco()
    
    # 1. Apagar seleções (Ações do usuário no app)
    if sb:
        # Pela identidade. O apagamento por `user_email` que acompanhava este
        # daqui saiu na fase 3c: a coluna deixou de ser escrita e some na 3d,
        # então continuar filtrando por ela seria apagar por um valor que o
        # portal já não grava — e daria a impressão de cobertura que não há.
        #
        # Sem `user_id` não dá para apagar nada com segurança, e numa rota de
        # LGPD isso não pode passar calado.
        uid = _user_id_da_sessao(token)
        if uid:
            sb.table("colaborador_cert_selecoes").delete().eq("user_id", uid).execute()
        else:
            logger.error(
                "Pedido de eliminação de %s não removeu as seleções: sessão sem "
                "user_id. O dado continua no banco.",
                email,
            )
    else:
        # Modo arquivo local: limpa a entrada
        from app.settings_state import save_colaborador_selecao
        save_colaborador_selecao(email, [])
        
    return {
        "status": "ok", 
        "message": "Seus dados operacionais associados foram permanentemente removidos."
    }


# ══════════════════════════════════════════════════════════════════════════
# MÓDULO INSTALADOR DE CERTIFICADOS DIGITAIS
# ══════════════════════════════════════════════════════════════════════════

from app import cert_installer


class UploadPfxRequest(BaseModel):
    """Payload enviado pelo agente com o PFX cifrado em trânsito."""
    fingerprint: str
    machine_id: str = "default"
    pfx_b64: str  # PFX em base64 (cifrado em trânsito via TLS)
    password: Optional[str] = None
    nome_titular: Optional[str] = None
    documento: Optional[str] = None
    documento_tipo: Optional[str] = None
    subject: Optional[str] = None
    not_before: Optional[str] = None
    not_after: Optional[str] = None
    friendly_name: Optional[str] = None


@app.post("/api/cert-installer/upload-pfx")
def upload_pfx(
    body: UploadPfxRequest,
    request: Request,
    token: auth.TokenData = Depends(require_agent_or_admin),
):
    """
    Recebe um PFX do agente, cifra com a chave do servidor e armazena.
    Chamado pelo agente durante o ciclo de scan.
    """
    import base64 as b64mod
    try:
        pfx_bytes = b64mod.b64decode(body.pfx_b64)
    except Exception:
        raise HTTPException(status_code=400, detail="pfx_b64 inválido")

    # Um PFX real tem poucos KB. 50 MB era um vetor de DoS via base64 no banco.
    if len(pfx_bytes) > 1 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="PFX excede 1 MB")

    # A máquina é a da credencial, não a do corpo (achado #4).
    machine_id = _machine_da_credencial(token, body.machine_id) or "default"
    fingerprint = (body.fingerprint or "").strip().lower()

    # Barreira de servidor da custódia: mesmo que um agente desatualizado (ou
    # adulterado) envie o que não devia, só entra no cofre o que a política
    # permite. O filtro por machine_id é parte da barreira, não detalhe de
    # consulta — a custódia é por estação desde a chave composta.
    #
    # Sob opt-in, esta barreira e a lista que o agente consome eram a MESMA
    # consulta, e uma falha nela devolvia lista vazia: nada passava. Sob
    # opt-out isso se inverte, e é aqui que a tradução literal do código antigo
    # abriria o portão — "não consegui ler os bloqueios" viraria "nada está
    # bloqueado, pode gravar". Por isso `CustodiaIndisponivel` é tratada como
    # recusa explícita, e não cai no `except Exception` genérico lá embaixo.
    try:
        autorizados = cert_installer.fingerprints_autorizados(machine_id)
    except cert_installer.CustodiaIndisponivel as e:
        logger.warning("Upload recusado por custódia indisponível (%s): %s", machine_id, e)
        raise HTTPException(
            status_code=503,
            detail="Custódia indisponível; o envio será retentado no próximo ciclo.",
        )

    if fingerprint not in autorizados:
        raise HTTPException(
            status_code=403,
            detail=(
                "Certificado fora da custódia desta estação: está bloqueado, "
                "vencido, ilegível, ou ausente do último inventário."
            ),
        )

    # Os metadados vêm de DENTRO do PFX, nunca do corpo (achado #4). O
    # `documento` é o que `assegurar_carteira` compara com a carteira do
    # operador: aceitá-lo declarado deixava um agente comprometido gravar o PFX
    # de quem quisesse sob o CNPJ de um cliente do alvo. E o fingerprint
    # declarado tem de ser o do certificado enviado — era o passo que fazia o
    # PFX do atacante passar na custódia sob a identidade de um legítimo.
    # Depois da custódia de propósito: só se abre o PFX de quem já podia mandar.
    try:
        lido = cert_installer.ler_metadados_do_pfx(pfx_bytes, body.password)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    if fingerprint != lido["fingerprint"]:
        raise HTTPException(
            status_code=422,
            detail="O fingerprint declarado não é o do certificado dentro do PFX.",
        )

    try:
        cert_id = cert_installer.upsert_pfx(
            fingerprint=fingerprint,
            pfx_bytes=pfx_bytes,
            machine_id=machine_id,
            password=body.password,
            nome_titular=lido["nome_titular"],
            documento=lido["documento"],
            documento_tipo=lido["documento_tipo"],
            subject=lido["subject"],
            not_before=lido["not_before"],
            not_after=lido["not_after"],
            friendly_name=body.friendly_name,
        )
        return {"status": "ok", "id": cert_id, "fingerprint": fingerprint}
    except RuntimeError as e:
        # O texto vinha do cofre/banco e podia trazer nome de chave de
        # ambiente ou de tabela (achado #35). Fica no log, com a rota.
        logger.exception("Operação recusada pelo cofre ou pelo banco: %s", e)
        raise HTTPException(status_code=500, detail=ERRO_INTERNO_VEJA_LOG)
    except Exception:
        logger.exception("Erro ao processar upload de PFX")
        raise HTTPException(status_code=500, detail="Erro interno ao armazenar PFX")


class VaultOptinRequest(BaseModel):
    """Admin autoriza um certificado a ter o PFX guardado no cofre."""
    fingerprint: str
    machine_id: str = "default"
    nome_titular: Optional[str] = None
    documento: Optional[str] = None


@app.get("/api/cert-installer/vault-optin")
def listar_vault_optin(
    machine_id: Optional[str] = Query(None),
    token: auth.TokenData = Depends(require_modulo("instalador", permitir_agente=True, recusar_anonimo=True)),
):
    """
    Fingerprints que esta máquina pode enviar ao cofre.

    **O caminho e o formato da resposta não mudaram na inversão de 15/08**, e
    isso é deliberado: o agente instalado no ANALISESRV é um `.exe` compilado
    que sempre perguntou "o que posso mandar?" e só agiu sobre a resposta.
    Trocar o que entra na lista — de "autorizados um a um" para "inventário
    válido menos bloqueados" — inverteu a custódia sem recompilar nada.

    Sem `machine_id` não há pergunta a responder: a custódia é por estação
    desde a chave composta, e uma lista global não significa nada aqui.
    """
    if not machine_id:
        raise HTTPException(
            status_code=422,
            detail="machine_id é obrigatório: a custódia é definida por estação.",
        )
    # Agente só pergunta pela própria estação (achado #30): a lista diz quais
    # certificados estão em custódia lá, e uma estação não tem por que saber
    # isso de outra. Gente com o módulo Instalador (admin) continua livre.
    if (token.role or "") == "agent":
        machine_id = _machine_da_credencial(token, machine_id) or machine_id
    try:
        return {"fingerprints": sorted(cert_installer.fingerprints_autorizados(machine_id))}
    except cert_installer.CustodiaIndisponivel as e:
        # 503, nunca lista vazia. O agente trata não-200 como "não enviar
        # nada"; uma lista vazia ele trataria como "nada a enviar", que é o
        # mesmo efeito hoje — mas as duas respostas dizem coisas diferentes, e
        # confundi-las é como o opt-out vira falha aberta na próxima mudança.
        logger.warning("Custódia indisponível para %s: %s", machine_id, e)
        raise HTTPException(
            status_code=503,
            detail="Não foi possível determinar a custódia do cofre agora.",
        )


@app.post("/api/cert-installer/vault-optin", dependencies=[Depends(require_modulo("instalador", permissoes.NIVEL_EDITAR))])
def reativar_vault_custodia(
    body: VaultOptinRequest,
    _token: auth.TokenData = Depends(require_admin),
):
    """
    Devolve o certificado à custódia: apaga o bloqueio.

    Sob opt-in isto se chamava "autorizar" e gravava uma permissão. Sob opt-out
    a permissão é o padrão, então a ação equivalente é remover a exceção. O
    caminho continua o mesmo para não quebrar a tela; o que ele faz, não.

    O material volta sozinho na varredura seguinte — o cofre é derivado dos
    arquivos do ANALISESRV, não há o que restaurar aqui.
    """
    try:
        cert_installer.reativar_custodia(
            fingerprint=body.fingerprint,
            machine_id=body.machine_id,
        )
        return {"status": "ok", "fingerprint": body.fingerprint, "custodia": "ativa"}
    except RuntimeError as e:
        # O texto vinha do cofre/banco e podia trazer nome de chave de
        # ambiente ou de tabela (achado #35). Fica no log, com a rota.
        logger.exception("Operação recusada pelo cofre ou pelo banco: %s", e)
        raise HTTPException(status_code=500, detail=ERRO_INTERNO_VEJA_LOG)
    except Exception:
        logger.exception("Erro ao reativar custódia do certificado")
        raise HTTPException(status_code=500, detail="Erro interno ao reativar custódia")


@app.delete("/api/cert-installer/vault-optin/{fingerprint}", dependencies=[Depends(require_modulo("instalador", permissoes.NIVEL_EDITAR))])
def bloquear_vault_custodia(
    fingerprint: str,
    machine_id: str = Query(..., min_length=1),
    motivo: Optional[str] = Query(None, max_length=300),
    token: auth.TokenData = Depends(require_admin),
):
    """
    Desativa a custódia: registra o bloqueio e APAGA o PFX — de UMA estação.

    **O bloqueio é o que faz isto durar.** Sob opt-in bastava apagar
    autorização e material: sem autorização o agente não reenviava. Sob
    opt-out, apagar só o material seria um botão que se desfaz sozinho — o
    certificado segue no inventário, volta a ser autorizado no ciclo seguinte
    e o PFX sobe de novo em até 24h.

    O `machine_id` é obrigatório: desde a chave composta `(machine_id,
    fingerprint)`, o mesmo certificado pode estar no cofre de várias estações,
    e a rota não tem como adivinhar qual delas o admin quer desativar. Sem o
    parâmetro a chamada é recusada, em vez de alcançar todas.
    """
    try:
        cert_installer.bloquear_custodia(
            fingerprint=fingerprint,
            machine_id=machine_id,
            bloqueado_por=token.email or "desconhecido",
            motivo=motivo,
        )
        return {
            "status": "ok",
            "fingerprint": fingerprint,
            "machine_id": machine_id,
            "pfx_removido": True,
            "custodia": "bloqueada",
        }
    except RuntimeError as e:
        # O texto vinha do cofre/banco e podia trazer nome de chave de
        # ambiente ou de tabela (achado #35). Fica no log, com a rota.
        logger.exception("Operação recusada pelo cofre ou pelo banco: %s", e)
        raise HTTPException(status_code=500, detail=ERRO_INTERNO_VEJA_LOG)
    except Exception:
        logger.exception("Erro ao revogar certificado do cofre")
        raise HTTPException(status_code=500, detail="Erro interno ao revogar")


# Teto de certificados por token. Cada PFX ocupa ~10 KB no cofre e vai inteiro
# no bundle do instalador; sem limite, `certificate_ids` é um array livre e o
# download vira imprevisível. Recusar com número claro é melhor que entregar um
# arquivo de dezenas de MB que talvez nem baixe.
MAX_CERTIFICADOS_POR_TOKEN = 50


def _validar_pedido_de_instalacao(
    user_id: str, role: str, certificate_ids: List[str]
) -> None:
    """
    Tudo o que precisa valer antes de emitir um token de instalação.

    Função única de propósito: as duas rotas emissoras chamam exatamente esta,
    e `tests/test_carteira.py` lê o código para falhar se alguma rota nova
    emitir token sem passar por aqui. Duplicar a checagem seria o caminho
    natural, e a cópia que divergisse para o lado permissivo não daria sintoma
    nenhum — só entregaria certificado a quem não devia.

    `CarteiraIndisponivel` vira 503 e não 403: negar por falha de banco é o
    resultado seguro, mas dizer "você não tem permissão" a quem tem manda a
    pessoa procurar o gestor em vez de esperar o banco voltar.
    """
    if len(certificate_ids) > MAX_CERTIFICADOS_POR_TOKEN:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Selecione no máximo {MAX_CERTIFICADOS_POR_TOKEN} certificados por "
                f"instalador ({len(certificate_ids)} selecionados)."
            ),
        )
    try:
        cert_installer.assegurar_carteira(user_id, role, certificate_ids)
    except cert_installer.ForaDaCarteira as e:
        logger.warning("Instalação negada por carteira (user=%s): %s", user_id, e)
        raise HTTPException(status_code=403, detail=str(e))
    except cert_installer.CarteiraIndisponivel as e:
        logger.warning("Carteira indisponível (user=%s): %s", user_id, e)
        raise HTTPException(
            status_code=503,
            detail="Não foi possível verificar suas permissões agora. Tente novamente.",
        )


ERRO_SEM_ALCANCE = (
    "Você não lidera nenhum departamento, então não há para quem liberar "
    "certificados. Peça a um administrador para incluí-lo como líder."
)


async def require_admin_ou_lider(
    token: auth.TokenData = Depends(require_auth),
) -> auth.TokenData:
    """
    Quem pode montar carteira: admin, ou quem lidera ao menos um departamento.

    Mudou em 18/08/2026. Antes bastava o papel `gestor`, e o alcance era total
    — qualquer gestor liberava qualquer cliente para qualquer operador. Agora o
    papel abre a porta e a LIDERANÇA define até onde se vai; cada rota confere
    o alvo com `cert_installer.pode_gerir`.

    Mudou de novo em 20/08/2026: o papel passou a ser decidido pela matriz de
    permissões (`require_modulo("carteiras", ...)` nas rotas), e esta função
    ficou só com a liderança. Quem chega aqui já provou que o papel dele alcança
    Carteiras; falta provar que a pessoa-alvo está no alcance dele.

    Quem lidera nada é recusado aqui mesmo, com uma mensagem que diz o que
    fazer. Deixá-lo entrar numa tela onde toda ação falha depois seria pior: o
    sintoma viraria "não consigo salvar nada".
    """
    papel = (token.role or "").strip().lower()
    if papel in cert_installer.PAPEIS_COM_ALCANCE_TOTAL:
        return token

    # O PAPEL deixou de ser decidido aqui em 20/08. Antes era um literal
    # (`papel != "gestor"`), agora quem diz se o papel alcanca Carteiras e a
    # matriz de permissoes, declarada nas rotas com `require_modulo`. Esta
    # guarda cuida so do outro eixo: a LIDERANCA, que diz de quem.
    #
    # Separar os dois e o que torna a tela util. Com o literal, marcar
    # "Carteiras: Ver e editar" para outro papel nao adiantaria nada — a guarda
    # recusaria assim mesmo, e a tela estaria prometendo o que nao entrega.

    uid = _user_id_da_sessao(token)
    try:
        if uid and cert_installer.departamentos_que_lidera(uid):
            return token
    except cert_installer.AlcanceIndisponivel:
        # 503, e não 403: "não consegui verificar" não é "você não pode". Um
        # 403 aqui faria o líder acreditar que perdeu a permissão.
        raise HTTPException(
            status_code=503,
            detail="Não foi possível verificar seus departamentos. Tente de novo.",
        )
    raise HTTPException(status_code=403, detail=ERRO_SEM_ALCANCE)


def _exigir_alcance(token: auth.TokenData, alvo_id: str) -> None:
    """
    Barreira por PESSOA. `require_admin_ou_lider` só diz que o ator pode montar
    carteiras; esta diz de quem.

    Sem ela, um líder do Fiscal montaria a carteira de alguém do Contábil
    apenas trocando o `user_id` na chamada — a tela filtra, mas a tela não é a
    barreira.
    """
    try:
        if cert_installer.pode_gerir(_user_id_da_sessao(token) or "", token.role or "", alvo_id):
            return
    except cert_installer.AlcanceIndisponivel:
        raise HTTPException(
            status_code=503,
            detail="Não foi possível verificar seu alcance. Tente de novo.",
        )
    raise HTTPException(
        status_code=403,
        detail="Esta pessoa não está em um departamento que você lidera.",
    )


class CarteiraRequest(BaseModel):
    user_id: str
    documentos: List[str]


# Modulo `carteiras` na matriz desde 20/08, com os DOIS eixos declarados: a
# matriz diz se o papel alcanca (e se so ve ou tambem monta), e
# `require_admin_ou_lider` diz de QUEM. Um lider do Fiscal com "Ver e editar"
# continua sem tocar na carteira de alguem do Contabil.
@app.get("/api/carteira/operadores", dependencies=[Depends(require_modulo("carteiras"))])
def listar_operadores(
    token: auth.TokenData = Depends(require_admin_ou_lider),
) -> dict:
    """
    Quem pode receber carteira, com quantos documentos cada um já tem.

    Rota própria em vez de `/api/users`: aquela é de admin e devolve a linha
    inteira do usuário. O gestor precisa montar carteira **sem** poder
    administrar contas, e não tem por que ver o hash de senha de ninguém.
    """
    from app.settings_state import _banco

    sb = _banco()
    if not sb:
        raise HTTPException(status_code=503, detail="Banco não configurado")
    try:
        us = sb.table("users").select(
            "id, email, full_name, role, ativo, gestor_id, departamento_id"
        ).execute().data or []
        cart = sb.table("carteira").select("user_id").execute().data or []
    except Exception:
        logger.exception("Falha ao listar operadores")
        raise HTTPException(status_code=503, detail="Não foi possível listar os operadores.")

    from collections import Counter

    # O líder vê apenas quem ele alcança. Mostrar a lista inteira e recusar
    # depois seria a pior combinação: ele monta a carteira de alguém do outro
    # setor, clica em salvar, e só aí descobre — sem entender o critério.
    #
    # Filtrado aqui e conferido de novo em cada rota que age: esta é a tela, e
    # tela não é barreira. Quem chamar a API direto com outro `user_id` esbarra
    # em `_exigir_alcance`.
    eu = _user_id_da_sessao(token) or ""
    papel = (token.role or "").strip().lower()
    if papel in cert_installer.PAPEIS_COM_ALCANCE_TOTAL:
        visiveis = us
    else:
        try:
            meus = cert_installer.departamentos_que_lidera(eu)
        except cert_installer.AlcanceIndisponivel:
            raise HTTPException(
                status_code=503,
                detail="Não foi possível verificar seus departamentos. Tente de novo.",
            )
        visiveis = [
            u for u in us
            if str(u.get("id")) == eu
            or (u.get("departamento_id") and str(u["departamento_id"]) in meus)
        ]

    quantos = Counter(str(c.get("user_id")) for c in cart)
    from app import texto as _texto
    operadores = []
    for u in visiveis:
        n = quantos.get(str(u.get("id")), 0)
        operadores.append(
            {
                "id": str(u.get("id")),
                "email": u.get("email"),
                "full_name": u.get("full_name"),
                # Só na exibição: "irla" → "Irla", caixa alta → título. O dado
                # gravado não muda (a correção do cadastro é em Usuários).
                "nome_exibicao": nomes.nome_pessoa(u.get("full_name")) or (u.get("email") or ""),
                "role": u.get("role"),
                "ativo": auth.conta_ativa(u),
                "gestor_id": u.get("gestor_id"),
                "departamento_id": u.get("departamento_id"),
                "documentos": n,
                "sem_carteira": n == 0,
                "textos": {"clientes": _texto.plural(n, "cliente")},
            }
        )
    # Sem carteira primeiro (é o único estado que pede ação; o Dashboard
    # aponta para cá por isso), depois em ordem alfabética.
    operadores.sort(key=lambda o: (0 if o["sem_carteira"] else 1, (o["nome_exibicao"] or "").lower()))

    # Resumo da lista, com a mesma regra da tela: só operadores (role user)
    # ativos, mais inativos que ainda tenham carteira a limpar.
    na_lista = [o for o in operadores if (o["role"] or "").lower() == "user" and (o["ativo"] or o["documentos"] > 0)]
    sem = sum(1 for o in na_lista if o["sem_carteira"])
    total = len(na_lista)
    if sem:
        resumo_txt = _texto.plural(total, "operador", "operadores") + " · " + str(sem) + " sem carteira"
    else:
        resumo_txt = _texto.plural(total, "operador", "operadores") + (", todos com carteira" if total else "")
    return {
        "operadores": operadores,
        "resumo": {"operadores": total, "sem_carteira": sem, "texto": resumo_txt},
    }


@app.get("/api/carteira/documentos", dependencies=[Depends(require_modulo("carteiras")), Depends(require_admin_ou_lider)])
def listar_documentos_atribuiveis(
    q: Optional[str] = Query(None, max_length=120),
    limite: int = Query(500, ge=1, le=2000),
) -> dict:
    """
    Universo de documentos para atribuir, filtrável por nome ou número.

    O teto era 500 e havia 491 clientes — a um cadastro de distância de
    truncar em silêncio, que é como a curva de vencimento perdeu 29
    certificados em 15/08. Subiu para 2000; a tela pede a lista inteira de
    uma vez (medido: 491 documentos = 33 KB em ~375 ms) e monta os dois
    painéis no cliente, então filtrar no servidor virou opcional.

    `total` continua vindo separado de `documentos` justamente para a tela
    poder dizer quando a lista foi cortada, em vez de parecer completa.
    """
    todos = cert_installer.universo_de_documentos()
    termo = (q or "").strip().lower()
    if termo:
        digitos = cert_installer.so_digitos(termo)
        todos = [
            d for d in todos
            if termo in (d["nome"] or "").lower()
            or (digitos and digitos in d["documento"])
        ]
    return {"total": len(todos), "documentos": todos[:limite]}


@app.get("/api/carteira/{user_id}", dependencies=[Depends(require_modulo("carteiras"))])
def obter_carteira(
    user_id: str,
    token: auth.TokenData = Depends(require_admin_ou_lider),
) -> dict:
    """
    Documentos que este operador pode instalar, com a trilha de atribuição.

    A dependência saiu do decorador e virou parâmetro porque agora o token é
    USADO: `_exigir_alcance` precisa saber quem está perguntando. A trilha diz
    quem liberou o quê — informação de dentro do setor.
    """
    _exigir_alcance(token, user_id)
    try:
        linhas = cert_installer.detalhar_carteira(user_id)
    except cert_installer.CarteiraIndisponivel as e:
        raise HTTPException(status_code=503, detail=str(e))

    nomes = {d["documento"]: d["nome"] for d in cert_installer.universo_de_documentos()}
    return {
        "user_id": user_id,
        "documentos": sorted(l["documento"] for l in linhas),
        "itens": [
            {
                "documento": l["documento"],
                # Documento atribuído que não está mais no inventário continua
                # na carteira: a atribuição é uma decisão, e sumir com ela
                # esconderia que a pessoa tem acesso a algo que voltou depois.
                "nome": nomes.get(l["documento"], ""),
                "no_inventario": l["documento"] in nomes,
                "atribuido_por": l.get("atribuido_por_email"),
                "atribuido_em": l.get("atribuido_em"),
            }
            for l in linhas
        ],
    }


@app.post("/api/carteira", dependencies=[Depends(require_modulo("carteiras", permissoes.NIVEL_EDITAR))])
def atribuir_carteira(
    body: CarteiraRequest,
    token: auth.TokenData = Depends(require_admin_ou_lider),
) -> dict:
    """
    Acrescenta documentos à carteira de um operador.

    Quem atribui fica registrado — e-mail inclusive, não só o UUID. Com o
    gestor podendo atribuir qualquer cliente do acervo, essa trilha é a única
    forma de reconstruir o que houve se uma conta de gestor for comprometida;
    guardar só o UUID a perderia no dia em que a conta fosse apagada.
    """
    _exigir_alcance(token, body.user_id)
    try:
        gravados = cert_installer.atribuir_carteira(
            user_id=body.user_id,
            documentos=body.documentos,
            atribuido_por=_user_id_da_sessao(token),
            atribuido_por_email=token.email or "desconhecido",
        )
        return {"status": "ok", "gravados": gravados}
    except RuntimeError as e:
        # O texto vinha do cofre/banco e podia trazer nome de chave de
        # ambiente ou de tabela (achado #35). Fica no log, com a rota.
        logger.exception("Operação recusada pelo cofre ou pelo banco: %s", e)
        raise HTTPException(status_code=500, detail=ERRO_INTERNO_VEJA_LOG)
    except Exception:
        logger.exception("Erro ao atribuir carteira")
        raise HTTPException(status_code=500, detail="Erro interno ao atribuir carteira")


def _linhas_da_planilha(nome: str, raw: bytes) -> List[Dict[str, str]]:
    """
    Lê .csv ou .xlsx e devolve as linhas como dicionários de cabeçalho→valor.

    O .xlsx entra porque é o que sai do Excel sem passo extra — pedir "salve
    como CSV" antes de cada importação é exatamente o trabalho manual que
    esta rota existe para tirar. O `openpyxl` só é importado aqui: quem nunca
    importa planilha não paga o custo no cold start da Vercel.
    """
    if nome.endswith(".xlsx"):
        try:
            from openpyxl import load_workbook
        except ImportError:  # pragma: no cover - depende do ambiente de deploy
            raise HTTPException(
                status_code=503,
                detail="Leitura de .xlsx indisponível no servidor. Envie o arquivo como .csv.",
            )
        try:
            wb = load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
            ws = wb.active
            linhas = list(ws.iter_rows(values_only=True))
        except Exception:
            raise HTTPException(status_code=422, detail="Não consegui ler a planilha .xlsx.")
        finally:
            try:
                wb.close()
            except Exception:
                pass
        if not linhas:
            raise HTTPException(status_code=422, detail="Planilha vazia.")
        cabecalho = [str(c or "").strip() for c in linhas[0]]
        return [
            {cabecalho[i]: ("" if v is None else str(v).strip())
             for i, v in enumerate(linha) if i < len(cabecalho)}
            for linha in linhas[1:]
        ]

    # CSV: mesmo tratamento do import de usuários — BOM do Excel e separador
    # `;` do pt-BR são a regra, não a exceção.
    texto = raw.decode("utf-8-sig", errors="replace")
    try:
        delim = csv.Sniffer().sniff(texto[:2048], delimiters=",;").delimiter
    except csv.Error:
        delim = ";"
    leitor = csv.DictReader(io.StringIO(texto), delimiter=delim)
    if not leitor.fieldnames:
        raise HTTPException(status_code=422, detail="CSV sem cabeçalho.")
    return [{(k or ""): (v or "") for k, v in linha.items()} for linha in leitor]


@app.post("/api/carteira/importar", dependencies=[Depends(require_modulo("carteiras", permissoes.NIVEL_EDITAR))])
async def importar_carteiras(
    file: UploadFile = File(...),
    token: auth.TokenData = Depends(require_admin_ou_lider),
) -> dict:
    """
    Atribui carteiras em massa a partir de uma planilha de e-mail + documento.

    Montar carteira clicando cliente a cliente não escala: quem recebe uma
    lista pronta da operação copiava CNPJ por CNPJ na mão.

    O ALCANCE É CONFERIDO POR PESSOA, e não uma vez para o arquivo: o gestor
    importa só para quem ele lidera, exatamente como na tela. Uma linha fora
    do alcance vira erro DAQUELA linha — recusar o arquivo inteiro por causa
    de uma pessoa faria o gestor perder o trabalho já correto.

    Nada é gravado até o arquivo inteiro ser lido e validado: um arquivo com
    metade das linhas erradas deixaria a carteira em estado parcial, e o
    operador não teria como saber o que entrou.
    """
    nome = (file.filename or "").lower()
    if not (nome.endswith(".csv") or nome.endswith(".xlsx")):
        raise HTTPException(
            status_code=422,
            detail="Formato inválido. Envie a planilha em .xlsx ou .csv.",
        )

    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=422, detail="Arquivo vazio.")
    if len(raw) > 5 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Arquivo muito grande (limite de 5MB).")
    # Executável disfarçado. O `PK` do zip é legítimo aqui — todo .xlsx começa
    # com ele —, então a checagem é por extensão declarada.
    if raw.startswith(b"MZ") or raw.startswith(b"\x7fELF") or raw.startswith(b"%PDF"):
        raise HTTPException(status_code=422, detail="Conteúdo do arquivo suspeito.")
    if nome.endswith(".xlsx") and not raw.startswith(b"PK"):
        raise HTTPException(status_code=422, detail="Isto não é um .xlsx válido.")

    linhas = _linhas_da_planilha(nome, raw)
    if not linhas:
        raise HTTPException(status_code=422, detail="A planilha não tem nenhuma linha de dados.")

    mapa = {_norm_header(h): h for linha in linhas[:1] for h in linha}

    def coluna(*aliases: str) -> Optional[str]:
        for a in aliases:
            k = mapa.get(_norm_header(a))
            if k:
                return k
        return None

    col_email = coluna("email", "e-mail", "colaborador", "email do colaborador", "usuario")
    col_doc = coluna("documento", "cnpj", "cpf", "cnpj/cpf", "cnpj da empresa", "cliente")
    if not col_email or not col_doc:
        raise HTTPException(
            status_code=422,
            detail="A planilha precisa de duas colunas: e-mail do colaborador e CNPJ/CPF do cliente.",
        )

    from app.settings_state import _banco

    sb = _banco()
    if not sb:
        raise HTTPException(status_code=503, detail="Banco não configurado.")
    try:
        contas = sb.table("users").select("id, email").execute().data or []
    except Exception:
        logger.exception("Falha ao ler usuários na importação de carteiras")
        raise HTTPException(status_code=503, detail="Não foi possível ler os usuários.")
    por_email = {str(u.get("email") or "").strip().lower(): str(u.get("id")) for u in contas}

    universo = {d["documento"] for d in cert_installer.universo_de_documentos()}

    erros: List[Dict[str, Any]] = []
    por_usuario: Dict[str, set] = {}
    alcance: Dict[str, bool] = {}
    ator = _user_id_da_sessao(token) or ""

    for i, linha in enumerate(linhas, start=2):  # 1 é o cabeçalho
        email = (linha.get(col_email) or "").strip().lower()
        doc = cert_installer.so_digitos(linha.get(col_doc) or "")
        if not email and not doc:
            continue  # linha em branco no fim da planilha
        if not email or not doc:
            erros.append({"linha": i, "motivo": "Falta o e-mail ou o CNPJ/CPF."})
            continue

        user_id = por_email.get(email)
        if not user_id:
            erros.append({"linha": i, "motivo": f"Não existe usuário com o e-mail {email}."})
            continue

        if user_id not in alcance:
            try:
                alcance[user_id] = cert_installer.pode_gerir(ator, token.role or "", user_id)
            except cert_installer.AlcanceIndisponivel:
                raise HTTPException(
                    status_code=503,
                    detail="Não foi possível verificar seu alcance. Tente de novo.",
                )
        if not alcance[user_id]:
            erros.append({"linha": i, "motivo": f"{email} não está em um departamento que você lidera."})
            continue

        if doc not in universo:
            erros.append({"linha": i, "motivo": f"O documento {doc} não está no inventário."})
            continue

        por_usuario.setdefault(user_id, set()).add(doc)

    atribuidos = 0
    pessoas = 0
    for user_id, docs in por_usuario.items():
        try:
            atribuidos += cert_installer.atribuir_carteira(
                user_id=user_id,
                documentos=sorted(docs),
                atribuido_por=ator,
                atribuido_por_email=token.email or "desconhecido",
            )
            pessoas += 1
        except Exception:
            logger.exception("Falha ao gravar carteira importada")
            erros.append({"linha": 0, "motivo": "Falha ao gravar a carteira de um dos operadores."})

    return {
        "status": "ok",
        "atribuidos": atribuidos,
        "pessoas": pessoas,
        "linhas_lidas": len(linhas),
        "erros": erros,
    }


@app.delete("/api/carteira/{user_id}/{documento}", dependencies=[Depends(require_modulo("carteiras", permissoes.NIVEL_EDITAR))])
def remover_carteira(
    user_id: str,
    documento: str,
    token: auth.TokenData = Depends(require_admin_ou_lider),
) -> dict:
    _exigir_alcance(token, user_id)
    try:
        cert_installer.remover_da_carteira(user_id, documento)
        return {"status": "ok", "user_id": user_id, "documento": documento}
    except RuntimeError as e:
        # O texto vinha do cofre/banco e podia trazer nome de chave de
        # ambiente ou de tabela (achado #35). Fica no log, com a rota.
        logger.exception("Operação recusada pelo cofre ou pelo banco: %s", e)
        raise HTTPException(status_code=500, detail=ERRO_INTERNO_VEJA_LOG)
    except Exception:
        logger.exception("Erro ao remover da carteira")
        raise HTTPException(status_code=500, detail="Erro interno ao remover da carteira")


class ConfigInstaladorBody(BaseModel):
    # `instalador_nome_template` saiu em 23/08/2026: ele nomeava o .exe que o
    # portal servia, e o portal nao serve mais .exe nenhum.
    install_token_ttl_min: int = 0
    trilha_retencao_dias: int = 0


@app.put("/api/cert-installer/configuracao", dependencies=[Depends(require_modulo("instalador", permissoes.NIVEL_EDITAR))])
def salvar_config_instalador(body: ConfigInstaladorBody) -> dict:
    """
    Grava **só** as três configurações do módulo instalador.

    Rota própria em vez de reaproveitar `PUT /api/settings`: aquele monta um
    `PortalSettings` inteiro a partir do corpo, então uma tela que mandasse
    apenas estes três campos apagaria host, usuário e senha do SMTP — sem erro
    nenhum, e ninguém notaria até o próximo alerta não sair.

    Aqui a configuração atual é lida, três campos mudam, e o resto vai de volta
    como estava.
    """
    ttl = int(body.install_token_ttl_min or 0)
    if ttl and not (cert_installer.TTL_TOKEN_MIN <= ttl <= cert_installer.TTL_TOKEN_MAX):
        raise HTTPException(
            status_code=422,
            detail=(
                f"Validade do token: use entre {cert_installer.TTL_TOKEN_MIN} e "
                f"{cert_installer.TTL_TOKEN_MAX} minutos, ou 0 para o padrão."
            ),
        )

    retencao = int(body.trilha_retencao_dias or 0)
    if retencao < 0:
        raise HTTPException(status_code=422, detail="Retenção não pode ser negativa.")

    atual = load_settings()
    atual.install_token_ttl_min = ttl
    atual.trilha_retencao_dias = retencao
    # 503, e não 200: o valor foi para o arquivo local, mas `load_settings`
    # prefere o banco — a próxima leitura devolveria o valor antigo. Dizer
    # "salvo" aqui seria a tela mentindo sobre um dado que ela mesma vai
    # recarregar diferente.
    try:
        save_settings(atual, exigir_banco=True)
    except GravacaoNaoPersistida as e:
        # O motivo (código do banco, coluna que falta) vai para o log, onde
        # quem vai consertar o lê; a resposta diz só o que aconteceu (#35).
        logger.error("Gravação da configuração não persistida: %s", e)
        raise HTTPException(
            status_code=503,
            detail=(
                "Não foi possível gravar no banco; nada foi alterado para o portal. "
                "A cópia local ficou guardada. Veja o log do servidor."
            ),
        )
    return _settings_dict(atual)


@app.get("/api/cert-installer/expurgo-previa", dependencies=[Depends(require_modulo("instalador"))])
def previa_do_expurgo() -> dict:
    """
    Quantos registros da trilha o expurgo apagaria agora, e até que data.

    Existe porque o botão "Expurgar log agora" é irreversível: a confirmação
    precisa dizer o tamanho do que vai apagar, não só que vai apagar.
    """
    from app.settings_state import _banco

    dias = int(load_settings().trilha_retencao_dias or 0)
    if dias <= 0:
        return {"executado": False, "retencao_dias": 0, "registros": 0, "motivo": "retenção desligada (sem limite)"}
    corte = (datetime.now(timezone.utc) - timedelta(days=dias)).isoformat()
    client = _banco()
    if not client:
        return {"executado": False, "retencao_dias": dias, "registros": 0, "motivo": "Banco não configurado"}
    # O PostgREST devolve no máximo 1.000 linhas e não avisa que truncou:
    # conta em páginas.
    n = 0
    inicio = 0
    try:
        while True:
            pagina = (
                client.table("install_log").select("id").lt("created_at", corte).range(inicio, inicio + 999).execute().data
                or []
            )
            n += len(pagina)
            if len(pagina) < 1000 or inicio > 50_000:
                break
            inicio += 1000
    except Exception as e:  # noqa: BLE001
        logger.exception("Falha ao contar registros para o expurgo")
        return {"executado": False, "retencao_dias": dias, "registros": 0, "motivo": str(e)}
    return {"executado": True, "retencao_dias": dias, "corte": corte, "registros": n}


@app.post("/api/cert-installer/expurgar-log", dependencies=[Depends(require_modulo("instalador", permissoes.NIVEL_EDITAR))])
def expurgar_log_agora() -> dict:
    """
    Roda o expurgo sob demanda, sem esperar o cron.

    Quem acabou de configurar a retenção precisa ver o efeito para confiar
    nela — e uma rotina de LGPD que só roda amanhã de manhã não dá para
    verificar antes de responder por ela.
    """
    return {
        "install_log": cert_installer.expurgar_install_log(),
        "user_activity": atividade.expurgar(),
        "cofre": cert_installer.expurgar_cofre(),
    }


@app.get("/api/dashboard", dependencies=[Depends(require_modulo("dashboard"))])
def dashboard_visao_geral(dias: int = Query(30, ge=1, le=365)) -> dict:
    """
    Os painéis baratos do dashboard, numa chamada (~1s).

    Separado das renovações de propósito: aquele precisa de dois snapshots
    completos (~1 MB) e os outros seis somam poucas dezenas de KB. Fazer o
    barato esperar o caro atrasaria toda a tela pelo painel menos urgente.
    """
    from app import dashboard

    return dashboard.visao_geral(dias)


@app.get("/api/dashboard/renovacoes", dependencies=[Depends(require_modulo("dashboard"))])
def dashboard_renovacoes(
    dias: int = Query(30, ge=1, le=365),
    machine_id: str = Query("ANALISESRV", min_length=1),
) -> dict:
    """
    Renovações: o inventário de hoje contra o de N dias atrás.

    Sai de `cert_snapshots`, não de `cert_history` — aquela é
    `upsert(on_conflict="arquivo_chave")` e guarda só o estado atual, então o valor
    anterior já foi sobrescrito e a conta daria zero.

    A resposta traz `referencia`: as varreduras têm lacunas, e pedir 30 dias
    pode devolver a comparação com uma de 54 dias atrás. Apresentar isso como
    "últimos 30 dias" seria mentira.
    """
    from app import dashboard

    return dashboard.painel_renovacoes(dias=dias, machine_id=machine_id)


@app.get("/carteiras", response_class=HTMLResponse)
def pagina_carteiras(request: Request) -> HTMLResponse:
    # O operador selecionado viaja na URL (?operador=<id>): cada item da
    # lista é um link, e no celular a tela vira duas etapas — só a lista
    # sem operador, só o detalhe com ele — por CSS, sem depender de JS.
    operador = (request.query_params.get("operador") or "").strip()[:64]
    return templates.TemplateResponse(
        request=request,
        name="carteiras.html",
        context={"pagina_ativa": "carteiras", "operador_id": operador},
    )


@app.get("/dashboard", response_class=HTMLResponse)
def pagina_dashboard(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request, name="dashboard.html", context={"pagina_ativa": "dashboard"}
    )


# Modulo `instalador` na matriz desde 20/08 — mas SO as rotas da tela de
# diagnostico e do cofre. Tres grupos ficaram FORA, e a distincao e a coisa mais
# importante deste bloco:
#
#   1. Maquina pura (`upload-pfx`, `redeem`, `report`, `claim`,
#      `report-avulso`) segue com a guarda propria. O agente nao tem papel na
#      matriz.
#
#   2. FLUXO DO COLABORADOR (`instalabilidade`, `prepare`) fica de
#      fora. Sao chamadas pelo `index.html`, ou seja pertencem ao Inicio, onde a
#      pessoa instala o proprio certificado. Gatea-las por "Instalador" tiraria
#      de TODO operador a capacidade de instalar — e o sintoma apareceria como
#      "o botao de instalar sumiu" numa tela que ninguem mexeu.
#
#      O menu "Instalador" e a tela de DIAGNOSTICO, nao o ato de instalar. Os
#      dois compartilham o prefixo `/api/cert-installer/` e nao compartilham
#      publico.
#
#   3. `GET vault-optin` e de mao dupla e leva `recusar_anonimo`: ela diz quais
#      certificados estao no cofre, e estava em `require_agent_or_admin`
#      justamente porque aquela guarda recusa a identidade anonima.
@app.get("/api/cert-installer/diagnostico", dependencies=[Depends(require_modulo("instalador"))])
def diagnostico_do_instalador() -> dict:
    """
    Estado do módulo instalador, num lugar só.

    Cada bloco corresponde a algo que já falhou em produção sem aviso:

    - **binário**: `is_file()` só era consultado no clique, e a falha virava um
      503 com instrução de rebuild — inútil na Vercel, onde o FS é read-only.
    - **assinatura**: adiada em 11/08 e "não verificada em máquina real". Fica
      visível aqui em vez de dormir num changelog.
    - **cofre**: as seis falhas de instalação registradas têm causa única
      ("Senha ausente no cofre"), e descobrir isso exigiu ler o agent.log de
      uma máquina remota.
    - **chaves**: em 15/08 a chave foi trocada sem rotação e todo o cofre virou
      lixo cifrado. Nada na interface disse isso.
    """
    # Os blocos `binario`, `assinatura` e `icone` sairam em 23/08/2026 junto do
    # instalador avulso: eles diagnosticavam um .exe que o portal nao serve
    # mais. Diagnostico de coisa que nao existe e ruido que envelhece para
    # mentira.
    out: dict = {}

    try:
        out["cofre"] = cert_installer.diagnostico_do_cofre()
        out["chaves"] = cert_installer.diagnostico_das_chaves()
    except Exception as e:  # noqa: BLE001
        logger.exception("Falha no diagnóstico do cofre")
        out["cofre"] = {"erro": str(e)}
        out["chaves"] = {"erro": str(e)}

    # Situação geral ESCRITA (seção 2 do DS: nunca só por cor) e a lista do
    # que está errado, com quantos. "Senha em claro" é o mais grave.
    from app import texto as _texto
    c = out.get("cofre") or {}
    k = out.get("chaves") or {}
    problemas: List[str] = []
    if not c.get("erro"):
        if c.get("senha_em_claro"):
            problemas.append(_texto.plural(c["senha_em_claro"], "certificado com senha em claro no cofre", "certificados com senha em claro no cofre") + ".")
        if c.get("sem_senha_cifrada"):
            problemas.append(_texto.plural(c["sem_senha_cifrada"], "certificado sem senha cifrada", "certificados sem senha cifrada") + ".")
    sem_chave = list(k.get("versoes_sem_chave") or []) if not k.get("erro") else []
    if sem_chave:
        problemas.append(
            "Versões de chave sem chave configurada: " + ", ".join("v" + str(v) for v in sem_chave)
            + ". Esse material está indecifrável agora; reponha a chave em CERT_ENCRYPTION_KEY_V<n> ou peça um rescan ao agente."
        )
    if c.get("erro") or k.get("erro"):
        out["situacao"] = "erro"
    else:
        out["situacao"] = "atencao" if problemas else "ok"
    out["problemas"] = problemas
    out["textos"] = {
        "maquinas": [f"{m} · " + _texto.plural(n, "certificado") for m, n in (c.get("por_maquina") or {}).items()],
        "em_uso": [f"v{v} · " + _texto.plural(n, "certificado") for v, n in (k.get("linhas_por_versao") or {}).items()],
        "ajuda_revalidar": "Confere de novo as senhas e chaves de todos os certificados guardados.",
    }
    return out


@app.post("/api/cert-installer/revalidar-cofre", dependencies=[Depends(require_modulo("instalador", permissoes.NIVEL_EDITAR))])
def revalidar_cofre() -> dict:
    """
    Prova que a chave em vigor decifra o que está guardado.

    Contar linhas não prova nada: em 15/08 o cofre tinha uma linha íntegra, com
    todos os campos preenchidos, e completamente indecifrável. É `POST` porque
    faz trabalho criptográfico de verdade, não porque grave algo.
    """
    try:
        return {"resultados": cert_installer.revalidar_cofre()}
    except RuntimeError as e:
        logger.error("Revalidação do cofre indisponível: %s", e)
        raise HTTPException(status_code=503, detail="O cofre está indisponível para revalidar. Veja o log do servidor.")
    except Exception:
        logger.exception("Falha ao revalidar o cofre")
        raise HTTPException(status_code=500, detail="Erro interno ao revalidar o cofre")


@app.get("/api/cert-installer/instalabilidade")
def instalabilidade(
    machine_id: str = Query(..., min_length=1),
    token: auth.TokenData = Depends(require_auth),
) -> dict:
    """
    O que **este** usuário pode instalar nesta máquina, e o motivo de cada não.

    Alimenta a seleção do Início. Não é barreira — a barreira é
    `assegurar_carteira`, no momento de emitir o token. Isto existe para a tela
    não convidar o usuário a marcar o que o servidor vai recusar depois, com o
    erro chegando só na máquina dele.
    """
    user_id = _user_id_da_sessao(token)
    if not user_id:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")
    alcance_total = (token.role or "").strip().lower() in cert_installer.PAPEIS_COM_ALCANCE_TOTAL

    if not alcance_total:
        # A estação tem de ser uma das desta pessoa (achado #30): a rota era
        # `require_auth` puro com `machine_id` livre, e devolvia o inventário
        # de qualquer estação a qualquer operador. Quem sabe o vínculo é o
        # portal de inventário; sem ele, o vínculo não é verificável e a
        # resposta segue — recortada pela carteira, abaixo — com aviso.
        dispositivos = _dispositivos_da_pessoa((token.email or "").strip().lower())
        if dispositivos is None:
            logger.warning(
                "Instalabilidade sem conferir o vínculo pessoa↔estação (%s): portal de "
                "inventário indisponível ou ponte não configurada.", machine_id,
            )
        else:
            minhas = {str(d.get("machine_id") or "").strip().lower() for d in dispositivos}
            if machine_id.strip().lower() not in minhas:
                raise HTTPException(status_code=403, detail="Esta estação não está vinculada a você.")

    try:
        itens = cert_installer.estado_de_instalabilidade(machine_id, user_id, token.role)
    except (cert_installer.CustodiaIndisponivel, cert_installer.CarteiraIndisponivel) as e:
        logger.warning("Instalabilidade indisponível (%s): %s", machine_id, e)
        raise HTTPException(
            status_code=503,
            detail="Não foi possível verificar quais certificados estão disponíveis.",
        )
    if not alcance_total:
        # O filtro de carteira decidia só o RÓTULO; o conjunto saía inteiro,
        # com fingerprint e id do cofre de clientes fora da carteira (#30).
        itens = {
            fp: v for fp, v in itens.items()
            if v.get("estado") != cert_installer.ESTADO_FORA_DA_CARTEIRA
        }
    return {
        "machine_id": machine_id,
        "alcance_total": alcance_total,
        "itens": itens,
    }


# A rota POST /api/cert-installer/prepare foi removida em 16/08/2026 e VOLTOU em
# 23/08/2026, por um destino diferente do original.
#
# O comentário de então dizia: "endpoint que emite token de instalação sem
# ninguém usar é superfície de ataque sem contrapartida". A premissa era o USO,
# não a arquitetura — e ela caiu quando o agente do INVENT, que já mora nas
# estações dos colaboradores, passou a ser quem instala.
#
# Ele fechava assim: "Se o caminho voltar a fazer sentido, o que falta é a rota:
# a barreira de carteira e a trilha já existem, e `tests/test_carteira.py`
# obriga qualquer rota nova que emita token a passar por elas." É exatamente o
# que segue abaixo.
#
# O que MUDOU em relação à original: ela enfileirava na fila deste portal, para
# o agente daqui. Agora o agente é o do INVENT, que escuta a fila DE LÁ — então
# este portal pede, servidor a servidor, que o outro enfileire. Nenhum dos dois
# ganha acesso ao banco do outro.


@app.get("/api/cert-installer/minha-estacao")
def minha_estacao(token: auth.TokenData = Depends(require_auth)) -> dict:
    """
    Há um agente vivo desta pessoa agora? Em qual máquina?

    O Início usa isto para decidir entre "Instalar nesta máquina" e o download
    do .exe. Quem sabe a resposta é o portal de inventário: o vínculo
    pessoa↔máquina nasce do login que ela mesma fez na estação.

    **Nunca levanta.** Uma indisponibilidade do outro portal não pode derrubar o
    Início — ela apenas faz o botão não aparecer, e a pessoa cai no caminho do
    .exe, que é o que ela já fazia antes de tudo isto existir. Degradar para o
    caminho antigo é diferente de quebrar.
    """
    if not config.ponte_invent_configurada():
        return {"disponivel": False, "motivo": "nao_configurado", "dispositivos": []}

    email = (token.email or "").strip().lower()
    if not email:
        return {"disponivel": False, "motivo": "sem_email", "dispositivos": []}

    dispositivos = _dispositivos_da_pessoa(email)
    if dispositivos is None:
        return {"disponivel": False, "motivo": "indisponivel", "dispositivos": []}

    return {
        "disponivel": bool(dispositivos),
        "motivo": "" if dispositivos else "sem_agente_vivo",
        "dispositivos": dispositivos,
    }


def _dispositivos_da_pessoa(email: str) -> Optional[List[dict]]:
    """As estações com agente vivo desta pessoa, segundo o portal de inventário.

    `None` quando não dá para saber (ponte não configurada ou indisponível) —
    diferente de lista vazia, que é "sei, e não há nenhuma". Quem chama decide
    o que fazer com a dúvida: o Início degrada para o caminho do .exe, e a
    instalabilidade deixa de conferir o vínculo, avisando.
    """
    if not config.ponte_invent_configurada() or not (email or "").strip():
        return None
    try:
        import httpx

        r = httpx.get(
            f"{config.INVENT_API_URL}/api/agent/devices/vivos",
            params={"email": email},
            headers={"Authorization": f"Bearer {config.CERT_PORTAL_TOKEN}"},
            timeout=8.0,
        )
        if r.status_code != 200:
            logger.warning("Portal de inventário respondeu %s ao consultar estações", r.status_code)
            return None
        return list((r.json() or {}).get("dispositivos") or [])
    except Exception:  # noqa: BLE001
        logger.warning("Não foi possível consultar as estações no portal de inventário", exc_info=True)
        return None


class PrepararInstalacaoRequest(BaseModel):
    """Instalar na máquina onde a pessoa está, pelo agente residente."""
    certificate_ids: List[str]
    machine_id: str
    hostname: Optional[str] = None


@app.post("/api/cert-installer/prepare")
def preparar_instalacao(
    body: PrepararInstalacaoRequest,
    request: Request,
    token: auth.TokenData = Depends(require_auth),
):
    """
    Emite o token e pede ao INVENT que a estação instale.

    Desde 23/08/2026 e a UNICA rota que emite token de instalacao — o caminho de
    download saiu. A barreira de carteira continua sendo o que a governa, porque
    um token e a entrega da chave privada.

    O `target_machine` deixa de ser "download-avulso" e passa a ser a máquina de
    verdade, o que torna a trilha capaz de responder ONDE o certificado entrou.
    """
    if not body.certificate_ids:
        raise HTTPException(status_code=400, detail="Selecione ao menos um certificado")

    machine_id = (body.machine_id or "").strip()
    if not machine_id:
        raise HTTPException(status_code=400, detail="Máquina de destino não informada.")

    if not config.ponte_invent_configurada():
        # 503 e não 404: a rota existe, o que falta é a ligação entre os dois
        # portais. Quem estiver implantando precisa saber a diferença.
        raise HTTPException(
            status_code=503,
            detail=(
                "Instalação pelo agente não está ligada neste portal "
                "(INVENT_API_URL / CERT_PORTAL_TOKEN)."
            ),
        )

    user_id = _user_id_da_sessao(token)
    if not user_id:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")

    _validar_pedido_de_instalacao(user_id, token.role, body.certificate_ids)

    client_ip = request.client.host if request.client else None

    try:
        token_raw, token_id, expires_at = cert_installer.create_install_token(
            user_id=user_id,
            user_email=token.email,
            target_machine=machine_id,
            certificate_ids=body.certificate_ids,
            client_ip=client_ip,
        )
    except RuntimeError as e:
        # O texto vinha do cofre/banco e podia trazer nome de chave de
        # ambiente ou de tabela (achado #35). Fica no log, com a rota.
        logger.exception("Operação recusada pelo cofre ou pelo banco: %s", e)
        raise HTTPException(status_code=500, detail=ERRO_INTERNO_VEJA_LOG)
    except Exception:
        logger.exception("Erro ao emitir token de instalação pelo agente")
        raise HTTPException(status_code=500, detail="Erro interno ao preparar a instalação")

    # Só registra SOLICITADO depois de o comando CHEGAR ao outro portal. Registrar
    # antes deixaria a trilha afirmando um pedido que talvez nunca tenha saído
    # daqui — e a trilha existe justamente para ser confiável.
    try:
        _pedir_instalacao_ao_invent(machine_id, token_raw, body.hostname, expires_at)
    except PonteRecusou as e:
        # Motivo curado pelo outro portal: "Erro interno" mandaria alguém ao
        # log por algo que se resolve na tela (token da ponte, máquina).
        logger.warning("Portal de inventário recusou o pedido: %s", e)
        raise HTTPException(
            status_code=502,
            detail=f"Não foi possível avisar o agente desta máquina: {e}",
        )
    except Exception:  # noqa: BLE001
        logger.exception("Falha ao pedir a instalação ao portal de inventário")
        raise HTTPException(
            status_code=502,
            detail="Não foi possível avisar o agente desta máquina. Veja o log do servidor.",
        )

    for cid in body.certificate_ids:
        cert_installer.log_event(
            event="SOLICITADO",
            user_id=user_id,
            user_email=token.email,
            token_id=token_id,
            certificate_id=cid,
            target_machine=machine_id,
            client_ip=client_ip,
        )

    return {
        "status": "ok",
        "machine_id": machine_id,
        # O ID do REGISTRO, nunca o token em si: e por ele que a tela acompanha
        # o desfecho. O token e a entrega da chave privada e nao volta para o
        # navegador — ver `/acompanhar`.
        "token_id": token_id,
        "expires_at": expires_at.isoformat() if expires_at else None,
        "validade_min": config.CERT_INSTALL_TOKEN_TTL_MIN,
    }


@app.get("/api/cert-installer/acompanhar/{token_id}")
def acompanhar_instalacao(
    token_id: str, token: auth.TokenData = Depends(require_auth)
) -> dict:
    """
    Em que pe esta aquele pedido de instalacao.

    Existe porque a tela mentia por omissao: dizia "Pedido enviado" e nunca mais
    voltava ao assunto. O desfecho ficava no `install_log` ou na janela do
    agente — dois lugares onde quem clicou nao esta.

    ── Escopo ────────────────────────────────────────────────────────────

    `user_email` do proprio requisitante, sempre. Um token de instalacao e a
    entrega de uma chave privada; saber o andamento do pedido de outra pessoa
    ja diz demais — quem, quando, para qual maquina.

    ── Desfechos ─────────────────────────────────────────────────────────

    `aguardando` cobre dois casos que a tela apresenta igual mas sao diferentes
    por dentro: o pedido acabou de sair, ou o agente ainda nao acordou. Nao
    distinguimos aqui de proposito — a pessoa nao pode fazer nada diferente num
    caso ou no outro, e um "o agente esta dormindo" so geraria ansiedade.

    `expirado` e outra coisa, e por isso e um desfecho proprio: ali existe algo a
    fazer — ligar a maquina e pedir de novo. Ver a secao abaixo.

    ── Maquina desligada = token morto ──────────────────────────────────

    O token vale minutos e o comando espera na fila. Quem clica e sai para
    almocar volta e encontra `failed`, sem explicacao. E, no intervalo entre o
    prazo acabar e a maquina acordar, o pedido ja esta morto enquanto a tela
    ainda diz "aguardando" — afirmando andamento onde nao ha mais nenhum.

    O prazo entra na resposta ANTES de a cadeia falhar, entao a tela para de
    esperar na hora certa em vez de descobrir pelo relato de erro do agente, que
    chega tarde ou nao chega. E uma falha JA registrada depois do prazo tambem
    sai como `expirado`: o motivo verdadeiro e o prazo, e "o portal recusou o
    token" mandaria alguem procurar defeito onde nao ha.
    """
    email = (token.email or "").strip().lower()
    if not email:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")

    prazo = cert_installer.prazo_do_token(str(token_id), email)
    expirado = bool(prazo and prazo.get("expirado") and not prazo.get("consumed_at"))
    expira_em = (prazo or {}).get("expires_at")

    def _resposta(desfecho: str, parou_em=None, detalhe: str = "") -> dict:
        return {
            "desfecho": desfecho,
            "parou_em": parou_em,
            "detalhe": detalhe,
            # A tela usa isto para se dar o prazo certo de espera em vez de
            # desistir num numero de tentativas escolhido a dedo — que era
            # menor que a validade do token e por isso desistia cedo demais.
            "expira_em": expira_em,
        }

    try:
        cadeias = cert_installer.cadeias_de_instalacao(user_email=email)
    except Exception:
        logger.exception("Falha ao consultar o andamento da instalação")
        # 200 com "desconhecido", e nao 500: a tela pergunta isto em laco, e um
        # erro faria a pessoa ver um alarme por causa de uma consulta que ela
        # nem sabe que existe. O certificado pode ter entrado.
        return _resposta("desconhecido")

    cadeia = next((c for c in cadeias if str(c.get("token_id")) == str(token_id)), None)
    if not cadeia:
        # Sem cadeia e com prazo vencido: o agente nunca chegou a tocar no
        # pedido. E o caso exato da maquina que ficou desligada.
        return _resposta("expirado" if expirado else "aguardando")

    desfecho = cadeia.get("desfecho") or "incompleto"
    eventos = cadeia.get("eventos") or []
    detalhe = ""
    for e in reversed(eventos):
        if e.get("detail"):
            detalhe = str(e["detail"])
            break

    if desfecho == "concluido":
        return _resposta("concluido", cadeia.get("parou_em"), detalhe)

    # `falhou` e `incompleto` viram `expirado` quando o prazo acabou sem consumo:
    # nos dois casos o que aconteceu foi o prazo, e o detalhe tecnico do agente
    # ("o portal recusou o token") mandaria procurar defeito onde nao ha.
    if expirado:
        return _resposta("expirado", cadeia.get("parou_em"), detalhe)

    return _resposta(
        "aguardando" if desfecho == "incompleto" else desfecho,
        cadeia.get("parou_em"),
        detalhe,
    )


class PonteRecusou(RuntimeError):
    """O portal de inventário respondeu, e disse não.

    O `detail` dele é texto do NOSSO outro portal, escrito para o operador
    ("CERT_PORTAL_TOKEN inválido", "máquina não encontrada"), e resolve na
    tela. É diferente de uma falha de rede ou de um proxy no caminho, cujo
    texto não é de ninguém de confiança — esse fica no log.
    """


def _pedir_instalacao_ao_invent(
    machine_id: str,
    token_raw: str,
    hostname: Optional[str],
    expira_em: Optional[datetime] = None,
) -> None:
    """
    Chama o portal de inventário, servidor a servidor.

    Levanta em qualquer desfecho que não seja sucesso: quem chama transforma em
    502 com o motivo. Silenciar aqui produziria a pior tela possível — "pedido
    enviado" para um agente que nunca vai receber nada.

    ── O prazo viaja junto ──────────────────────────────────────────────

    Sem ele, o outro portal não tem como saber que o comando morreu: o token é
    opaco do lado de lá, e a validade é configurável aqui (1 min a 24 h), então
    nenhum teto fixo adivinhado lá serviria. O efeito de não mandar é a máquina
    desligada acordar horas depois, tentar, ser recusada — e a trilha ganhar um
    ERRO que não é erro nenhum, no lugar onde ela é usada como prova.

    Opcional: um portal de inventário anterior a este campo simplesmente o
    ignora, e o comportamento volta a ser o de hoje.
    """
    import httpx

    r = httpx.post(
        f"{config.INVENT_API_URL}/api/agent-commands/instalar-certificado",
        headers={"Authorization": f"Bearer {config.CERT_PORTAL_TOKEN}"},
        json={
            "mac_address": machine_id,
            "token": token_raw,
            "hostname": hostname or None,
            "expira_em": expira_em.isoformat() if expira_em else None,
        },
        timeout=20.0,
    )
    if r.status_code != 200:
        detalhe = ""
        try:
            detalhe = str((r.json() or {}).get("detail") or "")
        except Exception:  # noqa: BLE001
            # Sem JSON não é o nosso portal falando (página de erro de proxy,
            # HTML): o texto cru não vai para a tela (achado #35), só o status.
            detalhe = ""
        raise PonteRecusou(detalhe or f"o portal de inventário respondeu {r.status_code}")


class RedeemRequest(BaseModel):
    """Payload enviado pelo agente para resgatar o bundle criptografado."""
    token: str
    clientPublicKey: str  # SPKI base64 (ECDH P-256)


@app.post("/api/cert-installer/redeem")
def redeem_install(
    body: RedeemRequest,
    request: Request,
    token: auth.TokenData = Depends(require_agent_or_admin),
):
    """
    Agente consome o token e recebe o bundle de certificados criptografado via ECDH.

    Só a máquina-alvo do token resgata (achado #21), e a chave compartilhada
    nunca: um token é a entrega da chave privada, e "qualquer agente" não é
    ninguém. A conferência vem ANTES do consumo, para o token sobrar para a
    máquina certa.
    """
    client_ip = request.client.host if request.client else None

    # 0. A máquina que pede é a máquina-alvo?
    alvo = cert_installer.alvo_do_token(body.token)
    if not alvo:
        raise HTTPException(status_code=403, detail="Token inválido, expirado ou já consumido")
    _machine_da_credencial(token, alvo.get("target_machine"), exigir_identidade=True)

    # 1. Validar e consumir token
    token_data = cert_installer.validate_and_consume_token(body.token)
    if not token_data:
        raise HTTPException(status_code=403, detail="Token inválido, expirado ou já consumido")

    user_id = token_data["user_id"]
    token_id = str(token_data["id"])
    cert_ids = token_data.get("certificate_ids") or []

    # 2. Log REDIMIDO
    cert_installer.log_event(
        event="REDIMIDO",
        user_id=user_id,
        user_email=token_data.get("user_email"),
        token_id=token_id,
        target_machine=token_data.get("target_machine"),
        client_ip=client_ip,
    )

    # 3. Montar bundle criptografado
    try:
        bundle = cert_installer.build_encrypted_bundle(
            certificate_ids=cert_ids,
            client_public_key_b64=body.clientPublicKey,
        )
        return bundle
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception:
        logger.exception("Erro ao montar bundle criptografado")
        raise HTTPException(status_code=500, detail="Erro interno ao montar bundle")


# ── Instalador avulso (modelo Ninite) ─────────────────────────────────────
#
# O agente resgata em /redeem autenticando-se com X-API-Key. O instalador que o
# usuário baixa não pode fazer o mesmo: embutir a API key no executável seria
# distribuí-la a todos que baixassem — e ela abre todas as rotas do agente.
#
# Aqui o próprio token É a credencial, como numa URL de download assinada. Isso
# se sustenta porque ele é de uso único (compare-and-swap em
# validate_and_consume_token), expira em CERT_INSTALL_TOKEN_TTL_MIN minutos, e
# só libera os certificate_ids gravados nele. O que falta a um bearer assim é
# resistência a força bruta, daí o limite por IP abaixo.

_CLAIM_JANELA_SEC = 60
_CLAIM_MAX_POR_JANELA = 10


def _ip_do_cliente(request: Request) -> str:
    """O IP de quem chama, atrás de `config.NUM_PROXIES_CONFIAVEIS` proxies.

    Contado a partir do FIM do X-Forwarded-For: cada proxy anexa o IP de quem
    falou com ele, então só os N últimos valores foram escritos por alguém de
    confiança. O primeiro valor é o que o cliente mandou — até o lote 1 da
    auditoria (24/09/2026) era ele que virava a chave do rate limit, e um
    `X-Forwarded-For: 1.2.3.<n>` novo a cada requisição tornava os tetos do
    login e do /claim decorativos (achado #6).

    Sem proxy configurado, ou com cabeçalho mais curto que a cadeia esperada
    (alguém forjou o cabeçalho sem passar por proxy nenhum), vale o socket.
    Antes de existir esta função os limites usavam `request.client.host`, que
    atrás do proxy é o PROXY — teto global compartilhado por todo mundo.
    """
    socket_ip = request.client.host if request.client else "desconhecido"
    n = int(getattr(config, "NUM_PROXIES_CONFIAVEIS", 0) or 0)
    if n <= 0:
        return socket_ip
    cadeia = [
        p.strip()
        for p in (request.headers.get("x-forwarded-for") or "").split(",")
        if p.strip()
    ]
    if len(cadeia) >= n:
        return cadeia[-n]
    return socket_ip


def _claim_rate_limit(ip: str) -> bool:
    """True se o IP ainda pode tentar.

    A janela vive no banco (`app/taxa.py`) desde o item 13 da Frente 2: em
    memória de processo, na Vercel, o teto valia POR INSTÂNCIA — cold starts
    diluíam o limite em "10 × quantas instâncias houver". Sem banco, o módulo
    degrada para a janela em memória (o comportamento antigo) e avisa no log.
    """
    return taxa.permitir(f"claim:{ip}", _CLAIM_MAX_POR_JANELA, _CLAIM_JANELA_SEC)


def _exigir_maquina_alvo_no_claim(request: Request, target_machine: Optional[str]) -> None:
    """Quem resgata é a máquina para a qual o token foi emitido (achado #21).

    Com `CLAIM_EXIGE_CREDENCIAL_DE_MAQUINA`: a X-API-Key precisa ser a
    credencial de máquina da estação-alvo. A chave compartilhada nunca serve —
    "qualquer agente" não é a máquina-alvo.

    Sem a flag (janela): o agente do INVENT ainda não apresenta credencial
    deste portal, então o resgate segue só com o token, mas um `X-Machine-Id`
    presente tem de casar com o alvo, e a ausência dele fica no log. É o que
    anula o roubo oportunista de token pela fila (#3) sem parar a instalação.
    """
    alvo = (target_machine or "").strip().lower()
    if config.CLAIM_EXIGE_CREDENCIAL_DE_MAQUINA:
        segredo = (request.headers.get("x-api-key") or "").strip()
        maquina = None
        if segredo and not (config.API_KEY and hmac.compare_digest(
            segredo.encode("utf-8"), config.API_KEY.encode("utf-8")
        )):
            try:
                maquina = machine_credentials.autenticar(segredo)
            except Exception:  # noqa: BLE001
                logger.exception("Credenciais de máquina indisponíveis no /claim")
                raise HTTPException(status_code=503, detail="Credenciais de máquina indisponíveis. Tente de novo.")
        propria = str((maquina or {}).get("machine_id") or "").strip().lower()
        if not propria or (alvo and propria != alvo):
            logger.warning("Resgate recusado: credencial de máquina ausente ou de outra estação (alvo %r).", alvo)
            raise HTTPException(status_code=403, detail="Token inválido, expirado ou já utilizado")
        return

    declarado = (request.headers.get("x-machine-id") or "").strip().lower()
    if not declarado:
        logger.warning(
            "Resgate de token sem identificação da máquina (alvo %r). O agente ainda não "
            "manda X-Machine-Id; janela do achado #21.", alvo,
        )
        return
    if alvo and declarado != alvo:
        logger.warning("Resgate recusado: X-Machine-Id %r não é a máquina-alvo %r.", declarado, alvo)
        raise HTTPException(status_code=403, detail="Token inválido, expirado ou já utilizado")


@app.post("/api/cert-installer/claim")
def claim_install(body: RedeemRequest, request: Request):
    """
    Resgate SEM API key: o token de uso único É a credencial.

    Nasceu para o instalador avulso e hoje serve o AGENTE, que chega na mesma
    condição — sem credencial neste portal, tendo só o token. O nome ficou; o
    público mudou.

    Deliberadamente não distingue token inválido de expirado ou já consumido:
    a resposta única evita virar oráculo de tokens válidos.
    """
    client_ip = _ip_do_cliente(request)

    if not _claim_rate_limit(client_ip):
        raise HTTPException(status_code=429, detail="Muitas tentativas. Aguarde um minuto.")

    # A máquina-alvo é conferida ANTES do consumo (achado #21): recusar depois
    # queimaria o token da máquina certa. Mesma resposta para tudo que não é
    # "a máquina-alvo com token válido", para não virar oráculo.
    alvo = cert_installer.alvo_do_token(body.token)
    if not alvo:
        raise HTTPException(status_code=403, detail="Token inválido, expirado ou já utilizado")
    _exigir_maquina_alvo_no_claim(request, alvo.get("target_machine"))

    token_data = cert_installer.validate_and_consume_token(body.token)
    if not token_data:
        raise HTTPException(status_code=403, detail="Token inválido, expirado ou já utilizado")

    cert_installer.log_event(
        event="REDIMIDO",
        user_id=token_data["user_id"],
        user_email=token_data.get("user_email"),
        token_id=str(token_data["id"]),
        target_machine=token_data.get("target_machine"),
        client_ip=client_ip,
        # Era "instalador avulso" ate 23/08/2026, e virou mentira quando o
        # download saiu: quem resgata agora e o agente da estacao. Numa
        # auditoria, esse campo responde "como esse certificado entrou?".
        detail="agente da estacao",
    )

    try:
        return cert_installer.build_encrypted_bundle(
            certificate_ids=token_data.get("certificate_ids") or [],
            client_public_key_b64=body.clientPublicKey,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:  # noqa: BLE001
        logger.exception("Erro ao montar bundle para o agente da estacao")
        # Chave errada no servidor é a causa que já aconteceu (20/09/2026) e a
        # única que vale nomear aqui: o texto vai parar no resultado do comando
        # no portal de inventário, que é onde o admin procura. O resto continua
        # genérico — o chamador é o agente, não o admin.
        detalhe = "Erro interno ao montar bundle"
        if type(e).__name__ == "InvalidTag":
            detalhe = (
                "O cofre não decifra com a chave configurada neste portal "
                "(CERT_ENCRYPTION_KEY). Confira em Instalador → Revalidar cofre."
            )
        raise HTTPException(status_code=500, detail=detalhe)


# O caminho de DOWNLOAD do instalador avulso saiu em 23/08/2026.
#
# `preparar-download` gerava o link e `/instalador/baixar/{token}` servia o
# .exe com o token no nome do arquivo. Enquanto nao havia agente nas
# estacoes, era a unica forma de alguem instalar um certificado.
#
# Agora ha: o agente do INVENT mora nas maquinas e instala na sessao da
# pessoa, com o portal so pedindo. Manter os dois caminhos significaria dois
# jeitos de emitir token de instalacao -- e token e a entrega da chave
# privada. O menos usado seria o menos observado.
#
# O que FICOU, e nao por descuido: `/claim` e `/report-avulso`. Elas nasceram
# para o .exe avulso, mas sao o caminho que o AGENTE usa -- ele tambem chega
# sem credencial neste portal, tendo so o token. Remove-las quebraria a
# instalacao que este commit torna a unica.

class InstallResultItem(BaseModel):
    certificateId: str
    fingerprint: Optional[str] = None
    thumbprint: Optional[str] = None
    status: str  # "OK" | "FALHA"
    detail: Optional[str] = None


class ReportRequest(BaseModel):
    """Payload enviado pelo agente após instalar os certificados."""
    token: str
    results: List[InstallResultItem]


@app.post("/api/cert-installer/report")
def report_install(
    body: ReportRequest,
    request: Request,
    _token: auth.TokenData = Depends(require_agent_or_admin),
):
    """
    Agente reporta o resultado da instalação de cada certificado.
    """
    return _registrar_relatorio(body, request)


@app.post("/api/cert-installer/report-avulso")
def report_install_avulso(body: ReportRequest, request: Request):
    """
    Mesma gravação, para quem resgata sem API key — hoje, o agente da estação.

    Abrir a rota não afeta o gate real: `_registrar_relatorio` já exigia um
    token conhecido E já redimido, o que a dependência de autenticação apenas
    duplicava. O pior que um token vazado permite aqui é sujar a auditoria da
    própria instalação que ele representa; não devolve material criptográfico.
    """
    ip = _ip_do_cliente(request)
    if not _claim_rate_limit(ip):
        raise HTTPException(status_code=429, detail="Muitas tentativas. Aguarde um minuto.")
    return _registrar_relatorio(body, request)


def _registrar_relatorio(body: ReportRequest, request: Request) -> dict:
    client_ip = request.client.host if request.client else None

    # Validar que o token existe e foi redimido (consumed_at != null)
    import hashlib
    token_hash = hashlib.sha256(body.token.encode()).hexdigest()
    from app.settings_state import _banco
    sb = _banco()
    if not sb:
        raise HTTPException(status_code=500, detail="Banco não configurado")

    try:
        r = sb.table("install_token").select("*").eq("token_hash", token_hash).execute()
        rows = r.data or []
        if not rows:
            raise HTTPException(status_code=403, detail="Token desconhecido")
        token_row = rows[0]
        if not token_row.get("consumed_at"):
            raise HTTPException(status_code=403, detail="Token ainda não foi redimido")
    except HTTPException:
        raise
    except Exception:
        logger.exception("Erro ao verificar token no report")
        raise HTTPException(status_code=500, detail="Erro interno")

    user_id = token_row["user_id"]
    token_id = str(token_row["id"])

    # Gravar log para cada resultado
    for result in body.results:
        event = "CONCLUIDO" if result.status.upper() == "OK" else "ERRO"
        cert_installer.log_event(
            event=event,
            user_id=user_id,
            user_email=token_row.get("user_email"),
            token_id=token_id,
            certificate_id=result.certificateId,
            fingerprint=result.fingerprint,
            target_machine=token_row.get("target_machine"),
            status=result.status,
            detail=result.detail,
            client_ip=client_ip,
        )

    return {
        "status": "ok",
        "processed": len(body.results),
    }


# ── Endpoints auxiliares do instalador ────────────────────────────────────

@app.get("/api/cert-installer/available")
def list_available_certificates(
    machine_id: Optional[str] = Query(None),
    token: auth.TokenData = Depends(require_modulo("instalador")),
):
    """Lista certificados PFX disponíveis para instalação (sem dados cifrados).

    Recortado pela carteira de quem pergunta (#32): a lista inteira do cofre
    — titular, documento, subject e id de cada certificado — saía para quem
    tivesse `instalador: ler`, concedível pela tela a qualquer papel.
    """
    certs = cert_installer.list_available_pfx(machine_id=machine_id)
    alcance = _documentos_ao_alcance(token)
    if alcance is not None:
        certs = [c for c in certs if cert_installer.so_digitos(c.documento) in alcance]
    return {
        "certificates": [
            {
                "id": c.id,
                "fingerprint": c.fingerprint,
                "machine_id": c.machine_id,
                "nome_titular": c.nome_titular,
                "documento": c.documento,
                "documento_tipo": c.documento_tipo,
                "subject": c.subject,
                "not_before": c.not_before,
                "not_after": c.not_after,
                "friendly_name": c.friendly_name,
                "uploaded_at": c.uploaded_at,
            }
            for c in certs
        ]
    }


@app.get("/api/cert-installer/logs")
def list_installer_logs(
    limit: int = Query(100, ge=1, le=500),
    token: auth.TokenData = Depends(require_modulo("instalador")),
):
    """Lista logs de auditoria de instalação.

    Escopado (#31): quem não tem alcance total vê só os próprios eventos, e
    sem `client_ip` — e-mail e IP dos colegas não são dado de operador.
    """
    if (token.role or "").strip().lower() in cert_installer.PAPEIS_COM_ALCANCE_TOTAL:
        return {"logs": cert_installer.list_install_logs(limit=limit)}
    uid = _user_id_da_sessao(token)
    if not uid:
        return {"logs": []}
    logs = cert_installer.list_install_logs(limit=limit, user_id=uid)
    return {"logs": [{k: v for k, v in l.items() if k != "client_ip"} for l in logs]}


@app.get("/api/cert-installer/trilha", dependencies=[Depends(require_modulo("instalador"))])
def trilha_de_instalacao(
    dias: int = Query(30, ge=1, le=365),
    user_email: Optional[str] = Query(None),
    apenas_falhas: bool = Query(False),
    limite: int = Query(500, ge=1, le=1000),
    token: auth.TokenData = Depends(require_auth),
) -> dict:
    """
    A trilha agrupada por token: uma linha por tentativa de instalação.

    Escopada (#31): sem alcance total, `user_email` é o da própria sessão —
    o parâmetro era filtro livre — e `client_ip` sai das cadeias.

    Substitui a lista plana, que mostrava eventos soltos em ordem cronológica.
    O que importa é **onde a cadeia quebrou** — e os números de produção
    mostram por quê: nove tentativas, seis mortas no mesmo ponto e pela mesma
    causa. Em fila, são 25 linhas sem forma.
    """
    admin = (token.role or "").strip().lower() in cert_installer.PAPEIS_COM_ALCANCE_TOTAL
    if not admin:
        user_email = (token.email or "").strip().lower() or "-"
    desde = (datetime.now(timezone.utc) - timedelta(days=dias)).isoformat()
    cadeias = cert_installer.cadeias_de_instalacao(
        limite=limite, desde=desde, user_email=user_email, apenas_com_falha=apenas_falhas
    )
    if not admin:
        for c in cadeias:
            c.pop("client_ip", None)
    # `target_machine` é o identificador da estação (o MAC que o agente
    # informa); o nome legível vem do cadastro de dispositivos, quando existe.
    nomes_maq: Dict[str, str] = {}
    try:
        for d in agent_devices.listar():
            mid = str(d.get("machine_id") or "")
            if mid and d.get("nome") and mid not in nomes_maq:
                nomes_maq[mid] = str(d["nome"])
    except Exception:  # noqa: BLE001 — sem nomes a trilha continua servindo
        logger.exception("Falha ao ler os nomes das estações para a trilha")
    for c in cadeias:
        c["target_nome"] = nomes_maq.get(str(c.get("target_machine") or ""), "")

    from app import texto as _texto
    resumo = cert_installer.resumo_das_cadeias(cadeias)
    total = int(resumo.get("total") or 0)
    concluidas = int(resumo.get("concluidas") or 0)
    resumo["textos"] = {
        "destaque": f"{concluidas} de {total}",
        "subtitulo": ("tentativa concluída" if total == 1 else "tentativas concluídas") + " no período",
    }
    return {
        "dias": dias,
        "desde": desde,
        "resumo": resumo,
        "cadeias": cadeias,
    }


@app.post("/api/cert-installer/cleanup")
def cleanup_tokens(token: auth.TokenData = Depends(require_modulo("instalador", permissoes.NIVEL_EDITAR))):
    """Remove tokens de instalação expirados (manutenção)."""
    count = cert_installer.cleanup_expired_tokens()
    return {"status": "ok", "removed": count}


def _resolve_user_id(email: str) -> Optional[str]:
    """Busca o UUID do usuário pelo email."""
    from app.settings_state import _banco
    sb = _banco()
    if not sb:
        return None
    try:
        r = sb.table("users").select("id").eq("email", email).limit(1).execute()
        if r.data:
            return str(r.data[0]["id"])
    except Exception:
        logger.exception("Erro ao resolver user_id para email=%s", email)
    return None


# ── Página HTML do Instalador ─────────────────────────────────────────────

@app.get("/instalador", response_class=HTMLResponse)
def page_instalador(request: Request) -> HTMLResponse:
    # Assinatura por keyword, igual às outras 8 rotas de página. A forma
    # posicional antiga — TemplateResponse(name, context) — quebra nesta versão
    # do Starlette com "TypeError: unhashable type: 'dict'", e a página do
    # módulo respondia 500 em toda requisição.
    # O nonce vem de request.state.nonce no template, como nos demais.
    # As abas são links (?aba=…): sem JavaScript a página abre já na aba
    # pedida; com JavaScript a troca é local e a URL acompanha.
    aba = request.query_params.get("aba") or "diagnostico"
    if aba not in ("diagnostico", "custodia", "trilha", "configuracao"):
        aba = "diagnostico"
    return templates.TemplateResponse(
        request=request, name="instalador.html", context={"pagina_ativa": "instalador", "aba": aba}
    )

