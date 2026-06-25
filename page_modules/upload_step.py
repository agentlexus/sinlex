"""STEP-анализ, геометрия, кэш session_state, восстановление из data.txt."""
import base64
import hashlib
import os

import requests
import streamlit as st

from upload_limits import (
    GLB_FETCH_TIMEOUT_SEC,
    STEP_ANALYZE_TIMEOUT_SEC,
    STEP_CASTING_ANALYZE_TIMEOUT_SEC,
    STEP_GLB_TIMEOUT_SEC,
    StepProcessingTimeout,
)
from utils import (
    api_resource_prefix,
    project_storage,
    user_storage_root,
    NGROK_URL,
    _apply_allowance,
    get_headers,
    load_project_params,
)

STEP_ANALYSIS_VERSION = "20260522_hybrid_shaft_v1"
CASTING_WALL_ANALYSIS_SUFFIX = "_casting_wall_v4"


def step_analysis_version() -> str:
    """Версия кэша анализа; для литья — с обязательной тонкостенностью."""
    if project_storage() == "casting":
        return f"{STEP_ANALYSIS_VERSION}{CASTING_WALL_ANALYSIS_SUFFIX}"
    return STEP_ANALYSIS_VERSION


WP_ROD = "Пруток"
WP_OPTIONS = [WP_ROD, "Плита", "Поковка", "Отливка"]

PART_FAMILY_LABELS = {
    "rod": "Пруток",
    "impeller": "Крыльчатка",
    "plate": "Плита",
    "oversize": "Крупногабаритная деталь",
    "hybrid_shaft": "Вал-корпус (гибрид)",
}


def normalize_wp_type(wp: str) -> str:
    """Старые проекты могли сохранять «Вал»."""
    return WP_ROD if wp in ("Вал", "вал") else wp


def is_rod_wp(wp: str) -> bool:
    return normalize_wp_type(wp or "") == WP_ROD


def rod_dims_from_box(x: float, y: float, z: float) -> tuple:
    """Ø и длина по трём размерам (диск или пруток)."""
    sm, md, lg = sorted([x, y, z])
    if lg > 0 and sm / lg < 0.45 and abs(lg - md) / lg < 0.2:
        return max(md, lg), sm
    return max(sm, md), lg


def format_model_dims(
    dimensions: dict,
    model_size: dict = None,
    operations: list = None,
    workpiece_type: str = None,
) -> str:
    """Чистовые габариты модели: Ø×L для токарных, иначе параллелепипед."""
    model_size = model_size or {}
    operations = operations or []
    dimensions = dimensions or {}
    x, y, z = dimensions.get("x", 0), dimensions.get("y", 0), dimensions.get("z", 0)

    def _rod_fmt(d: float, ln: float) -> str:
        return f"Ø{d:.0f} × {ln:.0f} мм"

    if model_size.get("format") == "rod":
        d = model_size.get("diameter", 0)
        ln = model_size.get("length", 0)
        if d and ln:
            return _rod_fmt(d, ln)

    use_rod = (
        "Токарная" in operations
        or is_rod_wp(workpiece_type or "")
        or (model_size.get("format") == "rod")
    )
    if x and y and z and use_rod:
        d, ln = rod_dims_from_box(x, y, z)
        return _rod_fmt(d, ln)

    if x and y and z:
        return f"{x:.0f} × {y:.0f} × {z:.0f} мм"
    return "—"


