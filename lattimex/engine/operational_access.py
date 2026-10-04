# -*- coding: utf-8 -*-
"""Validador de acceso operacional para descarga por tres puertas.

No exige una cadena LIFO global. Para cada entrega elige la mejor salida entre
puerta trasera y puertas laterales, y calcula el cierre de paquetes que deben
retirarse temporalmente para liberar el objetivo sin desarmar una pila.
"""
from __future__ import annotations

import math
from collections import Counter
from typing import Any, Iterable


EPS = 1e-6
DOORS = ("rear", "left", "right")


def _overlap(a0: float, a1: float, b0: float, b1: float) -> bool:
    return a0 < b1 - EPS and a1 > b0 + EPS


def _projection_overlap(left: dict[str, Any], right: dict[str, Any], axes: str) -> bool:
    dimensions = {
        "x": ("x", "lengthCm"),
        "y": ("y", "widthCm"),
        "z": ("z", "heightCm"),
    }
    return all(
        _overlap(
            float(left[position]),
            float(left[position]) + float(left[size]),
            float(right[position]),
            float(right[position]) + float(right[size]),
        )
        for position, size in (dimensions[axis] for axis in axes)
    )


def _directional_blocker(
    focus: dict[str, Any], candidate: dict[str, Any], door: str,
) -> bool:
    if door == "rear":
        return (
            float(candidate["x"])
            >= float(focus["x"]) + float(focus["lengthCm"]) - EPS
            and _projection_overlap(focus, candidate, "yz")
        )
    if door == "left":
        return (
            float(candidate["y"]) + float(candidate["widthCm"])
            <= float(focus["y"]) + EPS
            and _projection_overlap(focus, candidate, "xz")
        )
    if door == "right":
        return (
            float(candidate["y"])
            >= float(focus["y"]) + float(focus["widthCm"]) - EPS
            and _projection_overlap(focus, candidate, "xz")
        )
    raise ValueError(f"puerta desconocida: {door}")


def _directly_supported_by(support: dict[str, Any], item: dict[str, Any]) -> bool:
    """Indica si ``item`` toca por arriba al paquete que se retirará."""
    return (
        abs(
            float(support["z"]) + float(support["heightCm"]) - float(item["z"])
        ) <= EPS
        and _projection_overlap(support, item, "xy")
    )


def blocker_closure(
    target: dict[str, Any], placements: Iterable[dict[str, Any]], door: str,
) -> list[dict[str, Any]]:
    """Paquetes aún a bordo que deben moverse para extraer ``target``.

    El cierre es conservador: además del primer obstáculo incluye lo que bloquea
    su propia salida por la misma puerta y cualquier paquete situado encima.
    """
    target_rank = int(target["deliveryRank"])
    remaining = [
        value for value in placements
        if int(value["deliveryRank"]) > target_rank
    ]
    moved: dict[str, dict[str, Any]] = {}
    frontier = [target]
    while frontier:
        focus = frontier.pop()
        for candidate in remaining:
            guide_id = str(candidate["guideId"])
            if guide_id in moved:
                continue
            if (_directional_blocker(focus, candidate, door)
                    or _directly_supported_by(focus, candidate)):
                moved[guide_id] = candidate
                frontier.append(candidate)
    return list(moved.values())


def _percentile_nearest_rank(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, math.ceil(percentile * len(ordered)) - 1))
    return ordered[index]


def _removal_order(items: list[dict[str, Any]], door: str) -> list[str] | None:
    """Topological extraction order, including deliveries between temporary moves."""
    pending = {str(item["guideId"]): item for item in items}
    order = []
    while pending:
        ready = sorted(gid for gid, item in pending.items() if not any(
            other_id != gid and (_directional_blocker(item, other, door)
                                 or _directly_supported_by(item, other))
            for other_id, other in pending.items()))
        if not ready:
            return None
        for gid in ready:
            order.append(gid)
            del pending[gid]
    return order


