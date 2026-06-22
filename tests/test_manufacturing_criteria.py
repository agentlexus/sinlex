"""Тесты drawing_analysis.manufacturing_criteria (этап CR-1 TZ)."""

import unittest

from drawing_analysis.manufacturing_criteria import extract_manufacturing_criteria


def _extraction(text: str, **fields) -> dict:
    return {
        "pdf_hash": "abc123",
        "full_text": text,
        "fields": fields,
        "parsed_dimensions": [],
    }


class TestRaCriteria(unittest.TestCase):
    def test_ra_16_finish_not_grinding(self):
        c = extract_manufacturing_criteria(_extraction("Ra 1.6 по поверхности"))
        d = c["detected"]
        self.assertTrue(d["ra_finish_16"])
        self.assertFalse(d["ra_grinding"])
        self.assertIn("ra_finish_16", c["active_codes"])
        self.assertNotIn("ra_grinding", c["active_codes"])
        self.assertNotIn("Шлифование", c["modifiers"]["operations_add"])

    def test_ra_08_grinding(self):
        c = extract_manufacturing_criteria(_extraction("Ra 0.8"))
        d = c["detected"]
        self.assertTrue(d["ra_grinding"])
        self.assertTrue(d["ra_finish_16"])
        self.assertIn("ra_grinding", c["active_codes"])
        self.assertIn("Шлифование", c["modifiers"]["operations_add"])
        self.assertGreater(c["modifiers"]["grind_price_mult"], 1.0)

    def test_ra_comma_decimal(self):
        c = extract_manufacturing_criteria(_extraction("Ra 1,6"))
        self.assertAlmostEqual(c["detected"]["ra_min"], 1.6)


class TestHoleTolerance(unittest.TestCase):
    def test_counted_diameter_h7(self):
        c = extract_manufacturing_criteria(_extraction("Сверление 2×Ø6.4 H7"))
        self.assertGreaterEqual(c["detected"]["toleranced_holes"], 1)
        self.assertIn("hole_tolerance", c["active_codes"])

    def test_diameter_plus_tolerance(self):
        c = extract_manufacturing_criteria(_extraction("Ø6.4 +0.02"))
        self.assertGreaterEqual(c["detected"]["toleranced_holes"], 1)


class TestKeyway(unittest.TestCase):
    def test_keyway_paz_5(self):
        c = extract_manufacturing_criteria(_extraction("шпоночный паз 5"))
        self.assertTrue(c["detected"]["keyway"])
        self.assertAlmostEqual(c["detected"]["keyway_width_mm"], 5.0)
        self.assertIn("keyway", c["active_codes"])

    def test_keyway_not_from_expert_text(self):
        c = extract_manufacturing_criteria(
            _extraction(""),
            expert_text="На детали предусмотрен шпоночный паз 5 мм по тексту ИИ",
        )
        self.assertFalse(c["detected"]["keyway"])
        self.assertNotIn("keyway", c["active_codes"])


class TestThread(unittest.TestCase):
    def test_m6(self):
        c = extract_manufacturing_criteria(_extraction("Отверстие M6"))
        self.assertGreaterEqual(c["detected"]["threaded_holes"], 1)
        self.assertIn("threaded_hole", c["active_codes"])

    def test_resba_m6(self):
        c = extract_manufacturing_criteria(_extraction("резьба M6"))
        self.assertGreaterEqual(c["detected"]["threaded_holes"], 1)

    def test_m18_with_pitch(self):
        c = extract_manufacturing_criteria(_extraction("Резьба M18x1.5"))
        self.assertGreaterEqual(c["detected"]["threaded_holes"], 1)

    def test_m12(self):
        c = extract_manufacturing_criteria(_extraction("M12-6H"))
        self.assertGreaterEqual(c["detected"]["threaded_holes"], 1)


class TestEmptyDrawing(unittest.TestCase):
    def test_none_extraction(self):
        c = extract_manufacturing_criteria(None)
        self.assertEqual(c["active_codes"], [])
        m = c["modifiers"]
        self.assertEqual(m["cutting_mult"], 1.0)
        self.assertEqual(m["setup_mult"], 1.0)
        self.assertEqual(m["cam_mult"], 1.0)
        self.assertEqual(m["grind_price_mult"], 1.0)
        self.assertEqual(m["operations_add"], [])

    def test_empty_text(self):
        c = extract_manufacturing_criteria(_extraction("   "))
        self.assertEqual(c["active_codes"], [])
        self.assertEqual(c["modifiers"]["cutting_mult"], 1.0)


class TestCombined(unittest.TestCase):
    def test_summary_ru(self):
        text = "Ra 1.6\n2×Ø6.4 H7\nрезьба M6\nшпоночный паз 5"
        c = extract_manufacturing_criteria(_extraction(text))
        self.assertTrue(c["summary_ru"])
        self.assertIn("ra_finish_16", c["active_codes"])
        self.assertIn("hole_tolerance", c["active_codes"])
        self.assertIn("threaded_hole", c["active_codes"])
        self.assertIn("keyway", c["active_codes"])
        self.assertIn("finish_pass_global", c["active_codes"])


class TestFieldsRoughness(unittest.TestCase):
    def test_roughness_from_fields(self):
        c = extract_manufacturing_criteria(
            _extraction("", roughness=["Ra 3.2", "Ra 1.6"])
        )
        self.assertTrue(c["detected"]["ra_finish_16"])


if __name__ == "__main__":
    unittest.main()
