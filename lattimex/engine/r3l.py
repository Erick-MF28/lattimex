"""R3L: ruteo con la verificación de carga dentro de la búsqueda, para instancias pequeñas (desde 1.1.0).

El motor normal rutea con una capacidad de volumen y acomoda después; con orden de descarga muchas
rutas no caben y la mediación sólo prueba unos pocos cambios locales. R3L busca rutas sabiendo, en
cada paso, si la carga cabe:

- Destruir y reconstruir al estilo SISR (Christiaens y Vanden Berghe, 2020) con recocido simulado:
  se quitan cadenas de clientes cercanos y cada cliente vuelve a la posición más barata cuya ruta
  cabe (P3L). Flota "hasta k": sólo se abre una ruta si hay menos de k.
- Revisión de carga en niveles, con caché (llave: conjunto de clientes sin LIFO; secuencia con LIFO,
  y se prueba también la ruta inversa, que tiene la misma distancia):
    nivel 0, toda posición candidata: masa, volumen y una pasada voraz de P3L;
    nivel 1, la inserción más barata y las rutas acortadas: P3L con haz (<= 30 cajas) o esquinas;
    nivel 2, rutas de un solo cliente: P3L con todas las posiciones enteras.
- Sin LIFO el orden no cambia el acomodo, así que cada ruta se reordena con 2-opt.

Escala: cada revisión re-acomoda la ruta completa. Con rutas de hasta ~30 cajas cuesta ~0.3 ms; con
60-75 cajas, 15-300 ms. Por eso el motor sólo usa R3L con pocas entregas (ver engine_runtime).
Mediciones (19 instancias de Gendreau contra los óptimos de Tamke et al. 2026): paper/guia_senda2.pdf.
"""
from __future__ import annotations

import math
import random
import time

import p3l_packer

BIG = 1e5


