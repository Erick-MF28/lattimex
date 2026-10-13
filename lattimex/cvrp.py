# Copyright (c) 2026 LATTIMEX. Licencia MIT (ver LICENSE).
"""SENDA2 solo: CVRP clásico sobre archivos de CVRPLIB, sin carga 3D ni el resto del motor.

    python -m lattimex cvrp X-n101-k25.vrp --time 4 --seed 1
    python -m lattimex cvrp A-n32-k5.vrp --time 2 --fleet fixed --sol A-n32-k5.sol

Reproduce la forma en que se midió SENDA2 frente a HGS-CVRP en paper/guia_senda2.pdf:
- presupuesto interno = 80 % del tiempo pedido (el mismo margen para todos los solvers comparados);
- una o dos configuraciones del ALNS según las características de la instancia, más un brazo con
  penalización de capacidad; el tiempo se reparte por igual y se devuelve la mejor solución verificada;
- un hilo; distancias euclidianas redondeadas al entero más cercano (convención de CVRPLIB);
- flota fija (a lo sumo k rutas, con k tomado del nombre -kNN) o libre.
Todas las soluciones se verifican en Python (cobertura, capacidad, flota y costo) antes de imprimirse.
"""
from __future__ import annotations

import ctypes
import math
import re
import time
import zlib
from array import array
from pathlib import Path

from . import native

INTERNAL_SHARE = 0.8

_BASE = {"k": 15, "use_segment": 1, "use_swapstar": 1, "use_penalty": 0, "destroy_min": 0.10,
         "destroy_max": 0.35, "cand_ls_budget": 0.08, "best_polish_budget": 0.15, "polish_mode": 3,
         "swapstar_max_passes": 2, "best_polish_max_calls": 50}
CONFIGS = {
    "baseline_cap2_calls50": {},
    "long_10k_k25": {"k": 25},
    "large_destroy_k25": {"k": 25, "destroy_min": 0.15, "destroy_max": 0.45},
    "granular_k25": {"k": 25},
    "granular_k40": {"k": 40},
    "medium_destroy_k25": {"k": 25, "destroy_min": 0.10, "destroy_max": 0.25},
}


class Instance:
    def __init__(self, name, capacity, depot, coords, demands, vehicle_hint):
        self.name, self.capacity, self.depot = name, capacity, depot
        self.coords, self.demands, self.vehicle_hint = coords, demands, vehicle_hint
        self.customers = sorted(v for v in coords if v != depot)

    @property
    def total_demand(self):
        return sum(self.demands.get(c, 0) for c in self.customers)

    @property
    def vehicle_count(self):
        return self.vehicle_hint or math.ceil(self.total_demand / max(self.capacity, 1))

    def distance(self, a, b):
        if a == b:
            return 0
        (xa, ya), (xb, yb) = self.coords[a], self.coords[b]
        return int(math.hypot(xa - xb, ya - yb) + 0.5)

    def cost(self, routes):
        return sum(sum(self.distance(a, b) for a, b in zip([self.depot] + r, r + [self.depot])) for r in routes if r)


def read_cvrplib(path) -> Instance:
    """Lector de .vrp (EUC_2D con NODE_COORD_SECTION, DEMAND_SECTION y DEPOT_SECTION)."""
    path = Path(path)
    name, capacity, depot, ewt, comment = path.stem, None, None, "EUC_2D", ""
    coords, demands, section = {}, {}, None
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        up = line.upper()
        if not line:
            continue
        if up == "EOF":
            break
        if up.startswith("NODE_COORD_SECTION"):
            section = "coords"; continue
        if up.startswith("DEMAND_SECTION"):
            section = "demands"; continue
        if up.startswith("DEPOT_SECTION"):
            section = "depot"; continue
        if up.startswith("EDGE_WEIGHT_SECTION"):
            raise ValueError("matrices explícitas (EDGE_WEIGHT_SECTION) no están soportadas")
        if section == "coords":
            p = line.split(); coords[int(p[0])] = (float(p[1]), float(p[2])); continue
        if section == "demands":
            p = line.split(); demands[int(p[0])] = int(float(p[1])); continue
        if section == "depot":
            v = int(float(line.split()[0]))
            if v == -1:
                section = None
            else:
                depot = v
            continue
        value = line.split(":", 1)[1].strip() if ":" in line else ""
        if up.startswith("NAME"):
            name = value or name
        elif up.startswith("COMMENT"):
            comment = value
        elif up.startswith("CAPACITY"):
            capacity = int(float(value))
        elif up.startswith("EDGE_WEIGHT_TYPE"):
            ewt = value or ewt
    if ewt.upper() != "EUC_2D":
        raise ValueError(f"EDGE_WEIGHT_TYPE {ewt} no soportado (sólo EUC_2D)")
    if capacity is None:
        raise ValueError("falta CAPACITY")
    m = re.search(r"-k(\d+)", name) or re.search(r"(?:trucks|vehicles)\s*:\s*(\d+)", comment, re.I)
    return Instance(name, capacity, depot or 1, coords, demands, int(m.group(1)) if m else None)


