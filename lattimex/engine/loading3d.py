from __future__ import annotations

import ctypes
import math
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

EPS = 1e-7


def _cargar_nativo():
    """Empacador C++ (pack3d.cpp): puerto 1:1 del bucle de colocacion.
    Si no existe o no carga, todo sigue en Python. LATTIMEX_PACK3D=ruta fuerza
    un binario; LATTIMEX_PACK3D_OFF=1 desactiva el nativo."""
    if os.environ.get("LATTIMEX_PACK3D_OFF") == "1":
        return None
    ruta = os.environ.get("LATTIMEX_PACK3D") or str(Path(__file__).with_name("liblattimex_pack3d.so"))
    try:
        lib = ctypes.CDLL(ruta)
    except OSError:
        return None
    fn = lib.lattimex_pack3d
    D = ctypes.POINTER(ctypes.c_double); I = ctypes.POINTER(ctypes.c_int32); B = ctypes.POINTER(ctypes.c_uint8)
    fn.restype = ctypes.c_int
    fn.argtypes = [ctypes.c_int, D, I, D, I, D, D, I, B, B, D, D, ctypes.c_int, ctypes.c_uint32,
                   ctypes.c_double, ctypes.c_int, ctypes.c_int,
                   I, I, D, D, I, B, I, I]
    return fn


_NATIVE = _cargar_nativo()


@dataclass(frozen=True)
class LoadingOptions:
    max_restarts: int = 8
    support_ratio: float = 0.8
    enforce_unload_order: bool = False
    orientation_policy: str = "all"
    enforce_fragility: bool = False


class _Mulberry32:
    """Adaptación de Mulberry32 (Tommy Ettinger, CC0-1.0), equivalente al generador C++.

    Original: https://gist.github.com/tommyettinger/46a874533244883189143505d203312c
    Dedicación: https://creativecommons.org/publicdomain/zero/1.0/
    """

    def __init__(self, seed: int):
        self.state = seed & 0xFFFFFFFF

    def random(self) -> float:
        self.state = (self.state + 0x6D2B79F5) & 0xFFFFFFFF
        value = self.state
        value = _imul(value ^ (value >> 15), value | 1)
        value ^= (value + _imul(value ^ (value >> 7), value | 61)) & 0xFFFFFFFF
        return ((value ^ (value >> 14)) & 0xFFFFFFFF) / 4294967296.0


def _imul(left: int, right: int) -> int:
    return (left * right) & 0xFFFFFFFF


def _unique_orientations(dimensions: Iterable[float], policy: str) -> list[dict[str, Any]]:
    a, b, c = (float(value) for value in dimensions)
    all_orientations = [
        ([a, b, c], 0), ([a, c, b], 1), ([b, a, c], 2),
        ([b, c, a], 3), ([c, a, b], 4), ([c, b, a], 5),
    ]
    raw = all_orientations[:1] if policy == "fixed" else (
        [all_orientations[0], all_orientations[2]] if policy == "horizontal" else all_orientations
    )
    seen: set[tuple[float, float, float]] = set()
    result = []
    for dimensions_value, orientation in raw:
        key = tuple(dimensions_value)
        if key not in seen:
            seen.add(key)
            result.append({"dimensions": dimensions_value, "orientation": orientation})
    return result


def _overlap_1d(a0: float, a1: float, b0: float, b1: float) -> bool:
    return min(a1, b1) - max(a0, b0) > EPS


