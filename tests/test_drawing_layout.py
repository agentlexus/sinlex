"""Тесты drawing_analysis.layout (этап 3 TZ)."""

import unittest
from unittest.mock import MagicMock, patch

from drawing_analysis import config
from drawing_analysis.layout import (
    classify_word_to_zone,
    guess_designation_from_title,
    layout_page_from_image,
)
from drawing_analysis.parser import merge_fields_with_layout, parse_drawing_text_to_fields


class TestClassifyZone(unittest.TestCase):
    def test_title_block_bottom_right(self):
        zone = classify_word_to_zone((0.82, 0.88, 0.95, 0.95), "ЭПЛВФ.306569.004")
        self.assertEqual(zone, "title_block")

    def test_notes_top_left(self):
        zone = classify_word_to_zone((0.1, 0.1, 0.2, 0.15), "Примечание 1")
        self.assertEqual(zone, "notes")

    def test_dimension_area_pattern(self):
        zone = classify_word_to_zone((0.5, 0.5, 0.6, 0.55), "2×Ø6.4")
        self.assertEqual(zone, "dimension_area")


class TestGuessDesignation(unittest.TestCase):
    def test_decimal_designation(self):
        text = "Обозначение\nЭПЛВФ.306569.004.002\nМатериал Сталь"
        self.assertIn("ЭПЛВФ", guess_designation_from_title(text))


class TestMergeFieldsWithLayout(unittest.TestCase):
    def test_fallback_without_zones(self):
        full = "Материал: Сталь 45\nНаименование: Педаль"
        merged = merge_fields_with_layout(full, {})
        self.assertEqual(merged["material"], "Сталь 45")
        self.assertEqual(merged.get("fields_source"), "full_text")

    def test_title_block_overrides_designation(self):
        full = "размытый текст без полей"
        zones = {
            "title_block": "Обозначение: ЭПЛВФ.306569.004.002\nНаименование: Педаль",
            "notes": "",
            "dimension_area": "",
            "other": "",
        }
        merged = merge_fields_with_layout(full, zones)
        self.assertEqual(merged["designation"], "ЭПЛВФ.306569.004.002")
        self.assertEqual(merged["name"], "Педаль")
        self.assertEqual(merged.get("fields_source"), "layout")

    def test_full_text_fallback_fields(self):
        """Без зон — как этап 1."""
        text = "Материал: Алюминий"
        a = parse_drawing_text_to_fields(text)
        b = merge_fields_with_layout(text, {})
        self.assertEqual(a["material"], b["material"])


class TestLayoutPageMock(unittest.TestCase):
    @patch("pytesseract.image_to_data")
    def test_layout_page_groups_zones(self, mock_data):
        import pytesseract

        mock_data.return_value = {
            "text": ["ЭПЛВФ.306569", "2×Ø6.4", "Примечание"],
            "conf": ["90", "90", "90"],
            "left": [800, 400, 50],
            "top": [900, 500, 50],
            "width": [120, 80, 100],
            "height": [20, 20, 20],
            "block_num": [1, 1, 1],
            "par_num": [1, 1, 1],
            "line_num": [1, 2, 3],
            "page_num": [1, 1, 1],
        }
        pytesseract.Output.DICT = "dict"

        image = MagicMock()
        image.width = 1000
        image.height = 1200

        result = layout_page_from_image(image)
        self.assertTrue(result["ok"] or result["word_count"] > 0)
        self.assertIn("title_block", result["zones"])


class TestExtractTextFromPdfLayout(unittest.TestCase):
    @patch.object(config, "ENABLE_LAYOUT", True)
    @patch("drawing_analysis.reader.CascadeReader.extract_per_page")
    @patch("drawing_analysis.reader._pdf_page_count", return_value=1)
    @patch("drawing_analysis.layout.extract_layout_from_pdf")
    def test_layout_in_result(self, mock_layout, mock_count, mock_extract):
        from drawing_analysis.reader import extract_text_from_pdf

        mock_extract.return_value = (
            [{"page": 1, "method": "pdftotext", "text": "Материал: X", "char_count": 10}],
            [],
        )
        mock_layout.return_value = {
            "ok": True,
            "pages": [{"page": 1, "ok": True, "zones": {}}],
            "merged_zones": {
                "title_block": "Обозначение: ABC.001",
                "notes": "",
                "dimension_area": "",
                "other": "",
            },
            "method": "tesseract_data",
        }
        result = extract_text_from_pdf(b"pdf")
        self.assertIn("layout", result)
        self.assertEqual(result["fields"].get("designation"), "ABC.001")
        self.assertEqual(result["fields"].get("fields_source"), "layout")


if __name__ == "__main__":
    unittest.main()
