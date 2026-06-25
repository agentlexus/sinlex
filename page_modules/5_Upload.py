"""Загрузка STEP, расчёт стоимости, 3D-viewer, экспертный анализ PDF."""
import os
import sys
from pathlib import Path

import requests
import streamlit as st

# Соседние модули (page загружается через importlib, не как пакет)
_PAGE_DIR = Path(__file__).resolve().parent
if str(_PAGE_DIR) not in sys.path:
    sys.path.insert(0, str(_PAGE_DIR))

import importlib

import payment as sinlex_payment
from costing_ui import render_costing_section, render_geometry_captions, render_parameters_panel

import pdf_analysis as _pdf_analysis

_pdf_analysis = importlib.reload(_pdf_analysis)

from pdf_analysis import (
    build_costing_quote_for_tech_card,
    enrich_costing_quote_with_drawing_criteria,
    enrich_costing_quote_with_geometry,
    clear_legacy_expert_session,
    deep_analysis_key,
    last_saved_analysis_key,
    pdf_project_name_from_session,
    pdf_upload_fragment,
    render_project_drawing_order_panel,
    render_tech_card_section,
    resolve_pdf_paths,
)

# CR-3: при hot-reload Streamlit подхватывает актуальный pdf_analysis
drawing_criteria_key = _pdf_analysis.drawing_criteria_key
clear_drawing_criteria_session = getattr(
    _pdf_analysis,
    "clear_drawing_criteria_session",
    lambda slug: (
        st.session_state.pop(f"drawing_criteria_{slug}", None),
        st.session_state.pop(f"costing_recalc_stamp_{slug}", None),
    ),
)
resolve_drawing_criteria_for_costing = getattr(
    _pdf_analysis,
    "resolve_drawing_criteria_for_costing",
    lambda slug, project_name, user_folder_val="": None,
)
from upload_limits import (
    MAX_STEP_UPLOAD_MB,
    StepProcessingTimeout,
    format_step_max_size_label,
    is_large_step_upload,
    validate_step_upload,
)
from upload_step import (
    WP_ROD,
    invalidate_step_analysis_cache,
    is_rod_wp,
    load_glb_and_analysis,
    normalize_wp_type,
    project_key_slug,
    reconcile_blank_dims_from_analysis,
    reset_step_processing_session,
    restore_project_from_data,
    stage_glb_for_viewer,
    user_folder,
)
from utils import NGROK_URL, api_resource_prefix, get_headers, is_casting_mode, load_project_params, user_storage_root
from viewer_3d import render_3d_viewer, set_api_public_browser


