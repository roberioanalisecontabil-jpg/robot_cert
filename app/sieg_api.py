"""Cliente da API do SIEG (api.sieg.com) — inclusão de certificado A1.

Portado em 07/10/2026 do script que o usuário validou contra a API
(`instalar_certificados.py`, execuções de 06/10/2026), mantendo o que ele
aprendeu na prática:

* Autenticação: POST /api/v1/create-jwt com X-Client-Id / X-Secret-Key dá um
  JWT; toda chamada /api/v1 leva `Authorization: Bearer` E `X-Api-Key` (a
  chave da conta, diferente do Secret Key).
* A API já respondeu "registrado com sucesso" sem cadastrar (06/10, 11:56):
  depois de registrar, o cadastro é CONFERIDO na listagem.
* CNPJ que já existe (renovação, procuração, cadastro inativo): troca só o
  arquivo em /editar e, se inativo, reativa em /habilitar.
* Cadastro excluído logicamente (`Deletado=true`) volta por /habilitar.
* Opção de consulta que a conta não permite (NFC-e, SAT...): desliga a opção
  citada no erro e tenta de novo.

Nada aqui grava no banco nem lê o cofre: recebe bytes, senha e padrões e
devolve um `Resultado`. Segredo, senha, certificado e token nunca vão ao log.
"""

from __future__ import annotations

import base64
import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import httpx

logger = logging.getLogger(__name__)

BASE_URL_PADRAO = "https://api.sieg.com"
EP_JWT = "/api/v1/create-jwt"
EP_REGISTRAR = "/api/v1/registrar"
EP_EDITAR = "/api/v1/editar"
EP_LISTAR = "/api/v1/listar"
EP_HABILITAR = "/api/v1/habilitar"
POR_PAGINA = 100  # a listagem devolve no máximo 100; menos que isso é a última página

# Padrões do config.json validado em 06/10/2026 (UF 27 = Alagoas).
PADROES = {
    "UfCertificado": "27",
    "TipoConsultaNfse": "Nacional",
    "ConsultaNfe": True,
    "ConsultaCte": True,
    "ConsultaNfse": True,
    "ConsultaNfce": False,
    "ConsultaSat": False,
    "BaixarCancelados": False,
    "ConsultaNoturna": True,
    "ConsultaRegiaoHorario": False,
    "ExcluirTransferenciaFiliais": True,
    "IntegracaoEstadual": False,
    "ServicoPrestador": False,
    "ServicoTomador": False,
    "DiasRetroativos": 30,
}
CAMPOS_CONSULTA = (
    "ConsultaNfe", "ConsultaCte", "ConsultaNfse", "ConsultaNfce", "ConsultaSat",
    "ConsultaNoturna", "ConsultaRegiaoHorario", "BaixarCancelados", "IntegracaoEstadual",
    "ServicoPrestador", "ServicoTomador", "ExcluirTransferenciaFiliais",
)
# Trecho do erro da API → opção a desligar.
ERRO_PARA_CAMPO = (
    (r"nfce|nfc-e", "ConsultaNfce"),
    (r"\bnfe\b|nf-e", "ConsultaNfe"),
    (r"\bcte\b|ct-e", "ConsultaCte"),
    (r"nfse|nfs-e", "ConsultaNfse"),
    (r"\bsat\b", "ConsultaSat"),
    (r"noturna", "ConsultaNoturna"),
    (r"regi[aã]o\s*hor[aá]rio", "ConsultaRegiaoHorario"),
    (r"cancelad", "BaixarCancelados"),
    (r"estadual", "IntegracaoEstadual"),
    (r"prestador", "ServicoPrestador"),
    (r"tomador", "ServicoTomador"),
)


class SiegErro(Exception):
    """Falha de autenticação ou de rede: nada foi tentado no SIEG."""

    def __init__(self, mensagem: str, status: Optional[int] = None):
        super().__init__(mensagem)
        self.status = status


@dataclass
class Credenciais:
    client_id: str
    secret_key: str
    api_key: str
    base_url: str = BASE_URL_PADRAO


