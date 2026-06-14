"""Тесты UI-хелперов критериев чертежа (CR-4 TZ)."""

import unittest

from page_modules.costing_ui import (
    _criteria_has_ui,
    build_criteria_table_rows,
    _modifier_summary_lines,
)


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


if __name__ == "__main__":
    unittest.main()
