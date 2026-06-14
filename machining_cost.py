"""Расчёт времени обработки: резание, станочная наладка, написание УП (CAD/CAM)."""
from __future__ import annotations

import math
import os
from typing import Any, Dict, List, Optional

# Доля полной «единичной» наладки, учитываемая на партию (остальное амортизируется)
BATCH_SETUP_AMORT = {1: 1.0, 10: 0.42, 50: 0.18, 100: 0.12, 200: 0.08, 500: 0.05}
# Коэффициент серийности чистового времени резания (как было в app.py)
BATCH_CUTTING_FACTOR = {1: 1.0, 10: 0.5, 50: 0.3, 100: 0.2, 200: 0.15, 500: 0.1}
# Амортизация времени написания УП (модель STEP уже есть)
BATCH_CAM_AMORT = {1: 1.0, 10: 0.55, 50: 0.30, 100: 0.22, 200: 0.16, 500: 0.12}
# Ставка инженера-программиста, ₽/ч (можно переопределить SINLEX_CAM_RATE)
DEFAULT_CAM_RATE = int(os.environ.get("SINLEX_CAM_RATE", "1000"))
# УП считаем только для средней и высокой сложности; низкая — без вкладки и без ₽
CAM_APPLY_COMPLEXITIES = frozenset({"средняя", "высокая"})
# Доп. множитель времени УП для высокой сложности (средняя = 1.0)
CAM_HIGH_COMPLEXITY_MULT = float(os.environ.get("SINLEX_CAM_MULT_HIGH", "1.35"))


def _interp_curve(batch_size: int, curve: Dict[int, float]) -> float:
    batch_size = max(1, int(batch_size))
    keys = sorted(curve.keys())
    if batch_size <= keys[0]:
        return curve[keys[0]]
    if batch_size >= keys[-1]:
        return curve[keys[-1]]
    for i in range(len(keys) - 1):
        lo, hi = keys[i], keys[i + 1]
        if lo <= batch_size <= hi:
            t = (batch_size - lo) / (hi - lo)
            return curve[lo] * (1.0 - t) + curve[hi] * t
    return curve[keys[-1]]


def part_mass_kg(volume_mm3: float, density_g_cm3: float) -> float:
    """Масса готовой детали, кг (объём в мм³, плотность г/см³)."""
    return max(float(volume_mm3), 0.0) * float(density_g_cm3) / 1e6


def _rod_allowance_mm(diameter: float, length: float) -> tuple:
    pd = 10.0 if diameter >= 100 else 5.0
    pl = 10.0 if length >= 100 else 5.0
    return pd, pl


def blank_dims_with_allowance(
    workpiece_type: str,
    *,
    workpiece: Optional[Dict[str, Any]] = None,
    model_size: Optional[Dict[str, Any]] = None,
    dimensions: Optional[Dict[str, Any]] = None,
    operations: Optional[List[str]] = None,
) -> Dict[str, float]:
    """Габариты заготовки с припуском по workpiece / model_size / bbox (мм)."""
    wp = workpiece or {}
    ms = model_size or {}
    dims = dimensions or {}
    x, y, z = float(dims.get("x") or 0), float(dims.get("y") or 0), float(dims.get("z") or 0)
    ops = operations or []
    wtype = str(workpiece_type or wp.get("type") or "").strip()
    use_rod = wtype in ("Пруток", "Вал") or (
        wtype != "Плита" and any("токар" in str(o).lower() for o in ops)
    )

    if use_rod:
        diameter = float(wp.get("diameter") or ms.get("diameter") or 0)
        length = float(wp.get("length") or ms.get("length") or 0)
        if diameter <= 0 or length <= 0:
            small, mid, large = sorted([x, y, z])
            if large > 0 and small / large < 0.45 and abs(large - mid) / large < 0.2:
                diameter, length = max(mid, large), small
            else:
                diameter, length = max(small, mid), large
        pd, pl = _rod_allowance_mm(diameter, length)
        return {
            "diameter": diameter + pd,
            "length": length + pl,
            "width": 0.0,
            "height": 0.0,
            "workpiece_type": "Пруток",
        }

    px = 10.0 if x >= 100 else 5.0
    py = 10.0 if y >= 100 else 5.0
    pz = 10.0 if z >= 100 else 5.0
    return {
        "diameter": 0.0,
        "length": float(wp.get("length") or y) + py,
        "width": float(wp.get("width") or x) + px,
        "height": float(wp.get("height") or z) + pz,
        "workpiece_type": "Плита",
    }


