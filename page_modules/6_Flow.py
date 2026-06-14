"""Страница режима «Поток» — нормировка по 2D-чертежу."""
from __future__ import annotations

import datetime
import hashlib
import json
import os
from datetime import timedelta

import requests
import streamlit as st

from flow_drawing_io import FLOW_UPLOAD_TYPES, drawing_mime_type
from flow_data_store import (
    delete_flow_data,
    find_flow_data_by_hash,
    flow_data_md_path,
    load_flow_data,
    result_from_flow_data,
)
from flow_norm_hours import FLOW_NORM_PROJECT, EQUIPMENT_LABELS
from utils import NGROK_URL, get_headers

FLOW_SLUG = "flow_standalone"

_FLOW_HERO_BG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "static",
    "flow",
    "hero-bg.jpg",
)


def _flow_hero_bg_data_uri() -> str:
    try:
        with open(_FLOW_HERO_BG_PATH, "rb") as f:
            import base64

            encoded = base64.b64encode(f.read()).decode("ascii")
        return f"data:image/jpeg;base64,{encoded}"
    except OSError:
        return ""



def _hybrid_key(suffix: str) -> str:
    return f"flow_hybrid_{suffix}_{FLOW_SLUG}"


def _clear_flow_hybrid() -> None:
    for k in list(st.session_state.keys()):
        if k.startswith("flow_hybrid_") and k.endswith(f"_{FLOW_SLUG}"):
            st.session_state.pop(k, None)


def _api_detail(resp: requests.Response) -> str:
    if not resp.content:
        return str(resp.status_code)
    try:
        data = resp.json()
        if isinstance(data, dict):
            return str(data.get("detail") or data.get("message") or resp.status_code)
    except ValueError:
        pass
    return (resp.text or "")[:300] or str(resp.status_code)


def _flow_project_dir() -> str:
    folder = (st.session_state.get("user_folder") or "").strip()
    from project_store import _safe_dir_name, projects_base_dir

    base = projects_base_dir(folder)
    return os.path.join(base, _safe_dir_name(FLOW_NORM_PROJECT))


def _list_saved_flow_drawings() -> list[dict]:
    """Чертежи в папке «Поток» (PDF, PNG, JPG)."""
    proj_dir = _flow_project_dir()
    if not os.path.isdir(proj_dir):
        return []
    items: list[dict] = []
    for fname in os.listdir(proj_dir):
        low = fname.lower()
        if not (
            low.endswith(".pdf")
            or low.endswith(".png")
            or low.endswith(".jpg")
            or low.endswith(".jpeg")
        ):
            continue
        path = os.path.join(proj_dir, fname)
        if not os.path.isfile(path):
            continue
        try:
            stat = os.stat(path)
        except OSError:
            continue
        items.append(
            {
                "name": fname,
                "path": path,
                "mtime": stat.st_mtime,
                "size": stat.st_size,
            }
        )
    items.sort(key=lambda x: x["mtime"], reverse=True)
    return items


