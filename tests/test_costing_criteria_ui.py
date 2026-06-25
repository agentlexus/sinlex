"""Тесты UI-хелперов критериев чертежа (CR-4 TZ)."""

import importlib.util
from pathlib import Path
import sys
import types
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "page_modules"))

if importlib.util.find_spec("streamlit") is None:
    sys.modules["streamlit"] = types.SimpleNamespace(session_state={})

from page_modules.costing_ui import (
    _format_hours_h,
    _criteria_has_ui,
    build_criteria_table_rows,
    compute_costing_snapshot,
    _modifier_summary_lines,
)


class TestFormatHours(unittest.TestCase):
    def test_subminute_not_rounded_to_zero(self):
        self.assertEqual(_format_hours_h(0.005367), "0.3 мин")

    def test_zero(self):
        self.assertEqual(_format_hours_h(0), "0 мин")


class TestCriteriaUiHelpers(unittest.TestCase):
    def test_no_criteria(self):
        self.assertFalse(_criteria_has_ui(None))
        self.assertFalse(_criteria_has_ui({"active_codes": []}))
        self.assertEqual(build_criteria_table_rows(None), [])

    def test_table_rows(self):
        criteria = {
            "active_codes": ["ra_finish_16", "hole_tolerance", "finish_pass_global"],
            "modifiers": {
                "cutting_mult": 1.15,
                "setup_mult": 1.2,
                "measure_per_part_h": 0.25,
            },
        }
        rows = build_criteria_table_rows(criteria)
        codes = {r["Код"] for r in rows}
        self.assertIn("ra_finish_16", codes)
        self.assertIn("hole_tolerance", codes)
        self.assertNotIn("finish_pass_global", codes)

    def test_modifier_summary_grinding(self):
        mods = {"grind_price_mult": 1.35, "operations_add": ["Шлифование"]}
        lines = _modifier_summary_lines(mods, None)
        self.assertTrue(any("Шлифование" in ln for ln in lines))
        self.assertTrue(any("1.35" in ln for ln in lines))


class TestCostingSnapshotMaterialCost(unittest.TestCase):
    def test_material_cost_uses_full_blank_mass_and_chips_use_removed_mass(self):
        snap = compute_costing_snapshot(
            geometry={"part_family": "plate", "complexity": "средняя", "detail_index": 1.0},
            dimensions={},
            operations=["Фрезерная"],
            model_volume=3_653_505.535,
            params={
                "wp": "Плита",
                "d1": 85,
                "l1": 500,
                "w1": 500,
                "h1": 20,
                "cph": 3500,
                "sm": "Алюминий Д16Т",
                "batch_size": 1,
                "mp": 700,
            },
            cam_rate_per_hour=0,
        )

        blank_kg = snap["bv"] * snap["den"] / 1_000_000
        self.assertAlmostEqual(blank_kg, 13.55, places=2)
        self.assertAlmostEqual(snap["mct"], 9485, places=0)
        self.assertAlmostEqual(snap["tcm"], 3.65, places=2)
        self.assertAlmostEqual(snap["cr"], 346, delta=1)


if __name__ == "__main__":
    unittest.main()
