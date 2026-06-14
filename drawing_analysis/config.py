"""Настройки пайплайна извлечения текста из чертежей."""

import os

DRAWING_PIPELINE_VERSION = int(os.environ.get("SINLEX_DRAWING_PIPELINE_VERSION", "4"))
MAX_PAGES = int(os.environ.get("SINLEX_DRAWING_MAX_PAGES", "5"))
ENABLE_LAYOUT = os.environ.get("SINLEX_DRAWING_ENABLE_LAYOUT", "1").strip().lower() in (
    "1",
    "true",
    "yes",
)
# Нормализованные bbox зон (x0, y0, x1, y1) — этап 3 TZ
TITLE_BLOCK_BBOX = (0.75, 0.80, 1.0, 1.0)
NOTES_BBOX = (0.0, 0.0, 0.55, 0.35)
OCR_DPI = int(os.environ.get("SINLEX_DRAWING_OCR_DPI", "150"))
OCR_ENGINE = os.environ.get("SINLEX_DRAWING_OCR_ENGINE", "tesseract").strip().lower()
MIN_TEXT_CHARS = int(os.environ.get("SINLEX_DRAWING_MIN_TEXT_CHARS", "40"))
MIN_PAGE_CHARS = int(os.environ.get("SINLEX_DRAWING_MIN_PAGE_CHARS", str(MIN_TEXT_CHARS)))
OCR_TIMEOUT_SEC = int(os.environ.get("SINLEX_DRAWING_OCR_TIMEOUT", "120"))
ENABLE_PADDLE = os.environ.get("SINLEX_DRAWING_ENABLE_PADDLE", "0").strip().lower() in (
    "1",
    "true",
    "yes",
)
FULL_TEXT_MAX_CHARS = 50_000
TEXT_PREVIEW_MAX_CHARS = 200


def effective_ocr_engine() -> str:
    """Движок OCR для fallback: без ENABLE_PADDLE — только tesseract (этап 0)."""
    if not ENABLE_PADDLE:
        return "tesseract"
    engine = OCR_ENGINE
    if engine in ("paddle", "paddleocr"):
        return "paddle"
    if engine == "easyocr":
        return "easyocr"
    return "tesseract"
