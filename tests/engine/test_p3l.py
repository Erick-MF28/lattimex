# -*- coding: utf-8 -*-
"""Pruebas del acomodador P3L, del verificador estricto y de la relajación informada (versión 1.1.0).

    python -m lattimex build
    python -m unittest discover -s tests/engine -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from lattimex import native  # noqa: E402

native.configure()

import engine_runtime as er  # noqa: E402
import p3l_packer as pp  # noqa: E402


def caja(x, y, z, l, w, h, rank, fragile=False):
    return {"x": x, "y": y, "z": z, "l": l, "w": w, "h": h, "rank": rank, "fragile": fragile}


class VerificadorTest(unittest.TestCase):
    CARGO = [100, 50, 100]

    def test_acomodo_correcto(self):
        boxes = [caja(0, 0, 0, 100, 50, 50, 2), caja(0, 0, 50, 100, 50, 50, 1)]   # la última entrega abajo
        self.assertIsNone(pp.verify(boxes, self.CARGO, "all-constraints"))

    def test_caja_posterior_encima(self):
        # la 1.0.0 lo aceptaba: la caja de la segunda entrega queda encima de la primera
        boxes = [caja(0, 0, 0, 100, 50, 50, 1), caja(0, 0, 50, 100, 50, 50, 2)]
        self.assertEqual(pp.verify(boxes, self.CARGO, "all-constraints"), "orden-de-descarga-encima")
        self.assertIsNone(pp.verify(boxes, self.CARGO, "no-lifo"))

    def test_caja_posterior_delante(self):
        boxes = [caja(0, 0, 0, 50, 50, 50, 1), caja(50, 0, 0, 50, 50, 50, 2)]    # puerta en x = L
        self.assertEqual(pp.verify(boxes, self.CARGO, "no-support"), "orden-de-descarga-delante")

    def test_fragilidad_y_soporte(self):
        sobre_fragil = [caja(0, 0, 0, 100, 50, 50, 1, fragile=True), caja(0, 0, 50, 100, 50, 50, 1)]
        self.assertEqual(pp.verify(sobre_fragil, self.CARGO, "no-lifo"), "no-fragil-sobre-fragil")
        volada = [caja(0, 0, 0, 30, 50, 50, 1), caja(0, 0, 50, 100, 50, 50, 1)]
        self.assertEqual(pp.verify(volada, self.CARGO, "no-lifo"), "soporte-insuficiente")
        self.assertIsNone(pp.verify(volada, self.CARGO, "loading-only"))

    def test_solape_y_limites(self):
        self.assertEqual(pp.verify([caja(0, 0, 0, 60, 50, 50, 1), caja(50, 0, 0, 50, 50, 50, 1)],
                                   self.CARGO, "loading-only"), "solape")
        self.assertEqual(pp.verify([caja(60, 0, 0, 50, 50, 50, 1)], self.CARGO, "loading-only"), "fuera-del-contenedor")


class P3LTest(unittest.TestCase):
    def test_disponible_y_valido(self):
        self.assertTrue(pp.AVAILABLE, "compile con `python -m lattimex build`")
        items = [{"id": f"I{i}", "dims": [40 + 5 * (i % 3), 30, 20 + 10 * (i % 2)], "rank": 1 + i // 3, "fragile": i % 4 == 0}
                 for i in range(12)]
        ok, pl = pp.pack(items, [300, 150, 150], "all-constraints")
        self.assertTrue(ok)
        rank = {it["id"]: it for it in items}
        boxes = [{**b, "rank": rank[b["id"]]["rank"], "fragile": rank[b["id"]]["fragile"]} for b in pl]
        self.assertIsNone(pp.verify(boxes, [300, 150, 150], "all-constraints"))


def peticion_cuadro():
    """Cuatro entregas en cuadro, alternando no frágil / frágil; cada caja llena una capa entera.
    Con orden de descarga no existe acomodo para ningún orden del ciclo; sin él, sí."""
    coords = [(0, 0), (10, 0), (0, 10), (-10, 0), (0, -10)]
    M = [[float(round(((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** .5 * 100)) for b in coords] for a in coords]
    paquetes = [{"id": f"P{i}", "node": i, "dims_cm": [100, 50, 25], "weight_kg": 1, "fragile": i % 2 == 0,
                 "keep_upright": True} for i in range(1, 5)]
    return {"matrix_m": M, "vehicle": {"cargo_cm": [100, 50, 100], "max_weight_kg": 100}, "fleet_count": 1,
            "packages": paquetes, "constraints": {"support": True, "fragility": True, "lifo": True},
            "budget_sec": 1.0, "seed": 3}


class RelajacionInformadaTest(unittest.TestCase):
    def test_ruta_imposible_se_relaja_y_se_informa(self):
        res = er.solve(peticion_cuadro())
        self.assertTrue(res["feasible"])
        self.assertFalse(res["lifo_estricto"])
        self.assertFalse(res["routes"][0]["lifo_respetado"])
        self.assertEqual(res["advertencias"][0]["codigo"], "orden-de-descarga-relajado")
        self.assertEqual(res["advertencias"][0]["rutas"], [0])

    def test_sin_orden_de_descarga_no_hay_advertencia(self):
        req = peticion_cuadro()
        req["constraints"]["lifo"] = False
        res = er.solve(req)
        self.assertTrue(res["feasible"])
        self.assertTrue(res["lifo_estricto"])
        self.assertEqual(res["advertencias"], [])

    def test_empaque_estricto_no_relaja_por_su_cuenta(self):
        req = peticion_cuadro()
        source = er._normalized_source(req, 1)
        idx = er._items_by_customer(source)
        rep = er._pack_route(source, [1, 2, 3, 4], 0, idx, "all-constraints", {})
        self.assertNotEqual(rep["status"], "heuristic-feasible")
        rel = er._pack_route(source, [1, 2, 3, 4], 0, idx, "all-constraints", {}, relajar=True)
        self.assertEqual(rel["status"], "heuristic-feasible")
        self.assertFalse(rel["lifo_respetado"])


class OrdenSinExigirloTest(unittest.TestCase):
    """Sin orden de descarga P3L colocaba las cajas sin mirar la entrega: la primera podía quedar junto
    a la cabina y el operador tenía que apartar hasta 21 cajas (Planner, 300 entregas Qro)."""

    def peticion(self, constraints):
        coords = [(0, 0)] + [(10 * i, 0) for i in range(1, 9)]
        M = [[float(abs(a[0] - b[0]) * 100) for b in coords] for a in coords]
        paquetes = [{"id": f"P{i}{k}", "node": i, "dims_cm": [40, 30, 30], "weight_kg": 5}
                    for i in range(1, 9) for k in range(3)]
        return {"matrix_m": M, "vehicle": {"cargo_cm": [300, 150, 150], "max_weight_kg": 1000,
                                           "doors": ["rear"]}, "fleet_count": 1,
                "packages": paquetes, "constraints": constraints, "budget_sec": 1.0, "seed": 3}

    def test_sin_lifo_igual_respeta_el_orden_si_cabe(self):
        for c in ({"support": True, "fragility": True, "lifo": False},
                  {"support": False, "fragility": False, "lifo": False}):
            res = er.solve(self.peticion(c))
            self.assertTrue(res["feasible"])
            ruta = res["routes"][0]
            self.assertEqual(ruta["acceso"]["movimientos_max"], 0, c)
            orden = er._variant(c) if er._con_lifo(er._variant(c)) is None else er._con_lifo(er._variant(c))
            self.assertIsNone(er._verificar(ruta["placements"], [300, 150, 150], orden), c)


class R3LTest(unittest.TestCase):
    def test_hasta_k_respeta_el_orden_de_descarga(self):
        # con 2 unidades disponibles y flota "hasta k", R3L reparte el cuadro sin relajar nada
        req = dict(peticion_cuadro(), fleet_count=2, fleet_mode="up_to", budget_sec=2.0)
        res = er.solve(req)
        self.assertTrue(res["feasible"])
        self.assertTrue(res["lifo_estricto"])
        self.assertEqual(res["advertencias"], [])
        self.assertLessEqual(res["vehicles"], 2)
        self.assertEqual(sorted(c for r in res["routes"] for c in r["sequence"]), [1, 2, 3, 4])

    def test_flota_exacta_no_usa_r3l(self):
        res = er.solve(dict(peticion_cuadro(), fleet_count=2, budget_sec=1.0))
        self.assertNotEqual(res["metrics"].get("nucleo"), "senda2+r3l")
        self.assertEqual(res["vehicles"], 2)


if __name__ == "__main__":
    unittest.main()
