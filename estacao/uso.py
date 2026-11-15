"""Coleta do uso dos certificados (Frente C), na tarefa SYSTEM.

Liga a auditoria "Other System Events", lê os eventos 5061 novos do log de
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

GUID_AUDITORIA = "{0CCE9214-69AE-11D9-BED3-505054503030}"
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
        executar(f"auditpol /set /subcategory:{GUID_AUDITORIA} /success:enable /failure:enable")
        r = executar(f"auditpol /get /subcategory:{GUID_AUDITORIA} /r")
        linhas = list(csv.reader(io.StringIO(r.stdout or "")))
        # O cabeçalho vem traduzido: a configuração de inclusão é a 5ª coluna, por posição.
        valor = linhas[1][4].strip().lower()
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
    for i in range(0, len(eventos), LOTE):
        lote = eventos[i:i + LOTE]
        r = http.post(f"{portal()}/api/estacao/uso", json={
            "machine_id": bandeja.machine_id(), "chave": chave, "auditoria": auditoria, "eventos": lote})
        r.raise_for_status()
        enviados += len(lote)
        _gravar_marcador(lote[-1]["record_id"])
    return enviados