def infer_operations_from_geometry(geometry: dict, dimensions: dict = None) -> list:
    """Восстановить процессы из сохранённой geometry (старые data.txt без operations)."""
    geometry = geometry or {}
    dimensions = dimensions or {}
    fc = int(geometry.get("face_count") or 0)
    cyl = int(geometry.get("cyl_faces") or geometry.get("cyl_face_count") or 0)
    di = float(geometry.get("detail_index") or 0)
    elong = float(geometry.get("elongation_index") or 0)
    plane = int(geometry.get("plane_faces") or geometry.get("plane_face_count") or 0)
    ops: list = []

    rotational = cyl >= 3 and elong >= 1.2
    hex_stud = bool(geometry.get("hex_head_stud"))
    if not hex_stud and str(geometry.get("part_family") or "") == "rod":
        rp = geometry.get("rotation_profile") or {}
        x, y, z = (
            float(dimensions.get("x") or 0),
            float(dimensions.get("y") or 0),
            float(dimensions.get("z") or 0),
        )
        if x and y and z:
            sm, mid, lg = sorted([x, y, z])
            cross_square = abs(sm - mid) / max(sm, mid, 1e-9) < 0.15
            outer_share = float(rp.get("outer_cyl_area_share") or 0)
            hex_stud = cross_square and outer_share < 0.25 and plane >= 4 and elong >= 1.3

    if rotational or hex_stud:
        ops.append("Токарная")

    needs_5axis = fc >= 120 or di >= 12.0
    if needs_5axis:
        ops.append("Фрезерная (5-осевая)")
    elif hex_stud:
        ops.append("Фрезерная")
    elif plane >= 4 or fc >= 30 or (rotational and (plane >= 2 or cyl >= 20)):
        if "Фрезерная (5-осевая)" not in ops:
            ops.append("Фрезерная")

    if not ops:
        ops = ["Фрезерная"]
    seen = set()
    out = []
    for p in ops:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def maybe_apply_oversize_family(analysis: dict) -> None:
    """Крупногабарит: габарит > 400 мм и/или масса детали > 100 кг (по объёму STEP)."""
    if not analysis:
        return
    from extraction_tool.extractor import is_oversize_part

    bbox = analysis.get("bbox_dimensions") or {}
    if not float(bbox.get("x") or 0):
        dims = analysis.get("dimensions") or {}
        bbox = {"x": dims.get("x"), "y": dims.get("y"), "z": dims.get("z")}
    vol = float(analysis.get("volume") or analysis.get("volume_mm3") or 0)
    if not is_oversize_part(bbox, vol):
        return
    analysis["part_family"] = "oversize"
    analysis["part_type"] = PART_FAMILY_LABELS["oversize"]
    geom = dict(analysis.get("geometry") or {})
    geom["part_family"] = "oversize"
    geom["family"] = PART_FAMILY_LABELS["oversize"]
    geom["part_type"] = PART_FAMILY_LABELS["oversize"]
    analysis["geometry"] = geom


def infer_part_family_from_geometry(geometry: dict, dimensions: dict = None) -> str:
    """Семейство детали из geometry/dimensions, если part_family не сохранён."""
    geometry = geometry or {}
    dimensions = dimensions or {}
    if geometry.get("part_family"):
        return str(geometry["part_family"])

    x, y, z = (
        float(dimensions.get("x") or 0),
        float(dimensions.get("y") or 0),
        float(dimensions.get("z") or 0),
    )
    cyl = int(geometry.get("cyl_faces") or geometry.get("cyl_face_count") or 0)
    plane = int(geometry.get("plane_faces") or geometry.get("plane_face_count") or 0)
    fc = int(geometry.get("face_count") or 0)
    elong = float(geometry.get("elongation_index") or 0)
    plane_share = plane / fc if fc > 0 else 0.0

    if x > 0 and y > 0 and z > 0 and cyl >= 3:
        sm, mid, lg = sorted([x, y, z])
        cross_disc = mid / max(lg, 1e-9) >= 0.82
        thin_disc = sm / max(lg, 1e-9) < 0.55
        box_like = mid / max(lg, 1e-9) >= 0.45 and sm / max(mid, 1e-9) >= 0.35
        if plane_share >= 0.38 or box_like:
            return "plate"
        if cross_disc and thin_disc:
            return "rod"
        if elong >= 1.4 and not box_like and plane_share < 0.30:
            return "rod"

    if elong >= 1.8 and cyl >= 3 and plane_share < 0.30:
        return "rod"

    return "plate"


