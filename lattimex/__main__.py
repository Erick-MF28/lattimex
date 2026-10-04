# Copyright (c) 2026 LATTIMEX. Licencia MIT (ver LICENSE).
"""Línea de comandos de LATTIMEX.

  python -m lattimex build                          compila el motor (C++)
  python -m lattimex map --osm ciudad.osm --name c  construye el mapa propio
  python -m lattimex map --bbox S,W,N,E --name c    descarga (una vez) y construye
  python -m lattimex serve                          servidor local para el Planner
  python -m lattimex app                            ventana de inicio (sin terminal)
  python -m lattimex doctor                         revisa la instalación
  python -m lattimex probe                          huella determinista del motor
  python -m lattimex sample --n 60 > entregas.csv   entregas sintéticas para probar

Los datos (mapas, base SQLite y resultados) viven en ./data. Para usar otra carpeta:
--data CARPETA en cualquier comando, o la variable de entorno LATTIMEX_HOME.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import sys
from pathlib import Path

from . import __version__, ENGINE_VERSION, native

DATA = Path(os.environ.get("LATTIMEX_HOME", Path(__file__).resolve().parent.parent / "data"))


def cmd_build(_):
    for lib in native.build():
        print(f"  {lib.name}  sha256 {hashlib.sha256(lib.read_bytes()).hexdigest()[:16]}")


def cmd_map(args):
    from . import maps
    source = Path(args.osm) if args.osm else None
    if args.bbox:
        bbox = tuple(float(v) for v in args.bbox.split(","))
        source = DATA / "osm" / f"{args.name}.osm"
        if not source.exists():
            print("Descargando calles de OpenStreetMap (una sola vez)…")
            maps.download_osm(bbox, source)
    if not source:
        sys.exit("Indique --osm archivo.osm|.osm.pbf o --bbox sur,oeste,norte,este")
    meta = maps.build_map(source, args.name, DATA / "maps")
    print(json.dumps(meta, ensure_ascii=False, indent=1))


def cmd_serve(args):
    from .server import serve, DEFAULT_ORIGINS
    # --allow-origin agrega orígenes (p. ej. una copia local del Planner); lattimex.com sigue permitido.
    origins = DEFAULT_ORIGINS + tuple(o for o in (args.allow_origin or []) if o.rstrip("/") not in DEFAULT_ORIGINS)
    server = serve(DATA, args.port, args.map, origins)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def cmd_app(_):
    from .launcher import main as launcher_main
    launcher_main()


def cmd_doctor(_):
    ok = True
    print(f"LATTIMEX {__version__} · {ENGINE_VERSION}")
    print(f"  datos    {DATA}")
    for key, value in native.status().items():
        print(f"  {key:8} {value or 'FALTA'}")
        ok &= value is not None
    maps = sorted(p for p in (DATA / "maps").glob("*.json") if not p.name.endswith(".roads.json"))
    print(f"  mapas    {', '.join(p.stem for p in maps) or 'FALTA (python -m lattimex map ...)'}")
    ok &= bool(maps)
    for mod in ("numpy", "scipy", "networkx", "pyproj"):
        try:
            __import__(mod)
        except ImportError:
            print(f"  FALTA el paquete {mod}: pip install -r requirements.txt"); ok = False
    print("Todo listo." if ok else "Hay pendientes; revise las líneas marcadas con FALTA.")
    sys.exit(0 if ok else 1)


def cmd_probe(args):
    """Huella determinista: instancia entera fija y presupuesto por iteraciones.

    Dos binarios compilados del mismo fuente deben dar la misma huella aunque su
    hash de archivo difiera (compiladores distintos)."""
    os.environ["LATTIMEX_ITER_BUDGET"] = str(args.iters)
    os.environ["LATTIMEX_THREADS"] = "1"
    native.configure()
    import engine_runtime as er  # noqa: PLC0415
    rng = random.Random(20260929)
    n = 60
    pts = [(rng.randint(0, 1000), rng.randint(0, 1000)) for _ in range(n)]
    matrix = [[float(round(((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** .5)) for b in pts] for a in pts]
    packages = [{"id": f"P{i}", "node": i, "dims_cm": [40, 30, 20 + (i % 5) * 10], "weight_kg": 5 + i % 7}
                for i in range(1, n)]
    req = {"matrix_m": matrix, "fleet": [{"cargo_cm": [300, 150, 150], "max_weight_kg": 1200, "doors": ["rear"]}] * 4,
           "fleet_count": 4, "packages": packages, "constraints": {"support": False, "fragility": False, "lifo": False},
           "budget_sec": 30, "perfil": "fast", "seed": 7}
    res = er.solve(req)
    routes = [r["sequence"] for r in res["routes"]]
    firma = hashlib.sha256(json.dumps(routes).encode()).hexdigest()[:16]
    print(json.dumps({"engine": ENGINE_VERSION, "core_sha": er.CORE_SHA, "iters": args.iters,
                      "routes": len(routes), "distance_m": res.get("total_distance_m"), "signature": firma}))


def cmd_sample(args):
    """Entregas sintéticas sobre las calles del mapa (para probar; no son datos reales)."""
    import pickle  # noqa: PLC0415
    from pyproj import Transformer  # noqa: PLC0415
    from .server import load_map  # noqa: PLC0415
    graph, _, _ = load_map(DATA / "maps", args.map)
    with graph.open("rb") as fh:
        nodes = list(pickle.load(fh).nodes)
    back = Transformer.from_crs("EPSG:6372", "EPSG:4326", always_xy=True)
    rng = random.Random(args.seed)
    cx, cy = sorted(n[0] for n in nodes)[len(nodes) // 2], sorted(n[1] for n in nodes)[len(nodes) // 2]
    near = sorted(nodes, key=lambda p: (p[0] - cx) ** 2 + (p[1] - cy) ** 2)[: max(2000, args.n * 20)]
    picks = rng.sample(near, args.n + 1)
    sizes = [(20, 15, 10), (35, 25, 18), (45, 35, 25), (60, 40, 30), (80, 50, 40)]
    w = csv_writer()
    w(["tipo", "guia", "latitud", "longitud", "dimensiones_cm", "peso_kg", "fragil"])
    for i, (x, y) in enumerate(picks):
        lng, lat = back.transform(x, y)
        if i == 0:
            w(["deposito", "CENTRO", f"{lat:.6f}", f"{lng:.6f}", "1x1x1", "0", "0"]); continue
        d = rng.choice(sizes)
        w(["cliente", f"DEMO-{i:04d}", f"{lat:.6f}", f"{lng:.6f}", "x".join(map(str, d)),
           f"{round(d[0] * d[1] * d[2] / 8000 * rng.uniform(.6, 1.4), 1)}", "1" if rng.random() < .1 else "0"])


def csv_writer():
    import csv  # noqa: PLC0415
    writer = csv.writer(sys.stdout, lineterminator="\n")
    return writer.writerow


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(prog="lattimex", description="LATTIMEX local: motor, mapas y servidor")
    p.add_argument("--version", action="version", version=f"lattimex {__version__} ({ENGINE_VERSION})")
    sub = p.add_subparsers(dest="cmd", required=True)
    datos = argparse.ArgumentParser(add_help=False)
    datos.add_argument("--data", metavar="CARPETA",
                       help="carpeta de datos: mapas, base SQLite y resultados (por defecto ./data)")
    sub.add_parser("build", help="compila el motor").set_defaults(fn=cmd_build)
    m = sub.add_parser("map", parents=[datos], help="construye un mapa propio desde OpenStreetMap")
    m.add_argument("--osm"); m.add_argument("--bbox"); m.add_argument("--name", required=True)
    m.set_defaults(fn=cmd_map)
    s = sub.add_parser("serve", parents=[datos], help="servidor local para el Planner")
    s.add_argument("--port", type=int, default=8765); s.add_argument("--map")
    s.add_argument("--allow-origin", action="append",
                   help="origen adicional del Planner (por defecto https://lattimex.com)")
    s.set_defaults(fn=cmd_serve)
    sub.add_parser("doctor", parents=[datos], help="revisa la instalación").set_defaults(fn=cmd_doctor)
    sub.add_parser("app", help="ventana de inicio: servidor, mapa y Planner sin terminal").set_defaults(fn=cmd_app)
    pr = sub.add_parser("probe", help="huella determinista del motor")
    pr.add_argument("--iters", type=int, default=3000); pr.set_defaults(fn=cmd_probe)
    sa = sub.add_parser("sample", parents=[datos], help="entregas sintéticas para probar")
    sa.add_argument("--n", type=int, default=60); sa.add_argument("--seed", type=int, default=1)
    sa.add_argument("--map"); sa.set_defaults(fn=cmd_sample)
    args = p.parse_args(argv)
    if getattr(args, "data", None):
        global DATA
        DATA = Path(args.data).expanduser().resolve()
    args.fn(args)


if __name__ == "__main__":
    main()
