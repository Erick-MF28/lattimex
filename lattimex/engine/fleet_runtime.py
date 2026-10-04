"""Private heterogeneous fleet orchestration; existing SENDA ABI is unchanged.

Heuristic assignments have finite search limits, actual per-vehicle capacity
and independent 3D validation. Failure means unresolved, not proven infeasible.
"""
from __future__ import annotations

import itertools
import math
import time

ASSIGNMENT_STATES = 4000
ASSIGNMENT_STARTS = 4
REPAIR_CANDIDATES = 24


def _fits(item, vehicle):
    dims = item['dims_cm']
    rotations = [(dims[0], dims[1], dims[2]), (dims[1], dims[0], dims[2])] \
        if item.get('keep_upright') else set(itertools.permutations(dims))
    return any(all(a <= b + 1e-6 for a, b in zip(rotation, vehicle['cargo_cm'])) for rotation in rotations)


def _insertion(matrix, route, node):
    positions = [(matrix[a][node] + matrix[node][b] - matrix[a][b], i)
                 for i, (a, b) in enumerate(zip([0] + route, route + [0]))]
    return min(positions)


def _assign(matrix, nodes, eligible, volumes, weights, caps, limits, attempt, deadline):
    """Bounded backtracking, most constrained customers first; exact used fleet."""
    k = len(caps)
    order = sorted(nodes, key=lambda n: (len(eligible[n]),
        -max(volumes[n] / max(caps[i] for i in eligible[n]),
             weights[n] / max(limits[i] for i in eligible[n])),
        ((n * 7919 + attempt * 104729) % 65521) if attempt else n))
    routes = [[] for _ in caps]; loads = [0.] * k; masses = [0.] * k
    states = 0

    def search(pos):
        nonlocal states
        states += 1
        if states > ASSIGNMENT_STATES or time.perf_counter() > deadline:
            return False
        if pos == len(order):
            return all(routes)
        node = order[pos]
        empty = sum(not route for route in routes)
        options = []
        for i in eligible[node]:
            if len(order) - pos == empty and routes[i]:
                continue
            if loads[i] + volumes[node] > caps[i] + 1e-6 or masses[i] + weights[node] > limits[i] + 1e-6:
                continue
            delta, at = _insertion(matrix, routes[i], node)
            pressure = max((loads[i]+volumes[node])/caps[i], (masses[i]+weights[node])/limits[i])
            # Different complete candidates, all under physical limits.
            key = ((pressure, delta) if attempt % 2 else (delta, pressure))
            options.append((key, (i + attempt) % k, i, at))
        for _, _, i, at in sorted(options):
            routes[i].insert(at, node); loads[i] += volumes[node]; masses[i] += weights[node]
            if search(pos + 1):
                return True
            routes[i].pop(at); loads[i] -= volumes[node]; masses[i] -= weights[node]
        return False

    return ([list(r) for r in routes] if search(0) else None), states


