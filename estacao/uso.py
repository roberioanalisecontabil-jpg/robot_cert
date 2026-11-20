"""Coleta do uso dos certificados (Frente C): no vigia SYSTEM a cada 5 min
(1.5.2) e na tarefa SYSTEM (partida e 6 h).

Liga a auditoria "System Integrity", lê os eventos 5061 novos do log de
Segurança e manda ao portal. O marcador (maior EventRecordID aceito) fica na
pasta trancada da atualização: uma pessoa comum não pode editá-lo para
esconder um uso. Nunca abre a chave privada: o contêiner vem do próprio evento.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import os
from typing import List

from estacao.repositorio import _powershell

logger = logging.getLogger("estacao.uso")

# "System Integrity": é a subcategoria que emite o 5061 ("Other System Events" só traz 5058/5059).
GUID_AUDITORIA = "{0CCE9212-69AE-11D9-BED3-505054503030}"
PROVEDOR = "Microsoft Software Key Storage Provider"
LOTE = 2000
_SEM_AUDITORIA = ("no auditing", "sem auditoria")


def marcador() -> str:
    from estacao import tarefa

    return os.path.join(tarefa.pastas().raiz, "uso-marcador.json")


def _ler_marcador() -> int:
    try:
        with open(marcador(), encoding="utf-8") as f:
            return max(0, int(json.load(f)["record_id"]))
    except (OSError, ValueError, KeyError, TypeError):
        return 0


def _gravar_marcador(record_id: int) -> None:
    with open(marcador(), "w", encoding="utf-8") as f:
        json.dump({"record_id": record_id}, f)


def ligar_auditoria(executar=_powershell) -> str:
    """Pelo GUID, nunca pelo nome: o nome da subcategoria muda com o idioma."""
    try:
        # Entre aspas: no PowerShell, `{...}` solto é bloco de script e o auditpol
        # recebia o argumento quebrado (só mostrava a ajuda, até a 1.5.1).
        executar(f"auditpol /set '/subcategory:{GUID_AUDITORIA}' /success:enable /failure:enable")
        r = executar(f"auditpol /get '/subcategory:{GUID_AUDITORIA}' /r")
        saida = r.stdout or ""
        # A linha da subcategoria, achada pelo GUID: pelo PowerShell a saída vem
        # com linhas em branco entre as de texto, e a 2ª linha não era a dela
        # (IndexError em toda coleta até a 1.5.1). O cabeçalho vem traduzido: a
        # configuração de inclusão é a 5ª coluna, por posição.
        linha = next((l for l in csv.reader(io.StringIO(saida))
                      if len(l) > 4 and l[3].strip().upper() == GUID_AUDITORIA), None)
        if linha is None:
            logger.warning("auditpol sem a linha da auditoria: %r", saida[:300])
            return "desconhecida"
        valor = linha[4].strip().lower()
    except Exception:
        logger.warning("Não foi possível conferir a auditoria.", exc_info=True)
        return "desconhecida"
    return "desligada" if not valor or valor in _SEM_AUDITORIA else "ligada"


def _maior_record(executar) -> int | None:
    """Maior EventRecordID do log; None se não deu para ler."""
    r = executar(
        "(Get-WinEvent -LogName Security -MaxEvents 1 -ErrorAction SilentlyContinue).RecordId"
    )
    try:
        return int((r.stdout or "").strip())
    except ValueError:
        return None


def ler_eventos(desde_record: int, executar=_powershell) -> List[dict]:
    if desde_record > 0:
        filtro = f"EventID=5061 and EventRecordID>{int(desde_record)}"
    else:  # primeira coleta da máquina: 7 dias
        filtro = "EventID=5061 and TimeCreated[timediff(@SystemTime) <= 604800000]"
    script = (
        "[Console]::OutputEncoding = [Text.Encoding]::UTF8; "
        f"$r = @(Get-WinEvent -LogName Security -FilterXPath '*[System[{filtro}]]' -ErrorAction SilentlyContinue | "
        "ForEach-Object { $d = @{}; foreach ($n in ([xml]$_.ToXml()).Event.EventData.Data) { $d[$n.Name] = $n.'#text' }; "
        f"if ($d.ProviderName -eq '{PROVEDOR}' -and $d.ReturnCode -eq '0x0') {{ "
        "[pscustomobject]@{ record_id = [int64]$_.RecordId; quando = $_.TimeCreated.ToUniversalTime().ToString('o'); "
        "sid = $d.SubjectUserSid; usuario = $d.SubjectUserName; conteiner = $d.KeyName } } }); "
        "if ($r.Count -gt 0) { ConvertTo-Json -InputObject $r -Compress }"
    )
    r = executar(script)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or "").strip()[:300] or f"codigo {r.returncode}")
    texto = (r.stdout or "").strip()
    if not texto:
        return []
    dados = json.loads(texto)
    if isinstance(dados, dict):  # ConvertTo-Json desembrulha lista de um item
        dados = [dados]
    return sorted(dados, key=lambda e: e["record_id"])


def _limpar(s: str) -> str:
    """Surrogate solto vira U+FFFD: o Postgres do portal o rejeitaria e o lote inteiro falharia."""
    return s.encode("utf-16", "surrogatepass").decode("utf-16", "replace")


def _anexar_janelas(lote: List[dict]) -> List[dict]:
    """Acrescenta `janelas` a cada evento; qualquer falha de leitura deixa [] e a coleta segue."""
    from datetime import datetime

    from estacao import janelas, tarefa

    def quando(e: dict) -> datetime:
        return datetime.fromisoformat(str(e["quando"]).replace("Z", "+00:00"))

    ate: dict = {}
    for e in lote:
        try:
            ate[e["sid"]] = max(ate.get(e["sid"], quando(e)), quando(e))
        except (ValueError, KeyError, TypeError):
            pass
    registro: dict = {}
    for sid, t in ate.items():
        try:
            registro[sid] = janelas.ler(tarefa.pastas().raiz, sid, t)
        except Exception:
            logger.warning("Não foi possível ler as janelas de %s.", sid, exc_info=True)
    saida = []
    for e in lote:
        try:
            achadas = janelas.janelas_do_evento(registro.get(e["sid"], []), quando(e))
            achadas = [{**j, "programa": _limpar(j["programa"]), "titulo": _limpar(j["titulo"])} for j in achadas]
        except Exception:
            logger.warning("Janelas do evento %s descartadas.", e.get("record_id"), exc_info=True)
            achadas = []
        saida.append({**e, "janelas": achadas})
    return saida


TRAVA = "uso.lock"


def coletar_travado(http, executar=_powershell) -> int | None:
    """`coletar` com a trava da pasta trancada: o vigia (a cada 5 min) e a
    tarefa (partida e 6 h) não coletam juntos — os dois leriam o mesmo marcador
    e mandariam o mesmo lote. None se a outra já está coletando."""
    import msvcrt

    from estacao import anotador, tarefa

    fd = anotador._travar(os.path.join(tarefa.pastas().raiz, TRAVA))
    if fd is None:
        logger.info("Outra coleta do uso em curso; esta fica para a próxima.")
        return None
    try:
        return coletar(http, executar)
    finally:
        try:
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        finally:
            os.close(fd)


def coletar(http, executar=_powershell) -> int:
    """Devolve o total enviado. O marcador só avança depois de o portal aceitar."""
    from estacao import bandeja, chave_maquina
    from estacao.tarefa import portal

    chave = chave_maquina.ler()
    if not chave:
        logger.warning("Sem chave da máquina; coleta de uso adiada.")
        return 0
    auditoria = ligar_auditoria(executar)
    desde = _ler_marcador()
    maior = _maior_record(executar)
    if maior is not None and maior < desde:  # log limpo: o marcador aponta para o nada
        logger.warning("Log de Segurança menor que o marcador (%s < %s); voltando a 7 dias.", maior, desde)
        desde = 0
    eventos = ler_eventos(desde, executar)
    enviados = 0
    # Sem eventos ainda se manda um lote vazio: é ele que conta ao portal o estado da auditoria.
    for i in range(0, max(len(eventos), 1), LOTE):
        lido = eventos[i:i + LOTE]
        # Evento sem sid ou contêiner faria o portal responder 422 para sempre: sai daqui,
        # mas o marcador passa por ele.
        lote = _anexar_janelas(
            [{**e, "usuario": e.get("usuario") or ""} for e in lido if e.get("sid") and e.get("conteiner")])
        r = http.post(f"{portal()}/api/estacao/uso", json={
            "machine_id": bandeja.machine_id(), "chave": chave, "auditoria": auditoria, "eventos": lote})
        r.raise_for_status()
        enviados += len(lote)
        if lido:
            _gravar_marcador(lido[-1]["record_id"])
    return enviados
