"""
Глубокий анализ STEP: extraction_tool (pythonocc) + fallback trimesh.
"""
from __future__ import annotations

import os
import sys

# Корень Sinlex в path
_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


def analyze_step(file_bytes: bytes, *, force_wall_thickness: bool = False) -> dict:
    """
    Принимает байты STEP-файла, возвращает структурированный анализ для API/UI.
    """
    try:
        from extraction_tool.extractor import extract_step_bytes, to_api_format

        metrics = extract_step_bytes(
            file_bytes,
            file_name="upload.stp",
            skip_edges=True,
            fast=len(file_bytes) >= 512 * 1024,
            force_wall_thickness=force_wall_thickness,
        )
        if metrics.get("status") == "ok":
            return to_api_format(metrics)
        return {
            "volume": 0,
            "surface_area": 0,
            "dimensions": {"x": 0, "y": 0, "z": 0},
            "geometry": {},
            "error": metrics.get("error_message", "Ошибка извлечения"),
        }
    except ImportError:
        return _analyze_step_legacy(file_bytes)
    except Exception as e:
        legacy = _analyze_step_legacy(file_bytes)
        if legacy.get("volume", 0) > 0:
            legacy["error"] = f"Deep extract failed, legacy used: {e}"
            return legacy
        return {
            "volume": 0,
            "surface_area": 0,
            "dimensions": {"x": 0, "y": 0, "z": 0},
            "geometry": {},
            "error": str(e),
        }


def _trimesh_analyze(file_bytes: bytes) -> dict:
    """Упрощённый анализ через trimesh (без pythonocc)."""
    import tempfile

    with tempfile.NamedTemporaryFile(delete=False, suffix=".stp") as tmp:
        tmp.write(file_bytes)
        path = tmp.name
    try:
        from api.services.step_convert import _load_trimesh, _trimesh_dims_mm, _trimesh_volume_mm3

        mesh = _load_trimesh(path)
        vol = _trimesh_volume_mm3(mesh)
        d = _trimesh_dims_mm(mesh)
        return {
            "volume": round(vol, 3),
            "surface_area": 0,
            "dimensions": d,
            "face_count": 0,
            "surface_to_volume_ratio": 0,
            "complexity": "неизвестно",
            "thin_walls": False,
            "part_type": "неизвестно",
            "operation_type": "—",
            "geometry": {},
            "error": "",
        }
    except Exception as e:
        return {
            "volume": 0,
            "surface_area": 0,
            "dimensions": {"x": 0, "y": 0, "z": 0},
            "geometry": {},
            "error": str(e),
        }
    finally:
        if os.path.exists(path):
            os.unlink(path)


def _analyze_step_legacy(file_bytes: bytes) -> dict:
    """Прежний анализ (упрощённый), если extraction_tool недоступен."""
    import tempfile

    with tempfile.NamedTemporaryFile(delete=False, suffix=".stp") as tmp:
        tmp.write(file_bytes)
        step_path = tmp.name
    try:
        from extraction_tool.extractor import extract_step_path, to_api_format

        m = extract_step_path(step_path)
        if m.get("status") == "ok":
            return to_api_format(m)
    except Exception:
        pass
    finally:
        if os.path.exists(step_path):
            os.unlink(step_path)

    return _trimesh_analyze(file_bytes)
