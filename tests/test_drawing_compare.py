"""Тесты drawing_analysis: парсер размеров и сверка с STEP (этап 1 TZ)."""

import unittest

from drawing_analysis.compare import compare_drawing_to_step
from drawing_analysis.parser import parse_dimensions_from_text


PEDAL_STEP = {
    "part_family": "plate",
    "material": "",
    "holes": [
        {"diameter": 6.5, "radius": 3.2, "feature": "bore"},
        {"diameter": 6.5, "radius": 3.2, "feature": "bore"},
    ],
    "geometry": {"part_family": "plate", "holes": []},
}


class TestParseDimensions(unittest.TestCase):
    def test_counted_diameter(self):
        dims = parse_dimensions_from_text("Сверление 2×Ø6.4 на глубину 10")
        diam = [d for d in dims if d.get("kind") == "diameter"]
        self.assertEqual(len(diam), 1)
        self.assertAlmostEqual(diam[0]["value_mm"], 6.4)
        self.assertEqual(diam[0]["count_hint"], 2)

    def test_ra_roughness_in_fields_path(self):
        from drawing_analysis.parser import parse_drawing_text_to_fields

        fields = parse_drawing_text_to_fields("Ra 3.2 по всей поверхности")
        self.assertTrue(fields.get("roughness"))


class TestComparePedal(unittest.TestCase):
    def test_hole_diameter_mismatch_pedal(self):
        drawing = {
            "pdf_hash": "abc",
            "full_text": "2×Ø6.4",
            "parsed_dimensions": parse_dimensions_from_text("2×Ø6.4"),
            "fields": {"material": "Сталь 45"},
        }
        result = compare_drawing_to_step(drawing, PEDAL_STEP)
        codes = [i["code"] for i in result.get("items", [])]
        self.assertIn("hole_diameter_mismatch", codes)
        self.assertEqual(result["status"], "warning")

    def test_no_drawing_skips_hole_rules(self):
        result = compare_drawing_to_step({}, PEDAL_STEP)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["items"], [])

    def test_empty_compare_items_ok(self):
        drawing = {
            "pdf_hash": "x",
            "full_text": "плита 100x80",
            "parsed_dimensions": [],
            "fields": {},
        }
        step = {"part_family": "plate", "holes": []}
        result = compare_drawing_to_step(drawing, step)
        self.assertIn(result["status"], ("ok", "warning"))


if __name__ == "__main__":
    unittest.main()