@dataclass
class Resultado:
    """O que a trilha guarda de cada tentativa (o que a planilha do script tinha)."""

    ok: bool
    operacao: str  # cadastrar | atualizar | recuperar_deletado
    status: Optional[int]
    mensagem: str
    certificado_id: str = ""
    opcoes_desabilitadas: List[str] = field(default_factory=list)
    avisos: List[str] = field(default_factory=list)


def so_digitos(v: Any) -> str:
    return re.sub(r"\D", "", str(v or ""))


def mensagem_da_api(body: Any) -> str:
    if isinstance(body, dict):
        for k in ("ErrorMessage", "Message", "mensagem", "error", "Data", "data"):
            v = body.get(k)
            if v is not None and str(v).strip():
                return str(v)
        return json.dumps(body, ensure_ascii=False)[:500]
    return str(body or "")[:500]


def ja_cadastrado(msg: str) -> bool:
    return bool(re.search(r"j[aá]\s+foi\s+cadastrado|cadastrado\s+anteriormente|already\s+registered", msg, re.I))


def uf_normalizada(v: Any) -> Optional[str]:
    """Código IBGE de 2 dígitos (27 = AL); município de 7 dígitos vira os 2 primeiros."""
    t = str(v if v is not None else "").strip()
    d = so_digitos(t)
    if d:
        return d[:2]
    if re.fullmatch(r"[A-Za-z]{2}", t):
        return t.upper()
    return t or None


def desligar_consultas_do_erro(payload: Dict[str, Any], msg: str) -> List[str]:
    desligadas: List[str] = []
    baixo = msg.lower()
    for padrao, campo in ERRO_PARA_CAMPO:
        if payload.get(campo) is True and re.search(padrao, baixo, re.I):
            payload[campo] = False
            desligadas.append(campo)
    # Erro de "consulta indisponível" sem nome reconhecível: NFC-e é o mais comum.
    if not desligadas and re.search(r"dispon[ií]vel apenas|n[aã]o.*permit|consulta", baixo):
        for campo in ("ConsultaNfce", "ConsultaSat", "ConsultaRegiaoHorario"):
            if payload.get(campo) is True:
                payload[campo] = False
                desligadas.append(campo)
                break
    return desligadas