def infer_model_size_from_dims(
    dimensions: dict,
    operations: list = None,
    geometry: dict = None,
) -> dict:
    """model_size для старых проектов без finished_dimensions."""
    dimensions = dimensions or {}
    operations = operations or []
    geometry = geometry or {}
    x, y, z = (
        float(dimensions.get("x") or 0),
        float(dimensions.get("y") or 0),
        float(dimensions.get("z") or 0),
    )
    if not (x and y and z):
        return {}
    sm, mid, lg = sorted([x, y, z])
    plane = int(geometry.get("plane_faces") or geometry.get("plane_face_count") or 0)
    fc = int(geometry.get("face_count") or 0)
    plane_share = plane / fc if fc > 0 else 0.0
    box_like = mid / max(lg, 1e-9) >= 0.45 and sm / max(mid, 1e-9) >= 0.35
    use_rod = (
        "Токарная" in operations
        or (
            float(geometry.get("elongation_index") or 0) >= 1.4
            and plane_share < 0.38
            and not box_like
        )
        or infer_part_family_from_geometry(geometry, dimensions) == "rod"
    )
    if use_rod:
        cross_disc = mid / max(lg, 1e-9) >= 0.82 and sm / max(lg, 1e-9) < 0.55
        if cross_disc:
            d, ln = max(mid, lg), sm
        else:
            d, ln = rod_dims_from_box(x, y, z)
        return {
            "format": "rod",
            "diameter": round(d, 1),
            "length": round(ln, 1),
            "x": round(sm, 1),
            "y": round(mid, 1),
            "z": round(lg, 1),
        }
    return {
        "format": "box",
        "diameter": 0.0,
        "length": 0.0,
        "x": round(x, 1),
        "y": round(y, 1),
        "z": round(z, 1),
    }


def enrich_analysis_payload(data: dict) -> dict:
    """Дополнить урезанный снимок data.txt (operations, part_family, model_size)."""
    geom = dict(data.get("geometry") or {})
    dims = dict(data.get("dimensions") or {})
    ops = data.get("operations") or []
    if isinstance(ops, str):
        ops = [p.strip() for p in ops.split(",") if p.strip()]
    if not ops:
        ops = infer_operations_from_geometry(geom, dims)
    pf = str(data.get("part_family") or geom.get("part_family") or "")
    if not pf:
        pf = infer_part_family_from_geometry(geom, dims)
    model_size = dict(data.get("model_size") or {})
    if not model_size.get("format"):
        model_size = infer_model_size_from_dims(dims, ops, geom)
    enrich = {**data, "geometry": geom, "volume": data.get("volume")}
    maybe_apply_oversize_family(enrich)
    pf = str(enrich.get("part_family") or pf)
    geom = dict(enrich.get("geometry") or geom)
    geom["part_family"] = pf
    geom["family"] = PART_FAMILY_LABELS.get(pf, geom.get("family") or "—")
    return {
        "operations": ops,
        "operation_type": data.get("operation_type") or ", ".join(ops),
        "part_family": pf,
        "part_type": enrich.get("part_type") or geom.get("part_type") or "",
        "model_size": model_size,
        "geometry": geom,
    }


def format_part_family(geometry: dict = None, analysis: dict = None) -> str:
    """Подпись семейства детали для UI."""
    geometry = geometry or {}
    analysis = analysis or {}
    if geometry.get("family"):
        return str(geometry["family"])
    code = geometry.get("part_family") or analysis.get("part_family")
    if code in PART_FAMILY_LABELS:
        return PART_FAMILY_LABELS[code]
    hint = analysis.get("part_type") or geometry.get("part_type")
    if hint:
        return str(hint)
    return "—"


def step_file_digest(file_bytes: bytes) -> str:
    return hashlib.sha256(file_bytes).hexdigest()


def step_analysis_cache_valid(file_bytes: bytes) -> bool:
    return (
        st.session_state.get("step_analysis_digest") == step_file_digest(file_bytes)
        and st.session_state.get("step_analysis_version") == step_analysis_version()
        and bool(st.session_state.get("operations"))
    )


def invalidate_step_analysis_cache() -> None:
    for key in (
        "step_analysis",
        "step_analysis_digest",
        "step_analysis_version",
        "operations",
        "op_type",
        "model_size",
        "workpiece_analysis",
        "geometry",
        "model_dimensions",
    ):
        st.session_state.pop(key, None)


def reset_step_processing_session(
    *,
    slug: str | None = None,
    clear_upload: bool = False,
) -> None:
    """
    Сброс кэша GLB/анализа после ошибки или таймаута (чтобы страница не «висела»).
    """
    invalidate_step_analysis_cache()
    for key in (
        "glb_cache",
        "glb_size",
        "model_volume_cache",
        "cached_file_name",
        "surface_area",
        "detail_index",
        "_step_load_in_progress",
    ):
        st.session_state.pop(key, None)
    if slug:
        st.session_state.pop(f"_glb_staged_{slug}", None)
    if clear_upload:
        st.session_state.pop("cached_step", None)
        st.session_state.pop("cached_step_name", None)
        st.session_state.pop("auto_process", None)


