"""Грубая разметка зон чертежа (штамп, примечания, размеры) по координатам OCR."""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Tuple, TypedDict

from drawing_analysis import config

logger = logging.getLogger(__name__)

ZoneName = str  # title_block | notes | dimension_area | other

_DIM_HINT = re.compile(
    r"[ØøOoФф]|\d+[.,]\d+|\d+\s*[xх×]\s*\d+",
    re.IGNORECASE,
)
_DESIGNATION_HINT = re.compile(
    r"[A-ZА-ЯЁ][A-ZА-ЯЁ0-9.\-_]{4,}",
    re.UNICODE,
)


class ZoneTexts(TypedDict):
    title_block: str
    notes: str
    dimension_area: str
    other: str


class PageLayout(TypedDict):
    page: int
    ok: bool
    method: str
    zones: ZoneTexts
    word_count: int


def _norm_bbox(
    left: int,
    top: int,
    width: int,
    height: int,
    page_w: int,
    page_h: int,
) -> Tuple[float, float, float, float]:
    if page_w <= 0 or page_h <= 0:
        return (0.0, 0.0, 0.0, 0.0)
    x0 = left / page_w
    y0 = top / page_h
    x1 = (left + width) / page_w
    y1 = (top + height) / page_h
    return (x0, y0, x1, y1)


def _center_in_zone(cx: float, cy: float, zone: Tuple[float, float, float, float]) -> bool:
    zx0, zy0, zx1, zy1 = zone
    return zx0 <= cx <= zx1 and zy0 <= cy <= zy1


def _overlap_ratio(
    bbox: Tuple[float, float, float, float],
    zone: Tuple[float, float, float, float],
) -> float:
    bx0, by0, bx1, by1 = bbox
    zx0, zy0, zx1, zy1 = zone
    ix0 = max(bx0, zx0)
    iy0 = max(by0, zy0)
    ix1 = min(bx1, zx1)
    iy1 = min(by1, zy1)
    if ix1 <= ix0 or iy1 <= iy0:
        return 0.0
    inter = (ix1 - ix0) * (iy1 - iy0)
    box_area = max((bx1 - bx0) * (by1 - by0), 1e-9)
    return inter / box_area


def classify_word_to_zone(
    bbox: Tuple[float, float, float, float],
    text: str,
) -> ZoneName:
    """Классификация слова/строки в зону v1 (нормализованные координаты 0..1)."""
    cx = (bbox[0] + bbox[2]) / 2
    cy = (bbox[1] + bbox[3]) / 2
    title = config.TITLE_BLOCK_BBOX
    notes = config.NOTES_BBOX

    if _overlap_ratio(bbox, title) >= 0.35 or _center_in_zone(cx, cy, title):
        return "title_block"
    if _overlap_ratio(bbox, notes) >= 0.35 or _center_in_zone(cx, cy, notes):
        return "notes"
    if _DIM_HINT.search(text or ""):
        return "dimension_area"
    return "other"


def _group_lines_from_tesseract_data(data: Dict[str, List]) -> List[Dict[str, Any]]:
    """Группирует слова Tesseract image_to_data в строки."""
    n = len(data.get("text", []))
    lines_map: Dict[Tuple[int, int, int], List[int]] = {}
    for i in range(n):
        text = (data["text"][i] or "").strip()
        if not text:
            continue
        try:
            conf = int(float(data["conf"][i]))
        except (TypeError, ValueError):
            conf = -1
        if conf < 0:
            continue
        key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        lines_map.setdefault(key, []).append(i)

    lines: List[Dict[str, Any]] = []
    for indices in lines_map.values():
        words = []
        for i in indices:
            words.append(
                {
                    "text": (data["text"][i] or "").strip(),
                    "left": int(data["left"][i]),
                    "top": int(data["top"][i]),
                    "width": int(data["width"][i]),
                    "height": int(data["height"][i]),
                }
            )
        if not words:
            continue
        left = min(w["left"] for w in words)
        top = min(w["top"] for w in words)
        right = max(w["left"] + w["width"] for w in words)
        bottom = max(w["top"] + w["height"] for w in words)
        line_text = " ".join(w["text"] for w in words if w["text"])
        lines.append(
            {
                "text": line_text,
                "left": left,
                "top": top,
                "width": right - left,
                "height": bottom - top,
            }
        )
    return lines