def _features(inst: Instance) -> dict:
    cs = inst.customers
    dem = [inst.demands.get(c, 0) for c in cs]
    radii = [inst.distance(inst.depot, c) for c in cs]
    dx, dy = inst.coords[inst.depot]
    ang = [math.atan2(inst.coords[c][1] - dy, inst.coords[c][0] - dx) for c in cs]
    xs = [inst.coords[c][0] for c in cs]; ys = [inst.coords[c][1] for c in cs]
    area = max(max(xs) - min(xs), 1.0) * max(max(ys) - min(ys), 1.0)

    def std(v):
        if len(v) <= 1:
            return 0.0
        mu = sum(v) / len(v)
        return math.sqrt(sum((x - mu) ** 2 for x in v) / (len(v) - 1))
    md, mr = sum(dem) / max(len(dem), 1), sum(radii) / max(len(radii), 1)
    return {"customers": float(len(cs)), "vehicle_hint": float(inst.vehicle_count),
            "load_pressure": inst.total_demand / max(float(inst.capacity * inst.vehicle_count), 1.0),
            "demand_cv": std(dem) / md if md > 0 else 0.0, "radius_cv": std(radii) / mr if mr > 0 else 0.0,
            "angular_concentration": math.hypot(sum(map(math.cos, ang)), sum(map(math.sin, ang))) / max(len(ang), 1),
            "density": len(cs) / area}


def _extra_config(f: dict) -> str:
    """Rama adicional del portafolio según la instancia (selector de SENDA, guía 2026-09-30)."""
    n, k, lp, dcv, rcv, ang, den = (f["customers"], f["vehicle_hint"], f["load_pressure"], f["demand_cv"],
                                    f["radius_cv"], f["angular_concentration"], f["density"])
    if n < 150:
        if n >= 70:
            return "granular_k25"
        if 60 <= n < 70:
            if den >= 0.0085 or ang < 0.35:
                return "large_destroy_k25"
            if ang >= 0.80:
                return "long_10k_k25"
            if k >= 10:
                return "granular_k40"
            if dcv < 0.50:
                return "long_10k_k25"
            return "baseline_cap2_calls50"
        if 45 <= n <= 65 and lp < 0.93 and dcv < 0.50:
            return "medium_destroy_k25"
        return "baseline_cap2_calls50"
    if dcv >= 0.50 and n <= 245:
        return "large_destroy_k25"
    if dcv >= 0.50 and k >= 70:
        return "large_destroy_k25"
    if k <= 16 and ((dcv < 0.30 and rcv < 0.38) or (dcv < 0.70 and ang >= 0.88)):
        return "granular_k25"
    if k >= 55 and dcv >= 0.45 and ang >= 0.90:
        return "granular_k25"
    if n >= 300 and dcv >= 1.0:
        return "baseline_cap2_calls50"
    return "long_10k_k25"


def _lib(router: str):
    native.configure()
    import os  # noqa: PLC0415
    path = os.environ.get("LATTIMEX_CORE2" if router == "senda2" else "LATTIMEX_CORE")
    if not path:
        raise RuntimeError("Núcleo no compilado: ejecute `python -m lattimex build`")
    lib = ctypes.CDLL(path)
    I32, I64, U64, F64 = (ctypes.POINTER(t) for t in (ctypes.c_int32, ctypes.c_int64, ctypes.c_uint64, ctypes.c_double))
    fn = lib.senda_solve_multi_es
    fn.restype = ctypes.c_int
    fn.argtypes = [ctypes.c_int, F64, F64, I32, I32, ctypes.c_int, ctypes.c_int, ctypes.c_int, I32, ctypes.c_int, I32,
                   ctypes.c_int, U64, ctypes.c_int, I32, I32, I32, I32, I64, I32, I32, I32, F64, F64, F64, F64, I64,
                   ctypes.c_int, ctypes.c_int, ctypes.c_double, I32, ctypes.c_int, I64]
    return fn


