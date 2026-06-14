import os

import streamlit as st

NGROK_URL = os.environ.get("SINLEX_API_URL", "http://127.0.0.1:8001")
API_KEY = os.environ.get("SINLEX_API_KEY", "")

material_prices = {
    "Сталь 3": 65, "Сталь 20": 75, "Сталь 45": 80, "Сталь 40Х": 95,
    "09Г2С": 90, "Нерж. AISI 304": 350, "Нерж. AISI 316": 480,
    "Алюминий Д16Т": 700, "Алюминий АМг6": 750, "Титан ВТ6": 3500,
    "Латунь ЛС59": 520, "Медь М1": 850, "Чугун СЧ20": 70,
}

chip_prices = {
    "Сталь 3": 15, "Сталь 20": 15, "Сталь 45": 15,
    "Сталь 40Х": 15, "09Г2С": 15, "Чугун СЧ20": 12,
    "Нерж. AISI 304": 30, "Нерж. AISI 316": 35,
    "Алюминий Д16Т": 95, "Алюминий АМг6": 95,
    "Титан ВТ6": 150, "Латунь ЛС59": 450, "Медь М1": 720,
}


def transliterate(text):
    mapping = {
        'а':'a','б':'b','в':'v','г':'g','д':'d','е':'e','ё':'yo','ж':'zh','з':'z','и':'i','й':'y',
        'к':'k','л':'l','м':'m','н':'n','о':'o','п':'p','р':'r','с':'s','т':'t','у':'u','ф':'f',
        'х':'h','ц':'ts','ч':'ch','ш':'sh','щ':'sch','ъ':'','ы':'y','ь':'','э':'e','ю':'yu','я':'ya'
    }
    return ''.join(mapping.get(c.lower(), c) for c in text)


def get_headers():
    h = {"X-API-Key": API_KEY}
    if st.session_state.get("user_email") and not st.session_state.get("guest_mode"):
        h["X-User-Email"] = st.session_state.user_email
    return h


def is_casting_mode() -> bool:
    return st.session_state.get("project_domain") == "casting"


def api_resource_prefix() -> str:
    return "casting" if is_casting_mode() else "projects"


def user_storage_root() -> str:
    folder = _user_folder()
    base = "/opt/sinlex/casting" if is_casting_mode() else "/opt/sinlex/projects"
    return os.path.join(base, folder) if folder else base


def project_storage() -> str:
    return "casting" if is_casting_mode() else "projects"


def format_volume(mm3):
    if mm3 < 1000: return f"{round(mm3)} мм³"
    elif mm3 < 1_000_000: return f"{round(mm3/1000)} см³"
    else: return f"{round(mm3/1_000_000,2)} м³"


_WP_ROD = "Пруток"


def _normalize_wp_type(wp: str) -> str:
    """Старые проекты могли сохранять «Вал»."""
    return _WP_ROD if wp in ("Вал", "вал") else wp


def _apply_allowance(dims, workpiece=None, operations=None):
    """Припуск к заготовке: пруток или плита по геометрии STEP."""
    from machining_cost import blank_dims_with_allowance

    wp_type = _normalize_wp_type((workpiece or {}).get("type") or st.session_state.get("wp", _WP_ROD))
    blank = blank_dims_with_allowance(
        wp_type,
        workpiece=workpiece,
        model_size=st.session_state.get("model_size"),
        dimensions=dims,
        operations=operations,
    )
    if blank["workpiece_type"] == "Плита":
        st.session_state["wid"] = int(blank["width"])
        st.session_state["len"] = int(blank["length"])
        st.session_state["hei"] = int(blank["height"])
        st.session_state["wp"] = "Плита"
    else:
        st.session_state["diam"] = int(blank["diameter"])
        st.session_state["len"] = int(blank["length"])
        st.session_state["wp"] = _WP_ROD


def _user_folder() -> str:
    return st.session_state.get("user_folder", "") or ""


def load_project_params(project_name: str) -> dict:
    """Параметры заготовки из data.txt (полный файл — load_project_data)."""
    from project_store import load_project_data, user_params_slice

    data = load_project_data(project_name, _user_folder(), storage=project_storage())
    params = user_params_slice(data)
    if params.get("workpiece_type"):
        params["workpiece_type"] = _normalize_wp_type(params["workpiece_type"])
    return params


def save_project_data(pn, mat, vol, dims, geom, wp, d, l, w, h, cph, bs):
    """Обновить data.txt: сохранить заготовку + текущий анализ из session_state."""
    from project_store import load_project_data, merge_user_fields, save_project_data as _save

    existing = load_project_data(pn, _user_folder(), storage=project_storage())
    record = merge_user_fields(
        existing,
        material=mat,
        workpiece_type=wp,
        diam=d,
        length=l,
        width=w,
        height=h,
        cost_per_hour=cph,
        batch_size=bs,
        volume=vol,
    )
    if geom:
        record["geometry"] = geom
    if dims:
        record["dimensions"] = dims
    if st.session_state.get("operations"):
        record["operations"] = st.session_state["operations"]
    if st.session_state.get("op_type"):
        record["operation_type"] = st.session_state["op_type"]
    if st.session_state.get("model_size"):
        record["model_size"] = st.session_state["model_size"]
    geom = st.session_state.get("geometry") or {}
    if geom.get("part_family"):
        record["part_family"] = geom["part_family"]
    elif st.session_state.get("step_analysis", {}).get("part_family"):
        record["part_family"] = st.session_state["step_analysis"]["part_family"]
    if st.session_state.get("step_analysis"):
        record["step_analysis"] = st.session_state["step_analysis"]
    if st.session_state.get("step_analysis_version"):
        record["step_analysis_version"] = st.session_state.get("step_analysis_version")
    if st.session_state.get("step_analysis_digest"):
        record["step_file_digest"] = st.session_state.get("step_analysis_digest")
    if st.session_state.get("cam_rate") is not None:
        record["cam_rate"] = int(st.session_state["cam_rate"])
    user_folder = _user_folder()
    _save(pn, record, user_folder)
    from project_store import projects_base_dir
    from project_dates import sync_project_registry

    sync_project_registry(
        projects_base_dir(user_folder),
        pn,
        {
            "material": mat,
            "volume": vol,
            "workpiece_type": wp,
            "diam": d,
            "length": l,
            "width": w,
            "height": h,
            "cost_per_hour": cph,
        },
    )

def format_project_date_label(value, *, view_date=None):
    from project_dates import format_project_date_label as _fmt
    return _fmt(value, view_date=view_date)

