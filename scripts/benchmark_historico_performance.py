#!/usr/bin/env python3
"""
Benchmark do pipeline de Histórico/Vencidos (agregação em memória).

Não usa Supabase: simula snapshots com a mesma função `_historico_merge_snapshot_into_agregados`
usada na API. Objectivo: comparar custo (~CPU + linhas tocadas) alinhado ao vosso cenário:

- cada pedido ao histórico / vencidos reprocessa até `limite_snapshots` snapshots;
- trabalho dominante ≈ Σ |items| de cada snapshot lido (+ sort no mapa final).

Execução: a partir da raiz do projeto:
  python scripts/benchmark_historico_performance.py

Saída: tempos médios + recomendação de env `HISTORICO_LIMITE_SNAPSHOTS` por orçamento de ms.
"""

from __future__ import annotations

import os
import sys
import time
import tracemalloc
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Tuple


def _setup_path() -> None:
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    if root not in sys.path:
        sys.path.insert(0, root)


def _snap_item(seed: int) -> Dict[str, Any]:
    """Uma linha semelhante ao JSON do agente (campos usados pelo merge)."""
    return {
        "file_name": f"cert_{seed % 30000:05d}.pfx",
        "nome": f"Titular exemplo {seed % 500}",
        "display_name": "",
        "status": "expirado" if seed % 11 == 0 else "ok",
        "documento_formatado": f"{seed % 999999:014d}",
        "documento_numero": None,
        "not_after": "2026-12-31T23:59:59+00:00",
    }


def build_snapshots(
    limite_snapshots: int,
    items_por_snapshot: int,
    universo_certificados: int,
) -> List[Dict[str, Any]]:
    """
    Snapshots ordenados como no Supabase (mais recente primeiro).
    `universo_certificados` controla sobreposição entre snapshots (pool de file_name distintos).
    """
    u = max(1, universo_certificados)
    pool = [_snap_item(i) for i in range(u)]
    snaps = []
    base = datetime(2026, 1, 15, tzinfo=timezone.utc)
    for s in range(limite_snapshots):
        scanned = base - timedelta(hours=s * 8)
        items = []
        for k in range(items_por_snapshot):
            tmpl = dict(pool[(s * 97 + k) % u])
            items.append(tmpl)
        snaps.append({"scanned_at": scanned.isoformat(), "items": items})
    return snaps


def run_pipeline_once(
    snapshots: List[Dict[str, Any]],
    merge_fn: Callable[[dict, Dict[str, dict]], None],
    viz_fn: Callable[[Dict[str, dict]], List[dict]],
    filtrar_fn: Callable[[List[dict], str], List[dict]],
) -> Tuple[int, int, Dict[str, dict]]:
    agregados: Dict[str, dict] = {}
    trabalho_itens = 0
    for snap in snapshots:
        merge_count = len(snap.get("items") or [])
        trabalho_itens += merge_count
        merge_fn(snap, agregados)
    linhas = viz_fn(agregados)
    linhas_filtradas = filtrar_fn(linhas, "")
    _ = linhas_filtradas[:10]
    return trabalho_itens, len(linhas), agregados


