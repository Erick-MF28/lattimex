"""Respaldo del constructor de flota exacta (desde la versión 1.1.0).

Si `_exact_fleet_warm` no logra meter la carga en exactamente k rutas, se reparte igual (mismas
semillas lejanas, mismo criterio geográfico, pero aceptando sobrecarga) y se elimina la sobrecarga
con búsqueda local sobre la asignación:
  - traslado de un destino de una ruta sobrecargada a otra con espacio;
  - intercambio 1-1 y 2-1 que baja la sobrecarga total;
  - si nada mejora, un traslado aleatorio desde una ruta sobrecargada (perturbación) y se sigue.
Entre movimientos que bajan la sobrecarga igual, se prefiere el de menor costo geográfico
(distancia a la semilla de la ruta). Después se ordena cada ruta por vecino más cercano, igual que el
constructor publicado. Determinista (semilla fija) y con tope de tiempo.
"""
from __future__ import annotations
import random
import time


def _seeds(matrix, nodes, k):
    seeds = [max(nodes, key=lambda node: matrix[0][node])]
    chosen = set(seeds)
    near = {v: matrix[v][seeds[0]] for v in nodes}
    while len(seeds) < k:
        nxt = max((v for v in nodes if v not in chosen), key=lambda v: near[v])
        seeds.append(nxt); chosen.add(nxt)
        for v in nodes:
            near[v] = min(near[v], matrix[v][nxt])
    return seeds


def _sequence(matrix, routes):
    ordered = []
    for route in routes:
        remaining, current, seq = set(route), 0, []
        while remaining:
            nxt = min(remaining, key=lambda node: matrix[current][node])
            seq.append(nxt); remaining.remove(nxt); current = nxt
        ordered.append(seq)
    return ordered


def repair_assignment(matrix, demands, capacity, k, limit_sec=0.5, seed=20261011):
    started = time.perf_counter()
    nodes = sorted(demands, key=lambda node: (-demands[node], node))
    if len(nodes) < k or sum(demands.values()) > k * capacity + 1e-9 or max(demands.values()) > capacity + 1e-9:
        return None
    seeds = _seeds(matrix, nodes, k)
    geo = lambda v, b: matrix[v][seeds[b]]
    target = sum(demands.values()) / k
    label, loads = {}, [0.0] * k
    for i, s in enumerate(seeds):
        label[s] = i; loads[i] += demands[s]
    for v in nodes:
        if v in label:
            continue
        fit = [i for i in range(k) if loads[i] + demands[v] <= capacity]
        pool = fit or range(k)
        b = min(pool, key=lambda i: (geo(v, i) + matrix[0][seeds[i]] * 0.08 * (loads[i] / max(target, 1.0)), loads[i]))
        label[v] = b; loads[b] += demands[v]
    members = [set() for _ in range(k)]
    for v, b in label.items():
        members[b].add(v)
    over = lambda load: max(0.0, load - capacity)
    rng = random.Random(seed)
    stuck = 0
    while True:
        bad = [a for a in range(k) if loads[a] > capacity + 1e-9]
        if not bad:
            break
        if time.perf_counter() - started > limit_sec:
            return None
        best = None  # (overload reduction, -geo delta, move)
        for a in bad:
            oa = over(loads[a])
            for u in members[a]:
                du = demands[u]
                for b in range(k):
                    if b == a:
                        continue
                    ob = over(loads[b])
                    # traslado
                    red = oa + ob - over(loads[a] - du) - over(loads[b] + du)
                    if red > 1e-9:
                        key = (red, -(geo(u, b) - geo(u, a)))
                        if best is None or key > best[0]:
                            best = (key, ('move', u, a, b))
                    # intercambio 1-1
                    for v in members[b]:
                        dv = demands[v]
                        if dv >= du:
                            continue
                        red = oa + ob - over(loads[a] - du + dv) - over(loads[b] + du - dv)
                        if red > 1e-9:
                            key = (red, -(geo(u, b) + geo(v, a) - geo(u, a) - geo(v, b)))
                            if best is None or key > best[0]:
                                best = (key, ('swap', u, v, a, b))
        if best is None:
            # 2-1: dos de a por uno de b
            for a in bad:
                oa = over(loads[a]); ma = sorted(members[a])
                for i in range(len(ma)):
                    for j in range(i + 1, len(ma)):
                        u1, u2 = ma[i], ma[j]; du = demands[u1] + demands[u2]
                        for b in range(k):
                            if b == a:
                                continue
                            ob = over(loads[b])
                            for v in members[b]:
                                dv = demands[v]
                                red = oa + ob - over(loads[a] - du + dv) - over(loads[b] + du - dv)
                                if red > 1e-9 and (best is None or red > best[0][0]):
                                    best = ((red, 0.0), ('swap2', u1, u2, v, a, b))
        if best is None:
            stuck += 1
            a = rng.choice(bad); u = rng.choice(sorted(members[a]))
            b = rng.choice([i for i in range(k) if i != a])
            best = (None, ('move', u, a, b))
        mv = best[1]
        if mv[0] == 'move':
            _, u, a, b = mv
            members[a].remove(u); members[b].add(u); loads[a] -= demands[u]; loads[b] += demands[u]
        elif mv[0] == 'swap':
            _, u, v, a, b = mv
            members[a].remove(u); members[b].add(u); members[b].remove(v); members[a].add(v)
            loads[a] += demands[v] - demands[u]; loads[b] += demands[u] - demands[v]
        else:
            _, u1, u2, v, a, b = mv
            for u in (u1, u2):
                members[a].remove(u); members[b].add(u)
            members[b].remove(v); members[a].add(v)
            du = demands[u1] + demands[u2]
            loads[a] += demands[v] - du; loads[b] += du - demands[v]
    if any(not m for m in members):
        return None
    return _sequence(matrix, [sorted(m) for m in members])


def exact_fleet_warm_v2(original):
    """Envuelve el constructor publicado: primero el original; si falla, el respaldo."""
    def build(matrix, demands, capacity, fleet_count):
        try:
            return original(matrix, demands, capacity, fleet_count)
        except ValueError:
            routes = repair_assignment(matrix, demands, capacity, fleet_count)
            if routes is None:
                raise ValueError("La carga no cabe en exactamente las unidades seleccionadas")
            return routes
    return build
