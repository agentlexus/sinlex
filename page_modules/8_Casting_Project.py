"""Страница литьевого проекта: STEP, 3D-viewer, параметры литья и стоимость."""
import os
import sys
from pathlib import Path

import requests
import streamlit as st

_PAGE_DIR = Path(__file__).resolve().parent
if str(_PAGE_DIR) not in sys.path:
    sys.path.insert(0, str(_PAGE_DIR))

import payment as sinlex_payment
from casting_cost import (
    CASTING_MATERIALS,
    CASTING_TYPES,
    DEFAULT_ALLOWANCE_MM,
    DEFAULT_CASTING_MATERIAL,
    DEFAULT_CASTING_TYPE,
    DEFAULT_SHRINK_PCT,
    compute_casting_cost,
    wall_thickness_warning,
)
from casting_analysis import load_data_casting, run_casting_ai_analysis, save_data_casting
from casting_io import write_casting_artifacts
from casting_stock_glb import invalidate_stock_glbs_for_project
from page_shell import api_public_browser_url, inject_unified_main_scroll, page_title, refresh_casting_list
from project_store import load_project_data, merge_user_fields, save_project_data
from upload_limits import (
    MAX_STEP_UPLOAD_MB,
    StepProcessingTimeout,
    format_step_max_size_label,
    is_large_step_upload,
    validate_step_upload,
)
from upload_step import (
    apply_step_analysis,
    format_model_dims,
    invalidate_step_analysis_cache,
    load_glb_and_analysis,
    persist_analysis_to_data_txt,
    project_key_slug,
    reset_step_processing_session,
    restore_project_from_data,
    stage_glb_for_viewer,
    try_restore_analysis_from_data_txt,
    user_folder,
)
from utils import NGROK_URL, api_resource_prefix, get_headers, project_storage
from viewer_3d import broadcast_casting_ctx_to_viewer, render_3d_viewer, set_api_public_browser




def _render_casting_geometry_captions() -> None:
    """Компактные метрики STEP под 3D-viewer (колонка слева)."""
    geom = st.session_state.get("geometry") or {}
    step = st.session_state.get("step_analysis") or {}
    dimensions = st.session_state.get("model_dimensions") or {}

    t_min = geom.get("min_wall_thickness_mm") or step.get("min_wall_thickness_mm")
    thin = geom.get("thin_walls")
    if thin is None:
        thin = step.get("thin_walls")
    median = geom.get("wall_thickness_median_mm") or step.get("wall_thickness_median_mm")
    complexity = geom.get("complexity") or step.get("complexity")

    has_dims = any(dimensions.get(k) for k in ("x", "y", "z"))
    has_metrics = t_min is not None or thin is not None or bool(complexity)
    if not has_dims and not has_metrics:
        st.caption("Геометрия: ожидается анализ STEP")
        return

    dims_text = format_model_dims(
        dimensions,
        st.session_state.get("model_size"),
        [],
        "Литье",
    )
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.caption(f"Габариты: **{dims_text}**")
    with c2:
        if not thin and median is not None:
            st.caption(f"Типичная стенка: **{float(median):.1f} мм**")
        elif t_min is not None:
            st.caption(f"Мин. стенка: **{float(t_min):.2f} мм**")
        else:
            st.caption("Мин. стенка: **н/д**")
    with c3:
        if thin is not None:
            st.caption(f"Тонкие стенки: **{'да' if thin else 'нет'}**")
        else:
            st.caption("Тонкие стенки: **н/д**")
    with c4:
        st.caption(f"Сложность: **{complexity or '—'}**")


def _render_casting_wall_thickness_ui(
    geom: dict,
    t_min,
    *,
    casting_type: str,
    casting_material: str,
) -> None:
    """Предупреждение по мин. толщине стенки для выбранного типа литья."""
    step = st.session_state.get("step_analysis") or {}
    if t_min is None:
        t_min = geom.get("min_wall_thickness_mm") or step.get("min_wall_thickness_mm")
    warn = wall_thickness_warning(t_min, casting_type, casting_material)
    if warn:
        st.warning(warn)


def _casting_slug(project_name: str) -> str:
    return f"cast_{project_key_slug(project_name)}"


