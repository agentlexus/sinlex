"""Техкарта и costing_quote с критериями чертежа (CR-5 TZ)."""

import unittest

from page_modules.pdf_analysis import (
    enrich_costing_quote_with_drawing_criteria,
    inject_tech_card_section5,
)


class TestTechCardCriteria(unittest.TestCase):
    def test_enrich_no_criteria(self):
        q = {"Время на 1 деталь, ч": 2, "Партия, шт": 10}
        out = enrich_costing_quote_with_drawing_criteria(q, drawing_criteria=None)
        self.assertEqual(out, q)

    def test_enrich_with_criteria(self):
        q = {"Время на 1 деталь, ч": 3, "Партия, шт": 5}
        criteria = {
            "active_codes": ["ra_grinding", "hole_tolerance"],
            "summary_ru": "Ra 0.8, 2 отв. с допуском",
            "modifiers": {
                "measure_per_part_h": 0.25,
                "operations_add": ["Шлифование"],
                "grind_price_mult": 1.35,
            },
        }
        out = enrich_costing_quote_with_drawing_criteria(
            q, drawing_criteria=criteria, criteria_breakdown={"grind_price_mult": 1.35}
        )
        self.assertIn("Критерии чертежа (Sinlex)", out)
        self.assertIn("Шлифование", out["Доп. процессы по чертежу"])
        self.assertEqual(out["Контроль с чертежа, ч/шт"], 0.25)

    def test_inject_section5_criteria_note(self):
        text = "1. Маршрут\n\n4. Контроль"
        quote = {
            "Партия, шт": 1,
            "Время на 1 деталь, ч": 2,
            "Время на партию, ч": 2,
            "Критерии чертежа (Sinlex)": "Ra 1.6, шпон. паз",
        }
        out = inject_tech_card_section5(text, quote)
        self.assertIn("Учтены критерии чертежа", out)
        self.assertIn("Ra 1.6", out)


if __name__ == "__main__":
    unittest.main()