def user_folder() -> str:
    return st.session_state.get("user_folder", "") or ""


def safe_dir_name(project_name: str) -> str:
    return project_name.replace(" ", "_").replace("/", "_")


def project_key_slug(project_name: str) -> str:
    """Ключ Streamlit без точек и спецсимволов (точки в ключе ломают session_state)."""
    return hashlib.md5(project_name.encode("utf-8")).hexdigest()[:16]


def apply_step_analysis(analysis: dict) -> None:
    """Сохранить расширенный анализ STEP в session_state."""
    if not analysis:
        return
    maybe_apply_oversize_family(analysis)
    st.session_state["step_analysis"] = analysis
    st.session_state["model_dimensions"] = analysis.get("dimensions", {})
    st.session_state["model_size"] = analysis.get("model_size") or {}
    ops = analysis.get("operations") or []
    if not ops and analysis.get("operation_type"):
        ops = [p.strip() for p in str(analysis["operation_type"]).split(",") if p.strip()]
    st.session_state["operations"] = ops
    st.session_state["op_type"] = ", ".join(ops) if ops else "Фрезерная"
    wa = dict(analysis.get("workpiece") or {})
    if wa.get("type") in ("Вал", "вал"):
        wa["type"] = WP_ROD
    st.session_state["workpiece_analysis"] = wa
    geom = dict(analysis.get("geometry") or {})
    if analysis.get("part_family") and "part_family" not in geom:
        geom["part_family"] = analysis["part_family"]
    if analysis.get("part_type") and "part_type" not in geom:
        geom["part_type"] = analysis["part_type"]
    if "family" not in geom:
        code = geom.get("part_family") or analysis.get("part_family")
        geom["family"] = PART_FAMILY_LABELS.get(code, analysis.get("part_type") or "—")
    st.session_state["geometry"] = geom
    st.session_state["detail_index"] = analysis.get("detail_index") or geom.get("detail_index", 0)
    st.session_state["surface_area"] = analysis.get("surface_area", 0)


def data_has_user_blank(data: dict) -> bool:
    """В data.txt есть размеры заготовки, заданные клиентом (не только авто-анализ)."""
    if not data:
        return False
    wt = normalize_wp_type(data.get("workpiece_type") or "")
    if is_rod_wp(wt):
        return int(float(data.get("diam") or 0)) > 0 or int(float(data.get("length") or 0)) > 0
    return any(int(float(data.get(k) or 0)) > 0 for k in ("width", "length", "height"))


def mark_user_blank_dims_locked(data: dict = None) -> None:
    """Зафиксировать: размеры заготовки из формы/сохранения, не подменять авто-расчётом."""
    if data is not None and data_has_user_blank(data):
        st.session_state["user_blank_dims_locked"] = True


def reconcile_blank_dims_from_analysis() -> None:
    """Сбросить устаревшие Ø/L/W/H из bbox, если объём снятия завышен относительно workpiece."""
    if st.session_state.get("user_blank_dims_locked"):
        return
    from machining_cost import blank_dims_with_allowance, blank_volume_mm3

    mv = float(st.session_state.get("model_volume_cache") or 0)
    if mv <= 0:
        return
    dims = st.session_state.get("model_dimensions") or {}
    wa = st.session_state.get("workpiece_analysis") or {}
    if not dims and not wa:
        return
    wp = normalize_wp_type(st.session_state.get("wp", WP_ROD))
    ops = st.session_state.get("operations") or []
    calc = blank_dims_with_allowance(
        wp,
        workpiece=wa,
        model_size=st.session_state.get("model_size"),
        dimensions=dims,
        operations=ops,
    )
    if is_rod_wp(wp):
        sd, sl = float(st.session_state.get("diam") or 0), float(st.session_state.get("len") or 0)
        cd, cl = calc["diameter"], calc["length"]
        saved_vol = blank_volume_mm3(wp, sd, sl)
        calc_vol = blank_volume_mm3(wp, cd, cl)
    else:
        sw, sl, sh = (
            float(st.session_state.get("wid") or 0),
            float(st.session_state.get("len") or 0),
            float(st.session_state.get("hei") or 0),
        )
        cw, cl, ch = calc["width"], calc["length"], calc["height"]
        saved_vol = blank_volume_mm3(wp, width=sw, length=sl, height=sh)
        calc_vol = blank_volume_mm3(wp, width=cw, length=cl, height=ch)

    if saved_vol <= calc_vol * 1.12:
        return
    if is_rod_wp(wp):
        st.session_state["diam"] = int(cd)
        st.session_state["len"] = int(cl)
    else:
        st.session_state["wid"] = int(cw)
        st.session_state["len"] = int(cl)
        st.session_state["hei"] = int(ch)


