# Copyright (c) 2026 LATTIMEX. Licencia MIT (ver LICENSE).
"""Red vial local: ubica entregas sobre las calles, calcula la matriz de distancias
por caminos mínimos y la geometría de cada ruta. Sin servicios externos."""
from __future__ import annotations

import heapq
import math
import pickle
import threading
from functools import lru_cache
from pathlib import Path
from typing import Any

import networkx as nx
import numpy as np
from pyproj import Transformer

WGS84 = "EPSG:4326"
GRAPH_CRS = "EPSG:6372"
TO_GRAPH = Transformer.from_crs(WGS84, GRAPH_CRS, always_xy=True)
TO_WGS84 = Transformer.from_crs(GRAPH_CRS, WGS84, always_xy=True)
MAX_TERMINALS = 1000
MAX_SNAP_DISTANCE_M = 2500.0



class RoadNetwork:
    def __init__(self, graph_path: Path):
        self.graph_path = graph_path
        with graph_path.open("rb") as handle:
            self.graph: nx.Graph = pickle.load(handle)
        if self.graph.is_directed() or self.graph.is_multigraph():
            raise ValueError("El servidor espera el grafo simple no dirigido G_qro_urban")
        if not nx.is_connected(self.graph):
            raise ValueError("El grafo vial debe ser conexo")
        self.nodes = list(self.graph.nodes())
        self.coords = np.asarray([[float(node[0]), float(node[1])] for node in self.nodes], dtype=np.float64)
        self.node_to_index = {node: index for index, node in enumerate(self.nodes)}
        self._path_lock = threading.Lock()
        self._csr = None                 # matriz dispersa (via rapida, si hay SciPy)
        self._csr_intentado = False
        self._cierre_cache: dict = {}    # clausuras ya calculadas en esta sesion

    def _matriz_dispersa(self):
        """Representacion CSR del grafo para Dijkstra vectorizado (SciPy).

        Si SciPy no esta disponible se devuelve None y se usa la ruta clasica.
        """
        if self._csr_intentado:
            return self._csr
        self._csr_intentado = True
        try:
            from scipy.sparse import csr_matrix           # noqa: PLC0415
        except Exception:                                  # noqa: BLE001
            self._csr = None
            return None
        indice = self.node_to_index
        filas, columnas, pesos = [], [], []
        for a, b, datos in self.graph.edges(data=True):
            ia, ib = indice[a], indice[b]
            w = float(datos.get("weight", 0.0))
            filas.append(ia); columnas.append(ib); pesos.append(w)
            filas.append(ib); columnas.append(ia); pesos.append(w)
        n = len(self.nodes)
        self._csr = csr_matrix((np.asarray(pesos, dtype=np.float64),
                                (np.asarray(filas), np.asarray(columnas))), shape=(n, n))
        return self._csr

    def metadata(self) -> dict[str, Any]:
        return {
            "ready": True,
            "graph": self.graph_path.name,
            "graph_path": str(self.graph_path),
            "crs": GRAPH_CRS,
            "nodes": self.graph.number_of_nodes(),
            "edges": self.graph.number_of_edges(),
            "metric": "shortest_path_weight_m",
            "max_terminals": MAX_TERMINALS,
        }

    def snap(self, lat: float, lng: float) -> tuple[tuple[float, float], float]:
        x, y = TO_GRAPH.transform(lng, lat)
        delta = self.coords - np.asarray([x, y])
        squared = np.einsum("ij,ij->i", delta, delta)
        index = int(np.argmin(squared))
        return self.nodes[index], float(math.sqrt(float(squared[index])))

    def snap_points(self, points: list[dict[str, Any]]) -> tuple[list[tuple[float, float]], list[dict[str, float]]]:
        snapped_nodes: list[tuple[float, float]] = []
        snapped_points: list[dict[str, float]] = []
        for index, point in enumerate(points):
            try:
                lat, lng = float(point["lat"]), float(point["lng"])
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(f"Punto {index + 1}: latitud/longitud invalidas") from exc
            if not (-90 <= lat <= 90 and -180 <= lng <= 180):
                raise ValueError(f"Punto {index + 1}: coordenadas fuera de rango")
            node, snap_distance = self.snap(lat, lng)
            if snap_distance > MAX_SNAP_DISTANCE_M:
                raise ValueError(
                    f"Punto {index + 1}: esta a {snap_distance:.0f} m de la red urbana; "
                    f"el maximo permitido es {MAX_SNAP_DISTANCE_M:.0f} m"
                )
            node_lng, node_lat = TO_WGS84.transform(node[0], node[1])
            snapped_nodes.append(node)
            snapped_points.append({
                "lat": node_lat,
                "lng": node_lng,
                "snap_distance_m": round(snap_distance, 3),
            })
        return snapped_nodes, snapped_points

    def distances_to_targets(
        self, source: tuple[float, float], targets: set[tuple[float, float]]
    ) -> dict[tuple[float, float], float]:
        remaining = set(targets)
        remaining.discard(source)
        found = {source: 0.0}
        best = {source: 0.0}
        queue: list[tuple[float, tuple[float, float]]] = [(0.0, source)]
        while queue and remaining:
            distance, node = heapq.heappop(queue)
            if distance != best.get(node):
                continue
            if node in remaining:
                found[node] = distance
                remaining.remove(node)
                if not remaining:
                    break
            for neighbor, edge in self.graph[node].items():
                candidate = distance + float(edge["weight"])
                if candidate < best.get(neighbor, math.inf):
                    best[neighbor] = candidate
                    heapq.heappush(queue, (candidate, neighbor))
        if remaining:
            raise ValueError(f"No hay camino para {len(remaining)} terminal(es)")
        return found

    def _cierre_vectorizado(self, snapped_nodes) -> list[list[float]] | None:
        """Todas las distancias en pocas llamadas a SciPy en vez de 300 Dijkstra."""
        csr = self._matriz_dispersa()
        if csr is None:
            return None
        try:
            from scipy.sparse.csgraph import dijkstra      # noqa: PLC0415
        except Exception:                                  # noqa: BLE001
            return None
        indice = self.node_to_index
        unicos = list(dict.fromkeys(snapped_nodes))
        idx_unicos = [indice[nodo] for nodo in unicos]
        idx_destinos = np.asarray([indice[nodo] for nodo in snapped_nodes])
        filas: dict = {}
        bloque = 24                       # limita la memoria: 24 x nodos x 8 bytes
        for inicio in range(0, len(idx_unicos), bloque):
            fuentes = idx_unicos[inicio:inicio + bloque]
            distancias = dijkstra(csr, directed=False, indices=fuentes)
            for k, fuente in enumerate(fuentes):
                fila = distancias[k][idx_destinos]
                if not np.isfinite(fila).all():
                    return None           # algo inalcanzable: usar la ruta clasica
                filas[unicos[inicio + k]] = [round(float(v), 3) for v in fila]
        return [filas[nodo] for nodo in snapped_nodes]

    def metric_closure(self, points: list[dict[str, Any]]) -> dict[str, Any]:
        if not 2 <= len(points) <= MAX_TERMINALS:
            raise ValueError(f"Se requieren entre 2 y {MAX_TERMINALS} terminales")
        snapped_nodes, snapped_points = self.snap_points(points)

        clave = hash(tuple(snapped_nodes))
        if clave in self._cierre_cache:               # misma instancia: instantaneo
            matrix = self._cierre_cache[clave]
        else:
            matrix = self._cierre_vectorizado(snapped_nodes)
            if matrix is None:                        # sin SciPy: Dijkstra clasico
                unique_targets = set(snapped_nodes)
                rows_by_source: dict[tuple[float, float], list[float]] = {}
                for source in dict.fromkeys(snapped_nodes):
                    distances = self.distances_to_targets(source, unique_targets)
                    rows_by_source[source] = [
                        round(distances.get(target, 0.0), 3) for target in snapped_nodes
                    ]
                matrix = [rows_by_source[source] for source in snapped_nodes]
            if len(self._cierre_cache) > 6:
                self._cierre_cache.clear()
            self._cierre_cache[clave] = matrix
        return {
            "matrix": matrix,
            "snapped_points": snapped_points,
            "graph": self.graph_path.name,
            "crs": GRAPH_CRS,
            "metric": "network_shortest_path_m",
        }

    @lru_cache(maxsize=4096)
    def shortest_path(self, source_index: int, target_index: int) -> tuple[tuple[float, float], ...]:
        source, target = self.nodes[source_index], self.nodes[target_index]
        with self._path_lock:
            path = nx.shortest_path(self.graph, source=source, target=target, weight="weight")
        return tuple(path)

    def route_geometries(self, snapped_points: list[dict[str, Any]], routes: list[list[int]]) -> dict[str, Any]:
        nodes, _ = self.snap_points(snapped_points)
        node_indexes = [self.node_to_index[node] for node in nodes]
        geometries: list[list[list[float]]] = []
        for route_no, route in enumerate(routes, start=1):
            if len(route) < 2:
                raise ValueError(f"Ruta {route_no}: debe contener al menos dos terminales")
            if any(not isinstance(value, int) or value < 0 or value >= len(nodes) for value in route):
                raise ValueError(f"Ruta {route_no}: indice de terminal invalido")
            walk: list[tuple[float, float]] = []
            for offset, (a, b) in enumerate(zip(route, route[1:])):
                segment = self.shortest_path(node_indexes[a], node_indexes[b])
                walk.extend(segment if offset == 0 else segment[1:])
            geometry: list[list[float]] = []
            for x, y in walk:
                lng, lat = TO_WGS84.transform(x, y)
                geometry.append([lat, lng])
            geometries.append(geometry)
        return {"geometries": geometries}


