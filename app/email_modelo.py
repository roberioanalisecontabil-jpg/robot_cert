"""O texto do e-mail de alerta, editável pela tela.

Mesma convenção de `app/alertas_config.py`, e pelo mesmo motivo: a validação que
a tela usa para RECUSAR um texto tem de ser a mesma que o job usa para
INTERPRETÁ-LO. E **vazio significa "usar o padrão do código"** — uma instalação
que nunca abriu este modal manda exatamente o e-mail que mandava antes dele
existir.

Só a moldura é editável: assunto, título, abertura e recado final. A tabela de
certificados continua sendo gerada, porque não é texto — é o inventário do dia.
Um campo de texto no lugar dela produziria um e-mail que afirma vencimentos que
não conferiu.

## Duas assimetrias de propósito

**A tela recusa; o job não.** `validar_campo` levanta `ModeloInvalido` para o
autor ver o erro enquanto edita. `aplicar` nunca levanta: um texto ilegível cai
no padrão e o alerta SAI. É a mesma postura da trilha de permissões — o registro
não derruba a concessão. Alerta que não sai por causa do texto é o defeito que
este arquivo existe para não criar: o certificado vence do mesmo jeito, e agora
ninguém foi avisado.

**O rodapé de procedência não é editável.** `{motivo}` é a única linha que diz a
quem recebeu POR QUE recebeu e onde parar de receber. Deixá-la apagável cria um
e-mail que chega sem remetente reconhecível e sem saída — e quem apagaria é
justamente quem acha o rodapé feio, não quem pesa a consequência.
"""

from __future__ import annotations

import html as _html
import logging
import re
from typing import Dict, Mapping, Tuple

logger = logging.getLogger(__name__)

# ── Campos e seus padrões ──────────────────────────────────────────────────
# Os padrões abaixo reproduzem, palavra por palavra, o e-mail que `_montar_resumo`
# escrevia em código antes desta tela. Mudá-los aqui muda o e-mail de toda
# instalação que nunca editou o texto — que é o comportamento certo, e o motivo
# de eles morarem num lugar só.
ASSUNTO_PADRAO = (
    "Resumo de certificados — {a_vencer} a vencer, "
    "{vencidos} vencidos recentemente"
)
TITULO_PADRAO = "Resumo de certificados"
ABERTURA_PADRAO = (
    "Situação em {data} — {vencidos} vencido(s) nos últimos {janela} dias "
    "e {a_vencer} a vencer nos próximos {janela}."
)
RECADO_PADRAO = (
    "Certificados vencidos há mais de {janela} dias não entram aqui — "
    "consulte a página Vencidos para a lista completa."
)

PADROES: Dict[str, str] = {
    "assunto": ASSUNTO_PADRAO,
    "titulo": TITULO_PADRAO,
    "abertura": ABERTURA_PADRAO,
    "recado": RECADO_PADRAO,
}

# Limite por campo. Não é paranoia com banco: é o assunto que vira cabeçalho
# SMTP (servidores cortam cabeçalho longo) e o corpo que vira e-mail — um texto
# de dez mil caracteres empurra a tabela para fora da primeira tela.
LIMITES: Dict[str, int] = {
    "assunto": 200,
    "titulo": 120,
    "abertura": 2000,
    "recado": 2000,
}

# Vazio é "usar o padrão" nos QUATRO campos, sem exceção.
#
# Cheguei a abrir uma exceção para o recado final poder ser apagado, e desfiz:
# com uma coluna de texto só, vazio não consegue significar duas coisas — e a
# tentativa de fazê-lo significar produziria "vazio às vezes é padrão, às vezes
# é apagado", que ninguém adivinha lendo a tela. Quem não quer o recado padrão
# escreve o seu; apagá-lo por completo é um caso que ninguém pediu, e inventar
# um sentinela para ele custaria mais do que vale.

# ── Marcadores ─────────────────────────────────────────────────────────────
# Números do próprio envio. Nomes em português porque quem edita lê a tela em
# português; um `{expiring}` no meio de uma frase em pt-BR é ruído.
MARCADORES: Tuple[str, ...] = ("data", "a_vencer", "vencidos", "janela")

# Substituição por regex, e NÃO `str.format`. `"{x.__class__}".format(x=1)`
# alcança atributos do objeto, e `str.format` levanta em chave desconhecida ou
# em chave solta — dois comportamentos ruins para texto que uma pessoa digita.
# Aqui, marcador desconhecido é recusado na tela e fica literal no job.
_RE_MARCADOR = re.compile(r"\{([a-z_][a-z0-9_]*)\}")

# Quebra de linha em cabeçalho SMTP injeta cabeçalho novo (`\nBcc: ...`).
# `send_smtp_email` faz `msg["Subject"] = subject` sem sanitizar — o que nunca
# importou porque o assunto sempre veio do código. A partir do momento em que
# uma pessoa o digita, importa.
_RE_QUEBRA = re.compile(r"[\r\n]+")


class ModeloInvalido(ValueError):
    """Texto recusado na hora de salvar, com o motivo em português."""


def _bruto(texto: object) -> str:
    return (str(texto) if texto is not None else "").strip()


# ══════════════════════════════════════════════════════════════════════════
# Validação — usada pela tela, levanta
# ══════════════════════════════════════════════════════════════════════════