def _restore_drawing_artifacts_from_project_data(data: dict) -> None:
    pn = data.get("project_name") or st.session_state.get("current_project")
    if not pn:
        return
    slug = project_key_slug(str(pn))
    try:
        import sys
        from pathlib import Path

        page_dir = Path(__file__).resolve().parent
        if str(page_dir) not in sys.path:
            sys.path.insert(0, str(page_dir))
        from pdf_analysis import restore_drawing_artifacts_to_session

        restore_drawing_artifacts_to_session(data, slug)
    except Exception:
        pass


def restore_project_from_data(data: dict) -> None:
    """Восстановить session_state из data.txt (полный анализ + заготовка)."""
    if not data:
        return
    analysis = data.get("step_analysis")
    if isinstance(analysis, dict) and analysis.get("volume") is not None:
        if not analysis.get("operations"):
            patch = enrich_analysis_payload(
                {**data, **analysis, "geometry": analysis.get("geometry") or data.get("geometry")}
            )
            analysis = {**analysis, **patch}
        apply_step_analysis(analysis)
    elif data.get("geometry") or data.get("operations"):
        patch = enrich_analysis_payload(data)
        apply_step_analysis({
            "volume": data.get("volume", 0),
            "surface_area": data.get("surface_area", 0),
            "dimensions": data.get("dimensions") or {},
            "geometry": patch["geometry"],
            "model_size": patch["model_size"],
            "operations": patch["operations"],
            "operation_type": patch["operation_type"],
            "workpiece": data.get("workpiece") or data.get("workpiece_analysis") or {},
            "part_family": patch["part_family"],
            "part_type": patch["part_type"],
            "rod_features": data.get("rod_features"),
            "detail_index": data.get("detail_index") or (patch["geometry"] or {}).get("detail_index"),
        })
    if data.get("material"):
        st.session_state["mat"] = data["material"]
    if data.get("workpiece_type"):
        st.session_state["wp"] = normalize_wp_type(data["workpiece_type"])
    _sess_keys = {
        "diam": "diam",
        "length": "len",
        "width": "wid",
        "height": "hei",
        "cost_per_hour": "cost_h",
        "cam_rate": "cam_rate",
    }
    for key, sess_key in _sess_keys.items():
        if data.get(key) is not None:
            try:
                st.session_state[sess_key] = int(float(data[key]))
            except (TypeError, ValueError):
                pass
    if data.get("batch_size") is not None:
        try:
            st.session_state["saved_batch_size"] = int(float(data["batch_size"]))
        except (TypeError, ValueError):
            pass
    if data.get("volume") is not None:
        try:
            st.session_state["model_volume_cache"] = float(data["volume"])
        except (TypeError, ValueError):
            pass
    if data.get("step_analysis_version"):
        st.session_state["step_analysis_version"] = data["step_analysis_version"]
    if data.get("step_file_digest"):
        st.session_state["step_analysis_digest"] = data["step_file_digest"]
    mark_user_blank_dims_locked(data)
    reconcile_blank_dims_from_analysis()
    _restore_drawing_artifacts_from_project_data(data)


def persist_analysis_to_data_txt(project_name: str, analysis: dict, file_bytes: bytes = None) -> None:
    from project_store import persist_step_analysis

    digest = step_file_digest(file_bytes) if file_bytes else st.session_state.get("step_analysis_digest", "")
    persist_step_analysis(
        project_name,
        analysis,
        user_folder(),
        storage=project_storage(),
        analysis_version=step_analysis_version(),
        step_digest=digest,
    )


