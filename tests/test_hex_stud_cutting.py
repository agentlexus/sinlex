"""Раздельное время резания для шпильки с шестигранником."""

import unittest

from machining_cost import compute_machining_quote, _compute_machining_quote_base


STUD_GEOM = {
    "complexity": "высокая",
    "detail_index": 8.88,
    "part_family": "rod",
    "hex_head_stud": True,
    "setup_count_total": 2,
    "setup_count_turning": 1,
    "setup_count_milling": 1,
    "shafts": [{"diameter": 5.8, "radius": 2.9, "feature": "body"}],
    "holes": [{"diameter": 2.5, "radius": 1.2, "feature": "bore"}],
}
STUD_DIMS = {"x": 5.4, "y": 5.7, "z": 12.5}


class TestHexStudCutting(unittest.TestCase):
    def test_hex_stud_cutting_higher_than_bulk(self):
        kw = dict(
            removal_volume_cm3=0.852,
            removal_rate=210.0,
            batch_size=1,
            model_volume_mm3=153.4461,
            density_g_cm3=2.78,
            operations=["Токарная", "Фрезерная"],
            geometry=STUD_GEOM,
            workpiece_type="Пруток",
            part_family="rod",
            cam_rate_per_hour=0.0,
            dimensions=STUD_DIMS,
        )
        bulk = _compute_machining_quote_base(**{**kw, "geometry": {**STUD_GEOM, "hex_head_stud": False}})
        hex_q = compute_machining_quote(**kw)
        self.assertGreater(hex_q["cutting_per_part_h"], bulk["cutting_per_part_h"] * 2.0)
        bd = hex_q.get("cutting_breakdown") or {}
        self.assertEqual(bd.get("mode"), "hex_head_stud")
        self.assertGreater(bd.get("thread_h", 0), 0)
        self.assertGreater(bd.get("turn_h", 0), 0)
        self.assertGreater(bd.get("mill_h", 0), 0)
        # ~1+ min резания для M3 шпильки, не 0.2 мин
        self.assertGreater(hex_q["cutting_per_part_h"] * 60, 0.8)

    def test_milling_only_unchanged(self):
        kw = dict(
            removal_volume_cm3=0.852,
            removal_rate=210.0,
            batch_size=1,
            model_volume_mm3=153.4461,
            density_g_cm3=2.78,
            operations=["Фрезерная"],
            geometry={**STUD_GEOM, "hex_head_stud": True},
            workpiece_type="Пруток",
            part_family="rod",
        )
        q = _compute_machining_quote_base(**kw)
        self.assertNotIn("cutting_breakdown", q)


if __name__ == "__main__":
    unittest.main()
