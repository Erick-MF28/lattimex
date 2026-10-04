# -*- coding: utf-8 -*-
"""Motor LATTIMEX (PRIVADO — vive solo en el volumen /engine del worker).

Pipeline: routing SENDA C++ (matriz vial + capacidad efectiva alpha*V, con
escalera de alpha si la carga no cabe en la flota exacta)
-> empaque 3D por ruta (ExtremePoint3D, reinicios adaptativos, asentado por gravedad)
-> mediacion con flota fija (invertir/rotar rutas, reubicar clientes fallidos)
-> re-optimizacion warm-start con revalidacion de empaque.

Entrada/salida: dicts JSON del contrato pen3q.lattimex.solve.v1 (ver docs/API_LOCAL.md).
"""
from __future__ import annotations

import ctypes
import hashlib
import math
import os
import sys
import time
from array import array
from pathlib import Path

import loading3d
from loading3d import ExtremePoint3D, LoadingOptions
from contracts import options_for_variant
from terminal_mediator import route_request, _items_by_customer
from effective_capacity import DEFAULT_ALPHAS, FALLBACK_ALPHA
from operational_access import evaluate_access, evaluate_stops

# H2: plan de descarga por entrega con tres puertas (trasera, laterales) y un
# maximo de cajas que el operador puede apartar temporalmente.
ACCESO_MAX_MOV = 3
# Rescate local: resecuencia rutas con entregas en exceso, re-empaca y
# re-evalua el acceso; nunca cambia la flota ni sube la ruta mas de 5 %.
RESCATE = os.environ.get("LATTIMEX_RESCATE", "1") != "0"
RESCATE_GUARDA_DIST = 1.05
RESCATE_RONDAS = 3
RESCATE_CANDIDATOS = {"fast": 6, "thorough": 12}

DIR = Path(__file__).resolve().parent
# LATTIMEX_CORE permite cargar otro binario (p.ej. la DLL de Windows en pruebas locales).
LIB_PATH = Path(os.environ.get("LATTIMEX_CORE") or DIR / "libsenda.so")
CORE_SHA = hashlib.sha256(LIB_PATH.read_bytes()).hexdigest()[:12]
ENGINE_VERSION = "lattimex-engine-1.6.0"

# Perfiles de esfuerzo. 'fast' es el predeterminado: prioriza entregar una
# solucion factible en segundos. 'thorough' agota el esfuerzo de empaque para
# exprimir la ocupacion y respetar el orden de descarga siempre que sea posible.
PERFILES = {
    "fast":     {"reinicios": 1.0, "sondeo_lifo": 45,   "reloj": 3.0},
    "thorough": {"reinicios": 4.0, "sondeo_lifo": 10000, "reloj": 8.0},
}

# Reparto del presupuesto de ruteo (budget_sec). El empaque 3D corre con su
# propio reloj de pared (limite_total), derivado del perfil.
FRACCION_RUTEO = 0.55
REOPT_MIN, REOPT_MAX = 0.25, 0.45
# Escalera de capacidad efectiva: si la carga no cabe en k vehiculos con alpha*V
# se relaja alpha por pasos hasta 1.0 antes de rechazar el trabajo.
PASO_ALPHA = 0.10
# Mediacion con flota fija: rondas y candidatos evaluados por ronda.
MEDIACION_RONDAS = 3
MEDIACION_CANDIDATOS = 24
MEDIACION_VECINDAD = 3

# Portafolio de ruteo (SENDA): rejilla config x semilla en hilos del nucleo con
# reduccion determinista entre candidatos; el presupuesto por corrida depende de los hilos. El
# worker tiene cpus: 2.0 en docker-compose. LATTIMEX_PORTAFOLIO=0 usa una
# sola corrida.
PORTAFOLIO = os.environ.get("LATTIMEX_PORTAFOLIO", "1") != "0"
HILOS = max(1, int(os.environ.get("LATTIMEX_THREADS", "2")))
# Dos configuraciones complementarias del ALNS: vecindad estrecha, reparacion
# dura y destrucciones medianas; vecindad amplia (+or-opt3), penalizacion
# adaptativa y destrucciones chicas. Medido 2026-09-01 (ruteo puro, 3 semillas,
# 6 s): -0.3..-0.6 % de distancia en 120-200 destinos y varianza casi nula
# entre semillas frente a la corrida unica; sin efecto bajo 60 destinos.
#            k   moves  penalty  d_min  d_max
CONFIGS = [(15,   3,      0,     0.10,  0.35),
           (25,   7,      1,     0.05,  0.20)]
SEMILLAS_POR_CONFIG = 2
# Normalizacion de la demanda escalar: capacidad = ESCALA sin importar si se
# rutea por peso o por volumen. El nucleo fija su penalizacion de capacidad con
# maxDist/maxDem (acotada a [0.5, 1000]); con volumenes en cm3 (~1e7) el
# cociente se saturaba en 0.5 y la busqueda operaba fuera de escala.
NORMALIZAR = os.environ.get("LATTIMEX_NORMALIZAR", "1") != "0"
ESCALA_DEMANDA = 100_000
# Experimental (H3): presupuesto del portafolio en ITERACIONES de ALNS por
# corrida en vez de segundos de pared. 0 = pared (comportamiento actual).
ITER_BUDGET = int(os.environ.get("LATTIMEX_ITER_BUDGET", "0"))