def try_restore_analysis_from_data_txt(project_name: str, file_bytes: bytes) -> bool:
    """Вернуть True, если анализ восстановлен из data.txt без API."""
    from project_store import load_project_data

    data = load_project_data(project_name, user_folder(), storage=project_storage())
    if not data.get("step_analysis") and not data.get("geometry"):
        return False
    if data.get("step_analysis_version") != step_analysis_version():
        return False
    digest = data.get("step_file_digest")
    if digest and file_bytes and digest != step_file_digest(file_bytes):
        return False
    if not data.get("step_analysis") and data.get("geometry"):
        patch = enrich_analysis_payload(data)
        if not patch.get("operations"):
            return False
    restore_project_from_data(data)
    return True


def run_step_analysis(file_name: str, file_bytes: bytes, project_name: str) -> float:
    """Запрос analyze-step и обновление session_state. Возвращает объём модели."""
    try:
        files_a = {"file": (file_name, file_bytes, "application/octet-stream")}
        analyze_params = {}
        is_casting = project_storage() == "casting"
        if is_casting:
            analyze_params["casting"] = "true"
        analyze_timeout = STEP_CASTING_ANALYZE_TIMEOUT_SEC if is_casting else STEP_ANALYZE_TIMEOUT_SEC
        resp_a = requests.post(
            f"{NGROK_URL}/analyze-step",
            files=files_a,
            params=analyze_params,
            headers=get_headers(),
            timeout=analyze_timeout,
        )
        if resp_a.status_code != 200:
            return 0.0
        analysis = resp_a.json()
        model_volume = float(analysis.get("volume", 0) or 0)
        apply_step_analysis(analysis)
        persist_analysis_to_data_txt(project_name, analysis, file_bytes)
        _apply_allowance(
            st.session_state["model_dimensions"],
            st.session_state.get("workpiece_analysis"),
            st.session_state.get("operations"),
        )
        saved = load_project_params(project_name)
        if saved:
            if saved.get("material"):
                st.session_state["mat"] = saved["material"]
            if saved.get("workpiece_type"):
                st.session_state["wp"] = normalize_wp_type(saved["workpiece_type"])
            if saved.get("diam"):
                st.session_state["diam"] = int(saved["diam"])
            if saved.get("length"):
                st.session_state["len"] = int(saved["length"])
            if saved.get("width"):
                st.session_state["wid"] = int(saved["width"])
            if saved.get("height"):
                st.session_state["hei"] = int(saved["height"])
            if saved.get("cost_per_hour"):
                st.session_state["cost_h"] = int(saved["cost_per_hour"])
            if saved.get("cam_rate") is not None:
                st.session_state["cam_rate"] = int(saved["cam_rate"])
            if saved.get("batch_size"):
                st.session_state["saved_batch_size"] = int(saved["batch_size"])
            mark_user_blank_dims_locked(saved)
        reconcile_blank_dims_from_analysis()
        return model_volume
    except requests.Timeout as e:
        raise StepProcessingTimeout(
            f"Анализ STEP превысил {analyze_timeout} с. "
            "Упростите модель (чистовая без лишней сетки) или загрузите снова."
        ) from e
    except StepProcessingTimeout:
        raise
    except Exception:
        return 0.0


def ensure_step_analysis(file_name: str, file_bytes: bytes, project_name: str) -> float:
    """analyze-step с инвалидацией кэша при смене файла или версии алгоритма."""
    if step_analysis_cache_valid(file_bytes):
        return float(st.session_state.get("model_volume_cache") or 0)
    if try_restore_analysis_from_data_txt(project_name, file_bytes):
        st.session_state["step_analysis_digest"] = step_file_digest(file_bytes)
        st.session_state["step_analysis_version"] = step_analysis_version()
        return float(st.session_state.get("model_volume_cache") or 0)
    model_volume = run_step_analysis(file_name, file_bytes, project_name)
    st.session_state["step_analysis_digest"] = step_file_digest(file_bytes)
    st.session_state["step_analysis_version"] = step_analysis_version()
    return model_volume


