"""P3L: acomodador 3D de una ruta (native/p3l.cpp) y verificador estricto de restricciones de carga.

Desde la versión 1.1.0 es el acomodador predeterminado del motor. Semántica (Gendreau et al. 2006,
igual que el validador público de Krebs):
  x = largo (puerta en x = L), y = ancho, z = alto; P3L sólo rota en horizontal (l <-> w).
  soporte: área apoyada >= alpha * l * w (o en el piso), alpha = 0.75.
  fragilidad: una caja no frágil no toca por arriba a una frágil.
  LIFO: si e se entrega antes que t, t no queda delante de e con proyección y-z común, ni encima de e
        con proyección x-y común.

`verify` comprueba cualquier acomodo (de P3L o del empacador de puntos extremos de 1.0) con esa
semántica; el motor sólo acepta un acomodo que la cumple.
"""
from __future__ import annotations

import ctypes
import os
from pathlib import Path

SUPPORT_ALPHA = 0.75
EPS = 1e-6
VARIANT_FLAGS = {  # soporte, fragilidad, LIFO
    "loading-only": (0, 0, 0), "no-support": (0, 1, 1), "no-fragility": (1, 0, 1), "no-lifo": (1, 1, 0),
    "all-constraints": (1, 1, 1), "fragility-only": (0, 1, 0), "support-only": (1, 0, 0),
    "lifo-only": (0, 0, 1),     # interna: loading-only con orden de descarga
}

_D = ctypes.POINTER(ctypes.c_double)
_I = ctypes.POINTER(ctypes.c_int32)
_B = ctypes.POINTER(ctypes.c_uint8)
_FN = None
_PATH = os.environ.get("LATTIMEX_P3L")
if _PATH and Path(_PATH).exists():
    _lib = ctypes.CDLL(_PATH)
    _FN = _lib.p3l_pack
    _FN.restype = ctypes.c_int
    _FN.argtypes = [ctypes.c_int, _D, _I, _B, _B, ctypes.c_double, ctypes.c_double, ctypes.c_double, ctypes.c_int,
                    ctypes.c_double, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_double,
                    ctypes.c_uint32, _D, _D, _B, _D]
AVAILABLE = _FN is not None


def pack(items: list[dict], cargo, variant: str, *, flags: int | None = None, time_ms: float = 50.0,
         max_iters: int = 10 ** 6, seed: int = 1, alpha: float = SUPPORT_ALPHA):
    """Acomoda una ruta.

    items: [{'id', 'dims': [l, w, h], 'rank': posición de entrega (1 = primera), 'fragile'}].
    flags: None elige por tamaño (haz y posiciones enteras con <= 30 cajas; esquinas con más).
    Devuelve (todas_colocadas, colocaciones) con colocaciones
    [{'id', 'x', 'y', 'z', 'l', 'w', 'h'}] (dimensiones ya rotadas)."""
    if _FN is None:
        raise RuntimeError("P3L no está compilado: ejecute `python -m lattimex build`")
    n = len(items)
    sup, fra, lifo = VARIANT_FLAGS[variant]
    if flags is None:
        flags = 6 if n <= 30 else 1
    arr = lambda t, v: (t * max(1, len(v)))(*v)
    dims = arr(ctypes.c_double, [float(d) for it in items for d in it["dims"]])
    rank = arr(ctypes.c_int32, [int(it["rank"]) for it in items])
    frag = arr(ctypes.c_uint8, [1 if it.get("fragile") else 0 for it in items])
    rot = arr(ctypes.c_uint8, [1] * n)
    pos = (ctypes.c_double * (3 * n + 3))(); od = (ctypes.c_double * (3 * n + 3))(); pl = (ctypes.c_uint8 * (n + 1))()
    st = (ctypes.c_double * 3)()
    ok = _FN(n, dims, rank, frag, rot, float(cargo[0]), float(cargo[1]), float(cargo[2]), sup, alpha, fra, lifo,
             int(flags), int(max_iters), float(time_ms), int(seed) & 0xFFFFFFFF, pos, od, pl, st)
    out = [{"id": items[i]["id"], "x": pos[3 * i], "y": pos[3 * i + 1], "z": pos[3 * i + 2],
            "l": od[3 * i], "w": od[3 * i + 1], "h": od[3 * i + 2]} for i in range(n) if pl[i]]
    return bool(ok), out


def _ov(a0, a1, b0, b1):
    return min(a1, b1) - max(a0, b0) > EPS


def verify(boxes: list[dict], cargo, variant: str, alpha: float = SUPPORT_ALPHA) -> str | None:
    """None si el acomodo cumple la variante; si no, el motivo.

    boxes: [{'x','y','z','l','w','h','rank','fragile'}] con rank = posición de entrega (1 = primera)."""
    sup, fra, lifo = VARIANT_FLAGS[variant]
    L, W, H = (float(c) for c in cargo)
    for b in boxes:
        if b["x"] < -EPS or b["y"] < -EPS or b["z"] < -EPS or b["x"] + b["l"] > L + EPS \
                or b["y"] + b["w"] > W + EPS or b["z"] + b["h"] > H + EPS:
            return "fuera-del-contenedor"
    n = len(boxes)
    for i in range(n):
        a = boxes[i]
        for j in range(i + 1, n):
            b = boxes[j]
            if _ov(a["x"], a["x"] + a["l"], b["x"], b["x"] + b["l"]) and _ov(a["y"], a["y"] + a["w"], b["y"], b["y"] + b["w"]) \
                    and _ov(a["z"], a["z"] + a["h"], b["z"], b["z"] + b["h"]):
                return "solape"
    for t in boxes:
        if t["z"] <= EPS:
            continue
        area = 0.0
        for b in boxes:
            if b is t or abs(b["z"] + b["h"] - t["z"]) > EPS:
                continue
            ox = min(t["x"] + t["l"], b["x"] + b["l"]) - max(t["x"], b["x"])
            oy = min(t["y"] + t["w"], b["y"] + b["w"]) - max(t["y"], b["y"])
            if ox > EPS and oy > EPS:
                area += ox * oy
                if fra and b.get("fragile") and not t.get("fragile"):
                    return "no-fragil-sobre-fragil"
        if sup and area < alpha * t["l"] * t["w"] * 0.99 - EPS:
            return "soporte-insuficiente"
    if lifo:
        for e in boxes:
            for t in boxes:
                if t["rank"] <= e["rank"]:
                    continue
                # e se entrega antes: t no puede bloquearla por delante ni por encima
                xy = _ov(e["x"], e["x"] + e["l"], t["x"], t["x"] + t["l"]) and _ov(e["y"], e["y"] + e["w"], t["y"], t["y"] + t["w"])
                yz = _ov(e["y"], e["y"] + e["w"], t["y"], t["y"] + t["w"]) and _ov(e["z"], e["z"] + e["h"], t["z"], t["z"] + t["h"])
                if yz and e["x"] + e["l"] <= t["x"] + EPS:
                    return "orden-de-descarga-delante"
                if xy and e["z"] + e["h"] <= t["z"] + EPS:
                    return "orden-de-descarga-encima"
    return None
