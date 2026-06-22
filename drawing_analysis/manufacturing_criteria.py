"""Детерминированные критерии изготовления из чертежа (без влияния LLM на Ø)."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Set

from drawing_analysis import criteria_config as cfg

_DIAM = r"[ØøOoФф]"
_NUM = r"\d+[.,]?\d*"

_RE_RA = re.compile(r"(?:Ra|Rz)\s*(\d+[.,]?\d*)", re.IGNORECASE)
_RE_H_QUAL = re.compile(r"\bH([6-9]|10|11)\b", re.IGNORECASE)
_RE_PM_TOL = re.compile(r"[±]\s*0?\.\d+", re.IGNORECASE)
_RE_DIAM_PM = re.compile(
    rf"{_DIAM}\s*{_NUM}\s*[+]\s*0?\.\d+",
    re.IGNORECASE,
)
_RE_DIAM_H = re.compile(
    rf"{_DIAM}\s*{_NUM}\s*H([6-9]|10|11)",
    re.IGNORECASE,
)
_RE_COUNTED_H = re.compile(
    rf"\d+\s*(?:[×xхX\-]|отв\.?)\s*{_DIAM}\s*{_NUM}\s*H([6-9]|10|11)",
    re.IGNORECASE,
)
_RE_THROUGH_TOL = re.compile(r"сквозн\w*\s+с\s+допуск", re.IGNORECASE)
_RE_TOL_NEAR_DIAM = re.compile(
    rf"{_DIAM}\s*{_NUM}[^.\n]{{0,40}}допуск",
    re.IGNORECASE,
)
_RE_THREAD_M = re.compile(
    r"\bM([3-9]|1[0-9]|2[0-4])(?:[×xхX\-]\s*[0-9]+(?:[.,][0-9]+)?)?",
    re.IGNORECASE,
)
_RE_THREAD_WORD = re.compile(r"резьб\w*", re.IGNORECASE)
_RE_KEYWAY = re.compile(r"шпоночн\w*|шпон\w*|(?:^|[^\w])паз(?:\s|\w|$)", re.IGNORECASE)
_RE_KEYWAY_WIDTH = re.compile(
    r"(?:шпоночн\w*\s+)?паз\s*(\d+[.,]?\d*)",
    re.IGNORECASE,
)
_RE_KEYWAY_WIDTH_ALT = re.compile(
    r"ширин\w*\s*(?:паз\w*)?\s*(\d+[.,]?\d*)",
    re.IGNORECASE,
)
_RE_DIAM = re.compile(_DIAM, re.IGNORECASE)


def _parse_float(raw: str) -> Optional[float]:
    try:
        return float(raw.replace(",", "."))
    except (TypeError, ValueError):
        return None


def _collect_text_sources(
    drawing_extraction: Optional[Dict[str, Any]],
    expert_text: str = "",
) -> str:
    parts: List[str] = []
    if drawing_extraction:
        ft = drawing_extraction.get("full_text") or ""
        if ft:
            parts.append(ft)
        fields = drawing_extraction.get("fields") or {}
        for key in ("roughness", "tolerances", "notes", "dimensions_text", "requirements"):
            val = fields.get(key)
            if isinstance(val, list):
                parts.extend(str(v) for v in val if v)
            elif val and str(val).strip() not in ("", "неразборчиво"):
                parts.append(str(val))
        for dim in drawing_extraction.get("parsed_dimensions") or []:
            raw = dim.get("raw")
            if raw:
                parts.append(str(raw))
    if expert_text:
        parts.append(expert_text[:4000])
    return "\n".join(parts)


def _parse_ra_values(text: str) -> List[float]:
    values: List[float] = []
    for m in _RE_RA.finditer(text):
        v = _parse_float(m.group(1))
        if v is not None and v > 0:
            values.append(v)
    for m in re.finditer(
        r"шероховатост[ьи]\s*[:\s]*(\d+[.,]?\d*)",
        text,
        re.IGNORECASE,
    ):
        v = _parse_float(m.group(1))
        if v is not None and v > 0:
            values.append(v)
    return sorted(set(values))


def _count_toleranced_holes(text: str) -> int:
    count = 0
    patterns = (
        _RE_COUNTED_H,
        _RE_DIAM_H,
        _RE_DIAM_PM,
        _RE_H_QUAL,
    )
    seen: Set[str] = set()
    for pat in patterns:
        for m in pat.finditer(text):
            span = m.group(0).strip()
            if span not in seen:
                seen.add(span)
                count += 1
    if _RE_THROUGH_TOL.search(text):
        count = max(count, 1)
    for m in _RE_TOL_NEAR_DIAM.finditer(text):
        span = m.group(0).strip()
        if span not in seen:
            seen.add(span)
            count += 1
    if _RE_PM_TOL.search(text) and _RE_DIAM.search(text):
        for m in _RE_DIAM_PM.finditer(text):
            span = m.group(0).strip()
            if span not in seen:
                seen.add(span)
                count += 1
    return count


def _count_threaded_holes(text: str) -> int:
    count = len(_RE_THREAD_M.findall(text))
    if _RE_THREAD_WORD.search(text):
        count = max(count, 1)
    return count


def _detect_keyway(text: str) -> tuple[bool, Optional[float]]:
    if not _RE_KEYWAY.search(text):
        return False, None
    width: Optional[float] = None
    for pat in (_RE_KEYWAY_WIDTH, _RE_KEYWAY_WIDTH_ALT):
        m = pat.search(text)
        if m:
            width = _parse_float(m.group(1))
            break
    if width is not None:
        if width < cfg.KEYWAY_WIDTH_MIN_MM or width > cfg.KEYWAY_WIDTH_MAX_MM:
            return True, width
        return True, width
    return True, None


def _build_modifiers(
    *,
    ra_finish_16: bool,
    ra_grinding: bool,
    hole_tolerance: bool,
    threaded_holes: int,
    keyway: bool,
) -> Dict[str, Any]:
    cut_mult = 1.0
    setup_mult = 1.0
    cam_mult = 1.0
    setup_add_h = 0.0
    measure_h = 0.0
    grind_price_mult = 1.0
    operations_add: List[str] = []
    thread_cam_add_h = 0.0
    keyway_cam_add_h = 0.0

    finish_pass = ra_finish_16 or hole_tolerance or keyway
    if finish_pass:
        cut_mult = cfg.CUT_MULT
        setup_mult = cfg.SETUP_MULT
        cam_mult = cfg.CAM_MULT
        setup_add_h = cfg.SETUP_ADD_H

    if hole_tolerance:
        measure_h = cfg.MEASURE_PER_PART_H

    if ra_grinding:
        grind_price_mult = cfg.GRIND_PRICE_MULT
        operations_add.append(cfg.GRINDING_OPERATION)
        setup_add_h += cfg.SETUP_ADD_H
        setup_mult = max(setup_mult, cfg.SETUP_MULT)

    if threaded_holes > 0:
        thread_cam_add_h = threaded_holes * cfg.THREAD_CAM_H
        if cam_mult == 1.0:
            cam_mult = cfg.CAM_MULT

    if keyway:
        keyway_cam_add_h = cfg.KEYWAY_CAM_H
        if cam_mult == 1.0:
            cam_mult = cfg.CAM_MULT

    return {
        "cutting_mult": cut_mult,
        "setup_mult": setup_mult,
        "cam_mult": cam_mult,
        "setup_add_h": setup_add_h,
        "measure_per_part_h": measure_h,
        "grind_price_mult": grind_price_mult,
        "operations_add": operations_add,
        "thread_cam_add_h": thread_cam_add_h,
        "keyway_cam_add_h": keyway_cam_add_h,
    }


def _build_active_codes(
    *,
    ra_finish_16: bool,
    ra_grinding: bool,
    hole_tolerance: bool,
    threaded_holes: int,
    keyway: bool,
) -> List[str]:
    codes: List[str] = []
    if ra_finish_16:
        codes.append("ra_finish_16")
    if ra_grinding:
        codes.append("ra_grinding")
    if hole_tolerance:
        codes.append("hole_tolerance")
    if threaded_holes > 0:
        codes.append("threaded_hole")
    if keyway:
        codes.append("keyway")
    if ra_finish_16 or hole_tolerance or keyway:
        codes.append("finish_pass_global")
    return codes


def _build_summary_ru(
    *,
    ra_min: Optional[float],
    ra_finish_16: bool,
    ra_grinding: bool,
    toleranced_holes: int,
    threaded_holes: int,
    keyway: bool,
    keyway_width_mm: Optional[float],
) -> str:
    parts: List[str] = []
    if ra_min is not None:
        if ra_grinding:
            parts.append(f"Ra {ra_min:g} (шлифование)")
        elif ra_finish_16:
            parts.append(f"Ra {ra_min:g}")
    if toleranced_holes > 0:
        parts.append(
            f"{toleranced_holes} отв. с допуском"
            if toleranced_holes > 1
            else "отв. с допуском"
        )
    if threaded_holes > 0:
        parts.append(
            f"резьба ×{threaded_holes}" if threaded_holes > 1 else "резьба"
        )
    if keyway:
        if keyway_width_mm is not None:
            parts.append(f"шпоночный паз {keyway_width_mm:g} мм")
        else:
            parts.append("шпоночный паз")
    return ", ".join(parts)


def criteria_applies_to_pdf(
    criteria: Optional[Dict[str, Any]],
    current_pdf_hash: str,
    analysis_pdf_hash: Optional[str],
) -> bool:
    """Критерии в расчёте только при совпадении hash PDF и завершённом анализе."""
    if not criteria or not criteria.get("active_codes"):
        return False
    crit_hash = (criteria.get("pdf_hash") or "").strip()
    if not crit_hash or crit_hash != current_pdf_hash:
        return False
    if not analysis_pdf_hash or analysis_pdf_hash != current_pdf_hash:
        return False
    return True


def _empty_criteria(pdf_hash: str = "") -> Dict[str, Any]:
    return {
        "version": cfg.COSTING_CRITERIA_VERSION,
        "pdf_hash": pdf_hash,
        "detected": {
            "ra_values_mm": [],
            "ra_min": None,
            "ra_finish_16": False,
            "ra_grinding": False,
            "toleranced_holes": 0,
            "threaded_holes": 0,
            "keyway": False,
            "keyway_width_mm": None,
        },
        "modifiers": {
            "cutting_mult": 1.0,
            "setup_mult": 1.0,
            "cam_mult": 1.0,
            "setup_add_h": 0.0,
            "measure_per_part_h": 0.0,
            "grind_price_mult": 1.0,
            "operations_add": [],
            "thread_cam_add_h": 0.0,
            "keyway_cam_add_h": 0.0,
        },
        "active_codes": [],
        "summary_ru": "",
    }


def extract_manufacturing_criteria(
    drawing_extraction: Optional[Dict[str, Any]] = None,
    expert_text: str = "",
) -> Dict[str, Any]:
    """Извлекает критерии изготовления из чертежа (парсер + поля extraction)."""
    if not drawing_extraction:
        return _empty_criteria()

    text = _collect_text_sources(drawing_extraction, expert_text)
    if not text.strip():
        return _empty_criteria(drawing_extraction.get("pdf_hash") or "")

    drawing_text = _collect_text_sources(drawing_extraction, expert_text="")

    ra_values = _parse_ra_values(text)
    ra_min = min(ra_values) if ra_values else None
    ra_finish_16 = ra_min is not None and ra_min <= cfg.RA_FINISH_THRESHOLD_MM
    ra_grinding = ra_min is not None and ra_min < cfg.RA_FINISH_THRESHOLD_MM

    toleranced_holes = _count_toleranced_holes(text)
    hole_tolerance = toleranced_holes > 0

    threaded_holes = _count_threaded_holes(text)
    keyway, keyway_width = _detect_keyway(drawing_text)

    modifiers = _build_modifiers(
        ra_finish_16=ra_finish_16,
        ra_grinding=ra_grinding,
        hole_tolerance=hole_tolerance,
        threaded_holes=threaded_holes,
        keyway=keyway,
    )
    active_codes = _build_active_codes(
        ra_finish_16=ra_finish_16,
        ra_grinding=ra_grinding,
        hole_tolerance=hole_tolerance,
        threaded_holes=threaded_holes,
        keyway=keyway,
    )

    return {
        "version": cfg.COSTING_CRITERIA_VERSION,
        "pdf_hash": drawing_extraction.get("pdf_hash") or "",
        "detected": {
            "ra_values_mm": ra_values,
            "ra_min": ra_min,
            "ra_finish_16": ra_finish_16,
            "ra_grinding": ra_grinding,
            "toleranced_holes": toleranced_holes,
            "threaded_holes": threaded_holes,
            "keyway": keyway,
            "keyway_width_mm": keyway_width,
        },
        "modifiers": modifiers,
        "active_codes": active_codes,
        "summary_ru": _build_summary_ru(
            ra_min=ra_min,
            ra_finish_16=ra_finish_16,
            ra_grinding=ra_grinding,
            toleranced_holes=toleranced_holes,
            threaded_holes=threaded_holes,
            keyway=keyway,
            keyway_width_mm=keyway_width,
        ),
    }
