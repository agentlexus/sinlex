"""Тесты machining_cost + критерии чертежа (этап CR-2 TZ)."""

import unittest

from drawing_analysis.manufacturing_criteria import extract_manufacturing_criteria
from machining_cost import (
    _compute_machining_quote_base,
    apply_drawing_criteria_to_quote,
    compute_machining_quote,
)


def _base_kwargs() -> dict:
    geometry = {
        "complexity": "средняя",
        "detail_index": 8.0,
        "part_family": "plate",
        "setup_count_total": 2,
    }
    return {
        "removal_volume_cm3": 50.0,
        "removal_rate": 250.0,
        "batch_size": 10,
        "model_volume_mm3": 120_000.0,
        "density_g_cm3": 7.85,
        "operations": ["Фрезерная", "Сверлильная"],
        "geometry": geometry,
        "workpiece_type": "Плита",
        "part_family": "plate",
        "cam_rate_per_hour": 1000.0,
    }


class TestRegressionNoCriteria(unittest.TestCase):
    def test_no_criteria_matches_base(self):
        kw = _base_kwargs()
        base = _compute_machining_quote_base(**kw)
        full = compute_machining_quote(**kw, drawing_criteria=None)
        for key in ("mhpu", "mht", "cutting_per_part_h", "setup_per_part_h", "cam_per_part_h"):
            self.assertAlmostEqual(base[key], full[key], places=6, msg=key)
        self.assertEqual(full.get("criteria_breakdown"), {})
        self.assertEqual(full.get("grind_price_mult"), 1.0)

    def test_empty_criteria_active_codes(self):
        kw = _base_kwargs()
        empty = extract_manufacturing_criteria(None)
        q = compute_machining_quote(**kw, drawing_criteria=empty)
        base = _compute_machining_quote_base(**kw)
        self.assertAlmostEqual(base["mhpu"], q["mhpu"], places=6)


class TestCriteriaModifiers(unittest.TestCase):
    def test_finish_and_keyway_increase_times(self):
        kw = _base_kwargs()
        base = compute_machining_quote(**kw, drawing_criteria=None)
        text = "Ra 1.6\n2×Ø6.4 H7\nшпоночный паз 5"
        criteria = extract_manufacturing_criteria(
            {"pdf_hash": "x", "full_text": text, "fields": {}, "parsed_dimensions": []}
        )
        self.assertIn("ra_finish_16", criteria["active_codes"])
        self.assertIn("keyway", criteria["active_codes"])
        adj = compute_machining_quote(**kw, drawing_criteria=criteria)
        self.assertGreater(adj["mhpu"], base["mhpu"])
        self.assertGreater(adj["cam_per_part_h"], base["cam_per_part_h"])
        self.assertGreater(
            adj["quote_adjusted"]["mhpu"],
            adj["quote_base"]["mhpu"],
        )

    def test_grinding_price_mult(self):
        kw = _base_kwargs()
        criteria = extract_manufacturing_criteria(
            {"pdf_hash": "x", "full_text": "Ra 0.8", "fields": {}, "parsed_dimensions": []}
        )
        self.assertTrue(criteria["detected"]["ra_grinding"])
        q = compute_machining_quote(**kw, drawing_criteria=criteria)
        gmult = q.get("grind_price_mult", 1.0)
        self.assertGreater(gmult, 1.0)
        self.assertIn("Шлифование", q["criteria_breakdown"].get("operations_add", []))
        cph = 2500
        mct = 1000
        cam_cost = q["cam_cost_batch"]
        cr = 50
        mcst_base = q["quote_base"]["mht"] * cph
        mcst_adj = q["mht"] * cph * gmult
        tc_base = mcst_base + mct + cam_cost - cr
        tc_adj = mcst_adj + mct + cam_cost - cr
        self.assertGreater(tc_adj, tc_base)

    def test_measure_hours_in_mhpu(self):
        kw = _base_kwargs()
        base_q = _compute_machining_quote_base(**kw)
        criteria = extract_manufacturing_criteria(
            {"pdf_hash": "x", "full_text": "Ø10 H7", "fields": {}, "parsed_dimensions": []}
        )
        out = apply_drawing_criteria_to_quote(base_q, criteria, batch_size=10)
        measure = out["criteria_breakdown"]["measure_per_part_h"]
        self.assertGreater(measure, 0.0)
        self.assertGreaterEqual(
            out["mhpu"],
            base_q["mhpu"] + measure - 1e-6,
        )


if __name__ == "__main__":
    unittest.main()
