# Copyright (c) 2026 LATTIMEX. Licencia MIT (ver LICENSE).
"""Construcción de mapas propios a partir de datos de OpenStreetMap.

LATTIMEX no usa servidores de teselas ni servicios de ruteo externos. Cada
instalación construye, una sola vez, dos archivos a partir de un extracto OSM de
su ciudad (formato .osm XML, p. ej. exportado de Overpass o JOSM; o .osm.pbf si
está instalado `osmium`):

  data/maps/<nombre>.gpickle     grafo vial no dirigido para el motor
                                 (nodos en EPSG:6372, peso = metros)
  data/maps/<nombre>.roads.json  calles simplificadas para dibujar el mapa en el Planner

Los datos derivados de OSM están bajo la Open Database License (ODbL 1.0):
© colaboradores de OpenStreetMap. Ver docs/MAPS.md.
"""
from __future__ import annotations

import hashlib
import json
import math
import pickle
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

import networkx as nx
from pyproj import Transformer

GRAPH_CRS = "EPSG:6372"   # México ITRF2008 / LCC: el mismo que usa el motor en producción
ATTRIBUTION = "© colaboradores de OpenStreetMap · ODbL 1.0"

# Vías transitables por vehículos de reparto y su clase visual en el Planner.
HIGHWAY_CLASS = {
    "motorway": 0, "trunk": 0, "motorway_link": 0, "trunk_link": 0,
    "primary": 1, "primary_link": 1, "secondary": 1, "secondary_link": 1,
    "tertiary": 2, "tertiary_link": 2,
    "unclassified": 3, "residential": 3, "living_street": 3, "service": 3, "road": 3,
}
BLOCKED_ACCESS = {"no", "private"}
# Pasillos de estacionamiento, cocheras y autoservicios: no son vías de reparto.
BLOCKED_SERVICE = {"parking_aisle", "driveway", "drive-through", "emergency_access"}


def _read_osm_xml(path: Path):
    nodes, ways = {}, []
    for _, elem in ET.iterparse(str(path), events=("end",)):
        if elem.tag == "node":
            nodes[int(elem.get("id"))] = (float(elem.get("lat")), float(elem.get("lon")))
            elem.clear()
        elif elem.tag == "way":
            tags = {t.get("k"): t.get("v") for t in elem.findall("tag")}
            hw = tags.get("highway")
            if (hw in HIGHWAY_CLASS and tags.get("area") != "yes"
                    and tags.get("service") not in BLOCKED_SERVICE
                    and tags.get("access") not in BLOCKED_ACCESS
                    and tags.get("motor_vehicle") not in BLOCKED_ACCESS):
                ways.append((HIGHWAY_CLASS[hw], [int(nd.get("ref")) for nd in elem.findall("nd")]))
            elem.clear()
    return nodes, ways


def _read_osm_pbf(path: Path):
    try:
        import osmium  # noqa: PLC0415
    except ImportError as exc:
        raise RuntimeError("Para leer .pbf instale `pip install osmium` o use un extracto .osm XML") from exc

    class Handler(osmium.SimpleHandler):
        def __init__(self):
            super().__init__()
            self.ways = []

        def way(self, w):
            hw = w.tags.get("highway")
            if (hw in HIGHWAY_CLASS and w.tags.get("area") != "yes"
                    and w.tags.get("service") not in BLOCKED_SERVICE
                    and w.tags.get("access") not in BLOCKED_ACCESS
                    and w.tags.get("motor_vehicle") not in BLOCKED_ACCESS):
                self.ways.append((HIGHWAY_CLASS[hw], [(n.ref, n.lat, n.lon) for n in w.nodes]))

    h = Handler()
    h.apply_file(str(path), locations=True)
    nodes, ways = {}, []
    for cls, refs in h.ways:
        for ref, lat, lon in refs:
            nodes[ref] = (lat, lon)
        ways.append((cls, [r for r, _, _ in refs]))
    return nodes, ways