def _load_casting_params_from_data(project_name: str) -> dict:
    data = load_project_data(project_name, user_folder(), storage="casting")
    return {
        "casting_type": data.get("casting_type") or DEFAULT_CASTING_TYPE,
        "casting_material": data.get("casting_material")
        or data.get("material")
        or DEFAULT_CASTING_MATERIAL,
        "shrink_pct": float(data.get("shrink_pct") if data.get("shrink_pct") is not None else DEFAULT_SHRINK_PCT),
        "allowance_mm": float(
            data.get("allowance_mm") if data.get("allowance_mm") is not None else DEFAULT_ALLOWANCE_MM
        ),
        "batch_size": max(1, int(float(data.get("batch_size") or 1))),
    }


def _init_casting_session(project_name: str, defaults: dict) -> None:
    slug = _casting_slug(project_name)
    st.session_state.setdefault(f"{slug}_type", defaults["casting_type"])
    st.session_state.setdefault(f"{slug}_mat", defaults["casting_material"])
    st.session_state.setdefault(f"{slug}_shrink_in", float(defaults["shrink_pct"]))
    st.session_state.setdefault(f"{slug}_allow_in", float(defaults["allowance_mm"]))
    st.session_state.setdefault(f"{slug}_qty_in", int(defaults["batch_size"]))


def _persist_casting_params(project_name: str, params: dict, analysis: dict) -> None:
    existing = load_project_data(project_name, user_folder(), storage="casting")
    record = merge_user_fields(
        existing,
        material=params["casting_material"],
        casting_type=params["casting_type"],
        casting_material=params["casting_material"],
        shrink_pct=params["shrink_pct"],
        allowance_mm=params["allowance_mm"],
        batch_size=params["batch_size"],
    )
    save_project_data(project_name, record, user_folder(), storage="casting")
    write_casting_artifacts(
        project_name,
        user_folder(),
        meta={
            "casting_type": params["casting_type"],
            "casting_material": params["casting_material"],
            "shrink_pct": params["shrink_pct"],
            "allowance_mm": params["allowance_mm"],
            "batch_size": params["batch_size"],
        },
        analysis={
            "volume_mm3": analysis.get("volume_part_mm3"),
            "min_wall_thickness_mm": st.session_state.get("min_wall_thickness_mm"),
            "dimensions": st.session_state.get("model_dimensions"),
        },
        costing=analysis,
    )


def _save_to_api(
    project_name: str,
    file_name: str,
    file_bytes: bytes,
    params: dict,
    cost: dict,
    model_volume: float,
) -> bool:
    sx = cost.get("stock_dims_mm") or {}
    save_params = {
        "name": project_name,
        "material": params["casting_material"],
        "volume": model_volume,
        "workpiece_type": "Литье",
        "diam": 0,
        "length": float(sx.get("x") or 0),
        "width": float(sx.get("y") or 0),
        "height": float(sx.get("z") or 0),
        "cost_per_hour": 0,
        "cost_per_unit": int(cost.get("cost_per_unit") or cost.get("total_cost") or 0),
        "total_cost": int(cost.get("total_cost") or 0),
        "batch_size": int(params.get("batch_size") or 1),
        "machining_hours": "",
        "casting_type": params["casting_type"],
        "casting_material": params["casting_material"],
        "shrink_pct": params["shrink_pct"],
        "allowance_mm": params["allowance_mm"],
        "batch_size": int(params.get("batch_size") or 1),
    }
    try:
        resp = requests.post(
            f"{NGROK_URL}/{api_resource_prefix()}/save",
            files={"file": (file_name, file_bytes, "application/octet-stream")},
            params=save_params,
            headers=get_headers(),
            timeout=15,
        )
        if resp.status_code == 200:
            try:
                payload = resp.json()
                if isinstance(payload, dict) and payload.get("access"):
                    st.session_state["access_state"] = payload["access"]
            except Exception:
                pass
            return True
        else:
            try:
                detail = resp.json().get("detail", "")
            except Exception:
                detail = resp.text
            st.error(detail or "Не удалось сохранить проект")
    except Exception as e:
        st.error(f"Ошибка сохранения: {e}")
    return False




def _casting_ai_display_key(slug: str) -> str:
    return f"{slug}_casting_ai_display"


def _hydrate_casting_ai_display(slug: str, project_name: str) -> None:
    key = _casting_ai_display_key(slug)
    if key in st.session_state:
        return
    stored = load_data_casting(project_name, user_folder())
    st.session_state[key] = (stored.get("analysis_text") or "").strip()


