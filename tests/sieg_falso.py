"""Um SIEG falso para os testes (httpx.MockTransport), com estado.

Reproduz o que o script do usuário encontrou na API real em 06/10/2026:
falso sucesso no /registrar, opção de consulta recusada, CNPJ já cadastrado,
cadastro inativo e cadastro excluído logicamente (Deletado=true).
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import httpx

CLIENT_ID, SECRET, API_KEY, JWT = "cliente-falso-7f3a", "segredo-falso-91bd", "chave-conta-falsa-4c2e", "jwtfalso.parte2x.parte3y"


class SiegFalso:
    def __init__(self) -> None:
        self.cadastros: List[Dict[str, Any]] = []
        self.chamadas: List[str] = []
        self.payloads: List[Dict[str, Any]] = []
        self.recusa_nfce = False
        self.falso_sucesso = False
        self.habilitar_falha = False
        self.jwt_recusa = False
        self.conta = "20929"

    def cadastro(self, doc: str, nome: str = "X", ativo: bool = True, deletado: bool = False) -> Dict[str, Any]:
        c = {"Id": f"{self.conta}-{doc}", "CnpjCpf": doc, "Nome": nome, "Ativo": ativo, "Deletado": deletado}
        self.cadastros.append(c)
        return c

    def _json(self, status: int, body: Any) -> httpx.Response:
        return httpx.Response(status, json=body)

    def __call__(self, req: httpx.Request) -> httpx.Response:
        caminho = req.url.path
        self.chamadas.append(caminho)
        if caminho == "/api/v1/create-jwt":
            if self.jwt_recusa or req.headers.get("X-Client-Id") != CLIENT_ID or req.headers.get("X-Secret-Key") != SECRET:
                return self._json(401, {"Message": "nao autorizado"})
            return self._json(200, {"Token": JWT})
        if req.headers.get("Authorization") != f"Bearer {JWT}" or req.headers.get("X-Api-Key") != API_KEY:
            return self._json(401, {"Message": "API Key invalida"})
        if caminho == "/api/v1/listar":
            ativo = req.url.params.get("active") == "true"
            pagina = int(req.url.params.get("pagina") or 0)
            itens = [c for c in self.cadastros if bool(c["Ativo"]) == ativo]
            fatia = itens[pagina * 100:(pagina + 1) * 100]
            if not fatia:
                return self._json(404, {"Message": "Nenhum certificado"})
            return self._json(200, {"Data": [dict(c) for c in fatia]})
        corpo: Dict[str, Any] = json.loads(req.content or b"{}") if req.content else {}
        if caminho == "/api/v1/registrar":
            self.payloads.append(corpo)
            doc = corpo["CnpjCpf"]
            if any(c["CnpjCpf"] == doc and not c["Deletado"] for c in self.cadastros):
                return self._json(400, {"ErrorMessage": "Certificado ja foi cadastrado"})
            if self.recusa_nfce and corpo.get("ConsultaNfce"):
                return self._json(400, {"ErrorMessage": "Consulta de NFC-e disponivel apenas no plano X"})
            if self.falso_sucesso:
                return self._json(200, {"Message": "Certificado registrado com sucesso."})
            excluido = next((c for c in self.cadastros if c["CnpjCpf"] == doc and c["Deletado"]), None)
            if not excluido:
                self.cadastro(doc, corpo.get("Nome", ""))
            return self._json(200, {"Message": "Certificado registrado com sucesso."})
        if caminho == "/api/v1/editar":
            self.payloads.append(corpo)
            c = next((c for c in self.cadastros if c["Id"] == corpo["CertificadoId"]), None)
            if not c:
                return self._json(404, {"ErrorMessage": "nao encontrado"})
            return self._json(200, {"Message": "Certificado atualizado"})
        if caminho == "/api/v1/habilitar":
            c = next((c for c in self.cadastros if c["Id"] == req.url.params.get("id")), None)
            if not c or self.habilitar_falha:
                return self._json(400, {"ErrorMessage": "nao habilitado"})
            c["Ativo"], c["Deletado"] = True, False
            return self._json(200, {"Message": "habilitado"})
        return self._json(404, {"Message": "rota desconhecida"})

    def cliente(self):
        from app.sieg_api import ClienteSieg, Credenciais

        return ClienteSieg(Credenciais(CLIENT_ID, SECRET, API_KEY),
                           http=httpx.Client(transport=httpx.MockTransport(self)), pausa=0)