def render() -> None:
    import sys as _sys

    from page_shell import (
        api_public_browser_url,
        inject_unified_main_scroll,
        page_title,
        refresh_casting_list,
        refresh_projects_list,
    )

    set_api_public_browser(api_public_browser_url())
    inject_unified_main_scroll()
    page_title("Литье: загрузка модели" if is_casting_mode() else "📁 Загрузить деталь")
    dm, dw, dd, dl, dwi, dh, dc = "Сталь 45", WP_ROD, 85, 320, 100, 50, 3500

    if st.session_state.selected_project:
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
                dm = proj.get("material", dm)
                dw = normalize_wp_type(proj.get("workpiece_type", dw))
                dd = int(proj.get("diam", dd))
                dl = int(proj.get("length", dl))
                dwi = int(proj.get("width", dwi))
                dh = int(proj.get("height", dh))
                dc = int(proj.get("cost_per_hour", dc))
                st.session_state.auto_process = True
                st.session_state.pop("glb_cache", None)
                st.session_state.pop("cached_file_name", None)
                invalidate_step_analysis_cache()
            else:
                st.warning(f"⚠️ Файл проекта '{proj['name']}' не найден на сервере.")
        except Exception:
            st.warning("⚠️ Сервер проектов недоступен")

        from project_store import load_project_data

        disk = load_project_data(proj["name"], user_folder())
        restore_project_from_data(disk)
        saved = load_project_params(proj["name"])
        if saved:
            if saved.get("material"):
                dm = saved["material"]
            if saved.get("workpiece_type"):
                dw = normalize_wp_type(saved["workpiece_type"])
            if saved.get("diam"):
                dd = int(saved["diam"])
            if saved.get("length"):
                dl = int(saved["length"])
            if saved.get("width"):
                dwi = int(saved["width"])
            if saved.get("height"):
                dh = int(saved["height"])
            if saved.get("cost_per_hour"):
                dc = int(saved["cost_per_hour"])
            if saved.get("cam_rate") is not None:
                st.session_state["cam_rate"] = int(saved["cam_rate"])
            if saved.get("batch_size"):
                st.session_state["saved_batch_size"] = int(saved["batch_size"])
        reconcile_blank_dims_from_analysis()
        clear_legacy_expert_session()
        st.session_state["_active_expert_slug"] = project_key_slug(proj["name"])
        st.session_state.selected_project = None

    elif "current_project" in st.session_state:
        from project_store import load_project_data

        disk = load_project_data(st.session_state["current_project"], user_folder())
        restore_project_from_data(disk)
        saved = load_project_params(st.session_state["current_project"])
        if saved:
            if saved.get("material"):
                dm = saved["material"]
            if saved.get("workpiece_type"):
                dw = normalize_wp_type(saved["workpiece_type"])
            if saved.get("diam"):
                dd = int(saved["diam"])
            if saved.get("length"):
                dl = int(saved["length"])
            if saved.get("width"):
                dwi = int(saved["width"])
            if saved.get("height"):
                dh = int(saved["height"])
            if saved.get("cost_per_hour"):
                dc = int(saved["cost_per_hour"])
            if saved.get("cam_rate") is not None:
                st.session_state["cam_rate"] = int(saved["cam_rate"])
            if saved.get("batch_size"):
                st.session_state["saved_batch_size"] = int(saved["batch_size"])
        reconcile_blank_dims_from_analysis()

    if "show_kp_download" in st.session_state:
        del st.session_state["show_kp_download"]

    st.session_state["mat"] = dm
    st.session_state["wp"] = dw
    st.session_state["diam"] = dd
    st.session_state["len"] = dl
    st.session_state["wid"] = dwi
    st.session_state["hei"] = dh
    st.session_state["cost_h"] = dc

    upload_step_col, upload_pdf_col = st.columns(2, gap="medium", vertical_alignment="top")
    with upload_step_col:
        uploaded_file = st.file_uploader(
            "📁 Загрузить STEP-файл (чистовая модель)",
            type=["step", "stp"],
            help=format_step_max_size_label(),
            max_upload_size=MAX_STEP_UPLOAD_MB,
        )
        if uploaded_file is not None:
            raw = uploaded_file.read()
            size_err = validate_step_upload(raw)
            if size_err:
                st.error(size_err)
                reset_step_processing_session(clear_upload=True)
            else:
                st.session_state.cached_step = raw
                st.session_state.cached_step_name = uploaded_file.name
                st.session_state.pop("glb_cache", None)
                st.session_state.pop("cached_file_name", None)
                st.session_state.pop("user_blank_dims_locked", None)
                invalidate_step_analysis_cache()
                st.session_state.pop("model_size", None)
                clear_legacy_expert_session()
                if st.session_state.get("cached_step_name"):
                    pn = (
                        st.session_state.cached_step_name.replace(".stp", "").replace(".step", "")
                    )
                    slug_pn = project_key_slug(pn)
                    st.session_state.pop(deep_analysis_key(slug_pn), None)
                    st.session_state.pop(last_saved_analysis_key(slug_pn), None)
                    clear_drawing_criteria_session(slug_pn)

    with upload_pdf_col:
        pdf_project = pdf_project_name_from_session()
        if pdf_project:
            pdf_upload_fragment(pdf_project, project_key_slug(pdf_project))
        else:
            st.file_uploader(
                "📄 Загрузить чертеж",
                type=["pdf"],
                disabled=True,
                key="pdf_drawing_placeholder",
            )

    file_bytes = st.session_state.cached_step if st.session_state.get("cached_step") else None
    file_name = st.session_state.cached_step_name if file_bytes else None

    if st.session_state.get("auto_process") and st.session_state.get("cached_step"):
        file_bytes = st.session_state.cached_step
        file_name = st.session_state.cached_step_name
        st.session_state.auto_process = False

    if not file_bytes:
        return

    size_err = validate_step_upload(file_bytes)
    if size_err:
        st.error(size_err)
        reset_step_processing_session(clear_upload=True)
        st.stop()

    project_name = file_name.replace(".stp", "").replace(".step", "")
    (refresh_casting_list if is_casting_mode() else refresh_projects_list)()


    st.session_state["current_project"] = project_name
    slug = project_key_slug(project_name)
    if st.session_state.get("_active_expert_slug") != slug:
        st.session_state["_active_expert_slug"] = slug
        clear_legacy_expert_session()

    folder = st.session_state.get("user_folder", "")
    base_dir = user_storage_root()
    project_dir_for_log, _saved_pdf = resolve_pdf_paths(base_dir, project_name)
    os.makedirs(project_dir_for_log, exist_ok=True)

    if "show_kp_download" in st.session_state:
        del st.session_state["show_kp_download"]

    try:
        status_msg = (
            f"STEP {len(file_bytes) / (1024 * 1024):.1f} МБ — анализ "
            f"(до 10 мин на тяжёлых моделях)…"
            if is_large_step_upload(file_bytes)
            else "STEP — анализ геометрии…"
        )
        with st.status(status_msg, expanded=True) as status:
            glb_base64, model_volume, glb_size, fresh_load = load_glb_and_analysis(
                project_name,
                file_name,
                file_bytes,
                stage_glb_fn=stage_glb_for_viewer,
            )
            status.update(label="STEP обработан", state="complete")
        if fresh_load:
            st.success(f"Файл '{file_name}' загружен")
    except StepProcessingTimeout as e:
        reset_step_processing_session(slug=slug, clear_upload=True)
        st.error(str(e))
        st.info("Сессия сброшена. Загрузите файл снова или упростите модель.")
        st.stop()
    except RuntimeError as e:
        reset_step_processing_session(slug=slug, clear_upload=True)
        st.error(str(e))
        st.stop()
    except requests.Timeout as e:
        reset_step_processing_session(slug=slug, clear_upload=True)
        st.error(f"Превышено время ожидания сервера: {e}")
        st.info("Сессия сброшена. Попробуйте загрузить файл снова.")
        st.stop()
    except Exception as e:
        reset_step_processing_session(slug=slug, clear_upload=True)
        st.error(f"Ошибка соединения: {e}")
        st.stop()

    geometry = st.session_state.get("geometry", {})
    dimensions = st.session_state.get("model_dimensions", {})
    operations = st.session_state.get("operations") or []
    if not operations:
        ot = st.session_state.get("op_type", "Фрезерная")
        operations = [p.strip() for p in str(ot).split(",") if p.strip()] or ["Фрезерная"]

    st.markdown("---")
    view_left, view_right = st.columns([0.5, 0.5], gap="large")

    with view_left:
        st.markdown("### 🖥️ 3D Модель")
        render_3d_viewer(
            project_name,
            glb_base64,
            glb_size or (len(glb_base64) * 3 // 4 if glb_base64 else 0),
        )

    with view_right:
        params = render_parameters_panel(
            project_name=project_name,
            model_volume=model_volume,
            dimensions=dimensions,
            geometry=geometry,
            operations=operations,
        )

    render_geometry_captions(geometry, dimensions, operations, params["wp"])

    st.markdown("---")
    render_project_drawing_order_panel(
        project_name,
        slug,
        model_volume,
        dimensions,
        geometry,
        quote=None,
    )

    st.markdown("---")
    drawing_criteria = resolve_drawing_criteria_for_costing(
        slug, project_name, user_folder()
    )
    cost = render_costing_section(
        geometry=geometry,
        dimensions=dimensions,
        operations=operations,
        model_volume=model_volume,
        params=params,
        drawing_criteria=drawing_criteria,
    )
    st.session_state[f"_cost_snapshot_{slug}"] = cost

    costing_quote = enrich_costing_quote_with_geometry(
        enrich_costing_quote_with_drawing_criteria(
            build_costing_quote_for_tech_card(
                batch_size=cost["batch_size"],
                mhpu=cost["mhpu"],
                mht=cost["mht"],
                cutting_per_part_h=cost["cutting_per_part_h"],
                setup_per_part_h=cost["setup_per_part_h"],
                cam_per_part_h=cost["cam_per_part_h"],
                cpu=cost["cpu"],
                tc=cost["tc"],
                material=cost["sm"],
                workpiece_type=cost["wp"],
                cost_per_hour=cost["cph"],
                geometry=geometry,
            ),
            drawing_criteria=drawing_criteria,
            criteria_breakdown=cost.get("criteria_breakdown"),
        ),
        geometry,
    )

    st.markdown("---")
    render_tech_card_section(
        project_name,
        slug,
        model_volume,
        dimensions,
        geometry,
        costing_quote,
    )

    st.markdown("---")
    col_btn1, _ = st.columns([1, 3])
    with col_btn1:
        if st.button("📄 Скачать КП (PDF)", use_container_width=True, type="primary"):
            st.success("В разработке")

    sm = cost["sm"]
    wp = cost["wp"]
    d1, l1, w1, h1 = cost["d1"], cost["l1"], cost["w1"], cost["h1"]
    cph = cost["cph"]
    cpu, tc, mhpu = cost["cpu"], cost["tc"], cost["mhpu"]

    saved_ok = True
    try:
        files_save = {"file": (file_name, file_bytes, "application/octet-stream")}
        save_params = {
            "name": project_name,
            "material": sm,
            "volume": model_volume,
            "workpiece_type": wp,
            "diam": d1 if is_rod_wp(wp) else 0,
            "length": l1,
            "width": w1 if not is_rod_wp(wp) else 0,
            "height": h1 if not is_rod_wp(wp) else 0,
            "cost_per_hour": cph,
            "cost_per_unit": int(cpu),
            "total_cost": int(tc),
            "machining_hours": f"{round(mhpu)} ч",
        }
        resp_save = requests.post(
            f"{NGROK_URL}/{api_resource_prefix()}/save",
            files=files_save,
            params=save_params,
            headers=get_headers(),
            timeout=15,
        )
        if resp_save.status_code == 200:
            try:
                payload = resp_save.json()
                if isinstance(payload, dict) and payload.get("access"):
                    st.session_state["access_state"] = payload["access"]
            except Exception:
                pass
        else:
            saved_ok = False
            detail = ""
            try:
                payload = resp_save.json()
                detail = payload.get("detail", "") if isinstance(payload, dict) else str(payload)
            except Exception:
                detail = resp_save.text
            else:
                st.error(detail or "Не удалось сохранить проект")
    except Exception:
        saved_ok = False

    if saved_ok:
        from page_shell import refresh_casting_list, refresh_projects_list
        (refresh_casting_list if is_casting_mode() else refresh_projects_list)()