def _render_casting_ai_result(text: str) -> None:
    from expert_analyzer import normalize_analysis_display

    body = normalize_analysis_display(text or "").strip()
    if not body:
        return
    # Нативный виджет (как анализ чертежа) — без unsafe_allow_html.
    st.info(body)




def _inject_casting_analysis_button_styles() -> None:
    """Бирюзовая кнопка «Запустить анализ» — как «Поток» в 3D-проектах."""
    st.markdown(
        """
<style>
div[class*="st-key-btn_casting_analyze_"] button[kind="secondary"],
div[class*="st-key-btn_casting_analyze_"] button {
    background-color: #14b8a6 !important;
    border-color: #14b8a6 !important;
    color: #ffffff !important;
}
div[class*="st-key-btn_casting_analyze_"] button:hover:not(:disabled) {
    background-color: #0d9488 !important;
    border-color: #0d9488 !important;
    color: #ffffff !important;
}
div[class*="st-key-btn_casting_analyze_"] button:focus:not(:disabled) {
    box-shadow: 0 0 0 0.2rem rgba(20, 184, 166, 0.45) !important;
}
div[class*="st-key-btn_casting_analyze_"] button:disabled {
    background-color: #99f6e4 !important;
    border-color: #99f6e4 !important;
    color: #ffffff !important;
    opacity: 0.85;
}
div[class*="st-key-btn_casting_analyze_"] button p,
div[class*="st-key-btn_casting_analyze_"] button div {
    color: #ffffff !important;
}
</style>
        """,
        unsafe_allow_html=True,
    )



@st.fragment
def _render_casting_3d_viewer_fragment(
    project_name: str,
    glb_b64: str,
    glb_size: int,
    slug: str,
) -> None:
    st.markdown("### 3D модель")
    params = _casting_params_from_session(slug)
    dimensions = st.session_state.get("model_dimensions") or {}
    casting_ctx = {
        "allowance_mm": params["allowance_mm"],
        "shrink_pct": params["shrink_pct"],
        "dimensions": dimensions,
    }
    render_3d_viewer(
        project_name,
        glb_b64,
        glb_size,
        height=520,
        mode="casting",
        casting_ctx=casting_ctx,
    )
    _render_casting_geometry_captions()


def _casting_params_from_session(slug: str) -> dict:
    casting_type = st.session_state.get(f"{slug}_type_sel", st.session_state.get(f"{slug}_type", DEFAULT_CASTING_TYPE))
    casting_material = st.session_state.get(
        f"{slug}_mat_sel", st.session_state.get(f"{slug}_mat", DEFAULT_CASTING_MATERIAL)
    )
    shrink_pct = float(st.session_state.get(f"{slug}_shrink_in", DEFAULT_SHRINK_PCT))
    allowance_mm = float(st.session_state.get(f"{slug}_allow_in", DEFAULT_ALLOWANCE_MM))
    quantity = max(1, int(st.session_state.get(f"{slug}_qty_in", 1)))
    return {
        "casting_type": casting_type,
        "casting_material": casting_material,
        "shrink_pct": shrink_pct,
        "allowance_mm": allowance_mm,
        "batch_size": quantity,
    }