def stage_glb_for_viewer(project_name: str, glb_bytes: bytes) -> None:
    """Сохранить GLB на диск, чтобы embed-viewer мог загрузить любую модель."""
    folder = st.session_state.get("user_folder")
    if not folder or not glb_bytes:
        return
    safe = safe_dir_name(project_name)
    pd = os.path.join(user_storage_root(), safe)
    os.makedirs(pd, exist_ok=True)
    with open(os.path.join(pd, f"{safe}.glb"), "wb") as f:
        f.write(glb_bytes)


def _normalize_volume(model_volume: float) -> float:
    if model_volume < 1:
        return model_volume * 1_000_000_000
    return model_volume


def load_glb_and_analysis(
    project_name: str,
    file_name: str,
    file_bytes: bytes,
    *,
    stage_glb_fn,
) -> tuple[str, float, int, bool]:
    """
    Загрузить GLB (кэш / API / конвертация) и STEP-анализ.
    Возвращает (glb_base64, model_volume, glb_size, fresh_load).
    """
    slug = project_key_slug(project_name)
    fresh_load = False

    if "glb_cache" not in st.session_state or st.session_state.get("cached_file_name") != file_name:
        fresh_load = True
        st.session_state["_step_load_in_progress"] = file_name
        try:
            try:
                resp_glb = requests.get(
                    f"{NGROK_URL}/{api_resource_prefix()}/glb/{project_name}",
                    headers=get_headers(),
                    timeout=GLB_FETCH_TIMEOUT_SEC,
                )
                if resp_glb.status_code == 200 and len(resp_glb.content) > 100:
                    stage_glb_fn(project_name, resp_glb.content)
                    glb_base64 = base64.b64encode(resp_glb.content).decode("utf-8")
                    model_volume = ensure_step_analysis(file_name, file_bytes, project_name)
                    model_volume = _normalize_volume(model_volume)
                    st.session_state["glb_cache"] = glb_base64
                    st.session_state["glb_size"] = len(resp_glb.content)
                    st.session_state["model_volume_cache"] = model_volume
                    st.session_state["cached_file_name"] = file_name
                else:
                    raise RuntimeError("GLB не найден")
            except (RuntimeError, requests.RequestException):
                files_v = {"file": (file_name, file_bytes, "application/octet-stream")}
                try:
                    resp_v = requests.post(
                        f"{NGROK_URL}/step-to-glb",
                        files=files_v,
                        headers=get_headers(),
                        timeout=STEP_GLB_TIMEOUT_SEC,
                    )
                except requests.Timeout as e:
                    raise StepProcessingTimeout(
                        f"Конвертация STEP→GLB превысила {STEP_GLB_TIMEOUT_SEC} с."
                    ) from e
                if resp_v.status_code != 200 or len(resp_v.content) <= 100:
                    detail = ""
                    try:
                        payload = resp_v.json()
                        detail = payload.get("detail", "") if isinstance(payload, dict) else ""
                    except Exception:
                        detail = (resp_v.text or "")[:300]
                    raise RuntimeError(detail or "Ошибка конвертации")
                stage_glb_fn(project_name, resp_v.content)
                glb_base64 = base64.b64encode(resp_v.content).decode("utf-8")
                model_volume = float(resp_v.headers.get("X-Model-Volume", "0"))
                model_volume = _normalize_volume(model_volume)
                st.session_state["glb_cache"] = glb_base64
                st.session_state["glb_size"] = len(resp_v.content)
                st.session_state["model_volume_cache"] = model_volume
                st.session_state["cached_file_name"] = file_name
                ensure_step_analysis(file_name, file_bytes, project_name)
        finally:
            st.session_state.pop("_step_load_in_progress", None)
    else:
        glb_base64 = st.session_state["glb_cache"]
        model_volume = st.session_state["model_volume_cache"]
        staged_key = f"_glb_staged_{slug}"
        if glb_base64 and st.session_state.get("user_folder"):
            if st.session_state.get(staged_key) != file_name:
                try:
                    stage_glb_fn(project_name, base64.b64decode(glb_base64))
                    st.session_state[staged_key] = file_name
                except Exception:
                    pass
        if file_bytes and not step_analysis_cache_valid(file_bytes):
            ensure_step_analysis(file_name, file_bytes, project_name)

    return (
        st.session_state["glb_cache"],
        float(st.session_state.get("model_volume_cache") or 0),
        int(st.session_state.get("glb_size", 0)),
        fresh_load,
    )
