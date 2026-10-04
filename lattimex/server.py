# Copyright (c) 2026 LATTIMEX. Licencia MIT (ver LICENSE).
"""Servidor local de LATTIMEX.

Escucha solo en 127.0.0.1 y atiende al Planner que se abre en https://lattimex.com/planner.
El Planner es solo la interfaz: la base de datos, el mapa y el motor viven en esta
computadora y ningún dato de la operación se envía a LATTIMEX.

Seguridad (ver docs/SECURITY.md):
  * Host debe ser 127.0.0.1:<puerto> o localhost:<puerto> (evita DNS rebinding).
  * Origin debe estar en la lista permitida (por defecto https://lattimex.com).
  * Cada petición lleva un token de sesión que cambia en cada arranque.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import secrets
import socket
import sqlite3
import threading
import time
import traceback
import uuid
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from . import __version__, ENGINE_VERSION, fuel as fuel_mod, native, store as store_mod
from .network import RoadNetwork
from .store import LocalStore

DEFAULT_PORT = 8765
DEFAULT_ORIGINS = ("https://lattimex.com", "https://www.lattimex.com")
MAX_BODY_BYTES = 5 * 1024 * 1024
MAX_NODES = 1000
MAX_BUDGET_SEC = 300.0
RUNTIME_ID = secrets.token_urlsafe(18)
RUNTIME_TOKEN = secrets.token_urlsafe(32)


# ---------------------------------------------------------------------------
# Validación de la solicitud de optimización (mismo contrato que producción).
# ---------------------------------------------------------------------------
def finite_number(value, *, minimum=0.0, maximum=10_000_000.0, field="valor") -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field}: numero invalido")
    result = float(value)
    if not math.isfinite(result) or not minimum <= result <= maximum:
        raise ValueError(f"{field}: fuera de rango")
    return result


def validate_vehicle(vehicle: dict) -> dict:
    if not isinstance(vehicle, dict):
        raise ValueError("vehicle debe ser un objeto")
    cargo = vehicle.get("cargo_cm")
    if not isinstance(cargo, list) or len(cargo) != 3:
        raise ValueError("vehicle.cargo_cm necesita tres dimensiones")
    dims = [finite_number(v, minimum=0.1, maximum=100_000, field="vehicle.cargo_cm") for v in cargo]
    weight = finite_number(vehicle.get("max_weight_kg"), minimum=0.1, maximum=1_000_000,
                           field="vehicle.max_weight_kg")
    doors = vehicle.get("doors", ["rear"])
    if (not isinstance(doors, list) or not 1 <= len(doors) <= 3 or
            any(not isinstance(d, str) or d not in ("rear", "left", "right") for d in doors)):
        raise ValueError('vehicle.doors: lista no vacia con "rear", "left" y/o "right"')
    clean = {"cargo_cm": dims, "max_weight_kg": weight,
             "doors": [d for d in ("rear", "left", "right") if d in doors]}
    if "max_volume_cm3" in vehicle:
        clean["max_volume_cm3"] = finite_number(vehicle["max_volume_cm3"], minimum=0.001,
                                                maximum=math.prod(dims), field="vehicle.max_volume_cm3")
    return clean


def validate_solve(payload: dict) -> dict:
    points = payload.get("points")
    if not isinstance(points, list) or not 2 <= len(points) <= MAX_NODES:
        raise ValueError(f"points: lista de 2..{MAX_NODES} coordenadas")
    clean_points = [{"lat": finite_number((p or {}).get("lat"), minimum=-90, maximum=90, field="lat"),
                     "lng": finite_number((p or {}).get("lng"), minimum=-180, maximum=180, field="lng")}
                    for p in points]
    n = len(clean_points)
    fleet = payload.get("fleet")
    if not isinstance(fleet, list) or not 1 <= len(fleet) <= min(64, n - 1):
        raise ValueError("fleet: lista de 1..64 unidades, sin exceder destinos")
    clean_fleet = [validate_vehicle(v) for v in fleet]
    packages = payload.get("packages")
    if not isinstance(packages, list) or not 1 <= len(packages) <= 20_000:
        raise ValueError("packages: lista de 1..20000 elementos")
    clean_packages = []
    for index, pk in enumerate(packages):
        if not isinstance(pk, dict) or isinstance(pk.get("node"), bool) or not isinstance(pk.get("node"), int) \
                or not 1 <= pk["node"] < n:
            raise ValueError("cada paquete necesita node en 1..n-1")
        dims = pk.get("dims_cm")
        if not isinstance(dims, list) or len(dims) != 3:
            raise ValueError("cada paquete necesita dims_cm=[l,w,h] > 0")
        clean_packages.append({
            "id": str(pk.get("id", f"P{index + 1}"))[:120], "node": pk["node"],
            "dims_cm": [finite_number(x, minimum=0.1, maximum=100_000, field="dims_cm") for x in dims],
            "weight_kg": finite_number(pk.get("weight_kg", 0.1), minimum=0, maximum=1_000_000, field="weight_kg"),
            "fragile": bool(pk.get("fragile", False)), "stackable": bool(pk.get("stackable", True)),
            "keep_upright": bool(pk.get("keep_upright", False)),
        })
    ids = [pk["id"] for pk in clean_packages]
    if any(not gid for gid in ids) or len(ids) != len(set(ids)):
        raise ValueError("packages.id debe ser unico y no vacio")
    if {pk["node"] for pk in clean_packages} != set(range(1, n)):
        raise ValueError("Cada destino necesita al menos un paquete")
    constraints = payload.get("constraints") or {}
    perfil = str(payload.get("perfil", "fast")).lower()
    if perfil not in ("fast", "thorough"):
        raise ValueError("perfil debe ser 'fast' o 'thorough'")
    return {
        "points": clean_points, "fleet": clean_fleet, "fleet_count": len(clean_fleet),
        "packages": clean_packages,
        "constraints": {k: bool(constraints.get(k, False)) for k in ("support", "fragility", "lifo")},
        "budget_sec": finite_number(payload.get("budget_sec", 15), minimum=1, maximum=MAX_BUDGET_SEC,
                                    field="budget_sec"),
        "perfil": perfil,
    }


# ---------------------------------------------------------------------------
# Motor: un trabajo a la vez, en un hilo, igual que el worker de producción.
# ---------------------------------------------------------------------------
class Engine:
    def __init__(self, graph_path: Path):
        # El portafolio de ruteo lanza 4 corridas; el servidor de producción las repartía en 2 hilos
        # (contenedor de 2 CPU). En la computadora del usuario se usan hasta 4: mismo resultado
        # determinista, más búsqueda por segundo. LATTIMEX_THREADS sigue teniendo prioridad.
        os.environ.setdefault("LATTIMEX_THREADS", str(max(1, min(4, os.cpu_count() or 2))))
        native.configure()
        import engine_runtime                      # noqa: PLC0415  (módulos del motor sin cambios)
        from map_preparation import MapPreparation  # noqa: PLC0415
        self.runtime = engine_runtime
        self.maps = MapPreparation(graph_path)
        self.jobs: dict[str, dict] = {}
        self.lock = threading.Lock()
        self.busy = threading.Semaphore(1)
        # Matrices de distancias ya calculadas (Dijkstra sobre todo el mapa: ~10 s con 300 puntos).
        self._prep: dict[tuple, tuple] = {}
        self._prep_lock = threading.Lock()
        self._prep_running: dict[tuple, threading.Event] = {}

    @staticmethod
    def _points_key(points: list) -> tuple:
        return tuple((round(float(p["lat"]), 7), round(float(p["lng"]), 7)) for p in points)

    def prepare(self, points: list) -> tuple:
        """Matriz y puntos ubicados; reutiliza la última si los puntos no cambiaron."""
        key = self._points_key(points)
        while True:
            with self._prep_lock:
                if key in self._prep:
                    return self._prep[key]
                pending = self._prep_running.get(key)
                if pending is None:
                    pending = self._prep_running[key] = threading.Event()
                    owner = True
                else:
                    owner = False
            if not owner:
                pending.wait()
                continue
            try:
                value = self.maps.prepare(points)
                with self._prep_lock:
                    if len(self._prep) >= 4:
                        self._prep.pop(next(iter(self._prep)))
                    self._prep[key] = value
                return value
            finally:
                with self._prep_lock:
                    self._prep_running.pop(key, None)
                pending.set()

    def warm(self, points: list) -> None:
        """Calcula la matriz en segundo plano (al ubicar las guías), antes de pulsar Optimizar."""
        def run():
            try:
                self.prepare(points)
            except Exception:                        # noqa: BLE001 (el error se verá al resolver)
                pass
        threading.Thread(target=run, daemon=True).start()

    def submit(self, payload: dict) -> dict:
        job_id = str(uuid.uuid4())
        with self.lock:
            self.jobs[job_id] = {"status": "queued", "phase": "map", "progress": 0, "created": time.time()}
            for old in [k for k, v in self.jobs.items() if time.time() - v["created"] > 6 * 3600]:
                self.jobs.pop(old, None)
        threading.Thread(target=self._run, args=(job_id, payload), daemon=True).start()
        return {"id": job_id, "status": "queued", "budget_sec": payload["budget_sec"], "plan": "local"}

    def _set(self, job_id: str, **values) -> None:
        with self.lock:
            self.jobs[job_id].update(values)

    def _run(self, job_id: str, payload: dict) -> None:
        with self.busy:
            started = time.time()
            self._set(job_id, status="running", phase="map", progress=10, started=started)
            try:
                matrix, snapped = self.prepare(payload.pop("points"))
                payload["matrix_m"] = matrix
                self._set(job_id, phase="solver", progress=5)
                result = self.runtime.solve(payload)
                result["map_points"] = snapped
                result["depot_distances_m"] = [round(float(v), 1) for v in matrix[0]]
                for route in result.get("routes", []):
                    seq = [0, *route.get("sequence", []), 0]
                    route["legs_m"] = [round(float(matrix[a][b]), 1) for a, b in zip(seq, seq[1:])]
                result["engine"] = {"name": ENGINE_VERSION, "core": self.runtime.CORE_SHA}
                self._set(job_id, status="done", phase="solver", progress=100, result=result,
                          finished=time.time())
            except Exception as exc:                # noqa: BLE001
                traceback.print_exc()
                self._set(job_id, status="error", error=f"El motor no pudo completar el trabajo: {exc}",
                          finished=time.time())

    def job(self, job_id: str) -> dict:
        with self.lock:
            row = dict(self.jobs[job_id])
        phase, status = row["phase"], row["status"]
        map_p = 100 if phase == "solver" or status == "done" else int(row["progress"])
        sol_p = 100 if status == "done" else (int(row["progress"]) if phase == "solver" else 0)
        out = {"id": job_id, "status": status, "phase": phase, "stages": {
            "map": {"progress": map_p, "status": "error" if status == "error" and phase == "map"
                    else ("done" if map_p == 100 else "running")},
            "solver": {"progress": sol_p, "status": "error" if status == "error" and phase == "solver"
                       else ("done" if sol_p == 100 else ("running" if phase == "solver" else "pending"))}}}
        if status == "done":
            out["result"] = row["result"]
        if status == "error":
            out["error"] = row.get("error")
            out["stages"][phase]["error"] = row.get("error")
        if row.get("finished") and row.get("started"):
            out["runtime_sec"] = round(row["finished"] - row["started"], 2)
        return out


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------
class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = f"lattimex-local/{__version__}"
    network: RoadNetwork
    store: LocalStore
    engine: Engine
    origins: tuple[str, ...] = DEFAULT_ORIGINS
    roads_path: Path | None = None
    map_meta: dict = {}

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"[local] {self.command} {urlparse(self.path).path} {args[1] if len(args) > 1 else ''}")

    # --- origen y autorización -------------------------------------------
    def origin(self) -> str:
        return self.headers.get("Origin", "").rstrip("/")

    def valid_host(self) -> bool:
        port = self.server.server_address[1]
        return self.headers.get("Host", "").lower() in {f"127.0.0.1:{port}", f"localhost:{port}"}

    def allowed_origin(self) -> bool:
        return self.origin() in self.origins

    def cors(self) -> None:
        if self.allowed_origin():
            self.send_header("Access-Control-Allow-Origin", self.origin())
            self.send_header("Vary", "Origin")

    def authorize(self, bootstrap: bool = False) -> bool:
        if not self.valid_host() or not self.allowed_origin():
            self.discard_body()
            self.send_json({"error": "origen no autorizado"}, HTTPStatus.FORBIDDEN)
            return False
        if bootstrap:
            return True
        supplied = self.headers.get("X-LATTIMEX-Runtime-Token", "")
        if not supplied or not secrets.compare_digest(supplied, RUNTIME_TOKEN):
            self.discard_body()
            self.send_json({"error": "sesion local invalida"}, HTTPStatus.UNAUTHORIZED)
            return False
        return True

    # --- utilidades ---------------------------------------------------------
    def discard_body(self) -> None:
        try:
            size = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            size = 0
        if 0 < size <= MAX_BODY_BYTES:
            self.rfile.read(size)
        elif size > MAX_BODY_BYTES:
            self.close_connection = True

    def send_json(self, payload: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.cors()
        self.end_headers()
        self.wfile.write(body)

    def read_json(self) -> dict:
        size = int(self.headers.get("Content-Length", "0") or 0)
        if size <= 0 or size > MAX_BODY_BYTES:
            raise ValueError("Cuerpo JSON vacio o demasiado grande")
        payload = json.loads(self.rfile.read(size).decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("El cuerpo debe ser un objeto JSON")
        return payload

    # --- métodos --------------------------------------------------------------
    def do_OPTIONS(self) -> None:
        if not self.valid_host() or not self.allowed_origin():
            self.send_response(HTTPStatus.FORBIDDEN)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self.send_response(HTTPStatus.NO_CONTENT)
        self.cors()
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-LATTIMEX-Runtime-Token")
        self.send_header("Access-Control-Max-Age", "600")
        if self.headers.get("Access-Control-Request-Private-Network") == "true":
            self.send_header("Access-Control-Allow-Private-Network", "true")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path in ("/", "/health"):
            # Página mínima para quien abra el puerto en el navegador; no expone datos.
            return self.send_json({"lattimex": __version__, "engine": ENGINE_VERSION, "status": "ok",
                                   "planner": "https://lattimex.com/planner"})
        try:
            if path == "/api/runtime":
                if self.authorize(bootstrap=True):
                    self.send_json({"runtime_id": RUNTIME_ID, "runtime_token": RUNTIME_TOKEN,
                                    "version": __version__, "engine": ENGINE_VERSION,
                                    "map": self.map_meta})
                return
            if not self.authorize():
                return
            if path == "/api/map/roads":
                if not self.roads_path or not self.roads_path.exists():
                    raise KeyError("Este mapa no tiene capa de calles; reconstruyalo con `lattimex map`")
                body = self.roads_path.read_bytes()
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.cors()
                self.end_headers()
                self.wfile.write(body)
                return
            if path.startswith("/api/engine/v1/jobs/"):
                return self.send_json(self.engine.job(path.rsplit("/", 1)[1]))
            if path == "/api/engine/v1/me":
                return self.send_json({"plan": "local", "limites": {"budget_sec": 60, "max_nodes": MAX_NODES},
                                       "funciones": ["routing", "packing3d"]})
            if path == "/api/sample-instances":
                return self.send_json({"instances": []})
            if path == "/api/network/status":
                return self.send_json(self.network.metadata())
            if path == "/api/catalog/vehicles":
                return self.send_json({"vehicles": self.store.list_vehicles()})
            if path == "/api/catalog/operators":
                return self.send_json({"operators": self.store.list_operators()})
            if path == "/api/instances":
                return self.send_json({"instances": self.store.list_instances()})
            if path.startswith("/api/instances/"):
                return self.send_json(self.store.get_instance(int(path.rsplit("/", 1)[1])))
            if path == "/api/planning-state":
                return self.send_json(self.store.get_planning_state())
            if path == "/api/results-state":
                return self.send_json(self.store.get_results_state())
            if path == "/api/capture-draft":
                return self.send_json(self.store.get_capture_draft())
            if path == "/api/settings/fuel":
                return self.send_json(self.store.get_fuel())
            if path == "/api/planning-runs":
                return self.send_json({"runs": self.store.list_runs()})
            if path.startswith("/api/planning-runs/"):
                return self.send_json(self.store.get_run(int(path.rsplit("/", 1)[1])))
            self.send_json({"error": "Ruta API inexistente"}, HTTPStatus.NOT_FOUND)
        except (KeyError, ValueError) as exc:
            self.send_json({"error": str(exc).strip("'")}, HTTPStatus.NOT_FOUND)

    def _write(self, method: str) -> None:
        path = urlparse(self.path).path
        try:
            if not self.authorize():
                return
            payload = self.read_json() if method != "DELETE" else {}
            if method == "POST":
                if path == "/api/engine/v1/solve":
                    return self.send_json(self.engine.submit(validate_solve(payload)), HTTPStatus.ACCEPTED)
                if path == "/api/network/snap":
                    points = payload.get("points")
                    if not isinstance(points, list):
                        raise ValueError("points debe ser una lista")
                    snapped = self.network.snap_points(points)[1]
                    if 2 <= len(points) <= MAX_NODES:
                        self.engine.warm(points)      # la matriz queda lista al pulsar Optimizar
                    return self.send_json({"snapped_points": snapped})
                if path == "/api/network/paths":
                    points, routes = payload.get("points"), payload.get("routes")
                    if not isinstance(points, list) or not isinstance(routes, list):
                        raise ValueError("points y routes deben ser listas")
                    return self.send_json(self.network.route_geometries(points, routes))
                if path == "/api/catalog/vehicles":
                    return self.send_json(self.store.save_vehicle(payload), HTTPStatus.CREATED)
                if path == "/api/catalog/operators":
                    return self.send_json(self.store.save_operator(payload), HTTPStatus.CREATED)
                if path == "/api/instances":
                    return self.send_json(self.store.create_instance(payload), HTTPStatus.CREATED)
                if path == "/api/planning-runs":
                    return self.send_json(self.store.save_run(payload), HTTPStatus.CREATED)
                if path == "/api/settings/fuel/refresh":
                    return self.refresh_fuel(payload)
            elif method == "PUT":
                ident = path.rsplit("/", 1)[1]
                if path.startswith("/api/catalog/vehicles/"):
                    return self.send_json(self.store.save_vehicle(payload, int(ident)))
                if path.startswith("/api/catalog/operators/"):
                    return self.send_json(self.store.save_operator(payload, int(ident)))
                if path.startswith("/api/instances/"):
                    return self.send_json(self.store.update_instance(int(ident), payload))
                if path == "/api/planning-state":
                    return self.send_json(self.store.set_planning_state(payload))
                if path == "/api/results-state":
                    return self.send_json(self.store.set_results_state(payload))
                if path == "/api/capture-draft":
                    return self.send_json(self.store.set_capture_draft(payload))
                if path == "/api/settings/fuel":
                    return self.send_json(self.store.set_fuel(payload))
            elif method == "DELETE":
                if path == "/api/capture-draft":
                    return self.send_json(self.store.set_capture_draft({"draft": None}))
                if path == "/api/planning-runs":
                    return self.send_json({"ok": True, "deleted": self.store.delete_all_runs()})
                parts = path.strip("/").split("/")
                if len(parts) == 5 and parts[:2] == ["api", "instances"] and parts[3] == "guides":
                    self.store.delete_guide(int(parts[2]), int(parts[4])); return self.send_json({"ok": True})
                ident = int(path.rsplit("/", 1)[1])
                if path.startswith("/api/planning-runs/"):
                    self.store.delete_run(ident); return self.send_json({"ok": True})
                if path.startswith("/api/catalog/vehicles/"):
                    self.store.delete_vehicle(ident); return self.send_json({"ok": True})
                if path.startswith("/api/catalog/operators/"):
                    self.store.delete_operator(ident); return self.send_json({"ok": True})
                if path.startswith("/api/instances/"):
                    self.store.delete_instance(ident); return self.send_json({"ok": True})
            self.send_json({"error": "Ruta API inexistente"}, HTTPStatus.NOT_FOUND)
        except KeyError as exc:
            self.send_json({"error": str(exc).strip("'")}, HTTPStatus.NOT_FOUND)
        except sqlite3.IntegrityError as exc:
            self.send_json({"error": f"Datos incompatibles: {exc}"}, HTTPStatus.BAD_REQUEST)
        except (ValueError, json.JSONDecodeError) as exc:
            self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        except Exception as exc:                    # noqa: BLE001
            traceback.print_exc()
            self.send_json({"error": f"Error interno: {exc}"}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def refresh_fuel(self, payload: dict) -> None:
        """Consulta los precios públicos de la CRE (solo en modo automático) y los guarda."""
        if self.store.get_fuel()["mode"] != "auto":
            return self.send_json({"error": "El combustible está en modo manual; no se consulta la CRE."},
                                  HTTPStatus.CONFLICT)
        lat, lng = payload.get("lat"), payload.get("lng")
        center = (float(lat), float(lng)) if isinstance(lat, (int, float)) and isinstance(lng, (int, float)) \
            else self.store.fuel_center()
        try:
            summary = fuel_mod.fetch_summary(center)
        except Exception as exc:                    # noqa: BLE001 - red, formato o servicio caído
            return self.send_json({"error": f"No se pudo consultar la CRE: {exc}"}, HTTPStatus.BAD_GATEWAY)
        self.send_json(self.store.set_fuel({"auto": summary}))

    def do_POST(self) -> None:
        self._write("POST")

    def do_PUT(self) -> None:
        self._write("PUT")

    def do_DELETE(self) -> None:
        self._write("DELETE")


def load_map(maps_dir: Path, name: str | None) -> tuple[Path, Path, dict]:
    """Localiza el mapa y comprueba su huella antes de deserializarlo."""
    metas = sorted(maps_dir.glob("*.json"))
    metas = [m for m in metas if not m.name.endswith(".roads.json")]
    if name:
        metas = [m for m in metas if m.stem == name]
    if not metas:
        raise FileNotFoundError(
            f"No hay mapas en {maps_dir}. Construya uno con:\n"
            "  python -m lattimex map --osm su_ciudad.osm --name su_ciudad")
    meta = json.loads(metas[0].read_text(encoding="utf-8"))
    graph = maps_dir / f"{meta['name']}.gpickle"
    digest = hashlib.sha256(graph.read_bytes()).hexdigest()
    if not secrets.compare_digest(digest, meta["graph_sha256"]):
        raise RuntimeError(f"La huella de {graph.name} no coincide con {metas[0].name}; reconstruya el mapa.")
    return graph, maps_dir / f"{meta['name']}.roads.json", meta


class ExclusiveHTTPServer(ThreadingHTTPServer):
    """Un solo servidor por puerto. En Windows, SO_REUSEADDR permite que dos procesos escuchen en el
    mismo puerto sin error y el navegador puede terminar hablando con el equivocado."""

    allow_reuse_address = os.name != "nt"

    def server_bind(self) -> None:
        if os.name == "nt":
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def serve(data_dir: Path, port: int = DEFAULT_PORT, map_name: str | None = None,
          origins: tuple[str, ...] = DEFAULT_ORIGINS) -> ThreadingHTTPServer:
    data_dir.mkdir(parents=True, exist_ok=True)
    graph, roads, meta = load_map(data_dir / "maps", map_name)
    print(f"Datos: {data_dir.resolve()}  (otra carpeta: --data CARPETA)")
    print(f"Mapa: {meta['name']} ({meta['nodes']:,} nodos) · {meta['attribution']}")
    store_mod.RESULTS_DIR = data_dir / "resultados"
    Handler.store = LocalStore(data_dir / "lattimex.sqlite3")
    Handler.network = RoadNetwork(graph)
    Handler.engine = Engine(graph)
    Handler.origins = tuple(o.rstrip("/") for o in origins)
    Handler.roads_path, Handler.map_meta = roads, {k: meta[k] for k in ("name", "nodes", "attribution")}
    server = ExclusiveHTTPServer(("127.0.0.1", port), Handler)
    print(f"LATTIMEX local {__version__} · motor {ENGINE_VERSION} · core {Handler.engine.runtime.CORE_SHA}")
    print(f"Escuchando en http://127.0.0.1:{server.server_address[1]}  ·  origenes: {', '.join(Handler.origins)}")
    print("Abra https://lattimex.com/planner en Chrome, Edge o Firefox.")
    return server