I32P = ctypes.POINTER(ctypes.c_int32)
I64P = ctypes.POINTER(ctypes.c_int64)
U64P = ctypes.POINTER(ctypes.c_uint64)
F64P = ctypes.POINTER(ctypes.c_double)
_LIB = ctypes.CDLL(str(LIB_PATH))
_LIB.senda_solve.restype = ctypes.c_int
_LIB.senda_solve.argtypes = [ctypes.c_int, F64P, F64P, I32P, I32P,
    ctypes.c_int, ctypes.c_int, ctypes.c_int, I32P, ctypes.c_int, I32P, ctypes.c_int,
    ctypes.c_double, ctypes.c_uint64, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    I32P, ctypes.c_int, I64P]
_MULTI = getattr(_LIB, "senda_solve_multi_par", None)
if _MULTI is not None:
    _MULTI.restype = ctypes.c_int
    _MULTI.argtypes = [ctypes.c_int, F64P, F64P, I32P, I32P,
        ctypes.c_int, ctypes.c_int, ctypes.c_int, I32P, ctypes.c_int, I32P, ctypes.c_int,
        U64P, ctypes.c_int,
        I32P, I32P, I32P, I32P, I64P, I32P, I32P, I32P, F64P, F64P, F64P, F64P, I64P,
        ctypes.c_int, ctypes.c_int, ctypes.c_double, I32P, ctypes.c_int, I64P]


def _variant(constraints: dict) -> str:
    sup = bool(constraints.get("support", True))
    fra = bool(constraints.get("fragility", True))
    lifo = bool(constraints.get("lifo", True))
    if sup and fra and lifo:
        return "all-constraints"
    if not sup and fra and lifo:
        return "no-support"
    if sup and not fra and lifo:
        return "no-fragility"
    if sup and fra and not lifo:
        return "no-lifo"
    if not sup and not fra and not lifo:
        return "loading-only"
    if not sup and fra and not lifo:
        return "fragility-only"
    if sup and not fra and not lifo:
        return "support-only"
    return "all-constraints"   # combinaciones no mapeadas: la mas conservadora


def _normalized_source(req: dict, relaxed_fleet: int) -> dict:
    veh = req["vehicle"]
    L, W, H = [float(x) for x in veh["cargo_cm"]]
    items = []
    for p in req["packages"]:
        l, w, h = [float(x) for x in p["dims_cm"]]
        items.append({
            "id": str(p["id"]),
            "customer_id": int(p["node"]),
            "dimensions_cm": [l, w, h],
            "volume_cm3": l * w * h,
            "weight_kg": float(p.get("weight_kg", 0)),
            "fragile": bool(p.get("fragile", False)),
            "stackable": bool(p.get("stackable", True)),
            "keep_upright": bool(p.get("keep_upright", False)),
            "load_bearing_strength": 0.0 if p.get("fragile") or not p.get("stackable", True) else 1.0,
        })
    nodes = [{"id": i} for i in range(len(req["matrix_m"]))]
    return {
        "name": "lattimex-job",
        "vehicle": {
            "capacity": min(L * W * H, float(veh.get("max_volume_cm3", L * W * H))),
            "maxWeightKg": float(veh["max_weight_kg"]),
            "cargoDimensions": [L, W, H],
            "available": relaxed_fleet,
        },
        "nodes": nodes,
        "items": items,
    }


def _route_loads(source: dict, routes: list[list[int]]) -> list[tuple[float, float]]:
    per_v, per_w = {}, {}
    for it in source["items"]:
        per_v[it["customer_id"]] = per_v.get(it["customer_id"], 0.0) + it["volume_cm3"]
        per_w[it["customer_id"]] = per_w.get(it["customer_id"], 0.0) + it["weight_kg"]
    return [(sum(per_v.get(c, 0.0) for c in r), sum(per_w.get(c, 0.0) for c in r)) for r in routes]


def _dual_ok(source: dict, routes: list[list[int]], alpha_cap: float) -> bool:
    max_w = source["vehicle"]["maxWeightKg"]
    for vol, wei in _route_loads(source, routes):
        if vol > alpha_cap + 1e-6 or wei > max_w + 1e-6:
            return False
    return True


def _route_distance_m(matrix: list[list[float]], route: list[int]) -> float:
    d, prev = 0.0, 0
    for node in route:
        d += matrix[prev][node]; prev = node
    return d + matrix[prev][0]


def _total_distance(matrix, routes) -> float:
    return sum(_route_distance_m(matrix, r) for r in routes)


def _ensure_route_count(routes: list[list[int]], count: int) -> list[list[int]]:
    """Garantiza una ruta no vacia por unidad seleccionada.

    El nucleo interpreta vehicle_hint como maximo. Dividir la ruta mas larga
    conserva los limites individuales de volumen y peso de cada vehiculo.
    """
    routes = [list(route) for route in routes if route]
    target = min(max(1, int(count)), sum(len(route) for route in routes))
    while len(routes) < target:
        index = max(range(len(routes)), key=lambda i: len(routes[i]))
        route = routes[index]
        if len(route) < 2:
            break
        cut = len(route) // 2
        routes[index:index + 1] = [route[:cut], route[cut:]]
    return routes