def _format_drawing_label(item: dict) -> str:
    dt = datetime.datetime.fromtimestamp(item["mtime"])
    size_kb = max(1, int(item["size"]) // 1024)
    return f"{item['name']} — {dt.strftime('%d.%m.%Y %H:%M')}, {size_kb} КБ"


def _restore_flow_result(path: str, file_hash: str) -> bool:
    """Восстановить отчёт из flow_data.md (по пути или хэшу)."""
    data = load_flow_data(path)
    if not data or not result_from_flow_data(data):
        found = find_flow_data_by_hash(_flow_project_dir(), file_hash)
        if found:
            path, data = found
        else:
            return False
    restored = result_from_flow_data(data)
    if not restored:
        return False
    st.session_state[_hybrid_key("result")] = {
        "status": "ok",
        "analysis": restored.get("report_markdown") or "",
        "norm_calc": restored.get("norm_calc") or {},
        "structured": restored.get("structured"),
        "from_saved": True,
    }
    job = data.get("job") or {}
    if job.get("master_task_id"):
        st.session_state[_hybrid_key("task_id")] = job["master_task_id"]
    st.session_state[_hybrid_key("chat_enabled")] = True
    return True


def _activate_flow_drawing(path: str, name: str, pdf_bytes: bytes | None = None) -> None:
    """Загрузить чертёж в сессию и восстановить сохранённый анализ, если есть."""
    if pdf_bytes is None:
        with open(path, "rb") as f:
            pdf_bytes = f.read()
    if not pdf_bytes:
        return
    file_hash = hashlib.sha256(pdf_bytes).hexdigest()
    st.session_state[f"flow_pdf_bytes_{FLOW_SLUG}"] = pdf_bytes
    st.session_state[f"flow_pdf_name_{FLOW_SLUG}"] = name
    st.session_state[f"flow_pdf_hash_{FLOW_SLUG}"] = file_hash
    st.session_state[f"flow_last_upload_hash_{FLOW_SLUG}"] = file_hash
    for k in (
        _hybrid_key("task_id"),
        _hybrid_key("status"),
        _hybrid_key("chat_pending"),
        _hybrid_key("chat_id"),
        _hybrid_key("chat_status"),
        _hybrid_key("error"),
        _hybrid_key("poll_error"),
    ):
        st.session_state.pop(k, None)
    st.session_state.pop(_hybrid_key("result"), None)
    st.session_state.pop(_hybrid_key("chat_enabled"), None)
    if _restore_flow_result(path, file_hash):
        st.toast("Восстановлен сохранённый анализ", icon="📂")


def _load_flow_pdf_from_path(path: str, name: str) -> None:
    _activate_flow_drawing(path, name)


def _save_flow_pdf(pdf_bytes: bytes, pdf_name: str) -> str:
    proj_dir = _flow_project_dir()
    os.makedirs(proj_dir, exist_ok=True)
    out = os.path.join(proj_dir, pdf_name or "drawing.pdf")
    with open(out, "wb") as f:
        f.write(pdf_bytes)
    return out


def _clear_flow_pdf_session() -> None:
    for key in (
        f"flow_pdf_bytes_{FLOW_SLUG}",
        f"flow_pdf_name_{FLOW_SLUG}",
        f"flow_pdf_hash_{FLOW_SLUG}",
        f"flow_last_upload_hash_{FLOW_SLUG}",
    ):
        st.session_state.pop(key, None)


def _purge_flow_norm_jobs() -> None:
    folder = (st.session_state.get("user_folder") or "").strip()
    try:
        from flow_norm_analysis import flow_norm_jobs_dir
        from flow_norm_hours import FLOW_NORM_PROJECT

        jobs_dir = flow_norm_jobs_dir(FLOW_NORM_PROJECT, folder)
        for job_path in jobs_dir.glob("*.json"):
            try:
                job_path.unlink()
            except OSError:
                pass
    except Exception:
        pass


def _delete_flow_drawing_file(pdf_name: str) -> bool:
    """Удалить PDF с диска по имени файла."""
    name = (pdf_name or "").strip()
    if not name or ".." in name or "/" in name or "\\" in name:
        return False
    path = os.path.join(_flow_project_dir(), name)
    if os.path.isfile(path):
        delete_flow_data(path)
        os.remove(path)
        return True
    return False


def _delete_active_flow_drawing() -> None:
    pdf_name = (st.session_state.get(f"flow_pdf_name_{FLOW_SLUG}") or "").strip()
    if pdf_name:
        _delete_flow_drawing_file(pdf_name)
    _clear_flow_hybrid()
    _purge_flow_norm_jobs()
    _clear_flow_pdf_session()
    st.session_state[f"flow_pdf_upl_gen_{FLOW_SLUG}"] = (
        int(st.session_state.get(f"flow_pdf_upl_gen_{FLOW_SLUG}", 0)) + 1
    )


def _delete_flow_drawing_by_path(path: str) -> None:
    if path and os.path.isfile(path):
        delete_flow_data(path)
        os.remove(path)
    active_path = ""
    pdf_name = (st.session_state.get(f"flow_pdf_name_{FLOW_SLUG}") or "").strip()
    if pdf_name:
        active_path = os.path.join(_flow_project_dir(), pdf_name)
    if active_path and os.path.normpath(active_path) == os.path.normpath(path):
        _clear_flow_hybrid()
        _purge_flow_norm_jobs()
        _clear_flow_pdf_session()
        st.session_state[f"flow_pdf_upl_gen_{FLOW_SLUG}"] = (
            int(st.session_state.get(f"flow_pdf_upl_gen_{FLOW_SLUG}", 0)) + 1
        )


def _start_flow_norm(pdf_bytes: bytes, pdf_name: str, norm: dict) -> bool:
    """Запуск задачи. Возвращает True при успехе (без st.rerun — его делает on_click)."""
    st.session_state.pop(_hybrid_key("error"), None)
    try:
        maintype, subtype = drawing_mime_type(pdf_name)
        resp = requests.post(
            f"{NGROK_URL}/flow-norm/start",
            files={"file": (pdf_name, pdf_bytes, f"{maintype}/{subtype}")},
            data={
                "norm_inputs": json.dumps(norm, ensure_ascii=False),
                "project_name": FLOW_NORM_PROJECT,
            },
            headers=get_headers(),
            timeout=60,
        )
    except requests.RequestException as exc:
        st.session_state[_hybrid_key("error")] = f"Ошибка соединения: {exc}"
        return False
    if resp.status_code == 402:
        st.session_state[_hybrid_key("error")] = (
            "Недостаточно средств на балансе «Поток». Пополните баланс."
        )
        return False
    if resp.status_code != 200:
        st.session_state[_hybrid_key("error")] = (
            f"Не удалось запустить нормировку: {_api_detail(resp)}"
        )
        return False
    data = resp.json()
    task_id = data.get("task_id")
    if not task_id:
        st.session_state[_hybrid_key("error")] = "Сервер не вернул идентификатор задачи."
        return False
    st.session_state[_hybrid_key("task_id")] = task_id
    st.session_state[_hybrid_key("status")] = data.get("status") or "pending_balance"
    st.session_state[_hybrid_key("started_at")] = datetime.datetime.now().isoformat()
    st.session_state.pop(_hybrid_key("result"), None)
    return True


def _launch_flow_norm_from_session() -> None:
    """Callback кнопки «Запустить» — читает PDF и параметры из session_state."""
    pdf_bytes = st.session_state.get(f"flow_pdf_bytes_{FLOW_SLUG}")
    pdf_name = st.session_state.get(f"flow_pdf_name_{FLOW_SLUG}") or "drawing.pdf"
    norm = st.session_state.get(f"flow_norm_inputs_{FLOW_SLUG}") or {}
    if not pdf_bytes:
        st.session_state[_hybrid_key("error")] = "Сначала загрузите чертёж (PDF, PNG или JPG)."
        return
    _clear_flow_hybrid()
    _start_flow_norm(pdf_bytes, pdf_name, norm)


def _flow_rub_debited_label(amount_rub: int) -> str:
    n = abs(int(amount_rub))
    return f"Списано {n:,} ₽. Идет анализ...".replace(",", " ")


_FLOW_PREPARING_UI = (
    "Подготовка результатов нейросетевого анализа конструкторской документации..."
)


def _fetch_flow_finalize_result(task_id: str, norm: dict) -> dict | None:
    try:
        fin = requests.post(
            f"{NGROK_URL}/flow-norm/finalize/{task_id}",
            data={
                "norm_inputs": json.dumps(norm, ensure_ascii=False),
                "project_name": FLOW_NORM_PROJECT,
            },
            headers=get_headers(),
            timeout=300,
        )
    except requests.RequestException:
        return None
    if fin.status_code == 402:
        return {
            "status": "payment_required",
            "ui_message": "Недостаточно средств на балансе «Поток». Пополните баланс.",
        }
    if fin.status_code != 200:
        return None
    result = fin.json()
    if result.get("status") in ("pending_payment", "ok", "error"):
        return result
    return None


def _send_flow_chat(question: str, task_id: str) -> bool:
    try:
        resp = requests.post(
            f"{NGROK_URL}/flow-norm/chat",
            data={
                "task_id": task_id,
                "question": question,
                "project_name": FLOW_NORM_PROJECT,
            },
            headers=get_headers(),
            timeout=60,
        )
    except requests.RequestException as exc:
        st.session_state[_hybrid_key("chat_error")] = str(exc)
        return False
    if resp.status_code != 200:
        st.session_state[_hybrid_key("chat_error")] = _api_detail(resp)
        return False
    data = resp.json()
    st.session_state[_hybrid_key("chat_id")] = data.get("chat_id")
    st.session_state[_hybrid_key("chat_status")] = "pending"
    st.session_state.pop(_hybrid_key("chat_error"), None)
    return True


def _poll_flow_chat() -> bool:
    chat_id = st.session_state.get(_hybrid_key("chat_id"))
    if not chat_id or st.session_state.get(_hybrid_key("chat_status")) != "pending":
        return False
    try:
        resp = requests.get(
            f"{NGROK_URL}/flow-norm/chat/status/{chat_id}",
            params={"project_name": FLOW_NORM_PROJECT},
            headers=get_headers(),
            timeout=120,
        )
    except requests.RequestException:
        return False
    if resp.status_code != 200:
        return False
    data = resp.json()
    if data.get("status") == "pending":
        return False
    if data.get("status") == "ok" and data.get("result"):
        st.session_state[_hybrid_key("result")] = data["result"]
        st.session_state[_hybrid_key("chat_status")] = "ok"
        st.session_state.pop(_hybrid_key("chat_id"), None)
        return True
    return False


@st.fragment(run_every=timedelta(seconds=5))
def _flow_chat_poll_fragment() -> None:
    if _poll_flow_chat():
        st.rerun()


def _poll_flow_norm(norm: dict) -> bool:
    """Опрос статуса (как hybrid в проектах): баланс → списание → ответ email → LLM."""
    cur = st.session_state.get(_hybrid_key("status"))
    if cur not in ("pending", "pending_balance", "preparing"):
        return False

    task_id = st.session_state.get(_hybrid_key("task_id"))
    if not task_id:
        st.session_state[_hybrid_key("error")] = (
            "Сессия задачи потеряна. Нажмите «Запустить нормировку» снова."
        )
        return True

    folder = (st.session_state.get("user_folder") or "").strip()
    try:
        resp = requests.get(
            f"{NGROK_URL}/flow-norm/status/{task_id}",
            params={"project_name": FLOW_NORM_PROJECT, "user_folder": folder},
            headers=get_headers(),
            timeout=30,
        )
    except requests.RequestException as exc:
        st.session_state[_hybrid_key("poll_error")] = f"Сеть: {exc}"
        return False
    st.session_state.pop(_hybrid_key("poll_error"), None)

    if resp.status_code == 404:
        st.session_state[_hybrid_key("error")] = "Задача не найдена. Запустите нормировку снова."
        return True
    if resp.status_code != 200:
        st.session_state[_hybrid_key("poll_error")] = _api_detail(resp)
        return False

    data = resp.json()
    status = data.get("status")

    if status == "pending_balance":
        if cur != "pending_balance":
            st.session_state[_hybrid_key("status")] = "pending_balance"
            return True
        return False

    if status == "pending":
        charged = data.get("flow_rub_charged") or data.get("flow_tokens_charged")
        if charged is not None:
            st.session_state[_hybrid_key("rub_charged")] = int(charged)
        if cur != "pending":
            st.session_state[_hybrid_key("status")] = "pending"
            return True
        return False

    if status == "ready":
        if cur != "preparing":
            st.session_state[_hybrid_key("status")] = "preparing"
            return True
        result = _fetch_flow_finalize_result(task_id, norm)
        if result and result.get("status") == "pending_payment":
            st.session_state[_hybrid_key("result")] = result
            st.session_state.pop(_hybrid_key("error"), None)
            return True
        if result and result.get("status") == "payment_required":
            st.session_state[_hybrid_key("error")] = (
                result.get("ui_message") or "Недостаточно средств на балансе «Поток»."
            )
            return True
        if result and result.get("status") == "ok":
            st.session_state[_hybrid_key("result")] = result
            st.session_state[_hybrid_key("chat_enabled")] = True
            st.session_state.pop(_hybrid_key("error"), None)
            return True
        if result and result.get("status") == "error":
            st.session_state[_hybrid_key("error")] = result.get("message") or "Ошибка анализа"
            return True
        st.session_state[_hybrid_key("error")] = "Не удалось сформировать отчёт. Попробуйте позже."
        return True

    if status == "error":
        st.session_state[_hybrid_key("error")] = (
            (data.get("error_ui") or "").strip()
            or "Недостаточно средств на балансе «Поток». Пополните баланс."
        )
        return True

    if status == "timeout":
        st.session_state[_hybrid_key("error")] = (
            (data.get("error_ui") or "").strip()
            or "Анализ временно недоступен, попробуйте позже"
        )
        return True

    return False


def _flow_status_label(status: str) -> str:
    if status == "preparing":
        return _FLOW_PREPARING_UI
    charged = st.session_state.get(_hybrid_key("rub_charged"))
    if charged is not None:
        return _flow_rub_debited_label(int(charged))
    return "Идет анализ..."


@st.fragment(run_every=timedelta(seconds=5))
def _flow_poll_fragment(norm: dict) -> None:
    if _poll_flow_norm(norm):
        st.rerun()


def render() -> None:
    from page_shell import inject_unified_main_scroll, page_title

    page_title("Поток")
    inject_unified_main_scroll()

    hero_bg = _flow_hero_bg_data_uri()
    hero_bg_css = (
        f'url("{hero_bg}") center/cover no-repeat'
        if hero_bg
        else "linear-gradient(135deg, #f0fdfa 0%, #e0f2fe 100%)"
    )
    st.markdown(
        f"""
<style>
.potok-hero {{
    background: #ffffff {hero_bg_css};
    border: 1.5px solid #99f6e4;
    border-radius: 16px;
    padding: 2rem 2.25rem 1.75rem;
    margin-bottom: 1.25rem;
    min-height: 7.5rem;
    overflow: hidden;
}}
.potok-hero h2 {{ font-size: 1.35rem; font-weight: 700; color: #0f766e; margin: 0 0 0.6rem 0; }}
.potok-hero p {{ font-size: 0.98rem; color: #1e293b; line-height: 1.65; margin: 0; }}
</style>
<div class="potok-hero">
  <h2>«Поток» — когда обычный анализ не справляется</h2>
  <p>
    Режим «Поток» — это мощный ИИ-анализ конструкторской документации, который подключает
    продвинутые языковые модели прямо в карточке проекта. Он заменяет стандартный анализ и
    предназначен для действительно сложных случаев: когда чертёж плохо читается, оформлен
    нестандартно или вовсе не имеет рамок. «Поток» уверенно работает со сканами низкого качества,
    нестандартными шрифтами и даже советскими форматами КД — то есть с теми документами, на которых
    обычный режим может споткнуться.
  </p>
</div>
        """,
        unsafe_allow_html=True,
    )

    if st.session_state.get("guest_mode") or not st.session_state.get("user_email"):
        st.warning("Войдите в аккаунт для анализа чертежа.")
        return

    st.subheader("Чертёж")
    saved_drawings = _list_saved_flow_drawings()
    if saved_drawings:
        labels = [_format_drawing_label(item) for item in saved_drawings]
        path_by_label = {labels[i]: saved_drawings[i]["path"] for i in range(len(labels))}
        st.session_state[f"flow_saved_labels_{FLOW_SLUG}"] = labels
        st.session_state[f"flow_saved_paths_{FLOW_SLUG}"] = path_by_label

        current_name = (st.session_state.get(f"flow_pdf_name_{FLOW_SLUG}") or "").strip()
        default_idx = 0
        if current_name:
            for i, item in enumerate(saved_drawings):
                if item["name"] == current_name:
                    default_idx = i
                    break

        with st.form("flow_pick_saved_drawing", clear_on_submit=False):
            st.caption("В папке уже есть загруженные чертежи — выберите из списка или загрузите новый.")
            picked_label = st.selectbox(
                "Чертёж из загруженных",
                options=labels,
                index=default_idx,
                key=f"flow_saved_sel_{FLOW_SLUG}",
            )
            pick_col, del_col = st.columns(2)
            with pick_col:
                submitted_pick = st.form_submit_button("Открыть выбранный", use_container_width=True)
            with del_col:
                submitted_del = st.form_submit_button(
                    "Удалить выбранный",
                    use_container_width=True,
                )
            if submitted_pick:
                path = path_by_label.get(picked_label, "")
                if path and os.path.isfile(path):
                    _load_flow_pdf_from_path(path, os.path.basename(path))
                    st.toast(f"Выбран: {os.path.basename(path)}", icon="📄")
                    st.rerun()
                else:
                    st.error("Не удалось открыть файл.")
            if submitted_del:
                path = path_by_label.get(picked_label, "")
                if path and os.path.isfile(path):
                    _delete_flow_drawing_by_path(path)
                    st.toast(f"Удалён: {os.path.basename(path)}", icon="🗑️")
                    st.rerun()
                else:
                    st.error("Не удалось удалить файл.")

        st.divider()

    upl_gen = int(st.session_state.get(f"flow_pdf_upl_gen_{FLOW_SLUG}", 0))
    pdf_file = st.file_uploader(
        "Загрузить новый чертёж (PDF, PNG, JPG)",
        type=FLOW_UPLOAD_TYPES,
        key=f"flow_pdf_{FLOW_SLUG}_{upl_gen}",
    )
    if pdf_file is not None:
        pdf_bytes = pdf_file.getvalue() or pdf_file.read()
        if pdf_bytes:
            pdf_name = pdf_file.name or "drawing.pdf"
            new_hash = hashlib.sha256(pdf_bytes).hexdigest()
            last_hash = st.session_state.get(f"flow_last_upload_hash_{FLOW_SLUG}") or ""
            prev_name = (st.session_state.get(f"flow_pdf_name_{FLOW_SLUG}") or "").strip()
            if new_hash != last_hash or pdf_name != prev_name:
                saved_path = _save_flow_pdf(pdf_bytes, pdf_name)
                _activate_flow_drawing(saved_path, pdf_name, pdf_bytes)
                st.session_state[f"flow_pdf_upl_gen_{FLOW_SLUG}"] = upl_gen + 1
                st.toast(f"Чертёж загружен: {pdf_name}", icon="✅")
                st.rerun()

    pdf_bytes = st.session_state.get(f"flow_pdf_bytes_{FLOW_SLUG}")
    pdf_name = st.session_state.get(f"flow_pdf_name_{FLOW_SLUG}") or "drawing.pdf"
    if not pdf_bytes:
        if saved_drawings:
            st.caption("Выберите чертёж из списка или загрузите новый файл.")
        else:
            st.caption("Загрузите чертёж, укажите параметры и запустите нормировку.")
        return

    act_col, del_col = st.columns([4, 1])
    with act_col:
        st.caption(f"Активный чертёж: **{pdf_name}**")
    with del_col:
        if st.button("🗑️ Удалить", key="flow_del_active_pdf", use_container_width=True):
            _delete_active_flow_drawing()
            st.toast("Чертёж удалён", icon="🗑️")
            st.rerun()

    st.subheader("Параметры нормировки")
    c1, c2 = st.columns(2)
    with c1:
        material = st.text_input("Материал заготовки", key=f"flow_mat_{FLOW_SLUG}", placeholder="12Х18Н10Т")
        equipment = st.selectbox(
            "Оборудование",
            options=list(EQUIPMENT_LABELS.keys()),
            format_func=lambda k: EQUIPMENT_LABELS[k],
            key=f"flow_eq_{FLOW_SLUG}",
        )
        batch = st.number_input("Партия, шт", min_value=1, value=1, step=1, key=f"flow_batch_{FLOW_SLUG}")
    with c2:
        blank_desc = st.text_area(
            "Заготовка (тип, припуск)",
            key=f"flow_blank_desc_{FLOW_SLUG}",
            height=68,
            placeholder="Пруток Ø52, L120…",
        )
        d_blank = st.number_input("Ø заготовки, мм (0 — оценить с чертежа)", min_value=0.0, value=0.0, key=f"flow_d_{FLOW_SLUG}")
        l_blank = st.number_input("Длина заготовки, мм (0 — оценить)", min_value=0.0, value=0.0, key=f"flow_l_{FLOW_SLUG}")

    norm_inputs = {
        "material": (material or "").strip(),
        "equipment_type": equipment,
        "batch_size": int(batch),
        "blank_description": (blank_desc or "").strip(),
        "blank_diameter_mm": float(d_blank) if d_blank and d_blank > 0 else None,
        "blank_length_mm": float(l_blank) if l_blank and l_blank > 0 else None,
    }
    st.session_state[f"flow_norm_inputs_{FLOW_SLUG}"] = norm_inputs

    status = st.session_state.get(_hybrid_key("status"))
    result = st.session_state.get(_hybrid_key("result"))
    err = st.session_state.get(_hybrid_key("error"))
    poll_err = st.session_state.get(_hybrid_key("poll_error"))

    if result:
        if result.get("status") == "pending_payment":
            st.warning(result.get("ui_message") or "Пополните баланс для просмотра результата.")
        elif result.get("status") == "ok":
            if result.get("from_saved"):
                st.info("Показан сохранённый результат анализа. Чтобы пересчитать — нажмите «Новый анализ».")
            calc = result.get("norm_calc") or {}
            if calc:
                st.success("Экспресс-нормировка (ориентир)")
                m1, m2, m3, m4 = st.columns(4)
                m1.metric("Tо, мин", calc.get("machine_time_min", "—"))
                m2.metric("Tшт, мин", calc.get("total_piece_min", "—"))
                m3.metric("На партию, мин", calc.get("total_batch_min", "—"))
                m4.metric("Kвсп", calc.get("k_vsp", "—"))
                with st.expander("Детали расчёта"):
                    st.json(calc)
            st.markdown("### Отчёт по нормировке")
            st.markdown(result.get("analysis") or "")

            st.session_state[_hybrid_key("chat_enabled")] = True
            task_id = st.session_state.get(_hybrid_key("task_id"))
            chat_status = st.session_state.get(_hybrid_key("chat_status"))
            chat_err = st.session_state.get(_hybrid_key("chat_error"))

            st.markdown("### Уточнения по чертежу")
            st.caption(
                "Задайте вопрос по детали — система уточнит отчёт с учётом чертежа и контекста."
            )
            if chat_status == "pending":
                with st.status("Обрабатываем ваш вопрос…", state="running"):
                    st.caption("Ответ формируется, подождите.")
                _flow_chat_poll_fragment()
            else:
                with st.form("flow_chat_form", clear_on_submit=True):
                    st.text_area(
                        "Ваш вопрос",
                        key=f"flow_chat_q_{FLOW_SLUG}",
                        height=80,
                        placeholder="Например: уточните время на расточку отверстия Ø40 H7",
                    )
                    send_chat = st.form_submit_button("Отправить", use_container_width=True)
                if send_chat:
                    q = (st.session_state.get(f"flow_chat_q_{FLOW_SLUG}") or "").strip()
                    if not q:
                        st.warning("Введите вопрос.")
                    elif not task_id:
                        st.warning("Запустите анализ заново, чтобы задать вопрос.")
                    elif _send_flow_chat(q, task_id):
                        st.session_state.pop(f"flow_chat_q_{FLOW_SLUG}", None)
                        st.rerun()
                if chat_err:
                    st.error(chat_err)

        if st.button("Новый анализ", key="flow_new_analysis"):
            _clear_flow_hybrid()
            _clear_flow_pdf_session()
            st.session_state[f"flow_pdf_upl_gen_{FLOW_SLUG}"] = upl_gen + 1
            st.rerun()
        return

    if err:
        st.error(err)
        if st.button("Повторить", key="flow_retry_err"):
            _clear_flow_hybrid()
            st.rerun()
        return

    if status in ("pending", "pending_balance", "preparing"):
        with st.status(_flow_status_label(status), state="running", expanded=True):
            st.caption("Обновление каждые несколько секунд. Не закрывайте страницу.")
            if poll_err:
                st.warning(poll_err)
        _flow_poll_fragment(norm_inputs)
        if st.button("Отменить", key="flow_cancel_run"):
            _clear_flow_hybrid()
            st.rerun()
        return

    st.button(
        "Запустить нормировку по чертежу",
        type="primary",
        key="flow_run_norm",
        on_click=_launch_flow_norm_from_session,
        use_container_width=True,
    )
    st.caption("После запуска статус анализа обновится автоматически.")
