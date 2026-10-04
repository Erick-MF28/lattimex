# -*- coding: utf-8 -*-
"""Equivalencia empacador Python vs C++ (lattimex_pack3d). Corre donde exista el .so
(Linux, Windows o macOS tras `python -m lattimex build`). Genera rutas aleatorias deterministas de distintos tamanos y variantes,
empaca con ambos y compara colocaciones exactamente. Sale 1 si hay diferencias."""
import os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
from lattimex import native
native.configure()
import loading3d
from loading3d import ExtremePoint3D, LoadingOptions

assert loading3d._NATIVE is not None, "no cargo liblattimex_pack3d.so"


def lcg(s):
    while True:
        s = (1103515245 * s + 12345) % 2147483648
        yield s


VARIANTES = {
    "loading-only": dict(support_ratio=0.0, enforce_unload_order=False, enforce_fragility=False),
    "no-lifo": dict(support_ratio=0.75, enforce_unload_order=False, enforce_fragility=True),
    "all-constraints": dict(support_ratio=0.75, enforce_unload_order=True, enforce_fragility=True),
}


def ruta(seed, n_items, n_clientes):
    g = lcg(seed)
    cargo = [300 + next(g) % 3 * 50, 160 + next(g) % 3 * 20, 160 + next(g) % 3 * 20]
    if next(g) % 4 == 0:
        cargo = [400.0, 200.0, 200.0]
    items = []
    for i in range(n_items):
        c = 1 + next(g) % n_clientes
        d = [20 + next(g) % 60, 20 + next(g) % 50, 15 + next(g) % 45]
        if next(g) % 5 == 0:
            d = [float(v) + 0.5 for v in d]     # decimales: prueba el redondeo de claves
        items.append({"guideId": f"G{i}", "clientIndex": c, "dimensionsCm": d,
                      "weightKg": 1 + next(g) % 20, "fragile": next(g) % 6 == 0,
                      "stackable": next(g) % 9 != 0, "keepUpright": next(g) % 7 == 0})
    return {"vehicle": {"id": f"V{seed}", "cargoDimensions": cargo, "maxWeightKg": 5000},
            "deliveryOrder": list(range(1, n_clientes + 1)), "items": items}


def firma(rep):
    return (rep["status"], rep.get("restartsAttempted"),
            [(p["guideId"], p["x"], p["y"], p["z"], p["lengthCm"], p["widthCm"], p["heightCm"], p["orientation"])
             for p in rep["placements"]],
            sorted(u["guideId"] for u in rep.get("unplacedItems") or []))


casos = 0; diff = 0; t_py = 0.0; t_cc = 0.0
tam = [(6, 3), (12, 5), (25, 8), (45, 12), (70, 20), (110, 30)]
for vname, vopts in VARIANTES.items():
    for n_items, n_cli in tam:
        for s in range(4):
            req = ruta(1000 * n_items + 17 * s + hash(vname) % 97, n_items, n_cli)
            restarts = 16 if n_items <= 25 else (8 if n_items <= 70 else 4)
            py = ExtremePoint3D(LoadingOptions(max_restarts=restarts, **vopts)); py.forzar_python = True
            cc = ExtremePoint3D(LoadingOptions(max_restarts=restarts, **vopts))
            t = time.perf_counter(); rp = py.evaluate(req); t_py += time.perf_counter() - t
            t = time.perf_counter(); rc = cc.evaluate(req); t_cc += time.perf_counter() - t
            casos += 1
            if firma(rp) != firma(rc):
                diff += 1
                print(f"DIFF {vname} n={n_items} s={s}: py={rp['status']}/{rp.get('restartsAttempted')} "
                      f"cc={rc['status']}/{rc.get('restartsAttempted')} placed py={len(rp['placements'])} cc={len(rc['placements'])}")
                fp, fc = firma(rp)[2], firma(rc)[2]
                for k, (a, b) in enumerate(zip(fp, fc)):
                    if a != b:
                        print("   primera diferencia en colocacion", k, "\n    py:", a, "\n    cc:", b); break
            elif s == 0:
                print(f"ok   {vname:16s} n={n_items:3d} {rp['status']:20s} intento={rp.get('restartsAttempted')} "
                      f"py={rp['elapsedMs']:.0f} ms cc={rc['elapsedMs']:.1f} ms")
print(f"\ncasos={casos} diferencias={diff}  tiempo python={t_py:.1f}s  c++={t_cc:.2f}s  aceleracion={t_py / max(t_cc, 1e-9):.0f}x")
sys.exit(1 if diff else 0)
