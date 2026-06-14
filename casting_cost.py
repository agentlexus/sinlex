"""Расчёт стоимости литья: модель ₽/кг отливки + амортизация оснастки (эталоны РФ 2025-2026)."""
from __future__ import annotations

import json
import os
from functools import lru_cache
from typing import Any, Dict, Optional, Tuple

CASTING_TYPES = (
    "ЛПД",
    "ЛВМ",
    "ЛГМ",
    "Литье в землю",
    "ЛК",
)

CASTING_MATERIALS = ("Сталь", "Алюминий", "Чугун")

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "casting_config.json")

DENSITY_KG_M3 = {
    "Сталь": 7850.0,
    "Алюминий": 2700.0,
    "Чугун": 7200.0,
}

DEFAULT_CASTING_TYPE = "ЛПД"
DEFAULT_CASTING_MATERIAL = "Сталь"
DEFAULT_SHRINK_PCT = 1.5
DEFAULT_ALLOWANCE_MM = 2.0

# Встроенные значения, если casting_config.json недоступен
_EMBEDDED_CONFIG: Dict[str, Any] = {
    "price_per_kg_rub": {
        "Литье в землю": {"Чугун": 250, "Сталь": 350, "Алюминий": 450},
        "ЛГМ": {"Чугун": 280, "Сталь": 400, "Алюминий": 500},
        "ЛК": {"Чугун": 220, "Сталь": 380, "Алюминий": 500},
        "ЛПД": {"Чугун": 300, "Сталь": 450, "Алюминий": 550},
        "ЛВМ": {"Чугун": 2200, "Сталь": 1000, "Алюминий": 3000},
    },
    "tooling_base_rub": {
        "Литье в землю": 80000,
        "ЛГМ": 120000,
        "ЛК": 250000,
        "ЛПД": 200000,
        "ЛВМ": 150000,
    },
    "tooling_reference_span_mm": 200,
    "complexity_factor_by_type": {
        "ЛПД": 1.0,
        "ЛВМ": 1.15,
        "ЛГМ": 1.12,
        "Литье в землю": 0.95,
        "ЛК": 1.08,
    },
    "default_price_per_kg_rub": 350,
    "default_tooling_rub": 100000,
    "min_wall_allowed_mm": {
        "ЛПД|Алюминий": 2.5,
        "ЛПД|Сталь": 3.0,
        "ЛПД|Чугун": 4.0,
        "ЛВМ|Сталь": 3.0,
        "ЛВМ|Алюминий": 2.8,
        "ЛВМ|Чугун": 4.5,
        "ЛГМ|Чугун": 4.0,
        "ЛГМ|Сталь": 3.5,
        "ЛГМ|Алюминий": 3.0,
        "Литье в землю|Сталь": 5.0,
        "Литье в землю|Чугун": 6.0,
        "Литье в землю|Алюминий": 4.5,
        "ЛК|Сталь": 3.5,
        "ЛК|Алюминий": 3.0,
        "ЛК|Чугун": 4.5,
    },
}


@lru_cache(maxsize=1)
def load_casting_config() -> Dict[str, Any]:
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except (OSError, json.JSONDecodeError):
        pass
    return _EMBEDDED_CONFIG


def _key(casting_type: str, material: str) -> Tuple[str, str]:
    ct = casting_type if casting_type in CASTING_TYPES else DEFAULT_CASTING_TYPE
    mat = material if material in CASTING_MATERIALS else DEFAULT_CASTING_MATERIAL
    return ct, mat


def bbox_dims_mm(dimensions: Optional[Dict[str, Any]]) -> Tuple[float, float, float]:
    d = dimensions or {}
    x = float(d.get("x") or d.get("length") or 0)
    y = float(d.get("y") or d.get("width") or 0)
    z = float(d.get("z") or d.get("height") or 0)
    return x, y, z


def max_span_mm(dimensions: Optional[Dict[str, Any]]) -> float:
    x, y, z = bbox_dims_mm(dimensions)
    return max(x, y, z, 1.0)


def stock_dims_mm(
    dimensions: Optional[Dict[str, Any]],
    *,
    shrink_pct: float,
    allowance_mm: float,
) -> Tuple[float, float, float]:
    """Габариты с усадкой и припуском (для отображения; ₽/кг считается по массе отливки)."""
    x, y, z = bbox_dims_mm(dimensions)
    scale = 1.0 + max(0.0, float(shrink_pct)) / 100.0
    add = 2.0 * max(0.0, float(allowance_mm))
    return x * scale + add, y * scale + add, z * scale + add


def mass_kg_from_volume_mm3(volume_mm3: float, material: str) -> float:
    density = DENSITY_KG_M3.get(material, DENSITY_KG_M3[DEFAULT_CASTING_MATERIAL])
    return float(volume_mm3 or 0) * 1e-9 * density


def price_per_kg_rub(casting_type: str, material: str) -> float:
    cfg = load_casting_config()
    ct, mat = _key(casting_type, material)
    table = cfg.get("price_per_kg_rub") or {}
    row = table.get(ct) or {}
    if isinstance(row, dict) and mat in row:
        return float(row[mat])
    return float(cfg.get("default_price_per_kg_rub", 350))