def solve(inst: Instance, time_sec: float = 4.0, seed: int = 1, fleet: str = "free", router: str = "senda2") -> dict:
    """Resuelve una instancia. fleet = 'free' (rutas ilimitadas) o 'fixed' (a lo sumo k rutas)."""
    started = time.perf_counter()
    fn = _lib(router)
    size = max([inst.depot, *inst.customers]) + 1
    xs, ys = array("d", [0.0] * size), array("d", [0.0] * size)
    for v, (x, y) in inst.coords.items():
        xs[v], ys[v] = x, y
    dem = array("i", [0] * size)
    for v, d in inst.demands.items():
        if v < size:
            dem[v] = d
    custs = array("i", inst.customers)
    names = ["baseline_cap2_calls50"]
    extra = _extra_config(_features(inst))
    if extra != names[0]:
        names.append(extra)
    arms = [(n, 0) for n in names] + [(names[-1], 1)]
    atomic = max(0.001, time_sec * INTERNAL_SHARE) / len(arms)
    internal_seed = (zlib.crc32(inst.name.encode()) ^ (seed & 0xFFFFFFFF)) & 0x7FFFFFFF
    k_max = inst.vehicle_count if fleet == "fixed" else -1
    best, arms_out = None, []
    for name, penalty in arms:
        cfg = dict(_BASE, **CONFIGS[name])
        enhanced = fleet == "fixed" or penalty == 1
        flags = (cfg["use_segment"] & 1) | (2 if cfg["use_swapstar"] else 0) | (4 if enhanced else 0)
        out_cap = 4 * size + 16
        out = array("i", [0] * out_cap)
        info = (ctypes.c_int64 * 10)()
        init = array("i", [-2])
        c = lambda t, v: (t * len(v))(*v)
        rc = fn(size, (ctypes.c_double * size).from_buffer(xs), (ctypes.c_double * size).from_buffer(ys),
                ctypes.POINTER(ctypes.c_int32)(), (ctypes.c_int32 * size).from_buffer(dem), inst.capacity, inst.depot,
                int(k_max), (ctypes.c_int32 * len(custs)).from_buffer(custs), len(custs),
                (ctypes.c_int32 * 1).from_buffer(init), 0, c(ctypes.c_uint64, [internal_seed]), 1,
                c(ctypes.c_int32, [cfg["k"]]), c(ctypes.c_int32, [flags]), c(ctypes.c_int32, [int(cfg["use_penalty"] or penalty)]),
                c(ctypes.c_int32, [0]), c(ctypes.c_int64, [5000]), c(ctypes.c_int32, [cfg["polish_mode"]]),
                c(ctypes.c_int32, [cfg["swapstar_max_passes"]]), c(ctypes.c_int32, [cfg["best_polish_max_calls"]]),
                c(ctypes.c_double, [cfg["destroy_min"]]), c(ctypes.c_double, [cfg["destroy_max"]]),
                c(ctypes.c_double, [cfg["cand_ls_budget"]]), c(ctypes.c_double, [cfg["best_polish_budget"]]),
                c(ctypes.c_int64, [5000 if enhanced else 0]), 0, 1, float(atomic),
                (ctypes.c_int32 * out_cap).from_buffer(out), out_cap, info)
        if rc != 0:
            raise RuntimeError(f"senda_solve_multi_es rc={rc}")
        routes, cur = [], []
        for i in range(int(info[0])):
            v = out[i]
            if v == -2:
                break
            if v == -1:
                if cur:
                    routes.append(cur)
                cur = []
            else:
                cur.append(v)
        if cur:
            routes.append(cur)
        ok = _verify(inst, routes, k_max)
        cost = inst.cost(routes)
        arms_out.append({"config": name, "penalty": penalty, "verified": ok, "cost": cost, "iterations": int(info[1])})
        if ok and (best is None or cost < best["cost"]):
            best = {"cost": cost, "routes": routes}
    return {"instance": inst.name, "router": router, "fleet": fleet, "seed": seed, "time_sec": time_sec,
            "verified": best is not None, "cost": best["cost"] if best else None, "routes": best["routes"] if best else [],
            "arms": arms_out, "wall_sec": round(time.perf_counter() - started, 3)}


def _verify(inst, routes, k_max):
    flat = sorted(v for r in routes for v in r)
    return (flat == sorted(inst.customers)
            and all(sum(inst.demands.get(v, 0) for v in r) <= inst.capacity for r in routes)
            and (k_max < 0 or len([r for r in routes if r]) <= k_max))


def write_solution(path, result) -> None:
    lines = [f"Route #{i}: " + " ".join(str(v - 1) for v in r) for i, r in enumerate(result["routes"], 1)]
    lines.append(f"Cost {result['cost']}")
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")