def _boxes_overlap(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return (
        _overlap_1d(left["x"], left["x"] + left["lengthCm"], right["x"], right["x"] + right["lengthCm"])
        and _overlap_1d(left["y"], left["y"] + left["widthCm"], right["y"], right["y"] + right["widthCm"])
        and _overlap_1d(left["z"], left["z"] + left["heightCm"], right["z"], right["z"] + right["heightCm"])
    )


def _projection_yz_overlap(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return (
        _overlap_1d(left["y"], left["y"] + left["widthCm"], right["y"], right["y"] + right["widthCm"])
        and _overlap_1d(left["z"], left["z"] + left["heightCm"], right["z"], right["z"] + right["heightCm"])
    )


def _clipped_support_rect(box: dict[str, Any], item: dict[str, Any]) -> dict[str, Any] | None:
    if abs(box["z"] + box["heightCm"] - item["z"]) > EPS:
        return None
    x0 = max(box["x"], item["x"]); x1 = min(box["x"] + box["lengthCm"], item["x"] + item["lengthCm"])
    y0 = max(box["y"], item["y"]); y1 = min(box["y"] + box["widthCm"], item["y"] + item["widthCm"])
    if x1 - x0 <= EPS or y1 - y0 <= EPS:
        return None
    return {"x0": x0, "x1": x1, "y0": y0, "y1": y1, "box": box}


def _rectangle_union_area(rectangles: list[dict[str, Any]]) -> float:
    if not rectangles:
        return 0.0
    xs = sorted({value for rectangle in rectangles for value in (rectangle["x0"], rectangle["x1"])})
    area = 0.0
    for left, right in zip(xs, xs[1:]):
        if right - left <= EPS:
            continue
        intervals = sorted(
            (rectangle["y0"], rectangle["y1"])
            for rectangle in rectangles
            if rectangle["x0"] < right - EPS and rectangle["x1"] > left + EPS
        )
        if not intervals:
            continue
        start, end = intervals[0]; covered = 0.0
        for next_start, next_end in intervals[1:]:
            if next_start <= end + EPS:
                end = max(end, next_end)
            else:
                covered += end - start; start, end = next_start, next_end
        covered += end - start; area += (right - left) * covered
    return area


def _support_information(item: dict[str, Any], placed: list[dict[str, Any]]) -> dict[str, Any]:
    if item["z"] <= EPS:
        return {"ratio": 1.0, "supports": []}
    rectangles = [value for box in placed if (value := _clipped_support_rect(box, item)) is not None]
    area = _rectangle_union_area(rectangles)
    return {"ratio": area / (item["lengthCm"] * item["widthCm"]), "supports": [rectangle["box"] for rectangle in rectangles]}


def _inside_cargo(item: dict[str, Any], cargo: list[float]) -> bool:
    return (
        item["x"] >= -EPS and item["y"] >= -EPS and item["z"] >= -EPS
        and item["x"] + item["lengthCm"] <= cargo[0] + EPS
        and item["y"] + item["widthCm"] <= cargo[1] + EPS
        and item["z"] + item["heightCm"] <= cargo[2] + EPS
    )


def _sequence_compatible(candidate: dict[str, Any], placed: list[dict[str, Any]]) -> bool:
    for box in placed:
        if candidate["deliveryRank"] == box["deliveryRank"] or not _projection_yz_overlap(candidate, box):
            continue
        if candidate["deliveryRank"] < box["deliveryRank"]:
            if candidate["x"] < box["x"] + box["lengthCm"] - EPS:
                return False
        elif candidate["x"] + candidate["lengthCm"] > box["x"] + EPS:
            return False
    return True


def _contact_score(candidate: dict[str, Any], placed: list[dict[str, Any]], cargo: list[float]) -> int:
    contact = 0
    contact += int(candidate["x"] <= EPS or candidate["x"] + candidate["lengthCm"] >= cargo[0] - EPS)
    contact += int(candidate["y"] <= EPS or candidate["y"] + candidate["widthCm"] >= cargo[1] - EPS)
    contact += int(candidate["z"] <= EPS or candidate["z"] + candidate["heightCm"] >= cargo[2] - EPS)
    for box in placed:
        contact += int(abs(candidate["x"] - (box["x"] + box["lengthCm"])) <= EPS or abs(candidate["x"] + candidate["lengthCm"] - box["x"]) <= EPS)
        contact += int(abs(candidate["y"] - (box["y"] + box["widthCm"])) <= EPS or abs(candidate["y"] + candidate["widthCm"] - box["y"]) <= EPS)
        contact += int(abs(candidate["z"] - (box["z"] + box["heightCm"])) <= EPS or abs(candidate["z"] + candidate["heightCm"] - box["z"]) <= EPS)
    return contact


def _point_key(point: Iterable[float]) -> tuple[float, float, float]:
    return tuple(round(float(value), 3) for value in point)  # type: ignore[return-value]


def _candidate_positions(points: list[list[float]], dimensions: list[float], cargo: list[float]) -> list[list[float]]:
    length, width, _ = dimensions; positions: list[list[float]] = []; seen: set[tuple[float, float, float]] = set()
    for base in points:
        for raw in (
            [base[0], base[1], base[2]], [cargo[0] - length, base[1], base[2]],
            [base[0], 0.0, base[2]], [base[0], cargo[1] - width, base[2]],
            [base[0], base[1], 0.0], [cargo[0] - length, 0.0, base[2]],
            [cargo[0] - length, cargo[1] - width, base[2]],
        ):
            if min(raw) < -EPS:
                continue
            point = [max(0.0, value) for value in raw]; key = _point_key(point)
            if key not in seen:
                seen.add(key); positions.append(point)
    return positions


def _prune_points(points: list[list[float]], placed: list[dict[str, Any]], cargo: list[float]) -> list[list[float]]:
    result: list[list[float]] = []; seen: set[tuple[float, float, float]] = set()
    for point in points:
        if min(point) < -EPS or any(point[index] > cargo[index] + EPS for index in range(3)):
            continue
        inside = any(
            point[0] > box["x"] + EPS and point[0] < box["x"] + box["lengthCm"] - EPS
            and point[1] > box["y"] + EPS and point[1] < box["y"] + box["widthCm"] - EPS
            and point[2] > box["z"] + EPS and point[2] < box["z"] + box["heightCm"] - EPS
            for box in placed
        )
        key = _point_key(point)
        if not inside and key not in seen:
            seen.add(key); result.append(point)
    return result


def settle_placements(placements: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    """Asentado por gravedad: baja cada caja en z hasta tocar el piso o la caja
    mas alta bajo su huella. No cambia x/y ni orientacion. Devuelve la copia
    asentada y cuantas cajas bajaron. Con supportRatio 0 (loading-only) el
    empacador acepta cajas flotantes; el plan de carga que ve el operador no."""
    orden = sorted(range(len(placements)), key=lambda i: (placements[i]["z"], i))
    out = [dict(p) for p in placements]
    apoyadas: list[dict[str, Any]] = []
    bajadas = 0
    for i in orden:
        p = out[i]
        piso = 0.0
        for q in apoyadas:
            if (_overlap_1d(p["x"], p["x"] + p["lengthCm"], q["x"], q["x"] + q["lengthCm"])
                    and _overlap_1d(p["y"], p["y"] + p["widthCm"], q["y"], q["y"] + q["widthCm"])):
                piso = max(piso, q["z"] + q["heightCm"])
        if piso < p["z"] - EPS:
            p["z"] = p["zCm"] = piso
            bajadas += 1
        apoyadas.append(p)
    return out, bajadas


def _request_seed(request: dict[str, Any]) -> int:
    vehicle = request.get("vehicle") or {}
    text = f"{vehicle.get('id', 'vehicle')}|" + ",".join(str(item["guideId"]) for item in request.get("items", []))
    value = 2166136261
    for character in text:
        value ^= ord(character); value = _imul(value, 16777619)
    return value & 0xFFFFFFFF


class ExtremePoint3D:
    def __init__(self, options: LoadingOptions):
        self.options = options

    def _normalize(self, request: dict[str, Any], cargo: list[float]) -> list[dict[str, Any]]:
        order = {str(client): index + 1 for index, client in enumerate(request.get("deliveryOrder") or [])}
        result = []
        for index, source in enumerate(request.get("items") or []):
            item = dict(source)
            dimensions = [float(value) for value in item.get("dimensionsCm") or []]
            rotations = (
                [
                    value for value in _unique_orientations(dimensions, self.options.orientation_policy)
                    if all(value["dimensions"][axis] <= cargo[axis] + EPS for axis in range(3))
                ] if len(dimensions) == 3 else []
            )
            if item.get("keepUpright") is True:
                rotations = [rotation for rotation in rotations if rotation["orientation"] in (0, 2)]
            volume = float(item.get("volumeCm3") or math.prod(dimensions))
            maximum = max(dimensions, default=math.inf)
            rank = order.get(str(item.get("clientIndex")), index + 1)
            item.update({
                "dimensionsCm": dimensions,
                "rotations": rotations,
                "volumeCm3": volume,
                "weightKg": float(item.get("weightKg") or 0),
                "fragile": item.get("fragile") is True or int(item.get("fragility") or 0) == 1,
                "stackable": item.get("stackable", True) is not False,
                "deliveryRank": rank,
                "difficulty": volume / math.prod(cargo) + maximum / max(cargo) + (1.0 / len(rotations) if rotations else 10.0),
            })
            result.append(item)
        return result

    @staticmethod
    def _ordered(items: list[dict[str, Any]], attempt: int, random: _Mulberry32) -> list[dict[str, Any]]:
        result = list(items); variant = attempt % 6
        if variant == 0:
            result.sort(key=lambda item: (-item["difficulty"], -item["volumeCm3"]))
        elif variant == 1:
            result.sort(key=lambda item: -item["volumeCm3"])
        elif variant == 2:
            result.sort(key=lambda item: -max(item["dimensionsCm"]))
        elif variant == 3:
            result.sort(key=lambda item: (-item["deliveryRank"], -item["difficulty"]))
        elif variant == 4:
            result.sort(key=lambda item: (item["deliveryRank"], -item["difficulty"]))
        else:
            result.sort(key=lambda item: -max(
                item["dimensionsCm"][0] * item["dimensionsCm"][1],
                item["dimensionsCm"][0] * item["dimensionsCm"][2],
                item["dimensionsCm"][1] * item["dimensionsCm"][2],
            ))
        if attempt >= 6:
            result.sort(key=lambda item: -(item["difficulty"] * (0.75 + random.random() * 0.5)))
        return result

    def _verify(self, request: dict[str, Any], placements: list[dict[str, Any]]) -> tuple[bool, str]:
        cargo = [float(value) for value in (request.get("vehicle") or {}).get("cargoDimensions") or []]
        if len(cargo) != 3 or any(value <= 0 for value in cargo):
            return False, "vehicle-dimensions"
        if len(placements) != len(request.get("items") or []):
            return False, "missing-items"
        ids: set[str] = set()
        for placement in placements:
            guide_id = str(placement["guideId"])
            if guide_id in ids:
                return False, "duplicate-item"
            ids.add(guide_id)
            if not _inside_cargo(placement, cargo):
                return False, "outside-cargo"
        for index, left in enumerate(placements):
            if any(_boxes_overlap(left, right) for right in placements[index + 1:]):
                return False, "overlap"
        for placement in placements:
            others = [value for value in placements if value is not placement]
            support = _support_information(placement, others)
            if support["ratio"] + EPS < self.options.support_ratio:
                return False, "insufficient-support"
            if self.options.enforce_fragility and not placement["fragile"] and any(box["fragile"] for box in support["supports"]):
                return False, "nonfragile-on-fragile"
            if any(not box.get("stackable", True) for box in support["supports"]):
                return False, "item-on-nonstackable"
            if self.options.enforce_unload_order and any(box["deliveryRank"] < placement["deliveryRank"] for box in support["supports"]):
                return False, "support-blocks-earlier-delivery"
            if self.options.enforce_unload_order and not _sequence_compatible(placement, others):
                return False, "unload-order-blocked"
        return True, "ok"

    def _pack_attempt(self, items: list[dict[str, Any]], cargo: list[float], attempt: int, random: _Mulberry32) -> dict[str, Any]:
        placed: list[dict[str, Any]] = []; points = [[0.0, 0.0, 0.0]]
        max_rank = max((item["deliveryRank"] for item in items), default=1)
        for item in self._ordered(items, attempt, random):
            best: tuple[float, dict[str, Any]] | None = None
            for rotation in item["rotations"]:
                dimensions = rotation["dimensions"]
                for position in _candidate_positions(points, dimensions, cargo):
                    candidate = {
                        "guideId": item["guideId"], "clientIndex": item["clientIndex"],
                        "trackingCode": item.get("trackingCode") or str(item["guideId"]),
                        "deliveryRank": item["deliveryRank"],
                        "x": position[0], "y": position[1], "z": position[2],
                        "xCm": position[0], "yCm": position[1], "zCm": position[2],
                        "lengthCm": dimensions[0], "widthCm": dimensions[1], "heightCm": dimensions[2],
                        "orientation": rotation["orientation"], "volumeCm3": item["volumeCm3"],
                        "weightKg": item["weightKg"], "fragile": item["fragile"],
                        "stackable": item["stackable"],
                    }
                    if not _inside_cargo(candidate, cargo) or any(_boxes_overlap(candidate, box) for box in placed):
                        continue
                    if self.options.enforce_unload_order and not _sequence_compatible(candidate, placed):
                        continue
                    support = _support_information(candidate, placed)
                    if support["ratio"] + EPS < self.options.support_ratio:
                        continue
                    if self.options.enforce_fragility and not candidate["fragile"] and any(box["fragile"] for box in support["supports"]):
                        continue
                    if any(not box.get("stackable", True) for box in support["supports"]):
                        continue
                    if self.options.enforce_unload_order and any(box["deliveryRank"] < candidate["deliveryRank"] for box in support["supports"]):
                        continue
                    target_ratio = 1.0 if max_rank <= 1 else (max_rank - candidate["deliveryRank"]) / (max_rank - 1)
                    target_x = target_ratio * (cargo[0] - candidate["lengthCm"])
                    max_x = max([candidate["x"] + candidate["lengthCm"], *[box["x"] + box["lengthCm"] for box in placed], 0])
                    max_y = max([candidate["y"] + candidate["widthCm"], *[box["y"] + box["widthCm"] for box in placed], 0])
                    max_z = max([candidate["z"] + candidate["heightCm"], *[box["z"] + box["heightCm"] for box in placed], 0])
                    score = (
                        abs(candidate["x"] - target_x) / max(cargo[0], 1) * 700
                        + (candidate["z"] + candidate["heightCm"]) / max(cargo[2], 1) * 180
                        + max_x * max_y * max_z / math.prod(cargo) * 80
                        - support["ratio"] * 60 - _contact_score(candidate, placed, cargo) * 4
                        + candidate["y"] / max(cargo[1], 1) * 5
                    )
                    if best is None or score < best[0]:
                        best = score, candidate
            if best is None:
                continue
            candidate = best[1]; placed.append(candidate)
            points.extend([
                [candidate["x"] + candidate["lengthCm"], candidate["y"], candidate["z"]],
                [candidate["x"], candidate["y"] + candidate["widthCm"], candidate["z"]],
                [candidate["x"], candidate["y"], candidate["z"] + candidate["heightCm"]],
            ])
            points = _prune_points(points, placed, cargo)
        placed_ids = {str(value["guideId"]) for value in placed}
        unplaced = [item for item in items if str(item["guideId"]) not in placed_ids]
        max_x = max((item["x"] + item["lengthCm"] for item in placed), default=0.0)
        max_y = max((item["y"] + item["widthCm"] for item in placed), default=0.0)
        max_z = max((item["z"] + item["heightCm"] for item in placed), default=0.0)
        return {
            "placements": placed, "unplaced": unplaced,
            "placedVolume": sum(item["volumeCm3"] for item in placed),
            "boundingVolume": max_x * max_y * max_z,
        }

    def _native_pack(self, items: list[dict[str, Any]], cargo: list[float], attempts: int,
                     seed: int) -> dict[str, Any]:
        """Mismo resultado que el bucle Python de evaluate(), via lattimex_pack3d."""
        n = len(items)
        dims = (ctypes.c_double * (3 * n))(*[float(v) for it in items for v in it["dimensionsCm"]])
        offsets, rdims, rcodes = [0], [], []
        for it in items:
            for rot in it["rotations"]:
                rdims.extend(float(v) for v in rot["dimensions"]); rcodes.append(int(rot["orientation"]))
            offsets.append(len(rcodes))
        R = max(1, len(rcodes))
        arr = lambda ct, vals: (ct * max(1, len(vals)))(*vals)
        out_order = (ctypes.c_int32 * max(1, n))(); out_n = ctypes.c_int32(0)
        out_pos = (ctypes.c_double * (3 * max(1, n)))(); out_dims = (ctypes.c_double * (3 * max(1, n)))()
        out_rot = (ctypes.c_int32 * max(1, n))(); out_placed = (ctypes.c_uint8 * max(1, n))()
        out_attempt = ctypes.c_int32(0); out_verified = ctypes.c_int32(0)
        rc = _NATIVE(n, dims, arr(ctypes.c_int32, offsets), (ctypes.c_double * (3 * R))(*rdims),
                     arr(ctypes.c_int32, rcodes),
                     arr(ctypes.c_double, [it["volumeCm3"] for it in items]),
                     arr(ctypes.c_double, [it["weightKg"] for it in items]),
                     arr(ctypes.c_int32, [int(it["deliveryRank"]) for it in items]),
                     arr(ctypes.c_uint8, [1 if it["fragile"] else 0 for it in items]),
                     arr(ctypes.c_uint8, [1 if it["stackable"] else 0 for it in items]),
                     arr(ctypes.c_double, [it["difficulty"] for it in items]),
                     (ctypes.c_double * 3)(*cargo), int(attempts), int(seed) & 0xFFFFFFFF,
                     float(self.options.support_ratio), int(self.options.enforce_unload_order),
                     int(self.options.enforce_fragility),
                     out_order, ctypes.byref(out_n), out_pos, out_dims, out_rot, out_placed,
                     ctypes.byref(out_attempt), ctypes.byref(out_verified))
        if rc != 0:
            raise RuntimeError(f"lattimex_pack3d rc={rc}")
        placed = []
        for k in range(out_n.value):
            i = out_order[k]; it = items[i]
            x, y, z = out_pos[3 * i], out_pos[3 * i + 1], out_pos[3 * i + 2]
            l, w, h = out_dims[3 * i], out_dims[3 * i + 1], out_dims[3 * i + 2]
            placed.append({
                "guideId": it["guideId"], "clientIndex": it["clientIndex"],
                "trackingCode": it.get("trackingCode") or str(it["guideId"]),
                "deliveryRank": it["deliveryRank"],
                "x": x, "y": y, "z": z, "xCm": x, "yCm": y, "zCm": z,
                "lengthCm": l, "widthCm": w, "heightCm": h,
                "orientation": int(out_rot[i]), "volumeCm3": it["volumeCm3"],
                "weightKg": it["weightKg"], "fragile": it["fragile"], "stackable": it["stackable"],
            })
        unplaced = [it for i, it in enumerate(items) if not out_placed[i]]
        return {"placements": placed, "unplaced": unplaced, "attempt": int(out_attempt.value),
                "placedVolume": sum(p["volumeCm3"] for p in placed)}

    def evaluate(self, request: dict[str, Any]) -> dict[str, Any]:
        """Evaluate one route with a deterministic multi-start extreme-point heuristic."""
        started = time.perf_counter()
        vehicle = request.get("vehicle") or {}
        cargo = [float(value) for value in vehicle.get("cargoDimensions") or []]
        usar_nativo = _NATIVE is not None and not getattr(self, "forzar_python", False)
        base: dict[str, Any] = {
            "contract": "pen3q.3l.loading.result.v1",
            "solver": "extreme-point-3d-native" if usar_nativo else "extreme-point-3d-python",
            "execution_backend": "terminal-python",
            "exact": False, "certified": False, "placements": [], "conflicts": [],
        }
        if len(cargo) != 3 or any(value <= 0 for value in cargo):
            return {
                **base, "status": "incompatible",
                "conflicts": [{"reason": "vehicle-dimensions"}],
                "elapsedMs": (time.perf_counter() - started) * 1000,
            }

        items = self._normalize(request, cargo)
        total_volume = sum(item["volumeCm3"] for item in items)
        total_weight = sum(item["weightKg"] for item in items)
        physical_volume = math.prod(cargo)
        maximum_volume = min(physical_volume, float(vehicle.get("capacity") or physical_volume))
        maximum_weight = float(vehicle.get("maxWeightKg") or 0)
        conflicts: list[dict[str, Any]] = []
        conflicts.extend(
            {"guideId": item["guideId"], "reason": "individual-dimensions"}
            for item in items if not item["rotations"]
        )
        if total_volume > maximum_volume + EPS:
            conflicts.append({"reason": "total-volume", "actual": total_volume, "limit": maximum_volume})
        if maximum_weight > 0 and total_weight > maximum_weight + EPS:
            conflicts.append({"reason": "total-weight", "actual": total_weight, "limit": maximum_weight})
        if conflicts:
            return {
                **base, "status": "incompatible",
                "totalVolumeCm3": total_volume, "totalWeightKg": total_weight,
                "physicalCapacityCm3": maximum_volume,
                "unplacedItems": [
                    {"guideId": item["guideId"], "clientIndex": item["clientIndex"], "volumeCm3": item["volumeCm3"]}
                    for item in items
                ],
                "unplacedVolumeCm3": total_volume, "conflicts": conflicts,
                "constraints": self._constraints(),
                "elapsedMs": (time.perf_counter() - started) * 1000,
            }

        seed = _request_seed(request)
        attempts = max(1, int(self.options.max_restarts))
        best: dict[str, Any] | None = None
        if usar_nativo:
            best = self._native_pack(items, cargo, attempts, seed)
        else:
            random = _Mulberry32(seed)
            for attempt in range(attempts):
                candidate = self._pack_attempt(items, cargo, attempt, random)
                candidate_key = (
                    len(candidate["unplaced"]),
                    sum(item["volumeCm3"] for item in candidate["unplaced"]),
                    candidate["boundingVolume"],
                )
                if best is None or candidate_key < best["key"]:
                    best = {**candidate, "key": candidate_key, "attempt": attempt + 1}
                if not candidate["unplaced"]:
                    verified, _ = self._verify(request, candidate["placements"])
                    if verified:
                        best = {**candidate, "key": candidate_key, "attempt": attempt + 1}
                        break

        assert best is not None
        complete, verification_reason = self._verify(request, best["placements"])
        unplaced = best["unplaced"]
        asentadas = 0
        if complete:
            # Asentar solo si el resultado sigue siendo valido: bajar una caja puede
            # crear un bloqueo de orden de descarga o apoyarla sobre una fragil.
            settled, asentadas = settle_placements(best["placements"])
            if asentadas and self._verify(request, settled)[0]:
                best["placements"] = settled
            else:
                asentadas = 0
        return {
            **base,
            "status": "heuristic-feasible" if complete else "heuristic-unresolved",
            "certified": complete,
            "totalVolumeCm3": total_volume, "totalWeightKg": total_weight,
            "physicalCapacityCm3": maximum_volume,
            "utilization": total_volume / maximum_volume if maximum_volume > 0 else 0.0,
            "placements": best["placements"],
            "unplacedItems": [
                {"guideId": item["guideId"], "clientIndex": item["clientIndex"], "volumeCm3": item["volumeCm3"]}
                for item in unplaced
            ],
            "unplacedVolumeCm3": sum(item["volumeCm3"] for item in unplaced),
            "conflicts": [] if complete else [{
                "reason": verification_reason if not unplaced else "no-placement-found",
                "count": len(unplaced),
            }],
            "constraints": self._constraints(), "restartsAttempted": best["attempt"],
            "settledItems": asentadas,
            "elapsedMs": (time.perf_counter() - started) * 1000,
        }

    def _constraints(self) -> dict[str, Any]:
        return {
            "orientationPolicy": self.options.orientation_policy,
            "supportRatio": self.options.support_ratio,
            "fragilityEnforced": self.options.enforce_fragility,
            "unloadOrderEnforced": self.options.enforce_unload_order,
        }

    def verify(self, request: dict[str, Any], placements: list[dict[str, Any]]) -> dict[str, Any]:
        ok, reason = self._verify(request, placements)
        return {"ok": ok, "reason": reason}