def tooling_base_rub(casting_type: str) -> float:
    cfg = load_casting_config()
    ct = casting_type if casting_type in CASTING_TYPES else DEFAULT_CASTING_TYPE
    table = cfg.get("tooling_base_rub") or {}
    return float(table.get(ct, cfg.get("default_tooling_rub", 100000)))


def tooling_size_factor(
    dimensions: Optional[Dict[str, Any]],
    *,
    shrink_pct: float = 0.0,
) -> float:
    """Масштаб оснастки от габарита и усадки (крупнее отливка — дороже форма)."""
    cfg = load_casting_config()
    ref = float(cfg.get("tooling_reference_span_mm", 200) or 200)
    span = max_span_mm(dimensions)
    size_k = max(1.0, (span / ref) ** 0.45)
    shrink_k = 1.0 + max(0.0, float(shrink_pct)) / 100.0
    return size_k * shrink_k


def complexity_factor(casting_type: str, detail_index: float = 0.0) -> float:
    cfg = load_casting_config()
    ct = casting_type if casting_type in CASTING_TYPES else DEFAULT_CASTING_TYPE
    table = cfg.get("complexity_factor_by_type") or {}
    k = float(table.get(ct, 1.0))
    if detail_index and detail_index > 1.2:
        k *= min(1.35, 1.0 + (detail_index - 1.0) * 0.12)
    return k


def compute_casting_cost(
    *,
    part_volume_mm3: float,
    dimensions: Optional[Dict[str, Any]],
    casting_type: str,
    casting_material: str,
    shrink_pct: float,
    allowance_mm: float,
    detail_index: float = 0.0,
    quantity: int = 1,
) -> Dict[str, Any]:
    """
    Итого = N × (m_отл × ₽/кг × K_сложн) + T_оснастки.
    ₽/кг — полная отпускная цена отливки (рыночный коридор РФ).
    T_оснастки = tooling_base × K_габарит(усадка); амортизация на партию N.
    """
    ct, mat = _key(casting_type, casting_material)
    qty = max(1, int(quantity or 1))
    v_part = float(part_volume_mm3 or 0)
    m_part = mass_kg_from_volume_mm3(v_part, mat) if v_part > 0 else 0.0

    p_kg = price_per_kg_rub(ct, mat)
    k_cplx = complexity_factor(ct, detail_index)
    casting_unit = m_part * p_kg * k_cplx

    t_base = tooling_base_rub(ct)
    t_factor = tooling_size_factor(dimensions, shrink_pct=shrink_pct)
    tooling_once = t_base * t_factor

    total_order = qty * casting_unit + tooling_once
    cost_per_unit = int(round(total_order / qty))
    total = int(round(total_order))
    tooling_per_unit = tooling_once / qty

    sx, sy, sz = stock_dims_mm(
        dimensions, shrink_pct=shrink_pct, allowance_mm=allowance_mm
    )
    v_stock = sx * sy * sz if sx > 0 and sy > 0 and sz > 0 else 0.0
    m_stock = mass_kg_from_volume_mm3(v_stock, mat) if v_stock > 0 else 0.0

    return {
        "quantity": qty,
        "price_per_kg": round(p_kg, 2),
        "cost_per_unit": cost_per_unit,
        "total_cost": total,
        "casting_cost_per_unit": int(round(casting_unit)),
        "tooling_cost_once": int(round(tooling_once)),
        "tooling_cost_per_unit": int(round(tooling_per_unit)),
        "mass_kg": round(m_part, 4),
        "mass_stock_kg": round(m_stock, 4) if m_stock else round(m_part, 4),
        "volume_part_mm3": round(v_part, 2),
        "volume_stock_mm3": round(v_stock, 2),
        "stock_dims_mm": {"x": round(sx, 2), "y": round(sy, 2), "z": round(sz, 2)},
        "K_complexity": round(k_cplx, 3),
        "tooling_size_factor": round(t_factor, 3),
        "casting_type": ct,
        "casting_material": mat,
        "formula": "N × (m × ₽/кг × K) + T_оснастки",
    }


def min_wall_allowed_mm(casting_type: str, casting_material: str) -> Optional[float]:
    cfg = load_casting_config()
    ct, mat = _key(casting_type, casting_material)
    key = f"{ct}|{mat}"
    table = cfg.get("min_wall_allowed_mm") or {}
    val = table.get(key)
    return float(val) if val is not None else None


def wall_thickness_warning(
    t_min: Optional[float],
    casting_type: str,
    casting_material: str,
) -> Optional[str]:
    if t_min is None or (isinstance(t_min, float) and t_min <= 0):
        return None
    allowed = min_wall_allowed_mm(casting_type, casting_material)
    if allowed is None:
        return None
    if float(t_min) < float(allowed):
        return (
            f"Минимальная толщина стенки {t_min:.2f} мм меньше рекомендуемой для выбранного "
            f"типа литья и материала ({allowed:.1f} мм). Возможен брак или недолив."
        )
    return None