def _exact_fleet_warm(matrix, demands, capacity, fleet_count):
    """Construye exactamente k rutas antes de optimizar, sin post-split."""
    nodes = sorted(demands, key=lambda node: (-demands[node], node))
    if len(nodes) < fleet_count:
        raise ValueError("No hay suficientes destinos para las unidades seleccionadas")
    seeds = [max(nodes, key=lambda node: matrix[0][node])]
    while len(seeds) < fleet_count:
        seeds.append(max((node for node in nodes if node not in seeds),
                         key=lambda node: min(matrix[node][seed] for seed in seeds)))
    routes = [[seed] for seed in seeds]
    loads = [demands[seed] for seed in seeds]
    target = sum(demands.values()) / fleet_count
    for node in nodes:
        if node in seeds:
            continue
        choices = [i for i in range(fleet_count) if loads[i] + demands[node] <= capacity]
        if not choices:
            raise ValueError("La carga no cabe en exactamente las unidades seleccionadas")
        index = min(choices, key=lambda i: (matrix[node][seeds[i]] +
                    matrix[0][seeds[i]] * 0.08 * (loads[i] / max(target, 1.0)), loads[i]))
        routes[index].append(node)
        loads[index] += demands[node]
    ordered = []
    for route in routes:
        remaining, current, sequence = set(route), 0, []
        while remaining:
            nxt = min(remaining, key=lambda node: matrix[current][node])
            sequence.append(nxt); remaining.remove(nxt); current = nxt
        ordered.append(sequence)
    return ordered


def _escalera_alpha(alpha: float):
    """alpha, alpha+paso, ..., 1.0 (siempre termina en la capacidad nominal)."""
    valor = alpha
    while valor < 1.0 - 1e-9:
        yield round(valor, 4)
        valor += PASO_ALPHA
    yield 1.0


def _normalizar_demandas(demands_map: dict, capacity: float) -> tuple[dict, int]:
    """Demanda entera relativa a la capacidad (= ESCALA). Redondeo hacia arriba:
    nunca declara factible una carga que no cabe (error <= n/ESCALA)."""
    if not NORMALIZAR:
        return {k: int(round(v)) for k, v in demands_map.items()}, int(capacity)
    factor = ESCALA_DEMANDA / float(capacity)
    return {k: max(1, int(math.ceil(v * factor - 1e-9))) for k, v in demands_map.items()}, ESCALA_DEMANDA


def _solve_routing(matrix, demands_map, capacity, n, seed, budget_sec, warm=None, fleet_hint=-1,
                   portafolio: bool | None = None, stats: dict | None = None):
    flat = array("i", [0] * (n * n))
    for a in range(n):
        base, row = a * n, matrix[a]
        for b in range(n):
            flat[base + b] = int(round(row[b]))
    dem_norm, cap_int = _normalizar_demandas(demands_map, capacity)
    dem = array("i", [0] * n)
    for node, value in dem_norm.items():
        dem[node] = int(value)
    customers = array("i", [i for i in range(1, n) if demands_map.get(i, 0) > 0])
    if warm:
        init = array("i", [])
        for r in warm:
            init.extend(r); init.append(-1)
        init.append(-2)
        init_len = len(init)
    else:
        init = array("i", [-2]); init_len = 0
    out_cap = 4 * n + 16
    out = array("i", [0] * out_cap)
    info = (ctypes.c_int64 * 10)()
    k_def = min(25, max(1, len(customers) - 1))
    usar_multi = (PORTAFOLIO if portafolio is None else portafolio) and _MULTI is not None \
        and len(customers) >= 8
    if usar_multi:
        nconf = len(CONFIGS)
        nseeds = SEMILLAS_POR_CONFIG
        trabajos = nconf * nseeds
        # Cada corrida recibe budget*hilos/trabajos de pared (el nucleo suma un
        # 12% de pulido inicial): el portafolio completo cabe en budget_sec.
        por_corrida = max(0.05, float(budget_sec) * HILOS / trabajos / 1.12)
        seeds = (ctypes.c_uint64 * nseeds)(*[(int(seed) + 7919 * i) & 0x7FFFFFFF for i in range(nseeds)])
        cfg_k = (ctypes.c_int32 * nconf)(*[min(c[0], k_def) for c in CONFIGS])
        cfg_mv = (ctypes.c_int32 * nconf)(*[c[1] for c in CONFIGS])
        cfg_pen = (ctypes.c_int32 * nconf)(*[c[2] for c in CONFIGS])
        modo = 1 if ITER_BUDGET > 0 else 0
        cfg_mode = (ctypes.c_int32 * nconf)(*([modo] * nconf))       # 0 pared, 1 iteraciones
        cfg_iters = (ctypes.c_int64 * nconf)(*([ITER_BUDGET] * nconf))
        cfg_polish = (ctypes.c_int32 * nconf)(*([1] * nconf))        # pulido temporizado
        cfg_swap = (ctypes.c_int32 * nconf)(*([-1] * nconf))
        cfg_calls = (ctypes.c_int32 * nconf)(*([-1] * nconf))
        cfg_dmin = (ctypes.c_double * nconf)(*[c[3] for c in CONFIGS])
        cfg_dmax = (ctypes.c_double * nconf)(*[c[4] for c in CONFIGS])
        cfg_cand = (ctypes.c_double * nconf)(*([0.08] * nconf))
        cfg_bpb = (ctypes.c_double * nconf)(*([0.15] * nconf))
        rc = _MULTI(n, F64P(), F64P(),
            (ctypes.c_int32 * len(flat)).from_buffer(flat),
            (ctypes.c_int32 * n).from_buffer(dem), cap_int, 0, int(fleet_hint),
            (ctypes.c_int32 * len(customers)).from_buffer(customers), len(customers),
            (ctypes.c_int32 * len(init)).from_buffer(init), init_len,
            seeds, nseeds,
            cfg_k, cfg_mv, cfg_pen, cfg_mode, cfg_iters, cfg_polish, cfg_swap, cfg_calls,
            cfg_dmin, cfg_dmax, cfg_cand, cfg_bpb, I64P(),
            HILOS, nconf, por_corrida,
            (ctypes.c_int32 * out_cap).from_buffer(out), out_cap, info)
    else:
        rc = _LIB.senda_solve(n, F64P(), F64P(),
            (ctypes.c_int32 * len(flat)).from_buffer(flat),
            (ctypes.c_int32 * n).from_buffer(dem), cap_int, 0, int(fleet_hint),
            (ctypes.c_int32 * len(customers)).from_buffer(customers), len(customers),
            (ctypes.c_int32 * len(init)).from_buffer(init), init_len,
            float(budget_sec), int(seed) & 0x7FFFFFFF,
            k_def, 3, 0,
            (ctypes.c_int32 * out_cap).from_buffer(out), out_cap, info)
    if rc != 0:
        raise RuntimeError(f"routing rc={rc}")
    if stats is not None:
        stats.update({"iters": int(info[1]), "evals": int(info[2]), "dist": int(info[3]),
                      "multi": bool(usar_multi)})
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
    return routes