def blank_volume_mm3(
    workpiece_type: str,
    diameter: float = 0,
    length: float = 0,
    width: float = 0,
    height: float = 0,
) -> float:
    """Объём заготовки, мм³."""
    wt = str(workpiece_type or "").strip()
    if wt in ("Пруток", "Вал"):
        d, l = max(float(diameter), 1.0), max(float(length), 1.0)
        return math.pi * (d / 2.0) ** 2 * l
    w, l, h = max(float(width), 1.0), max(float(length), 1.0), max(float(height), 1.0)
    return w * l * h


def removal_volume_cm3(blank_volume_mm3: float, model_volume_mm3: float) -> float:
    """Объём снимаемого металла, см³ (не завышаем при отрицательном припуске)."""
    rv_mm3 = float(blank_volume_mm3) - max(float(model_volume_mm3), 0.0)
    if rv_mm3 < 0:
        return max(model_volume_mm3 * 0.02 / 1000.0, 0.1)
    return max(rv_mm3 / 1000.0, 0.1)


def removal_rate_cm3_h(
    geometry: Optional[Dict[str, Any]] = None,
    *,
    material: str = "",
    detail_index: float = 0,
) -> float:
    """Скорость съёма, см³/ч (чем сложнее деталь — тем ниже)."""
    geometry = geometry or {}
    comp = str(geometry.get("complexity") or "низкая").strip().lower()
    tw = bool(geometry.get("thin_walls"))
    di = float(geometry.get("detail_index") or detail_index or 0)

    if comp == "высокая":
        rr = 150.0
    elif comp == "средняя":
        rr = 250.0
    else:
        rr = 400.0
    if tw:
        rr *= 0.85
    if di > 12:
        rr *= max(0.45, 12.0 / di)
    mat = str(material or "")
    if "Нерж" in mat or "Титан" in mat:
        rr *= 0.65
    elif "Алюминий" in mat:
        rr *= 1.4
    elif "Латунь" in mat or "Медь" in mat:
        rr *= 1.15
    rr = max(rr, 20.0)
    # Крупногабарит: крупные станки с ЧПУ — выше производительность съёма
    pf = str((geometry or {}).get("part_family") or "").strip().lower()
    if pf == "oversize":
        rr *= 1.5
        if "Алюминий" in mat:
            rr *= 2.4  # ×2 (крупный станок) ×1.2
    return rr


def count_process_stations(
    operations: List[str],
    geometry: Optional[Dict[str, Any]] = None,
) -> int:
    """
    Число установов: по OCC (противоположные обрабатываемые плоскости) или по процессам.
    Токарная/фрезерная — отдельно; обе стороны плиты → переворот, не один установ.
    """
    geometry = geometry or {}
    ops = [str(o).lower() for o in (operations or [])]
    geo_total = geometry.get("setup_count_total")
    if geo_total is not None and int(geo_total) > 0:
        return max(int(geo_total), 1)

    n = 0
    turn_g = geometry.get("setup_count_turning")
    mill_g = geometry.get("setup_count_milling")
    if any("токар" in o for o in ops):
        n += int(turn_g) if turn_g is not None else 1
    if any("фрез" in o for o in ops):
        n += int(mill_g) if mill_g is not None else 1
    if any("сверл" in o for o in ops) and not any("фрез" in o for o in ops):
        n += 1
    if any("шлиф" in o for o in ops):
        n += 1
    return max(n, 1)


def setup_hours_full(
    operations: List[str],
    part_mass_kg: float,
    geometry: Optional[Dict[str, Any]] = None,
    workpiece_type: str = "",
    part_family: str = "",
) -> Dict[str, float]:
    """
    Полная наладка при партии из 1 шт.: база + масса + переналадки между процессами + оснастка.
    На партию: total * amort(batch); на деталь: (total * amort) / batch_size.
    """
    geometry = geometry or {}
    complexity = str(geometry.get("complexity") or "низкая")
    di = float(geometry.get("detail_index") or 0)
    tw = bool(geometry.get("thin_walls"))

    base_h = 0.35
    mass_h = min(5.0, 0.25 * math.sqrt(max(part_mass_kg, 0.05)))

    stations = count_process_stations(operations, geometry)
    ops_low = [str(o).lower() for o in (operations or [])]
    process_h = 0.0
    if stations >= 2:
        process_h = 1.2 + 0.55 * (stations - 1)
    elif stations == 1 and any("фрез" in o for o in ops_low):
        process_h = 0.65

    pf = (part_family or "").lower()
    wp = workpiece_type or ""
    is_plate = pf == "plate" or wp == "Плита"
    is_impeller = pf == "impeller"

    fixture_h = 0.0
    if is_plate or is_impeller:
        if complexity == "высокая":
            fixture_h = 10.0
        elif complexity == "средняя":
            fixture_h = 5.0
        else:
            fixture_h = 2.5
        if tw:
            fixture_h *= 1.2
        if di >= 14:
            fixture_h *= 1.25
        elif di >= 10:
            fixture_h *= 1.1
    elif pf == "rod":
        fixture_h = 0.45 + 0.04 * min(part_mass_kg, 100.0)

    total = base_h + mass_h + process_h + fixture_h
    return {
        "base_h": base_h,
        "mass_h": mass_h,
        "process_h": process_h,
        "fixture_h": fixture_h,
        "total_h": total,
        "stations": float(stations),
    }


