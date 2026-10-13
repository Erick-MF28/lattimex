from __future__ import annotations

import unittest

import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
from lattimex import native; native.configure()
from loading3d import ExtremePoint3D, LoadingOptions, _guillotine_layout


def _request(count, dims, cargo):
    return {"vehicle": {"id": "van", "cargoDimensions": cargo, "maxWeightKg": 1e6}, "deliveryOrder": [1],
            "items": [{"guideId": f"B{i}", "clientIndex": 1, "dimensionsCm": dims, "weightKg": 5,
                       "keepUpright": True} for i in range(count)]}


class HomogeneousLayersTest(unittest.TestCase):
    def setUp(self):
        self.solver = ExtremePoint3D(LoadingOptions(
            max_restarts=8, support_ratio=1.0, enforce_unload_order=False,
            orientation_policy="horizontal", enforce_fragility=True,
        ))

    def test_layout_beats_single_orientation_grid(self):
        # 40 × 30 en 337.344 × 137.192: una sola orientación da 32 u 33 por capa.
        layout = _guillotine_layout(337.344, 137.192, [(40.0, 30.0), (30.0, 40.0)])
        self.assertGreaterEqual(len(layout), 35)
        for i, (x, y, l, w) in enumerate(layout):
            self.assertLessEqual(x + l, 337.344 + 1e-6)
            self.assertLessEqual(y + w, 137.192 + 1e-6)
            for x2, y2, l2, w2 in layout[i + 1:]:
                self.assertFalse(x < x2 + l2 and x2 < x + l and y < y2 + w2 and y2 < y + w)

    def test_identical_boxes_use_layers_and_verify(self):
        cargo = [337.344, 137.192, 177.88]
        request = _request(220, [40, 30, 30], cargo)
        result = self.solver.evaluate(request)
        placed = {p["guideId"] for p in result["placements"]}
        self.assertGreaterEqual(len(placed), 175)
        self.assertEqual(result.get("pattern"), "homogeneous-layers")
        subset = {**request, "items": [i for i in request["items"] if i["guideId"] in placed]}
        self.assertTrue(self.solver.verify(subset, result["placements"])["ok"])

    def test_mixed_boxes_keep_extreme_point_result(self):
        request = _request(6, [40, 30, 30], [337.344, 137.192, 177.88])
        request["items"][0]["dimensionsCm"] = [50, 30, 30]
        result = self.solver.evaluate(request)
        self.assertNotIn("pattern", result)
        self.assertEqual(result["status"], "heuristic-feasible")


if __name__ == "__main__":
    unittest.main()
