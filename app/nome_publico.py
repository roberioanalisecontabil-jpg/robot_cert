"""
Nome público de um arquivo de certificado — o que pode sair do servidor.

A convenção operacional da pasta de certificados põe a SENHA do PFX no nome do
arquivo ("EMPRESA_CNPJ senha 123456.pfx"). O portal usava esse nome como
identidade do certificado: chave primária de `cert_history`, campo de todo item
de snapshot, resposta de três rotas, coluna copiável na tela Duplicidades e
linha de log do agente. O cofre cifrava a senha; o nome ao lado a entregava em
claro (SECURITY_AUDIT #2, crítico; #58 no agente).

Desde o lote 3 (25/09/2026) o nome original **não entra no banco nem sai pela
API**. O que existe no lugar dele:

  * `nome_publico` — o nome sem a senha. Para um certificado legível a
    identidade que vale é a do PRÓPRIO PFX (`nome`, `documento_numero`,
    `fingerprint_sha256`, lidos do X.509); o nome público é o rótulo do
    arquivo, para a pessoa achá-lo na pasta. A limpeza por regex é o fallback
    do arquivo ilegível, que não tem subject — e cobre as formas REAIS da
    pasta, levantadas em 25/09/2026 (ver `tests/test_seguranca_lote3.py`).
  * `pasta` — o diretório, sem o nome do arquivo. Só admin recebe.
  * `arquivo_chave` — chave de deduplicação derivada só de dado público
    (nome público + fingerprint). Não é hash do nome original: um hash de
    "prefixo conhecido + senha de 6 dígitos" cai em segundos.

Módulo só de stdlib de propósito: o agente Windows o importa para logar o
nome público, e o script de migração o importa para transformar o banco com a
MESMA regra que o servidor usa em produção.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any, Dict, Optional

# Extensões de PKCS#12 que a pasta tem.
_RE_EXTENSAO = re.compile(r"\.(?:pfx|p12)\s*$", re.IGNORECASE)

# A palavra que anuncia a senha. Antes dela, qualquer coisa que não seja
# letra: espaço, "_", "-" ou o próprio CNPJ colado ("…000199senha 123",
# "…_SENHA 123" existem na pasta; `\b` não os pegaria porque "_" e dígito
# contam como \w). "DESENHOS" e "ENGENHARIA" têm letra antes de "senh" e
# ficam. O lookahead depois: "SENHORA" tem 'o' depois de "senh" e é nome;
# "senha 123", "SENHA123", "senh 123" (o erro de digitação que existe na
# pasta), "senha:", "senha_" são anúncio de senha. Tudo a partir daí é
# sensível — inclusive sufixos como "(2)" ou "- renovado", que vêm depois da
# senha e não há como separar dela com segurança.
_RE_SENHA = re.compile(r"(?<![A-Za-zÀ-ÿ])senh(?:a|as)?(?=\s|[\d:=_\-#@!*]|$)", re.IGNORECASE)

# Documento (CPF 11 ou CNPJ 14 dígitos) precedido de separador e seguido de
# QUALQUER coisa: o que vem depois do documento é a senha sem a palavra
# ("EMPRESA_21640463000198 123456.pfx"). O documento fica; o resto sai.
_RE_DOC_E_RESTO = re.compile(r"^(?P<ate_doc>.*?[\s_\-]\d{11}(?:\d{3})?)(?P<resto>[\s_\-].*)$", re.DOTALL)

_SEPARADORES = " \t\r\n_-.,;:"

# Estados em que o `nome` do item veio do NOME DO ARQUIVO, e não do X.509.
_ESTADOS_SEM_SUBJECT = frozenset({"erro", "fora_do_padrao"})

CHAVES_SENSIVEIS = ("file_name", "path", "password", "password_from_name", "senha")


def nome_publico_de_arquivo(file_name: Optional[str]) -> str:
    """O nome do arquivo sem a senha e sem a extensão.

    Devolve "" quando não sobra nada (nome que era só a senha): quem chama
    decide o fallback. Nunca levanta.
    """
    nome = (file_name or "").strip()
    if not nome:
        return ""
    nome = _RE_EXTENSAO.sub("", nome)

    m = _RE_SENHA.search(nome)
    if m:
        nome = nome[: m.start()]
    else:
        d = _RE_DOC_E_RESTO.match(nome)
        if d:
            nome = d.group("ate_doc")

    nome = nome.strip(_SEPARADORES)
    return " ".join(nome.split())


def pasta_de(path: Optional[Any]) -> str:
    """O diretório de um caminho, com barras normalizadas e sem o arquivo."""
    bruto = str(path or "").strip().replace("\\", "/")
    if not bruto or "/" not in bruto:
        return ""
    return bruto.rsplit("/", 1)[0].rstrip("/")


def chave_de_arquivo(nome_publico: str, fingerprint: Optional[str]) -> str:
    """Chave de deduplicação: o mesmo certificado, sob o mesmo nome público, é
    uma linha só — troque-se a senha do arquivo quantas vezes for.

    Só dado público entra: não há o que adivinhar a partir dela.
    """
    base = f"{(nome_publico or '').strip().lower()}|{(fingerprint or '').strip().lower()}"
    return hashlib.sha256(base.encode("utf-8")).hexdigest()


def sanitizar_item(item: Dict[str, Any]) -> Dict[str, Any]:
    """Um item de inventário como ele pode existir no banco e na resposta.

    Aceita o item de um agente ANTIGO (com `file_name`/`path`) e o de um agente
    novo (já com `nome_publico`/`pasta`); é idempotente. Remove todo campo
    sensível; acrescenta `nome_publico`, `pasta` e `arquivo_chave`.
    """
    it = dict(item or {})
    fingerprint = str(it.get("fingerprint_sha256") or it.get("cert_sha256") or "").strip()
    status = str(it.get("status") or "").strip().lower()

    nome_pub = str(it.get("nome_publico") or "").strip()
    if not nome_pub and it.get("file_name"):
        nome_pub = nome_publico_de_arquivo(str(it.get("file_name")))
    if not nome_pub:
        # Sem arquivo (ou arquivo que era só a senha): o rótulo é o que o
        # X.509 disse, ou nada.
        nome_pub = str(it.get("nome") or it.get("display_name") or "").strip()
        if status in _ESTADOS_SEM_SUBJECT:
            nome_pub = nome_publico_de_arquivo(nome_pub) or nome_pub

    pasta = str(it.get("pasta") or "").strip() or pasta_de(it.get("path"))

    # `display_name` é o nome lógico que o scanner tira do arquivo; num nome
    # fora do padrão é o stem inteiro, senha inclusa. `nome` só vem do
    # arquivo quando não houve X.509 — num legível vem do CN e não se toca:
    # "SENHA SERVICOS LTDA" é uma razão social possível.
    if it.get("display_name"):
        it["display_name"] = nome_publico_de_arquivo(str(it["display_name"])) or nome_pub
    if status in _ESTADOS_SEM_SUBJECT and it.get("nome"):
        it["nome"] = nome_publico_de_arquivo(str(it["nome"])) or nome_pub

    for chave in CHAVES_SENSIVEIS:
        it.pop(chave, None)

    it["nome_publico"] = nome_pub
    it["pasta"] = pasta
    it["arquivo_chave"] = chave_de_arquivo(nome_pub, fingerprint)
    return it


def sem_pasta(item: Dict[str, Any]) -> Dict[str, Any]:
    """O item para quem não é admin: o diretório do servidor não é dele."""
    it = dict(item)
    it.pop("pasta", None)
    return it
