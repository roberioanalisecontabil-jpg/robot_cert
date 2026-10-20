"""Atualização automática da bandeja — o lado da estação (1.1.0, 20/10/2026).

Veio de `core/atualizador.py` do Hardlyze. A diferença: o Certguard Análise
não tem serviço. O papel do serviço fica com uma TAREFA AGENDADA que roda como
SYSTEM na partida do Windows e a cada 6 horas (`certguard_analise.exe
--atualizacao`, criada pelo instalador). A bandeja roda como a pessoa, sem
direito de administrador, e não consegue instalar nada em Program Files.

Três papéis, em dois processos:

1. **A tarefa** (`verificar_e_disparar`): pede o manifesto ao portal, confere
   a assinatura (estacao/manifesto.py), decide se há o que fazer, baixa o
   instalador conferindo tamanho e SHA-256, grava o PEDIDO em disco e dispara
   o atualizador. Não instala nada: o exe dela é o que vai ser sobrescrito.

2. **O atualizador** (`executar_pedido`), um processo à parte que roda de uma
   CÓPIA do executável (o original é sobrescrito pela instalação). Guarda o
   instalador da versão atual como "anterior", roda o novo em silêncio e
   espera até 10 minutos pela confirmação da versão nova. Sem confirmação,
   reinstala a anterior e marca a versão como bloqueada — senão a tarefa
   baixaria a mesma versão quebrada de novo, em laço.

3. **A versão nova** (`confirmar_na_partida`): o instalador novo dispara a
   tarefa no fim; depois de falar com o portal, se há pedido para a versão
   dela, ela escreve a confirmação que o atualizador espera e conta ao portal
   ("atualizou" ou "voltou").

Tudo que toca rede, disco do sistema e processos entra por parâmetro, para
os testes exercitarem o fluxo inteiro sem Windows nem portal.

── O atualizador roda como SYSTEM: a pasta é a fronteira ──────────────────

Por padrão qualquer usuário cria arquivos em subpastas de %ProgramData%. Se
desse para escrever o `pedido.json`, uma pessoa sem privilégio apontaria o
"instalador" para um programa dela e ele rodaria como SYSTEM. Três camadas:

  * a pasta é trancada a SYSTEM e Administradores, com o DONO trocado (quem
    cria uma pasta pode reabrir as permissões dela) — `proteger_pasta`, pelo
    instalador e de novo pela tarefa a cada rodada;
  * o pedido carrega o pacote ASSINADO, e o atualizador confere assinatura e
    SHA-256 do instalador de novo antes de rodar: pedido forjado não passa
    sem a chave privada;
  * o instalador tem de estar DENTRO da pasta.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from estacao import manifesto

PRODUTO = manifesto.PRODUTO
ESPERA_CONFIRMACAO_SEG = 600  # decidido em 10/10/2026: 10 minutos
INTERVALO_CONFERENCIA_SEG = 6 * 3600
ATRASO_INICIAL_SEG = 300
# Pedido "em andamento" mais velho que isto é sobra de uma máquina desligada
# no meio do caminho (o atualizador morreu antes de instalar). Sem caducar,
# a tarefa antiga diria "pedido em andamento" para sempre e nunca mais
# atualizaria.
PEDIDO_CADUCA_SEG = 2 * 3600

# Estados do pedido, na ordem em que acontecem.
BAIXADO = "baixado"  # a tarefa deixou o instalador e o pedido prontos
INSTALANDO = "instalando"  # o atualizador começou a rodar o novo
INSTALADO = "instalado"  # o novo terminou; esperando a versão nova confirmar
CONFIRMADO = "confirmado"  # a versão nova subiu e falou com o portal
VOLTOU = "voltou"  # sem confirmação: a anterior foi reinstalada
FALHOU = "falhou"  # nem a anterior voltou; precisa de gente


@dataclass(frozen=True)
class Pastas:
    """Tudo mora em %ProgramData%\\CertguardAnalise\\atualizacoes."""

    raiz: str

    @property
    def pedido(self) -> str:
        return os.path.join(self.raiz, "pedido.json")

    @property
    def bloqueadas(self) -> str:
        return os.path.join(self.raiz, "bloqueadas.json")

    @property
    def instalado(self) -> str:
        # Gravado pelo instalador em toda instalação: é a versão que está na
        # máquina agora, e vira a "anterior" antes de instalar a próxima.
        return os.path.join(self.raiz, "instalado.exe")

    @property
    def anterior(self) -> str:
        return os.path.join(self.raiz, "anterior.exe")

    def novo(self, arquivo: str) -> str:
        return os.path.join(self.raiz, arquivo)


def _agora() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class ArquivoIlegivel(RuntimeError):
    """O arquivo existe mas não deu para ler — quase sempre permissão."""


def ler_json(caminho: str) -> Any:
    """O conteúdo, ou None se o arquivo não existe ou não é JSON.

    Existir e não abrir (permissão) LEVANTA `ArquivoIlegivel`: tratado como
    "não existe", foi o que escondeu o defeito das permissões no ensaio de
    12/10/2026 — o atualizador dizia "sem pedido" com o pedido ali.
    """
    try:
        with open(caminho, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return None
    except ValueError:
        return None
    except OSError as e:
        raise ArquivoIlegivel(f"{caminho}: {e}") from e


def gravar_json(caminho: str, dados: Any) -> None:
    """Grava de forma atômica: quem ler no meio vê o antigo ou o novo."""
    temporario = caminho + ".tmp"
    with open(temporario, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=2)
    os.replace(temporario, caminho)


# SIDs bem conhecidos: o nome do grupo muda com o idioma do Windows.
SID_SYSTEM = "*S-1-5-18"
SID_ADMINISTRADORES = "*S-1-5-32-544"


def comandos_de_protecao(raiz: str, tem_conteudo: bool) -> list[list[str]]:
    """icacls que deixam só SYSTEM e Administradores na pasta e no que houver.

    A PASTA recebe as concessões, com herança, e só ela — sem `/T`. O
    conteúdo que já existir é zerado para HERDAR da pasta (`/reset`).

    Até o 2.2.0 do ensaio de 12/10/2026 a concessão ia com `/T`: o
    `/inheritance:r` chegava aos arquivos, tirava deles o que herdavam, e a
    concessão `(OI)(CI)` (que só faz sentido em pasta) não entrava no lugar.
    O `pedido.json` ficava sem permissão nenhuma — nem o SYSTEM o lia — e o
    atualizador terminava em "sem pedido" sem instalar nada.
    """
    comandos = [
        ["icacls", raiz, "/setowner", SID_ADMINISTRADORES, "/T", "/C", "/Q"],
        [
            "icacls",
            raiz,
            "/inheritance:r",
            "/grant:r",
            f"{SID_SYSTEM}:(OI)(CI)F",
            f"{SID_ADMINISTRADORES}:(OI)(CI)F",
            "/C",
            "/Q",
        ],
    ]
    if tem_conteudo:
        # Sem conteúdo o curinga não casa com nada e o icacls sai com erro.
        comandos.append(["icacls", os.path.join(raiz, "*"), "/reset", "/T", "/C", "/Q"])
    return comandos


def proteger_pasta(raiz: str, executar: Callable[[list[str]], int]) -> bool:
    """Cria e tranca a pasta. False se algum icacls falhou: aí não se baixa
    nem se dispara nada — pasta aberta é pior que não atualizar."""
    os.makedirs(raiz, exist_ok=True)
    comandos = comandos_de_protecao(raiz, tem_conteudo=bool(os.listdir(raiz)))
    return all(executar(c) == 0 for c in comandos)


def versoes_bloqueadas(pastas: Pastas) -> set[str]:
    dados = ler_json(pastas.bloqueadas)
    return set(dados) if isinstance(dados, list) else set()


def bloquear(pastas: Pastas, versao: str) -> None:
    gravar_json(pastas.bloqueadas, sorted(versoes_bloqueadas(pastas) | {versao}))


# ── 1. A tarefa: conferir e disparar ─────────────────────────────────────


def verificar_e_disparar(
    *,
    pastas: Pastas,
    versao_atual: str,
    buscar_pacote: Callable[[], dict | None],
    baixar: Callable[[str, str], None],
    disparar: Callable[[str], None],
    proteger: Callable[[str], bool] = lambda _r: True,
    log: Callable[[str], None] = lambda _m: None,
    agora: Callable[[], float] = time.time,
    estacao: Callable[[], bool] = lambda: True,
) -> str:
    """Uma rodada. Devolve o que aconteceu, para o log e os testes.

    Servidor (ProductType do Windows) não se atualiza sozinho: decisão da
    frente B das decisões do Hardlyze (INVENT), mantida aqui: no ANALISESRV
    quem atualiza é a TI.

    `buscar_pacote()` é o GET do manifesto (None = sem versão publicada);
    `baixar(sha256, destino)` grava o instalador; `disparar(pedido)` sobe o
    atualizador. Qualquer manifesto que não confira é ignorado — nunca é
    motivo para instalar.
    """
    if not estacao():
        return "servidor: atualização manual"
    pedido = ler_json(pastas.pedido)
    if isinstance(pedido, dict) and pedido.get("estado") in (BAIXADO, INSTALANDO, INSTALADO):
        if agora() - float(pedido.get("criado_ts") or 0) < PEDIDO_CADUCA_SEG:
            return "pedido em andamento"
        log(f"Pedido para {pedido.get('para')} parado em {pedido.get('estado')}; descartado.")
        os.remove(pastas.pedido)

    pacote = buscar_pacote()
    if pacote is None:
        return "sem versão publicada"
    try:
        m = manifesto.conferir(pacote)
        acao = manifesto.decidir(m, PRODUTO, versao_atual)
    except manifesto.ManifestoInvalido as e:
        log(f"Manifesto recusado: {e}")
        return "manifesto recusado"
    if acao == "nada":
        return "em dia"
    if m["versao"] in versoes_bloqueadas(pastas) and not m["pode_voltar"]:
        return "versão bloqueada"

    if not proteger(pastas.raiz):
        log("Não foi possível trancar a pasta de atualização; nada baixado.")
        return "pasta desprotegida"
    destino = pastas.novo(m["arquivo"])
    parcial = destino + ".part"
    baixar(m["sha256"], parcial)
    if (
        os.path.getsize(parcial) != m["tamanho"]
        or manifesto.sha256_do_arquivo(parcial) != m["sha256"]
    ):
        os.remove(parcial)
        log("Instalador baixado não confere com o manifesto; descartado.")
        return "download não confere"
    os.replace(parcial, destino)

    gravar_json(
        pastas.pedido,
        {
            "estado": BAIXADO,
            "acao": acao,
            "de": versao_atual,
            "para": m["versao"],
            "instalador": destino,
            "pacote": pacote,
            "criado_em": _agora(),
            "criado_ts": agora(),
        },
    )
    disparar(pastas.pedido)
    log(f"Atualização {versao_atual} -> {m['versao']} disparada ({acao}).")
    return acao


# ── 2. O atualizador ─────────────────────────────────────────────────────


def executar_pedido(
    *,
    pastas: Pastas,
    instalar: Callable[[str], int],
    esperar: Callable[[float], None] = time.sleep,
    relogio: Callable[[], float] = time.monotonic,
    espera_seg: float = ESPERA_CONFIRMACAO_SEG,
    log: Callable[[str], None] = lambda _m: None,
) -> str:
    """Instala, espera a confirmação e volta atrás se ela não vier.

    `instalar(caminho)` roda o instalador em silêncio e devolve o código de
    saída. Devolve o estado final gravado no pedido.
    """
    try:
        pedido = ler_json(pastas.pedido)
    except ArquivoIlegivel as e:
        log(f"Pedido existe mas não pôde ser lido: {e}")
        return "pedido ilegível"
    if not isinstance(pedido, dict) or pedido.get("estado") != BAIXADO:
        return "sem pedido"
    motivo = _pedido_confiavel(pastas, pedido)
    if motivo:
        log(f"Pedido recusado: {motivo}")
        os.remove(pastas.pedido)
        return "pedido recusado"

    tem_anterior = os.path.isfile(pastas.instalado)
    if tem_anterior:
        # Antes de instalar: o novo instalador sobrescreve `instalado.exe`.
        with open(pastas.instalado, "rb") as origem, open(pastas.anterior, "wb") as destino:
            destino.write(origem.read())

    pedido.update(estado=INSTALANDO, iniciado_em=_agora())
    gravar_json(pastas.pedido, pedido)
    codigo = instalar(pedido["instalador"])
    log(f"Instalador de {pedido['para']} terminou com código {codigo}.")

    if codigo == 0:
        pedido.update(estado=INSTALADO)
        gravar_json(pastas.pedido, pedido)
        limite = relogio() + espera_seg
        while relogio() < limite:
            try:
                atual = ler_json(pastas.pedido)
            except ArquivoIlegivel as e:
                # Não pode derrubar a espera: sem ela não há volta automática.
                log(f"Pedido ilegível durante a espera: {e}")
                atual = None
            if isinstance(atual, dict) and atual.get("estado") == CONFIRMADO:
                log(f"Versão {pedido['para']} confirmada pela versão nova.")
                return CONFIRMADO
            esperar(10)
        log(f"Versão {pedido['para']} não confirmou em {int(espera_seg)} s.")

    # Não subiu (ou o instalador falhou): volta para a anterior e bloqueia.
    bloquear(pastas, pedido["para"])
    if not tem_anterior:
        pedido.update(estado=FALHOU, detalhe="sem instalador anterior guardado para voltar")
        gravar_json(pastas.pedido, pedido)
        return FALHOU
    pedido.update(estado=VOLTOU, detalhe=f"versão {pedido['para']} não subiu (código {codigo})")
    gravar_json(pastas.pedido, pedido)
    codigo_volta = instalar(pastas.anterior)
    if codigo_volta != 0:
        pedido.update(estado=FALHOU, detalhe=f"a volta também falhou (código {codigo_volta})")
        gravar_json(pastas.pedido, pedido)
        return FALHOU
    log(f"Voltou para {pedido['de']}.")
    return VOLTOU


def _pedido_confiavel(pastas: Pastas, pedido: dict) -> str:
    """ "" se o pedido pode ser executado como SYSTEM; senão, o motivo."""
    try:
        m = manifesto.conferir(pedido.get("pacote"))
    except manifesto.ManifestoInvalido as e:
        return f"pacote não confere ({e})"
    if m["versao"] != pedido.get("para"):
        return "versão do pedido não é a do pacote"
    caminho = os.path.realpath(str(pedido.get("instalador") or ""))
    raiz = os.path.realpath(pastas.raiz)
    if os.path.dirname(caminho) != raiz or os.path.basename(caminho) != m["arquivo"]:
        return "instalador fora da pasta de atualização"
    if not os.path.isfile(caminho) or manifesto.sha256_do_arquivo(caminho) != m["sha256"]:
        return "instalador não confere com o pacote"
    return ""


# ── 3. A versão nova ─────────────────────────────────────────────────────


def confirmar_na_partida(
    *,
    pastas: Pastas,
    versao_atual: str,
    contar: Callable[[str, str, str, str], None],
    log: Callable[[str], None] = lambda _m: None,
) -> str:
    """Chamado pela tarefa depois que o portal respondeu: a versão nova roda
    e alcança o portal, que é o que a confirmação afirma.

    `contar(resultado, de, para, detalhe)` faz o POST do evento ao portal.
    Depois de contar, o pedido sai do disco — exceto o INSTALADO confirmado,
    que o atualizador ainda está olhando: esse vira CONFIRMADO e quem apaga é
    a próxima partida.
    """
    pedido = ler_json(pastas.pedido)
    if not isinstance(pedido, dict):
        return "sem pedido"
    estado = pedido.get("estado")

    if estado in (INSTALANDO, INSTALADO) and pedido.get("para") == versao_atual:
        pedido.update(estado=CONFIRMADO, confirmado_em=_agora())
        gravar_json(pastas.pedido, pedido)
        contar("atualizou", pedido.get("de", ""), versao_atual, "")
        log(f"Atualização para {versao_atual} confirmada.")
        return CONFIRMADO

    if estado == VOLTOU and pedido.get("de") == versao_atual:
        contar("voltou", pedido.get("para", ""), versao_atual, pedido.get("detalhe", ""))
    elif estado == FALHOU:
        contar("falhou", pedido.get("de", ""), pedido.get("para", ""), pedido.get("detalhe", ""))
    elif estado in (BAIXADO, INSTALANDO, INSTALADO):
        # Pedido de outra versão ainda em curso: não é desta versão mexer.
        return "pedido de outra versão"

    os.remove(pastas.pedido)
    return estado or "pedido sem estado"
