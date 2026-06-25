"""
Глубокое извлечение метрик из STEP (pythonocc-core + numpy).
Используется пакетной утилитой main.py и API Sinlex (step_analyzer).
"""
from __future__ import annotations

import json
import math
import time
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from . import config

# --- Заглушки / TODO ---
WALL_THICKNESS_NOTE = "OCC IntCurvesFace + BRepClass3d (ray-casting по нормалям граней)"
CURVATURE_TODO = "TODO: средняя/мин/макс кривизна граней (BRepAdaptor_Curve / sampling)"


def _volume_props(shape) -> Tuple[float, float, Any, np.ndarray]:
    """Объём, площадь поверхности, центр масс, матрица инерции 3×3."""
    from OCC.Core.GProp import GProp_GProps
    from OCC.Core.BRepGProp import brepgprop

    vp = GProp_GProps()
    sp = GProp_GProps()
    try:
        brepgprop.VolumeProperties(shape, vp)
        brepgprop.SurfaceProperties(shape, sp)
    except AttributeError:
        from OCC.Core.BRepGProp import brepgprop_VolumeProperties, brepgprop_SurfaceProperties
        brepgprop_VolumeProperties(shape, vp)
        brepgprop_SurfaceProperties(shape, sp)

    volume = float(vp.Mass())
    area = float(sp.Mass())
    com = vp.CentreOfMass()
    center = np.array([com.X(), com.Y(), com.Z()], dtype=float)

    mat = vp.MatrixOfInertia()
    inertia = np.array(
        [[mat.Value(i, j) for j in range(1, 4)] for i in range(1, 4)],
        dtype=float,
    )
    return volume, area, center, inertia


def _principal_axes(inertia: np.ndarray) -> Dict[str, Any]:
    """Главные оси инерции (собственные векторы симметричной матрицы)."""
    try:
        w, v = np.linalg.eigh(inertia)
        return {
            "eigenvalues": [float(x) for x in w],
            "eigenvectors": v.tolist(),
        }
    except Exception as e:
        return {"error": str(e)}


def _bounding_box(shape) -> Dict[str, float]:
    from OCC.Core.Bnd import Bnd_Box
    from OCC.Core.BRepBndLib import brepbndlib_Add

    box = Bnd_Box()
    brepbndlib_Add(shape, box)
    xmin, ymin, zmin, xmax, ymax, zmax = box.Get()
    dx, dy, dz = xmax - xmin, ymax - ymin, zmax - zmin
    return {
        "xmin": xmin, "ymin": ymin, "zmin": zmin,
        "xmax": xmax, "ymax": ymax, "zmax": zmax,
        "x": dx, "y": dy, "z": dz,
        "proj_xy": dx * dy,
        "proj_xz": dx * dz,
        "proj_yz": dy * dz,
    }


def _topology_counts(shape) -> Dict[str, int]:
    from OCC.Core.TopExp import TopExp_Explorer
    from OCC.Core.TopAbs import TopAbs_FACE, TopAbs_EDGE, TopAbs_VERTEX, TopAbs_SOLID

    def count(topo_type) -> int:
        n = 0
        exp = TopExp_Explorer(shape, topo_type)
        while exp.More():
            n += 1
            exp.Next()
        return n

    return {
        "face_count": count(TopAbs_FACE),
        "edge_count": count(TopAbs_EDGE),
        "vertex_count": count(TopAbs_VERTEX),
        "solid_count": max(1, count(TopAbs_SOLID)),
    }


def _bbox_axis_profile(bbox: Dict[str, float]) -> Dict[str, Any]:
    """
    Оси по AABB: вал — два малых размера ≈ Ø, большой — длина;
    диск — два больших ≈ Ø, малый — толщина.
    """
    sm, mid, lg = sorted([bbox["x"], bbox["y"], bbox["z"]])
    elongation = lg / max(sm, 1e-9) if sm > 0 else 1.0
    cross_shaft = sm / max(mid, 1e-9) >= 0.82
    cross_disc = mid / max(lg, 1e-9) >= 0.82
    is_elongated_rod = cross_shaft and elongation >= 1.8
    is_disc = cross_disc and sm / max(lg, 1e-9) < 0.55
    if is_elongated_rod:
        rod_d, rod_l = max(sm, mid), lg
    elif is_disc:
        rod_d, rod_l = max(mid, lg), sm
    else:
        rod_d, rod_l = _rod_dims_from_extents(sm, mid, lg)
    return {
        "elongation": elongation,
        "cross_shaft": cross_shaft,
        "cross_disc": cross_disc,
        "cross_round": cross_shaft or cross_disc,
        "is_elongated_rod": is_elongated_rod,
        "is_disc": is_disc,
        "diameter": rod_d,
        "length": rod_l,
        "min_cross": sm,
    }


def _is_hybrid_turn_mill_body(
    face_counts: Dict[str, int],
    bbox: Dict[str, float],
    *,
    face_count: int = 0,
    part_name: str = "",
) -> bool:
    """
    Вал намотки и аналоги: длинное тело с прямоугольным/коробчатым сечением,
    токарная обработка торцов (2 установки) + фрезерные карманы по бокам.
    """
    name_low = (part_name or "").lower()
    if any(k in name_low for k in ("намотк", "намоточ", "winding")):
        return True
    axis = _bbox_axis_profile(bbox)
    if axis["elongation"] < 2.0 or axis["cross_round"]:
        return False
    cyl = int(face_counts.get("cyl_face_count") or 0)
    plane = int(face_counts.get("plane_face_count") or 0)
    torus = int(face_counts.get("torus_face_count") or 0)
    fc = face_count or _face_count_total(face_counts, {})
    sm, mid, lg = sorted(
        [float(bbox.get("x") or 0), float(bbox.get("y") or 0), float(bbox.get("z") or 0)]
    )
    box_section = mid / max(lg, 1e-9) >= 0.08 and sm / max(mid, 1e-9) >= 0.3
    if not box_section:
        return False
    if cyl >= 12 and plane >= 10 and fc >= 50:
        return True
    if cyl >= 25 and axis["elongation"] >= 3.5:
        return True
    if torus >= 6 and plane >= 18 and axis["elongation"] >= 3.0:
        return True
    return False


def _cyl_hole_max_diameter(bbox: Dict[str, float], avg_dim: float) -> float:
    """Порог Ø: цилиндр меньше — отверстие, больше — наружный контур вала."""
    axis = _bbox_axis_profile(bbox)
    if axis["is_elongated_rod"]:
        return axis["min_cross"] * 0.68
    return avg_dim * 0.75


# --- Семейства деталей: пруток | крыльчатка | плита | крупногабарит ---

OVERSIZE_MIN_DIM_MM = 400.0
OVERSIZE_MIN_MASS_KG = 100.0
# Порог массы по объёму STEP, если материал ещё не выбран (сталь 45)
OVERSIZE_DEFAULT_DENSITY_G_CM3 = 7.85


def is_oversize_part(
    bbox: Dict[str, float],
    volume_mm3: float,
    *,
    density_g_cm3: float = OVERSIZE_DEFAULT_DENSITY_G_CM3,
) -> bool:
    """Крупногабарит: габарит > 400 мм и/или масса готовой детали > 100 кг."""
    if not bbox:
        return False
    max_dim = max(
        float(bbox.get("x") or 0),
        float(bbox.get("y") or 0),
        float(bbox.get("z") or 0),
    )
    if max_dim > OVERSIZE_MIN_DIM_MM:
        return True
    mass_kg = max(float(volume_mm3 or 0), 0.0) * float(density_g_cm3) / 1e6
    return mass_kg > OVERSIZE_MIN_MASS_KG


def _vec3_gp(v) -> Tuple[float, float, float]:
    return float(v.X()), float(v.Y()), float(v.Z())


def _normalize_vec(v: Tuple[float, float, float]) -> Tuple[float, float, float]:
    ln = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])
    if ln < 1e-12:
        return (0.0, 0.0, 1.0)
    return (v[0] / ln, v[1] / ln, v[2] / ln)


def _angle_between_dirs(a: Tuple[float, float, float], b: Tuple[float, float, float]) -> float:
    la = math.sqrt(sum(x * x for x in a))
    lb = math.sqrt(sum(x * x for x in b))
    if la < 1e-12 or lb < 1e-12:
        return 0.0
    dot = abs(sum(x * y for x, y in zip(a, b))) / (la * lb)
    return math.degrees(math.acos(min(1.0, max(-1.0, dot))))


def _dist_point_to_axis(
    p: Tuple[float, float, float],
    axis_pt: Tuple[float, float, float],
    axis_dir: Tuple[float, float, float],
) -> float:
    ax, ay, az = p[0] - axis_pt[0], p[1] - axis_pt[1], p[2] - axis_pt[2]
    dx, dy, dz = axis_dir
    cross = (ay * dz - az * dy, az * dx - ax * dz, ax * dy - ay * dx)
    return math.sqrt(cross[0] ** 2 + cross[1] ** 2 + cross[2] ** 2)


def _cylindrical_shell_kind(shape, surf, eps: float = 0.05) -> str:
    """P±ε·n: outer_shell | bore_shell | ambiguous."""
    from OCC.Core.BRepClass3d import BRepClass3d_SolidClassifier
    from OCC.Core.TopAbs import TopAbs_IN, TopAbs_OUT
    from OCC.Core.gp import gp_Pnt, gp_Vec

    u1, u2 = surf.FirstUParameter(), surf.LastUParameter()
    v1, v2 = surf.FirstVParameter(), surf.LastVParameter()
    um, vm = (u1 + u2) / 2, (v1 + v2) / 2
    p = gp_Pnt()
    du, dv = gp_Vec(), gp_Vec()
    surf.D1(um, vm, p, du, dv)
    n = du.Crossed(dv)
    if n.Magnitude() < 1e-9:
        return "ambiguous"
    n.Normalize()
    pp = gp_Pnt(p.X() + eps * n.X(), p.Y() + eps * n.Y(), p.Z() + eps * n.Z())
    pm = gp_Pnt(p.X() - eps * n.X(), p.Y() - eps * n.Y(), p.Z() - eps * n.Z())
    c1 = BRepClass3d_SolidClassifier(shape, pp, 1e-3).State()
    c2 = BRepClass3d_SolidClassifier(shape, pm, 1e-3).State()
    sp = {TopAbs_IN: "IN", TopAbs_OUT: "OUT"}.get(c1, "?")
    sm = {TopAbs_IN: "IN", TopAbs_OUT: "OUT"}.get(c2, "?")
    if sp == "OUT" and sm == "IN":
        return "outer"
    if sp == "IN" and sm == "OUT":
        return "bore"
    return "ambiguous"


def _face_count_total(face_counts: Dict[str, int], topo: Dict[str, int]) -> int:
    fc = topo.get("face_count", 0)
    if fc:
        return fc
    return (
        face_counts.get("cyl_face_count", 0)
        + face_counts.get("plane_face_count", 0)
        + face_counts.get("cone_face_count", 0)
        + face_counts.get("torus_face_count", 0)
        + face_counts.get("other_face_count", 0)
        + face_counts.get("sphere_face_count", 0)
    )


def _is_flat_plate_bbox(bbox: Dict[str, float]) -> bool:
    """
    Плита / педаль / лист с рёбрами: малый габарит по толщине, без овального сечения вала/диска.
    Отсекает ложную «крыльчатку» из-за скруглений и цилиндров рёбер.
    """
    sm, mid, lg = sorted(
        [float(bbox.get("x") or 0), float(bbox.get("y") or 0), float(bbox.get("z") or 0)]
    )
    if lg < 1e-6:
        return False
    if sm / lg >= 0.25:
        return False
    if mid / lg < 0.18:
        return False
    axis = _bbox_axis_profile(bbox)
    if axis.get("cross_disc") or axis.get("cross_shaft"):
        return False
    return True


def _is_impeller_family(
    face_counts: Dict[str, int],
    topo: Dict[str, int],
    *,
    bbox: Optional[Dict[str, float]] = None,
    detail_index: float = 0.0,
) -> bool:
    """
    Крыльчатка / колесо компрессора: сечение лопатки — сложный сплайн (BSPL/TORUS).
    Корпус с прямолинейными рёбрами охлаждения: много PLANE, не крыльчатка.
    Плоская плита с рёбрами (педаль) — не крыльчатка.
    Гильза/пруток с тороидальными галтелями — не крыльчатка (нужны сплайны лопаток).
    """
    if bbox and _is_flat_plate_bbox(bbox):
        return False

    fc = topo.get("face_count", 0)
    cyl = face_counts.get("cyl_face_count", 0)
    plane = face_counts.get("plane_face_count", 0)
    torus = face_counts.get("torus_face_count", 0)
    bspl = face_counts.get("other_face_count", 0)
    n = _face_count_total(face_counts, topo)
    if n < 1:
        return False

    plane_share = plane / n
    bspl_share = bspl / n
    freeform_share = (torus + bspl) / n
    cyl_share = cyl / n

    axis = _bbox_axis_profile(bbox) if bbox else {}

    # Тороиды без сплайнов на вытянутом теле вращения — галтели, не лопатки
    if axis.get("is_elongated_rod") and cyl_share >= 0.12 and bspl < 40:
        return False

    # Рёбра охлаждения и грани корпуса — преимущественно плоские, не лопатки
    if plane_share >= 0.38:
        return False

    # Без доли сплайновых граней сечение не похоже на лопатку (тороиды сами по себе — галтели)
    curved_blade_evidence = (
        bspl >= 55
        or bspl_share >= 0.18
        or (torus >= 20 and bspl >= 15)
        or (freeform_share >= 0.45 and bspl >= max(int(torus * 0.5), 25))
    )
    if not curved_blade_evidence:
        return False

    rotational = bool(axis.get("cross_round"))

    if bspl >= 60:
        return True
    if torus >= 80 and bspl_share >= 0.12:
        return rotational or bspl >= 40
    if fc >= 200 and freeform_share >= 0.4 and bspl_share >= 0.10:
        return rotational or bspl_share >= 0.12
    if detail_index >= 17.0 and freeform_share >= 0.35 and fc >= 120 and bspl_share >= 0.08:
        return rotational
    if torus >= 40 and bspl >= 40 and freeform_share >= 0.5:
        return True
    return False