def validar_campo(campo: str, texto: object) -> str:
    """Devolve o texto normalizado ou levanta `ModeloInvalido`.

    Vazio passa: significa "usar o padrão", e é como a pessoa desfaz uma edição.
    """
    if campo not in PADROES:
        raise ModeloInvalido(f"Campo desconhecido: “{campo}”.")

    valor = _bruto(texto)
    if campo == "assunto":
        valor = _RE_QUEBRA.sub(" ", valor).strip()
    if not valor:
        return ""

    limite = LIMITES[campo]
    if len(valor) > limite:
        raise ModeloInvalido(
            f"O campo “{campo}” tem {len(valor)} caracteres e o limite é {limite}."
        )

    desconhecidos = sorted(
        {m for m in _RE_MARCADOR.findall(valor) if m not in MARCADORES}
    )
    if desconhecidos:
        lista = ", ".join("{%s}" % m for m in desconhecidos)
        disponiveis = ", ".join("{%s}" % m for m in MARCADORES)
        raise ModeloInvalido(
            f"Marcador não reconhecido: {lista}. Os disponíveis são: {disponiveis}."
        )
    return valor


def validar_modelo(campos: Mapping[str, object]) -> Dict[str, str]:
    """Valida os campos presentes. Ausente é "não mexer", não "apagar"."""
    saida: Dict[str, str] = {}
    for campo, texto in campos.items():
        if texto is None:
            continue
        saida[campo] = validar_campo(campo, texto)
    return saida


# ══════════════════════════════════════════════════════════════════════════
# Aplicação — usada pelo job, nunca levanta
# ══════════════════════════════════════════════════════════════════════════

def campo_efetivo(campo: str, texto: object) -> str:
    """O texto que vale: o digitado, ou o padrão quando ilegível ou vazio.

    Nunca levanta. Um texto que passou pela tela e ficou inválido depois — por
    edição direta no banco, ou por um marcador que este código deixou de
    reconhecer — vira registro no log e não impede o envio.
    """
    if campo not in PADROES:
        return ""
    valor = _bruto(texto)
    if not valor:
        return PADROES[campo]
    try:
        return validar_campo(campo, valor)
    except ModeloInvalido as e:
        logger.warning(
            "Texto inválido no campo “%s” do e-mail de alerta (%s). "
            "Usando o padrão para não bloquear o envio.", campo, e
        )
        return PADROES[campo]


def preencher(texto: str, valores: Mapping[str, object]) -> str:
    """Troca `{marcador}` pelo valor. Desconhecido fica literal, não explode."""
    def _troca(m: "re.Match[str]") -> str:
        nome = m.group(1)
        if nome not in valores:
            return m.group(0)
        return str(valores[nome])
    return _RE_MARCADOR.sub(_troca, texto or "")


def para_html(texto: str) -> str:
    """Texto digitado -> HTML seguro.

    Escapa antes de qualquer coisa: quem edita escreve texto, não marcação, e um
    `<` digitado tem de aparecer como `<`. Só depois a quebra de linha vira
    `<br>`, para o parágrafo digitado em duas linhas chegar em duas linhas.
    """
    return _html.escape(texto or "").replace("\n", "<br>")


def assunto_final(texto: object, valores: Mapping[str, object]) -> str:
    """Assunto pronto para virar cabeçalho: sem marcador e sem quebra.

    A quebra é removida em `validar_campo`, por onde TODO assunto passa —
    inclusive o que veio direto do banco, porque `campo_efetivo` valida antes de
    devolver. Cheguei a repetir a limpeza aqui como "defesa em duas camadas" e
    tirei: a segunda era inalcançável, e uma mutação provou isso — apagá-la não
    quebrava teste nenhum. Defesa que nada exercita não é camada, é código que
    parece proteger.

    O que sustenta a garantia é `test_quebra_de_linha_no_assunto...`, que morre
    se `validar_campo` parar de limpar.
    """
    return preencher(campo_efetivo("assunto", texto), valores).strip()


def bloco_html(campo: str, texto: object, valores: Mapping[str, object]) -> str:
    """Campo de corpo pronto para o e-mail."""
    efetivo = campo_efetivo(campo, texto)
    if not efetivo:
        return ""
    return para_html(preencher(efetivo, valores))


# ══════════════════════════════════════════════════════════════════════════
# Ponte com PortalSettings
# ══════════════════════════════════════════════════════════════════════════

# O nome do campo na tela e o nome da coluna se correspondem num lugar só. Já
# perdi tempo em bug de nome divergente neste projeto; três cópias deste dicionário
# — job, rota e template — é como "recado" viraria "rodape" em um deles.
CAMPO_COLUNA: Dict[str, str] = {
    "assunto": "alerta_email_assunto",
    "titulo": "alerta_email_titulo",
    "abertura": "alerta_email_abertura",
    "recado": "alerta_email_recado",
}


def do_settings(settings: object) -> Dict[str, str]:
    """Os quatro textos crus de um `PortalSettings`.

    `getattr` com default: se a migration ainda não rodou, o atributo pode não
    existir e o padrão continua valendo — mesma tolerância de `_from_row`.
    """
    return {
        campo: str(getattr(settings, coluna, "") or "")
        for campo, coluna in CAMPO_COLUNA.items()
    }
