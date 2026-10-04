from __future__ import annotations

import unittest

import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
from lattimex import native; native.configure()
from loading3d import ExtremePoint3D, LoadingOptions


class CapturedConstraintTest(unittest.TestCase):
    def setUp(self):
        self.solver = ExtremePoint3D(LoadingOptions(
            max_restarts=1, support_ratio=0.0, enforce_unload_order=False,
            orientation_policy="all", enforce_fragility=False,
        ))

    def test_keep_upright_preserves_original_height(self):
        items = self.solver._normalize({"items": [{
            "guideId": "G1", "clientIndex": 1, "dimensionsCm": [2, 3, 4],
            "volumeCm3": 24, "keepUpright": True,
        }]}, [10, 10, 10])
        self.assertEqual({rotation["dimensions"][2] for rotation in items[0]["rotations"]}, {4.0})

    def test_nonstackable_rejects_box_on_top(self):
        request = {"vehicle": {"cargoDimensions": [10, 10, 10]}, "items": [{}, {}]}
        bottom = {"guideId": "A", "x": 0, "y": 0, "z": 0, "lengthCm": 5,
                  "widthCm": 5, "heightCm": 5, "fragile": False,
                  "stackable": False, "deliveryRank": 2}
        top = {"guideId": "B", "x": 0, "y": 0, "z": 5, "lengthCm": 5,
               "widthCm": 5, "heightCm": 5, "fragile": False,
               "stackable": True, "deliveryRank": 1}
        self.assertEqual(self.solver._verify(request, [bottom, top]),
                         (False, "item-on-nonstackable"))


if __name__ == "__main__":
    unittest.main()