class Problem:
    def __init__(self, D, items_by_customer, cargo, mass_cap, variant, k, seed=1, fast_ms=3.0, strong_ms=20.0,
                 max_checks=40):
        self.n = len(D)
        self.D = [list(map(float, row)) for row in D]
        self.items = {c: items_by_customer.get(c, []) for c in range(self.n)}  # [{'id','dims','mass','fragile'}]
        self.cargo = [float(c) for c in cargo]
        self.cap_vol = self.cargo[0] * self.cargo[1] * self.cargo[2]
        self.mass_cap = float(mass_cap)
        self.variant, self.k, self.seed = variant, int(k), int(seed)
        self.fast_ms, self.strong_ms, self.max_checks = fast_ms, strong_ms, max_checks
        self.mass = [sum(i["mass"] for i in self.items[c]) for c in range(self.n)]
        self.vol = [sum(i["dims"][0] * i["dims"][1] * i["dims"][2] for i in self.items[c]) for c in range(self.n)]
        self.lifo = bool(p3l_packer.VARIANT_FLAGS[variant][2])
        self.cache: dict = {}
        self.tried: dict = {}
        self.near = [sorted(range(1, self.n), key=lambda j: self.D[i][j]) for i in range(self.n)]
        self.stats = {"checks": 0, "cache_hits": 0, "packs": 0, "pack_sec": 0.0}

    def _items(self, route):
        rank = {c: p + 1 for p, c in enumerate(route)}
        return [{"id": it["id"], "dims": it["dims"], "rank": rank[c], "fragile": it["fragile"]}
                for c in route for it in self.items[c]]

    def _key(self, route):
        return frozenset(route) if not self.lifo else tuple(route)

    def _pack(self, route, level):
        items = self._items(route)
        t0 = time.perf_counter()
        self.stats["packs"] += 1
        if level == 0:
            ok, pl = p3l_packer.pack(items, self.cargo, self.variant, flags=0, max_iters=12, time_ms=1e9,
                                     seed=self.seed + len(route))
        elif level == 1:
            ok, pl = p3l_packer.pack(items, self.cargo, self.variant, flags=2 if len(items) <= 30 else 1,
                                     time_ms=self.fast_ms, seed=self.seed + len(route))
        else:
            ok, pl = p3l_packer.pack(items, self.cargo, self.variant, time_ms=self.strong_ms, seed=self.seed + len(route))
        self.stats["pack_sec"] += time.perf_counter() - t0
        return ok, pl

    def _try(self, route, level):
        ok, pl = self._pack(route, level)
        if ok:
            return (tuple(route), pl)
        if self.lifo and len(route) > 1:
            rev = list(reversed(route))
            ok, pl = self._pack(rev, level)
            if ok:
                return (tuple(rev), pl)
        return None

    def two_opt(self, r):
        r = list(r); D = self.D; improved = True
        while improved and len(r) > 2:
            improved = False
            for i in range(len(r) - 1):
                a = r[i - 1] if i > 0 else 0
                for j in range(i + 1, len(r)):
                    b = r[i]; c = r[j]; d = r[j + 1] if j + 1 < len(r) else 0
                    if D[a][c] + D[b][d] < D[a][b] + D[c][d] - 1e-9:
                        r[i:j + 1] = r[i:j + 1][::-1]; improved = True
        return r

    def _store(self, route, res):
        if not self.lifo:
            self.cache[frozenset(route)] = res
        else:
            key = tuple(route)
            self.cache[key] = res
            self.cache[key[::-1]] = res

    def _mark(self, key, lv):
        self.tried[key] = max(self.tried.get(key, -1), lv)
        if self.lifo:
            self.tried[key[::-1]] = self.tried[key]

    def _out(self, route, res):
        if res is None:
            return None
        return tuple(route) if not self.lifo else res[0]

    def check(self, route, level=0):
        """La secuencia que cabe (con LIFO, la dada o su inversa) o None. Un rechazo se recuerda con su
        nivel; pedir un nivel mayor lo reintenta."""
        key = self._key(route)
        self.stats["checks"] += 1
        if key in self.cache:
            r = self.cache[key]
            if r is not None or self.tried.get(key, -1) >= level:
                self.stats["cache_hits"] += 1
                return self._out(route, r)
        elif sum(self.mass[c] for c in route) > self.mass_cap + 1e-9 or sum(self.vol[c] for c in route) > self.cap_vol + 1e-9:
            self._store(route, None); self._mark(key, 9)
            return None
        res = None
        for lv in range(self.tried.get(key, -1) + 1, level + 1):
            res = self._try(route, lv)
            self._mark(key, lv)
            if res:
                break
        self._store(route, res)
        return self._out(route, res)

    def placements(self, route):
        r = self.cache.get(self._key(route))
        if not r or (self.lifo and r[0] != tuple(route)):
            return None
        return r[1]

    def rdist(self, r):
        D = self.D
        return D[0][r[0]] + sum(D[a][b] for a, b in zip(r, r[1:])) + D[r[-1]][0] if r else 0.0


class Solution:
    def __init__(self, routes, unassigned):
        self.routes = [list(r) for r in routes]; self.unassigned = list(unassigned)

    def copy(self):
        return Solution(self.routes, self.unassigned)


def cost(P, S):
    return sum(P.rdist(r) for r in S.routes) + BIG * len(S.unassigned)


def recreate(P, S, rng, blink=0.01, max_checks=None):
    max_checks = max_checks or P.max_checks
    order = list(S.unassigned)
    mode = rng.random()
    if mode < 0.4:
        rng.shuffle(order)
    elif mode < 0.7:
        order.sort(key=lambda c: -P.vol[c])
    elif mode < 0.9:
        order.sort(key=lambda c: -P.D[0][c])
    else:
        order.sort(key=lambda c: P.D[0][c])
    S.unassigned = []
    D = P.D
    for c in order:
        cands = []
        for ri, r in enumerate(S.routes):
            if P.mass[c] + sum(P.mass[x] for x in r) > P.mass_cap + 1e-9:
                continue
            if P.vol[c] + sum(P.vol[x] for x in r) > P.cap_vol + 1e-9:
                continue
            prev = 0
            for pos in range(len(r) + 1):
                nxt = r[pos] if pos < len(r) else 0
                cands.append((D[prev][c] + D[c][nxt] - D[prev][nxt], ri, pos))
                prev = nxt
        if len(S.routes) < P.k:
            cands.append((2 * D[0][c], -1, 0))
        cands.sort()
        placed, checks = False, 0
        for rank_c, (_, ri, pos) in enumerate(cands):
            if rng.random() < blink:
                continue
            if ri == -1:
                seq = P.check([c], 2)
                if seq is not None:
                    S.routes.append(list(seq)); placed = True; break
                continue
            seq = P.check(S.routes[ri][:pos] + [c] + S.routes[ri][pos:], 1 if rank_c == 0 else 0)
            checks += 1
            if seq is not None:
                S.routes[ri] = list(seq); placed = True; break
            if checks >= max_checks:
                break
        if not placed:
            S.unassigned.append(c)
    if not P.lifo:
        S.routes = [P.two_opt(r) for r in S.routes]
    return S


