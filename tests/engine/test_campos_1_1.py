# -*- coding: utf-8 -*-
"""Campos nuevos de la API local en 1.1.0: fleet_mode y router llegan validados al motor."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from lattimex.server import validate_solve  # noqa: E402


def peticion(**extra):
    return {"points": [{"lat": 20.58, "lng": -100.38}, {"lat": 20.59, "lng": -100.37}],
            "fleet": [{"cargo_cm": [300, 150, 150], "max_weight_kg": 1000}],
            "packages": [{"id": "P1", "node": 1, "dims_cm": [40, 30, 20], "weight_kg": 2}], **extra}


class CamposTest(unittest.TestCase):
    def test_valores_por_omision(self):
        v = validate_solve(peticion())
        self.assertEqual((v["fleet_mode"], v["router"]), ("exact", "auto"))

    def test_valores_validos(self):
        v = validate_solve(peticion(fleet_mode="UP_TO", router="senda"))
        self.assertEqual((v["fleet_mode"], v["router"]), ("up_to", "senda"))

    def test_valores_invalidos(self):
        with self.assertRaises(ValueError):
            validate_solve(peticion(fleet_mode="libre"))
        with self.assertRaises(ValueError):
            validate_solve(peticion(router="hgs"))


if __name__ == "__main__":
    unittest.main()
