"""M1 · Capacidad volumetrica EFECTIVA para el routing (modulo aditivo).

No modifica ningun modulo existente. Produce una copia del `source` normalizado
con la capacidad volumetrica del vehiculo multiplicada por un factor de empaque
`alpha` calibrado por variante, de modo que `cpp_terminal.solve_terminal_routing`
(sin cambios) construya rutas que el empacador 3D pueda aceptar casi siempre.

Procedencia de los alphas por defecto: percentil 75 de la ocupacion volumetrica
POR RUTA ACEPTADA (`loading_reports[].utilization`, status heuristic-feasible)
del brazo integrado en el checkpoint parcial de `phase2_formal_terminal_w4`
(2026-07-26, instancias 3l_cvrp01-06, n=184..204 rutas por variante). Ver
`results/EVALUACION_RENDIMIENTO_3L_20260726.md`, mejora M1.
"""
from __future__ import annotations

import copy
import json
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any

# p75 de ocupacion por ruta aceptada, por variante (checkpoint parcial formal).
DEFAULT_ALPHAS: dict[str, float] = {
    "all-constraints": 0.51,
    "loading-only": 0.59,
    "fragility-only": 0.54,
    "support-only": 0.55,
    "no-fragility": 0.50,
    "no-lifo": 0.54,
    "no-support": 0.54,
}
FALLBACK_ALPHA = 0.55


def alpha_for(variant: str, overrides: dict[str, float] | None = None) -> float:
    table = dict(DEFAULT_ALPHAS)
    if overrides:
        table.update(overrides)
    return float(table.get(variant, FALLBACK_ALPHA))


def effective_source(source: dict[str, Any], variant: str,
                     overrides: dict[str, float] | None = None) -> tuple[dict[str, Any], float]:
    """Copia profunda del source con capacidad volumetrica alpha*V.

    El source ORIGINAL debe seguir usandose para: distancias reportadas,
    verificacion dual final, empaque 3D y validacion externa. El source
    efectivo es SOLO para el motor de routing.
    """
    import math
    alpha = alpha_for(variant, overrides)
    eff = copy.deepcopy(source)
    eff["vehicle"]["capacity"] = float(source["vehicle"]["capacity"]) * alpha
    # La flota "available" de Gendreau es un hint de entrada, no una cota del
    # problema (la metrica lexicografica ya castiga vehiculos). Con capacidad
    # efectiva reducida hay que relajarla para que la particion dual interna
    # de cpp_terminal siempre tenga solucion; el conteo real de vehiculos se
    # toma de las rutas finales.
    nominal_fleet = int(source["vehicle"].get("available", 1))
    eff["vehicle"]["available"] = max(nominal_fleet, math.ceil(nominal_fleet / alpha) + 1)
    eff["_effective_capacity"] = {
        "alpha": alpha,
        "variant": variant,
        "nominal_capacity": float(source["vehicle"]["capacity"]),
        "nominal_fleet": nominal_fleet,
        "relaxed_fleet": eff["vehicle"]["available"],
    }
    return eff, alpha


def recalibrate_from_partial(jsonl_path: Path, percentile: float = 0.75,
                             integrated_config: str = "SENDA+PE+Mediator") -> dict[str, float]:
    """Recalcula alphas desde un raw_runs(.partial).jsonl.

    Estadistico: percentil de `utilization` sobre rutas con status
    heuristic-feasible del brazo integrado. Devuelve {variante: alpha}.
    """
    per_variant: dict[str, list[float]] = defaultdict(list)
    with open(jsonl_path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line.endswith("}"):
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("config") != integrated_config:
                continue
            for report in row.get("loading_reports") or []:
                if report.get("status") == "heuristic-feasible" and report.get("utilization"):
                    per_variant[row["variant"]].append(float(report["utilization"]))
    out: dict[str, float] = {}
    for variant, values in per_variant.items():
        values.sort()
        idx = min(len(values) - 1, int(len(values) * percentile))
        out[variant] = round(values[idx], 2)
    return out


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        print(json.dumps(recalibrate_from_partial(Path(sys.argv[1])), indent=2))
    else:
        print(json.dumps(DEFAULT_ALPHAS, indent=2))
