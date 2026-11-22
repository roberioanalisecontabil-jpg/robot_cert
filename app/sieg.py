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
from app.sieg_api import (PADROES, ClienteSieg, Credenciais, SiegErro, cadastro_ativo, instante, so_digitos,
                          validade_br, validade_confere)

logger = logging.getLogger(__name__)

INCLUINDO, NO_SIEG, ERRO, SUBSTITUIDO, REMOVIDO = "incluindo", "no_sieg", "erro", "substituido", "removido"
# Ligado = o interruptor não volta. "erro" fica ligado (a pessoa pediu) e
# oferece "Tentar de novo"; "removido" volta a poder ser ligado.
LIGADOS = (INCLUINDO, NO_SIEG, ERRO, SUBSTITUIDO)
# Um "incluindo" mais velho que isto foi interrompido (o processo caiu).
INCLUINDO_EXPIRA = timedelta(minutes=15)
# Quem aparece na trilha quando o portal troca sozinho (conferir_e_trocar).
POR_AUTOMATICO = "troca automática"
# A troca automática que deu erro só tenta de novo depois disto.
ERRO_ESPERA = timedelta(hours=24)
# Mais que esta fração dos "No SIEG" saindo de uma vez = listagem suspeita.
FORA_SUSPEITO = 0.2

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
                validade=item.get("not_after"),
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


def reconciliar(fp: str, settings: Any, por: str, http=None, not_after: Any = None) -> Dict[str, Any]:
    """Administrador: confere no SIEG. Ativo com ESTE certificado → mantém;
    ativo com outro (DataExpira diferente da validade) ou fora → removido."""
    client = _banco()
    atual = estado(fp)
    if not atual:
        raise LookupError("Este certificado nunca foi ligado ao SIEG.")
    situacao, item = cliente(settings, http=http).situacao(atual["documento"])
    sieg_id = str((item or {}).get("Id") or "")
    if situacao == "ativo" and validade_confere(not_after, (item or {}).get("DataExpira")) is False:
        novo = REMOVIDO
        msg = "O SIEG está com outro certificado (vence em " + validade_br(item.get("DataExpira")) + ")."
        _gravar_estado(client, fp, estado=REMOVIDO, mensagem=msg + " Pode ser ligado de novo.")
        evento = "reconciliado_desligado"
    elif situacao == "ativo":
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


def _vigentes(itens: List[Dict[str, Any]], settings: Any) -> Dict[str, Dict[str, Any]]:
    """Documento → o certificado válido e legível de vencimento mais distante."""
    vigentes: Dict[str, Dict[str, Any]] = {}
    for it in itens:
        if motivo_para_nao_ligar(it, None, settings) in ("vencido", "ilegivel"):
            continue
        doc = so_digitos(it.get("documento_numero"))
        if not doc:
            continue
        if doc not in vigentes or str(it.get("not_after") or "") > str(vigentes[doc].get("not_after") or ""):
            vigentes[doc] = it
    return vigentes


