"""Чтение чертежей «Поток»: PDF и растровые форматы."""

from __future__ import annotations

import hashlib
import io
import logging
import os
from typing import Any, Dict, Tuple

LOG = logging.getLogger("flow_drawing_io")

FLOW_DRAWING_EXTENSIONS = frozenset({".pdf", ".png", ".jpg", ".jpeg"})
FLOW_UPLOAD_TYPES = ["pdf", "png", "jpg", "jpeg"]


def safe_drawing_filename(name: str) -> str:
    base = os.path.basename((name or "drawing.pdf").strip())
    if not base or ".." in base or "/" in base or "\\" in base:
        return "drawing.pdf"
    ext = os.path.splitext(base)[1].lower()
    if ext not in FLOW_DRAWING_EXTENSIONS:
        return base + (".pdf" if not ext else "")
    return base


def drawing_mime_type(filename: str) -> Tuple[str, str]:
    ext = os.path.splitext(filename or "")[1].lower()
    if ext == ".pdf":
        return "application", "pdf"
    if ext == ".png":
        return "image", "png"
    if ext in (".jpg", ".jpeg"):
        return "image", "jpeg"
    return "application", "octet-stream"


def is_pdf(filename: str) -> bool:
    return os.path.splitext(filename or "")[1].lower() == ".pdf"


def drawing_hash(file_bytes: bytes) -> str:
    return hashlib.sha256(file_bytes).hexdigest()


def _ocr_image_bytes(image_bytes: bytes) -> str:
    try:
        from PIL import Image

        import numpy as np

        from drawing_analysis.config import effective_ocr_engine

        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        arr = np.array(img)
        engine = effective_ocr_engine()
        if engine == "easyocr":
            import easyocr

            reader = easyocr.Reader(["ru", "en"], gpu=False, verbose=False)
            parts = [t[1] for t in reader.readtext(arr) if t and len(t) > 1 and t[1]]
            return "\n".join(parts)
        if engine == "paddle":
            from paddleocr import PaddleOCR

            ocr = PaddleOCR(use_angle_cls=True, lang="ru", show_log=False)
            result = ocr.ocr(arr, cls=True)
            lines = []
            if result and result[0]:
                for line in result[0]:
                    if line and len(line) > 1 and line[1]:
                        lines.append(line[1][0])
            return "\n".join(lines)
        import pytesseract

        return pytesseract.image_to_string(img, lang="rus+eng") or ""
    except Exception as exc:
        LOG.warning("image OCR failed: %s", exc)
        return ""


def extract_text_from_drawing(file_bytes: bytes, filename: str) -> Dict[str, Any]:
    """Единый формат как extract_text_from_pdf для job auto_extraction."""
    fname = safe_drawing_filename(filename)
    if is_pdf(fname):
        from drawing_analysis.reader import extract_text_from_pdf

        out = extract_text_from_pdf(file_bytes)
        out["source_format"] = "pdf"
        return out

    text = _ocr_image_bytes(file_bytes)
    return {
        "version": 1,
        "pdf_hash": drawing_hash(file_bytes),
        "page_count": 1,
        "pages_processed": 1,
        "extraction_method": "image_ocr",
        "ocr_engine": "image",
        "per_page": [
            {
                "page": 1,
                "method": "image_ocr",
                "char_count": len(text),
                "text_preview": text[:500],
            }
        ],
        "full_text": text,
        "layout": {"ok": False, "pages": [], "merged_zones": {}},
        "fields": {"fields_source": "full_text"},
        "parsed_dimensions": {},
        "warnings": [],
        "source_format": os.path.splitext(fname)[1].lstrip("."),
    }


def flow_data_md_path(drawing_path: str) -> str:
    """flow_data.md рядом с файлом чертежа (stem.flow_data.md)."""
    base, _ext = os.path.splitext(drawing_path)
    return f"{base}.flow_data.md"