def _normalize_complexity(geometry: Optional[Dict[str, Any]]) -> str:
    return str((geometry or {}).get("complexity") or "низкая").strip().lower()


def cam_programming_applies(geometry: Optional[Dict[str, Any]] = None) -> bool:
    """Написание УП только для средней и высокой сложности."""
    return _normalize_complexity(geometry) in CAM_APPLY_COMPLEXITIES


def cam_complexity_multiplier(geometry: Optional[Dict[str, Any]] = None) -> float:
    """Множитель времени УП: высокая сложность дороже средней."""
    if _normalize_complexity(geometry) == "высокая":
        return CAM_HIGH_COMPLEXITY_MULT
    return 1.0


def _empty_cam_breakdown() -> Dict[str, float]:
    return {
        "base_h": 0.0,
        "turn_h": 0.0,
        "mill_h": 0.0,
        "drill_h": 0.0,
        "complexity_h": 0.0,
        "geometry_h": 0.0,
        "total_h": 0.0,
    }


def cam_programming_hours_full(
    operations: List[str],
    part_mass_kg: float,
    geometry: Optional[Dict[str, Any]] = None,
    workpiece_type: str = "",
    part_family: str = "",
) -> Dict[str, float]:
    """
    Полное время написания УП при 1 шт. (STEP/3D уже есть): импорт, стратегии по процессам, сложность.
    """
    geometry = geometry or {}
    if not cam_programming_applies(geometry):
        return _empty_cam_breakdown()

    complexity = _normalize_complexity(geometry)
    di = float(geometry.get("detail_index") or 0)
    tw = bool(geometry.get("thin_walls"))
    fc = int(geometry.get("face_count") or 0)
    ops_low = [str(o).lower() for o in (operations or [])]

    base_h = 0.75

    turn_h = 0.0
    if any("токар" in o for o in ops_low):
        if complexity == "высокая":
            turn_h = 5.0
        elif complexity == "средняя":
            turn_h = 3.0
        else:
            turn_h = 1.8

    mill_h = 0.0
    if any("фрез" in o for o in ops_low):
        is_5axis = any("5" in o for o in ops_low)
        if is_5axis:
            if complexity == "высокая":
                mill_h = 9.0
            elif complexity == "средняя":
                mill_h = 7.0
            else:
                mill_h = 5.0
        elif complexity == "высокая":
            mill_h = 4.5
        elif complexity == "средняя":
            mill_h = 3.0
        else:
            mill_h = 2.0

    drill_h = 1.2 if any("сверл" in o for o in ops_low) else 0.0

    pf = (part_family or "").lower()
    wp = workpiece_type or ""
    complexity_h = 0.0
    if pf in ("plate", "impeller") or wp == "Плита":
        if complexity == "высокая":
            complexity_h = 8.0
        elif complexity == "средняя":
            complexity_h = 3.5
        else:
            complexity_h = 1.0
    elif complexity == "высокая":
        complexity_h = 2.0
    elif complexity == "средняя":
        complexity_h = 1.0

    if di >= 14:
        complexity_h *= 1.3
    elif di >= 10:
        complexity_h *= 1.15
    if tw:
        complexity_h *= 1.1
    if pf == "impeller":
        complexity_h += 4.0

    geometry_h = min(4.0, 0.01 * min(fc, 400)) + min(
        2.0, 0.02 * math.sqrt(max(part_mass_kg, 0.05))
    )

    total = (base_h + turn_h + mill_h + drill_h + complexity_h + geometry_h) * cam_complexity_multiplier(
        geometry
    )
    return {
        "base_h": base_h,
        "turn_h": turn_h,
        "mill_h": mill_h,
        "drill_h": drill_h,
        "complexity_h": complexity_h,
        "geometry_h": geometry_h,
        "total_h": total,
        "complexity_mult": cam_complexity_multiplier(geometry),
    }