def solve_fleet(req, er):
    started = time.perf_counter()
    fleet = req['fleet']; matrix = req['matrix_m']; k = len(fleet)
    budget = float(req.get('budget_sec', 10)); profile = req.get('perfil', 'fast')
    deadline = started + max(budget * er.PERFILES.get(profile, er.PERFILES['fast'])['reloj'], budget + 30)
    assignment_deadline = min(deadline, started + max(1., budget * .25))
    variant = er._variant(req.get('constraints') or {})
    sources = [er._normalized_source(dict(req, vehicle=v), 1) for v in fleet]
    items = er._items_by_customer(sources[0])
    caps = [s['vehicle']['capacity'] for s in sources]
    limits = [s['vehicle']['maxWeightKg'] for s in sources]
    packages = {}
    for package in req['packages']:
        packages.setdefault(package['node'], []).append(package)
    nodes = sorted(packages)
    volumes = {n: sum(math.prod(p['dims_cm']) for p in packages[n]) for n in nodes}
    weights = {n: sum(float(p.get('weight_kg', 0)) for p in packages[n]) for n in nodes}
    eligible = {n: [i for i, v in enumerate(fleet) if volumes[n] <= caps[i] + 1e-6 and
        weights[n] <= limits[i] + 1e-6 and all(_fits(p, v) for p in packages[n])] for n in nodes}
    cache = {}; counters = {'assignment_states': 0, 'assignment_candidates': 0, 'repair_candidates': 0}

    def capacity_ok(route, i):
        return bool(route and all(i in eligible[n] for n in route) and
            sum(volumes[n] for n in route) <= caps[i] + 1e-6 and
            sum(weights[n] for n in route) <= limits[i] + 1e-6)

    def pack(route, i):
        return er._pack_route(sources[i], route, i, items, variant, cache, deadline=deadline, perfil=profile)

    def key(routes, reports):
        return er._clave_solucion(matrix, routes, reports)

    best = None
    assignments = set()
    if len(nodes) >= k and all(eligible.values()) and sum(volumes.values()) <= sum(caps)+1e-6 \
            and sum(weights.values()) <= sum(limits)+1e-6:
        for attempt in range(ASSIGNMENT_STARTS):
            if time.perf_counter() > deadline:
                break
            routes, states = _assign(matrix, nodes, eligible, volumes, weights, caps, limits,
                                     attempt, assignment_deadline)
            counters['assignment_states'] += states
            if routes is None:
                continue
            signature = tuple(tuple(sorted(r)) for r in routes)
            if signature in assignments:
                continue
            assignments.add(signature); counters['assignment_candidates'] += 1
            reports = [pack(r, i) for i, r in enumerate(routes)]
            candidate = (key(routes, reports), routes, reports)
            if best is None or candidate[0] < best[0]:
                best = candidate
            if candidate[0][0] == 0:
                break

    if best is not None:
        _, routes, reports = best
        # Repair actual packing failures with bounded moves/swaps between units.
        for _ in range(3):
            current = key(routes, reports); improved = None; evaluated = 0
            if current[0] == 0 or time.perf_counter() > deadline:
                break
            for i, report in enumerate(reports):
                if report['status'] == 'heuristic-feasible':
                    continue
                for node in routes[i][:8]:
                    for j in eligible[node]:
                        if i == j:
                            continue
                        for other in [None] + routes[j][:3]:
                            if other is None and len(routes[i]) == 1:
                                continue
                            left = [n for n in routes[i] if n != node]
                            right = [n for n in routes[j] if n != other]
                            right.insert(_insertion(matrix, right, node)[1], node)
                            if other is not None:
                                left.insert(_insertion(matrix, left, other)[1], other)
                            if not capacity_ok(left, i) or not capacity_ok(right, j):
                                continue
                            if evaluated >= REPAIR_CANDIDATES or time.perf_counter() > deadline:
                                break
                            evaluated += 1
                            candidate_routes = list(routes); candidate_reports = list(reports)
                            candidate_routes[i], candidate_routes[j] = left, right
                            candidate_reports[i], candidate_reports[j] = pack(left, i), pack(right, j)
                            if key(candidate_routes, candidate_reports) < current:
                                improved = (candidate_routes, candidate_reports)
                                break
                        if improved or evaluated >= REPAIR_CANDIDATES:
                            break
                    if improved or evaluated >= REPAIR_CANDIDATES:
                        break
                if improved or evaluated >= REPAIR_CANDIDATES:
                    break
            counters['repair_candidates'] += evaluated
            if not improved:
                break
            routes, reports = improved

        # SENDA optimizes each assigned sequence without changing its vehicle.
        routing_deadline = min(deadline, started + budget)
        for i, route in enumerate(routes):
            remaining = routing_deadline - time.perf_counter()
            if remaining < .1 or reports[i]['status'] != 'heuristic-feasible' or len(route) < 3:
                continue
            indexes = [0] + route
            local_matrix = [[matrix[a][b] for b in indexes] for a in indexes]
            local_demands = {j: volumes[n] for j, n in enumerate(indexes) if j}
            candidate = er._solve_routing(local_matrix, local_demands, caps[i], len(indexes),
                int(req.get('seed', 20260726)) + i, remaining / (k - i),
                warm=[list(range(1, len(indexes)))], fleet_hint=1)
            if len(candidate) != 1 or sorted(candidate[0]) != list(range(1, len(indexes))):
                continue
            sequence = [indexes[j] for j in candidate[0]]
            if er._route_distance_m(matrix, sequence) >= er._route_distance_m(matrix, route) - 1e-6:
                continue
            report = pack(sequence, i)
            if report['status'] == 'heuristic-feasible':
                routes[i], reports[i] = sequence, report
    else:
        routes, reports = [], []

    feasible = (len(routes) == k and all(report['status'] == 'heuristic-feasible' for report in reports)
                and all(capacity_ok(route, i) for i, route in enumerate(routes)))
    if routes:
        assert sorted(n for route in routes for n in route) == nodes
    accesses = [er._evaluar_acceso(route, report.get('placements') or [], fleet[i].get('doors', ['rear']))
        if report['status'] == 'heuristic-feasible' else None
        for i, (route, report) in enumerate(zip(routes, reports))]
    rescues = []
    if feasible and er.RESCATE:
        for i in range(k):
            rs, reps, accs, log = er._rescatar_acceso(sources[i], matrix, [routes[i]], [reports[i]],
                [accesses[i]], items, variant, cache, deadline, profile, fleet[i].get('doors', ['rear']))
            routes[i], reports[i], accesses[i] = rs[0], reps[0], accs[0]
            rescues.append({'vehicle_index': i, **log})
    out_routes = []
    for i, (route, report) in enumerate(zip(routes, reports)):
        out_routes.append({'vehicle_index': i, 'sequence': route,
            'distance_m': round(er._route_distance_m(matrix, route), 1),
            'packages': [p['id'] for n in route for p in packages[n]],
            'loading_status': report['status'], 'placements': report.get('placements'),
            'utilization': report.get('utilization'), 'acceso': accesses[i],
            'packing_feasible': report['status'] == 'heuristic-feasible',
            'operational_feasible': accesses[i]['factible'] if accesses[i] else None,
            'lifo_respetado': report.get('lifo_respetado', True)})
    return {'contract': 'pen3q.lattimex.solve.v1', 'feasible': feasible, 'packing_feasible': feasible,
        'operational_feasible': all(a['factible'] for a in accesses) if feasible and all(accesses) else None,
        'solution_status': 'feasible' if feasible else 'heuristic-unresolved',
        'vehicles': len(routes), 'total_distance_m': round(sum(r['distance_m'] for r in out_routes), 1),
        'routes': out_routes, 'metrics': {'runtime_sec': round(time.perf_counter()-started, 3),
            'fleet': counters, 'acceso_rescate': rescues},
        'engine': {'version': er.ENGINE_VERSION, 'core': er.CORE_SHA, 'perfil': profile,
                   'router': 'senda-per-assigned-vehicle'}}