def _sin_lifo(variant: str) -> str:
    """Variante equivalente pero sin exigir orden de descarga."""
    mapa = {"all-constraints": "no-lifo", "no-support": "fragility-only",
            "no-fragility": "no-lifo", "no-lifo": "no-lifo", "loading-only": "loading-only"}
    mapa.update({"fragility-only": "fragility-only", "support-only": "support-only"})
    return mapa.get(variant, "no-lifo")


def _restarts_por_tamano(n_items: int, apurado: bool, factor: float = 1.0) -> tuple:
    """Esfuerzo de empaque segun el tamano de la ruta y el tiempo restante.

    El empacador es O(items^2) por reinicio: con rutas de 100 bultos, 16
    reinicios cuestan minutos. Las rutas grandes ya vienen holgadas por la
    capacidad efectiva alpha, asi que necesitan menos intentos.
    """
    if apurado:
        return (2,)
    if n_items > 80:
        base = (2, 8)
    elif n_items > 40:
        base = (4, 12)
    elif n_items > 20:
        base = (8, 24)
    else:
        base = (16, 64)
    if factor == 1.0:
        return base
    return tuple(min(64, max(1, int(round(r * factor)))) for r in base)


def _pack_route(source, route, index, items_idx, variant, cache, restarts=None,
                deadline=None, perfil=None):
    key = hashlib.sha256(repr((variant, tuple(route), source["vehicle"])).encode()).hexdigest()
    n_items = sum(len(items_idx.get(c, ())) for c in route)
    apurado = bool(deadline and time.perf_counter() > deadline)
    cfg = PERFILES.get(perfil or "fast", PERFILES["fast"])
    if restarts is None:
        restarts = _restarts_por_tamano(n_items, apurado, cfg["reinicios"])
    esfuerzo = int(max(restarts))
    # La cache guarda el esfuerzo con que se obtuvo cada veredicto: un rechazo
    # conseguido con 2 reinicios (modo apurado) no bloquea un reintento con 16.
    cached = cache.get(key)
    if cached and (cached.get("status") == "heuristic-feasible"
                   or cached.get("_esfuerzo", 0) >= esfuerzo):
        return cached
    report = None
    # Cadena de esfuerzo: variante pedida -> misma sin LIFO. En rutas largas el
    # orden estricto de descarga suele ser imposible geometricamente; degradar
    # el requisito es mucho mejor que partir la ruta y duplicar vehiculos.
    relajada = _sin_lifo(variant)
    if relajada != variant and n_items > cfg["sondeo_lifo"]:
        # En rutas largas el LIFO estricto casi nunca es geometricamente posible:
        # se sondea con un solo reinicio (barato) y se pasa a la variante relajada.
        intentos = [(variant, (1,)), (relajada, restarts)]
    else:
        intentos = [(variant, restarts)]
        if relajada != variant:
            intentos.append((relajada, (max(restarts),)))
    for var_actual, secuencia in intentos:
      for r in secuencia:
        opts = options_for_variant(var_actual)
        solver = ExtremePoint3D(LoadingOptions(
            max_restarts=int(r),
            support_ratio=float(opts["supportRatio"]),
            enforce_unload_order=bool(opts["enforceUnloadOrder"]),
            orientation_policy=str(opts["orientationPolicy"]),
            enforce_fragility=bool(opts["enforceFragility"]),
        ))
        report = solver.evaluate(route_request(source, route, index, items_idx))
        report["variant_used"] = var_actual
        report["lifo_respetado"] = (var_actual == variant)
        if report.get("status") == "heuristic-feasible":
            break
        if deadline and time.perf_counter() > deadline:
            break          # sin tiempo para escalar el esfuerzo
      if report and report.get("status") == "heuristic-feasible":
          break
    report["_esfuerzo"] = esfuerzo
    cache[key] = report
    return report