def layout_page_from_image(image) -> PageLayout:
    """Разметка одной страницы по image_to_data (Tesseract)."""
    empty_zones: ZoneTexts = {
        "title_block": "",
        "notes": "",
        "dimension_area": "",
        "other": "",
    }
    try:
        import pytesseract

        data = pytesseract.image_to_data(
            image,
            lang="rus+eng",
            output_type=pytesseract.Output.DICT,
        )
    except Exception as exc:
        logger.debug("layout image_to_data failed: %s", exc)
        return {
            "page": 0,
            "ok": False,
            "method": "tesseract_data",
            "zones": empty_zones,
            "word_count": 0,
        }

    page_w = max(int(max(data.get("width", [0]) or [0])), image.width)
    page_h = max(int(max(data.get("height", [0]) or [0])), image.height)
    zone_lines: Dict[ZoneName, List[str]] = {
        "title_block": [],
        "notes": [],
        "dimension_area": [],
        "other": [],
    }
    word_count = 0

    for line in _group_lines_from_tesseract_data(data):
        text = line["text"]
        if not text:
            continue
        word_count += len(text.split())
        bbox = _norm_bbox(
            line["left"],
            line["top"],
            line["width"],
            line["height"],
            page_w,
            page_h,
        )
        zone = classify_word_to_zone(bbox, text)
        zone_lines[zone].append(text)

    zones: ZoneTexts = {
        "title_block": "\n".join(zone_lines["title_block"]).strip(),
        "notes": "\n".join(zone_lines["notes"]).strip(),
        "dimension_area": "\n".join(zone_lines["dimension_area"]).strip(),
        "other": "\n".join(zone_lines["other"]).strip(),
    }
    ok = bool(zones["title_block"] or zones["notes"] or word_count >= 3)
    return {
        "page": 0,
        "ok": ok,
        "method": "tesseract_data",
        "zones": zones,
        "word_count": word_count,
    }


def _pdf_page_count(pdf_bytes: bytes) -> int:
    try:
        from pdf2image import pdfinfo_from_bytes

        info = pdfinfo_from_bytes(pdf_bytes)
        return max(1, int(info.get("Pages", 1)))
    except Exception:
        return 1


def _page_image(pdf_bytes: bytes, page: int):
    from pdf2image import convert_from_bytes

    pages = convert_from_bytes(
        pdf_bytes,
        dpi=config.OCR_DPI,
        fmt="png",
        first_page=page,
        last_page=page,
    )
    return pages[0] if pages else None


def extract_layout_from_pdf(
    pdf_bytes: bytes,
    page_numbers: Optional[List[int]] = None,
) -> Dict[str, Any]:
    """
    Извлекает зоны по страницам PDF.
    Возвращает {ok, pages: [PageLayout], merged_zones: ZoneTexts}.
    """
    merged: ZoneTexts = {
        "title_block": "",
        "notes": "",
        "dimension_area": "",
        "other": "",
    }
    if not pdf_bytes:
        return {"ok": False, "pages": [], "merged_zones": merged, "method": "none"}

    total = _pdf_page_count(pdf_bytes)
    if page_numbers is None:
        limit = min(total, config.MAX_PAGES)
        page_numbers = list(range(1, limit + 1))

    page_layouts: List[PageLayout] = []
    for page in page_numbers:
        image = _page_image(pdf_bytes, page)
        if image is None:
            continue
        pl = layout_page_from_image(image)
        pl["page"] = page
        page_layouts.append(pl)
        for zone in ("title_block", "notes", "dimension_area", "other"):
            chunk = pl["zones"].get(zone, "")
            if chunk:
                if merged[zone]:
                    merged[zone] += "\n"
                merged[zone] += chunk

    ok = any(p.get("ok") for p in page_layouts) and bool(
        merged["title_block"] or merged["notes"] or merged["dimension_area"]
    )
    return {
        "ok": ok,
        "pages": page_layouts,
        "merged_zones": merged,
        "method": "tesseract_data",
    }


def guess_designation_from_title(title_text: str) -> str:
    """Эвристика обозначения в штампе без метки «Обозначение»."""
    if not title_text:
        return ""
    for line in title_text.split("\n"):
        line = line.strip()
        if not line or len(line) < 5:
            continue
        lower = line.lower()
        if any(
            skip in lower
            for skip in (
                "материал",
                "масса",
                "масштаб",
                "лист",
                "разраб",
                "пров",
                "утв",
                "наименование",
            )
        ):
            continue
        m = _DESIGNATION_HINT.search(line)
        if m:
            return m.group(0).strip()
        if re.search(r"\d{3,}", line) and "." in line:
            return line
    return ""