def _detect_part_family(
    face_counts: Dict[str, int],
    bbox: Dict[str, float],
    topo: Dict[str, int],
    *,
    detail_index: float = 0.0,
    rot_profile: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Три семьи: rod (пруток/вал), impeller (крыльчатка), plate (плиты и корпуса).
    Порядок: крыльчатка → пруток → плита.
    """
    fc = topo.get("face_count", 0)
    cyl = face_counts.get("cyl_face_count", 0)
    plane = face_counts.get("plane_face_count", 0)
    torus = face_counts.get("torus_face_count", 0)
    bspl = face_counts.get("other_face_count", 0)
    n = _face_count_total(face_counts, topo)
    if n < 1:
        return "plate"

    plane_share = plane / n
    cyl_share = cyl / n

    axis = _bbox_axis_profile(bbox)
    sm, mid, lg = sorted([bbox["x"], bbox["y"], bbox["z"]])
    box_like = mid / max(lg, 1e-9) >= 0.45 and sm / max(mid, 1e-9) >= 0.35
    if box_like and plane_share >= 0.35 and not axis.get("cross_round"):
        return "plate"

    if _is_flat_plate_bbox(bbox):
        return "plate"

    if _is_impeller_family(face_counts, topo, bbox=bbox, detail_index=detail_index):
        return "impeller"
    # Для family-router: оценка наружного Ø по AABB, если список shafts ещё не построен
    prov_shafts: List[Dict] = []
    if cyl >= 1 and axis.get("cross_round"):
        prov_shafts.append({"diameter": axis["diameter"]})
    rev = _revolution_geometry_profile(
        face_counts, bbox, prov_shafts, rot_profile=rot_profile
    )
    rot_conf = float((rot_profile or {}).get("rotation_confidence") or 0)
    body_d = float(axis.get("diameter") or 0)
    if body_d > config.BAR_STOCK_MAX_D_MM and rot_conf < config.ROT_CONF_FORGING:
        rev = dict(rev)
        rev["rotational"] = False

    # Общее правило: если габариты читаются как "Ø × длина" (круглое поперечное сечение)
    # и тело не превышает параметров прутка, считаем семейство prutok/rod.
    if axis.get("cross_round") and 0 < body_d <= config.BAR_STOCK_MAX_D_MM and rot_conf >= 0.5:
        return "rod"

    if fc <= 10 and cyl >= 1 and torus < 5 and bspl < 3 and rev.get("simple_blank"):
        if body_d <= config.BAR_STOCK_MAX_D_MM or rot_conf >= config.ROT_CONF_FORGING:
            return "rod"

    if axis["is_elongated_rod"] and body_d <= config.BAR_STOCK_MAX_D_MM:
        return "rod"
    if (
        axis["is_elongated_rod"]
        and body_d > config.BAR_STOCK_MAX_D_MM
        and rot_conf >= config.ROT_CONF_FORGING
    ):
        return "rod"

    if (
        rev["rotational"]
        and cyl_share >= 0.12
        and torus < 8
        and bspl < 25
        and fc < 150
    ):
        return "rod"

    if rev["rotational"] and cyl >= 3 and torus < 5 and fc < 120:
        return "rod"

    if axis.get("is_disc") and rev.get("rotational") and cyl >= 3:
        return "rod"

    if (
        rev.get("rotational")
        and axis.get("cross_round")
        and axis["elongation"] >= 1.4
        and cyl_share >= 0.08
        and (body_d <= config.BAR_STOCK_MAX_D_MM or rot_conf >= config.ROT_CONF_FORGING)
    ):
        return "rod"

    # Короткие круглые детали (ролики/диски): высокая вращательность и вклад наружных цилиндров
    # даже при L/D ~ 1.0 должны относиться к семейству rod, чтобы не терять токарку в маршруте.
    if (
        rev.get("rotational")
        and axis.get("cross_round")
        and 0.7 <= axis["elongation"] <= 1.4
        and cyl_share >= 0.6
        and body_d > 0
        and body_d <= config.BAR_STOCK_MAX_D_MM
        and rot_conf >= 0.7
    ):
        return "rod"

    if _is_hybrid_turn_mill_body(face_counts, bbox, face_count=fc):
        return "hybrid_shaft"

    return "plate"


def _resolve_part_family(
    face_counts: Dict[str, int],
    bbox: Dict[str, float],
    topo: Dict[str, int],
    *,
    detail_index: float = 0.0,
    volume_mm3: float = 0.0,
) -> str:
    """Базовое семейство по геометрии; крупногабарит перекрывает при Ø>400 мм или массе >100 кг.

    Дополнительное правило: если габариты читаются как «Ø × длина» (круглое поперечное сечение)
    и Ø не превышает предела прутка BAR_STOCK_MAX_D_MM, считаем семейство прутком (rod).
    """
    base = _detect_part_family(
        face_counts, bbox, topo, detail_index=detail_index
    )
    if is_oversize_part(bbox, volume_mm3):
        return "oversize"

    n = _face_count_total(face_counts, topo)
    cyl_share = face_counts.get("cyl_face_count", 0) / max(n, 1)
    bspl = face_counts.get("other_face_count", 0)
    axis = _bbox_axis_profile(bbox)
    body_d = float(axis.get("diameter") or 0.0)

    if base == "impeller":
        # Гильза/пруток с тороидальными галтелями не должны оставаться крыльчаткой
        if axis.get("is_elongated_rod") and cyl_share >= 0.12 and bspl < 40:
            return "rod"
        return "impeller"

    if axis.get("cross_round") and 0.0 < body_d <= config.BAR_STOCK_MAX_D_MM:
        return "rod"

    return base


def _infer_main_axis_from_cylinders(
    cyl_records: List[Dict[str, Any]],
) -> Tuple[Tuple[float, float, float], Tuple[float, float, float]]:
    """Ось вала по наружным цилиндрам (взвешенное направление)."""
    votes: Dict[Tuple[float, float, float], float] = {}
    for c in cyl_records:
        if c.get("kind") != "outer" or c.get("area", 0) < config.SMALL_FACE_AREA_MM2:
            continue
        d = _normalize_vec(c["axis"])
        key = (round(abs(d[0]), 3), round(abs(d[1]), 3), round(abs(d[2]), 3))
        votes[key] = votes.get(key, 0.0) + c["area"]
    if not votes:
        return (1.0, 0.0, 0.0), (0.0, 0.0, 0.0)
    best_key = max(votes, key=votes.get)
    for c in cyl_records:
        if c.get("kind") != "outer":
            continue
        d = c["axis"]
        key = (round(abs(d[0]), 3), round(abs(d[1]), 3), round(abs(d[2]), 3))
        if key == best_key:
            loc = c.get("loc", (0.0, 0.0, 0.0))
            return _normalize_vec(d), loc
    return _normalize_vec(best_key), (0.0, 0.0, 0.0)


def _collect_cylindrical_face_records(shape, bbox: Dict[str, float]) -> List[Dict[str, Any]]:
    from OCC.Core.TopExp import TopExp_Explorer
    from OCC.Core.TopAbs import TopAbs_FACE
    from OCC.Core.BRepAdaptor import BRepAdaptor_Surface
    from OCC.Core.BRepGProp import brepgprop
    from OCC.Core.GProp import GProp_GProps
    from OCC.Core.GeomAbs import GeomAbs_Cylinder
    from OCC.Core.gp import gp_Pnt

    records: List[Dict[str, Any]] = []
    exp = TopExp_Explorer(shape, TopAbs_FACE)
    idx = 0
    while exp.More():
        face = exp.Current()
        surf = BRepAdaptor_Surface(face)
        if surf.GetType() != GeomAbs_Cylinder:
            idx += 1
            exp.Next()
            continue
        cyl = surf.Cylinder()
        d = 2.0 * float(cyl.Radius())
        ax = cyl.Axis()
        axis_dir = _normalize_vec(_vec3_gp(ax.Direction()))
        loc = _vec3_gp(ax.Location())
        u1, u2 = surf.FirstUParameter(), surf.LastUParameter()
        v1, v2 = surf.FirstVParameter(), surf.LastVParameter()
        p = gp_Pnt()
        surf.D0((u1 + u2) / 2, (v1 + v2) / 2, p)
        cent = _vec3_gp(p)
        kind = _cylindrical_shell_kind(shape, surf)
        fp = GProp_GProps()
        try:
            brepgprop.SurfaceProperties(face, fp)
        except AttributeError:
            from OCC.Core.BRepGProp import brepgprop_SurfaceProperties
            brepgprop_SurfaceProperties(face, fp)
        area = float(fp.Mass())
        u_span = abs(u2 - u1)
        v_span = abs(v2 - v1)
        records.append({
            "idx": idx,
            "d": d,
            "area": area,
            "kind": kind,
            "axis": axis_dir,
            "loc": loc,
            "cent": cent,
            "u_span": u_span,
            "v_span": v_span,
            "circ_span": max(u_span, v_span),
        })
        idx += 1
        exp.Next()
    return records


def _plate_thickness_direction(bbox: Dict[str, float]) -> Tuple[float, float, float]:
    """Единичный вектор вдоль наименьшего габарита AABB (толщина плиты)."""
    dims = [("x", float(bbox.get("x") or 0)), ("y", float(bbox.get("y") or 0)), ("z", float(bbox.get("z") or 0))]
    dims.sort(key=lambda t: t[1])
    if dims[0][0] == "x":
        return (1.0, 0.0, 0.0)
    if dims[0][0] == "y":
        return (0.0, 1.0, 0.0)
    return (0.0, 0.0, 1.0)


def _setup_axis_from_inertia(
    principal: Dict[str, Any],
    bbox: Dict[str, float],
    part_family: str,
    *,
    for_milling: bool,
) -> Optional[np.ndarray]:
    """Ось для подсчёта противоположных плоскостей: токарная — по инерции, плита — мин. момент."""
    if principal.get("error"):
        return None
    try:
        w = np.asarray(principal["eigenvalues"], dtype=float)
        R = np.asarray(principal["eigenvectors"], dtype=float)
    except Exception:
        return None
    if R.shape != (3, 3) or w.shape != (3,):
        return None
    prof = _bbox_axis_profile(bbox)
    pf = (part_family or "").lower()
    if for_milling:
        idx = int(np.argmin(w))
    elif prof.get("is_disc") or (pf == "rod" and prof.get("is_disc")):
        idx = int(np.argmin(w))
    elif prof.get("is_elongated_rod") or pf == "rod":
        idx = int(np.argmax(w))
    else:
        idx = int(np.argmax(w))
    ax = R[:, idx].astype(float)
    n = float(np.linalg.norm(ax))
    if n < 1e-9:
        return None
    return ax / n


def _align_axis_to_thickness(axis: np.ndarray, bbox: Dict[str, float]) -> np.ndarray:
    """Согласовать знак оси с направлением толщины AABB (для плиты)."""
    thick = np.asarray(_plate_thickness_direction(bbox), dtype=float)
    if float(np.dot(axis, thick)) < 0:
        return -axis
    return axis


def _collect_setup_face_elements(
    shape,
    bbox: Dict[str, float],
    avg_dim: float,
) -> List[Dict[str, Any]]:
    """Грани с центроидом/нормалью для критерия «обрабатываемая противоположная плоскость»."""
    from OCC.Core.TopExp import TopExp_Explorer
    from OCC.Core.TopAbs import TopAbs_FACE
    from OCC.Core.BRepAdaptor import BRepAdaptor_Surface
    from OCC.Core.BRepGProp import brepgprop
    from OCC.Core.GProp import GProp_GProps
    from OCC.Core.GeomAbs import (
        GeomAbs_Cylinder, GeomAbs_Plane, GeomAbs_Cone,
        GeomAbs_Sphere, GeomAbs_Torus,
    )
    from OCC.Core.gp import gp_Pnt

    hole_max_d = _cyl_hole_max_diameter(bbox, avg_dim)
    body_d = float(_bbox_axis_profile(bbox).get("diameter") or 0)
    elements: List[Dict[str, Any]] = []
    exp = TopExp_Explorer(shape, TopAbs_FACE)
    while exp.More():
        face = exp.Current()
        surf = BRepAdaptor_Surface(face)
        st = surf.GetType()
        st_name = "other"
        normal: Optional[Tuple[float, float, float]] = None
        cyl_axis: Optional[Tuple[float, float, float]] = None
        cyl_kind = ""
        cyl_d = 0.0
        if st == GeomAbs_Plane:
            st_name = "plane"
            try:
                pl = surf.Plane()
                normal = _normalize_vec(_vec3_gp(pl.Axis().Direction()))
            except Exception:
                pass
        elif st == GeomAbs_Cylinder:
            st_name = "cylinder"
            try:
                cyl = surf.Cylinder()
                cyl_d = 2.0 * float(cyl.Radius())
                cyl_axis = _normalize_vec(_vec3_gp(cyl.Axis().Direction()))
                cyl_kind = _cylindrical_shell_kind(shape, surf)
            except Exception:
                pass
        elif st == GeomAbs_Cone:
            st_name = "cone"
            try:
                cone = surf.Cone()
                cyl_axis = _normalize_vec(_vec3_gp(cone.Axis().Direction()))
                cyl_kind = _cylindrical_shell_kind(shape, surf)
            except Exception:
                pass
        elif st == GeomAbs_Sphere:
            st_name = "sphere"
        elif st == GeomAbs_Torus:
            st_name = "torus"
        else:
            st_name = "other"

        fp = GProp_GProps()
        try:
            brepgprop.SurfaceProperties(face, fp)
        except AttributeError:
            from OCC.Core.BRepGProp import brepgprop_SurfaceProperties
            brepgprop_SurfaceProperties(face, fp)
        area = float(fp.Mass())
        com_f = fp.CentreOfMass()
        cent = (float(com_f.X()), float(com_f.Y()), float(com_f.Z()))
        if st_name in ("cylinder", "cone") and not cent:
            u1, u2 = surf.FirstUParameter(), surf.LastUParameter()
            v1, v2 = surf.FirstVParameter(), surf.LastVParameter()
            p = gp_Pnt()
            surf.D0((u1 + u2) / 2, (v1 + v2) / 2, p)
            cent = _vec3_gp(p)

        elements.append({
            "stype": st_name,
            "area": area,
            "cent": cent,
            "normal": normal,
            "axis": cyl_axis,
            "cyl_kind": cyl_kind,
            "d": cyl_d,
            "hole_max_d": hole_max_d,
            "body_d": body_d,
        })
        exp.Next()
    return elements


def _setup_element_machinable(
    el: Dict[str, Any],
    setup_axis: Tuple[float, float, float],
    mode: str,
) -> bool:
    """Хотя бы один технологический элемент на торце/стороне вдоль оси установки."""
    area = float(el.get("area") or 0)
    if area < config.SMALL_FACE_AREA_MM2:
        return False
    st = el.get("stype") or "other"
    ax = setup_axis
    if st == "plane":
        n = el.get("normal")
        if not n:
            return True
        return abs(_dot3(n, ax)) >= 0.55
    if st == "cone":
        return True
    if st == "cylinder":
        ca = el.get("axis")
        kind = el.get("cyl_kind") or ""
        d = float(el.get("d") or 0)
        body_d = float(el.get("body_d") or 0)
        hole_max = float(el.get("hole_max_d") or 0)
        if kind == "bore" or (hole_max > 0 and d < hole_max):
            return True
        if not ca:
            return kind != "outer"
        if mode == "turning" and _angle_between_dirs(ca, ax) < 12.0:
            if kind == "outer" and body_d > 0 and d >= body_d * 0.45:
                return False
            return False
        if mode == "milling":
            if _angle_between_dirs(ca, ax) > 70.0:
                return True
            return kind != "outer"
        return kind != "outer"
    if st in ("other", "torus"):
        return area >= config.SMALL_FACE_AREA_MM2 * 3.0
    if st == "sphere":
        return area >= config.SMALL_FACE_AREA_MM2 * 2.0
    return False


def _dot3(a: Tuple[float, float, float], b: Tuple[float, float, float]) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _opposite_plane_sides_active(
    setup_axis: Tuple[float, float, float],
    center: np.ndarray,
    elements: List[Dict[str, Any]],
    mode: str,
) -> Tuple[bool, bool]:
    """
    Две противоположные плоскости вдоль оси: если на стороне есть обрабатываемый элемент — +1 установ.
    """
    com = np.asarray(center, dtype=float).reshape(3)
    ax = np.asarray(setup_axis, dtype=float)
    n = float(np.linalg.norm(ax))
    if n < 1e-9 or not elements:
        return False, False
    ax = ax / n
    ts: List[float] = []
    for el in elements:
        c = el.get("cent")
        if not c:
            continue
        ts.append(float(np.dot(np.asarray(c, dtype=float) - com, ax)))
    if not ts:
        return False, False
    t_min, t_max = min(ts), max(ts)
    span = max(t_max - t_min, 1e-6)
    band = max(span * 0.12, 2.0, span * 0.05)
    pos_active = False
    neg_active = False
    for el in elements:
        c = el.get("cent")
        if not c or not _setup_element_machinable(el, tuple(ax), mode):
            continue
        t = float(np.dot(np.asarray(c, dtype=float) - com, ax))
        if t >= t_max - band:
            pos_active = True
        if t <= t_min + band:
            neg_active = True
    return pos_active, neg_active


def count_setups_from_shape(
    shape,
    center: np.ndarray,
    principal: Dict[str, Any],
    bbox: Dict[str, float],
    avg_dim: float,
    part_family: str,
    processes: List[str],
    rod_meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Установы по OCC: противоположные плоскости вдоль главной оси инерции (токарная)
    или толщины плиты (фрезерная). Каждая сторона с элементами — отдельный установ (+переворот).
    """
    processes = processes or []
    rod_meta = rod_meta or {}
    ops_low = [str(p).lower() for p in processes]
    has_turn = any("токар" in o for o in ops_low)
    has_mill = any("фрез" in o for o in ops_low)
    pf = (part_family or "").lower()
    elements = _collect_setup_face_elements(shape, bbox, avg_dim)
    com = np.asarray(center, dtype=float).reshape(3)

    turning_sides = 0
    milling_sides = 0
    detail: Dict[str, Any] = {"criterion": "opposite_planes_occ"}

    if has_turn:
        ax_t = _setup_axis_from_inertia(principal, bbox, pf, for_milling=False)
        if rod_meta.get("main_axis"):
            ax_t = np.asarray(rod_meta["main_axis"], dtype=float)
            nrm = float(np.linalg.norm(ax_t))
            if nrm > 1e-9:
                ax_t = ax_t / nrm
        if ax_t is not None:
            pos, neg = _opposite_plane_sides_active(
                tuple(ax_t), com, elements, "turning"
            )
            turning_sides = int(pos) + int(neg)
            detail["turning"] = {
                "axis": [float(x) for x in ax_t],
                "positive_side": pos,
                "negative_side": neg,
                "sides_with_features": turning_sides,
            }

    if has_mill:
        ax_m = _setup_axis_from_inertia(principal, bbox, pf, for_milling=True)
        if ax_m is None:
            ax_m = np.asarray(_plate_thickness_direction(bbox), dtype=float)
        else:
            ax_m = _align_axis_to_thickness(ax_m, bbox)
        pos, neg = _opposite_plane_sides_active(
            tuple(ax_m), com, elements, "milling"
        )
        milling_sides = int(pos) + int(neg)
        detail["milling"] = {
            "axis": [float(x) for x in ax_m],
            "positive_side": pos,
            "negative_side": neg,
            "sides_with_features": milling_sides,
        }
        if pos and neg:
            detail["milling"]["flip_required"] = True

    if has_turn and (rod_meta.get("hybrid_turn_mill") or pf in ("hybrid_shaft", "oversize")):
        axis_prof = _bbox_axis_profile(bbox)
        if axis_prof["elongation"] >= 2.0 and not axis_prof["cross_round"]:
            turning_sides = max(turning_sides, 2)
            detail["hybrid_end_turning"] = True
    if rod_meta.get("hex_head_stud"):
        if has_turn:
            turning_sides = 1
            detail["hex_head_stud_turning"] = True
        if has_mill:
            milling_sides = 1
            detail["hex_head_stud_milling"] = True
    turning_count = max(turning_sides, 1) if has_turn else 0
    milling_count = max(milling_sides, 1) if has_mill else 0
    drill_extra = 0
    if any("сверл" in o for o in ops_low) and not has_mill:
        drill_extra = 1
    grind_extra = 1 if any("шлиф" in o for o in ops_low) else 0
    total = turning_count + milling_count + drill_extra + grind_extra
    if total < 1:
        total = 1

    detail["setup_count_turning"] = turning_count
    detail["setup_count_milling"] = milling_count
    detail["setup_count_total"] = total
    return {
        "setup_count_turning": turning_count,
        "setup_count_milling": milling_count,
        "setup_count_total": total,
        "setup_planes": detail,
    }


def _dist_parallel_axes(
    loc1: Tuple[float, float, float],
    dir1: Tuple[float, float, float],
    loc2: Tuple[float, float, float],
    dir2: Tuple[float, float, float],
) -> float:
    """Расстояние между параллельными осями (мм)."""
    d = (loc2[0] - loc1[0], loc2[1] - loc1[1], loc2[2] - loc1[2])
    u = _normalize_vec(dir1)
    along = (d[0] * u[0] + d[1] * u[1] + d[2] * u[2])
    px = d[0] - along * u[0]
    py = d[1] - along * u[1]
    pz = d[2] - along * u[2]
    return math.sqrt(px * px + py * py + pz * pz)


def _holes_from_bore_clustering(shape, bbox: Dict[str, float]) -> List[Dict[str, Any]]:
    """
    Отверстия: внутренние (bore) цилиндры, без коротких дуг скруглений рёбер;
    кластеризация по Ø и положению оси.
    """
    cyls = _collect_cylindrical_face_records(shape, bbox)
    thickness_dir = _plate_thickness_direction(bbox)
    flat_plate = _is_flat_plate_bbox(bbox)
    candidates: List[Dict[str, Any]] = []
    for c in cyls:
        if c["kind"] != "bore":
            continue
        if c["d"] < config.MIN_HOLE_DIAMETER_MM:
            continue
        # U-параметр цилиндра — угол обхвата; короткая дуга = скругление ребра, не отверстие
        if c.get("u_span", 0) < config.MIN_HOLE_CIRC_SPAN_RAD:
            continue
        if flat_plate and _angle_between_dirs(c["axis"], thickness_dir) > 15.0:
            continue
        candidates.append(c)

    clusters: List[Dict[str, Any]] = []
    for c in candidates:
        d = round(c["d"], 1)
        matched = False
        for cl in clusters:
            if abs(cl["d"] - d) > 0.6:
                continue
            if _angle_between_dirs(c["axis"], cl["axis"]) > 8.0:
                continue
            if _dist_parallel_axes(c["loc"], c["axis"], cl["loc"], cl["axis"]) < config.HOLE_AXIS_CLUSTER_MM:
                matched = True
                break
        if not matched:
            clusters.append({"d": d, "loc": c["loc"], "axis": c["axis"]})

    holes: List[Dict[str, Any]] = []
    for cl in sorted(clusters, key=lambda x: (x["d"], x["loc"][0])):
        d = cl["d"]
        holes.append(
            {
                "diameter": d,
                "radius": round(d / 2, 1),
                "feature": "bore",
            }
        )
    return holes[:15]


def _collect_cone_face_records(shape) -> List[Dict[str, Any]]:
    from OCC.Core.TopExp import TopExp_Explorer
    from OCC.Core.TopAbs import TopAbs_FACE
    from OCC.Core.BRepAdaptor import BRepAdaptor_Surface
    from OCC.Core.BRepGProp import brepgprop
    from OCC.Core.GProp import GProp_GProps
    from OCC.Core.GeomAbs import GeomAbs_Cone
    from OCC.Core.gp import gp_Pnt

    records: List[Dict[str, Any]] = []
    exp = TopExp_Explorer(shape, TopAbs_FACE)
    idx = 0
    while exp.More():
        face = exp.Current()
        surf = BRepAdaptor_Surface(face)
        if surf.GetType() != GeomAbs_Cone:
            idx += 1
            exp.Next()
            continue
        cone = surf.Cone()
        u1, u2 = surf.FirstUParameter(), surf.LastUParameter()
        v1, v2 = surf.FirstVParameter(), surf.LastVParameter()
        p = gp_Pnt()
        surf.D0((u1 + u2) / 2, (v1 + v2) / 2, p)
        ax = cone.Axis()
        fp = GProp_GProps()
        try:
            brepgprop.SurfaceProperties(face, fp)
        except AttributeError:
            from OCC.Core.BRepGProp import brepgprop_SurfaceProperties
            brepgprop_SurfaceProperties(face, fp)
        records.append({
            "idx": idx,
            "semi_deg": math.degrees(float(cone.SemiAngle())),
            "ref_r": float(cone.RefRadius()),
            "area": float(fp.Mass()),
            "kind": _cylindrical_shell_kind(shape, surf),
            "axis": _normalize_vec(_vec3_gp(ax.Direction())),
            "cent": _vec3_gp(p),
            "loc": _vec3_gp(ax.Location()),
        })
        idx += 1
        exp.Next()
    return records


def _project_scalar(p: Tuple[float, float, float], axis_pt: Tuple[float, float, float], axis_dir: Tuple[float, float, float]) -> float:
    return (
        (p[0] - axis_pt[0]) * axis_dir[0]
        + (p[1] - axis_pt[1]) * axis_dir[1]
        + (p[2] - axis_pt[2]) * axis_dir[2]
    )


def _m6_on_end_detected(
    shape,
    main_axis: Tuple[float, float, float],
    axis_pt: Tuple[float, float, float],
    cones: List[Dict],
    *,
    body_d: float = 0.0,
) -> bool:
    """М6: фаска 1×45 (bore CONE) у торца на оси прутка."""
    max_axis_dist = max(4.5, body_d * 0.085) if body_d > 0 else 4.5
    for c in cones:
        if c["kind"] != "bore":
            continue
        if abs(c["semi_deg"] - 45.0) > 2.0:
            continue
        if _angle_between_dirs(c["axis"], main_axis) > 8.0:
            continue
        if _dist_point_to_axis(c["cent"], axis_pt, main_axis) > max_axis_dist:
            continue
        if c["area"] < 5.0:
            continue
        return True
    return False


def _analyze_rod_family(shape, bbox: Dict[str, float]) -> Dict[str, Any]:
    """
    Разбор прутка: P±εn, кластеры отверстий, паз, М6, глухое Ø15.
    Возвращает списки shafts/holes для API и счётчики по технологическим признакам.
    """
    cyls = _collect_cylindrical_face_records(shape, bbox)
    cones = _collect_cone_face_records(shape)
    main_axis, axis_pt = _infer_main_axis_from_cylinders(cyls)

    min_outer_area = config.SMALL_FACE_AREA_MM2

    axis_prof = _bbox_axis_profile(bbox)
    body_d_guess = float(axis_prof.get("diameter") or 0)

    outer_steps: Dict[float, float] = {}
    for c in cyls:
        if c["kind"] not in ("outer", "ambiguous") or c["area"] < min_outer_area:
            continue
        if c["kind"] == "ambiguous" and body_d_guess > 0 and c["d"] < body_d_guess * 0.55:
            continue
        dk = round(c["d"], 1)
        outer_steps[dk] = outer_steps.get(dk, 0.0) + c["area"]

    shafts = [
        {"diameter": d, "radius": round(d / 2, 1), "feature": "body"}
        for d in sorted(outer_steps.keys(), reverse=True)
    ]
    if not shafts and body_d_guess > 0:
        shafts = [
            {
                "diameter": round(body_d_guess, 1),
                "radius": round(body_d_guess / 2, 1),
                "feature": "body",
            }
        ]

    body_d = max((float(s["diameter"]) for s in shafts), default=body_d_guess)
    bore_holes: List[Dict[str, Any]] = []
    for c in cyls:
        if c["kind"] not in ("bore", "ambiguous"):
            continue
        if body_d > 0 and c["d"] >= body_d * 0.92:
            continue
        if c["area"] < 8.0 and c["d"] < 4.5:
            continue
        bore_holes.append(
            {
                "diameter": round(c["d"], 1),
                "radius": round(c["d"] / 2, 1),
                "feature": "bore",
            }
        )

    keyway_perp = [
        c for c in cyls
        if c["kind"] == "bore"
        and 4.5 <= c["d"] <= 5.5
        and c["area"] < 80.0
        and _angle_between_dirs(c["axis"], main_axis) > 75.0
    ]
    keyway_wall = [
        c for c in cyls
        if c["kind"] == "bore"
        and 4.5 <= c["d"] <= 5.5
        and c["area"] >= 50.0
        and _angle_between_dirs(c["axis"], main_axis) < 10.0
        and _dist_point_to_axis(c["cent"], axis_pt, main_axis) < 5.0
    ]
    has_keyway = len(keyway_perp) >= 2 or (len(keyway_perp) >= 1 and len(keyway_wall) >= 1)

    bolt_clusters: Dict[Tuple[float, float, float], int] = {}
    for c in cyls:
        if c["kind"] != "bore":
            continue
        if not (5.5 <= c["d"] <= 6.5):
            continue
        if _angle_between_dirs(c["axis"], main_axis) > 15.0:
            continue
        key = (
            round(c["cent"][0], 0),
            round(c["cent"][1], 0),
            round(c["cent"][2], 0),
        )
        bolt_clusters[key] = bolt_clusters.get(key, 0) + 1
    bolt_count = len(bolt_clusters)

    blind_15 = any(
        c["kind"] == "bore" and 28.0 <= c["semi_deg"] <= 32.0
        and _angle_between_dirs(c["axis"], main_axis) < 15.0
        and c["area"] > 80.0
        for c in cones
    )

    has_m6 = _m6_on_end_detected(shape, main_axis, axis_pt, cones, body_d=body_d)

    holes: List[Dict[str, Any]] = list(bore_holes)
    features: List[Dict[str, Any]] = []

    if bolt_count > 0:
        holes.extend({"diameter": 6.0, "radius": 3.0, "feature": "bolt_hole"} for _ in range(bolt_count))
        features.append({"type": "bolt_holes", "count": bolt_count, "diameter_mm": 6.0})
    if blind_15:
        holes.append({"diameter": 15.0, "radius": 7.5, "feature": "blind_hole"})
        features.append({"type": "blind_hole", "count": 1, "diameter_mm": 15.0})
    if has_m6:
        holes.append({"diameter": 6.0, "radius": 3.0, "feature": "thread_m6"})
        features.append({"type": "thread_m6", "count": 1, "diameter_mm": 6.0})
    if has_keyway:
        features.append({"type": "keyway", "count": 1, "width_mm": 5.0})

    holes_feature_count = bolt_count + (1 if blind_15 else 0) + (1 if has_m6 else 0)

    return {
        "holes": holes[:15],
        "shafts": shafts[:15],
        "holes_feature_count": holes_feature_count,
        "shafts_feature_count": len(shafts),
        "features": features,
        "has_keyway": has_keyway,
        "has_m6": has_m6,
        "has_blind_15": blind_15,
        "bolt_hole_count": bolt_count,
        "main_axis": main_axis,
    }


def _face_details(
    shape,
    avg_dim: float = 100.0,
    bbox: Optional[Dict[str, float]] = None,
    *,
    fast: bool = False,
) -> Tuple[List[Dict[str, Any]], Dict[str, int], List[Dict], List[Dict]]:
    """Список граней, счётчики типов, отверстия и валы (по цилиндрическим граням)."""
    from OCC.Core.TopExp import TopExp_Explorer
    from OCC.Core.TopAbs import TopAbs_FACE
    from OCC.Core.BRepAdaptor import BRepAdaptor_Surface
    from OCC.Core.BRepGProp import brepgprop
    from OCC.Core.GProp import GProp_GProps
    from OCC.Core.GeomAbs import (
        GeomAbs_Cylinder, GeomAbs_Plane, GeomAbs_Cone,
        GeomAbs_Sphere, GeomAbs_Torus,
    )

    faces: List[Dict[str, Any]] = []
    holes: List[Dict[str, Any]] = []
    shafts: List[Dict[str, Any]] = []
    cyl, plane, cone, sphere, torus, other = 0, 0, 0, 0, 0, 0
    small_faces = 0
    idx = 0
    exp = TopExp_Explorer(shape, TopAbs_FACE)
    while exp.More():
        face = exp.Current()
        surf = BRepAdaptor_Surface(face)
        st = surf.GetType()
        st_name = "other"
        if st == GeomAbs_Plane:
            plane += 1
            st_name = "plane"
        elif st == GeomAbs_Cylinder:
            cyl += 1
            st_name = "cylinder"
            try:
                c_geom = surf.Cylinder()
                if c_geom:
                    r = round(float(c_geom.Radius()), 1)
                    d = round(r * 2, 1)
                    hole_max_d = (
                        _cyl_hole_max_diameter(bbox, avg_dim)
                        if bbox
                        else avg_dim * 0.75
                    )
                    if d < hole_max_d:
                        holes.append({"diameter": d, "radius": r})
                    else:
                        shafts.append({"diameter": d, "radius": r})
            except Exception:
                pass
        elif st == GeomAbs_Cone:
            cone += 1
            st_name = "cone"
        elif st == GeomAbs_Sphere:
            sphere += 1
            st_name = "sphere"
        elif st == GeomAbs_Torus:
            torus += 1
            st_name = "torus"
        else:
            other += 1

        f_area = 0.0
        if not fast or st == GeomAbs_Cylinder:
            fp = GProp_GProps()
            try:
                brepgprop.SurfaceProperties(face, fp)
            except AttributeError:
                from OCC.Core.BRepGProp import brepgprop_SurfaceProperties
                brepgprop_SurfaceProperties(face, fp)
            f_area = float(fp.Mass())
            if f_area < config.SMALL_FACE_AREA_MM2:
                small_faces += 1

        if not fast or idx < 80:
            faces.append({
                "face_index": idx,
                "area_mm2": round(f_area, 4),
                "surface_type": st_name,
            })
        idx += 1
        exp.Next()

    counts = {
        "cyl_face_count": cyl,
        "plane_face_count": plane,
        "cone_face_count": cone,
        "sphere_face_count": sphere,
        "torus_face_count": torus,
        "other_face_count": other,
        "small_face_count": small_faces,
        "holes_count": len(holes),
        "shafts_count": len(shafts),
    }
    return faces, counts, holes[:15], shafts[:15]


def _edge_details(shape) -> Tuple[List[Dict[str, Any]], int]:
    """Длины рёбер и число «острых» (малый радиус скругления / линейные)."""
    from OCC.Core.TopExp import TopExp_Explorer
    from OCC.Core.TopAbs import TopAbs_EDGE
    from OCC.Core.BRepAdaptor import BRepAdaptor_Curve
    from OCC.Core.GProp import GProp_GProps
    from OCC.Core.BRepGProp import brepgprop_LinearProperties

    edges: List[Dict[str, Any]] = []
    sharp = 0
    idx = 0
    exp = TopExp_Explorer(shape, TopAbs_EDGE)
    while exp.More():
        edge = exp.Current()
        lp = GProp_GProps()
        try:
            brepgprop_LinearProperties(edge, lp)
            length = float(lp.Mass())
        except Exception:
            length = 0.0

        is_sharp = 0
        try:
            curve = BRepAdaptor_Curve(edge)
            if curve.GetType() == 0:  # GeomAbs_Line — грань без скругления
                is_sharp = 1
                sharp += 1
        except Exception:
            pass

        edges.append({
            "edge_index": idx,
            "length_mm": round(length, 4),
            "is_sharp": is_sharp,
        })
        idx += 1
        exp.Next()
    return edges, sharp


def _bbox_diagonal(bbox: Dict[str, float]) -> float:
    x, y, z = bbox.get("x", 0), bbox.get("y", 0), bbox.get("z", 0)
    return math.sqrt(x * x + y * y + z * z)


def _sigmoid(x: float) -> float:
    if x >= 20.0:
        return 1.0
    if x <= -20.0:
        return 0.0
    return 1.0 / (1.0 + math.exp(-x))


def _wall_thickness_run_probability(
    *,
    surface_to_volume_ratio: float,
    detail_index: float,
    part_family: str,
    base_family: str,
    bbox: Dict[str, float],
    face_counts: Dict[str, int],
    topo: Dict[str, int],
    rot_profile: Optional[Dict[str, Any]] = None,
    hybrid_turn_mill: bool = False,
    volume_mm3: float = 0.0,
) -> float:
    """
    Вероятность [0, 1], что в fast-режиме стоит запускать OCC ray-casting стенок.
    Сглаженная оценка по метрикам, уже доступным до тяжёлого шага.
    """
    if is_oversize_part(bbox, volume_mm3):
        return 0.0

    sa_v = float(surface_to_volume_ratio or 0.0)
    di = float(detail_index or 0.0)
    axis = _bbox_axis_profile(bbox)
    rot = rot_profile or {}

    p_surface = _sigmoid((sa_v - config.WALL_THICKNESS_SA_V_MID) * config.WALL_THICKNESS_SA_V_SLOPE)
    p_detail = _sigmoid(
        (di - config.WALL_THICKNESS_DETAIL_MID) * config.WALL_THICKNESS_DETAIL_SLOPE
    )
    n = max(_face_count_total(face_counts, topo), 1)
    freeform = (
        face_counts.get("torus_face_count", 0) + face_counts.get("other_face_count", 0)
    ) / n
    p_freeform = _sigmoid((freeform - 0.35) * 6.0)

    family_prior = {
        "impeller": 0.95,
        "plate": 0.82,
        "hybrid_shaft": 0.35,
        "rod": 0.55,
        "oversize": 0.0,
    }.get(part_family, 0.6)
    base_prior = {
        "impeller": 0.95,
        "plate": 0.80,
        "rod": 0.50,
    }.get(base_family, 0.55)
    p_family = max(family_prior, base_prior)

    blend = 0.42 * p_surface + 0.22 * p_detail + 0.16 * p_freeform + 0.20 * p_family

    if axis.get("is_disc") and sa_v >= 0.45:
        blend = max(blend, 0.72)

    shaft_penalty = 1.0
    if axis.get("is_elongated_rod") and sa_v < config.WALL_THICKNESS_SHAFT_SA_V_MAX:
        shaft_penalty = 0.08
    elif (
        part_family == "rod"
        and base_family == "rod"
        and axis.get("cross_round")
        and not axis.get("is_disc")
        and sa_v < 0.28
        and float(rot.get("rotation_confidence") or 0.0) >= config.ROT_CONF_MIN_TURN
        and float(axis.get("elongation") or 0.0) >= config.ROD_MIN_LD_RATIO
    ):
        shaft_penalty = 0.12

    if hybrid_turn_mill and sa_v < 0.20:
        shaft_penalty = min(shaft_penalty, 0.15)

    score = blend * shaft_penalty
    return max(0.0, min(1.0, score))


def _resolve_wall_thickness_info(
    shape,
    bbox: Dict[str, float],
    face_count: int,
    *,
    fast: bool,
    force_wall_thickness: bool,
    run_probability: float,
) -> Dict[str, Any]:
    """Решение о ray-casting стенок: полный / литьё / fast+гейт / пропуск."""
    if not fast:
        return _analyze_wall_thickness(shape, bbox, face_count)
    if force_wall_thickness:
        return _analyze_wall_thickness(
            shape,
            bbox,
            face_count,
            max_faces_cap=config.CASTING_WALL_MAX_FACES,
            samples_per_face=config.CASTING_WALL_SAMPLES_PER_FACE,
            time_budget_sec=config.CASTING_WALL_TIME_BUDGET_SEC,
        )
    if run_probability >= config.WALL_THICKNESS_RUN_THRESHOLD:
        info = _analyze_wall_thickness(shape, bbox, face_count)
        note = (info.get("note") or WALL_THICKNESS_NOTE).strip()
        info["note"] = f"{note} (fast p={run_probability:.2f})"
        return info
    return {
        "min_wall_thickness_mm": None,
        "thin_walls": False,
        "thin_wall_ratio": 0.0,
        "note": f"fast_skip (p={run_probability:.2f})",
    }


def _analyze_wall_thickness(
    shape,
    bbox: Dict[str, float],
    face_count: int,
    *,
    max_faces_cap: int | None = None,
    samples_per_face: int | None = None,
    time_budget_sec: float | None = None,
) -> Dict[str, Any]:
    """
    Минимальная толщина стенки и признак тонкостенности (OCC ray-casting).
    Луч вдоль внутренней нормали грани; толщина — сегмент луча внутри тела (BRepClass3d).
    """
    if not config.ENABLE_WALL_THICKNESS_OCC:
        return {
            "min_wall_thickness_mm": None,
            "thin_walls": False,
            "thin_wall_ratio": 0.0,
            "note": "disabled",
        }
    try:
        from OCC.Core.BRepAdaptor import BRepAdaptor_Surface
        from OCC.Core.BRepClass3d import BRepClass3d_SolidClassifier
        from OCC.Core.IntCurvesFace import IntCurvesFace_ShapeIntersector
        from OCC.Core.TopAbs import TopAbs_FACE, TopAbs_IN, TopAbs_REVERSED
        from OCC.Core.TopExp import TopExp_Explorer
        from OCC.Core.TopoDS import topods
        from OCC.Core.gp import gp_Dir, gp_Lin, gp_Pnt, gp_Vec

        diag = _bbox_diagonal(bbox)
        if diag < 1e-6:
            return {"min_wall_thickness_mm": None, "thin_walls": False, "thin_wall_ratio": 0.0, "note": "empty"}

        tol = max(diag * 1e-6, 1e-3)
        thresh = max(config.THIN_WALL_MIN_MM, diag * config.THIN_WALL_REL)
        fc = int(face_count or 0)
        if max_faces_cap is not None:
            max_faces = int(max_faces_cap)
        else:
            max_faces = min(
                config.WALL_THICKNESS_MAX_FACES,
                max(25, fc // 12),
            )
        if fc > 3000:
            max_faces = min(max_faces, 12)
        elif fc > 1000:
            max_faces = min(max_faces, 18)
        n_per = int(samples_per_face or config.WALL_THICKNESS_SAMPLES_PER_FACE)
        n_per = max(1, min(n_per, 3))
        t0 = time.monotonic()

        inter = IntCurvesFace_ShapeIntersector()
        inter.Load(shape, tol)
        clf = BRepClass3d_SolidClassifier(shape)

        thicknesses: List[float] = []
        exp = TopExp_Explorer(shape, TopAbs_FACE)
        face_index = 0
        sampled_faces = 0
        stride = max(1, fc // max(1, max_faces)) if fc > 0 else 1
        timed_out = False
        while exp.More() and sampled_faces < max_faces:
            if time_budget_sec and (time.monotonic() - t0) > time_budget_sec:
                timed_out = True
                break
            if face_index % stride != 0:
                face_index += 1
                exp.Next()
                continue
            face = topods.Face(exp.Current())
            surf = BRepAdaptor_Surface(face)
            u1, u2 = surf.FirstUParameter(), surf.LastUParameter()
            v1, v2 = surf.FirstVParameter(), surf.LastVParameter()
            if abs(u2 - u1) < 1e-9 or abs(v2 - v1) < 1e-9:
                face_index += 1
                exp.Next()
                continue
            for i in range(n_per):
                for j in range(n_per):
                    u = u1 + (u2 - u1) * (i + 0.5) / n_per
                    v = v1 + (v2 - v1) * (j + 0.5) / n_per
                    pt = gp_Pnt()
                    du = gp_Vec()
                    dv = gp_Vec()
                    surf.D1(u, v, pt, du, dv)
                    nv = du.Crossed(dv)
                    if nv.Magnitude() < 1e-12:
                        continue
                    nv.Normalize()
                    if face.Orientation() == TopAbs_REVERSED:
                        nv.Reverse()
                    d_in = gp_Dir(nv.X(), nv.Y(), nv.Z())
                    d_in.Reverse()
                    lin = gp_Lin(pt, d_in)
                    inter.Perform(lin, -diag, diag)
                    nb = inter.NbPnt()
                    if nb < 2:
                        continue
                    ws = sorted(inter.WParameter(k + 1) for k in range(nb))
                    for a, b in zip(ws, ws[1:]):
                        mid = 0.5 * (a + b)
                        pm = gp_Pnt(
                            pt.X() + d_in.X() * mid,
                            pt.Y() + d_in.Y() * mid,
                            pt.Z() + d_in.Z() * mid,
                        )
                        clf.Perform(pm, tol)
                        if clf.State() == TopAbs_IN:
                            t = abs(b - a)
                            if t > 0.05:
                                thicknesses.append(t)
            sampled_faces += 1
            face_index += 1
            exp.Next()

        if not thicknesses:
            note = "no samples"
            if timed_out:
                note = f"timeout ({time_budget_sec:.0f}s)"
            return {
                "min_wall_thickness_mm": None,
                "thin_walls": False,
                "thin_wall_ratio": 0.0,
                "note": note,
            }

        arr = np.asarray(thicknesses, dtype=float)
        pct = int(getattr(config, "WALL_THICKNESS_REPORT_PERCENTILE", 10))
        pct = max(5, min(pct, 25))
        min_wall = float(np.percentile(arr, pct))
        median_wall = float(np.median(arr))
        if median_wall >= thresh * 0.45 and min_wall < median_wall * 0.45:
            min_wall = float(np.percentile(arr, 25))
        thin_ratio = float(np.mean(arr < thresh))
        median_factor = float(getattr(config, "WALL_THICKNESS_THIN_MEDIAN_FACTOR", 0.85))
        thin_walls = (
            thin_ratio >= config.THIN_WALL_SAMPLE_RATIO
            and median_wall < thresh * median_factor
        )
        note = WALL_THICKNESS_NOTE
        if timed_out:
            note = f"{WALL_THICKNESS_NOTE} (частичная выборка, лимит {time_budget_sec:.0f} с)"
        return {
            "min_wall_thickness_mm": round(min_wall, 3),
            "wall_thickness_median_mm": round(median_wall, 3),
            "thin_walls": thin_walls,
            "thin_wall_ratio": round(thin_ratio, 4),
            "thin_wall_threshold_mm": round(thresh, 2),
            "wall_samples": len(thicknesses),
            "note": note,
        }
    except Exception as e:
        return {
            "min_wall_thickness_mm": None,
            "thin_walls": False,
            "thin_wall_ratio": 0.0,
            "note": f"error: {e}",
        }


def _void_hint(step_path: str, volume: float) -> Dict[str, Any]:
    """Приближение полостей: объём выпуклой оболочки vs объём тела."""
    if not config.ENABLE_TRIMESH_VOID_HINT:
        return {"has_internal_void": None, "void_volume_mm3": None, "note": "disabled"}
    try:
        import scipy  # noqa: F401
        import trimesh
        mesh = trimesh.load(step_path, file_type="step")
        if isinstance(mesh, trimesh.Scene):
            combined = trimesh.Trimesh()
            for g in mesh.geometry.values():
                if isinstance(g, trimesh.Trimesh):
                    combined += g
            mesh = combined
        if not isinstance(mesh, trimesh.Trimesh) or mesh.volume <= 0:
            return {"has_internal_void": 0, "void_volume_mm3": 0.0}
        hull_vol = float(mesh.convex_hull.volume)
        void_v = max(0.0, hull_vol - volume)
        return {
            "has_internal_void": 1 if void_v > volume * 0.02 else 0,
            "void_volume_mm3": round(void_v, 2),
            "convex_hull_volume_mm3": round(hull_vol, 2),
        }
    except Exception as e:
        return {"has_internal_void": None, "void_volume_mm3": None, "note": str(e)}


def _caf_metadata(step_path: str) -> Dict[str, Optional[str]]:
    """Имя, цвет, материал из STEP (XCAF), если доступно."""
    if not config.ENABLE_CAF_METADATA:
        return {}
    out = {"part_name": None, "cad_color": None, "cad_layer": None, "cad_material": None}
    try:
        from OCC.Core.STEPCAFControl import STEPCAFControl_Reader
        from OCC.Core.TDocStd import TDocStd_Document
        from OCC.Core.XCAFDoc import XCAFDoc_DocumentTool
        from OCC.Core.TCollection import TCollection_ExtendedString
        from OCC.Core.TDF import TDF_LabelSequence
        from OCC.Core.Quantity import Quantity_Color

        doc = TDocStd_Document(TCollection_ExtendedString("MDTV-XCAF"))
        reader = STEPCAFControl_Reader()
        reader.SetColorMode(True)
        reader.SetNameMode(True)
        reader.SetLayerMode(True)
        reader.SetMaterialMode(True)
        if reader.ReadFile(step_path) != 1:
            return out
        reader.Transfer(doc)
        shape_tool = XCAFDoc_DocumentTool.ShapeTool(doc.Main())
        color_tool = XCAFDoc_DocumentTool.ColorTool(doc.Main())
        material_tool = XCAFDoc_DocumentTool.MaterialTool(doc.Main())
        labels = TDF_LabelSequence()
        shape_tool.GetFreeShapes(labels)
        if labels.Length() >= 1:
            label = labels.Value(1)
            out["part_name"] = shape_tool.GetShapeName(label) or None
            c = Quantity_Color()
            if color_tool.GetColor(label, c):
                out["cad_color"] = f"#{int(c.Red()*255):02x}{int(c.Green()*255):02x}{int(c.Blue()*255):02x}"
            mat = material_tool.GetMaterial(label)
            if mat:
                out["cad_material"] = str(mat.GetMaterialName()) if hasattr(mat, "GetMaterialName") else str(mat)
    except Exception:
        pass
    return out



def _effective_cyl_kind(
    rec: Dict[str, Any],
    body_d: float,
    main_axis: Tuple[float, float, float],
    axis_pt: Tuple[float, float, float],
) -> str:
    """Разрешить ambiguous по Ø тела и коаксиальности."""
    kind = rec.get("kind") or "ambiguous"
    d = float(rec.get("d") or 0)
    if kind != "ambiguous":
        return kind
    if body_d <= 0:
        return "ambiguous"
    coax = _angle_between_dirs(rec.get("axis") or main_axis, main_axis) <= config.COAXIAL_ANGLE_DEG
    if d >= body_d * config.AMBIGUOUS_OUTER_D_RATIO and coax:
        return "outer"
    if d <= body_d * config.AMBIGUOUS_BORE_D_RATIO:
        return "bore"
    return "ambiguous"


def _legacy_revolution_hint(
    face_counts: Dict[str, int],
    bbox: Dict[str, float],
    shafts: Optional[List[Dict]] = None,
) -> float:
    """Слабая подсказка 0…1 из старых эвристик (не напрямую rotational)."""
    shafts = shafts or []
    cyl = face_counts.get("cyl_face_count", 0)
    plane = face_counts.get("plane_face_count", 0)
    cone = face_counts.get("cone_face_count", 0)
    other = face_counts.get("other_face_count", 0)
    n_faces = cyl + plane + cone + other + face_counts.get("sphere_face_count", 0) + face_counts.get("torus_face_count", 0)
    rev_shell = cyl + cone
    axis = _bbox_axis_profile(bbox)
    elongation = axis["elongation"]
    cross_round = axis["cross_round"]
    max_shaft = max((float(s.get("diameter", 0)) for s in shafts), default=0.0)
    min_bbox = axis["min_cross"]
    max_bbox = max(bbox["x"], bbox["y"], bbox["z"])
    large_cyl = max_shaft >= min_bbox * 0.68 or max_shaft >= max_bbox * 0.5
    hints: List[float] = []
    if (
        n_faces <= 10
        and cross_round
        and large_cyl
        and elongation >= 1.1
        and cyl >= 1
        and plane <= 4
        and (rev_shell >= 1 or (cyl >= 1 and other >= 1))
    ):
        hints.append(0.85)
    if cyl >= 3 and elongation >= 1.4 and plane < cyl * 2.5 and cross_round:
        hints.append(0.75)
    if cross_round and large_cyl and elongation >= 1.15 and cyl >= 2 and plane <= cyl + cone + 2:
        hints.append(0.7)
    if axis["is_elongated_rod"] and cyl >= 2:
        hints.append(0.65)
    return max(hints) if hints else 0.0


def _rotation_shell_profile(
    shape,
    bbox: Dict[str, float],
    face_counts: Dict[str, int],
    *,
    shafts: Optional[List[Dict]] = None,
) -> Dict[str, Any]:
    """
    Профиль вращения по outer/bore цилиндрам (P±ε·n).
    Возвращает rotation_confidence и признаки для токарки.
    """
    shafts = shafts or []
    cyls = _collect_cylindrical_face_records(shape, bbox)
    axis_prof = _bbox_axis_profile(bbox)
    body_d = float(axis_prof.get("diameter") or 0)
    outer_ds: List[float] = []

    if cyls:
        main_axis, axis_pt = _infer_main_axis_from_cylinders(
            [c for c in cyls if c.get("kind") in ("outer", "ambiguous")]
        )
        if main_axis == (0.0, 0.0, 1.0) and axis_pt == (0.0, 0.0, 0.0):
            main_axis, axis_pt = _infer_main_axis_from_cylinders(cyls)
    else:
        main_axis, axis_pt = (0.0, 0.0, 1.0), (0.0, 0.0, 0.0)

    total_area = 0.0
    outer_area = 0.0
    bore_area = 0.0
    ambiguous_area = 0.0
    coax_area = 0.0

    for c in cyls:
        area = float(c.get("area") or 0)
        if area < config.SMALL_FACE_AREA_MM2:
            continue
        total_area += area
        ek = _effective_cyl_kind(c, body_d, main_axis, axis_pt)
        coaxial = _angle_between_dirs(c.get("axis") or main_axis, main_axis) <= config.COAXIAL_ANGLE_DEG
        if coaxial:
            coax_area += area
        if ek == "outer":
            outer_area += area
            outer_ds.append(float(c.get("d") or 0))
        elif ek == "bore":
            bore_area += area
        else:
            ambiguous_area += area
            outer_area += area * 0.35

    if total_area < 1e-6:
        total_area = 1.0
    outer_share = outer_area / total_area
    bore_share = bore_area / total_area
    coaxiality = coax_area / total_area

    if outer_ds:
        d_max, d_min = max(outer_ds), min(outer_ds)
        diameter_span = (d_max - d_min) / max(d_max, 1e-9)
    else:
        diameter_span = 1.0

    n_faces = max(_face_count_total(face_counts, {}), 1)
    plane_n = face_counts.get("plane_face_count", 0)
    plane_share = plane_n / n_faces
    if outer_share < 0.2 and bore_share > 0.35:
        plane_penalty = min(1.0, plane_share * 1.4 + bore_share * 0.45)
    else:
        plane_penalty = min(1.0, plane_share * max(0.0, 1.0 - coaxiality) * 0.7)

    base = outer_share * (0.45 + 0.55 * coaxiality)
    pen_bore = max(0.0, bore_share - outer_share) * 0.45 if outer_share < 0.25 else 0.0
    span_excess = max(0.0, diameter_span - config.OUTER_DIAMETER_SPAN_MAX)
    span_scale = 0.12 if outer_share >= 0.42 else 0.32
    pen_span = (span_excess / 0.65) * span_scale
    pen_plane = max(0.0, plane_penalty - config.PLANE_PENALTY_FORGING_MAX) * 0.45
    legacy = _legacy_revolution_hint(face_counts, bbox, shafts) * 0.28

    rot_conf = base - pen_bore - pen_span - pen_plane + legacy
    rot_conf = max(0.0, min(1.0, rot_conf))

    outer_d = max(outer_ds) if outer_ds else body_d
    if outer_d <= 0 and shafts:
        outer_d = max(float(s.get("diameter", 0)) for s in shafts)
    if (
        axis_prof.get("is_disc")
        and body_d > 0
        and outer_d < body_d * config.DISC_MIN_OUTER_CYL_TO_BBOX_RATIO
    ):
        outer_d = body_d
    if outer_d <= 0:
        outer_d = body_d
    length_d = float(axis_prof.get("length") or 0)
    ld_ratio = length_d / max(outer_d, 1e-9) if outer_d > 0 else 0.0

    return {
        "rotation_confidence": round(rot_conf, 4),
        "outer_cyl_area_share": round(outer_share, 4),
        "bore_cyl_area_share": round(bore_share, 4),
        "ambiguous_cyl_area_share": round(ambiguous_area / total_area, 4),
        "main_axis_coaxiality": round(coaxiality, 4),
        "outer_diameter_span": round(diameter_span, 4),
        "plane_penalty": round(plane_penalty, 4),
        "bbox_cross_round": bool(axis_prof.get("cross_round")),
        "outer_diameter_mm": round(outer_d, 2),
        "length_mm": round(length_d, 2),
        "ld_ratio": round(ld_ratio, 4),
        "main_axis": main_axis,
        "cyl_record_count": len(cyls),
    }


def _evaluate_turning_case(
    rot_profile: Dict[str, Any],
    bbox: Dict[str, float],
    *,
    part_family: str = "plate",
    hybrid_turn_mill: bool = False,
    part_name: str = "",
    face_counts: Optional[Dict[str, int]] = None,
    shafts: Optional[List[Dict]] = None,
    hex_head_stud: bool = False,
) -> Tuple[Optional[str], bool, Optional[str]]:
    """
    Case A bar | B forging | C disc | D hybrid | None.
    Возвращает (turning_case, rotational, skip_reason).
    """
    rot_conf = float(rot_profile.get("rotation_confidence") or 0)
    outer_d = float(rot_profile.get("outer_diameter_mm") or 0)
    ld = float(rot_profile.get("ld_ratio") or 0)
    outer_share = float(rot_profile.get("outer_cyl_area_share") or 0)
    plane_pen = float(rot_profile.get("plane_penalty") or 0)
    axis = _bbox_axis_profile(bbox)
    name_low = (part_name or "").lower()

    if hex_head_stud or _is_hex_head_stud(
        rot_profile,
        bbox,
        face_counts or {},
        shafts,
        part_family=part_family,
        part_name=part_name,
    ):
        return "bar", True, None

    if any(k in name_low for k in ("намотк", "намоточ", "winding")):
        return "hybrid", True, None

    if hybrid_turn_mill and rot_conf >= config.ROT_CONF_HYBRID:
        return "hybrid", True, None

    if (
        part_family == "rod"
        and axis.get("is_elongated_rod")
        and outer_d > 0
        and outer_d <= config.BAR_STOCK_MAX_D_MM
        and rot_conf >= config.ROT_CONF_HYBRID
        and outer_share >= 0.30
        and (ld >= config.ROD_MIN_LD_RATIO or axis.get("elongation", 0) >= config.ROD_MIN_LD_RATIO)
    ):
        return "bar", True, None

    if (
        part_family == "rod"
        and outer_d <= config.BAR_STOCK_MAX_D_MM
        and rot_conf >= 0.48
        and outer_share >= 0.38
        and (ld >= 1.45 or axis.get("is_elongated_rod") or axis.get("elongation", 0) >= 1.6)
    ):
        return "bar", True, None

    if rot_conf < config.ROT_CONF_MIN_TURN:
        return None, False, f"rotation_confidence {rot_conf:.2f} < {config.ROT_CONF_MIN_TURN}"

    if axis.get("is_disc") and rot_conf >= config.ROT_CONF_DISC:
        return "disc", True, None

    # Короткие круглые детали (ролики/диски) с высокой долей наружных цилиндров:
    # даже при L/D ~ 1.0 должны считаться вращательными заготовками с токаркой.
    if (
        not axis.get("is_disc")
        and outer_d > 0
        and outer_d <= config.BAR_STOCK_MAX_D_MM
        and 0.7 <= rot_conf < config.ROT_CONF_FORGING
        and outer_share >= 0.6
        and 0.7 <= ld <= 1.4
    ):
        return "disc", True, None

    if (
        outer_d > config.BAR_STOCK_MAX_D_MM
        and rot_conf >= config.ROT_CONF_FORGING
        and outer_share >= config.OUTER_AREA_SHARE_FORGING_MIN
        and plane_pen < config.PLANE_PENALTY_FORGING_MAX
    ):
        return "forging", True, None

    axis_ld = float(axis.get("elongation") or ld)
    if (
        outer_d > 0
        and outer_d <= config.BAR_STOCK_MAX_D_MM
        and (ld >= config.ROD_MIN_LD_RATIO or axis_ld >= config.ROD_MIN_LD_RATIO)
        and rot_conf >= config.ROT_CONF_BAR
    ):
        return "bar", True, None

    # Простые короткие заготовки: диск/маховик без L/D прутка
    if (
        rot_conf >= config.ROT_CONF_DISC
        and axis.get("cross_round")
        and outer_share >= 0.18
        and plane_pen < config.PLANE_PENALTY_FORGING_MAX
        and outer_d <= config.BAR_STOCK_MAX_D_MM
    ):
        return "disc", True, None

    if part_family == "rod" and rot_conf >= config.ROT_CONF_BAR:
        if outer_d <= config.BAR_STOCK_MAX_D_MM or rot_conf >= config.ROT_CONF_FORGING:
            return "bar" if outer_d <= config.BAR_STOCK_MAX_D_MM else "forging", True, None

    return None, False, f"no turning case (rot_conf={rot_conf:.2f}, Ø={outer_d:.0f}, L/D={ld:.2f})"


_HEX_STUD_NAME_KEYS = (
    "шестигр",
    "шестиг",
    "hex",
    "stud",
    "болт",
    "винт",
    "стойк",
    "шпильк",
)


def _is_hex_head_stud(
    rot_profile: Dict[str, Any],
    bbox: Dict[str, float],
    face_counts: Dict[str, int],
    shafts: Optional[List[Dict]] = None,
    *,
    part_family: str = "plate",
    part_name: str = "",
) -> bool:
    """
    Шпилька/стойка с шестигранной головкой: тело и резьба — токарка, фрезеровка только под ключ.
    Наружных цилиндров в STEP часто нет (шестигранник + резьба), rotation_confidence ≈ 0.
    """
    if part_family != "rod":
        return False

    name_low = (part_name or "").lower()
    name_hint = any(k in name_low for k in _HEX_STUD_NAME_KEYS)

    shafts = shafts or []
    body_ds = [
        float(s.get("diameter", 0))
        for s in shafts
        if s.get("feature") == "body" and float(s.get("diameter", 0)) > 0
    ]
    body_d = max(body_ds) if body_ds else float(rot_profile.get("outer_diameter_mm") or 0)
    if body_d <= 0 or body_d > config.BAR_STOCK_MAX_D_MM:
        return False

    axis = _bbox_axis_profile(bbox)
    ld = float(rot_profile.get("ld_ratio") or axis.get("elongation") or 0)
    if ld < 1.3 and float(axis.get("elongation") or 0) < 1.3:
        return False

    sm, mid, lg = sorted([bbox["x"], bbox["y"], bbox["z"]])
    cross_square = abs(sm - mid) / max(sm, mid, 1e-9) < 0.15
    outer_share = float(rot_profile.get("outer_cyl_area_share") or 0)
    plane = int(face_counts.get("plane_face_count") or 0)
    cyl = int(face_counts.get("cyl_face_count") or 0)

    geo_hex_stud = (
        cross_square
        and outer_share < 0.25
        and plane >= 4
        and lg <= 150.0
        and (cyl >= 2 or plane <= 16)
    )
    if geo_hex_stud:
        return True
    if name_hint and cross_square and body_d > 0 and ld >= 1.2:
        return True
    return False


def _rotation_profile_with_turning(
    shape,
    bbox: Dict[str, float],
    face_counts: Dict[str, int],
    *,
    shafts: Optional[List[Dict]] = None,
    part_family: str = "plate",
    hybrid_turn_mill: bool = False,
    part_name: str = "",
) -> Dict[str, Any]:
    """Полный профиль: метрики + turning_case + rotational."""
    prof = _rotation_shell_profile(shape, bbox, face_counts, shafts=shafts)
    case, rotational, skip = _evaluate_turning_case(
        prof,
        bbox,
        part_family=part_family,
        hybrid_turn_mill=hybrid_turn_mill,
        part_name=part_name,
    )
    prof["turning_case"] = case
    prof["rotational"] = rotational
    prof["turning_skip_reason"] = skip
    return prof


def _revolution_geometry_profile(
    face_counts: Dict[str, int],
    bbox: Dict[str, float],
    shafts: Optional[List[Dict]] = None,
    *,
    rot_profile: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Признаки тела вращения. rotational — из rot_profile (outer/bore), не только AABB.
    """
    shafts = shafts or []
    cyl = face_counts.get("cyl_face_count", 0)
    plane = face_counts.get("plane_face_count", 0)
    other = face_counts.get("other_face_count", 0)
    cone = face_counts.get("cone_face_count", 0)
    n_faces = (
        cyl + plane + cone + other
        + face_counts.get("sphere_face_count", 0)
        + face_counts.get("torus_face_count", 0)
    )
    axis = _bbox_axis_profile(bbox)
    elongation = axis["elongation"]
    cross_round = axis["cross_round"]
    legacy_hint = _legacy_revolution_hint(face_counts, bbox, shafts)
    simple_blank = legacy_hint >= 0.82 and n_faces <= 10

    if rot_profile is not None:
        if "rotational" in rot_profile:
            rotational = bool(rot_profile.get("rotational"))
        else:
            rc = float(rot_profile.get("rotation_confidence") or 0)
            outer_d = float(rot_profile.get("outer_diameter_mm") or axis.get("diameter") or 0)
            if outer_d > config.BAR_STOCK_MAX_D_MM:
                rotational = rc >= config.ROT_CONF_FORGING
            else:
                rotational = rc >= config.ROT_CONF_BAR
    else:
        rotational = legacy_hint >= 0.72

    return {
        "rotational": rotational,
        "simple_blank": simple_blank,
        "elongation": elongation,
        "cross_round": cross_round,
        "n_faces": n_faces,
        "legacy_hint": legacy_hint,
    }


def _needs_5axis_milling(
    face_count: int,
    detail_index: float,
    torus: int,
    other: int,
    *,
    part_family: str = "plate",
    bbox: Optional[Dict[str, float]] = None,
) -> bool:
    """5-ось: импеллер, лопатки, обтекаемые поверхности — не «много цилиндров» от отверстий."""
    if part_family == "plate" and bbox and _is_flat_plate_bbox(bbox):
        return False
    if part_family == "plate":
        return torus >= 25 and other >= 80 and detail_index >= 20.0
    return (
        face_count >= 120
        or torus >= 15
        or other >= 60
        or detail_index >= 17.0
        or (torus >= 5 and other >= 30)
    )


def _infer_processes(
    face_counts: Dict[str, int],
    bbox: Dict[str, float],
    holes: Optional[List[Dict]] = None,
    shafts: Optional[List[Dict]] = None,
    *,
    face_count: int = 0,
    detail_index: float = 0.0,
    part_family: str = "plate",
    rod_meta: Optional[Dict[str, Any]] = None,
    rot_profile: Optional[Dict[str, Any]] = None,
    part_name: str = "",
) -> List[str]:
    """Все технологические процессы по геометрии STEP (не один)."""
    holes = holes or []
    shafts = shafts or []
    rod_meta = rod_meta or {}
    cyl = face_counts.get("cyl_face_count", 0)
    plane = face_counts.get("plane_face_count", 0)
    other = face_counts.get("other_face_count", 0)
    cone = face_counts.get("cone_face_count", 0)
    torus = face_counts.get("torus_face_count", 0)
    holes_n = face_counts.get("holes_count", len(holes))
    if part_family == "rod" and rod_meta.get("holes_feature_count") is not None:
        holes_n = int(rod_meta["holes_feature_count"])
    if not face_count:
        face_count = (
            cyl + plane + cone + torus + other
            + face_counts.get("sphere_face_count", 0)
        )

    rev = _revolution_geometry_profile(
        face_counts, bbox, shafts, rot_profile=rot_profile
    )
    simple_blank = rev["simple_blank"]
    hybrid_turn_mill = bool(rod_meta.get("hybrid_turn_mill")) or _is_hybrid_turn_mill_body(
        face_counts, bbox, face_count=face_count, part_name=part_name
    )
    hex_head_stud = bool(rod_meta.get("hex_head_stud")) or _is_hex_head_stud(
        rot_profile or {},
        bbox,
        face_counts,
        shafts,
        part_family=part_family,
        part_name=part_name,
    )
    if rot_profile is not None:
        rotational = bool(rot_profile.get("rotational"))
        add_turning = rotational or hex_head_stud
    else:
        rotational = rev["rotational"]
        add_turning = rotational or hex_head_stud or (
            hybrid_turn_mill
            and float(rev.get("legacy_hint") or 0) >= config.ROT_CONF_HYBRID
        )
    needs_5axis = _needs_5axis_milling(
        face_count, detail_index, torus, other, part_family=part_family, bbox=bbox
    )
    if hybrid_turn_mill and part_family in ("plate", "oversize", "hybrid_shaft"):
        needs_5axis = needs_5axis or (torus >= 4 and other >= 15 and detail_index >= 14.0)
    processes: List[str] = []

    if add_turning:
        processes.append("Токарная")

    if needs_5axis:
        processes.append("Фрезерная (5-осевая)")
    elif hex_head_stud:
        processes.append("Фрезерная")
    elif not simple_blank:
        # Диск/маховик: 2 установки на 3-оси после токарки (отверстия, контур, фаски)
        rod_needs_milling = part_family == "rod" and (
            rod_meta.get("has_keyway")
            or rod_meta.get("has_m6")
            or rod_meta.get("has_blind_15")
        )
        # Чисто токарные валы/ролики: вращательное тело, без явных признаков фрезеровки.
        # Допускаются фаски/галтелки и осевые отверстия, но нет боковых плоскостей/карманов.
        pure_rod_turning_only = (
            part_family == "rod"
            and not hybrid_turn_mill
            and not rod_needs_milling
            and rotational
            and holes_n <= 1
            and plane <= 2
        )
        needs_3axis = (
            not pure_rod_turning_only
            and (
                hybrid_turn_mill
                or rod_needs_milling
                or plane >= 6
                or other >= 8
                or (rotational and face_count < 120 and (plane >= 2 or holes_n >= 3 or cone >= 2))
                or (rotational and (plane > 4 or other >= 4))
                or (not rotational and (plane >= 4 or cone >= 2))
            )
        )
        if needs_3axis:
            processes.append("Фрезерная")

    if hex_head_stud:
        pass
    elif holes_n >= 2:
        processes.append("Сверление")
    elif holes_n >= 1 and not rotational:
        processes.append("Сверление")
    elif holes_n >= 1 and rotational:
        max_hole = max((float(h.get("diameter", 0)) for h in holes), default=0.0)
        max_shaft = max((float(s.get("diameter", 0)) for s in shafts), default=0.0)
        if max_hole > 0 and (max_shaft <= 0 or max_hole < max_shaft * 0.95):
            processes.append("Сверление")

    if cone >= 2 and not rotational and "Фрезерная" not in processes and "Фрезерная (5-осевая)" not in processes:
        processes.append("Фрезерная")

    if not processes:
        processes.append("Фрезерная")
    seen = set()
    out: List[str] = []
    for p in processes:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def _vertex_points(shape) -> np.ndarray:
    """Все вершины тела — для чистовых габаритов по фактической геометрии."""
    from OCC.Core.TopExp import TopExp_Explorer
    from OCC.Core.TopAbs import TopAbs_VERTEX
    from OCC.Core.TopoDS import topods
    from OCC.Core.BRep import BRep_Tool

    pts: List[List[float]] = []
    exp = TopExp_Explorer(shape, TopAbs_VERTEX)
    while exp.More():
        v = topods.Vertex(exp.Current())
        p = BRep_Tool.Pnt(v)
        pts.append([p.X(), p.Y(), p.Z()])
        exp.Next()
    return np.array(pts, dtype=float) if pts else np.empty((0, 3))


def _principal_extents(shape, center, inertia) -> Tuple[List[float], bool]:
    """
    Габариты чистовой модели в главных осях инерции (не мировой AABB).
    Устраняет завышение при повороте детали в STEP.
    """
    pts = _vertex_points(shape)
    if len(pts) < 4:
        return [], False
    origin = np.asarray(center, dtype=float).reshape(3)
    pa = _principal_axes(inertia)
    if pa.get("error"):
        return [], False
    R = np.asarray(pa["eigenvectors"], dtype=float)
    if R.shape != (3, 3):
        return [], False
    local = (pts - origin) @ R
    ext = (local.max(axis=0) - local.min(axis=0)).tolist()
    return sorted(ext), True


def _rod_dims_from_bbox(bbox: Dict[str, float]) -> Tuple[float, float]:
    """Ø и длина по AABB (вал или диск)."""
    axis = _bbox_axis_profile(bbox)
    return axis["diameter"], axis["length"]


def _rod_dims_from_extents(sm: float, mid: float, lg: float) -> Tuple[float, float]:
    """
    Ø и длина прутка по трём главным размерам.
    Диск: два больших ≈ Ø, малый — толщина. Вал: малый+средний ≈ Ø, большой — длина.
    """
    if lg > 0 and sm / lg < 0.45 and abs(lg - mid) / lg < 0.2:
        return max(mid, lg), sm
    return max(sm, mid), lg


def _refine_rod_diameter(
    d_geom: float,
    shafts: List[Dict],
    *,
    axis: Optional[Dict[str, Any]] = None,
) -> float:
    """Согласовать Ø геометрии с наружными цилиндрическими гранями STEP."""
    d_cyl = max((float(s.get("diameter", 0)) for s in shafts), default=0.0)
    if d_cyl <= 0:
        return d_geom
    if d_geom <= 0:
        return d_cyl
    # Диск/корпус: наружный контур часто многоугольный (плоские грани), не цилиндр.
    if axis and axis.get("is_disc") and d_geom > d_cyl * 1.08:
        return d_geom
    if d_geom < d_cyl * 0.92:
        return d_cyl
    if d_geom > d_cyl * 1.08:
        return d_cyl
    return min(d_geom, d_cyl)


def _finished_dimensions(
    shape,
    center,
    inertia,
    shafts: List[Dict],
    processes: List[str],
    bbox: Dict[str, float],
    face_counts: Optional[Dict[str, int]] = None,
    *,
    rot_profile: Optional[Dict[str, Any]] = None,
    part_family: str = "plate",
) -> Dict[str, Any]:
    """Чистовые габариты детали (не заготовка, не описанный цилиндр AABB)."""
    shafts = shafts or []
    processes = processes or []
    face_counts = face_counts or {}
    rev = _revolution_geometry_profile(
        face_counts, bbox, shafts, rot_profile=rot_profile
    )
    ext, ok = _principal_extents(shape, center, inertia)
    if not ok:
        ext = sorted([bbox["x"], bbox["y"], bbox["z"]])
    sm, mid, lg = ext[0], ext[1], ext[2]
    cyl = len(shafts)
    axis = _bbox_axis_profile(bbox)
    turning = "Токарная" in processes
    turning_case = (rot_profile or {}).get("turning_case")
    as_rod = turning and turning_case in ("bar", "disc", "forging", "hybrid", None)
    if turning and part_family == "oversize" and turning_case not in ("bar", "disc", "forging", "hybrid"):
        as_rod = turning_case in ("forging", "disc")
    if not turning:
        as_rod = False

    if as_rod and (cyl >= 1 or axis["is_elongated_rod"] or lg / max(sm, 1e-9) >= 1.2):
        if rev.get("simple_blank") or axis["is_elongated_rod"] or axis.get("is_disc"):
            diameter, length = _rod_dims_from_bbox(bbox)
        else:
            diameter, length = _rod_dims_from_extents(sm, mid, lg)
            diameter = _refine_rod_diameter(diameter, shafts, axis=axis)
        if axis["is_elongated_rod"]:
            diameter = max(diameter, axis["diameter"])
            length = max(length, axis["length"])
        return {
            "format": "rod",
            "diameter": round(diameter, 1),
            "length": round(length, 1),
            "x": round(sm, 1),
            "y": round(mid, 1),
            "z": round(lg, 1),
        }
    return {
        "format": "box",
        "diameter": 0.0,
        "length": 0.0,
        "x": round(sm, 1),
        "y": round(mid, 1),
        "z": round(lg, 1),
    }


def _infer_workpiece(
    finished: Dict[str, Any],
    face_counts: Dict[str, int],
    processes: List[str],
    *,
    rot_profile: Optional[Dict[str, Any]] = None,
    part_family: str = "plate",
) -> Dict[str, Any]:
    """Заготовка: пруток, поковка или плита/блок по геометрии и токарке."""
    sm, mid, lg = finished.get("x", 0), finished.get("y", 0), finished.get("z", 0)
    rot_profile = rot_profile or {}
    turning_case = rot_profile.get("turning_case")
    outer_d = float(
        rot_profile.get("outer_diameter_mm") or finished.get("diameter") or 0
    )

    if turning_case == "forging" or (
        "Токарная" in processes
        and outer_d > config.BAR_STOCK_MAX_D_MM
    ):
        d = outer_d or max(sm, mid, lg)
        length = float(rot_profile.get("length_mm") or lg)
        return {
            "type": "Поковка",
            "diameter": round(d, 1),
            "length": round(length, 1),
        }

    use_cylinder = (
        finished.get("format") == "rod"
        and turning_case in ("bar", "disc", "hybrid", None)
        and outer_d <= config.BAR_STOCK_MAX_D_MM
    ) or (
        "Токарная" in processes
        and turning_case == "bar"
        and outer_d <= config.BAR_STOCK_MAX_D_MM
    )

    if use_cylinder:
        if finished.get("format") == "rod":
            diameter, length = finished["diameter"], finished["length"]
        else:
            diameter, length = _rod_dims_from_extents(sm, mid, lg)
        return {
            "type": "Пруток",
            "diameter": round(diameter, 1),
            "length": round(length, 1),
        }

    if part_family == "oversize":
        wp_type = "Блок"
    else:
        wp_type = "Плита"
    return {
        "type": wp_type,
        "width": round(finished.get("x", 0), 1),
        "length": round(finished.get("y", 0), 1),
        "height": round(finished.get("z", 0), 1),
    }


def _complexity_metrics(
    volume: float,
    area: float,
    bbox: Dict[str, float],
    topo: Dict[str, int],
    face_counts: Dict[str, int],
    holes: Optional[List[Dict]] = None,
    part_family: str = "plate",
    *,
    hybrid_turn_mill: bool = False,
) -> Dict[str, Any]:
    """Безразмерные индексы сложности (не зависят только от объёма)."""
    vol = max(volume, 1e-9)
    sa_v = area / vol if vol > 0 else 0.0
    vol_23 = vol ** (2.0 / 3.0)
    detail_index = area / vol_23 if vol_23 > 0 else 0.0
    dims = sorted([bbox["x"], bbox["y"], bbox["z"]], reverse=True)
    elongation = dims[0] / max(dims[2], 1e-9) if dims[2] > 0 else 0.0

    fc = topo.get("face_count", 0)
    cyl = face_counts.get("cyl_face_count", 0)
    plane = face_counts.get("plane_face_count", 0)
    torus = face_counts.get("torus_face_count", 0)
    other_fc = face_counts.get("other_face_count", 0)

    if part_family == "rod":
        part_type = "Пруток"
    elif part_family == "impeller":
        part_type = "Крыльчатка"
    elif part_family == "oversize":
        part_type = "Крупногабаритная деталь"
    elif part_family == "hybrid_shaft":
        part_type = "Вал-корпус (гибрид)"
    else:
        part_type = "Плита"

    complexity = (
        "высокая"
        if sa_v > 0.3
        or fc > 500
        or part_family == "hybrid_shaft"
        or hybrid_turn_mill
        or detail_index >= 17.0
        else "средняя"
        if sa_v > 0.15 or fc > 100
        else "низкая"
    )
    return {
        "surface_to_volume_ratio": round(sa_v, 5),
        "detail_index": round(detail_index, 5),
        "elongation_index": round(elongation, 4),
        "part_type_hint": part_type,
        "operation_type_hint": "Фрезерная",
        "operations": [],
        "complexity_hint": complexity,
        "thin_walls_hint": False,
    }


def _primitive_price(volume_mm3: float) -> float:
    return round(volume_mm3 * config.PRICE_PER_MM3, 2)


def _read_shape(step_path: str):
    from OCC.Core.STEPControl import STEPControl_Reader
    reader = STEPControl_Reader()
    if reader.ReadFile(step_path) != 1:
        raise ValueError(f"Не удалось прочитать STEP: {step_path}")
    reader.TransferRoots()
    return reader.OneShape()


def extract_step_path(
    step_path: str,
    save_faces_edges: bool = False,
    skip_edges: bool = False,
    fast: bool = False,
    force_wall_thickness: bool = False,
) -> Dict[str, Any]:
    """
    Извлечь все метрики из файла STEP.
    Возвращает dict, готовый для database.insert_part и API.
    """
    if not os.path.isfile(step_path):
        raise FileNotFoundError(step_path)

    file_name = os.path.basename(step_path)
    result: Dict[str, Any] = {
        "file_path": os.path.abspath(step_path),
        "file_name": file_name,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": "ok",
        "error_message": None,
    }

    try:
        shape = _read_shape(step_path)
        volume, area, center, inertia = _volume_props(shape)
        bbox = _bounding_box(shape)
        topo = _topology_counts(shape)
        avg_dim = (bbox["x"] + bbox["y"] + bbox["z"]) / 3.0
        faces, face_counts, holes, shafts = _face_details(shape, avg_dim, bbox, fast=fast)
        if fast or skip_edges or topo.get("edge_count", 0) > 8000:
            edges, sharp_count = [], 0
        else:
            edges, sharp_count = _edge_details(shape)
        void_info = _void_hint(step_path, volume) if not fast else {
            "has_internal_void": None,
            "void_volume_mm3": None,
            "note": "fast_analyze",
        }
        meta = _caf_metadata(step_path)
        vol_safe = max(volume, 1e-9)
        detail_index = area / (vol_safe ** (2.0 / 3.0)) if vol_safe > 0 else 0.0
        sa_v_early = area / vol_safe if vol_safe > 0 else 0.0
        rot_shell = _rotation_shell_profile(
            shape, bbox, face_counts, shafts=shafts
        )
        base_family = _detect_part_family(
            face_counts,
            bbox,
            topo,
            detail_index=detail_index,
            rot_profile=rot_shell,
        )
        part_family = _resolve_part_family(
            face_counts, bbox, topo, detail_index=detail_index, volume_mm3=volume
        )
        hybrid_turn_mill = _is_hybrid_turn_mill_body(
            face_counts,
            bbox,
            face_count=topo.get("face_count", 0),
            part_name=file_name,
        )
        wall_run_p = _wall_thickness_run_probability(
            surface_to_volume_ratio=sa_v_early,
            detail_index=detail_index,
            part_family=part_family,
            base_family=base_family,
            bbox=bbox,
            face_counts=face_counts,
            topo=topo,
            rot_profile=rot_shell,
            hybrid_turn_mill=hybrid_turn_mill,
            volume_mm3=volume,
        )
        wall_info = _resolve_wall_thickness_info(
            shape,
            bbox,
            topo.get("face_count", 0),
            fast=fast,
            force_wall_thickness=force_wall_thickness,
            run_probability=wall_run_p,
        )

        rod_meta: Optional[Dict[str, Any]] = None
        hex_head_stud = False
        if part_family == "rod":
            rod_meta = _analyze_rod_family(shape, bbox)
            holes = rod_meta["holes"]
            shafts = rod_meta["shafts"]
            face_counts["holes_count"] = rod_meta["holes_feature_count"]
            face_counts["shafts_count"] = rod_meta["shafts_feature_count"]
            hex_head_stud = _is_hex_head_stud(
                rot_shell,
                bbox,
                face_counts,
                shafts,
                part_family=part_family,
                part_name=file_name,
            )
            if hex_head_stud:
                rod_meta["hex_head_stud"] = True
        else:
            holes = _holes_from_bore_clustering(shape, bbox)
            face_counts["holes_count"] = len(holes)
        rot_profile = dict(rot_shell)
        tc, t_rot, t_skip = _evaluate_turning_case(
            rot_profile,
            bbox,
            part_family=part_family,
            hybrid_turn_mill=hybrid_turn_mill,
            part_name=file_name,
            face_counts=face_counts,
            shafts=shafts,
            hex_head_stud=hex_head_stud,
        )
        rot_profile["turning_case"] = tc
        rot_profile["rotational"] = t_rot
        rot_profile["turning_skip_reason"] = t_skip
        proc_meta: Dict[str, Any] = dict(rod_meta or {})
        if hybrid_turn_mill:
            proc_meta["hybrid_turn_mill"] = True
        proc_meta["rotation_profile"] = rot_profile
        processes = _infer_processes(
            face_counts,
            bbox,
            holes,
            shafts,
            face_count=topo.get("face_count", 0),
            detail_index=detail_index,
            part_family=part_family,
            rod_meta=proc_meta,
            rot_profile=rot_profile,
            part_name=file_name,
        )
        complexity = _complexity_metrics(
            volume,
            area,
            bbox,
            topo,
            face_counts,
            holes,
            part_family=part_family,
            hybrid_turn_mill=hybrid_turn_mill,
        )
        complexity["thin_walls_hint"] = wall_info.get("thin_walls", False)
        complexity["operations"] = processes
        complexity["operation_type_hint"] = processes[0] if processes else "Фрезерная"
        finished = _finished_dimensions(
            shape,
            center,
            inertia,
            shafts,
            processes,
            bbox,
            face_counts,
            rot_profile=rot_profile,
            part_family=part_family,
        )
        workpiece = _infer_workpiece(
            finished,
            face_counts,
            processes,
            rot_profile=rot_profile,
            part_family=part_family,
        )

        part_name = meta.get("part_name") or os.path.splitext(file_name)[0]
        principal = _principal_axes(inertia)
        setup_counts = count_setups_from_shape(
            shape,
            center,
            principal,
            bbox,
            avg_dim,
            part_family,
            processes,
            rod_meta=proc_meta,
        )

        result["holes"] = holes
        result["shafts"] = shafts

        result.update({
            "part_name": part_name,
            "volume_mm3": round(volume, 4),
            "surface_area_mm2": round(area, 4),
            "bbox_x_mm": round(bbox["x"], 4),
            "bbox_y_mm": round(bbox["y"], 4),
            "bbox_z_mm": round(bbox["z"], 4),
            "center_x": round(float(center[0]), 6),
            "center_y": round(float(center[1]), 6),
            "center_z": round(float(center[2]), 6),
            "inertia_ij": inertia.tolist(),
            "principal_axes": principal,
            "face_count": topo["face_count"],
            "edge_count": topo["edge_count"],
            "vertex_count": topo["vertex_count"],
            "solid_count": topo["solid_count"],
            "min_wall_thickness_mm": wall_info.get("min_wall_thickness_mm"),
            "wall_thickness_median_mm": wall_info.get("wall_thickness_median_mm"),
            "thin_walls": wall_info.get("thin_walls", False),
            "thin_wall_ratio": wall_info.get("thin_wall_ratio", 0.0),
            "min_wall_thickness_note": wall_info.get("note", WALL_THICKNESS_NOTE),
            "wall_thickness_run_probability": round(wall_run_p, 4),
            "has_internal_void": void_info.get("has_internal_void"),
            "void_volume_mm3": void_info.get("void_volume_mm3"),
            "proj_area_xy_mm2": round(bbox["proj_xy"], 4),
            "proj_area_xz_mm2": round(bbox["proj_xz"], 4),
            "proj_area_yz_mm2": round(bbox["proj_yz"], 4),
            "max_height_x_mm": round(bbox["x"], 4),
            "max_height_y_mm": round(bbox["y"], 4),
            "max_height_z_mm": round(bbox["z"], 4),
            "curvature_note": CURVATURE_TODO,
            "cad_color": meta.get("cad_color"),
            "cad_layer": meta.get("cad_layer"),
            "cad_material": meta.get("cad_material"),
            "surface_to_volume_ratio": complexity["surface_to_volume_ratio"],
            "detail_index": complexity["detail_index"],
            "elongation_index": complexity["elongation_index"],
            "small_face_count": face_counts.get("small_face_count", 0),
            "sharp_edge_count": sharp_count,
            "cyl_face_count": face_counts.get("cyl_face_count", 0),
            "plane_face_count": face_counts.get("plane_face_count", 0),
            "operation_type_hint": complexity["operation_type_hint"],
            "operations": processes,
            "finished_dimensions": finished,
            "workpiece": workpiece,
            "part_type_hint": complexity["part_type_hint"],
            "part_family": part_family,
            "rotation_confidence": rot_profile.get("rotation_confidence"),
            "rotation_profile": {
                k: rot_profile.get(k)
                for k in (
                    "outer_cyl_area_share",
                    "bore_cyl_area_share",
                    "main_axis_coaxiality",
                    "outer_diameter_span",
                    "plane_penalty",
                    "rotational",
                    "turning_case",
                    "turning_skip_reason",
                    "outer_diameter_mm",
                    "ld_ratio",
                )
            },
            "hybrid_turn_mill": hybrid_turn_mill,
            "complexity_hint": complexity["complexity_hint"],
            "price_primitive": _primitive_price(volume),
            "notes": "",
            "rod_features": rod_meta.get("features") if rod_meta else None,
            "hex_head_stud": bool(rod_meta.get("hex_head_stud")) if rod_meta else False,
            "setup_count_turning": setup_counts.get("setup_count_turning", 0),
            "setup_count_milling": setup_counts.get("setup_count_milling", 0),
            "setup_count_total": setup_counts.get("setup_count_total", 1),
            "setup_planes": setup_counts.get("setup_planes"),
        })

        result["raw_json"] = to_api_format(result)

        if save_faces_edges and config.ENABLE_FACE_EDGE_TABLES:
            result["_faces"] = faces
            result["_edges"] = edges

    except Exception as e:
        result["status"] = "error"
        result["error_message"] = str(e)

    return result


def extract_step_bytes(
    file_bytes: bytes,
    file_name: str = "model.stp",
    skip_edges: bool = True,
    fast: bool | None = None,
    force_wall_thickness: bool = False,
) -> Dict[str, Any]:
    """Извлечение из байтов (временный файл). skip_edges/fast ускоряют API."""
    import tempfile

    if fast is None:
        fast = len(file_bytes) >= 512 * 1024
    suffix = ".stp" if not file_name.lower().endswith((".stp", ".step")) else ""
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix or ".stp") as tmp:
        tmp.write(file_bytes)
        path = tmp.name
    try:
        return extract_step_path(
            path,
            skip_edges=skip_edges or fast,
            fast=fast,
            force_wall_thickness=force_wall_thickness,
        )
    finally:
        if os.path.exists(path):
            os.unlink(path)


def build_expert_geometry_brief(project_name: str, data: Dict[str, Any]) -> str:
    """
    Сводка геометрии STEP для экспертного анализа.
    Учитывает валы с наружным Ø < 20 мм; не использует порог «>20 мм = вал».
    """
    if not data:
        return "Данные STEP отсутствуют."

    name_low = (project_name or data.get("project_name") or "").lower()
    geom = dict(data.get("geometry") or {})
    pf = str(data.get("part_family") or geom.get("part_family") or "")
    ms = dict(data.get("model_size") or data.get("finished_dimensions") or {})
    dims = dict(data.get("dimensions") or {})
    elong = float(data.get("elongation_index") or geom.get("elongation_index") or 0)
    holes = list(data.get("holes") or geom.get("holes") or [])
    shafts = list(data.get("shafts") or geom.get("shafts") or [])
    rod_features = data.get("rod_features") or []
    ops = data.get("operations") or []
    if isinstance(ops, str):
        ops = [p.strip() for p in ops.split(",") if p.strip()]

    body_d = float(ms.get("diameter") or 0)
    body_l = float(ms.get("length") or 0)
    if body_d <= 0 and dims:
        sm, mid, lg = sorted([float(dims.get("x") or 0), float(dims.get("y") or 0), float(dims.get("z") or 0)])
        axis = _bbox_axis_profile({"x": sm, "y": mid, "z": lg})
        body_d = float(axis.get("diameter") or max(sm, mid))
        body_l = float(axis.get("length") or lg)

    is_shaft_name = any(k in name_low for k in ("вал", "shaft", "ось", "шпиндель"))
    is_rod_family = pf == "rod"
    is_elongated = elong >= 2.5
    is_shaft_like = is_shaft_name or (is_rod_family and is_elongated)

    lines: List[str] = []

    if is_shaft_like:
        part_label = "вал" if is_shaft_name else "пруток/вал"
        lines.append(f"Классификация: {part_label} (семейство {pf or 'rod'}, удлинение {elong:.1f}).")
        if body_d > 0:
            lines.append(
                f"Тело детали — наружный цилиндрический контур Ø{body_d:.1f}×{body_l:.1f} мм "
                f"(габариты {dims.get('x', '?')}×{dims.get('y', '?')}×{dims.get('z', '?')} мм). "
                f"Это основной вал, не отверстие."
            )
        if shafts:
            ds = ", ".join(f"Ø{float(s.get('diameter', 0)):.1f}" for s in shafts[:6])
            lines.append(f"Наружные диаметры по граням: {ds} мм.")
        if holes:
            hs = ", ".join(
                f"Ø{float(h.get('diameter', 0)):.1f}"
                + (f" ({h.get('feature')})" if h.get("feature") else "")
                for h in holes[:8]
            )
            lines.append(f"Отверстия / внутренние цилиндры: {hs} мм.")
        elif rod_features:
            lines.append(f"Технологические признаки: {json.dumps(rod_features, ensure_ascii=False)}.")
        else:
            lines.append("Отдельные сквозные/глухие отверстия по STEP не выделены.")
        lines.append(
            "Правило: наружный контур вала может быть Ø8–20 мм — не считать его отверстием. "
            "Отверстия — только внутренние цилиндры меньше наружного Ø или поперечные каналы."
        )
    elif pf == "impeller":
        lines.append("Классификация: крыльчатка / сложное тело вращения.")
        if body_d > 0:
            lines.append(f"Габарит вращения ~Ø{body_d:.1f}×{body_l:.1f} мм.")
    elif pf == "oversize":
        lines.append(
            "Классификация: крупногабаритная деталь (габарит > 400 мм и/или масса > 100 кг); "
            "обработка на крупных станках с ЧПУ."
        )
        if geom.get("hybrid_turn_mill") or data.get("hybrid_turn_mill"):
            lines.append(
                "Гибрид: длинный корпус с прямоугольным сечением — токарная обработка с двух торцов "
                "(установы на противоположных торцах) + фрезерные карманы по граням корпуса."
            )
    elif pf == "hybrid_shaft":
        lines.append(
            "Классификация: вал-корпус (гибрид) — не классический пруток: основное тело "
            "прямоугольного сечения (часто полое), токарка торцов с двух сторон, "
            "фрезерование карманов (в т.ч. радиусы 15/25 мм) по боковым граням."
        )
    elif pf == "plate":
        lines.append("Классификация: плита / корпус.")
    else:
        lines.append(f"Классификация: {geom.get('family') or pf or 'деталь общего типа'}.")

    t_min = data.get("min_wall_thickness_mm")
    if t_min is None:
        t_min = geom.get("min_wall_thickness_mm")
    thin = data.get("thin_walls")
    if thin is None:
        thin = geom.get("thin_walls")
    if t_min is not None:
        lines.append(
            f"Тонкостенность (OCC ray-casting): мин. стенка {float(t_min):.2f} мм, "
            f"тонкие стенки: {'да' if thin else 'нет'}."
        )

    if ops:
        lines.append(f"Рекомендуемые процессы (STEP): {', '.join(ops)}.")
    wp = data.get("workpiece") or {}
    if wp:
        wt = wp.get("type", "")
        if wt in ("Пруток", "Вал") or pf == "rod":
            lines.append(f"Заготовка: пруток Ø{wp.get('diameter', '?')}×{wp.get('length', '?')} мм.")
        else:
            lines.append(f"Заготовка: {wt}.")

    return "\n".join(lines)


def to_api_format(metrics: Dict[str, Any], faces_list: Optional[List] = None) -> Dict[str, Any]:
    """Формат для совместимости с app.py / analyze-step."""
    if metrics.get("status") == "error":
        return {
            "volume": 0,
            "surface_area": 0,
            "dimensions": {"x": 0, "y": 0, "z": 0},
            "error": metrics.get("error_message"),
        }
    raw = metrics.get("raw_json")
    if isinstance(raw, dict) and "volume" in raw:
        return raw

    finished = metrics.get("finished_dimensions") or {}
    dims = {
        "x": finished.get("x", metrics.get("bbox_x_mm", 0)),
        "y": finished.get("y", metrics.get("bbox_y_mm", 0)),
        "z": finished.get("z", metrics.get("bbox_z_mm", 0)),
    }
    part_family = metrics.get("part_family", "plate")
    family_labels = {
        "rod": "Пруток",
        "impeller": "Крыльчатка",
        "plate": "Плита",
        "oversize": "Крупногабаритная деталь",
        "hybrid_shaft": "Вал-корпус (гибрид)",
    }
    family_label = family_labels.get(
        part_family,
        metrics.get("part_type_hint") or "Плита",
    )
    return {
        "volume": metrics.get("volume_mm3", 0),
        "surface_area": metrics.get("surface_area_mm2", 0),
        "dimensions": dims,
        "model_size": finished,
        "bbox_dimensions": {
            "x": metrics.get("bbox_x_mm", 0),
            "y": metrics.get("bbox_y_mm", 0),
            "z": metrics.get("bbox_z_mm", 0),
        },
        "face_count": metrics.get("face_count", 0),
        "edge_count": metrics.get("edge_count", 0),
        "vertex_count": metrics.get("vertex_count", 0),
        "surface_to_volume_ratio": metrics.get("surface_to_volume_ratio", 0),
        "detail_index": metrics.get("detail_index", 0),
        "elongation_index": metrics.get("elongation_index", 0),
        "complexity": metrics.get("complexity_hint", "неизвестно"),
        "thin_walls": bool(metrics.get("thin_walls", False)),
        "min_wall_thickness_mm": metrics.get("min_wall_thickness_mm"),
        "wall_thickness_median_mm": metrics.get("wall_thickness_median_mm"),
        "part_type": metrics.get("part_type_hint", ""),
        "part_family": metrics.get("part_family", "plate"),
        "rod_features": metrics.get("rod_features"),
        "operations": metrics.get("operations") or (
            [metrics["operation_type_hint"]] if metrics.get("operation_type_hint") else []
        ),
        "operation_type": ", ".join(
            metrics.get("operations")
            or ([metrics["operation_type_hint"]] if metrics.get("operation_type_hint") else ["Фрезерная"])
        ),
        "workpiece": metrics.get("workpiece") or {},
        "price_primitive": metrics.get("price_primitive", 0),
        "center_of_mass": {
            "x": metrics.get("center_x"),
            "y": metrics.get("center_y"),
            "z": metrics.get("center_z"),
        },
        "principal_axes": metrics.get("principal_axes"),
        "inertia_matrix": metrics.get("inertia_ij"),
        "projection_areas": {
            "xy": metrics.get("proj_area_xy_mm2"),
            "xz": metrics.get("proj_area_xz_mm2"),
            "yz": metrics.get("proj_area_yz_mm2"),
        },
        "has_internal_void": metrics.get("has_internal_void"),
        "void_volume_mm3": metrics.get("void_volume_mm3"),
        "cad_color": metrics.get("cad_color"),
        "cad_material": metrics.get("cad_material"),
        "part_name": metrics.get("part_name"),
        "rotation_confidence": metrics.get("rotation_confidence"),
        "rotation_profile": metrics.get("rotation_profile"),
        "holes": metrics.get("holes") or [],
        "shafts": metrics.get("shafts") or [],
        "geometry": {
            "face_count": metrics.get("face_count", 0),
            "surface_area": metrics.get("surface_area_mm2", 0),
            "surface_to_volume_ratio": metrics.get("surface_to_volume_ratio", 0),
            "thin_walls": bool(metrics.get("thin_walls", False)),
            "min_wall_thickness_mm": metrics.get("min_wall_thickness_mm"),
            "wall_thickness_median_mm": metrics.get("wall_thickness_median_mm"),
            "complexity": metrics.get("complexity_hint"),
            "part_family": part_family,
            "family": family_label,
            "cyl_faces": metrics.get("cyl_face_count", 0),
            "plane_faces": metrics.get("plane_face_count", 0),
            "small_faces": metrics.get("small_face_count", 0),
            "sharp_edges": metrics.get("sharp_edge_count", 0),
            "detail_index": metrics.get("detail_index", 0),
            "elongation_index": metrics.get("elongation_index", 0),
            "hybrid_turn_mill": bool(metrics.get("hybrid_turn_mill")),
            "hex_head_stud": bool(metrics.get("hex_head_stud")),
            "rotation_confidence": metrics.get("rotation_confidence"),
            "rotation_profile": metrics.get("rotation_profile"),
            "holes": metrics.get("holes") or [],
            "shafts": metrics.get("shafts") or [],
            "setup_count_turning": metrics.get("setup_count_turning"),
            "setup_count_milling": metrics.get("setup_count_milling"),
            "setup_count_total": metrics.get("setup_count_total"),
            "setup_planes": metrics.get("setup_planes"),
        },
        "extraction": {
            "min_wall_thickness_note": metrics.get("min_wall_thickness_note"),
            "wall_thickness_run_probability": metrics.get("wall_thickness_run_probability"),
            "curvature_note": metrics.get("curvature_note"),
            "solid_count": metrics.get("solid_count"),
        },
        "error": None,
    }