def _clave_solucion(matrix, routes, reports) -> tuple:
    """Orden lexicografico de la mediacion: rutas sin resolver, volumen sin
    colocar, bultos sin colocar, distancia. Menor es mejor."""
    malos = [rep for rep in reports if rep.get("status") != "heuristic-feasible"]
    return (len(malos),
            sum(float(rep.get("unplacedVolumeCm3") or 0.0) for rep in malos),
            sum(len(rep.get("unplacedItems") or []) for rep in malos),
            _total_distance(matrix, routes))


def _candidatos_mediacion(routes, reports, items_idx):
    """Vecindad de reparacion con flota fija: nunca agrega ni quita rutas."""
    for i, rep in enumerate(reports):
        if rep.get("status") == "heuristic-feasible":
            continue
        ruta = routes[i]
        if len(ruta) > 1:
            cand = [list(r) for r in routes]
            cand[i] = list(reversed(ruta))
            yield "invertir-ruta", cand
            for shift in range(1, min(len(ruta), MEDIACION_VECINDAD + 1)):
                cand = [list(r) for r in routes]
                cand[i] = ruta[shift:] + ruta[:shift]
                yield "rotar-ruta", cand
        if len(ruta) < 2:
            continue    # reubicar dejaria la ruta vacia y cambiaria la flota
        fallidos = {int(it.get("clientIndex")) for it in rep.get("unplacedItems") or []
                    if it.get("clientIndex") is not None}
        clientes = [c for c in ruta if c in fallidos] or list(ruta)
        for cliente in clientes[:2]:
            for j, destino in enumerate(routes):
                if j == i:
                    continue
                posiciones = list(range(min(len(destino), MEDIACION_VECINDAD) + 1))
                if len(destino) not in posiciones:
                    posiciones.append(len(destino))     # tambien al final
                for pos in posiciones:
                    cand = [list(r) for r in routes]
                    cand[i].remove(cliente)
                    cand[j].insert(pos, cliente)
                    yield "reubicar-cliente", cand


def _mediar(source, matrix, routes, reports, items_idx, variant, cache, alpha_cap,
            deadline, perfil, rondas=MEDIACION_RONDAS, max_candidatos=MEDIACION_CANDIDATOS):
    """Reparacion local de rutas no empacables sin cambiar el numero de vehiculos.

    Evalua vecinos (invertir, rotar, reubicar clientes fallidos), acepta solo
    mejoras lexicograficas y se detiene al lograr factibilidad, agotar rondas
    o vencer el reloj. Devuelve (routes, reports, bitacora)."""
    best_routes, best_reports = routes, reports
    best_key = _clave_solucion(matrix, routes, reports)
    bitacora = {"rondas": 0, "candidatos": 0, "acciones": []}
    vistos = {tuple(tuple(r) for r in routes)}
    for _ in range(rondas):
        if best_key[0] == 0 or (deadline and time.perf_counter() > deadline):
            break
        bitacora["rondas"] += 1
        ronda_routes, ronda_reports, ronda_key, accion = None, None, best_key, None
        evaluados = 0
        for nombre, cand in _candidatos_mediacion(best_routes, best_reports, items_idx):
            firma = tuple(tuple(r) for r in cand)
            if firma in vistos or any(not r for r in cand):
                continue
            vistos.add(firma)
            if not _dual_ok(source, cand, alpha_cap):
                continue
            cand_reports = [_pack_route(source, r, k, items_idx, variant, cache,
                                        deadline=deadline, perfil=perfil)
                            for k, r in enumerate(cand)]
            evaluados += 1
            key = _clave_solucion(matrix, cand, cand_reports)
            if key < ronda_key:
                ronda_routes, ronda_reports, ronda_key, accion = cand, cand_reports, key, nombre
            if ronda_key[0] == 0 or evaluados >= max_candidatos:
                break
            if deadline and time.perf_counter() > deadline:
                break
        bitacora["candidatos"] += evaluados
        if ronda_routes is None:
            break
        bitacora["acciones"].append({"accion": accion,
                                     "sin_resolver": [best_key[0], ronda_key[0]],
                                     "distancia_m": [round(best_key[3], 1), round(ronda_key[3], 1)]})
        best_routes, best_reports, best_key = ronda_routes, ronda_reports, ronda_key
    return best_routes, best_reports, bitacora


def _evaluar_acceso(route, placements, puertas=None):
    """Plan de descarga por entrega (cliente): puerta y cajas a apartar.
    Se evalua sobre el acomodo ya verificado; no lo modifica.

    `puertas` son las que existen en la unidad (contrato: vehicle.doors). Solo
    se proponen salidas por puertas declaradas: un plan por una puerta que el
    vehiculo no tiene no es ejecutable."""
    if not placements:
        return None
    rango = {c: i + 1 for i, c in enumerate(route)}
    pl = [dict(p, deliveryRank=rango.get(p["clientIndex"], p["deliveryRank"])) for p in placements]
    # Sin puertas declaradas se asume solo la trasera: un plan pesimista es
    # ejecutable, uno optimista por una puerta inexistente no lo es.
    return evaluate_stops(pl, max_temporary_moves=ACCESO_MAX_MOV, doors=puertas or ["rear"])


