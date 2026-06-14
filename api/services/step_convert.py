"""STEP/STP → GLB conversion (OCC metadata when available, trimesh + cascadio fallback)."""
import os

from fastapi import HTTPException


def _occ_available() -> bool:
    try:
        from OCC.Core.STEPControl import STEPControl_Reader  # noqa: F401

        return True
    except ImportError:
        return False


def _read_step_shape_occ(step_path: str):
    from OCC.Core.STEPControl import STEPControl_Reader
    from OCC.Core.BRepGProp import brepgprop_VolumeProperties
    from OCC.Core.GProp import GProp_GProps
    from OCC.Core.Bnd import Bnd_Box
    from OCC.Core.BRepBndLib import brepbndlib_Add

    reader = STEPControl_Reader()
    if reader.ReadFile(step_path) != 1:
        raise ValueError("Не удалось прочитать STEP")
    reader.TransferRoots()
    shape = reader.OneShape()
    props = GProp_GProps()
    brepgprop_VolumeProperties(shape, props)
    volume = props.Mass()
    bbox = Bnd_Box()
    brepbndlib_Add(shape, bbox)
    xmin, ymin, zmin, xmax, ymax, zmax = bbox.Get()
    dims = {
        "x": round(xmax - xmin, 1),
        "y": round(ymax - ymin, 1),
        "z": round(zmax - zmin, 1),
    }
    return volume, dims


def _load_trimesh(step_path: str):
    import trimesh

    mesh = trimesh.load(step_path, file_type="step")
    if isinstance(mesh, trimesh.Scene):
        combined = trimesh.Trimesh()
        for geom in mesh.geometry.values():
            if isinstance(geom, trimesh.Trimesh):
                combined += geom
        mesh = combined
    if not isinstance(mesh, trimesh.Trimesh) or not len(mesh.vertices):
        raise ValueError("Пустая геометрия STEP")
    return mesh


def _trimesh_volume_mm3(mesh) -> float:
    vol = float(mesh.volume) if mesh.volume else 0.0
    if 0 < vol < 1:
        vol *= 1_000_000_000
    return vol


def _trimesh_dims_mm(mesh) -> dict:
    if mesh.bounds is None:
        return {"x": 0.0, "y": 0.0, "z": 0.0}
    ext = mesh.bounds[1] - mesh.bounds[0]
    scale = 1000.0 if float(max(ext)) < 10 else 1.0
    return {
        "x": round(float(ext[0]) * scale, 1),
        "y": round(float(ext[1]) * scale, 1),
        "z": round(float(ext[2]) * scale, 1),
    }


def _read_step_shape_trimesh(step_path: str):
    mesh = _load_trimesh(step_path)
    return _trimesh_volume_mm3(mesh), _trimesh_dims_mm(mesh)


def _read_step_shape(step_path: str):
    if _occ_available():
        try:
            return _read_step_shape_occ(step_path)
        except Exception:
            pass
    return _read_step_shape_trimesh(step_path)


def _export_glb(step_path: str, glb_path: str) -> None:
    mesh = _load_trimesh(step_path)
    mesh.export(glb_path, file_type="glb")


def convert_step_file_to_glb(step_path: str, glb_path: str) -> tuple[float, dict]:
    volume, dims = _read_step_shape(step_path)
    _export_glb(step_path, glb_path)
    return volume, dims


def step_bytes_to_glb_response(step_path: str, glb_path: str) -> tuple[bytes, float, dict]:
    volume, dims = convert_step_file_to_glb(step_path, glb_path)
    with open(glb_path, "rb") as f:
        return f.read(), volume, dims


def ensure_glb_from_stp(stp_path: str, glb_path: str) -> None:
    if os.path.exists(glb_path):
        return
    if not os.path.exists(stp_path):
        raise HTTPException(404, "GLB не найден")
    try:
        convert_step_file_to_glb(stp_path, glb_path)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Не удалось сгенерировать GLB: {str(e)}") from e
    if not os.path.exists(glb_path):
        raise HTTPException(404, "GLB не найден")