def _quote_time_snapshot(quote: Dict[str, Any]) -> Dict[str, float]:
    return {
        "mhpu": float(quote["mhpu"]),
        "mht": float(quote["mht"]),
        "cutting_per_part_h": float(quote["cutting_per_part_h"]),
        "setup_per_part_h": float(quote["setup_per_part_h"]),
        "cam_per_part_h": float(quote.get("cam_per_part_h") or 0.0),
    }


def apply_drawing_criteria_to_quote(
    quote: Dict[str, Any],
    criteria: Optional[Dict[str, Any]],
    *,
    batch_size: int,
) -> Dict[str, Any]:
    """
    Применяет модификаторы из drawing_manufacturing_criteria к расчёту времени.
    Без active_codes возвращает копию quote с quote_base == quote_adjusted.
    """
    batch = max(int(batch_size), 1)
    base_snap = _quote_time_snapshot(quote)
    out = dict(quote)
    out["quote_base"] = dict(base_snap)
    out["drawing_criteria"] = criteria

    active = (criteria or {}).get("active_codes") or []
    if not active:
        out["quote_adjusted"] = dict(base_snap)
        out["criteria_breakdown"] = {}
        out["grind_price_mult"] = 1.0
        return out

    mods = (criteria or {}).get("modifiers") or {}
    cut_mult = float(mods.get("cutting_mult") or 1.0)
    setup_mult = float(mods.get("setup_mult") or 1.0)
    setup_add_h = float(mods.get("setup_add_h") or 0.0)
    cam_mult = float(mods.get("cam_mult") or 1.0)
    measure_h = float(mods.get("measure_per_part_h") or 0.0)
    grind_price_mult = float(mods.get("grind_price_mult") or 1.0)
    thread_cam_h = float(mods.get("thread_cam_add_h") or 0.0)
    keyway_cam_h = float(mods.get("keyway_cam_add_h") or 0.0)

    cutting_adj = float(quote["cutting_per_part_h"]) * cut_mult

    setup_amort = float(quote["setup_amort"])
    setup_full_adj = (float(quote["setup_full_h"]) + setup_add_h) * setup_mult
    setup_batch_adj = setup_full_adj * setup_amort
    setup_per_adj = setup_batch_adj / batch

    mhpu_adj = cutting_adj + setup_per_adj + measure_h
    mht_adj = cutting_adj * batch + setup_batch_adj

    cam_per_adj = float(quote.get("cam_per_part_h") or 0.0)
    cam_batch_adj = float(quote.get("cam_batch_h") or 0.0)
    cam_full_adj = float(quote.get("cam_full_h") or 0.0)
    cam_cost_batch = float(quote.get("cam_cost_batch") or 0.0)

    if quote.get("cam_applies"):
        cam_amort = float(quote["cam_amort"])
        cam_full_adj = (cam_full_adj + thread_cam_h + keyway_cam_h) * cam_mult
        cam_batch_adj = cam_full_adj * cam_amort
        cam_per_adj = cam_batch_adj / batch
        cam_rate = float(quote.get("cam_rate") or DEFAULT_CAM_RATE)
        cam_cost_batch = cam_batch_adj * cam_rate

    out.update(
        {
            "cutting_per_part_h": cutting_adj,
            "setup_full_h": setup_full_adj,
            "setup_batch_h": setup_batch_adj,
            "setup_per_part_h": setup_per_adj,
            "mhpu": mhpu_adj,
            "mht": mht_adj,
            "cam_full_h": cam_full_adj,
            "cam_batch_h": cam_batch_adj,
            "cam_per_part_h": cam_per_adj,
            "cam_cost_batch": cam_cost_batch,
            "grind_price_mult": grind_price_mult,
            "quote_adjusted": {
                "mhpu": mhpu_adj,
                "mht": mht_adj,
                "cutting_per_part_h": cutting_adj,
                "setup_per_part_h": setup_per_adj,
                "cam_per_part_h": cam_per_adj,
            },
            "criteria_breakdown": {
                "active_codes": list(active),
                "cutting_mult": cut_mult,
                "setup_mult": setup_mult,
                "setup_add_h": setup_add_h,
                "cam_mult": cam_mult,
                "measure_per_part_h": measure_h,
                "grind_price_mult": grind_price_mult,
                "thread_cam_add_h": thread_cam_h,
                "keyway_cam_add_h": keyway_cam_h,
                "operations_add": list(mods.get("operations_add") or []),
            },
        }
    )
    return out


