"""Rotas do agente: comandos, entrada, fila, dispositivos e credenciais de
máquina — Frente 3, leva 8 (12/10/2026).

Saiu de `app/main.py` sem mudar comportamento. O `/api/ingest` (inventário)
fica com os certificados, que é o que ele alimenta.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app import agent_devices, auth, computadores, config, machine_credentials, taxa
from app import entrada as entrada_certificados
from app.command_queue import COMMANDS, enqueue, list_pending, pop_next_for_agent
from app.rotas.computadores import _texto_da_situacao
from app.rotas.usuarios import _conferir_credenciais
from app.sessao import (
    _erro_sem_banco,
    _ip_do_cliente,
    _machine_da_credencial,
    _sb_do_login,
    _user_id_da_sessao,
    conta_ativa,
    require_admin,
    require_agent_or_admin,
    require_auth,
)

logger = logging.getLogger("app.main")
router = APIRouter()


class EntradaRelatorioBody(BaseModel):
    """O que o agente fez na pasta de entrada neste ciclo, e o que ficou lá."""
    machine_id: str = Field(default="default", max_length=128)
    eventos: List[dict] = Field(default_factory=list, max_length=5000)
    pendentes: List[dict] = Field(default_factory=list, max_length=5000)



class EnqueueCommandBody(BaseModel):
    machine_id: str = "default"
    command: str = Field(..., description="mover_vencidos | rescan | ping")



# Enfileirar comando para o agente e acao de operacao, e a unica chamadora e
# `configuracao.html` — pagina que so admin ve. Estava sob `require_auth`, que
# aceita QUALQUER autenticado: um operador comum podia mandar o servidor
# reescanear ou mover certificados. Ver docs/PLANO_niveis_de_acesso.md §1.
@router.post("/api/agent/commands", dependencies=[Depends(require_admin)])
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


@router.post("/api/agent/entrada")
def agent_entrada(
    body: EntradaRelatorioBody,
    token: auth.TokenData = Depends(require_agent_or_admin),
) -> dict:
    """
    O agente do servidor conta o que fez na pasta de entrada (02/10/2026):
    cada PFX renomeado e movido é um evento; o que não abriu e ficou lá é
    pendente. Pendente NOVO gera e-mail aos administradores; a lista inteira
    fica em Instalador › Entrada. Nenhum nome de arquivo com senha chega aqui:
    o agente já os limpou (`nome_publico_de_arquivo`).
    """
    # A estação só relata a própria pasta (auditoria de 10/10/2026): com o
    # `machine_id` do corpo, uma estação fechava as pendências de outra.
    declarado = _machine_da_credencial(token, body.machine_id)
    machine_id = (declarado or "default").strip()[:128] or "default"
    r = entrada_certificados.receber_relatorio(machine_id, body.eventos, body.pendentes)
    return {"ok": True, **r}


@router.get("/api/agent/next")
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


@router.get("/api/agent/queue", dependencies=[Depends(require_admin)])
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
    email: str = Field(max_length=320)
    password: str = Field(max_length=1024)
    machine_id: str = Field(max_length=128)
    nome: Optional[str] = Field(default=None, max_length=128)
    # Gerada pela bandeja 2.1.4 na instalação e guardada na estação (adendo ao
    # ADR 0002, 10/10/2026). Opcional: bandeja antiga não manda.
    chave_maquina: Optional[str] = Field(default=None, max_length=256)


class TokenDoDispositivoBody(BaseModel):
    segredo: str
    # Reportada pela estação, não medida pelo portal. Opcional porque um agente
    # anterior a esta coluna continua trocando token normalmente — exigir aqui
    # deixaria a frota velha sem acesso no deploy, que é o oposto do objetivo.
    versao: Optional[str] = None




@router.post("/api/agent/dispositivos/registrar")
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
    # E tetos por CONTA: por conta e endereço (10/5 min) e, acima dele, por
    # conta (50/5 min), que trocar de IP não contorna. Até a auditoria de
    # 10/10/2026 só existia o segundo, com 10: um anônimo que soubesse o e-mail
    # mandava 10 senhas erradas a cada 5 minutos e o dono nunca mais registrava
    # a bandeja. Agora trancar o dono exige vários endereços reais (o teto do
    # login segura cada um), e o de um endereço só tranca aquele endereço.
    email_alvo = (body.email or "").strip().lower()
    if not taxa.permitir(f"senha:{email_alvo}:{ip}", 10, 300) or not taxa.permitir(f"senha:{email_alvo}", 50, 300):
        raise HTTPException(status_code=429, detail="Muitas tentativas nesta conta. Aguarde alguns minutos.")

    user = _conferir_credenciais(body.email, body.password, ip)

    if bool(user.get("deve_trocar_senha")):
        raise HTTPException(
            status_code=403,
            detail="Troque a senha no portal antes de registrar o agente.",
            headers={"X-Senha-Provisoria": "1"},
        )

    machine_id = computadores.mac(body.machine_id)
    if not machine_id:
        raise HTTPException(status_code=400, detail="Informe a máquina do agente.")

    try:
        # ADR 0002: um acesso por vez e vínculo autorizado pelo administrador;
        # adendo de 10/10/2026: reconexão só com a chave da máquina.
        segredo, situacao = computadores.entrar(
            str(user["id"]), machine_id, body.nome or machine_id, body.chave_maquina
        )
    except (agent_devices.SemBanco, computadores.SemBanco) as e:
        raise _erro_sem_banco(e)
    except computadores.OutroDispositivo:
        raise HTTPException(
            status_code=409,
            detail="Já há um pedido para esta máquina vindo de outra estação. Peça ao administrador para recusá-lo.",
        )
    except Exception:
        logger.exception("Falha ao registrar dispositivo do agente")
        raise HTTPException(status_code=500, detail="Erro interno ao registrar o dispositivo.")

    if segredo is None:
        # Par autorizado que não provou a máquina: equipamento novo. Sem
        # segredo — a bandeja que está lá continua a dela.
        raise HTTPException(
            status_code=403,
            detail="Esta máquina precisa ser confirmada pelo administrador (Usuários › Computadores). "
                   "Entre de novo depois da aprovação.",
            headers={"X-Confirmacao-Pendente": "1"},
        )

    return {
        "segredo": segredo,
        "machine_id": machine_id,
        "email": user["email"],
        "role": user["role"],
        # O agente usa isto para renovar antes de expirar, em vez de descobrir
        # pelo 401 — que chegaria no meio de uma instalação.
        "validade_token_min": agent_devices.VALIDADE_TOKEN_MIN,
        **_texto_da_situacao(situacao),
    }


@router.post("/api/agent/dispositivos/token")
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


@router.get("/api/agent/dispositivos")
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


@router.delete("/api/agent/dispositivos/{device_id}")
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


@router.post("/api/agent/maquinas/provisionar")
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
    # Credencial de máquina só fala por si (auditoria de 10/10/2026): sem isto,
    # o segredo de UMA estação emitia credenciais para nomes novos, que
    # sobreviviam à revogação dela. Para a própria máquina, a linha já existe e
    # o 409 abaixo responde.
    mid = _machine_da_credencial(token, body.machine_id)
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


@router.get("/api/agent/maquinas", dependencies=[Depends(require_admin)])
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


@router.delete("/api/agent/maquinas/{machine_id}", dependencies=[Depends(require_admin)])
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


@router.post("/api/agent/maquinas/{machine_id}/reemitir", dependencies=[Depends(require_admin)])
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
