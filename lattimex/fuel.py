# Copyright (c) 2026 LATTIMEX. Licencia MIT (ver LICENSE).
"""Precio del combustible desde los datos abiertos de la CRE (Comisión Reguladora de Energía).

La CRE publica el precio vigente de cada estación de servicio de México (gasolina regular, premium y
diésel) y su ubicación. Aquí se descargan esos dos archivos públicos y se calcula la mediana de las
estaciones cercanas al centro de distribución; si hay pocas, la mediana nacional.

La consulta solo descarga datos públicos: no envía ningún dato de la operación. En modo manual no se
hace ninguna consulta.
"""
from __future__ import annotations

import math
import statistics
import time
import urllib.request
import xml.etree.ElementTree as ET

PRICES_URL = "https://publicacionexterna.azurewebsites.net/publicaciones/prices"
PLACES_URL = "https://publicacionexterna.azurewebsites.net/publicaciones/places"
SOURCE = "CRE · precios vigentes por estación (datos abiertos)"
FUEL_TYPES = ("regular", "premium", "diesel")
MAX_BYTES = 40_000_000
RADIUS_KM = 25.0
MIN_STATIONS = 5
STALE_HOURS = 12


def _download(url: str, timeout: float = 30.0) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "lattimex-local"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = response.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError("El archivo de la CRE excede el tamaño esperado")
    return data


def _parse(data: bytes) -> ET.Element:
    # Los archivos de la CRE no usan DTD; rechazarla evita expansiones de entidades.
    if b"<!DOCTYPE" in data[:4096] or b"<!ENTITY" in data:
        raise ValueError("Formato de la CRE no reconocido")
    return ET.fromstring(data)


def _number(node: ET.Element | None) -> float | None:
    try:
        value = float((node.text or "").strip()) if node is not None else None
    except ValueError:
        return None
    return value if value is not None and math.isfinite(value) else None


def parse_places(data: bytes) -> dict[str, tuple[float, float]]:
    places = {}
    for place in _parse(data):
        lng, lat = _number(place.find("location/x")), _number(place.find("location/y"))
        if lat is not None and lng is not None:
            places[place.get("place_id", "")] = (lat, lng)
    return places


def parse_prices(data: bytes) -> dict[str, dict[str, float]]:
    prices: dict[str, dict[str, float]] = {}
    for place in _parse(data):
        for node in place.findall("gas_price"):
            value, kind = _number(node), node.get("type")
            # Se descartan capturas evidentemente erróneas (precios de 0 o de miles de pesos).
            if kind in FUEL_TYPES and value is not None and 5 < value < 100:
                prices.setdefault(place.get("place_id", ""), {})[kind] = value
    return prices


def _km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat = math.radians((a[0] + b[0]) / 2)
    return 6371.0 * math.hypot(math.radians(b[1] - a[1]) * math.cos(lat), math.radians(b[0] - a[0]))


def summarize(prices: dict[str, dict[str, float]], places: dict[str, tuple[float, float]],
              center: tuple[float, float] | None, radius_km: float = RADIUS_KM) -> dict:
    """Mediana por tipo; local si hay al menos MIN_STATIONS estaciones en el radio, si no nacional."""
    near = []
    if center is not None:
        near = [prices[pid] for pid, loc in places.items() if pid in prices and _km(center, loc) <= radius_km]
    out = {"prices": {}, "stations": {}, "scope": {}}
    for kind in FUEL_TYPES:
        local = [p[kind] for p in near if kind in p]
        values, scope = (local, "local") if len(local) >= MIN_STATIONS else (
            [p[kind] for p in prices.values() if kind in p], "nacional")
        if values:
            out["prices"][kind] = round(statistics.median(values), 2)
            out["stations"][kind] = len(values)
            out["scope"][kind] = scope
    out["radius_km"] = radius_km
    out["center"] = list(center) if center else None
    return out


def fetch_summary(center: tuple[float, float] | None) -> dict:
    """Descarga los archivos públicos de la CRE y devuelve el resumen con la fecha de consulta."""
    prices = parse_prices(_download(PRICES_URL))
    places = parse_places(_download(PLACES_URL))
    if not prices:
        raise ValueError("La CRE no devolvió precios")
    summary = summarize(prices, places, center)
    summary["fetched_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    summary["fetched_epoch"] = time.time()
    summary["source"] = SOURCE
    return summary