def medir(fn: Callable[[], Any], aquecimento: int = 1, repeticoes: int = 3) -> Tuple[float, Any]:
    for _ in range(aquecimento):
        resultado = fn()
    tempos = []
    for _ in range(repeticoes):
        t0 = time.perf_counter()
        resultado = fn()
        tempos.append(time.perf_counter() - t0)
    return sum(tempos) / len(tempos), resultado


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
    _setup_path()
    from app.main import (  # noqa: WPS433
        _historico_filtrar_busca,
        _historico_itens_visualizacao,
        _historico_merge_snapshot_into_agregados,
    )

    def run_once(snaps: List[Dict[str, Any]]) -> Tuple[int, int, Dict[str, dict]]:
        return run_pipeline_once(
            snaps,
            _historico_merge_snapshot_into_agregados,
            _historico_itens_visualizacao,
            _historico_filtrar_busca,
        )

    cenários = [
        # (rótulo, limite_snapshots, items/snap, pool certificados)
        ("pesado (muitos itens)", 120, 400, 280),
        ("médio (típico inventário médio)", 200, 200, 280),
        ("leve (limite menor)", 100, 200, 280),
        ("stress 500 snaps × 350 itens", 500, 350, 300),
        ("pool pequeno (muitos choques mesmo ficheiro)", 200, 250, 80),
    ]

    print("Benchmark Analise CertiDigital — pipeline agregação histórico\n")
    print(
        "| Cenário | Snaps | Itens/snap | ~Itens lidos | Chaves únicas | ms médio "
        "| Memória Pico (KB) |\n|---|---:|---:|---:|---:|---:|---:|"
    )

    orcamentos_ms = [100, 300, 800, 2000]

    linhas_benchmark: List[Tuple[str, int, int, int, float, float]] = []

    for rotulo, lim, ipp, pool in cenários:
        snaps = build_snapshots(lim, ipp, pool)

        t_mean, (_it_total, _n_linhas, ag) = medir(lambda: run_once(snaps))
        tracemalloc.start()
        run_once(snaps)
        _cur, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        itens_total = lim * ipp
        ms_mean = t_mean * 1000
        linhas_benchmark.append((rotulo, lim, ipp, itens_total, ms_mean, peak / 1024))
        print(
            f"| {rotulo} | {lim} | {ipp} | ~{itens_total} "
            f"| {len(ag)} | {ms_mean:.1f} | {peak / 1024:.0f} |"
        )

    print("\n### Conclusão (cenário sintético, mesma ordem do código real)\n")
    print(
        "- **Custo domina pela soma** de itens lidos em cada snapshot. "
        "Reduzir `HISTORICO_LIMITE_SNAPSHOTS` reduz proporcionalmente o trabalho até ao teto.",
    )
    print(
        "- **Paginação UI** só corta JSON; cada pedido volta a pagar o mesmo merge no servidor.",
    )
    print(
        "- **Overlap** entre snapshots (pool pequeno) altera só o número de chaves únicas finais "
        "**não** o número de itens percorridos (continua igual).",
    )
    print("\n### Sugestão de env `HISTORICO_LIMITE_SNAPSHOTS` por orçamento de latência média\n")
    print(
        "(Apenas **CPU**, sem tempo de rede/Supabase/deserialização HTTP — produto será mais lento.)\n"
    )

    maior_vol = max(linhas_benchmark, key=lambda x: x[3])
    nome_mx, lim_mx, ipp_mx, vol_mx, ms_mx, mem_mx = maior_vol
    pico_observado_ms = max(r[4] for r in linhas_benchmark)
    sla_minimo = min(orcamentos_ms)
    if pico_observado_ms <= sla_minimo:
        print(
            f"Nestes dados sintéticos, **todo** o CPU do merge ficou abaixo de **{sla_minimo} ms** "
            f"(pico observado nesta corrida: **~{pico_observado_ms:.1f} ms**).\n\n"
            f"- **Referência (maior volume simulado)**: `{nome_mx}` (~{vol_mx} itens lidos, "
            f"{lim_mx} snaps × {ipp_mx} itens): **~{ms_mx:.1f} ms**, pico **~{mem_mx:.0f} KB**.",
        )
        print(
            "\n  Para decidir `HISTORICO_LIMITE_SNAPSHOTS` em produção, use sobretudo **latência real** "
            "(rede + Supabase) e a percentagem de ganho ao reduzir limite nas linhas abaixo; "
            "este script só isola custo CPU do merge.",
        )
    else:
        print("Orçamentos possíveis (maior volumetria simulada que ainda cabe em cada SLA):\n")
        for b in sorted(orcamentos_ms):
            candidatos = [row for row in linhas_benchmark if row[4] <= b]
            if not candidatos:
                print(
                    f"- **≤ {b} ms CPU**: nenhum cenário desta corrida cabe — reduza snaps/itens no script.",
                )
                continue
            nome, lim, ipp, vol, ms, mem = max(candidatos, key=lambda x: x[3])
            print(
                f"- **≤ {b} ms CPU**: maior volume simulado a caber: ~{vol} linhas "
                f"({lim} snaps × {ipp} itens, `{nome}`, ~{ms:.1f} ms, pico ~{mem:.0f} KB).",
            )

    ipp_fixo = 200
    pool_fixo = 280
    for lim_maior, lim_menor in [(200, 120), (500, 200)]:
        snaps_maior = build_snapshots(lim_maior, ipp_fixo, pool_fixo)
        snaps_menor = build_snapshots(lim_menor, ipp_fixo, pool_fixo)
        t_maior, _ = medir(lambda: run_once(snaps_maior), repeticoes=8)
        t_menor, _ = medir(lambda: run_once(snaps_menor), repeticoes=8)
        ganho = (1 - (t_menor / t_maior)) * 100 if t_maior > 0 else 0.0
        print(
            f"\nReduzir `HISTORICO_LIMITE_SNAPSHOTS`: **{lim_maior} → {lim_menor}** "
            f"({ipp_fixo} itens/snap sintéticos): média CPU "
            f"**{t_maior * 1000:.1f} ms** → **{t_menor * 1000:.1f} ms** (**~{ganho:.0f}%** menos tempo)."
        )


if __name__ == "__main__":
    os.environ.setdefault("HISTORICO_LIMITE_SNAPSHOTS", "500")
    main()
