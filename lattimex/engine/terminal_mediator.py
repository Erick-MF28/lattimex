from __future__ import annotations

from typing import Any, Iterable

from contracts import options_for_variant
from loading3d import LoadingOptions

# Adaptadores de peticion que usa engine_runtime. La mediacion con flota fija
# vive en engine_runtime._mediar.


def _items_by_customer(source: dict[str, Any]) -> dict[int, list[dict[str, Any]]]:
    result: dict[int, list[dict[str, Any]]] = {}
    for item in source.get("items") or []:
        customer = int(item["customer_id"])
        result.setdefault(customer, []).append({
            "id": item["id"],
            "guideId": item["id"],
            "trackingCode": item["id"],
            "clientIndex": customer,
            "dimensionsCm": list(item["dimensions_cm"]),
            "volumeCm3": float(item["volume_cm3"]),
            "weightKg": float(item["weight_kg"]),
            "fragile": bool(item.get("fragile")),
            "stackable": bool(item.get("stackable", True)),
            "keepUpright": bool(item.get("keep_upright", False)),
            "externalId": item.get("external_id"),
            "externalTypeId": item.get("external_type_id"),
        })
    return result


def route_request(
    source: dict[str, Any],
    route: list[int],
    route_index: int,
    item_index: dict[int, list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    item_index = item_index or _items_by_customer(source)
    base = source["vehicle"]
    vehicle = {
        "id": f"{source['name']}-V{route_index + 1}",
        "name": f"{source['name']} V{route_index + 1}",
        "capacity": float(base["capacity"]),
        "maxWeightKg": float(base["maxWeightKg"]),
        "cargoDimensions": list(base["cargoDimensions"]),
    }
    return {
        "contract": "pen3q.3l.loading.request.v1",
        "instance": source["name"],
        "routeId": f"{source['name']}-R{route_index + 1}",
        "vehicle": vehicle,
        "deliveryOrder": list(route),
        "items": [dict(item) for customer in route for item in item_index.get(customer, [])],
    }


def _loading_options(variant: str, max_restarts: int) -> LoadingOptions:
    options = options_for_variant(variant)
    return LoadingOptions(
        max_restarts=max(1, int(max_restarts)),
        support_ratio=float(options["supportRatio"]),
        enforce_unload_order=bool(options["enforceUnloadOrder"]),
        orientation_policy=str(options["orientationPolicy"]),
        enforce_fragility=bool(options["enforceFragility"]),
    )


def average_utilization(reports: Iterable[dict[str, Any]]) -> float:
    values = [
        (float(report.get("totalVolumeCm3") or 0), float(report.get("physicalCapacityCm3") or 0))
        for report in reports
    ]
    capacity = sum(value[1] for value in values if value[1] > 0)
    return sum(value[0] for value in values if value[1] > 0) / capacity if capacity > 0 else 0.0


def acceptance_rate(reports: Iterable[dict[str, Any]]) -> float:
    values = list(reports)
    return (
        sum(report.get("status") == "heuristic-feasible" for report in values) / len(values)
        if values else 0.0
    )
