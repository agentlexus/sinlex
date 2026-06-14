"""Мультистраничное извлечение текста из PDF (pdftotext → каскад OCR)."""

from __future__ import annotations

import hashlib
import logging
import os
import subprocess
import tempfile
import time
from typing import Any, Dict, List, Optional, Tuple, TypedDict

from drawing_analysis import config
from drawing_analysis.parser import (
    merge_fields_with_layout,
    parse_dimensions_from_text,
    parse_drawing_text_to_fields,
)

logger = logging.getLogger(__name__)

_PADDLE_OCR = None
_EASYOCR_READER = None


class PageText(TypedDict):
    page: int
    method: str
    text: str
    char_count: int


def _pdf_page_count(pdf_bytes: bytes) -> int:
    try:
        from pdf2image import pdfinfo_from_bytes

        info = pdfinfo_from_bytes(pdf_bytes)
        return max(1, int(info.get("Pages", 1)))
    except Exception:
        return 1


def _pdftotext_page(pdf_bytes: bytes, page: int) -> str:
    tmp_path = ""
    try:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(pdf_bytes)
            tmp_path = tmp.name
        result = subprocess.run(
            ["pdftotext", "-layout", "-f", str(page), "-l", str(page), tmp_path, "-"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0 and result.stdout:
            return result.stdout
    except Exception:
        pass
    finally:
        if tmp_path and os.path.isfile(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
    return ""


def _page_image(pdf_bytes: bytes, page: int):
    from pdf2image import convert_from_bytes

    pages = convert_from_bytes(
        pdf_bytes,
        dpi=config.OCR_DPI,
        fmt="png",
        first_page=page,
        last_page=page,
    )
    if not pages:
        return None
    return pages[0]


def _tesseract_page(pdf_bytes: bytes, page: int) -> str:
    import pytesseract

    try:
        image = _page_image(pdf_bytes, page)
        if image is None:
            return ""
        return pytesseract.image_to_string(image, lang="rus+eng") or ""
    except Exception as exc:
        logger.debug("tesseract page %s failed: %s", page, exc)
        return ""


def _get_paddle_ocr():
    global _PADDLE_OCR
    if _PADDLE_OCR is None:
        from paddleocr import PaddleOCR

        _PADDLE_OCR = PaddleOCR(
            use_angle_cls=True,
            lang="ru",
            show_log=False,
            use_gpu=False,
        )
    return _PADDLE_OCR


def _paddle_page(pdf_bytes: bytes, page: int) -> str:
    try:
        import numpy as np

        image = _page_image(pdf_bytes, page)
        if image is None:
            return ""
        ocr = _get_paddle_ocr()
        result = ocr.ocr(np.array(image), cls=True)
        lines: List[str] = []
        for block in result or []:
            if not block:
                continue
            for line in block:
                if line and len(line) >= 2 and line[1]:
                    lines.append(str(line[1][0]))
        return "\n".join(lines)
    except Exception as exc:
        logger.warning("paddleocr page %s failed: %s", page, exc)
        return ""


def _get_easyocr_reader():
    global _EASYOCR_READER
    if _EASYOCR_READER is None:
        import easyocr

        _EASYOCR_READER = easyocr.Reader(["ru", "en"], gpu=False, verbose=False)
    return _EASYOCR_READER


def _easyocr_page(pdf_bytes: bytes, page: int) -> str:
    try:
        import numpy as np

        image = _page_image(pdf_bytes, page)
        if image is None:
            return ""
        reader = _get_easyocr_reader()
        result = reader.readtext(np.array(image))
        return "\n".join(str(item[1]) for item in result if len(item) >= 2)
    except Exception as exc:
        logger.warning("easyocr page %s failed: %s", page, exc)
        return ""


def _ocr_page(pdf_bytes: bytes, page: int, engine: str) -> Tuple[str, str]:
    """OCR одной страницы; возвращает (текст, method)."""
    if engine == "paddle":
        return _paddle_page(pdf_bytes, page), "paddle"
    if engine == "easyocr":
        return _easyocr_page(pdf_bytes, page), "easyocr"
    return _tesseract_page(pdf_bytes, page), "tesseract"


class CascadeReader:
    """Каскад: pdftotext → OCR (tesseract | paddle | easyocr) при нехватке текста."""

    def __init__(
        self,
        *,
        min_page_chars: int = config.MIN_PAGE_CHARS,
        max_pages: int = config.MAX_PAGES,
        ocr_engine: Optional[str] = None,
        timeout_sec: int = config.OCR_TIMEOUT_SEC,
    ) -> None:
        self.min_page_chars = min_page_chars
        self.max_pages = max_pages
        self.ocr_engine = ocr_engine or config.effective_ocr_engine()
        self.timeout_sec = timeout_sec
        self._deadline: Optional[float] = None

    def _timed_out(self) -> bool:
        return self._deadline is not None and time.monotonic() >= self._deadline

    def _process_page(self, pdf_bytes: bytes, page: int) -> PageText:
        text = _pdftotext_page(pdf_bytes, page)
        method = "pdftotext"
        if len(text.strip()) < self.min_page_chars and not self._timed_out():
            ocr_text, ocr_method = _ocr_page(pdf_bytes, page, self.ocr_engine)
            if len(ocr_text.strip()) > len(text.strip()):
                text = ocr_text
                method = ocr_method
        char_count = len(text.strip())
        logger.info(
            "drawing page %s: method=%s chars=%s engine=%s",
            page,
            method,
            char_count,
            self.ocr_engine if method != "pdftotext" else "-",
        )
        return {
            "page": page,
            "method": method,
            "text": text,
            "char_count": char_count,
        }

    def extract_per_page(self, pdf_bytes: bytes) -> Tuple[List[PageText], List[str]]:
        page_count = _pdf_page_count(pdf_bytes)
        limit = min(page_count, self.max_pages)
        self._deadline = time.monotonic() + self.timeout_sec
        pages: List[PageText] = []
        warnings: List[str] = []

        for page in range(1, limit + 1):
            if self._timed_out():
                warnings.append("ocr_timeout")
                logger.warning(
                    "drawing OCR timeout after %ss at page %s/%s",
                    self.timeout_sec,
                    page,
                    limit,
                )
                break
            pages.append(self._process_page(pdf_bytes, page))

        if page_count > self.max_pages:
            warnings.append(f"processed_first_{self.max_pages}_of_{page_count}")

        return pages, warnings


def extract_text_per_page(pdf_bytes: bytes) -> List[PageText]:
    """Извлекает текст по страницам (каскад pdftotext → OCR)."""
    pages, _warnings = CascadeReader().extract_per_page(pdf_bytes)
    return pages


def merge_pages(pages: List[PageText]) -> str:
    """Склеивает страницы с маркерами «--- Лист N ---»."""
    parts: List[str] = []
    for p in pages:
        parts.append(f"\n--- Лист {p['page']} ---\n")
        parts.append(p["text"])
    full = "".join(parts)
    if len(full) > config.FULL_TEXT_MAX_CHARS:
        return full[: config.FULL_TEXT_MAX_CHARS]
    return full


def _extraction_method(pages: List[PageText]) -> str:
    methods = {p["method"] for p in pages}
    if len(methods) == 1:
        return methods.pop() if methods else "pdftotext"
    return "mixed"


def extract_text_from_pdf(pdf_bytes: bytes) -> Dict[str, Any]:
    """Полный результат извлечения (DrawingExtractionResult v1)."""
    reader = CascadeReader()
    pages, warnings = reader.extract_per_page(pdf_bytes)
    full_text = merge_pages(pages)
    page_count = _pdf_page_count(pdf_bytes)

    per_page = [
        {
            "page": p["page"],
            "method": p["method"],
            "char_count": p["char_count"],
            "text_preview": (p["text"] or "")[: config.TEXT_PREVIEW_MAX_CHARS],
        }
        for p in pages
    ]

    layout_result: Dict[str, Any] = {"ok": False, "pages": [], "merged_zones": {}}
    fields = parse_drawing_text_to_fields(full_text)
    if config.ENABLE_LAYOUT:
        try:
            from drawing_analysis.layout import extract_layout_from_pdf

            page_nums = [p["page"] for p in pages]
            layout_result = extract_layout_from_pdf(pdf_bytes, page_nums)
            if layout_result.get("ok"):
                fields = merge_fields_with_layout(
                    full_text,
                    layout_result.get("merged_zones") or {},
                )
            else:
                fields["fields_source"] = "full_text"
        except Exception as exc:
            logger.warning("drawing layout failed, fallback to full_text: %s", exc)
            warnings.append("layout_failed")
            fields["fields_source"] = "full_text"
    else:
        fields["fields_source"] = "full_text"

    return {
        "version": 1,
        "pdf_hash": hashlib.sha256(pdf_bytes).hexdigest(),
        "page_count": page_count,
        "pages_processed": len(pages),
        "extraction_method": _extraction_method(pages) if pages else "pdftotext",
        "ocr_engine": reader.ocr_engine,
        "per_page": per_page,
        "full_text": full_text,
        "layout": layout_result,
        "fields": fields,
        "parsed_dimensions": parse_dimensions_from_text(full_text),
        "warnings": warnings,
    }