def _clave_acceso(acc, dist):
    """Menor es mejor: entregas en exceso, maximo de movimientos, total, distancia."""
    return (len(set(acc["entregas_con_exceso"]) | set(acc.get("entregas_sin_orden", []))), acc["movimientos_max"],
            sum(e["movimientos"] for e in acc["plan"]), dist)


def _acepta_rescate(base, candidate, base_dist, candidate_dist, original_dist):
    """Independent guards; lexicographic improvement alone is insufficient."""
    return bool(candidate and
        candidate_dist <= original_dist * RESCATE_GUARDA_DIST + 1e-6 and
        len(candidate["entregas_con_exceso"]) <= len(base["entregas_con_exceso"]) and
        len(candidate.get("entregas_sin_orden", [])) <= len(base.get("entregas_sin_orden", [])) and
        candidate["movimientos_max"] <= base["movimientos_max"] and
        _clave_acceso(candidate, candidate_dist) < _clave_acceso(base, base_dist))


def _candidatos_rescate(route, acc, cliente_de_guia):
    """Vecindad de resecuenciacion alrededor de las entregas con exceso."""
    vistos = {tuple(route)}
    out = []

    def add(nombre, r):
        t = tuple(r)
        if t not in vistos:
            vistos.add(t); out.append((nombre, r))

    plan = {e["cliente"]: e for e in acc["plan"]}
    for c in sorted(set(acc["entregas_con_exceso"]) | set(acc.get("entregas_sin_orden", []))):
        i = route.index(c)
        for k in (1, 2, 3):
            if i - k >= 0:
                r = list(route); r.pop(i); r.insert(i - k, c); add(f"adelantar-{k}", r)
        if i > 0:
            r = list(route); r[i - 1], r[i] = r[i], r[i - 1]; add("intercambiar-anterior", r)
        mover = plan[c]["mover"]
        cb = cliente_de_guia.get(mover[0]) if mover else None
        if cb is not None and cb in route and cb != c:
            a, b = sorted((i, route.index(cb)))
            add("invertir-segmento", route[:a] + list(reversed(route[a:b + 1])) + route[b + 1:])
    return out


def _rescatar_acceso(source, matrix, routes, reports, accesos, items_idx, variant, cache,
                     deadline, perfil, puertas=None):
    """Para cada ruta con entregas en exceso, busca una resecuencia que empaque,
    no suba la distancia mas de RESCATE_GUARDA_DIST y mejore la clave de acceso.
    Devuelve (routes, reports, accesos, bitacora)."""
    routes, reports, accesos = list(routes), list(reports), list(accesos)
    bit = {"rutas_con_exceso": 0, "rutas_rescatadas": 0, "candidatos": 0, "acciones": []}
    max_cand = RESCATE_CANDIDATOS.get(perfil, 6)
    cliente_de_guia = {it["guideId"]: c for c, its in items_idx.items() for it in its}
    for i, acc in enumerate(accesos):
        if not acc or acc["factible"]:
            continue
        bit["rutas_con_exceso"] += 1
        base_dist = _route_distance_m(matrix, routes[i])
        limite = base_dist * RESCATE_GUARDA_DIST
        best_route, best_rep, best_acc = routes[i], reports[i], acc
        best_key = _clave_acceso(acc, base_dist)
        mejoro = False
        for _ in range(RESCATE_RONDAS):
            if best_acc["factible"] or (deadline and time.perf_counter() > deadline):
                break
            evaluados, avance = 0, None
            for nombre, cand in _candidatos_rescate(best_route, best_acc, cliente_de_guia):
                if evaluados >= max_cand or (deadline and time.perf_counter() > deadline):
                    break
                dist = _route_distance_m(matrix, cand)
                if dist > limite:
                    continue
                rep = _pack_route(source, cand, i, items_idx, variant, cache, deadline=deadline, perfil=perfil)
                evaluados += 1
                if rep.get("status") != "heuristic-feasible":
                    continue
                cacc = _evaluar_acceso(cand, rep.get("placements") or [], puertas)
                key = _clave_acceso(cacc, dist)
                if _acepta_rescate(best_acc, cacc, _route_distance_m(matrix, best_route), dist, base_dist):
                    avance = (nombre, cand, rep, cacc, key, dist)
                    break
            bit["candidatos"] += evaluados
            if avance is None:
                break
            nombre, best_route, best_rep, best_acc, best_key, dist = avance
            mejoro = True
            bit["acciones"].append({"ruta": i, "accion": nombre,
                                    "exceso": [len(acc["entregas_con_exceso"]), len(best_acc["entregas_con_exceso"])],
                                    "max_mov": [acc["movimientos_max"], best_acc["movimientos_max"]],
                                    "distancia_m": [round(base_dist, 1), round(dist, 1)]})
        if mejoro:
            bit["rutas_rescatadas"] += 1
            routes[i], reports[i], accesos[i] = best_route, best_rep, best_acc
    return routes, reports, accesos, bit


