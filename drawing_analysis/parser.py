"""Разбор текста чертежа в структурированные поля и размеры."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

_DIAM_SYMBOL = r"[ØøOoФф]"
_NUM = r"(\d+[.,]\d+|\d+)"
_DIM_COUNT = re.compile(
    rf"(?P<count>\d+)\s*(?:[×xхX\-]|отв\.?)\s*{_DIAM_SYMBOL}\s*{_NUM}",
    re.IGNORECASE,
)
_DIM_SINGLE = re.compile(
    rf"{_DIAM_SYMBOL}\s*{_NUM}",
    re.IGNORECASE,
)
_ROUGHNESS = re.compile(
    r"(?:Ra|Rz)\s*(\d+[.,]?\d*)|шероховатост[ьи]\s*[:\s]*(\d+[.,]?\d*)",
    re.IGNORECASE,
)
_GABARIT = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*[xх×]\s*(\d+(?:[.,]\d+)?)(?:\s*[xх×]\s*(\d+(?:[.,]\d+)?))?",
    re.IGNORECASE,
)


def _parse_mm_number(raw: str) -> Optional[float]:
    if not raw:
        return None
    try:
        return float(raw.replace(",", "."))
    except ValueError:
        return None


def parse_dimensions_from_text(text: str) -> List[Dict[str, Any]]:
    """
    Извлекает размеры из текста чертежа (regex v1).
    Возвращает список dict: raw, kind, value_mm, count_hint, page.
    """
    if not text:
        return []
    results: List[Dict[str, Any]] = []
    seen_spans: List[tuple] = []

    def _add(raw: str, value_mm: float, count_hint: int, start: int, end: int) -> None:
        for s0, s1 in seen_spans:
            if start >= s0 and end <= s1:
                return
        seen_spans.append((start, end))
        results.append(
            {
                "raw": raw.strip(),
                "kind": "diameter",
                "value_mm": value_mm,
                "count_hint": count_hint,
                "page": None,
            }
        )

    for m in _DIM_COUNT.finditer(text):
        count = int(m.group("count"))
        val = _parse_mm_number(m.group(2))
        if val is None:
            continue
        _add(m.group(0), val, count, m.start(), m.end())

    for m in _DIM_SINGLE.finditer(text):
        if any(m.start() >= s0 and m.end() <= s1 for s0, s1 in seen_spans):
            continue
        val = _parse_mm_number(m.group(1))
        if val is None:
            continue
        _add(m.group(0), val, 1, m.start(), m.end())

    for m in _GABARIT.finditer(text):
        nums = [m.group(1), m.group(2)]
        if m.group(3):
            nums.append(m.group(3))
        vals = [_parse_mm_number(n) for n in nums]
        if not all(v is not None for v in vals):
            continue
        raw = m.group(0)
        if any(raw in r.get("raw", "") for r in results):
            continue
        results.append(
            {
                "raw": raw.strip(),
                "kind": "gabarit",
                "value_mm": vals[0],
                "values_mm": vals,
                "count_hint": 1,
                "page": None,
            }
        )

    return results


def _collect_roughness(text: str, lines: List[str]) -> List[str]:
    found: List[str] = []
    for m in _ROUGHNESS.finditer(text):
        val = m.group(1) or m.group(2)
        if val:
            label = m.group(0).strip()
            if label not in found:
                found.append(label)
    for line in lines:
        lower = line.lower()
        if "шероховатость" in lower or re.search(r"\bra\s*\d", lower):
            parts = line.split(":", 1) if ":" in line else [line]
            chunk = parts[-1].strip() if len(parts) > 1 else line.strip()
            if chunk and chunk not in found:
                found.append(chunk)
    return found


def parse_drawing_text_to_fields(text: str) -> Dict[str, Any]:
    """Разбор текста чертежа в поля (общий для pdftotext и Tesseract)."""
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    result: Dict[str, Any] = {
        "designation": "неразборчиво",
        "name": "неразборчиво",
        "material": "неразборчиво",
        "mass": "неразборчиво",
        "dimensions": "неразборчиво",
        "dimensions_text": "неразборчиво",
        "tolerances": "неразборчиво",
        "roughness": [],
        "requirements": [],
        "notes": "",
    }
    for line in lines:
        lower = line.lower()
        if "обозначение" in lower or "децимальный" in lower:
            parts = line.split(":", 1) if ":" in line else line.split(" ", 1)
            if len(parts) > 1:
                result["designation"] = parts[1].strip()
        elif "наименование" in lower and result["name"] == "неразборчиво":
            parts = line.split(":", 1) if ":" in line else line.split(" ", 1)
            if len(parts) > 1:
                result["name"] = parts[1].strip()
        elif "материал" in lower:
            parts = line.split(":", 1) if ":" in line else line.split(" ", 1)
            if len(parts) > 1:
                result["material"] = parts[1].strip()
        elif "масса" in lower:
            parts = line.split(":", 1) if ":" in line else line.split(" ", 1)
            if len(parts) > 1:
                result["mass"] = parts[1].strip()
        elif "размер" in lower or "габарит" in lower:
            parts = line.split(":", 1) if ":" in line else line.split(" ", 1)
            if len(parts) > 1:
                val = parts[1].strip()
                result["dimensions"] = val
                result["dimensions_text"] = val
        elif "допуск" in lower or "квалитет" in lower:
            parts = line.split(":", 1) if ":" in line else line.split(" ", 1)
            if len(parts) > 1:
                result["tolerances"] = parts[1].strip()
        elif "требование" in lower or "требования" in lower:
            parts = line.split(":", 1) if ":" in line else line.split(" ", 1)
            if len(parts) > 1:
                result["requirements"].append(parts[1].strip())

    gabarits = [d["raw"] for d in parse_dimensions_from_text(text) if d.get("kind") == "gabarit"]
    if gabarits and result["dimensions_text"] == "неразборчиво":
        result["dimensions_text"] = "; ".join(gabarits[:3])
        result["dimensions"] = result["dimensions_text"]

    roughness = _collect_roughness(text, lines)
    if roughness:
        result["roughness"] = roughness
    elif any("ra" in ln.lower() or "шероховатость" in ln.lower() for ln in lines):
        result["roughness"] = ["неразборчиво"]

    scalar_keys = ("designation", "name", "material", "mass", "dimensions_text", "tolerances")
    if all(result.get(k) == "неразборчиво" for k in scalar_keys) and not result["requirements"]:
        result["raw_text"] = text[:2000]
    return result


_UNREADABLE = "неразборчиво"
_FIELD_KEYS = (
    "designation",
    "name",
    "material",
    "mass",
    "dimensions",
    "dimensions_text",
    "tolerances",
)


def _is_filled(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, list):
        return len(value) > 0
    if isinstance(value, str):
        return bool(value.strip()) and value.strip() != _UNREADABLE
    return bool(value)


def merge_fields_with_layout(
    full_text: str,
    merged_zones: Dict[str, str],
) -> Dict[str, Any]:
    """
    Парсит full_text и зоны layout; приоритет у штампа для полей основной надписи.
    При пустом layout — результат как parse_drawing_text_to_fields(full_text).
    """
    base = parse_drawing_text_to_fields(full_text or "")
    title = (merged_zones or {}).get("title_block", "").strip()
    notes = (merged_zones or {}).get("notes", "").strip()
    dim_area = (merged_zones or {}).get("dimension_area", "").strip()

    if not title and not notes and not dim_area:
        base["fields_source"] = "full_text"
        return base

    from drawing_analysis.layout import guess_designation_from_title

    title_fields = parse_drawing_text_to_fields(title) if title else {}
    notes_fields = parse_drawing_text_to_fields(notes) if notes else {}
    dim_fields = parse_drawing_text_to_fields(dim_area) if dim_area else {}

    for key in _FIELD_KEYS:
        for zone_fields in (title_fields, notes_fields, dim_fields):
            val = zone_fields.get(key)
            if _is_filled(val):
                base[key] = val
                break

    if not _is_filled(base.get("designation")):
        guessed = guess_designation_from_title(title)
        if guessed:
            base["designation"] = guessed

    if notes and not base.get("notes"):
        base["notes"] = notes[:2000]

    if dim_area:
        dim_dims = parse_dimensions_from_text(dim_area)
        if dim_dims and base.get("dimensions_text") == _UNREADABLE:
            gab = [d["raw"] for d in dim_dims if d.get("kind") == "gabarit"]
            diam = [d["raw"] for d in dim_dims if d.get("kind") == "diameter"]
            parts = (gab or diam)[:5]
            if parts:
                base["dimensions_text"] = "; ".join(parts)
                base["dimensions"] = base["dimensions_text"]

    rough = _collect_roughness(
        "\n".join(filter(None, [title, notes, dim_area, full_text])),
        [],
    )
    if rough and not base.get("roughness"):
        base["roughness"] = rough

    base["fields_source"] = "layout"
    return base