def evaluate_stops(placements: list[dict[str, Any]], max_temporary_moves: int = 3,
                   doors: Iterable[str] | None = None) -> dict[str, Any]:
    """One door and union of blockers for ALL packages delivered at a stop.

    Counts distinct temporarily removed packages, not lift/return actions.
    Geometry is evaluated independently at each stop under the existing local
    restow model. Door aperture and physical restow positions are not modeled.
    """
    declared = list(doors) if doors is not None else ["rear"]
    usable = [d for d in DOORS if d in declared]
    if not usable:
        raise ValueError("No hay puertas validas para evaluar la descarga")
    ids = [str(p["guideId"]) for p in placements]
    if len(ids) != len(set(ids)):
        raise ValueError("Identificadores de paquete duplicados")
    plan = []
    for rank in sorted({int(p["deliveryRank"]) for p in placements}):
        targets = [p for p in placements if int(p["deliveryRank"]) == rank]
        target_ids = {str(p["guideId"]) for p in targets}
        candidates = []
        for door in usable:
            moved = {}
            details = []
            for target in targets:
                blockers = blocker_closure(target, placements, door)
                moved.update((str(b["guideId"]), b) for b in blockers)
                details.append({"guia": str(target["guideId"]),
                                "bloqueadores": sorted(str(b["guideId"]) for b in blockers)})
            order = _removal_order(targets + list(moved.values()), door)
            weight = sum(float(p.get("weightKg") or 0) for p in moved.values())
            volume = sum(float(p.get("volumeCm3") or 0) for p in moved.values())
            record = {
                "cliente": int(targets[0]["clientIndex"]), "puerta": door,
                "entregar": sorted(target_ids),
                "mover": [gid for gid in order if gid in moved] if order is not None else sorted(moved),
                "movimientos": len(moved), "orden_resuelto": order is not None,
                "pasos": [{"accion": "entregar" if gid in target_ids else "apartar", "guia": gid}
                          for gid in (order or [])],
                "detalle_bultos": details,
                "peso_temporal_kg": round(weight, 3), "volumen_temporal_cm3": round(volume, 3),
                "aviso_manipulacion": weight > 25 or volume > 150_000,
            }
            candidates.append(((order is None, len(moved) > max_temporary_moves,
                                len(moved), volume, weight, DOORS.index(door)), record))
        plan.append(min(candidates, key=lambda c: c[0])[1])
    excess = [p["cliente"] for p in plan if p["movimientos"] > max_temporary_moves]
    unresolved = [p["cliente"] for p in plan if not p["orden_resuelto"]]
    return {
        "evaluado": True, "factible": not excess and not unresolved,
        "modelo": "parada-union-v2", "max_movimientos": max_temporary_moves,
        "puertas_disponibles": usable, "entregas": len(plan),
        "entregas_con_exceso": excess, "entregas_sin_orden": unresolved,
        "entregas_sin_movimientos": sum(p["movimientos"] == 0 and p["orden_resuelto"] for p in plan),
        "movimientos_max": max((p["movimientos"] for p in plan), default=0),
        "puertas": dict(Counter(p["puerta"] for p in plan)), "plan": plan,
        "recolocacion": "local-despues-de-cada-parada",
        "alcance": "extraccion-direccional-sin-modelo-de-hueco-ni-recolocacion-fisica",
    }


