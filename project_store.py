"""
Спинной мозг проекта: полный анализ STEP (pythonOCC) и параметры в data.txt.
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional

# Ключи, которые всегда сериализуем как JSON
_JSON_KEYS = frozenset({
    "dimensions",
    "geometry",
    "model_size",
    "finished_dimensions",
    "workpiece",
    "workpiece_analysis",
    "operations",
    "step_analysis",
    "rod_features",
    "bbox_dimensions",
    "center_of_mass",
    "principal_axes",
    "inertia_matrix",
    "projection_areas",
    "extraction",
    "holes",
    "shafts",
    "drawing_extraction",
    "drawing_manufacturing_criteria",
})

# Поля заготовки / UI (числа и строки)
_USER_SCALAR_KEYS = frozenset({
    "material",
    "workpiece_type",
    "diam",
    "length",
    "width",
    "height",
    "cost_per_hour",
    "cam_rate",
    "batch_size",
    "casting_type",
    "casting_material",
    "shrink_pct",
    "allowance_mm",
})


def _safe_dir_name(project_name: str) -> str:
    return project_name.replace(" ", "_").replace("/", "_")


def _storage_root(storage: str = "projects") -> str:
    if storage == "casting":
        return "/opt/sinlex/casting"
    return "/opt/sinlex/projects"


def projects_base_dir(user_folder: str = "", storage: str = "projects") -> str:
    base = _storage_root(storage)
    if user_folder:
        return os.path.join(base, user_folder)
    return base


def project_data_path(
    project_name: str, user_folder: str = "", storage: str = "projects"
) -> str:
    safe = _safe_dir_name(project_name)
    return os.path.join(projects_base_dir(user_folder, storage=storage), safe, "data.txt")


def _serialize_value(key: str, value: Any) -> str:
    if value is None:
        return ""
    if key in _JSON_KEYS or isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _parse_value(raw: str) -> Any:
    raw = raw.strip()
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    low = raw.lower()
    if low == "true":
        return True
    if low == "false":
        return False
    try:
        if "." in raw or "e" in low:
            return float(raw)
        return int(raw)
    except ValueError:
        return raw


def load_project_data(project_name: str, user_folder: str = "", storage: str = "projects") -> Dict[str, Any]:
    """Прочитать весь data.txt проекта."""
    path = project_data_path(project_name, user_folder, storage=storage)
    if not os.path.isfile(path):
        return {}
    data: Dict[str, Any] = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("==="):
                continue
            if ": " not in line:
                continue
            key, val = line.split(": ", 1)
            data[key.strip()] = _parse_value(val)
    return data


def save_project_data(project_name: str, data: Dict[str, Any], user_folder: str = "", storage: str = "projects") -> None:
    """Записать полный data.txt (все ключи из словаря)."""
    safe = _safe_dir_name(project_name)
    pdir = os.path.join(projects_base_dir(user_folder, storage=storage), safe)
    os.makedirs(pdir, exist_ok=True)
    path = os.path.join(pdir, "data.txt")
    pn = data.get("project_name") or project_name
    lines = [f"=== ПРОЕКТ: {pn} ===", f"project_name: {pn}"]
    skip = {"project_name"}
    for key in sorted(data.keys()):
        if key in skip:
            continue
        val = data[key]
        if val is None or val == "":
            continue
        lines.append(f"{key}: {_serialize_value(key, val)}")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def record_from_step_analysis(
    analysis: Dict[str, Any],
    project_name: str,
    *,
    analysis_version: str = "",
    step_digest: str = "",
) -> Dict[str, Any]:
    """Собрать плоскую запись data.txt из ответа analyze-step."""
    geom = dict(analysis.get("geometry") or {})
    family_labels = {
        "rod": "Пруток",
        "impeller": "Крыльчатка",
        "plate": "Плита",
    }
    pf = analysis.get("part_family") or geom.get("part_family") or ""
    if pf:
        geom["part_family"] = pf
        geom["family"] = family_labels.get(
            pf,
            analysis.get("part_type") or geom.get("family") or "—",
        )
    if analysis.get("part_type") and "part_type" not in geom:
        geom["part_type"] = analysis["part_type"]

    holes = analysis.get("holes") or geom.get("holes")
    shafts = analysis.get("shafts") or geom.get("shafts")
    if holes is not None:
        geom["holes"] = holes
    if shafts is not None:
        geom["shafts"] = shafts

    record: Dict[str, Any] = {
        "project_name": project_name,
        "step_analysis_version": analysis_version,
        "step_file_digest": step_digest,
        "volume": analysis.get("volume"),
        "surface_area": analysis.get("surface_area"),
        "dimensions": analysis.get("dimensions") or {},
        "geometry": geom,
        "holes": holes,
        "shafts": shafts,
        "model_size": analysis.get("model_size") or {},
        "finished_dimensions": analysis.get("model_size") or {},
        "bbox_dimensions": analysis.get("bbox_dimensions") or {},
        "operations": analysis.get("operations") or [],
        "operation_type": analysis.get("operation_type", ""),
        "workpiece": analysis.get("workpiece") or {},
        "workpiece_analysis": analysis.get("workpiece") or {},
        "part_family": analysis.get("part_family", ""),
        "part_type": analysis.get("part_type", ""),
        "rod_features": analysis.get("rod_features"),
        "face_count": analysis.get("face_count"),
        "edge_count": analysis.get("edge_count"),
        "vertex_count": analysis.get("vertex_count"),
        "surface_to_volume_ratio": analysis.get("surface_to_volume_ratio"),
        "detail_index": analysis.get("detail_index"),
        "elongation_index": analysis.get("elongation_index"),
        "complexity": analysis.get("complexity") or geom.get("complexity"),
        "thin_walls": analysis.get("thin_walls", geom.get("thin_walls")),
        "min_wall_thickness_mm": analysis.get("min_wall_thickness_mm")
        or geom.get("min_wall_thickness_mm"),
        "price_primitive": analysis.get("price_primitive"),
        "center_of_mass": analysis.get("center_of_mass"),
        "principal_axes": analysis.get("principal_axes"),
        "inertia_matrix": analysis.get("inertia_matrix"),
        "projection_areas": analysis.get("projection_areas"),
        "has_internal_void": analysis.get("has_internal_void"),
        "void_volume_mm3": analysis.get("void_volume_mm3"),
        "cad_color": analysis.get("cad_color"),
        "cad_material": analysis.get("cad_material"),
        "part_name": analysis.get("part_name"),
        "extraction": analysis.get("extraction"),
        "step_analysis": analysis,
    }
    return record


def merge_user_fields(
    record: Dict[str, Any],
    *,
    material: str = None,
    workpiece_type: str = None,
    diam: int = None,
    length: int = None,
    width: int = None,
    height: int = None,
    cost_per_hour: int = None,
    cam_rate: int = None,
    batch_size: int = None,
    volume: float = None,
    casting_type: str = None,
    casting_material: str = None,
    shrink_pct: float = None,
    allowance_mm: float = None,
) -> Dict[str, Any]:
    """Дополнить запись полями заготовки / UI."""
    out = dict(record)
    if material is not None:
        out["material"] = material
    if workpiece_type is not None:
        out["workpiece_type"] = workpiece_type
    if diam is not None:
        out["diam"] = diam
    if length is not None:
        out["length"] = length
    if width is not None:
        out["width"] = width
    if height is not None:
        out["height"] = height
    if cost_per_hour is not None:
        out["cost_per_hour"] = cost_per_hour
    if cam_rate is not None:
        out["cam_rate"] = cam_rate
    if batch_size is not None:
        out["batch_size"] = batch_size
    if volume is not None:
        out["volume"] = volume
    if casting_type is not None:
        out["casting_type"] = casting_type
    if casting_material is not None:
        out["casting_material"] = casting_material
    if shrink_pct is not None:
        out["shrink_pct"] = shrink_pct
    if allowance_mm is not None:
        out["allowance_mm"] = allowance_mm
    return out


def persist_step_analysis(
    project_name: str,
    analysis: Dict[str, Any],
    user_folder: str = "",
    storage: str = "projects",
    *,
    analysis_version: str = "",
    step_digest: str = "",
    preserve_user_fields: bool = True,
    **user_overrides,
) -> None:
    """Сохранить полный анализ STEP в data.txt, не затирая материал/заготовку."""
    existing = load_project_data(project_name, user_folder, storage=storage) if preserve_user_fields else {}
    record = record_from_step_analysis(
        analysis,
        project_name,
        analysis_version=analysis_version,
        step_digest=step_digest,
    )
    if preserve_user_fields:
        for key in _USER_SCALAR_KEYS:
            if key in existing and key not in user_overrides:
                record[key] = existing[key]
    record.update({k: v for k, v in user_overrides.items() if v is not None})
    save_project_data(project_name, record, user_folder, storage=storage)


def user_params_slice(data: Dict[str, Any]) -> Dict[str, Any]:
    """Только поля заготовки для совместимости с load_project_params."""
    out = {}
    for key in _USER_SCALAR_KEYS:
        if key in data and data[key] is not None:
            out[key] = data[key]
    return out