@st.fragment
def _render_casting_params_fragment(
    slug: str,
    project_name: str,
    file_name: str,
    file_bytes: bytes,
    model_volume: float,
    dimensions: dict,
    geom: dict,
    t_min,
    detail_index: float,
) -> None:
    st.markdown("### Параметры литья")
    type_ix = (
        CASTING_TYPES.index(st.session_state[f"{slug}_type"])
        if st.session_state[f"{slug}_type"] in CASTING_TYPES
        else 0
    )
    mat_ix = (
        CASTING_MATERIALS.index(st.session_state[f"{slug}_mat"])
        if st.session_state[f"{slug}_mat"] in CASTING_MATERIALS
        else 0
    )
    st.selectbox(
        "Тип литья",
        CASTING_TYPES,
        index=type_ix,
        key=f"{slug}_type_sel",
    )
    st.selectbox(
        "Материал",
        CASTING_MATERIALS,
        index=mat_ix,
        key=f"{slug}_mat_sel",
    )
    shrink_pct = st.number_input(
        "Усадка, %",
        min_value=0.0,
        max_value=10.0,
        step=0.1,
        key=f"{slug}_shrink_in",
    )
    if shrink_pct < 0 or shrink_pct > 10:
        st.warning("Усадка обычно в диапазоне 0–10 %.")
    st.number_input(
        "Припуск на сторону, мм",
        min_value=0.0,
        max_value=50.0,
        step=0.5,
        key=f"{slug}_allow_in",
    )
    st.number_input(
        "Количество, шт",
        min_value=1,
        max_value=100000,
        step=1,
        key=f"{slug}_qty_in",
    )

    params = _casting_params_from_session(slug)
    cost = compute_casting_cost(
        part_volume_mm3=model_volume,
        dimensions=dimensions,
        casting_type=params["casting_type"],
        casting_material=params["casting_material"],
        shrink_pct=params["shrink_pct"],
        allowance_mm=params["allowance_mm"],
        detail_index=detail_index,
        quantity=params["batch_size"],
    )

    _render_casting_wall_thickness_ui(
        geom,
        t_min,
        casting_type=params["casting_type"],
        casting_material=params["casting_material"],
    )
    _persist_casting_params(project_name, params, cost)
    if _save_to_api(project_name, file_name, file_bytes, params, cost, model_volume):
        refresh_casting_list()

    st.session_state[f"{slug}_last_cost"] = cost
    st.session_state[f"{slug}_last_params"] = params
    broadcast_casting_ctx_to_viewer(params["allowance_mm"], params["shrink_pct"])

@st.fragment
def _casting_ai_section(
    slug: str,
    project_name: str,
    params: dict,
    cost: dict,
) -> None:
    _hydrate_casting_ai_display(slug, project_name)
    display_key = _casting_ai_display_key(slug)

    _inject_casting_analysis_button_styles()
    if st.button(
        "Запустить анализ",
        type="secondary",
        key=f"btn_casting_analyze_{slug}",
        use_container_width=True,
    ):
        live_params = st.session_state.get(f"{slug}_last_params") or params
        live_cost = st.session_state.get(f"{slug}_last_cost") or cost
        with st.spinner("Запуск анализа…"):
            analysis_text, api_used = run_casting_ai_analysis(
                project_name,
                user_folder(),
                params=live_params,
                cost=live_cost,
            )
        save_data_casting(
            project_name,
            user_folder(),
            analysis_text=analysis_text,
            api_used=api_used,
            params=params,
            cost=cost,
        )
        st.session_state[display_key] = (analysis_text or "").strip()
        st.rerun()

    ai_text = (st.session_state.get(display_key) or "").strip()
    if ai_text:
        _render_casting_ai_result(ai_text)