def _ativo(cads: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    return next((c for c in cads if cadastro_ativo(c)), None)


def sincronizar(itens: List[Dict[str, Any]], settings: Any, por: str, http=None) -> Dict[str, int]:
    """Marca "No SIEG" o certificado que o SIEG de fato tem em cada cliente.

    Só cria linha onde não há nenhuma (não mexe em pedido nem em erro). Qual
    certificado: o que tem a validade do DataExpira da listagem; sem a data,
    o vigente do documento (o de vencimento mais distante entre os válidos).
    Até 22/11/2026 era sempre o vigente, e 11 clientes ficaram "No SIEG" com
    o SIEG ainda no certificado antigo.
    """
    client = _banco()
    cadastros = cliente(settings, http=http).cadastros()
    no_sieg = {doc: _ativo(cads) for doc, cads in cadastros.items() if _ativo(cads)}
    vigentes = _vigentes(itens, settings)
    ja = estados(None)
    marcados = 0
    for doc, cad in no_sieg.items():
        expira = cad.get("DataExpira")
        if expira:
            it = next((i for i in itens if so_digitos(i.get("documento_numero")) == doc and i.get("fingerprint_sha256")
                       and validade_confere(i.get("not_after"), expira)), None)
        else:
            it = vigentes.get(doc)
        if not it:
            continue
        fp = str(it["fingerprint_sha256"]).lower()
        if fp in ja:
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


def _erro_recente(e: Dict[str, Any]) -> bool:
    try:
        quando = datetime.fromisoformat(str(e.get("atualizado_em") or "").replace("Z", "+00:00"))
    except ValueError:
        return False
    return _agora() - quando < ERRO_ESPERA


def conferir_e_trocar(itens: List[Dict[str, Any]], settings: Any, por: str = POR_AUTOMATICO,
                      http=None) -> Dict[str, int]:
    """Ciclo periódico (app/main.py): confere e troca pelo certificado mais novo.

    1. Conferir: certificado "No SIEG" cujo cadastro ativo tem outra validade
       (DataExpira) passa a "Fora do SIEG", com a validade do que está lá; o
       de cliente excluído ou inativo no SIEG também. Listagem vazia ou que
       tiraria mais de FORA_SUSPEITO de uma vez não tira ninguém.
    2. Trocar: cliente ativo no SIEG com um certificado mais novo no portal,
       válido, legível e no cofre, recebe o novo (decisão de 22/11/2026:
       logo que o novo chega). Erro recente não repete antes de ERRO_ESPERA.
    """
    client = _banco()
    cadastros = cliente(settings, http=http).cadastros()
    ativos = {doc: _ativo(cads) for doc, cads in cadastros.items() if _ativo(cads)}
    por_fp = {str(i.get("fingerprint_sha256") or "").lower(): i for i in itens if i.get("fingerprint_sha256")}
    divergentes = fora = 0
    no_sieg = [(fp, e) for fp, e in estados(None).items() if e["estado"] == NO_SIEG]
    sairiam = []
    for fp, e in no_sieg:
        cad = ativos.get(e["documento"])
        if not cad:
            msg = "Inativo no SIEG." if cadastros.get(e["documento"]) else "Não existe no SIEG."
            sairiam.append((fp, e, msg))
            continue
        it = por_fp.get(fp)
        if it and validade_confere(it.get("not_after"), cad.get("DataExpira")) is False:
            msg = "O SIEG está com outro certificado (vence em " + validade_br(cad.get("DataExpira")) + ")."
            _gravar_estado(client, fp, estado=REMOVIDO, mensagem=msg + " Pode ser ligado de novo.")
            _trilhar(client, fp=fp, documento=e["documento"], nome=e.get("nome", ""), evento="conferido_divergente",
                     por=por, mensagem=msg)
            divergentes += 1
    if sairiam and (not ativos or len(sairiam) > len(no_sieg) * FORA_SUSPEITO):
        logger.warning("SIEG: %s de %s certificados sairiam do SIEG de uma vez; listagem suspeita, ninguém marcado.",
                       len(sairiam), len(no_sieg))
        sairiam = []
    for fp, e, msg in sairiam:
        _gravar_estado(client, fp, estado=REMOVIDO, mensagem=msg + " Pode ser ligado de novo.")
        _trilhar(client, fp=fp, documento=e["documento"], nome=e.get("nome", ""), evento="conferido_fora",
                 por=por, mensagem=msg)
        fora += 1

    no_cofre = {str(l.get("fingerprint") or "").lower()
                for l in (client.table("cert_pfx_store").select("fingerprint").execute().data or [])}
    atual = estados(None)
    trocados = falhas = 0
    for doc, it in _vigentes(itens, settings).items():
        cad = ativos.get(doc)
        fp = str(it["fingerprint_sha256"]).lower()
        if not cad or fp not in no_cofre or not cad.get("DataExpira"):
            continue
        if validade_confere(it.get("not_after"), cad["DataExpira"]) is not False:
            continue  # o SIEG já está com ele
        if instante(it.get("not_after")) <= instante(cad["DataExpira"]):
            continue  # o do SIEG é o mais novo
        e = atual.get(fp)
        if e and (e["estado"] == INCLUINDO or (e["estado"] == ERRO and _erro_recente(e))):
            continue
        solicitar(it, por)
        r = executar(it, settings, por, http=http)
        if r.get("estado") == NO_SIEG:
            trocados += 1
        else:
            falhas += 1
    if divergentes or fora or trocados or falhas:
        logger.info("SIEG: %s divergente(s), %s fora, %s trocado(s), %s falha(s)", divergentes, fora, trocados, falhas)
    return {"divergentes": divergentes, "fora": fora, "trocados": trocados, "falhas": falhas}
