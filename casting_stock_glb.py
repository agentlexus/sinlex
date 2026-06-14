"""Кэш и генерация GLB заготовки (stock) с OCC offset для литья."""
from __future__ import annotations

import json
import logging
import os
import time

logger = logging.getLogger(__name__)

STOCK_OFFSET_ALGO_VERSION = 3


def allowance_cache_tag(allowance_mm: float) -> str:
    return f"{float(allowance_mm):.1f}"


def stock_glb_filename(safe_name: str, allowance_mm: float) -> str:
    return f"{safe_name}.stock_{allowance_cache_tag(allowance_mm)}.glb"


def stock_glb_path(pdir: str, safe_name: str, allowance_mm: float) -> str:
    return os.path.join(pdir, stock_glb_filename(safe_name, allowance_mm))


def stock_meta_path(stock_glb_path: str) -> str:
    return f"{stock_glb_path}.meta.json"


def invalidate_stock_glbs(pdir: str) -> None:
    if not os.path.isdir(pdir):
        return
    for name in os.listdir(pdir):
        full = os.path.join(pdir, name)
        if ".stock_" in name and (name.endswith(".glb") or name.endswith(".glb.meta.json")):
            try:
                os.remove(full)
            except OSError:
                pass
    legacy = os.path.join(pdir, "stock_meta.json")
    if os.path.isfile(legacy):
        try:
            os.remove(legacy)
        except OSError:
            pass


def invalidate_stock_glbs_for_project(project_name: str, user_folder: str = "") -> None:
    from casting_io import _project_dir

    invalidate_stock_glbs(_project_dir(project_name, user_folder))


def _load_part_trimesh(part_glb_path: str):
    import trimesh

    mesh = trimesh.load(part_glb_path, force="mesh")
    if isinstance(mesh, trimesh.Scene):
        geoms = [g for g in mesh.geometry.values() if isinstance(g, trimesh.Trimesh)]
        if not geoms:
            raise ValueError("Пустой part GLB")
        mesh = trimesh.util.concatenate(geoms)
    if not isinstance(mesh, trimesh.Trimesh) or not len(mesh.vertices):
        raise ValueError("Пустой part GLB")
    return mesh


def _uniform_scale_to_part(part_mesh, occ_shape) -> float:
    from casting_allowance_offset import occ_bbox_span

    occ_span = occ_bbox_span(occ_shape)
    part_ext = part_mesh.bounds[1] - part_mesh.bounds[0]
    part_span = float(max(part_ext))
    if occ_span <= 0 or part_span <= 0:
        return 1.0
    return part_span / occ_span


def _write_stock_meta(out_path: str, *, allowance_mm: float, stp_mtime: float) -> None:
    meta = {
        "algo_version": STOCK_OFFSET_ALGO_VERSION,
        "allowance_mm": float(allowance_mm),
        "stp_mtime": stp_mtime,
        "generated_at": time.time(),
    }
    with open(stock_meta_path(out_path), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)


def _cache_valid(out_path: str, stp_path: str, allowance_mm: float) -> bool:
    if not os.path.isfile(out_path):
        return False
    if not os.path.isfile(stp_path):
        return False
    if os.path.getmtime(out_path) < os.path.getmtime(stp_path):
        return False
    meta_path = stock_meta_path(out_path)
    if not os.path.isfile(meta_path):
        return True
    try:
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)
        if meta.get("algo_version") != STOCK_OFFSET_ALGO_VERSION:
            return False
        if float(meta.get("allowance_mm", -1)) != float(allowance_mm):
            return False
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return False
    return True



def _finalize_stock_mesh(mesh):
    """Сшивка вершин и очистка; ориентация граней — из OCC Face.Orientation()."""
    try:
        mesh.merge_vertices()
    except Exception:
        pass
    try:
        mesh.remove_degenerate_faces()
        mesh.remove_duplicate_faces()
    except Exception:
        pass
    return mesh

def build_stock_glb(stp_path: str, part_glb_path: str, out_path: str, allowance_mm: float) -> str:
    from casting_allowance_offset import offset_step_to_trimesh

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    stock_mesh, occ_shape = offset_step_to_trimesh(stp_path, allowance_mm)
    part_mesh = _load_part_trimesh(part_glb_path)
    scale = _uniform_scale_to_part(part_mesh, occ_shape)
    if abs(scale - 1.0) > 1e-9:
        stock_mesh.apply_scale(scale)
    stock_mesh = _finalize_stock_mesh(stock_mesh)
    stock_mesh.export(out_path, file_type="glb")
    _write_stock_meta(out_path, allowance_mm=allowance_mm, stp_mtime=os.path.getmtime(stp_path))
    logger.info("stock GLB offset OK: %s allowance=%.1f", out_path, allowance_mm)
    return out_path


def ensure_stock_glb_cached(stp_path: str, part_glb_path: str, out_path: str, allowance_mm: float) -> str:
    if _cache_valid(out_path, stp_path, allowance_mm):
        return out_path
    if os.path.isfile(out_path):
        try:
            os.remove(out_path)
        except OSError:
            pass
    meta = stock_meta_path(out_path)
    if os.path.isfile(meta):
        try:
            os.remove(meta)
        except OSError:
            pass
    build_stock_glb(stp_path, part_glb_path, out_path, allowance_mm)
    return out_path
