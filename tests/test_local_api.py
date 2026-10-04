# Copyright (c) 2026 LATTIMEX. Licencia MIT (ver LICENSE).
"""Pruebas de llamada del servidor local, de punta a punta.

Construye un mapa sintético (cuadrícula de calles en formato OSM), levanta el
servidor en un puerto libre y ejerce el mismo recorrido que hace el Planner:
arranque -> flota -> guías -> ubicación en calles -> optimización -> geometrías.
También comprueba las defensas: Host, Origin, token y preflight CORS.

    python -m lattimex build
    python -m unittest tests.test_local_api -v
"""
from __future__ import annotations

import json
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lattimex import maps, server  # noqa: E402

ORIGIN = "http://planner.test"


def synthetic_osm(path: Path, size: int = 14, step: float = 0.0015) -> None:
    lat0, lng0 = 20.5900, -100.3900
    nodes, ways, nid, wid = [], [], 1, 1
    grid = {}
    for i in range(size):
        for j in range(size):
            grid[i, j] = nid
            nodes.append(f'<node id="{nid}" lat="{lat0 + i * step:.6f}" lon="{lng0 + j * step:.6f}"/>')
            nid += 1
    for i in range(size):
        cls = "primary" if i == size // 2 else "residential"
        row = "".join(f'<nd ref="{grid[i, j]}"/>' for j in range(size))
        col = "".join(f'<nd ref="{grid[j, i]}"/>' for j in range(size))
        ways.append(f'<way id="{wid}">{row}<tag k="highway" v="{cls}"/></way>'); wid += 1
        ways.append(f'<way id="{wid}">{col}<tag k="highway" v="residential"/></way>'); wid += 1
    ways.append(f'<way id="{wid}"><nd ref="1"/><nd ref="2"/><tag k="highway" v="service"/>'
                f'<tag k="service" v="parking_aisle"/></way>')
    path.write_text('<?xml version="1.0"?><osm version="0.6">' + "".join(nodes) + "".join(ways) + "</osm>",
                    encoding="utf-8")


class LocalApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # ignore_cleanup_errors: en Windows SQLite puede retener el archivo unos milisegundos
        cls.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        data = Path(cls.tmp.name)
        osm = data / "grid.osm"
        synthetic_osm(osm)
        cls.meta = maps.build_map(osm, "grid", data / "maps")
        cls.httpd = server.serve(data, 0, None, (ORIGIN,))
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.token = cls.call("GET", "/api/runtime")[1]["runtime_token"]

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown(); cls.httpd.server_close(); cls.tmp.cleanup()

    @classmethod
    def call(cls, method, path, body=None, origin=ORIGIN, host=None, token=True, headers=None):
        h = {"Origin": origin} if origin else {}
        if host:
            h["Host"] = host
        if token and getattr(cls, "token", None):
            h["X-LATTIMEX-Runtime-Token"] = cls.token
        if body is not None:
            h["Content-Type"] = "application/json"
        h.update(headers or {})
        req = urllib.request.Request(f"http://127.0.0.1:{cls.port}{path}", method=method, headers=h,
                                     data=None if body is None else json.dumps(body).encode())
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                raw = r.read()
                return r.status, (json.loads(raw) if raw else {}), dict(r.headers)
        except urllib.error.HTTPError as e:
            raw = e.read()
            return e.code, (json.loads(raw) if raw else {}), dict(e.headers)

    # --- mapa -------------------------------------------------------------
    def test_map_build_excludes_parking_and_keeps_grid(self):
        self.assertEqual(self.meta["nodes"], 14 * 14)
        roads = json.loads((Path(self.tmp.name) / "maps" / "grid.roads.json").read_text(encoding="utf-8"))
        self.assertEqual(roads["format"], "lattimex.roads.v1")
        self.assertIn("OpenStreetMap", roads["attribution"])
        self.assertEqual(sum(len(layer) for layer in roads["layers"]), 28)   # la vía de estacionamiento no entra

    # --- defensas -----------------------------------------------------------
    def test_rejects_foreign_origin(self):
        status, body, _ = self.call("GET", "/api/runtime", origin="https://evil.example", token=False)
        self.assertEqual(status, 403)

    def test_rejects_missing_origin(self):
        status, _, _ = self.call("GET", "/api/catalog/vehicles", origin=None)
        self.assertEqual(status, 403)

    def test_rejects_dns_rebinding_host(self):
        status, _, _ = self.call("GET", "/api/runtime", host=f"evil.example:{self.port}", token=False)
        self.assertEqual(status, 403)

    def test_rejects_bad_token(self):
        status, _, _ = self.call("GET", "/api/catalog/vehicles", headers={"X-LATTIMEX-Runtime-Token": "x"})
        self.assertEqual(status, 401)

    def test_preflight_allows_planner_and_private_network(self):
        status, _, headers = self.call("OPTIONS", "/api/engine/v1/solve", token=False, headers={
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type,x-lattimex-runtime-token",
            "Access-Control-Request-Private-Network": "true"})
        self.assertEqual(status, 204)
        self.assertEqual(headers.get("Access-Control-Allow-Origin"), ORIGIN)
        self.assertEqual(headers.get("Access-Control-Allow-Private-Network"), "true")
        status, _, _ = self.call("OPTIONS", "/api/engine/v1/solve", origin="https://evil.example", token=False)
        self.assertEqual(status, 403)

    def test_health_does_not_expose_data(self):
        status, body, _ = self.call("GET", "/", origin=None, token=False)
        self.assertEqual(status, 200)
        self.assertEqual(set(body), {"lattimex", "engine", "status", "planner"})

    # --- recorrido completo del Planner -----------------------------------------
    def test_full_planning_flow(self):
        s, v, _ = self.call("POST", "/api/catalog/vehicles", {
            "name": "VAN-01", "km_per_liter": 9, "cargo_length_cm": 300, "cargo_width_cm": 150,
            "cargo_height_cm": 150, "max_weight_kg": 1200, "doors": ["rear"]})
        self.assertEqual(s, 201, v)
        s, op, _ = self.call("POST", "/api/catalog/operators", {"name": "Operador 01", "cost_per_day_mxn": 400})
        self.assertEqual(s, 201, op)
        lat0, lng0, st = 20.5900, -100.3900, 0.0015
        guides = [{"tracking_code": f"G{i:02d}", "lat": lat0 + (i % 12 + 1) * st, "lng": lng0 + (i * 5 % 12 + 1) * st,
                   "length_cm": 40, "width_cm": 30, "height_cm": 25, "weight_kg": 6}
                  for i in range(12)]
        s, inst, _ = self.call("POST", "/api/instances", {"name": "prueba", "depot_lat": lat0, "depot_lng": lng0,
                                                          "guides": guides})
        self.assertEqual(s, 201, inst)
        points = [{"lat": lat0, "lng": lng0}] + [{"lat": g["lat"], "lng": g["lng"]} for g in guides]
        s, snap, _ = self.call("POST", "/api/network/snap", {"points": points})
        self.assertEqual(s, 200, snap)
        self.assertEqual(len(snap["snapped_points"]), 13)
        payload = {"points": points,
                   "fleet": [{"cargo_cm": [300, 150, 150], "max_weight_kg": 1200, "doors": ["rear"]}] * 2,
                   "fleet_count": 2,
                   "packages": [{"id": g["tracking_code"], "node": i + 1, "dims_cm": [40, 30, 25], "weight_kg": 6}
                                for i, g in enumerate(guides)],
                   "constraints": {"support": True, "fragility": False, "lifo": False}, "budget_sec": 2}
        s, job, _ = self.call("POST", "/api/engine/v1/solve", payload)
        self.assertEqual(s, 202, job)
        for _ in range(240):
            s, st_, _ = self.call("GET", f"/api/engine/v1/jobs/{job['id']}")
            if st_["status"] in ("done", "error"):
                break
            time.sleep(0.5)
        self.assertEqual(st_["status"], "done", st_)
        result = st_["result"]
        self.assertTrue(result["feasible"])
        served = sorted(n for r in result["routes"] for n in r["sequence"])
        self.assertEqual(served, list(range(1, 13)))
        self.assertTrue(all("placements" in r for r in result["routes"]))
        s, geo, _ = self.call("POST", "/api/network/paths",
                              {"points": snap["snapped_points"], "routes": [r["sequence"] for r in result["routes"]]})
        self.assertEqual(s, 200, geo)
        s, roads, _ = self.call("GET", "/api/map/roads")
        self.assertEqual(s, 200)
        self.assertEqual(roads["format"], "lattimex.roads.v1")

    def test_delete_guides_runs_and_instances(self):
        results = Path(self.tmp.name) / "resultados"
        guides = [{"tracking_code": f"B{i}", "lat": 20.59 + i * 0.001, "lng": -100.39, "length_cm": 20,
                   "width_cm": 20, "height_cm": 20, "weight_kg": 1} for i in range(3)]
        s, inst, _ = self.call("POST", "/api/instances", {"name": "borrar", "depot_lat": 20.59, "depot_lng": -100.39,
                                                          "guides": guides})
        self.assertEqual(s, 201, inst)
        gid = inst["guides"][0]["id"]
        s, _, _ = self.call("DELETE", f"/api/instances/{inst['id']}/guides/{gid}")
        self.assertEqual(s, 200)
        self.assertEqual(len(self.call("GET", f"/api/instances/{inst['id']}")[1]["guides"]), 2)

        def run():
            s, r, _ = self.call("POST", "/api/planning-runs", {"instance_id": inst["id"], "result": {"routes": []}})
            self.assertEqual(s, 201, r)
            self.assertTrue((results / f"ejecucion_{r['id']:06d}.json").exists())
            return r["id"]
        r1 = run()
        self.assertEqual(self.call("DELETE", f"/api/planning-runs/{r1}")[0], 200)
        self.assertFalse((results / f"ejecucion_{r1:06d}.json").exists())
        self.assertEqual(self.call("GET", f"/api/planning-runs/{r1}")[0], 404)
        r2, r3 = run(), run()
        s, body, _ = self.call("DELETE", "/api/planning-runs")
        self.assertEqual((s, body["deleted"] >= 2), (200, True))
        self.assertFalse(any((results / f"ejecucion_{r:06d}.json").exists() for r in (r2, r3)))
        r4 = run()
        self.assertEqual(self.call("DELETE", f"/api/instances/{inst['id']}")[0], 200)
        self.assertFalse((results / f"ejecucion_{r4:06d}.json").exists())
        self.assertEqual(self.call("GET", f"/api/planning-runs/{r4}")[0], 404)

    def test_capture_draft_survives_restart(self):
        draft = {"name": "captura a medias", "depot_lat": 20.59, "depot_lng": -100.39,
                 "guides": [{"tracking_code": "D1", "lat": 20.6, "lng": -100.4, "weight_kg": 2}]}
        s, body, _ = self.call("PUT", "/api/capture-draft", {"draft": draft})
        self.assertEqual((s, body["draft"]), (200, draft))
        # Otra conexión a la misma base (equivale a reiniciar el servidor) ve el mismo borrador.
        again = server.LocalStore(Path(self.tmp.name) / "lattimex.sqlite3").get_capture_draft()
        self.assertEqual(again["draft"], draft)
        self.assertEqual(self.call("PUT", "/api/capture-draft", {"draft": {"guides": "x"}})[0], 400)
        s, body, _ = self.call("DELETE", "/api/capture-draft")
        self.assertEqual((s, body["draft"]), (200, None))

    def test_fuel_settings_auto_and_manual(self):
        s, cfg, _ = self.call("GET", "/api/settings/fuel")
        self.assertEqual((s, cfg["mode"], cfg["effective_source"]), (200, "auto", "manual"))
        self.assertTrue(cfg["stale"])                     # nunca se ha consultado la CRE
        fake = {"prices": {"regular": 23.94, "diesel": 26.99}, "stations": {"regular": 272},
                "scope": {"regular": "local"}, "fetched_epoch": time.time(), "source": "prueba",
                "center": [20.59, -100.39]}
        original = server.fuel_mod.fetch_summary
        server.fuel_mod.fetch_summary = lambda center: fake    # sin red en las pruebas
        try:
            s, cfg, _ = self.call("POST", "/api/settings/fuel/refresh", {})
        finally:
            server.fuel_mod.fetch_summary = original
        self.assertEqual((s, cfg["effective_price"], cfg["effective_source"], cfg["stale"]), (200, 23.94, "auto", False))
        s, cfg, _ = self.call("PUT", "/api/settings/fuel", {"fuel_type": "diesel"})
        self.assertEqual(cfg["effective_price"], 26.99)
        s, cfg, _ = self.call("PUT", "/api/settings/fuel", {"mode": "manual", "manual_price": 25.1})
        self.assertEqual((cfg["effective_price"], cfg["effective_source"]), (25.1, "manual"))
        self.assertEqual(self.call("POST", "/api/settings/fuel/refresh", {})[0], 409)   # manual: no consulta
        self.assertEqual(self.call("PUT", "/api/settings/fuel", {"manual_price": 0})[0], 400)
        self.assertEqual(self.call("PUT", "/api/settings/fuel", {"fuel_type": "gas"})[0], 400)
        self.call("PUT", "/api/settings/fuel", {"mode": "auto", "fuel_type": "regular"})

    def test_fuel_summary_local_and_national(self):
        from lattimex import fuel
        prices = fuel.parse_prices(b'<places>' + b''.join(
            f'<place place_id="{i}"><gas_price type="regular">{20 + i}</gas_price></place>'.encode()
            for i in range(8)) + b'<place place_id="99"><gas_price type="regular">0</gas_price></place></places>')
        places = fuel.parse_places(b'<places>' + b''.join(
            f'<place place_id="{i}"><location><x>-100.39</x><y>{20.59 + (0 if i < 6 else 5)}</y></location></place>'.encode()
            for i in range(8)) + b'</places>')
        local = fuel.summarize(prices, places, (20.59, -100.39))
        self.assertEqual((local["prices"]["regular"], local["stations"]["regular"], local["scope"]["regular"]),
                         (22.5, 6, "local"))             # el precio 0 se descarta como captura errónea
        self.assertEqual(fuel.summarize(prices, places, (30.0, -110.0))["scope"]["regular"], "nacional")
        with self.assertRaises(ValueError):
            fuel.parse_prices(b'<!DOCTYPE x [<!ENTITY a "b">]><places/>')

    def test_invalid_solve_is_rejected(self):
        s, body, _ = self.call("POST", "/api/engine/v1/solve", {"points": [{"lat": 1, "lng": 1}]})
        self.assertEqual(s, 400)


if __name__ == "__main__":
    unittest.main()
