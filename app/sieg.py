"""Inclusão de certificado no SIEG — estado, trilha e execução (07/10/2026).

Decisões em docs/modal-detalhes-e-sieg.md. Em resumo:

* Um estado por CERTIFICADO (fingerprint) em `sieg_inclusao`: incluindo,
  no_sieg, erro, substituido (o certificado novo do mesmo CNPJ entrou) ou
  removido (a reconciliação do administrador não achou no SIEG). Ninguém
  desliga; só a reconciliação devolve a "removido", e aí pode religar.
* A inclusão roda no PORTAL, com o PFX e a senha do cofre (que o agente
  alimenta com a pasta do ANALISESRV), em segundo plano: a rota grava
  "incluindo" e responde; `executar` chama a API e grava o resultado.
* Cada tentativa vai à `sieg_trilha` com operação, HTTP, mensagem da API,
  opções desligadas e avisos — e ao log do servidor. Nunca senha, PFX,
  credencial ou token.

A autorização (alcance da carteira, administrador) fica nas rotas de
app/main.py; aqui entra o que já foi autorizado.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional

from app import cert_installer
from app.sieg_api import PADROES, ClienteSieg, Credenciais, SiegErro, so_digitos

logger = logging.getLogger(__name__)

INCLUINDO, NO_SIEG, ERRO, SUBSTITUIDO, REMOVIDO = "incluindo", "no_sieg", "erro", "substituido", "removido"
# Ligado = o interruptor não volta. "erro" fica ligado (a pessoa pediu) e
# oferece "Tentar de novo"; "removido" volta a poder ser ligado.
LIGADOS = (INCLUINDO, NO_SIEG, ERRO, SUBSTITUIDO)
# Um "incluindo" mais velho que isto foi interrompido (o processo caiu).
INCLUINDO_EXPIRA = timedelta(minutes=15)

ROTULOS = {
    INCLUINDO: "Incluindo…",
    NO_SIEG: "No SIEG",
    ERRO: "Erro",
    SUBSTITUIDO: "Substituído",
    REMOVIDO: "Fora do SIEG",
}

# Por que o interruptor não liga (o texto vai à tela).
MOTIVOS = {
    "vencido": "Certificado vencido não vai ao SIEG.",
    "ilegivel": "Certificado ilegível (senha ou arquivo): o SIEG recusaria.",
    "nao_enviado": "Ainda não enviado ao cofre do portal: o agente envia no próximo ciclo.",
    "sem_credenciais": "O SIEG ainda não foi configurado (Configuração › SIEG).",
}


class SiegIndisponivel(RuntimeError):
    """O banco não respondeu: nada foi gravado."""


def _banco():
    from app.settings_state import _banco as _sb

    return _sb()


def _agora() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


# ── Configuração ─────────────────────────────────────────────────────────

def padroes(settings: Any) -> Dict[str, Any]:
    """Padrões gravados sobre os do código (campo vazio ou JSON torto = código)."""
    try:
        gravados = json.loads(settings.sieg_padroes) if settings.sieg_padroes else {}
    except (TypeError, ValueError):
        gravados = {}
    return {**PADROES, **{k: v for k, v in (gravados or {}).items() if k in PADROES}}


def credenciais(settings: Any) -> Optional[Credenciais]:
    from app.smtp_service import decrypt_password

    secret = decrypt_password(settings.sieg_secret_key_encrypted) if settings.sieg_secret_key_encrypted else ""
    api_key = decrypt_password(settings.sieg_api_key_encrypted) if settings.sieg_api_key_encrypted else ""
    if not (settings.sieg_client_id and secret and api_key):
        return None
    return Credenciais(settings.sieg_client_id, secret, api_key)


def configurado(settings: Any) -> bool:
    return bool(settings.sieg_client_id and settings.sieg_secret_key_encrypted and settings.sieg_api_key_encrypted)


def cliente(settings: Any, http=None) -> ClienteSieg:
    cred = credenciais(settings)
    if cred is None:
        raise SiegErro(MOTIVOS["sem_credenciais"])
    return ClienteSieg(cred, http=http)


# ── Leitura ──────────────────────────────────────────────────────────────

def _normalizar(linha: Dict[str, Any]) -> Dict[str, Any]:
    """"incluindo" velho demais vira erro: o processo caiu no meio."""
    out = dict(linha)
    if out.get("estado") == INCLUINDO:
        try:
            quando = datetime.fromisoformat(str(out.get("atualizado_em")).replace("Z", "+00:00"))
        except ValueError:
            quando = None
        if quando and _agora() - quando > INCLUINDO_EXPIRA:
            out["estado"] = ERRO
            out["mensagem"] = "A inclusão foi interrompida (o portal reiniciou?). Tente de novo."
    out["rotulo"] = ROTULOS.get(out.get("estado"), out.get("estado"))
    out["ligado"] = out.get("estado") in LIGADOS
    return out


def estados(fingerprints: Optional[Iterable[str]] = None) -> Dict[str, Dict[str, Any]]:
    """fingerprint → linha de `sieg_inclusao` (com rotulo/ligado). Sem banco: vazio."""
    client = _banco()
    if not client:
        return {}
    try:
        q = client.table("sieg_inclusao").select("*")
        fps = sorted({f.lower() for f in fingerprints or [] if f}) if fingerprints is not None else None
        if fps is not None:
            if not fps:
                return {}
            q = q.in_("fingerprint", fps)
        linhas = q.execute().data or []
    except Exception:  # noqa: BLE001 — sem a tabela (migration não rodou) a tela segue sem selo
        logger.exception("Falha ao ler sieg_inclusao")
        return {}
    return {str(l["fingerprint"]).lower(): _normalizar(l) for l in linhas}


def estado(fingerprint: str) -> Optional[Dict[str, Any]]:
    return estados([fingerprint]).get(fingerprint.lower())


def trilha(fingerprint: Optional[str] = None, limite: int = 200) -> List[Dict[str, Any]]:
    client = _banco()
    if not client:
        return []
    q = client.table("sieg_trilha").select("*")
    if fingerprint:
        q = q.eq("fingerprint", fingerprint.lower())
    return q.order("em", desc=True).limit(limite).execute().data or []


def motivo_para_nao_ligar(item: Dict[str, Any], no_cofre: Optional[bool], settings: Any) -> Optional[str]:
    """Chave de MOTIVOS, ou None se o interruptor pode ser ligado."""
    status = str(item.get("status") or "").lower()
    vence = item.get("not_after")
    vencido_pela_data = False
    if vence:
        try:
            vencido_pela_data = datetime.fromisoformat(str(vence).replace("Z", "+00:00")) < _agora()
        except ValueError:
            pass
    if status in ("expirado", "vencido") or vencido_pela_data:
        return "vencido"
    if status in ("erro", "fora_do_padrao") or not item.get("fingerprint_sha256"):
        return "ilegivel"
    if no_cofre is False:
        return "nao_enviado"
    if not configurado(settings):
        return "sem_credenciais"
    return None


# ── Escrita ──────────────────────────────────────────────────────────────

def _trilhar(client, *, fp: str, documento: str, nome: str, evento: str, por: str,
             operacao: str = "", http_status: Optional[int] = None, mensagem: str = "",
             opcoes: Iterable[str] = (), avisos: Iterable[str] = (), sieg_id: str = "") -> None:
    client.table("sieg_trilha").insert({
        "fingerprint": fp, "documento": documento, "nome": nome, "evento": evento,
        "operacao": operacao, "http_status": http_status, "mensagem": (mensagem or "")[:2000],
        "opcoes_desabilitadas": "; ".join(opcoes), "avisos": "; ".join(avisos)[:2000],
        "sieg_id": sieg_id or "", "por": por, "em": _iso(_agora()),
    }).execute()


def _gravar_estado(client, fp: str, **campos: Any) -> None:
    campos["atualizado_em"] = _iso(_agora())
    client.table("sieg_inclusao").update(campos).eq("fingerprint", fp).execute()


def solicitar(item: Dict[str, Any], por: str) -> Dict[str, Any]:
    """Grava "incluindo" (e a trilha). Quem chama agenda `executar` depois.

    Devolve o estado gravado. Já ligado e não em erro = nada a fazer
    (o interruptor não liga duas vezes); `erro` e `removido` religam.
    """
    client = _banco()
    if not client:
        raise SiegIndisponivel("Sem banco: o pedido não seria guardado.")
    fp = str(item["fingerprint_sha256"]).lower()
    documento = so_digitos(item.get("documento_numero"))
    nome = str(item.get("nome") or item.get("display_name") or "")
    atual = estado(fp)
    if atual and atual["estado"] in (INCLUINDO, NO_SIEG, SUBSTITUIDO):
        return atual
    agora = _iso(_agora())
    linha = {
        "fingerprint": fp, "documento": documento, "nome": nome, "estado": INCLUINDO,
        "solicitado_por": por, "solicitado_em": agora, "atualizado_em": agora,
        "mensagem": "", "substituido_por": "",
    }
    try:
        if atual:
            # Religar (erro → de novo; removido → de novo) mantém quem pediu
            # primeiro? Não: quem religa é quem responde por esta tentativa.
            client.table("sieg_inclusao").update(linha).eq("fingerprint", fp).execute()
        else:
            client.table("sieg_inclusao").insert({**linha, "sieg_id": ""}).execute()
        _trilhar(client, fp=fp, documento=documento, nome=nome, por=por,
                 evento="religado" if atual else "solicitado")
    except Exception as e:  # noqa: BLE001
        logger.exception("Falha ao gravar o pedido de inclusão no SIEG")
        raise SiegIndisponivel(str(e)) from e
    logger.info("SIEG: inclusão pedida por %s para %s (%s)", por, documento, fp[:12])
    return _normalizar(linha)


def _linha_do_cofre(fp: str, machine_id: Optional[str]) -> Optional[Dict[str, Any]]:
    client = _banco()
    linhas = client.table("cert_pfx_store").select("*").eq("fingerprint", fp).execute().data or []
    if machine_id:
        da_maquina = [l for l in linhas if l.get("machine_id") == machine_id]
        linhas = da_maquina or linhas
    return linhas[0] if linhas else None


def executar(item: Dict[str, Any], settings: Any, por: str, *, machine_id: Optional[str] = None,
             http=None) -> Dict[str, Any]:
    """Faz a inclusão (segundo plano) e grava o resultado. Nunca levanta."""
    client = _banco()
    fp = str(item["fingerprint_sha256"]).lower()
    documento = so_digitos(item.get("documento_numero"))
    nome = str(item.get("nome") or item.get("display_name") or "")

    def falhar(mensagem: str, **kw: Any) -> Dict[str, Any]:
        logger.warning("SIEG: inclusão de %s falhou: %s", documento, mensagem)
        _gravar_estado(client, fp, estado=ERRO, mensagem=mensagem[:2000])
        _trilhar(client, fp=fp, documento=documento, nome=nome, evento="erro", por=por, mensagem=mensagem, **kw)
        return {"estado": ERRO, "mensagem": mensagem}

    try:
        linha = _linha_do_cofre(fp, machine_id)
        if not linha:
            return falhar(MOTIVOS["nao_enviado"])
        try:
            pfx = cert_installer.decifrar_pfx_da_linha(linha)
            senha = cert_installer.decifrar_senha_da_linha(linha)
        except Exception as e:  # noqa: BLE001
            return falhar("Não foi possível abrir o certificado do cofre: "
                          + (cert_installer.descrever_falha_de_decifra(e) or e.__class__.__name__))
        if not senha:
            return falhar("O cofre não tem a senha deste certificado.")
        try:
            r = cliente(settings, http=http).incluir(
                nome=nome, documento=documento, pfx=pfx, senha=senha, padroes=padroes(settings),
                tipo="P12" if str(item.get("nome_publico") or "").lower().endswith(".p12") else "Pfx",
            )
        except SiegErro as e:
            return falhar(str(e), http_status=e.status)

        kw = dict(operacao=r.operacao, http_status=r.status, opcoes=r.opcoes_desabilitadas,
                  avisos=r.avisos, sieg_id=r.certificado_id)
        if not r.ok:
            return falhar(r.mensagem, **kw)
        _gravar_estado(client, fp, estado=NO_SIEG, sieg_id=r.certificado_id, mensagem=r.mensagem[:2000])
        _trilhar(client, fp=fp, documento=documento, nome=nome, evento="incluido", por=por,
                 mensagem=r.mensagem, **kw)
        _substituir_anteriores(client, fp, documento, nome, por)
        logger.info("SIEG: %s incluído (%s, Id %s)", documento, r.operacao, r.certificado_id)
        return {"estado": NO_SIEG, "sieg_id": r.certificado_id, "mensagem": r.mensagem}
    except Exception as e:  # noqa: BLE001 — segundo plano: o erro vai à trilha, não some
        logger.exception("SIEG: falha inesperada na inclusão de %s", documento)
        try:
            return falhar(f"Falha inesperada: {e.__class__.__name__}")
        except Exception:  # noqa: BLE001
            return {"estado": ERRO, "mensagem": "Falha inesperada"}


def _substituir_anteriores(client, fp: str, documento: str, nome: str, por: str) -> None:
    """Renovação: o cadastro do CNPJ no SIEG agora é deste certificado."""
    antigos = (client.table("sieg_inclusao").select("*").eq("documento", documento).execute().data or [])
    for a in antigos:
        if a["fingerprint"] == fp or a.get("estado") not in (NO_SIEG, ERRO):
            continue
        _gravar_estado(client, a["fingerprint"], estado=SUBSTITUIDO, substituido_por=fp,
                       mensagem="Substituído pelo certificado novo deste cliente.")
        _trilhar(client, fp=a["fingerprint"], documento=documento, nome=a.get("nome") or nome,
                 evento="substituido", por=por, mensagem=f"Substituído por {fp[:12]}…")


def reconciliar(fp: str, settings: Any, por: str, http=None) -> Dict[str, Any]:
    """Administrador: confere no SIEG. Ativo → mantém; senão → removido."""
    client = _banco()
    atual = estado(fp)
    if not atual:
        raise LookupError("Este certificado nunca foi ligado ao SIEG.")
    situacao, item = cliente(settings, http=http).situacao(atual["documento"])
    sieg_id = str((item or {}).get("Id") or "")
    if situacao == "ativo":
        novo = NO_SIEG if atual["estado"] in (ERRO, REMOVIDO, INCLUINDO) else atual["estado"]
        _gravar_estado(client, fp, estado=novo, sieg_id=sieg_id or atual.get("sieg_id", ""),
                       mensagem="Conferido no SIEG: ativo.")
        evento, msg = "reconciliado_mantido", f"Ativo no SIEG (Id {sieg_id})."
    else:
        novo = REMOVIDO
        msg = "Inativo no SIEG." if situacao == "inativo" else "Não existe no SIEG."
        _gravar_estado(client, fp, estado=REMOVIDO, mensagem=msg + " Pode ser ligado de novo.")
        evento = "reconciliado_desligado"
    _trilhar(client, fp=fp, documento=atual["documento"], nome=atual.get("nome", ""), evento=evento,
             por=por, mensagem=msg, sieg_id=sieg_id)
    return {"estado": novo, "situacao": situacao, "mensagem": msg}


def sincronizar(itens: List[Dict[str, Any]], settings: Any, por: str, http=None) -> Dict[str, int]:
    """Marca "No SIEG" o certificado vigente de cada cliente que já está lá.

    Só cria linha onde não há nenhuma (não mexe em pedido nem em erro), e só
    para o certificado vigente do documento (o de vencimento mais distante
    entre os válidos), que é o que o SIEG deve estar usando.
    """
    client = _banco()
    no_sieg = {doc for doc, cads in cliente(settings, http=http).cadastros().items()
               if any(c.get("Ativo") is True or c.get("_listado_como_ativo") is True for c in cads)}
    vigentes: Dict[str, Dict[str, Any]] = {}
    for it in itens:
        if motivo_para_nao_ligar(it, None, settings) in ("vencido", "ilegivel"):
            continue
        doc = so_digitos(it.get("documento_numero"))
        if not doc:
            continue
        if doc not in vigentes or str(it.get("not_after") or "") > str(vigentes[doc].get("not_after") or ""):
            vigentes[doc] = it
    ja = estados(None)
    marcados = 0
    for doc, it in vigentes.items():
        fp = str(it["fingerprint_sha256"]).lower()
        if doc not in no_sieg or fp in ja:
            continue
        agora = _iso(_agora())
        client.table("sieg_inclusao").insert({
            "fingerprint": fp, "documento": doc, "nome": str(it.get("nome") or ""), "estado": NO_SIEG,
            "sieg_id": "", "solicitado_por": por, "solicitado_em": agora, "atualizado_em": agora,
            "substituido_por": "", "mensagem": "Já estava no SIEG (sincronização).",
        }).execute()
        _trilhar(client, fp=fp, documento=doc, nome=str(it.get("nome") or ""), evento="sincronizado", por=por,
                 mensagem="Já estava no SIEG.")
        marcados += 1
    return {"clientes_no_sieg": len(no_sieg), "marcados": marcados}
