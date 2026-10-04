# -*- coding: utf-8 -*-
"""Pruebas del motor (las mismas que validan la version de produccion 1.6.0).

    python -m lattimex build
    python -m unittest discover -s tests -v
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from lattimex import native  # noqa: E402

native.configure()

import engine_runtime as er                       # noqa: E402
from loading3d import ExtremePoint3D, LoadingOptions, settle_placements  # noqa: E402


def matriz(coords):
    return [[abs(a[0] - b[0]) + abs(a[1] - b[1]) for b in coords] for a in coords]


def apoyada(p, otros):
    """La caja descansa en el piso o toca la tapa de otra bajo su huella."""
    if p["z"] <= 1e-6:
        return True
    for q in otros:
        if q is p:
            continue
        if (abs(q["z"] + q["heightCm"] - p["z"]) <= 1e-6
                and p["x"] < q["x"] + q["lengthCm"] and q["x"] < p["x"] + p["lengthCm"]
                and p["y"] < q["y"] + q["widthCm"] and q["y"] < p["y"] + p["widthCm"]):
            return True
    return False


def peticion(coords, paquetes, fleet=1, cargo=(100, 100, 100), peso=1000, constraints=None,
             budget=1.0, doors=("rear", "left", "right")):
    return {"matrix_m": matriz(coords),
            "vehicle": {"cargo_cm": list(cargo), "max_weight_kg": peso, "doors": list(doors)},
            "fleet_count": fleet, "packages": paquetes, "budget_sec": budget,
            "constraints": constraints or {}, "seed": 7}


class AsentadoTest(unittest.TestCase):
    def test_caja_flotante_baja_hasta_apoyo(self):
        piso = {"guideId": "A", "x": 0, "y": 0, "z": 0, "zCm": 0, "lengthCm": 10, "widthCm": 10, "heightCm": 10}
        flota = {"guideId": "B", "x": 2, "y": 2, "z": 37, "zCm": 37, "lengthCm": 5, "widthCm": 5, "heightCm": 5}
        aire = {"guideId": "C", "x": 50, "y": 50, "z": 20, "zCm": 20, "lengthCm": 5, "widthCm": 5, "heightCm": 5}
        out, bajadas = settle_placements([piso, flota, aire])
        self.assertEqual(bajadas, 2)
        self.assertEqual([p["z"] for p in out], [0, 10, 0])
        self.assertEqual(flota["z"], 37, "no debe mutar la entrada")

    def test_evaluate_loading_only_no_deja_cajas_en_el_aire(self):
        solver = ExtremePoint3D(LoadingOptions(max_restarts=4, support_ratio=0.0))
        items = [{"guideId": f"G{i}", "clientIndex": 1, "dimensionsCm": [30, 30, 20 + 5 * (i % 3)]}
                 for i in range(9)]
        rep = solver.evaluate({"vehicle": {"cargoDimensions": [100, 100, 100]},
                               "deliveryOrder": [1], "items": items})
        self.assertEqual(rep["status"], "heuristic-feasible")
        for p in rep["placements"]:
            self.assertTrue(apoyada(p, rep["placements"]), p["guideId"])


class CacheEsfuerzoTest(unittest.TestCase):
    def test_rechazo_apurado_no_bloquea_reintento_con_mas_esfuerzo(self):
        cache = {}
        clave = "k"
        cache[clave] = {"status": "heuristic-unresolved", "_esfuerzo": 2}
        # misma logica que _pack_route: solo se reutiliza si fue factible o con >= esfuerzo
        cached = cache.get(clave)
        reutiliza = cached.get("status") == "heuristic-feasible" or cached.get("_esfuerzo", 0) >= 16
        self.assertFalse(reutiliza)
        cache[clave]["_esfuerzo"] = 16
        reutiliza = cached.get("status") == "heuristic-feasible" or cached.get("_esfuerzo", 0) >= 16
        self.assertTrue(reutiliza)


class EscaleraAlphaTest(unittest.TestCase):
    def test_escalera_termina_en_uno(self):
        self.assertEqual(list(er._escalera_alpha(0.59)), [0.59, 0.69, 0.79, 0.89, 0.99, 1.0])
        self.assertEqual(list(er._escalera_alpha(1.0)), [1.0])

    def test_carga_al_80_por_ciento_ya_no_se_rechaza(self):
        # 8 cajas de 100k cm3 = 0.8 V, un vehiculo. Con alpha 0.59 fijo esto lanzaba
        # "La carga no cabe en exactamente las unidades seleccionadas".
        coords = [(0, 0), (10, 0), (0, 10), (10, 10)]
        paquetes = [{"id": f"P{i}", "node": 1 + i % 3, "dims_cm": [50, 50, 40], "weight_kg": 1}
                    for i in range(8)]
        res = er.solve(peticion(coords, paquetes, fleet=1))
        self.assertEqual(res["vehicles"], 1)
        self.assertGreater(res["metrics"]["alpha_used"], res["metrics"]["alpha_base"])
        self.assertTrue(res["feasible"])


class FlotaExactaTest(unittest.TestCase):
    def test_conserva_la_solucion_del_nucleo_y_reparte_en_k_unidades(self):
        # 6 destinos diminutos: al nucleo le conviene una sola ruta; antes se
        # descartaba todo el ALNS y se devolvia la construccion greedy.
        coords = [(0, 0)] + [(5 * i, 3 * (i % 2)) for i in range(1, 7)]
        paquetes = [{"id": f"P{i}", "node": i, "dims_cm": [10, 10, 10], "weight_kg": 1}
                    for i in range(1, 7)]
        res = er.solve(peticion(coords, paquetes, fleet=3))
        self.assertEqual(res["vehicles"], 3)
        self.assertEqual(len([r for r in res["routes"] if r["sequence"]]), 3)
        self.assertIn(res["metrics"]["ajuste_flota"], ("nucleo", "division"))
        self.assertTrue(res["feasible"])


class MediacionTest(unittest.TestCase):
    def test_reubica_cliente_y_logra_factibilidad_sin_cambiar_flota(self):
        # A y B llevan cajas de 60x60x60 en caja de 100^3: caben en volumen
        # (2 x 216k < 590k) pero no en geometria. C lleva un cubo pequeno.
        coords = [(0, 0), (10, 0), (11, 0), (500, 0)]
        A, B, C = 1, 2, 3
        paquetes = [{"id": "PA", "node": A, "dims_cm": [60, 60, 60], "weight_kg": 1},
                    {"id": "PB", "node": B, "dims_cm": [60, 60, 60], "weight_kg": 1},
                    {"id": "PC", "node": C, "dims_cm": [10, 10, 10], "weight_kg": 1}]
        req = peticion(coords, paquetes, fleet=2)
        source = er._normalized_source(req, relaxed_fleet=2)
        items_idx = er._items_by_customer(source)
        alpha_cap = source["vehicle"]["capacity"] * 0.59
        cache = {}
        routes = [[A, B], [C]]
        reports = [er._pack_route(source, r, i, items_idx, "loading-only", cache) for i, r in enumerate(routes)]
        self.assertNotEqual(reports[0]["status"], "heuristic-feasible", "el fixture debe ser infactible")
        nuevas, nreps, bit = er._mediar(source, req["matrix_m"], routes, reports, items_idx,
                                        "loading-only", cache, alpha_cap, None, "fast")
        self.assertEqual(len(nuevas), 2)
        self.assertTrue(all(r["status"] == "heuristic-feasible" for r in nreps))
        self.assertGreaterEqual(bit["candidatos"], 1)
        self.assertEqual(bit["acciones"][-1]["accion"], "reubicar-cliente")

    def test_solve_integra_la_mediacion(self):
        coords = [(0, 0), (10, 0), (11, 0), (500, 0)]
        paquetes = [{"id": "PA", "node": 1, "dims_cm": [60, 60, 60], "weight_kg": 1},
                    {"id": "PB", "node": 2, "dims_cm": [60, 60, 60], "weight_kg": 1},
                    {"id": "PC", "node": 3, "dims_cm": [10, 10, 10], "weight_kg": 1}]
        res = er.solve(peticion(coords, paquetes, fleet=2))
        self.assertTrue(res["feasible"])
        self.assertEqual(res["vehicles"], 2)


class PortafolioTest(unittest.TestCase):
    def _instancia(self):
        coords = [(0, 0)] + [((i * 37) % 100, (i * 53) % 100) for i in range(1, 13)]
        paquetes = [{"id": f"P{i}", "node": i, "dims_cm": [20, 20, 20], "weight_kg": 1}
                    for i in range(1, 13)]
        return peticion(coords, paquetes, fleet=2, budget=1.0)

    def test_portafolio_activo_y_determinista(self):
        self.assertIsNotNone(er._MULTI, "el nucleo debe exportar senda_solve_multi_par")
        a = er.solve(self._instancia())
        b = er.solve(self._instancia())
        self.assertTrue(a["metrics"]["portafolio"])
        self.assertEqual(a["engine"]["router"], "senda-portfolio/2x2")
        self.assertEqual([r["sequence"] for r in a["routes"]], [r["sequence"] for r in b["routes"]])

    def test_normalizacion_es_conservadora(self):
        dem, cap = er._normalizar_demandas({1: 300.0, 2: 700.0, 3: 0.4}, 1000.0)
        self.assertEqual(cap, er.ESCALA_DEMANDA)
        self.assertEqual(dem[1] + dem[2], er.ESCALA_DEMANDA)   # exactamente lleno sigue cabiendo
        self.assertGreaterEqual(dem[3], 1)                     # nunca demanda cero
        self.assertGreaterEqual(dem[1], 300.0 / 1000.0 * er.ESCALA_DEMANDA)


def caja(gid, cliente, x, y, z, l=50, w=50, h=50):
    return {"guideId": gid, "clientIndex": cliente, "deliveryRank": cliente, "x": x, "y": y, "z": z,
            "lengthCm": l, "widthCm": w, "heightCm": h, "volumeCm3": l * w * h, "weightKg": 1,
            "fragile": False, "stackable": True}


class AccesoTest(unittest.TestCase):
    def test_ruta_de_un_cliente_es_cero_movimientos(self):
        acc = er._evaluar_acceso([1], [caja("A", 1, 0, 0, 0), caja("B", 1, 50, 0, 0)])
        self.assertTrue(acc["factible"])
        self.assertEqual((acc["entregas"], acc["movimientos_max"]), (1, 0))
        self.assertEqual(acc["puertas"], {"rear": 1})  # puertas por parada, no por bulto

    def test_bloqueo_trasero_se_resuelve_por_puerta_lateral(self):
        # Cliente 1 (primera entrega) al fondo en x=0..50; cliente 2 delante en x=50..100.
        # Por la trasera (x creciente) habria que apartar a B; por la lateral sale libre.
        pl = [caja("A", 1, 0, 0, 0), caja("B", 2, 50, 0, 0)]
        acc = er._evaluar_acceso([1, 2], pl, ["rear", "left", "right"])
        e1 = next(e for e in acc["plan"] if e["cliente"] == 1)
        self.assertEqual(e1["movimientos"], 0)
        self.assertIn(e1["puerta"], ("left", "right"))
        self.assertTrue(acc["factible"])

    def test_unidad_sin_laterales_no_propone_puerta_inexistente(self):
        # Mismo caso: con solo puerta trasera hay que apartar la caja de enfrente.
        pl = [caja("A", 1, 0, 0, 0), caja("B", 2, 50, 0, 0)]
        acc = er._evaluar_acceso([1, 2], pl, ["rear"])
        self.assertEqual(acc["puertas_disponibles"], ["rear"])
        self.assertEqual({e["puerta"] for e in acc["plan"]}, {"rear"})
        self.assertEqual(next(e for e in acc["plan"] if e["cliente"] == 1)["movimientos"], 1)

    def test_puertas_por_defecto_es_solo_trasera(self):
        pl = [caja("A", 1, 0, 0, 0), caja("B", 2, 50, 0, 0)]
        self.assertEqual(er._evaluar_acceso([1, 2], pl)["puertas_disponibles"], ["rear"])

    def test_exceso_se_reporta(self):
        # El validador no conoce paredes: una puerta solo se bloquea con cajas.
        # Cliente 1 en A (x 0-50, y 50-100). Trasera: 4 cajas delante en x.
        # Lateral izq: L1 al lado (y 0-50) con 3 encima (cierre vertical = 4).
        # Lateral der: R1 (y 100-150) con 3 encima. Las tres puertas piden 4.
        pl = [caja("A", 1, 0, 50, 0)]
        pl += [caja(f"B{k}", 2, 50 * (k + 1), 50, 0) for k in range(4)]
        pl += [caja("L1", 2, 0, 0, 0)] + [caja(f"L{k}", 2, 0, 0, 50 * (k - 1)) for k in range(2, 5)]
        pl += [caja("R1", 2, 0, 100, 0)] + [caja(f"R{k}", 2, 0, 100, 50 * (k - 1)) for k in range(2, 5)]
        acc = er._evaluar_acceso([1, 2], pl)
        self.assertFalse(acc["factible"])
        self.assertEqual(acc["entregas_con_exceso"], [1])
        self.assertEqual(acc["movimientos_max"], 4)

    def test_solve_incluye_acceso_en_cada_ruta(self):
        coords = [(0, 0)] + [((i * 37) % 100, (i * 53) % 100) for i in range(1, 9)]
        paquetes = [{"id": f"P{i}", "node": i, "dims_cm": [20, 20, 20], "weight_kg": 1} for i in range(1, 9)]
        res = er.solve(peticion(coords, paquetes, fleet=2, budget=0.5))
        for ru in res["routes"]:
            self.assertEqual(ru["acceso"]["entregas"], len(ru["sequence"]))
        self.assertEqual(res["metrics"]["acceso"]["entregas"], 8)


class RescateTest(unittest.TestCase):
    def _acc(self, plan_mov, exceso, mover=None):
        plan = [{"cliente": c, "puerta": "rear", "mover": (mover or {}).get(c, []), "movimientos": m}
                for c, m in plan_mov.items()]
        return {"factible": not exceso, "max_movimientos": 3, "entregas": len(plan),
                "entregas_con_exceso": exceso, "entregas_sin_movimientos": 0,
                "movimientos_max": max(plan_mov.values()), "puertas": {}, "plan": plan}

    def test_vecindad_genera_adelantos_intercambio_e_inversion(self):
        acc = self._acc({1: 0, 2: 0, 3: 5}, [3], mover={3: ["G1"]})
        cands = er._candidatos_rescate([1, 2, 3], acc, {"G1": 1})
        nombres = [n for n, _ in cands]
        self.assertEqual(nombres, ["adelantar-1", "adelantar-2", "invertir-segmento"])
        self.assertEqual(dict(cands)["adelantar-2"], [3, 1, 2])
        self.assertEqual(dict(cands)["invertir-segmento"], [3, 2, 1])

    def test_rescate_acepta_mejora_y_respeta_guarda_de_distancia(self):
        from unittest.mock import patch
        matrix = [[0, 10, 10, 10], [10, 0, 1, 50], [10, 1, 0, 1], [10, 50, 1, 0]]
        route = [1, 2, 3]                      # dist 0-1-2-3-0 = 10+1+1+10 = 22
        # El bloqueador principal de 3 es una caja del cliente 1: habilita invertir-segmento.
        acc0 = self._acc({1: 0, 2: 0, 3: 5}, [3], mover={3: ["G1"]})
        items_idx = {1: [{"guideId": "G1"}], 2: [{"guideId": "G2"}], 3: [{"guideId": "G3"}]}

        def pack(source, r, i, *a, **k):
            return {"status": "heuristic-feasible", "placements": [{"r": list(r)}]}

        def acceso(r, pl, puertas=None):
            # [3,2,1] resuelve (dist 10+1+1+10=22); [2,1,3]: 10+1+50+10=71 (>5 %, no debe evaluarse)
            return self._acc({1: 0, 2: 0, 3: 0}, []) if r == [3, 2, 1] else self._acc({1: 0, 2: 0, 3: 5}, [3])

        with patch.object(er, "_pack_route", side_effect=pack) as pk, patch.object(er, "_evaluar_acceso", side_effect=acceso):
            routes, reports, accesos, bit = er._rescatar_acceso(
                {}, matrix, [route], [{"status": "heuristic-feasible", "placements": []}], [acc0],
                items_idx, "loading-only", {}, None, "fast")
        self.assertEqual(routes[0], [3, 2, 1])
        self.assertTrue(accesos[0]["factible"])
        self.assertEqual(bit["rutas_rescatadas"], 1)
        for llamada in pk.call_args_list:              # ningun candidato por encima de +5 %
            self.assertLessEqual(er._route_distance_m(matrix, llamada.args[1]), 22 * 1.05 + 1e-9)

    def test_sin_exceso_no_evalua_candidatos(self):
        acc = self._acc({1: 0, 2: 1}, [])
        routes, reports, accesos, bit = er._rescatar_acceso(
            {}, [[0, 1, 1], [1, 0, 1], [1, 1, 0]], [[1, 2]], [{}], [acc], {}, "loading-only", {}, None, "fast")
        self.assertEqual(bit["candidatos"], 0)
        self.assertEqual(routes, [[1, 2]])


class ReoptTest(unittest.TestCase):
    def test_reopt_se_ejecuta_cuando_hay_factibilidad(self):
        coords = [(0, 0)] + [((i * 37) % 100, (i * 53) % 100) for i in range(1, 13)]
        paquetes = [{"id": f"P{i}", "node": i, "dims_cm": [20, 20, 20], "weight_kg": 1}
                    for i in range(1, 13)]
        res = er.solve(peticion(coords, paquetes, fleet=2, budget=1.0))
        self.assertTrue(res["feasible"])
        # 1.1.x comparaba perf_counter() < deadline*0.8 (absoluto x 0.8): nunca entraba.
        self.assertGreater(res["metrics"]["reopt_sec"], 0.0)
        self.assertGreaterEqual(res["metrics"]["reopt_gain_m"], 0.0)


if __name__ == "__main__":
    unittest.main()