def _resumen_acceso(accesos, puertas=None):
    validos = [a for a in accesos if a]
    return {"puertas_disponibles": list(puertas or []),
            "entregas": sum(a["entregas"] for a in validos),
            "con_exceso": sum(len(a["entregas_con_exceso"]) for a in validos),
            "sin_movimientos": sum(a["entregas_sin_movimientos"] for a in validos),
            "max_movimientos": max((a["movimientos_max"] for a in validos), default=0)}


def solve(req: dict) -> dict:
    """Keep the legacy homogeneous path; fleet assignments stay in the worker."""
    fleet = req.get("fleet")
    if fleet is not None:
        if not isinstance(fleet, list) or not fleet or len(fleet) > 64:
            raise ValueError("fleet invalida")
        if req.get("fleet_count", len(fleet)) != len(fleet):
            raise ValueError("fleet_count no coincide con fleet")
        if len(fleet) > len({p["node"] for p in req["packages"]}):
            raise ValueError("Mas unidades que destinos")
        if any(v != fleet[0] for v in fleet[1:]):
            from fleet_runtime import solve_fleet
            return solve_fleet(req, sys.modules[__name__])
        req = dict(req, vehicle=fleet[0], fleet_count=len(fleet))
        req.pop("fleet")
    result = _solve_uniform(req)
    for i, route in enumerate(result["routes"]):
        route["vehicle_index"] = i
    result["solution_status"] = "feasible" if result["feasible"] else "heuristic-unresolved"
    return result


