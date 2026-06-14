"""OCC: STEP solid → outward offset (allowance) → trimesh."""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class AllowanceOffsetError(Exception):
    """Offset не сошёлся или OCC недоступен."""


def occ_available() -> bool:
    try:
        from OCC.Core.STEPControl import STEPControl_Reader  # noqa: F401

        return True
    except ImportError:
        return False


def read_step_shape(step_path: str):
    from OCC.Core.STEPControl import STEPControl_Reader

    reader = STEPControl_Reader()
    if reader.ReadFile(step_path) != 1:
        raise AllowanceOffsetError("Не удалось прочитать STEP")
    reader.TransferRoots()
    shape = reader.OneShape()
    if shape.IsNull():
        raise AllowanceOffsetError("Пустая геометрия STEP")
    return shape


def occ_bbox_span(shape) -> float:
    from OCC.Core.Bnd import Bnd_Box
    from OCC.Core.BRepBndLib import brepbndlib_Add

    bbox = Bnd_Box()
    brepbndlib_Add(shape, bbox)
    xmin, ymin, zmin, xmax, ymax, zmax = bbox.Get()
    return float(max(xmax - xmin, ymax - ymin, zmax - zmin, 1e-9))


def _fix_shape(shape):
    from OCC.Core.ShapeFix import ShapeFix_Shape

    fix = ShapeFix_Shape(shape)
    fix.Perform()
    fixed = fix.Shape()
    return fixed if fixed and not fixed.IsNull() else shape


def _sew_shape(shape):
    from OCC.Core.BRepBuilderAPI import BRepBuilderAPI_Sewing

    sewer = BRepBuilderAPI_Sewing(1e-3)
    sewer.Add(shape)
    sewer.Perform()
    sewn = sewer.SewedShape()
    return sewn if sewn and not sewn.IsNull() else shape


def _prepare_shape(shape):
    return _fix_shape(_sew_shape(shape))


# OCC иногда падает на «к round» значениях (напр. 5.0 мм на Корзине); ±0.1 мм визуально не заметны.
_OFFSET_PERTURBATIONS_MM = (0.0, 0.05, -0.05, 0.1, -0.1, 0.15, -0.15, 0.2, -0.2, 0.25, -0.25)


def _perform_offset_join(base, dist: float):
    from OCC.Core.BRepOffsetAPI import BRepOffsetAPI_MakeOffsetShape

    tol = max(1e-3, dist * 1e-4)
    mk = BRepOffsetAPI_MakeOffsetShape()
    try:
        mk.PerformByJoin(base, dist, tol)
    except Exception as exc:
        raise AllowanceOffsetError(f"OCC PerformByJoin: {exc}") from exc
    if not mk.IsDone():
        raise AllowanceOffsetError("OCC offset не сошёлся (IsDone=false)")
    result = mk.Shape()
    if result.IsNull():
        raise AllowanceOffsetError("OCC offset вернул пустую форму")
    return result


def offset_shape_outward(shape, allowance_mm: float):
    """Положительный offset наружу на allowance_mm (единицы STEP, обычно мм)."""
    dist = float(allowance_mm)
    if dist <= 0:
        raise AllowanceOffsetError("allowance_mm must be > 0")

    base = _prepare_shape(shape)
    last_err: AllowanceOffsetError | None = None
    for delta in _OFFSET_PERTURBATIONS_MM:
        trial = dist + delta
        if trial <= 0:
            continue
        try:
            return _perform_offset_join(base, trial)
        except AllowanceOffsetError as exc:
            last_err = exc
            continue
    raise last_err or AllowanceOffsetError(f"OCC offset не сошёлся на {dist} мм")


def _count_faces(shape) -> int:
    from OCC.Core.TopAbs import TopAbs_FACE
    from OCC.Core.TopExp import TopExp_Explorer

    exp = TopExp_Explorer(shape, TopAbs_FACE)
    n = 0
    while exp.More():
        n += 1
        exp.Next()
    return n


def _mesh_shape(shape, linear_deflection: float, angular_deflection: float) -> None:
    from OCC.Core.BRepMesh import BRepMesh_IncrementalMesh

    mesher = BRepMesh_IncrementalMesh(shape, linear_deflection, False, angular_deflection, True)
    mesher.Perform()


def _extract_shape_mesh(shape) -> tuple[list[list[float]], list[list[int]], int, int]:
    from OCC.Core.BRep import BRep_Tool
    from OCC.Core.TopAbs import TopAbs_FACE, TopAbs_REVERSED
    from OCC.Core.TopExp import TopExp_Explorer
    from OCC.Core.TopLoc import TopLoc_Location
    from OCC.Core.TopoDS import topods

    vertices: list[list[float]] = []
    faces: list[list[int]] = []
    offset = 0
    skipped = 0
    total = 0

    exp = TopExp_Explorer(shape, TopAbs_FACE)
    while exp.More():
        total += 1
        face = topods.Face(exp.Current())
        loc = TopLoc_Location()
        triangulation = BRep_Tool.Triangulation(face, loc)
        if triangulation is None:
            skipped += 1
            exp.Next()
            continue
        trsf = loc.Transformation()
        reversed_face = face.Orientation() == TopAbs_REVERSED
        n_nodes = triangulation.NbNodes()
        for i in range(1, n_nodes + 1):
            p = triangulation.Node(i)
            p.Transform(trsf)
            vertices.append([p.X(), p.Y(), p.Z()])
        n_triangles = triangulation.NbTriangles()
        for i in range(1, n_triangles + 1):
            tri = triangulation.Triangle(i)
            n1, n2, n3 = tri.Get()
            if reversed_face:
                n2, n3 = n3, n2
            faces.append([offset + n1 - 1, offset + n2 - 1, offset + n3 - 1])
        offset += n_nodes
        exp.Next()

    return vertices, faces, skipped, total


def shape_to_trimesh(shape, *, linear_deflection: float = 0.5, angular_deflection: float = 0.5):
    import numpy as np
    import trimesh

    total_faces = _count_faces(shape)
    mesh_steps = [
        (linear_deflection, angular_deflection),
        (max(linear_deflection * 0.4, 0.08), max(angular_deflection * 0.7, 0.2)),
        (max(linear_deflection * 0.15, 0.03), max(angular_deflection * 0.5, 0.12)),
    ]

    vertices: list[list[float]] = []
    faces: list[list[int]] = []
    skipped = total_faces
    for lin, ang in mesh_steps:
        _mesh_shape(shape, lin, ang)
        vertices, faces, skipped, _ = _extract_shape_mesh(shape)
        if vertices and faces and skipped == 0:
            break
        if vertices and faces and total_faces > 0 and skipped / total_faces <= 0.01:
            break

    if not vertices or not faces:
        raise AllowanceOffsetError("OCC triangulation пустая")
    if skipped > 0:
        logger.warning("OCC triangulation: пропущено граней %s из %s", skipped, total_faces)

    return trimesh.Trimesh(vertices=np.asarray(vertices, dtype=np.float64), faces=np.asarray(faces, dtype=np.int64))


def offset_step_to_trimesh(step_path: str, allowance_mm: float):
    if not occ_available():
        raise AllowanceOffsetError("OCC недоступен")
    shape = read_step_shape(step_path)
    offset = offset_shape_outward(shape, allowance_mm)
    mesh = shape_to_trimesh(offset)
    return mesh, shape