def evaluate_access(
    placements: list[dict[str, Any]],
    max_temporary_moves: int = 3,
    max_temporary_volume_cm3: float = 150_000.0,
    max_temporary_weight_kg: float = 25.0,
    support_ratio: float = 0.8,
    doors: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Evalúa accesibilidad y produce un plan de descarga operable.

    ``doors`` son las puertas que EXISTEN en la unidad. Un plan que use una
    puerta inexistente no es ejecutable, así que el motor solo debe pasar las
    declaradas por el cliente; el valor por omisión conserva las tres para no
    cambiar el comportamiento de quien ya llamaba a esta función.
    """
    usable = [door for door in (doors if doors is not None else DOORS) if door in DOORS]
    if not usable:
        usable = ["rear"]
    plan: list[dict[str, Any]] = []
    for target in sorted(placements, key=lambda value: int(value["deliveryRank"])):
        candidates: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
        for door in usable:
            moved = blocker_closure(target, placements, door)
            volume = sum(float(value.get("volumeCm3") or 0.0) for value in moved)
            weight = sum(float(value.get("weightKg") or 0.0) for value in moved)
            record = {
                "guideId": str(target["guideId"]),
                "deliveryRank": int(target["deliveryRank"]),
                "door": door,
                "temporaryMoves": [str(value["guideId"]) for value in moved],
                "temporaryMoveCount": len(moved),
                "temporaryVolumeCm3": round(volume, 3),
                "temporaryWeightKg": round(weight, 3),
            }
            hard_violation = int(len(moved) > max_temporary_moves)
            key = (hard_violation, len(moved), volume, weight, DOORS.index(door))
            candidates.append((key, record))
        _, chosen = min(candidates, key=lambda value: value[0])
        # La modificación del acomodo se mide por piezas desplazadas. Volumen y
        # peso quedan como alerta ergonómica: no convierten por sí solos una
        # extracción geométricamente simple en una ruta no factible.
        chosen["withinOperationalLimit"] = bool(
            chosen["temporaryMoveCount"] <= max_temporary_moves
        )
        chosen["manualHandlingAdvisory"] = bool(
            chosen["temporaryVolumeCm3"] > max_temporary_volume_cm3 + EPS
            or chosen["temporaryWeightKg"] > max_temporary_weight_kg + EPS
        )
        plan.append(chosen)

    counts = [float(value["temporaryMoveCount"]) for value in plan]
    volumes = [float(value["temporaryVolumeCm3"]) for value in plan]
    weights = [float(value["temporaryWeightKg"]) for value in plan]
    violations = [value for value in plan if not value["withinOperationalLimit"]]
    advisories = [value for value in plan if value["manualHandlingAdvisory"]]
    return {
        "feasible": not violations,
        "policy": {
            "doors": list(usable),
            "maxTemporaryMovesPerDelivery": int(max_temporary_moves),
            "maxTemporaryVolumeCm3PerDelivery": float(max_temporary_volume_cm3),
            "maxTemporaryWeightKgPerDelivery": float(max_temporary_weight_kg),
            "verticalClosure": True,
            "recursiveDoorClosure": True,
            "directSupportClosure": True,
            "restowModel": "local-after-each-delivery",
        },
        "deliveryPlan": plan,
        "metrics": {
            "deliveries": len(plan),
            "violatingDeliveries": len(violations),
            "manualHandlingAdvisories": len(advisories),
            "zeroMoveDeliveries": sum(value == 0 for value in counts),
            "totalTemporaryMoves": int(sum(counts)),
            "p90TemporaryMoves": int(_percentile_nearest_rank(counts, 0.90)),
            "p95TemporaryMoves": int(_percentile_nearest_rank(counts, 0.95)),
            "maxTemporaryMoves": int(max(counts, default=0)),
            "p90TemporaryVolumeCm3": round(_percentile_nearest_rank(volumes, 0.90), 3),
            "maxTemporaryVolumeCm3": round(max(volumes, default=0.0), 3),
            "p90TemporaryWeightKg": round(_percentile_nearest_rank(weights, 0.90), 3),
            "maxTemporaryWeightKg": round(max(weights, default=0.0), 3),
            "doorUsage": dict(Counter(value["door"] for value in plan)),
        },
    }


def access_key(report: dict[str, Any]) -> tuple[Any, ...]:
    """Orden lexicográfico para elegir el acomodo menos intrusivo."""
    metrics = report["metrics"]
    return (
        int(not report["feasible"]),
        int(metrics["maxTemporaryMoves"]),
        int(metrics["violatingDeliveries"]),
        int(metrics["p95TemporaryMoves"]),
        int(metrics["totalTemporaryMoves"]),
        float(metrics["maxTemporaryVolumeCm3"]),
        float(metrics["maxTemporaryWeightKg"]),
    )