def _solve_uniform(req: dict) -> dict:
    started = time.perf_counter()
    matrix = req["matrix_m"]
    n = len(matrix)
    if n < 2 or any(len(row) != n for row in matrix):
        raise ValueError("matrix_m debe ser cuadrada, indice 0 = deposito")
    budget = float(req.get("budget_sec", 10))
    perfil = str(req.get("perfil", "fast")).lower()
    if perfil not in PERFILES:
        perfil = "fast"
    cfg_perfil = PERFILES[perfil]
    seed = int(req.get("seed", 20260726))
    fleet_count = max(1, int(req.get("fleet_count", 1)))
    fleet_count = min(fleet_count, n - 1)
    variant = _variant(req.get("constraints") or {})
    alpha_base = float(DEFAULT_ALPHAS.get(variant, FALLBACK_ALPHA))

    source = _normalized_source(req, relaxed_fleet=fleet_count)
    veh = source["vehicle"]
    nominal_cap = veh["capacity"]

    per_v, per_w = {}, {}
    for it in source["items"]:
        per_v[it["customer_id"]] = per_v.get(it["customer_id"], 0.0) + it["volume_cm3"]
        per_w[it["customer_id"]] = per_w.get(it["customer_id"], 0.0) + it["weight_kg"]
    # Un solo destino no puede exceder la caja fisica ni el peso maximo.
    if any(v > nominal_cap for v in per_v.values()) or any(w > veh["maxWeightKg"] for w in per_w.values()):
        raise ValueError("Hay un nodo cuya carga excede un vehiculo (imposible sin dividir entregas)")

    vol_pressure = sum(per_v.values()) / (nominal_cap * alpha_base)
    wei_pressure = sum(per_w.values()) / veh["maxWeightKg"]
    if wei_pressure > vol_pressure:
        demands = {k: v * 100.0 for k, v in per_w.items()}
        capacity = veh["maxWeightKg"] * 100.0
        scalar = "weight"
        alpha = alpha_base
        alpha_cap = nominal_cap * alpha
        exact_warm = _exact_fleet_warm(matrix, demands, capacity, fleet_count)
    else:
        demands = dict(per_v)
        scalar = "volume-effective"
        # Escalera de alpha: la capacidad efectiva es una heuristica de
        # empacabilidad, no un limite fisico. Si con alpha*V la carga no cabe en
        # la flota exacta, se relaja por pasos; el empacador 3D y la mediacion
        # deciden despues si la geometria realmente cabe.
        exact_warm, alpha = None, alpha_base
        for alpha in _escalera_alpha(alpha_base):
            capacity = nominal_cap * alpha
            try:
                exact_warm = _exact_fleet_warm(matrix, demands, capacity, fleet_count)
                break
            except ValueError as exc:
                ultimo_error = exc
        if exact_warm is None:
            raise ValueError(str(ultimo_error))
        alpha_cap = capacity

    routes = _solve_routing(matrix, demands, capacity, n, seed, budget * FRACCION_RUTEO,
                            warm=exact_warm, fleet_hint=fleet_count)
    rutas_nucleo = len(routes)
    if len(routes) < fleet_count:
        # El nucleo trata la flota como maximo: conservar su solucion optimizada
        # y repartirla en las unidades pedidas, en vez de descartarla.
        routes = _ensure_route_count(routes, fleet_count)
    if len(routes) != fleet_count or not _dual_ok(source, routes, alpha_cap):
        routes = exact_warm
    ajuste_flota = ("nucleo" if rutas_nucleo == fleet_count and routes is not exact_warm
                    else ("division" if routes is not exact_warm else "construccion"))

    # A partir de aqui todo respeta un reloj comun: el empaque 3D crece muy
    # rapido con el numero de bultos y sin esta cota una instancia grande puede
    # tardar horas.
    limite_total = float(req.get("max_wall_sec",
                                 max(budget * cfg_perfil["reloj"], budget + 30.0)))
    deadline = started + limite_total
    dl_empaque = started + limite_total * 0.75

    items_idx = _items_by_customer(source)
    cache: dict = {}
    reports = [_pack_route(source, r, i, items_idx, variant, cache, deadline=dl_empaque,
                          perfil=perfil)
               for i, r in enumerate(routes)]

    mediacion = {"rondas": 0, "candidatos": 0, "acciones": []}
    if any(rep.get("status") != "heuristic-feasible" for rep in reports):
        routes, reports, mediacion = _mediar(source, matrix, routes, reports, items_idx,
                                             variant, cache, alpha_cap, dl_empaque, perfil)

    feasible = all(rep.get("status") == "heuristic-feasible" for rep in reports)

    # re-optimizacion warm-start (nunca empeora; solo si ya es factible). Usa lo
    # que quede del presupuesto de ruteo, con un minimo garantizado.
    reopt_gain = 0.0
    reopt_sec = 0.0
    if feasible and time.perf_counter() < started + limite_total * 0.8:
        transcurrido = time.perf_counter() - started
        reopt_sec = min(budget * REOPT_MAX, max(budget * REOPT_MIN, budget - transcurrido))
        if reopt_sec >= 0.2:
            base_dist = _total_distance(matrix, routes)
            cand = _solve_routing(matrix, demands, capacity, n, seed + 7919,
                                  reopt_sec, warm=routes, fleet_hint=len(routes))
            if cand and len(cand) == len(routes) and _dual_ok(source, cand, alpha_cap):
                cand_reports = [_pack_route(source, r, i, items_idx, variant, cache,
                                            deadline=dl_empaque, perfil=perfil)
                                for i, r in enumerate(cand)]
                if all(rep.get("status") == "heuristic-feasible" for rep in cand_reports):
                    cand_dist = _total_distance(matrix, cand)
                    if cand_dist < base_dist - 1e-6:
                        reopt_gain = base_dist - cand_dist
                        routes, reports = cand, cand_reports
        else:
            reopt_sec = 0.0

    puertas = req["vehicle"].get("doors") or ["rear"]
    accesos = [_evaluar_acceso(r, rep.get("placements") or [], puertas)
               if rep.get("status") == "heuristic-feasible" else None
               for r, rep in zip(routes, reports)]
    rescate = {"rutas_con_exceso": 0, "rutas_rescatadas": 0, "candidatos": 0, "acciones": []}
    if RESCATE and feasible and any(a and not a["factible"] for a in accesos):
        routes, reports, accesos, rescate = _rescatar_acceso(
            source, matrix, routes, reports, accesos, items_idx, variant, cache, dl_empaque,
            perfil, puertas)
    out_routes = []
    for i, (r, rep) in enumerate(zip(routes, reports)):
        out_routes.append({
            "acceso": accesos[i],
            "packing_feasible": rep.get("status") == "heuristic-feasible",
            "operational_feasible": accesos[i]["factible"] if accesos[i] else None,
            "sequence": [int(c) for c in r],
            "distance_m": round(_route_distance_m(matrix, r), 1),
            "packages": [it["id"] for c in r for it in items_idx.get(c, [])],
            "loading_status": rep.get("status"),
            "utilization": rep.get("utilization"),
            "placements": rep.get("placements"),
            "lifo_respetado": rep.get("lifo_respetado", True),
            "restricciones_aplicadas": rep.get("variant_used", variant),
        })
    return {
        "contract": "pen3q.lattimex.solve.v1",
        "feasible": bool(feasible),
        "packing_feasible": bool(feasible),
        "operational_feasible": (all(a["factible"] for a in accesos)
                                 if feasible and all(accesos) else None),
        "vehicles": len(routes),
        "total_distance_m": round(sum(r["distance_m"] for r in out_routes), 1),
        "routes": out_routes,
        "metrics": {
            "runtime_sec": round(time.perf_counter() - started, 2),
            "variant": variant,
            "scalarization": scalar,
            "alpha_base": alpha_base,
            "alpha_used": round(alpha, 4),
            "rutas_nucleo": rutas_nucleo,
            "ajuste_flota": ajuste_flota,
            "mediacion": mediacion,
            "reopt_sec": round(reopt_sec, 2),
            "reopt_gain_m": round(reopt_gain, 1),
            "acceso": _resumen_acceso(accesos, puertas),
            "acceso_rescate": rescate,
            "portafolio": bool(PORTAFOLIO and _MULTI is not None and (n - 1) >= 8),
            "hilos": HILOS,
            "demanda_normalizada": bool(NORMALIZAR),
        },
        "engine": {"version": ENGINE_VERSION, "perfil": perfil, "core": CORE_SHA,
                   "packer": ("extreme-point-3d/native+gravedad" if loading3d._NATIVE is not None
                              else "extreme-point-3d/python+gravedad"),
                   "router": ("senda-portfolio/%dx%d" % (len(CONFIGS), SEMILLAS_POR_CONFIG)
                              if PORTAFOLIO and _MULTI is not None else "senda-single")},
    }
