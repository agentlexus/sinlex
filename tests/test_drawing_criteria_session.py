"""Тесты синхронизации критериев с PDF hash (CR-3 TZ)."""

import unittest

from drawing_analysis.manufacturing_criteria import criteria_applies_to_pdf


class TestCriteriaAppliesToPdf(unittest.TestCase):
    def test_empty_codes(self):
        c = {"pdf_hash": "abc", "active_codes": [], "modifiers": {}}
        self.assertFalse(criteria_applies_to_pdf(c, "abc", "abc"))

    def test_matching_hash(self):
        c = {
            "pdf_hash": "abc",
            "active_codes": ["ra_finish_16"],
            "modifiers": {"cutting_mult": 1.15},
        }
        self.assertTrue(criteria_applies_to_pdf(c, "abc", "abc"))

    def test_pdf_changed(self):
        c = {"pdf_hash": "old", "active_codes": ["keyway"], "modifiers": {}}
        self.assertFalse(criteria_applies_to_pdf(c, "new", "new"))

    def test_no_analysis_hash(self):
        c = {"pdf_hash": "abc", "active_codes": ["threaded_hole"], "modifiers": {}}
        self.assertFalse(criteria_applies_to_pdf(c, "abc", None))


if __name__ == "__main__":
    unittest.main()
