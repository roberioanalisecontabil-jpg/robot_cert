"""Instalador de certificados — Frente 3, leva 7 (10/10/2026).

Saiu de `app/main.py` sem mudar comportamento: o cofre (upload do agente,
custódia, recifrar, revalidar), o diagnóstico e a configuração do módulo, o
expurgo da trilha, e o fluxo de instalação inteiro — instalabilidade, a
estação da pessoa, prepare, acompanhar, redeem, claim, report — mais a
Entrada (Movimentos) e a Trilha. A página `/instalador` fica em `main.py`,
com as outras páginas.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app import agent_devices, auth, cert_installer, computadores, taxa
from app import entrada as entrada_certificados
from app.comum import ERRO_INTERNO_VEJA_LOG, _settings_dict
from app.rotas.computadores import _dispositivo_da_requisicao
from app.sessao import (
    _erro_sem_banco,
    _ip_do_cliente,
    _limitar,
    _machine_da_credencial,
    _user_id_da_sessao,
    require_admin,
    require_agent_or_admin,
    require_auth,
)
from app.settings_state import GravacaoNaoPersistida, load_settings, save_settings

logger = logging.getLogger("app.main")
router = APIRouter()


# ══════════════════════════════════════════════════════════════════════════
# MÓDULO INSTALADOR DE CERTIFICADOS DIGITAIS
# ══════════════════════════════════════════════════════════════════════════

class UploadPfxRequest(BaseModel):
    """Payload enviado pelo agente com o PFX cifrado em trânsito."""
    fingerprint: str = Field(max_length=64)
    machine_id: str = Field(default="default", max_length=128)
    # 1 MB de PFX em base64 (o teto real é conferido depois de decodificar).
    pfx_b64: str = Field(max_length=1_500_000)  # PFX em base64 (cifrado em trânsito via TLS)
    password: Optional[str] = Field(default=None, max_length=256)
    nome_titular: Optional[str] = Field(default=None, max_length=512)
    documento: Optional[str] = Field(default=None, max_length=64)
    documento_tipo: Optional[str] = Field(default=None, max_length=16)
    subject: Optional[str] = Field(default=None, max_length=2048)
    not_before: Optional[str] = Field(default=None, max_length=64)
    not_after: Optional[str] = Field(default=None, max_length=64)
    friendly_name: Optional[str] = Field(default=None, max_length=512)


@router.post("/api/cert-installer/upload-pfx")
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
    """Custódia por (servidor da varredura, fingerprint): o administrador a
    reativa (apaga o bloqueio) ou desativa (grava o bloqueio e apaga o PFX)."""
    fingerprint: str
    machine_id: str = "default"
    nome_titular: Optional[str] = None
    documento: Optional[str] = None


@router.get("/api/cert-installer/vault-optin")
def listar_vault_optin(
    machine_id: Optional[str] = Query(None),
    token: auth.TokenData = Depends(require_agent_or_admin),
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
            detail="machine_id é obrigatório: a custódia é por servidor da varredura.",
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


@router.post("/api/cert-installer/vault-optin", dependencies=[Depends(require_admin)])
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


@router.delete("/api/cert-installer/vault-optin/{fingerprint}", dependencies=[Depends(require_admin)])
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


class ConfigInstaladorBody(BaseModel):
    # `instalador_nome_template` saiu em 23/08/2026: ele nomeava o .exe que o
    # portal servia, e o portal nao serve mais .exe nenhum.
    install_token_ttl_min: int = 0
    trilha_retencao_dias: int = 0


@router.put("/api/cert-installer/configuracao", dependencies=[Depends(require_admin)])
def salvar_config_instalador(body: ConfigInstaladorBody) -> dict:
    """
    Grava **só** as duas configurações do módulo instalador (validade do
    pedido e retenção da trilha).

    Rota própria em vez de reaproveitar `PUT /api/settings`: aquele monta um
    `PortalSettings` inteiro a partir do corpo, então uma tela que mandasse
    apenas estes campos apagaria host, usuário e senha do SMTP — sem erro
    nenhum, e ninguém notaria até o próximo alerta não sair.

    Aqui a configuração atual é lida, dois campos mudam, e o resto vai de volta
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


