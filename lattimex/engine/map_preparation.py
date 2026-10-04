# -*- coding: utf-8 -*-
"""Preparacion vial privada para el pipeline de LATTIMEX."""
from __future__ import annotations

import math
import pickle
from pathlib import Path

import networkx as nx
import numpy as np
from pyproj import Transformer
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import dijkstra

GRAPH_CRS = "EPSG:6372"
WGS84 = "EPSG:4326"
MAX_SNAP_DISTANCE_M = 2500.0
TO_GRAPH = Transformer.from_crs(WGS84, GRAPH_CRS, always_xy=True)
TO_WGS84 = Transformer.from_crs(GRAPH_CRS, WGS84, always_xy=True)


class MapPreparation:
    def __init__(self, graph_path: Path | None = None):
        self.graph_path = graph_path or Path(__file__).with_name("G_qro_urban.gpickle")
        with self.graph_path.open("rb") as handle:
            self.graph: nx.Graph = pickle.load(handle)
        if self.graph.is_directed() or self.graph.is_multigraph() or not nx.is_connected(self.graph):
            raise ValueError("mapa privado invalido")
        self.nodes = list(self.graph.nodes())
        self.coords = np.asarray(self.nodes, dtype=np.float64)
        self.node_to_index = {node: index for index, node in enumerate(self.nodes)}
        rows, cols, weights = [], [], []
        for a, b, data in self.graph.edges(data=True):
            ia, ib = self.node_to_index[a], self.node_to_index[b]
            weight = float(data.get("weight", 0.0))
            rows.extend((ia, ib)); cols.extend((ib, ia)); weights.extend((weight, weight))
        size = len(self.nodes)
        self.csr = csr_matrix((np.asarray(weights), (np.asarray(rows), np.asarray(cols))),
                              shape=(size, size))

    def _snap(self, point: dict, index: int):
        try:
            lat, lng = float(point["lat"]), float(point["lng"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"Punto {index + 1}: coordenadas invalidas") from exc
        if not (-90 <= lat <= 90 and -180 <= lng <= 180):
            raise ValueError(f"Punto {index + 1}: coordenadas fuera de rango")
        x, y = TO_GRAPH.transform(lng, lat)
        delta = self.coords - np.asarray([x, y])
        squared = np.einsum("ij,ij->i", delta, delta)
        node_index = int(np.argmin(squared))
        snap_distance = math.sqrt(float(squared[node_index]))
        if snap_distance > MAX_SNAP_DISTANCE_M:
            raise ValueError(f"Punto {index + 1}: fuera del area operativa")
        node = self.nodes[node_index]
        node_lng, node_lat = TO_WGS84.transform(node[0], node[1])
        return node, {"lat": node_lat, "lng": node_lng,
                      "snap_distance_m": round(snap_distance, 3)}

    def prepare(self, points: list[dict]) -> tuple[list[list[float]], list[dict]]:
        snapped = [self._snap(point, i) for i, point in enumerate(points)]
        nodes = [item[0] for item in snapped]
        public_points = [item[1] for item in snapped]
        unique = list(dict.fromkeys(nodes))
        target_indexes = np.asarray([self.node_to_index[node] for node in nodes])
        rows_by_node = {}
        for start in range(0, len(unique), 24):
            block = unique[start:start + 24]
            source_indexes = [self.node_to_index[node] for node in block]
            distances = dijkstra(self.csr, directed=False, indices=source_indexes)
            for offset, node in enumerate(block):
                row = distances[offset][target_indexes]
                if not np.isfinite(row).all():
                    raise ValueError("Hay puntos sin conexion vial")
                rows_by_node[node] = [round(float(value), 3) for value in row]
        return [rows_by_node[node] for node in nodes], public_points