def _nome_normalizado(v: Optional[str]) -> str:
    t = (v or "").upper().replace("_", " ")
    t = re.sub(r"[^A-Z0-9\s]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def pontuar_candidato(item: Dict[str, Any], nome: str) -> int:
    """Qual cadastro do mesmo CNPJ atualizar (principal x procuração x inativo)."""
    pontos = 0
    a, b = _nome_normalizado(nome), _nome_normalizado(str(item.get("Nome") or ""))
    if a and b:
        if a == b:
            pontos += 200
        elif a in b or b in a:
            pontos += 120
        vazias = {"LTDA", "ME", "EIRELI", "SA", "E", "DE", "DA", "DO", "DOS", "DAS", "COMERCIO"}
        ta = {t for t in a.split() if len(t) > 2 and t not in vazias}
        tb = {t for t in b.split() if len(t) > 2 and t not in vazias}
        pontos += len(ta & tb) * 15
        if "PROCURA" in b and "PROCURA" not in a:
            pontos -= 40
        if "PROCURA" in b and "PROCURA" in a:
            pontos += 80
    # Empate: o inativo costuma ser o que bloqueia o cadastro novo.
    pontos += 25 if not cadastro_ativo(item) else 10
    return pontos


def cadastro_ativo(item: Optional[Dict[str, Any]]) -> bool:
    if not item or item.get("Deletado") is True:
        return False
    if item.get("Ativo") is True:
        return True
    if item.get("Ativo") is False:
        return False
    return item.get("_listado_como_ativo") is True


def _token_da_resposta(body: Any) -> Optional[str]:
    if isinstance(body, str):
        t = body.strip().strip('"')
        if t.count(".") == 2 and len(t) > 20:
            return t
        try:
            body = json.loads(body)
        except Exception:  # noqa: BLE001
            return None
    if not isinstance(body, dict):
        return None
    for k in ("token", "Token", "access_token", "accessToken", "jwt", "Jwt", "JwtToken", "jwtToken"):
        v = body.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    for k in ("data", "Data", "result", "Result"):
        v = body.get(k)
        if isinstance(v, dict):
            t = _token_da_resposta(v)
            if t:
                return t
        if isinstance(v, str) and v.count(".") == 2:
            return v.strip()
    return None


def _itens_da_listagem(body: Any) -> List[Dict[str, Any]]:
    if isinstance(body, list):
        return [i for i in body if isinstance(i, dict)]
    if isinstance(body, dict):
        d = body.get("Data", body.get("data"))
        if isinstance(d, list):
            return [i for i in d if isinstance(i, dict)]
    return []


class ClienteSieg:
    """Uma sessão com a API: gera o JWT na primeira chamada e o reaproveita."""

    def __init__(self, cred: Credenciais, http: Optional[httpx.Client] = None,
                 timeout: float = 60.0, pausa: float = 1.0):
        if not (cred.client_id and cred.secret_key and cred.api_key):
            raise SiegErro("Credenciais do SIEG incompletas: informe Client ID, Secret Key e API Key na Configuração.")
        self.cred = cred
        self.base = (cred.base_url or BASE_URL_PADRAO).rstrip("/")
        self.http = http or httpx.Client(timeout=timeout)
        self.pausa = pausa
        self._jwt: Optional[str] = None

    # ── HTTP ─────────────────────────────────────────────────────────────
    def _corpo(self, r: httpx.Response) -> Any:
        try:
            return r.json()
        except Exception:  # noqa: BLE001
            return r.text

    def _gerar_jwt(self) -> str:
        try:
            r = self.http.post(self.base + EP_JWT, headers={
                "X-Client-Id": self.cred.client_id, "X-Secret-Key": self.cred.secret_key,
                "Content-Type": "application/json", "Accept": "application/json",
            })
        except httpx.HTTPError as e:
            raise SiegErro(f"Sem conexão com o SIEG: {e.__class__.__name__}") from e
        if not (200 <= r.status_code < 300):
            if r.status_code == 401:
                raise SiegErro("O SIEG recusou o Client ID / Secret Key.", 401)
            raise SiegErro(f"O SIEG não gerou o token (HTTP {r.status_code}): {mensagem_da_api(self._corpo(r))}", r.status_code)
        token = _token_da_resposta(self._corpo(r))
        if not token:
            raise SiegErro("O SIEG respondeu sem token reconhecível.", r.status_code)
        return token

    def _cab(self) -> Dict[str, str]:
        if not self._jwt:
            self._jwt = self._gerar_jwt()
        return {"Authorization": f"Bearer {self._jwt}", "X-Api-Key": self.cred.api_key,
                "Content-Type": "application/json", "Accept": "application/json"}

    def _get(self, ep: str, params: Dict[str, str]) -> Tuple[int, Any]:
        try:
            r = self.http.get(self.base + ep, params=params, headers=self._cab())
        except httpx.HTTPError as e:
            raise SiegErro(f"Sem conexão com o SIEG: {e.__class__.__name__}") from e
        return r.status_code, self._corpo(r)

    def _post(self, ep: str, json_: Optional[Dict[str, Any]] = None,
              params: Optional[Dict[str, str]] = None) -> Tuple[bool, int, Any]:
        try:
            r = self.http.post(self.base + ep, json=json_, params=params, headers=self._cab())
        except httpx.HTTPError as e:
            raise SiegErro(f"Sem conexão com o SIEG: {e.__class__.__name__}") from e
        body = self._corpo(r)
        ok = 200 <= r.status_code < 300 and not (isinstance(body, dict) and body.get("IsSuccess") is False)
        return ok, r.status_code, body

    # ── Leitura ──────────────────────────────────────────────────────────
    def _paginas(self):
        """Todos os cadastros, ativos e inativos (com `_listado_como_ativo`)."""
        for ativo in (True, False):
            pagina = 0
            while True:
                status, body = self._get(EP_LISTAR, {"active": str(ativo).lower(), "pagina": str(pagina)})
                if status == 404:  # nenhum cadastro nesse filtro
                    break
                if status == 401 or status == 403:
                    raise SiegErro(f"O SIEG recusou a API Key (HTTP {status}): {mensagem_da_api(body)}", status)
                if not (200 <= status < 300):
                    raise SiegErro(f"Listagem do SIEG falhou (HTTP {status}): {mensagem_da_api(body)}", status)
                itens = _itens_da_listagem(body)
                for it in itens:
                    yield {**it, "_listado_como_ativo": ativo}
                if len(itens) < POR_PAGINA:
                    break
                pagina += 1

    def testar(self) -> int:
        """Gera o JWT e lê a primeira página. Devolve quantos vieram."""
        status, body = self._get(EP_LISTAR, {"active": "true", "pagina": "0"})
        if status == 404:
            return 0
        if not (200 <= status < 300):
            raise SiegErro(f"O SIEG recusou a consulta (HTTP {status}): {mensagem_da_api(body)}", status)
        return len(_itens_da_listagem(body))

    def cadastros(self) -> Dict[str, List[Dict[str, Any]]]:
        """Índice CNPJ → cadastros não excluídos (para a sincronização)."""
        idx: Dict[str, List[Dict[str, Any]]] = {}
        for it in self._paginas():
            if it.get("Deletado") is True:
                continue
            doc = so_digitos(it.get("CnpjCpf") or it.get("cnpjCpf"))
            if doc:
                idx.setdefault(doc, []).append(it)
        return idx

    def cadastros_do_documento(self, doc: str, incluir_deletado: bool = False) -> List[Dict[str, Any]]:
        doc = so_digitos(doc)
        return [it for it in self._paginas()
                if so_digitos(it.get("CnpjCpf") or it.get("cnpjCpf")) == doc
                and (incluir_deletado or it.get("Deletado") is not True)]

    def situacao(self, doc: str) -> Tuple[str, Optional[Dict[str, Any]]]:
        """'ativo' | 'inativo' | 'ausente' — a consulta da reconciliação."""
        itens = self.cadastros_do_documento(doc)
        ativos = [i for i in itens if cadastro_ativo(i)]
        if ativos:
            return "ativo", ativos[0]
        if itens:
            return "inativo", itens[0]
        return "ausente", None

    def _ativo_na_listagem(self, doc: str) -> Optional[Dict[str, Any]]:
        return next((i for i in self.cadastros_do_documento(doc) if cadastro_ativo(i)), None)

    # ── Escrita ──────────────────────────────────────────────────────────
    def _habilitar(self, cert_id: str) -> Tuple[bool, Any]:
        ok, _st, body = self._post(EP_HABILITAR, params={"id": cert_id})
        return ok, body

    def _atualizar(self, doc: str, cert_id: str, inativo: bool, pfx_b64: str, senha: str, tipo: str,
                   r: Resultado) -> Resultado:
        r.operacao = "atualizar"
        r.certificado_id = cert_id
        ok, status, body = self._post(EP_EDITAR, {
            "CertificadoId": cert_id, "SenhaCertificado": senha,
            "TipoCertificado": tipo, "Certificado": pfx_b64,
        })
        r.status, r.mensagem = status, mensagem_da_api(body) or ("OK" if ok else "Falha ao atualizar")
        if ok and inativo:
            ok_h, body_h = self._habilitar(cert_id)
            if ok_h:
                r.avisos.append("Cadastro inativo atualizado e reativado")
            else:
                r.avisos.append(f"Atualizado, mas não reativou: {mensagem_da_api(body_h)}")
                ok = False
        if ok and self._ativo_na_listagem(doc) is None:
            r.avisos.append("A API respondeu OK, mas o cadastro não ficou ativo na listagem")
            ok = False
        r.ok = ok
        return r

    def incluir(self, *, nome: str, documento: str, pfx: bytes, senha: str,
                padroes: Optional[Dict[str, Any]] = None, tipo: str = "Pfx") -> Resultado:
        """Cadastra (ou atualiza o cadastro do mesmo CNPJ) e confere na listagem."""
        doc = so_digitos(documento)
        pfx_b64 = base64.b64encode(pfx).decode("ascii")
        r = Resultado(ok=False, operacao="cadastrar", status=None, mensagem="")

        candidatos = self.cadastros_do_documento(doc)
        if candidatos:
            alvo = max(candidatos, key=lambda i: pontuar_candidato(i, nome))
            cert_id = str(alvo.get("Id") or alvo.get("id") or "")
            if cert_id:
                return self._atualizar(doc, cert_id, not cadastro_ativo(alvo), pfx_b64, senha, tipo, r)

        p = {**PADROES, **(padroes or {})}
        payload: Dict[str, Any] = {
            "Nome": nome, "CnpjCpf": doc, "SenhaCertificado": senha, "TipoCertificado": tipo,
            "Certificado": pfx_b64, "UfCertificado": uf_normalizada(p.get("UfCertificado")),
            "TipoConsultaNfse": p.get("TipoConsultaNfse") or "Nacional",
            "DiasRetroativos": int(p.get("DiasRetroativos") or 0),
        }
        for campo in CAMPOS_CONSULTA:
            payload[campo] = bool(p.get(campo))
        for extra in ("CnpjIntegracaoEstadual", "NomeMunicipio", "InscricaoMunicipal"):
            if p.get(extra):
                payload[extra] = so_digitos(p[extra]) if extra == "CnpjIntegracaoEstadual" else p[extra]
        payload = {k: v for k, v in payload.items() if v is not None and v != ""}

        for tentativa in range(1, len(CAMPOS_CONSULTA) + 3):
            ok, status, body = self._post(EP_REGISTRAR, payload)
            msg = mensagem_da_api(body)
            r.status, r.mensagem = status, msg
            if ok:
                return self._conferir_cadastro(doc, r)
            if ja_cadastrado(msg):
                todos = self.cadastros_do_documento(doc, incluir_deletado=True)
                vivos = [i for i in todos if i.get("Deletado") is not True] or todos
                if vivos:
                    alvo = max(vivos, key=lambda i: pontuar_candidato(i, nome))
                    cert_id = str(alvo.get("Id") or alvo.get("id") or "")
                    if cert_id:
                        return self._atualizar(doc, cert_id, not cadastro_ativo(alvo), pfx_b64, senha, tipo, r)
                r.mensagem = msg + " (o SIEG diz que já existe, mas o cadastro não aparece na listagem)"
                return r
            desligadas = desligar_consultas_do_erro(payload, msg)
            if desligadas:
                r.opcoes_desabilitadas.extend(desligadas)
                r.avisos.append(f"Tentativa {tentativa}: desligado {', '.join(desligadas)} pelo erro da API")
                continue
            return r
        r.mensagem = "Esgotadas as tentativas de desligar opções de consulta"
        return r

    def _conferir_cadastro(self, doc: str, r: Resultado) -> Resultado:
        """Depois do "sucesso": o cadastro existe, está ativo e não excluído?"""
        if self.pausa:
            time.sleep(self.pausa)
        vivos = self.cadastros_do_documento(doc)
        if not vivos:
            excluidos = [i for i in self.cadastros_do_documento(doc, incluir_deletado=True) if i.get("Deletado") is True]
            if excluidos:
                cert_id = str(excluidos[0].get("Id") or excluidos[0].get("id") or "")
                r.operacao, r.certificado_id = "recuperar_deletado", cert_id
                ok_h, body_h = self._habilitar(cert_id)
                if ok_h and self._ativo_na_listagem(doc):
                    r.avisos.append("Cadastro excluído antes foi recuperado (/habilitar)")
                    r.ok = True
                    return r
                r.mensagem += (" | O cadastro está excluído no SIEG e não voltou por /habilitar"
                               f" ({mensagem_da_api(body_h)}). Restaure no painel do SIEG ou peça ao suporte.")
                return r
            r.mensagem += " | Conferência: o CNPJ não aparece no SIEG depois do cadastro (falso sucesso da API)"
            return r
        alvo = next((i for i in vivos if cadastro_ativo(i)), vivos[0])
        r.certificado_id = str(alvo.get("Id") or alvo.get("id") or "")
        if not cadastro_ativo(alvo):
            ok_h, body_h = self._habilitar(r.certificado_id)
            if not ok_h or self._ativo_na_listagem(doc) is None:
                r.mensagem += f" | Cadastrado, mas não ficou ativo: {mensagem_da_api(body_h)}"
                return r
        r.ok = True
        return r