@router.get("/api/cert-installer/expurgo-previa", dependencies=[Depends(require_admin)])
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


@router.post("/api/cert-installer/expurgar-log", dependencies=[Depends(require_admin)])
def expurgar_log_agora() -> dict:
    """
    Roda o expurgo DA TRILHA sob demanda, sem esperar o cron.

    Quem acabou de configurar a retenção precisa ver o efeito para confiar
    nela — e uma rotina de LGPD que só roda amanhã de manhã não dá para
    verificar antes de responder por ela.

    Só a trilha (decisão P3, 01/10/2026): a prévia conta a trilha, e o botão
    chama-se "Expurgar trilha". Até 30/09 ele também expurgava a atividade dos
    usuários e o cofre — uma surpresa num lugar onde surpresa custa caro. Os
    dois continuam no job diário (`cron_alerts`).
    """
    return {"install_log": cert_installer.expurgar_install_log()}


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
@router.get("/api/cert-installer/diagnostico", dependencies=[Depends(require_admin)])
def diagnostico_do_instalador() -> dict:
    """
    Estado do módulo instalador, num lugar só.

    Cada bloco corresponde a algo que já falhou em produção sem aviso:

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
        # Lote 8 (#42): a ajuda antiga ("confere de novo as senhas e chaves de
        # todos os certificados") dava a entender que o botão consertava o
        # cofre. Ele só PROVA; quem corrige é o Recifrar.
        "ajuda_revalidar": "Prova que as chaves em vigor decifram uma amostra de cada versão (PFX e senha). Não altera nada.",
        "ajuda_recifrar": (
            "Regrava os registros fora do estado em vigor com as chaves atuais e dados associados. "
            "Use depois de rotacionar uma chave; quando 'para recifrar' chegar a zero, a chave antiga pode sair do ambiente."
        ),
        "para_recifrar": k.get("linhas_para_recifrar") if not k.get("erro") else None,
    }
    if not c.get("erro") and c.get("sem_aad") and not k.get("exige_aad"):
        problemas.append(
            _texto.plural(c["sem_aad"], "registro no envelope antigo (sem dados associados)", "registros no envelope antigo (sem dados associados)")
            + ". Recifre o cofre e ligue COFRE_EXIGE_AAD."
        )
        out["situacao"] = "atencao" if out["situacao"] == "ok" else out["situacao"]
    sem_chave_senha = list((k.get("senha") or {}).get("versoes_sem_chave") or []) if not k.get("erro") else []
    if sem_chave_senha:
        problemas.append(
            "Versões da chave da SENHA sem chave configurada: " + ", ".join("v" + str(v) for v in sem_chave_senha)
            + ". Essas senhas estão indecifráveis agora; reponha CERT_PASSWORD_ENCRYPTION_KEY_V<n>."
        )
        out["situacao"] = "atencao" if out["situacao"] == "ok" else out["situacao"]
    return out


@router.post(
    "/api/cert-installer/recifrar-cofre",
    dependencies=[
        Depends(require_admin),
        # Decifra e regrava o cofre: três por dez minutos por identidade (#60).
        Depends(_limitar("recifrar", 3, 600)),
    ],
)
def recifrar_cofre() -> dict:
    """
    Completa uma rotação de chave (lote 8: #42, #19, #55).

    Regrava as linhas fora do estado em vigor — versão da chave do PFX, da
    chave da senha ou envelope sem AAD — decifrando com a versão gravada e
    cifrando com as em vigor. Linha que não decifra fica intocada e vem em
    `falhas`. Chame de novo enquanto `restantes` > 0.
    """
    try:
        return cert_installer.recifrar_cofre()
    except RuntimeError as e:
        logger.error("Recifra do cofre indisponível: %s", e)
        raise HTTPException(status_code=503, detail="O cofre está indisponível para recifrar. Veja o log do servidor.")
    except Exception:
        logger.exception("Falha ao recifrar o cofre")
        raise HTTPException(status_code=500, detail="Erro interno ao recifrar o cofre")


@router.post(
    "/api/cert-installer/revalidar-cofre",
    dependencies=[
        Depends(require_admin),
        # Decifra o cofre inteiro: três por dez minutos por identidade (#60).
        Depends(_limitar("revalidar", 3, 600)),
    ],
)
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


@router.get("/api/cert-installer/instalabilidade")
def instalabilidade(
    machine_id: str = Query(..., min_length=1),
    estacao: Optional[str] = Query(None, max_length=120),
    token: auth.TokenData = Depends(require_auth),
) -> dict:
    """
    O que **este** usuário pode instalar na estação dele, e o motivo de cada não.

    Alimenta a seleção do Início. Não é barreira — a barreira é
    `assegurar_carteira`, no momento de emitir o token. Isto existe para a tela
    não convidar o usuário a marcar o que o servidor vai recusar depois, com o
    erro chegando só na máquina dele.

    Dois identificadores, de propósito (revisão de 01/10/2026): `machine_id` é
    a máquina que VARREU os PFX (o snapshot e o cofre são dela — o servidor);
    `estacao` é a máquina da pessoa, onde o certificado vai ser instalado. Até
    30/09 a rota recebia um só, e para operador e gestor o vínculo
    pessoa↔estação era conferido contra o servidor da varredura — dava 403
    sempre que a ponte com o Hardlyze estava de pé. Sem `estacao`, o vínculo é
    conferido contra `machine_id`, como antes.
    """
    user_id = _user_id_da_sessao(token)
    if not user_id:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")
    # O mesmo alcance da leitura: admin tem tudo; Gestor, tudo menos as
    # Exceções; Operador, as Atribuições (`documentos_ao_alcance`, ADR 0001).
    try:
        alcance_total = cert_installer.documentos_ao_alcance(user_id, token.role) is None
    except (cert_installer.CustodiaIndisponivel, cert_installer.CarteiraIndisponivel) as e:
        logger.warning("Instalabilidade sem conseguir ler o alcance (%s): %s", machine_id, e)
        raise HTTPException(status_code=503, detail="Não foi possível verificar sua carteira. Tente de novo.")

    meu = _computador_autorizado_da_pessoa(user_id) if not alcance_total else None
    if meu and meu["autorizacao"] == computadores.AUTORIZADO:
        if computadores.mac(estacao or machine_id) != computadores.mac(meu["machine_id"]):
            raise HTTPException(status_code=403, detail="Esta estação não está vinculada a você.")
    elif not alcance_total and (estacao or "").strip():
        # A estação tem de ser a desta pessoa (achado #30). O vínculo mora
        # aqui desde 08/10/2026; sem computador autorizado, nenhuma estação.
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
        "estacao": estacao or machine_id,
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


def _computador_autorizado_da_pessoa(user_id: str) -> Optional[dict]:
    """A máquina ativa e autorizada da pessoa neste portal (None se não há ou sem tabela)."""
    try:
        c = computadores.computador_da_pessoa(user_id)
    except Exception:  # noqa: BLE001 — migration pendente: cai no caminho do Hardlyze
        logger.warning("Vínculos de computador indisponíveis; usando o Hardlyze", exc_info=True)
        return None
    return c


@router.get("/api/cert-installer/minha-estacao")
def minha_estacao(token: auth.TokenData = Depends(require_auth)) -> dict:
    """
    Há um agente vivo desta pessoa agora? Em qual máquina?

    O Início usa isto para mostrar (ou não) o botão "Instalar na estação" e
    dizer o motivo quando não há estação. Quem sabe a resposta é o Hardlyze: o
    vínculo pessoa↔estação nasce do login que ela mesma fez na máquina. Uma
    pessoa tem UMA estação: a atual, a que está com o agente vivo (decisão I2,
    01/10/2026); se trocar de máquina, a nova passa a ser a padrão.

    **Nunca levanta.** Uma indisponibilidade do outro portal não pode derrubar o
    Início — ela apenas faz o botão não aparecer, com o motivo na linha de
    status. Degradar é diferente de quebrar.
    """
    uid = _user_id_da_sessao(token)
    c = _computador_autorizado_da_pessoa(uid) if uid else None
    if c:
        if c["autorizacao"] != computadores.AUTORIZADO:
            return {"disponivel": False, "motivo": "aguardando_autorizacao" if c["autorizacao"] == computadores.PENDENTE
                    else "nao_vinculado", "dispositivos": [], "computador": c}
        if not c.get("vivo"):
            return {"disponivel": False, "motivo": "bandeja_parada", "dispositivos": [], "computador": c}
        return {"disponivel": True, "motivo": "", "canal": "portal", "computador": c,
                "dispositivos": [{"machine_id": c["machine_id"], "nome": c["nome"], "canal": "portal"}]}

    return {"disponivel": False, "motivo": "sem_computador", "dispositivos": []}

class PrepararInstalacaoRequest(BaseModel):
    """Instalar na máquina onde a pessoa está, pelo agente residente."""
    certificate_ids: List[str] = Field(max_length=MAX_CERTIFICADOS_POR_TOKEN)
    machine_id: str = Field(max_length=128)
    hostname: Optional[str] = Field(default=None, max_length=253)


def _exigir_maquina_autorizada(user_id: str, machine_id: str, e_admin: bool) -> None:
    """ADR 0002: instala só pela fila deste portal, em máquina com bandeja
    autorizada; operador e gestor, só na própria. O caminho antigo (comando
    pela fila do Hardlyze) foi cortado em 08/10/2026."""
    try:
        disp = computadores.dispositivo_da_maquina(machine_id)
        autorizado = bool(disp) and computadores.situacao(
            str(disp["user_id"]), machine_id)["autorizacao"] == computadores.AUTORIZADO
    except computadores.SemBanco as e:
        raise _erro_sem_banco(e)
    if not autorizado:
        raise HTTPException(
            status_code=409,
            detail=("A bandeja deste computador não está autorizada em Usuários › Computadores." if e_admin else
                    "Este computador não está autorizado para você. Entre na bandeja dele com sua conta "
                    "e aguarde a autorização do administrador."),
        )
    if not e_admin and str(disp["user_id"]) != str(user_id):
        raise HTTPException(status_code=403, detail="Esta estação não está vinculada a você.")


@router.post("/api/cert-installer/prepare")
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

    user_id = _user_id_da_sessao(token)
    if not user_id:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")

    _exigir_maquina_autorizada(user_id, machine_id, (token.role or "").strip().lower() == "admin")
    canal = "portal"

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
        computadores.enfileirar(machine_id, token_raw, token_id, expires_at)
    except Exception:  # noqa: BLE001
        logger.exception("Falha ao enfileirar a instalação")
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
        "canal": canal,
        "machine_id": machine_id,
        # O ID do REGISTRO, nunca o token em si: e por ele que a tela acompanha
        # o desfecho. O token e a entrega da chave privada e nao volta para o
        # navegador — ver `/acompanhar`.
        "token_id": token_id,
        "expires_at": expires_at.isoformat() if expires_at else None,
        "validade_min": cert_installer.ttl_do_token(),
    }


@router.get("/api/cert-installer/acompanhar/{token_id}")
def acompanhar_instalacao(
    token_id: str,
    # A tela pergunta em laço, e cada pergunta agrega a trilha inteira da
    # pessoa: 120 por minuto por identidade é folga para o laço da tela e
    # teto para quem o roda à mão (#60).
    token: auth.TokenData = Depends(_limitar("acompanhar", 120, 60)),
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


class RedeemRequest(BaseModel):
    """Payload enviado pelo agente para resgatar o bundle criptografado."""
    token: str = Field(max_length=256)
    clientPublicKey: str = Field(max_length=4096)  # SPKI base64 (ECDH P-256)


@router.post("/api/cert-installer/redeem")
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

    # Mesmo teto por IP do /claim gêmeo (#60): resgate é tentativa de token.
    if not _claim_rate_limit(_ip_do_cliente(request)):
        raise HTTPException(status_code=429, detail="Muitas tentativas. Aguarde um minuto.")

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




def _claim_rate_limit(ip: str) -> bool:
    """True se o IP ainda pode tentar.

    A janela vive no banco (`app/taxa.py`) desde o item 13 da Frente 2: em
    memória de processo, na Vercel, o teto valia POR INSTÂNCIA — cold starts
    diluíam o limite em "10 × quantas instâncias houver". Sem banco, o módulo
    degrada para a janela em memória (o comportamento antigo) e avisa no log.
    """
    return taxa.permitir(f"claim:{ip}", _CLAIM_MAX_POR_JANELA, _CLAIM_JANELA_SEC)


@router.post("/api/cert-installer/claim")
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
    if (request.headers.get("x-device-secret") or "").strip():
        # Bandeja nova (ADR 0002): o dispositivo tem de ser DA máquina-alvo e
        # estar autorizado. Resposta única para não virar oráculo.
        disp = _dispositivo_da_requisicao(request)
        mesma = computadores.mac(disp["machine_id"]) == computadores.mac(alvo.get("target_machine"))
        try:
            autorizado = computadores.situacao(str(disp["user_id"]), disp["machine_id"])["autorizacao"] == computadores.AUTORIZADO
        except computadores.SemBanco:
            autorizado = False
        if not (mesma and autorizado):
            logger.warning("Resgate recusado: dispositivo de %r sem vínculo autorizado com o alvo %r.",
                           disp.get("machine_id"), alvo.get("target_machine"))
            raise HTTPException(status_code=403, detail="Token inválido, expirado ou já utilizado")
    else:
        # Sem credencial da bandeja não há resgate (08/10/2026): o caminho
        # antigo, que resgatava só com o token, foi cortado.
        logger.warning("Resgate recusado: sem credencial da bandeja (alvo %r).", alvo.get("target_machine"))
        raise HTTPException(status_code=403, detail="Token inválido, expirado ou já utilizado")

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
    token: str = Field(max_length=256)
    results: List[InstallResultItem] = Field(max_length=200)


@router.post("/api/cert-installer/report")
def report_install(
    body: ReportRequest,
    request: Request,
    _token: auth.TokenData = Depends(require_agent_or_admin),
):
    """
    Agente reporta o resultado da instalação de cada certificado.
    """
    return _registrar_relatorio(body, request)


@router.post("/api/cert-installer/report-avulso")
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

# `available`, `logs` e `cleanup` sairam em 01/10/2026 (revisao da pagina
# Instalador): nenhuma tela, agente ou script os chamava. O agente continua
# com `claim`/`report`; a trilha agrupada e `cadeias_de_instalacao`.

@router.get("/api/cert-installer/entrada", dependencies=[Depends(require_admin)])
def entrada_de_certificados(
    dias: int = Query(30, ge=1, le=365),
    limite: int = Query(500, ge=1, le=1000),
) -> dict:
    """Instalador › Movimentos: as pendências abertas e os movimentos do período."""
    return entrada_certificados.listar(dias=dias, limite=limite)


@router.get("/api/cert-installer/trilha", dependencies=[Depends(require_admin)])
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

    # Qual certificado foi instalado (07/10/2026): os eventos guardam o id do
    # cofre; nome e documento vêm do cofre, sem trazer o PFX cifrado.
    ids = sorted({str(e.get("certificate_id")) for c in cadeias for e in (c.get("eventos") or []) if e.get("certificate_id")})
    titulares = cert_installer.titulares_do_cofre(ids)
    for c in cadeias:
        vistos = []
        for e in c.get("eventos") or []:
            t = titulares.get(str(e.get("certificate_id") or ""))
            if t and t not in vistos:
                vistos.append(t)
        c["certificados_info"] = vistos

    from app import texto as _texto
    resumo = cert_installer.resumo_das_cadeias(cadeias)
    total = int(resumo.get("total") or 0)
    concluidas = int(resumo.get("concluidas") or 0)
    resumo["textos"] = {
        "destaque": f"{concluidas} de {total}",
        "subtitulo": ("tentativa concluída" if total == 1 else "tentativas concluídas") + " no período",
    }
    # O teto de eventos (`limite`) corta em silêncio; a tela precisa dizer
    # "estas são as mais recentes" em vez de parecer completa.
    eventos = sum(len(c.get("eventos") or []) for c in cadeias)
    return {
        "dias": dias,
        "desde": desde,
        "resumo": resumo,
        "cadeias": cadeias,
        "truncado": eventos >= min(limite, 1000),
    }
