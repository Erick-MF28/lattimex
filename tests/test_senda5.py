# Copyright (c) 2026 LATTIMEX. Licencia MIT (ver LICENSE).
"""Regresiones de integración: selector, flota, matriz dirigida y reloj de SENDA5."""
import math
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from lattimex import cvrp, native
from tests.test_senda3 import _instancia


@unittest.skipUnless(native.CORE5_LIB.exists() and native.CORE2_LIB.exists(), "ejecute python -m lattimex build")
class Senda5Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        cls.small = _instancia(root, 124, 8, 1)
        cls.large = _instancia(root, 125, 8, 2)
        cls.short = _instancia(root, 200, 40, 3)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def verify(self, inst, result, fixed=False):
        self.assertTrue(result["verified"])
        routes = result["routes"]
        self.assertEqual(sorted(v for r in routes for v in r), sorted(inst.customers))
        self.assertTrue(all(sum(inst.demands[v] for v in r) <= inst.capacity for r in routes))
        cost = sum(int(math.dist(inst.coords[a], inst.coords[b]) + .5)
                   for r in routes for a, b in zip([inst.depot] + r, r + [inst.depot]))
        self.assertEqual(result["cost"], cost)
        if fixed:
            self.assertLessEqual(len(routes), inst.vehicle_count)

    def test_default_and_size_boundary(self):
        for inst, core in ((self.small, "senda2"), (self.large, "s5")):
            result = cvrp.solve(inst, time_sec=.5, fleet="fixed")
            self.verify(inst, result, fixed=True)
            self.assertEqual((result["router"], result["core"]), ("senda5", core))

    def test_short_routes_free_and_fixed_fleet(self):
        for fleet in ("free", "fixed"):
            with self.subTest(fleet=fleet):
                result = cvrp.solve(self.short, time_sec=.8, fleet=fleet)
                self.verify(self.short, result, fixed=fleet == "fixed")
                self.assertEqual(result["core"], "s5")

    def test_legacy_cli_cores_remain_selectable(self):
        for router in ("senda3", "senda2", "senda"):
            result = cvrp.solve(self.large, time_sec=.3, router=router)
            self.verify(self.large, result)
            self.assertEqual(result["router"], router)

    def test_forced_fallback_restores_selector(self):
        result = cvrp._trayectoria_senda3(self.small, .4, 1, "fixed", "senda5")
        self.verify(self.small, result, fixed=True)
        self.assertEqual(result["arms"][0]["config"], "s5_cadenas")
        result = cvrp.solve(self.small, .4, fleet="fixed")
        self.assertEqual(result["core"], "senda2")

    def test_failed_small_solution_uses_latest_fallback(self):
        original = cvrp.solve
        def solve(*args, **kwargs):
            if kwargs.get("router") == "senda2":
                return {"verified": False, "arms": []}
            return original(*args, **kwargs)
        with patch.object(cvrp, "solve", side_effect=solve):
            result = cvrp._solve_senda3(self.small, .6, 1, "fixed", "senda5")
        self.verify(self.small, result, fixed=True)
        self.assertEqual(result["core"], "senda2>s5")

    def test_engine_loads_senda5_and_preserves_short_route_policy(self):
        native.configure()
        import engine_runtime as er
        self.assertEqual(er.LIB2_PATH, native.CORE5_LIB)
        self.assertEqual(er.NUCLEO2, "senda5")
        self.assertEqual(er._elegir_nucleo("auto", 120, 10), "senda5")
        self.assertEqual(er._elegir_nucleo("auto", 120, 30), "senda")
        self.assertEqual(er._elegir_nucleo("senda5", 120, 30), "senda5")

    def test_directed_matrix_single_and_parallel(self):
        native.configure()
        import engine_runtime as er
        n = 130
        matrix = [[0 if a == b else 10 + abs(a - b) * 3 + (a * 13 + b * 7) % 17
                   for b in range(n)] for a in range(n)]
        demands = {i: 1 for i in range(1, n)}
        for parallel in (False, True):
            stats = {}
            routes = er._solve_routing(matrix, demands, 20, n, 7, .6, fleet_hint=-1,
                                       portafolio=parallel, stats=stats, router="senda5")
            self.assertEqual(sorted(v for r in routes for v in r), list(range(1, n)))
            self.assertTrue(all(len(r) <= 20 for r in routes))
            self.assertEqual(stats["router"], "senda5")
            self.assertEqual(stats["multi"], parallel)
            self.assertEqual(stats["dist"], sum(matrix[a][b] for r in routes for a, b in zip([0] + r, r + [0])))

    def test_corrected_clock_does_not_overrun_large_instance(self):
        inst = _instancia(Path(self.tmp.name), 502, 40, 9)
        start = time.perf_counter()
        result = cvrp.solve(inst, time_sec=1.5, fleet="free")
        self.verify(inst, result)
        # Margen para preparación y máquinas lentas del CI; sin exigir igualdad de rutas por pared.
        self.assertLess(time.perf_counter() - start, 2.5)


if __name__ == "__main__":
    unittest.main()
