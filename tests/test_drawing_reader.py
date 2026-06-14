"""Smoke-тесты drawing_analysis.reader (этапы 0–2 TZ)."""

import unittest
from unittest.mock import MagicMock, patch

from drawing_analysis import config
from drawing_analysis.reader import CascadeReader, extract_text_per_page, merge_pages


class TestMergePages(unittest.TestCase):
    def test_sheet_markers(self):
        pages = [
            {"page": 1, "method": "pdftotext", "text": "Лист один", "char_count": 9},
            {"page": 2, "method": "pdftotext", "text": "Лист два", "char_count": 8},
            {"page": 3, "method": "tesseract", "text": "Лист три", "char_count": 8},
        ]
        full = merge_pages(pages)
        self.assertIn("--- Лист 1 ---", full)
        self.assertIn("--- Лист 2 ---", full)
        self.assertIn("--- Лист 3 ---", full)
        self.assertIn("Лист один", full)
        self.assertIn("Лист три", full)


class TestEffectiveOcrEngine(unittest.TestCase):
    @patch.object(config, "ENABLE_PADDLE", False)
    @patch.object(config, "OCR_ENGINE", "paddle")
    def test_paddle_disabled_uses_tesseract(self):
        self.assertEqual(config.effective_ocr_engine(), "tesseract")

    @patch.object(config, "ENABLE_PADDLE", True)
    @patch.object(config, "OCR_ENGINE", "paddleocr")
    def test_paddle_enabled(self):
        self.assertEqual(config.effective_ocr_engine(), "paddle")


class TestExtractTextPerPage(unittest.TestCase):
    @patch("drawing_analysis.reader._pdf_page_count", return_value=3)
    @patch(
        "drawing_analysis.reader._pdftotext_page",
        side_effect=lambda _b, p: f"достаточно длинный текст страницы {p} для pdftotext",
    )
    @patch("drawing_analysis.reader._ocr_page")
    def test_pdftotext_all_pages(self, mock_ocr, mock_pdf, mock_count):
        pages = extract_text_per_page(b"%PDF-fake")
        self.assertEqual(len(pages), 3)
        self.assertEqual(pages[0]["page"], 1)
        self.assertEqual(pages[0]["method"], "pdftotext")
        mock_ocr.assert_not_called()
        full = merge_pages(pages)
        self.assertIn("--- Лист 3 ---", full)

    @patch("drawing_analysis.reader._pdf_page_count", return_value=2)
    @patch("drawing_analysis.reader._pdftotext_page", return_value="x")
    @patch(
        "drawing_analysis.reader._ocr_page",
        return_value=("OCR fallback text here enough", "tesseract"),
    )
    def test_tesseract_fallback_short_page(self, *_mocks):
        pages = extract_text_per_page(b"%PDF-fake")
        self.assertEqual(pages[0]["method"], "tesseract")
        self.assertGreater(pages[0]["char_count"], 10)

    @patch.object(config, "ENABLE_PADDLE", True)
    @patch("drawing_analysis.reader._pdf_page_count", return_value=1)
    @patch("drawing_analysis.reader._pdftotext_page", return_value="")
    @patch(
        "drawing_analysis.reader._ocr_page",
        return_value=("paddle ocr text long enough for test", "paddle"),
    )
    @patch.object(config, "effective_ocr_engine", return_value="paddle")
    def test_paddle_engine_when_enabled(self, *_mocks):
        reader = CascadeReader()
        self.assertEqual(reader.ocr_engine, "paddle")
        pages, warnings = reader.extract_per_page(b"%PDF-fake")
        self.assertEqual(pages[0]["method"], "paddle")
        self.assertEqual(warnings, [])


class TestCascadeTimeout(unittest.TestCase):
    @patch("drawing_analysis.reader._pdf_page_count", return_value=5)
    @patch("drawing_analysis.reader._pdftotext_page", return_value="x")
    @patch(
        "drawing_analysis.reader._ocr_page",
        return_value=("OCR fallback text here enough chars", "tesseract"),
    )
    def test_ocr_timeout_warning(self, *_mocks):
        reader = CascadeReader(timeout_sec=0)
        pages, warnings = reader.extract_per_page(b"%PDF-fake")
        self.assertIn("ocr_timeout", warnings)
        self.assertLess(len(pages), 5)


class TestExtractTextFromPdf(unittest.TestCase):
    @patch("drawing_analysis.reader.CascadeReader.extract_per_page")
    @patch("drawing_analysis.reader._pdf_page_count", return_value=8)
    def test_result_shape(self, mock_count, mock_extract):
        from drawing_analysis.reader import extract_text_from_pdf

        mock_extract.return_value = (
            [{"page": 1, "method": "pdftotext", "text": "Материал: Сталь", "char_count": 14}],
            ["processed_first_5_of_8"],
        )
        result = extract_text_from_pdf(b"pdf-bytes")
        self.assertEqual(result["version"], 1)
        self.assertEqual(result["page_count"], 8)
        self.assertEqual(result["pages_processed"], 1)
        self.assertIn("fields", result)
        self.assertIn("ocr_engine", result)
        self.assertIn("--- Лист 1 ---", result["full_text"])
        self.assertTrue(any("processed_first" in w for w in result["warnings"]))


if __name__ == "__main__":
    unittest.main()
