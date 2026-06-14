"""Детерминированная сверка чертежа (текст/OCR) с данными STEP."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

DIAMETER_MATCH_TOLERANCE_MM = 0.3
DIAMETER_MISMATCH_EPS_MM = 0.05


def _step_holes(step_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    geom = step_data.get("geometry") or {}
    holes = step_data.get("holes") or geom.get("holes") or []
    return [h for h in holes if isinstance(h, dict)]


def _step_part_family(step_data: Dict[str, Any]) -> str:
    geom = step_data.get("geometry") or {}
    return str(
        step_data.get("part_family")
        or geom.get("part_family")
        or ""
    ).strip().lower()


def _step_material(step_data: Dict[str, Any]) -> str:
    return str(step_data.get("material") or "").strip()


def _cluster_holes_by_diameter(holes: List[Dict[str, Any]]) -> Dict[float, List[Dict[str, Any]]]:
    clusters: Dict[float, List[Dict[str, Any]]] = {}
    for h in holes:
        d = h.get("diameter")
        if d is None:
            continue
        try:
            key = round(float(d), 2)
        except (TypeError, ValueError):
            continue
        clusters.setdefault(key, []).append(h)
    return clusters


def _find_step_cluster(
    drawing_mm: float,
    clusters: Dict[float, List[Dict[str, Any]]],
) -> Optional[Tuple[float, List[Dict[str, Any]]]]:
    best: Optional[Tuple[float, List[Dict[str, Any]]]] = None
    best_dist = DIAMETER_MATCH_TOLERANCE_MM + 1.0
    for d, group in clusters.items():
        dist = abs(drawing_mm - d)
        if dist <= DIAMETER_MATCH_TOLERANCE_MM and dist < best_dist:
            best_dist = dist
            best = (d, group)
    return best


def _format_drawing_dim(value_mm: float, count_hint: int, raw: str) -> str:
    if raw:
        return raw
    if count_hint > 1:
        return f"{count_hint}×Ø{value_mm:g}"
    return f"Ø{value_mm:g}"


def _format_step_dim(diameter_mm: float, count: int) -> str:
    if count > 1:
        return f"{count}×Ø{diameter_mm:g}"
    return f"Ø{diameter_mm:g}"


def _build_summary(items: List[Dict[str, Any]]) -> str:
    if not items:
        return "Расхождений не обнаружено"
    critical = sum(1 for i in items if i.get("severity") == "error")
    warnings = sum(1 for i in items if i.get("severity") == "warning")
    w = warnings + critical
    if w == 0:
        return f"{len(items)} замечаний"
    return f"{len(items)} расхождений, {critical} критичных"


def compare_drawing_to_step(
    drawing: Optional[Dict[str, Any]],
    step_data: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Сверка DrawingExtractionResult с step_data.
    Возвращает DrawingStepCompareResult v1.
    """
    drawing = drawing or {}
    step_data = step_data or {}
    items: List[Dict[str, Any]] = []
    has_drawing_text = bool(
        drawing.get("pdf_hash")
        or str(drawing.get("full_text") or "").strip()
        or drawing.get("pages_processed")
    )

    parsed = [
        d
        for d in (drawing.get("parsed_dimensions") or [])
        if isinstance(d, dict) and d.get("kind") == "diameter"
    ]
    fields = drawing.get("fields") or {}
    full_text = str(drawing.get("full_text") or "").lower()
    step_holes = _step_holes(step_data)
    clusters = _cluster_holes_by_diameter(step_holes)

    for dim in parsed:
        try:
            value_mm = float(dim.get("value_mm"))
        except (TypeError, ValueError):
            continue
        count_hint = int(dim.get("count_hint") or 1)
        raw = str(dim.get("raw") or "")
        drawing_label = _format_drawing_dim(value_mm, count_hint, raw)

        matched = _find_step_cluster(value_mm, clusters)
        if matched is None:
            if step_holes:
                items.append(
                    {
                        "code": "hole_diameter_mismatch",
                        "severity": "warning",
                        "drawing": drawing_label,
                        "step": "—",
                        "message": (
                            f"На чертеже {drawing_label}, в STEP нет отверстий "
                            f"Ø≈{value_mm:g} мм (допуск ±{DIAMETER_MATCH_TOLERANCE_MM:g} мм)"
                        ),
                    }
                )
            continue

        step_d, step_group = matched
        step_count = len(step_group)
        step_label = _format_step_dim(step_d, step_count)

        if abs(value_mm - step_d) > DIAMETER_MISMATCH_EPS_MM:
            items.append(
                {
                    "code": "hole_diameter_mismatch",
                    "severity": "warning",
                    "drawing": drawing_label,
                    "step": step_label,
                    "message": (
                        f"На чертеже {drawing_label}, в STEP — {step_label}"
                    ),
                }
            )

        if count_hint != step_count:
            items.append(
                {
                    "code": "hole_count_mismatch",
                    "severity": "warning",
                    "drawing": drawing_label,
                    "step": step_label,
                    "message": (
                        f"Количество на чертеже: {count_hint}, в STEP: {step_count} "
                        f"(Ø{step_d:g} мм)"
                    ),
                }
            )

    if not has_drawing_text:
        return {
            "version": 1,
            "status": "ok",
            "items": [],
            "summary_ru": "Чертёж не анализировался",
        }

    material_field = str(fields.get("material") or "").strip()
    material_ok = material_field and material_field.lower() not in (
        "неразборчиво",
        "не указан",
        "—",
        "-",
    )
    if material_ok and not _step_material(step_data):
        items.append(
            {
                "code": "material_unknown_step",
                "severity": "warning",
                "drawing": material_field,
                "step": "не указан",
                "message": (
                    f"Материал на чертеже: {material_field}; в STEP материал не задан"
                ),
            }
        )

    plate_words = ("плита", "лист", "plate", "sheet")
    text_has_plate = any(w in full_text for w in plate_words)
    part_family = _step_part_family(step_data)
    if text_has_plate and part_family and part_family != "plate":
        items.append(
            {
                "code": "blank_family_hint",
                "severity": "warning",
                "drawing": "плита/лист (текст чертежа)",
                "step": part_family,
                "message": (
                    "В тексте чертежа указана плита/лист, в STEP семейство детали иное"
                ),
            }
        )

    if not parsed and step_holes:
        n = len(step_holes)
        items.append(
            {
                "code": "no_holes_on_drawing",
                "severity": "warning",
                "drawing": "Ø не найдены в тексте",
                "step": f"{n} отверстий в STEP",
                "message": (
                    f"В тексте чертежа не распознаны диаметры Ø, в STEP — {n} отверстий"
                ),
            }
        )

    status = "ok"
    if any(i.get("severity") == "error" for i in items):
        status = "error"
    elif items:
        status = "warning"

    return {
        "version": 1,
        "status": status,
        "items": items,
        "summary_ru": _build_summary(items),
    }
