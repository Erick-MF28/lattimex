# -*- coding: utf-8 -*-
"""Pruebas de las tres formas de uso de la versión 1.1.0: SENDA2 solo (`lattimex cvrp`), el acomodador
solo (`lattimex pack`) y el motor completo (cubierto por las demás pruebas).

    python -m lattimex build
    python -m unittest discover -s tests/engine -v
"""
from __future__ import annotations

import json
import random
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from lattimex import cvrp  # noqa: E402


def instancia_vrp(path: Path, n: int = 30, cap: int = 50, k: int = 6, seed: int = 4) -> None:
    rng = random.Random(seed)
    lines = [f"NAME : prueba-n{n + 1}-k{k}", "TYPE : CVRP", f"DIMENSION : {n + 1}", "EDGE_WEIGHT_TYPE : EUC_2D",
             f"CAPACITY : {cap}", "NODE_COORD_SECTION"]
    lines += [f"{i} {rng.randint(0, 100)} {rng.randint(0, 100)}" for i in range(1, n + 2)]
    lines += ["DEMAND_SECTION"] + [f"{i} {0 if i == 1 else rng.randint(1, 15)}" for i in range(1, n + 2)]
    lines += ["DEPOT_SECTION", "1", "-1", "EOF"]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


class CVRPTest(unittest.TestCase):
    def test_senda2_y_senda_resuelven_y_verifican(self):
        with tempfile.TemporaryDirectory() as tmp:
            vrp = Path(tmp) / "prueba.vrp"
            instancia_vrp(vrp)
            inst = cvrp.read_cvrplib(vrp)
            self.assertEqual(inst.vehicle_hint, 6)
            for router in ("senda2", "senda"):
                res = cvrp.solve(inst, time_sec=0.5, seed=1, fleet="fixed", router=router)
                self.assertTrue(res["verified"], router)
                self.assertLessEqual(len(res["routes"]), 6)
                self.assertEqual(res["cost"], inst.cost(res["routes"]))

    def test_linea_de_comandos(self):
        with tempfile.TemporaryDirectory() as tmp:
            vrp, sol = Path(tmp) / "prueba.vrp", Path(tmp) / "prueba.sol"
            instancia_vrp(vrp)
            out = subprocess.run([sys.executable, "-m", "lattimex", "cvrp", str(vrp), "--time", "0.5", "--sol", str(sol)],
                                 capture_output=True, text=True, cwd=ROOT, check=True)
            res = json.loads(out.stdout.strip().splitlines()[-1])
            self.assertTrue(res["verified"])
            self.assertTrue(sol.read_text().strip().splitlines()[-1].startswith("Cost "))


class PackTest(unittest.TestCase):
    def test_acomodador_solo(self):
        datos = {"cargo_cm": [240, 120, 120], "constraints": {"support": True, "fragility": True, "lifo": True},
                 "items": [{"id": f"C{i}", "dims_cm": [40, 30, 30 + 10 * (i % 3)], "stop": 1 + i // 4,
                            "fragile": i % 5 == 0} for i in range(16)]}
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "cajas.json"
            f.write_text(json.dumps(datos), encoding="utf-8")
            out = subprocess.run([sys.executable, "-m", "lattimex", "pack", str(f)], capture_output=True, text=True,
                                 cwd=ROOT, check=True)
            res = json.loads(out.stdout)
            self.assertEqual(res["variant"], "all-constraints")
            self.assertTrue(res["all_placed"])
            self.assertTrue(res["verified"])
            self.assertEqual(len(res["placements"]), 16)


if __name__ == "__main__":
    unittest.main()