def render() -> None:
    set_api_public_browser(api_public_browser_url())
    inject_unified_main_scroll()
    page_title("Литье: проект")

    if st.button("← К списку литьевых проектов", type="tertiary", key="casting_back_list"):
        st.session_state.page = "casting"
        st.session_state.pop("cached_step", None)
        st.session_state.pop("cached_step_name", None)
        st.rerun()

    if st.session_state.get("selected_project"):
        proj = st.session_state.selected_project
        try:
            file_resp = requests.get(
                f"{NGROK_URL}/{api_resource_prefix()}/file/{proj['name']}",
                headers=get_headers(),
                timeout=10,
            )
            if file_resp.status_code == 200:
                st.session_state.cached_step = file_resp.content
                st.session_state.cached_step_name = f"{proj['name']}.stp"
                st.session_state.auto_process = True
                st.session_state.pop("glb_cache", None)
                invalidate_step_analysis_cache()
            else:
                st.warning(f"Файл проекта «{proj['name']}» не найден.")
        except Exception:
            st.warning("Сервер проектов недоступен")
        disk = load_project_data(proj["name"], user_folder(), storage="casting")
        restore_project_from_data(disk)
        st.session_state.selected_project = None

    uploaded = st.file_uploader(
        "Загрузить STEP-файл",
        type=["step", "stp"],
        help=format_step_max_size_label(),
        max_upload_size=MAX_STEP_UPLOAD_MB,
        key="casting_step_uploader",
    )
    if uploaded is not None:
        raw = uploaded.read()
        err = validate_step_upload(raw)
        if err:
            st.error(err)
            reset_step_processing_session(clear_upload=True)
        else:
            st.session_state.cached_step = raw
            st.session_state.cached_step_name = uploaded.name
            st.session_state.pop("glb_cache", None)
            invalidate_step_analysis_cache()

    file_bytes = st.session_state.get("cached_step")
    file_name = st.session_state.get("cached_step_name") if file_bytes else None
    if st.session_state.get("auto_process") and file_bytes:
        file_name = st.session_state.cached_step_name
        st.session_state.auto_process = False

    if not file_bytes:
        st.info("Загрузите STEP-файл или откройте проект из списка «Литье».")
        return

    err = validate_step_upload(file_bytes)
    if err:
        st.error(err)
        st.stop()

    project_name = (file_name or "project").replace(".stp", "").replace(".step", "")
    refresh_casting_list()


    defaults = _load_casting_params_from_data(project_name)
    _init_casting_session(project_name, defaults)
    slug = _casting_slug(project_name)

    slug_key = project_key_slug(project_name)
    if "glb_cache" not in st.session_state or st.session_state.get("cached_file_name") != file_name:
        try:
            status_msg = (
                f"STEP {len(file_bytes) / (1024 * 1024):.1f} МБ — анализ…"
                if is_large_step_upload(file_bytes)
                else "STEP — анализ геометрии…"
            )
            with st.status(status_msg, expanded=True) as status:
                if not try_restore_analysis_from_data_txt(project_name, file_bytes):
                    glb_b64, model_volume, glb_size, fresh = load_glb_and_analysis(
                        project_name,
                        file_name,
                        file_bytes,
                        stage_glb_fn=stage_glb_for_viewer,
                    )
                    if fresh:
                        invalidate_stock_glbs_for_project(project_name, user_folder())
                        analysis = st.session_state.get("step_analysis") or {}
                        apply_step_analysis(analysis)
                        persist_analysis_to_data_txt(project_name, analysis, file_bytes)
                else:
                    glb_b64 = st.session_state.get("glb_cache", "")
                    model_volume = float(st.session_state.get("model_volume_cache") or 0)
                    glb_size = int(st.session_state.get("glb_size") or 0)
                glb_b64 = st.session_state.get("glb_cache", "")
                model_volume = float(st.session_state.get("model_volume_cache") or 0)
                glb_size = int(st.session_state.get("glb_size") or 0)
                status.update(label="Геометрия готова", state="complete")
        except StepProcessingTimeout as e:
            reset_step_processing_session(slug=slug_key, clear_upload=True)
            st.error(str(e))
            st.stop()
        except Exception as e:
            reset_step_processing_session(slug=slug_key, clear_upload=True)
            st.error(str(e))
            st.stop()
    else:
        glb_b64 = st.session_state.get("glb_cache", "")
        model_volume = float(st.session_state.get("model_volume_cache") or 0)
        glb_size = int(st.session_state.get("glb_size") or 0)

    model_volume = float(st.session_state.get("model_volume_cache") or model_volume or 0)
    dimensions = st.session_state.get("model_dimensions") or {}
    geom = st.session_state.get("geometry") or {}
    t_min = geom.get("min_wall_thickness_mm") or st.session_state.get("step_analysis", {}).get(
        "min_wall_thickness_mm"
    )
    st.session_state["min_wall_thickness_mm"] = t_min
    detail_index = float(geom.get("detail_index") or st.session_state.get("detail_index") or 0)

    glb_size_effective = glb_size or (len(glb_b64) * 3 // 4 if glb_b64 else 0)

    view_left, view_right = st.columns([0.65, 0.35], gap="large")
    with view_left:
        _render_casting_3d_viewer_fragment(project_name, glb_b64, glb_size_effective, slug)

    with view_right:
        _render_casting_params_fragment(
            slug,
            project_name,
            file_name,
            file_bytes,
            model_volume,
            dimensions,
            geom,
            t_min,
            detail_index,
        )

    params = _casting_params_from_session(slug)
    cost = st.session_state.get(f"{slug}_last_cost") or compute_casting_cost(
        part_volume_mm3=model_volume,
        dimensions=dimensions,
        casting_type=params["casting_type"],
        casting_material=params["casting_material"],
        shrink_pct=params["shrink_pct"],
        allowance_mm=params["allowance_mm"],
        detail_index=detail_index,
        quantity=params["batch_size"],
    )

    st.markdown("---")
    _casting_ai_section(slug, project_name, params, cost)