def build_map(source: Path, name: str, out_dir: Path) -> dict:
    """Construye el grafo del motor y la capa de calles del Planner."""
    source = Path(source)
    nodes, ways = (_read_osm_pbf if source.name.endswith(".pbf") else _read_osm_xml)(source)
    if not ways:
        raise ValueError("El extracto no contiene calles transitables")
    to_graph = Transformer.from_crs("EPSG:4326", GRAPH_CRS, always_xy=True)
    projected = {}

    def xy(ref):
        if ref not in projected:
            lat, lon = nodes[ref]
            x, y = to_graph.transform(lon, lat)
            projected[ref] = (round(x, 2), round(y, 2))
        return projected[ref]

    graph = nx.Graph()
    for _, refs in ways:
        refs = [r for r in refs if r in nodes]
        for a, b in zip(refs, refs[1:]):
            pa, pb = xy(a), xy(b)
            if pa == pb:
                continue
            w = math.dist(pa, pb)
            if not graph.has_edge(pa, pb) or graph[pa][pb]["weight"] > w:
                graph.add_edge(pa, pb, weight=w)
    largest = max(nx.connected_components(graph), key=len)
    graph = graph.subgraph(largest).copy()
    keep = set(largest)

    # Capa visual: cada vía como polilínea (lat, lng con 5 decimales ≈ 1 m),
    # codificada en diferencias enteras para reducir el tamaño del archivo.
    layers = [[] for _ in range(4)]
    for cls, refs in ways:
        pts = [nodes[r] for r in refs if r in nodes and xy(r) in keep]
        if len(pts) < 2:
            continue
        flat, px, py = [], 0, 0
        for lat, lon in pts:
            ix, iy = round(lat * 1e5), round(lon * 1e5)
            flat += [ix - px, iy - py]
            px, py = ix, iy
        layers[cls].append(flat)
    lats = [nodes[r][0] for r in nodes]
    lons = [nodes[r][1] for r in nodes]
    out_dir.mkdir(parents=True, exist_ok=True)
    gpath, rpath = out_dir / f"{name}.gpickle", out_dir / f"{name}.roads.json"
    with gpath.open("wb") as fh:
        pickle.dump(graph, fh, protocol=pickle.HIGHEST_PROTOCOL)
    roads = {"format": "lattimex.roads.v1", "attribution": ATTRIBUTION, "precision": 1e5,
             "bbox": [min(lats), min(lons), max(lats), max(lons)],
             "classes": ["autopista", "principal", "secundaria", "local"], "layers": layers}
    rpath.write_text(json.dumps(roads, separators=(",", ":")), encoding="utf-8")
    meta = {"name": name, "source": source.name, "built": time.strftime("%Y-%m-%d %H:%M:%S"),
            "crs": GRAPH_CRS, "nodes": graph.number_of_nodes(), "edges": graph.number_of_edges(),
            "roads_bytes": rpath.stat().st_size, "attribution": ATTRIBUTION,
            "graph_sha256": hashlib.sha256(gpath.read_bytes()).hexdigest()}
    (out_dir / f"{name}.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    return meta


def download_osm(bbox: tuple[float, float, float, float], target: Path,
                 endpoint: str = "https://overpass-api.de/api/interpreter") -> Path:
    """Descarga UNA vez las vías de un rectángulo (sur, oeste, norte, este) desde Overpass.

    Respete la política de uso de Overpass: una descarga por ciudad, no en cada arranque.
    Para regiones grandes use un extracto .pbf de Geofabrik.
    """
    s, w, n, e = bbox
    if (n - s) * (e - w) > 1.0:
        raise ValueError("Rectángulo demasiado grande para Overpass; use un extracto .pbf")
    query = f'[out:xml][timeout:180];way["highway"]({s},{w},{n},{e});(._;>;);out body;'
    data = urllib.parse.urlencode({"data": query}).encode()
    req = urllib.request.Request(endpoint, data=data, headers={"User-Agent": "LATTIMEX map builder"})
    target.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(req, timeout=300) as resp, target.open("wb") as fh:
        while chunk := resp.read(1 << 20):
            fh.write(chunk)
    return target