def ruin(P, S, rng, cbar=10.0, lmax=10):
    """SISR: quita cadenas de clientes cercanos a un cliente semilla."""
    nc = sum(len(r) for r in S.routes)
    if nc == 0:
        return S
    ls_max = min(lmax, nc / max(1, len(S.routes)))
    ks_max = 4 * cbar / (1 + ls_max) - 1
    k_s = int(rng.random() * ks_max) + 1
    where = {c: ri for ri, r in enumerate(S.routes) for c in r}
    seed_c = rng.choice(list(where))
    removed, touched = [], set()
    for c in P.near[seed_c]:
        if len(touched) >= k_s:
            break
        if c not in where or where[c] in touched:
            continue
        ri = where[c]; r = S.routes[ri]
        l = int(rng.random() * min(len(r), ls_max)) + 1
        i = r.index(c)
        start = max(0, min(i - rng.randrange(l), len(r) - l))
        removed += r[start:start + l]; touched.add(ri)
        S.routes[ri] = r[:start] + r[start + l:]
    S.unassigned += removed
    # quitar clientes no siempre conserva la factibilidad (LIFO, soporte): las rutas acortadas se re-verifican
    keep = []
    for r in S.routes:
        if not r:
            continue
        seq = P.check(r, 1)
        if seq is None:
            S.unassigned += r
        else:
            keep.append(list(seq))
    S.routes = keep
    return S


def warm_solution(P, routes, rng):
    """Arranque desde rutas dadas (p. ej. de SENDA2): se conservan las que caben y se reinsertan los
    clientes de las demás."""
    keep, loose = [], []
    for r in sorted((list(r) for r in routes if r), key=lambda r: -len(r)):
        seq = P.check(r, 1) if len(keep) < P.k else None
        if seq is None:
            loose += r
        else:
            keep.append(list(seq))
    seen = {c for r in keep for c in r} | set(loose)
    loose += [c for c in range(1, P.n) if c not in seen and P.items[c]]
    return recreate(P, Solution(keep, loose), rng, blink=0.0, max_checks=10 ** 9)


def solve(P, time_limit=10.0, seed=1, init_routes=None):
    rng = random.Random(seed)
    start = time.perf_counter()
    clientes = [c for c in range(1, P.n) if P.items[c]]
    S = recreate(P, Solution([], clientes), rng, blink=0.0, max_checks=10 ** 9)
    if init_routes:
        W = warm_solution(P, init_routes, rng)
        if cost(P, W) < cost(P, S):
            S = W
    cur, cur_c = S, cost(P, S)
    best, best_c = (S.copy(), cur_c) if not S.unassigned else (None, math.inf)
    avg_edge = sum(P.D[0][c] for c in clientes) / max(1, len(clientes))
    T0, Tf = 0.1 * avg_edge, 0.001 * avg_edge
    it = 0
    while True:
        el = time.perf_counter() - start
        if el >= time_limit:
            break
        T = T0 * (Tf / T0) ** (el / time_limit)
        cand = recreate(P, ruin(P, cur.copy(), rng), rng)
        c = cost(P, cand)
        if c < cur_c - T * math.log(rng.random() + 1e-300):
            cur, cur_c = cand, c
            if not cand.unassigned and c < best_c - 1e-9:
                best, best_c = cand.copy(), c
        it += 1
    return {"best": best, "best_cost": best_c, "iters": it, "stats": dict(P.stats), "wall": time.perf_counter() - start}