def _compute_machining_quote_base(
    *,
    removal_volume_cm3: float,
    removal_rate: float,
    batch_size: int,
    model_volume_mm3: float,
    density_g_cm3: float,
    operations: List[str],
    geometry: Optional[Dict[str, Any]] = None,
    workpiece_type: str = "",
    part_family: str = "",
    cam_rate_per_hour: Optional[float] = None,
) -> Dict[str, Any]:
    """Базовый расчёт без критериев чертежа."""
    rr = max(float(removal_rate), 1e-6)
    bmh = float(removal_volume_cm3) / rr
    cut_fct = _interp_curve(batch_size, BATCH_CUTTING_FACTOR)
    cutting_per_part_h = bmh * cut_fct

    mass_kg = part_mass_kg(model_volume_mm3, density_g_cm3)
    setup_parts = setup_hours_full(
        operations, mass_kg, geometry, workpiece_type, part_family
    )
    setup_full_h = setup_parts["total_h"]
    setup_amort = _interp_curve(batch_size, BATCH_SETUP_AMORT)
    setup_batch_h = setup_full_h * setup_amort
    setup_per_part_h = setup_batch_h / max(int(batch_size), 1)

    mhpu = cutting_per_part_h + setup_per_part_h
    mht = cutting_per_part_h * max(int(batch_size), 1) + setup_batch_h

    cam_applies = cam_programming_applies(geometry)
    if cam_applies:
        cam_parts = cam_programming_hours_full(
            operations, mass_kg, geometry, workpiece_type, part_family
        )
        cam_full_h = cam_parts["total_h"]
        cam_amort = _interp_curve(batch_size, BATCH_CAM_AMORT)
        cam_batch_h = cam_full_h * cam_amort
        cam_per_part_h = cam_batch_h / max(int(batch_size), 1)
        cam_rate = float(cam_rate_per_hour if cam_rate_per_hour is not None else DEFAULT_CAM_RATE)
        cam_cost_batch = cam_batch_h * cam_rate
    else:
        cam_parts = _empty_cam_breakdown()
        cam_full_h = cam_amort = cam_batch_h = cam_per_part_h = cam_cost_batch = 0.0
        cam_rate = float(cam_rate_per_hour if cam_rate_per_hour is not None else DEFAULT_CAM_RATE)

    return {
        "bmh": bmh,
        "cut_fct": cut_fct,
        "cutting_per_part_h": cutting_per_part_h,
        "setup_full_h": setup_full_h,
        "setup_amort": setup_amort,
        "setup_batch_h": setup_batch_h,
        "setup_per_part_h": setup_per_part_h,
        "mhpu": mhpu,
        "mht": mht,
        "part_mass_kg": mass_kg,
        "setup_breakdown": setup_parts,
        "cam_full_h": cam_full_h,
        "cam_amort": cam_amort,
        "cam_batch_h": cam_batch_h,
        "cam_per_part_h": cam_per_part_h,
        "cam_rate": cam_rate,
        "cam_cost_batch": cam_cost_batch,
        "cam_breakdown": cam_parts,
        "cam_applies": cam_applies,
    }


def compute_machining_quote(
    *,
    removal_volume_cm3: float,
    removal_rate: float,
    batch_size: int,
    model_volume_mm3: float,
    density_g_cm3: float,
    operations: List[str],
    geometry: Optional[Dict[str, Any]] = None,
    workpiece_type: str = "",
    part_family: str = "",
    cam_rate_per_hour: Optional[float] = None,
    drawing_criteria: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Время резания, наладка, CAM; при drawing_criteria — модификаторы чертежа."""
    base = _compute_machining_quote_base(
        removal_volume_cm3=removal_volume_cm3,
        removal_rate=removal_rate,
        batch_size=batch_size,
        model_volume_mm3=model_volume_mm3,
        density_g_cm3=density_g_cm3,
        operations=operations,
        geometry=geometry,
        workpiece_type=workpiece_type,
        part_family=part_family,
        cam_rate_per_hour=cam_rate_per_hour,
    )
    return apply_drawing_criteria_to_quote(
        base,
        drawing_criteria,
        batch_size=batch_size,
    )
