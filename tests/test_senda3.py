# Copyright (c) 2026 LATTIMEX. Licencia MIT (ver LICENSE).
"""SENDA3: selector por tamaño en lattimex.cvrp y núcleo del motor.

    python -m unittest tests.test_senda3
"""
from __future__ import annotations

import os
import random
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lattimex import cvrp, native  # noqa: E402


def _instancia(carpeta: Path, nodos: int, k: int, semilla: int) -> cvrp.Instance:
    """Instancia aleatoria en formato CVRPLIB con `nodos` nodos (clientes + depósito) y k rutas holgadas."""
    rng = random.Random(semilla)
    demandas = [0] + [rng.randint(1, 20) for _ in range(nodos - 1)]
    capacidad = int(sum(demandas) / k * 1.15) + 20
    lineas = [f"NAME : T-n{nodos}-k{k}", "TYPE : CVRP", f"DIMENSION : {nodos}", "EDGE_WEIGHT_TYPE : EUC_2D",
              f"CAPACITY : {capacidad}", "NODE_COORD_SECTION"]
    lineas += [f"{i + 1} {rng.randint(0, 1000)} {rng.randint(0, 1000)}" for i in range(nodos)]
    lineas += ["DEMAND_SECTION"] + [f"{i + 1} {d}" for i, d in enumerate(demandas)]
    lineas += ["DEPOT_SECTION", "1", "-1", "EOF"]
    ruta = carpeta / f"T-n{nodos}-k{k}.vrp"
    ruta.write_text("\n".join(lineas) + "\n", encoding="utf-8")
    return cvrp.read_cvrplib(ruta)


@unittest.skipUnless(native.CORE3_LIB.exists() and native.CORE2_LIB.exists(), "falta compilar: python -m lattimex build")
class Senda3Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        carpeta = Path(cls.tmp.name)
        cls.chica = _instancia(carpeta, cvrp.SENDA3_UMBRAL - 1, 8, 1)
        cls.grande = _instancia(carpeta, cvrp.SENDA3_UMBRAL, 8, 2)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_bajo_el_umbral_corre_senda2(self):
        res = cvrp.solve(self.chica, time_sec=1.0, seed=1, fleet="fixed", router="senda3")
        self.assertTrue(res["verified"])
        self.assertEqual(res["core"], "senda2")
        self.assertEqual(res["router"], "senda3")

    def test_desde_el_umbral_corre_el_bucle_s3(self):
        for flota in ("free", "fixed"):
            res = cvrp.solve(self.grande, time_sec=1.0, seed=1, fleet=flota, router="senda3")
            self.assertTrue(res["verified"], flota)
            self.assertEqual(res["core"], "s3")
            self.assertLessEqual(res["wall_sec"], 1.5)
            # una iteración del bucle S3 cuesta cientos de veces menos que una de SENDA2
            self.assertGreater(res["arms"][0]["iterations"], 20_000)
            if flota == "fixed":
                self.assertLessEqual(len(res["routes"]), self.grande.vehicle_count)

    def test_senda2_no_cambia_con_la_biblioteca_nueva(self):
        """router='senda2' sigue usando libsenda2: muchas menos iteraciones que el bucle S3."""
        res = cvrp.solve(self.grande, time_sec=1.0, seed=1, fleet="free", router="senda2")
        self.assertTrue(res["verified"])
        self.assertLess(sum(a["iterations"] for a in res["arms"]), 20_000)

    def test_respaldo_fuerza_s3_y_restaura_el_selector(self):
        """La trayectoria forzada corre S3 aun bajo el umbral y después la biblioteca vuelve a decidir por tamaño."""
        res = cvrp._trayectoria_senda3(self.chica, 0.6, 1, "fixed")
        self.assertTrue(res["verified"])
        self.assertGreater(res["arms"][0]["iterations"], 20_000)
        otra = cvrp.solve(self.chica, time_sec=0.6, seed=1, fleet="fixed", router="senda3")
        self.assertEqual(otra["core"], "senda2")

    def test_el_motor_usa_la_biblioteca_senda3(self):
        native.configure()
        self.assertEqual(os.environ.get("LATTIMEX_CORE3"), str(native.CORE3_LIB))
        import engine_runtime as er  # noqa: PLC0415
        self.assertEqual(er.LIB2_PATH, native.CORE3_LIB)


if __name__ == "__main__":
    unittest.main()
