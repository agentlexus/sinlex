"""Загрузка PDF-чертежа, проверка грифов, экспертный анализ и техкарта."""
import datetime
import hashlib
import json
import math
import os
import re
import shutil
import urllib.parse
from datetime import timedelta

import requests
import streamlit as st

from upload_step import project_key_slug, safe_dir_name, user_folder
from utils import API_KEY, NGROK_URL, get_headers

try:
    from expert_analyzer import LLM_UI_ERROR_MESSAGE
except ImportError:
    LLM_UI_ERROR_MESSAGE = "Сервер анализа временно недоступен"

HYBRID_SUFFLER_TIMEOUT_MESSAGE = "Анализ временно недоступен, попробуйте позже"

POTOK_HELP_TOOLTIP = (
    "Поток — это углублённый ИИ-анализ сложных и трудночитаемых чертежей. "
    "Восстанавливает геометрию, распознаёт размеры, допуски и формирует нормировку. "
    "Оплачивается с баланса «Поток»: стоимость зависит от сложности чертежа. "
    "Списание в рублях."
)


def deep_analysis_key(slug: str) -> str:
    return f"deep_analysis_{slug}"


def drawing_extraction_key(slug: str) -> str:
    return f"drawing_extraction_{slug}"


def drawing_criteria_key(slug: str) -> str:
    return f"drawing_criteria_{slug}"


def pdf_scan_hash_key(slug: str) -> str:
    return f"pdf_scan_hash_{slug}"


def costing_recalc_stamp_key(slug: str) -> str:
    return f"costing_recalc_stamp_{slug}"


def hybrid_task_id_key(slug: str) -> str:
    return f"hybrid_task_id_{slug}"


def hybrid_status_key(slug: str) -> str:
    return f"hybrid_status_{slug}"


def hybrid_started_at_key(slug: str) -> str:
    return f"hybrid_started_at_{slug}"


def hybrid_result_key(slug: str) -> str:
    return f"hybrid_result_{slug}"


def hybrid_persist_done_key(slug: str) -> str:
    return f"hybrid_persist_done_{slug}"


def hybrid_error_ui_key(slug: str) -> str:
    return f"hybrid_error_ui_{slug}"


def _hybrid_poll_interval_sec() -> int:
    raw = os.environ.get("SUFFLER_POLL_INTERVAL_SEC", "15").strip()
    try:
        return max(5, int(raw))
    except ValueError:
        return 15


def hybrid_suffler_ui_enabled() -> bool:
    try:
        from max_suffler import hybrid_suffler_enabled

        return hybrid_suffler_enabled()
    except Exception:
        return False


def clear_hybrid_session(slug: str) -> None:
    st.session_state.pop(hybrid_task_id_key(slug), None)
    st.session_state.pop(hybrid_started_at_key(slug), None)
    st.session_state.pop(hybrid_result_key(slug), None)
    st.session_state.pop(hybrid_persist_done_key(slug), None)
    st.session_state.pop(hybrid_error_ui_key(slug), None)
    st.session_state.pop(hybrid_pending_meta_key(slug), None)
    st.session_state.pop(f"hybrid_rub_charged_{slug}", None)
    st.session_state.pop(f"hybrid_tokens_charged_{slug}", None)
    st.session_state[hybrid_status_key(slug)] = "idle"


def _purge_hybrid_for_project(
    project_name: str,
    user_folder: str,
    *,
    pdf_hash: str = "",
) -> None:
    if not (project_name or "").strip():
        return
    from hybrid_analysis import purge_hybrid_jobs

    purge_hybrid_jobs(project_name, user_folder, pdf_hash=pdf_hash)


def _flow_rub_debited_label(amount_rub: int) -> str:
    """Списано N ₽. Идет анализ..."""
    n = abs(int(amount_rub))
    return f"Списано {n:,} ₽. Идет анализ...".replace(",", " ")


_HYBRID_PREPARING_UI = (
    "Подготовка результатов нейросетевого анализа конструкторской документации..."
)


def _hybrid_spinner_label(slug: str, hybrid_status: str) -> str:
    if hybrid_status == "preparing":
        return _HYBRID_PREPARING_UI
    charged = st.session_state.get(f"hybrid_rub_charged_{slug}")
    if charged is None:
        legacy = st.session_state.get(f"hybrid_tokens_charged_{slug}")
        if legacy is not None:
            charged = int(legacy) * 10
    if charged is not None:
        return _flow_rub_debited_label(int(charged))
    return "Идет анализ"


def _flow_payment_blocked() -> bool:
    """Блокировка «Поток» при нулевом балансе (не для exempt)."""
    from page_shell import fetch_flow_balance

    import payment as sinlex_payment

    email = (st.session_state.get("user_email") or "").strip()
    if not email or st.session_state.get("guest_mode"):
        return False
    return fetch_flow_balance() <= 0




def _hybrid_result_paywalled(result: dict | None) -> bool:
    """Не показывать гибридный текст без списания при нулевом балансе."""
    if not result or result.get("status") != "ok":
        return False
    if int(result.get("tokens_debited") or 0) > 0:
        return False
    from page_shell import fetch_flow_balance

    return fetch_flow_balance() <= 0




def _try_unlock_flow_pending_hybrid(
    slug: str,
    project_name: str,
    step_data: dict,
) -> bool:
    """После пополнения: снять pending и показать готовый анализ без повторного LLM."""
    email = (st.session_state.get("user_email") or "").strip()
    task_id = (st.session_state.get(hybrid_task_id_key(slug)) or "").strip()
    if not email or not task_id:
        return False
    meta = st.session_state.get(hybrid_pending_meta_key(slug)) or {}
    need = int(meta.get("rub_required") or meta.get("tokens_required") or 0)
    if meta.get("tokens_required") and not meta.get("rub_required"):
        need = int(meta.get("tokens_required") or 0) * 10
    from page_shell import fetch_flow_balance

    import payment as sinlex_payment

    balance = fetch_flow_balance()
    if need > 0 and balance < need:
        return False

    released = sinlex_payment.release_flow_pending_queue(email)
    for item in released:
        if item.get("task_id") != task_id:
            continue
        payload = dict(item.get("result_payload") or {})
        if not (payload.get("analysis") or "").strip():
            continue
        payload["status"] = "ok"
        payload["tokens_debited"] = int(item.get("tokens_debited") or need or 0)
        st.session_state[hybrid_result_key(slug)] = payload
        st.session_state[hybrid_status_key(slug)] = "done"
        st.session_state.pop(hybrid_pending_meta_key(slug), None)
        st.session_state.pop("flow_balance_cache", None)
        return True

    result = _fetch_hybrid_finalize_result(task_id, project_name, step_data)
    if (
        result
        and result.get("status") == "ok"
        and (result.get("analysis") or "").strip()
        and not _hybrid_result_paywalled(result)
    ):
        st.session_state[hybrid_result_key(slug)] = result
        st.session_state[hybrid_status_key(slug)] = "done"
        st.session_state.pop(hybrid_pending_meta_key(slug), None)
        return True
    return False

def hybrid_pending_meta_key(slug: str) -> str:
    return f"hybrid_pending_meta_{slug}"


def _hybrid_button_allowed(cached: dict, saved_pdf: str) -> bool:
    if not saved_pdf or not os.path.isfile(saved_pdf):
        return False
    classification = (cached or {}).get("classification")
    if classification in ("blocked", "review"):
        return False
    return True


def _persist_hybrid_finalize(
    slug: str,
    project_name: str,
    project_dir_for_log: str,
    pdf_bytes: bytes,
    pdf_name: str,
    step_data: dict,
    result: dict,
) -> None:
    """Сохранить результат гибрида в session, log и data.txt (без deep_analysis_{slug})."""
    if st.session_state.get(hybrid_persist_done_key(slug)):
        return
    analysis = (result.get("analysis") or "").strip()
    if not analysis or result.get("status") != "ok":
        return
    st.session_state[hybrid_result_key(slug)] = result
    pdf_hash = hashlib.sha256(pdf_bytes).hexdigest()
    st.session_state[pdf_scan_hash_key(slug)] = pdf_hash
    extraction = result.get("drawing_extraction")
    if extraction:
        st.session_state[drawing_extraction_key(slug)] = extraction
    criteria = result.get("drawing_manufacturing_criteria")
    if not criteria and extraction:
        criteria = store_drawing_criteria_after_analysis(
            slug,
            pdf_hash,
            extraction,
            expert_text=analysis,
        )
    elif criteria:
        if pdf_hash:
            criteria["pdf_hash"] = pdf_hash
        st.session_state[drawing_criteria_key(slug)] = criteria
        st.session_state[costing_recalc_stamp_key(slug)] = pdf_hash
    log_file = os.path.join(project_dir_for_log, "analysis_log.jsonl")
    new_entry = {
        "timestamp": datetime.datetime.now().isoformat(),
        "pdf_name": pdf_name,
        "pdf_hash": pdf_hash,
        "analysis": analysis,
        "temperature": 0.05,
        "hybrid": True,
    }
    if os.path.exists(log_file):
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(new_entry, ensure_ascii=False) + "\n")
    else:
        with open(log_file, "w", encoding="utf-8") as f:
            f.write(json.dumps(new_entry, ensure_ascii=False) + "\n")
    persist_drawing_artifacts_to_project(
        project_name,
        step_data.get("user_folder", "") if step_data else "",
        drawing_extraction=extraction,
        drawing_criteria=criteria,
    )
    st.session_state[hybrid_persist_done_key(slug)] = True


def _fetch_hybrid_finalize_result(
    task_id: str,
    project_name: str,
    step_data: dict,
) -> dict | None:
    """Finalize гибридного job; при успехе — dict с analysis (кэш DeepSeek на сервере)."""
    if not task_id:
        return None
    try:
        fin = requests.post(
            f"{NGROK_URL}/hybrid-analysis/finalize/{task_id}",
            data={
                "step_data": json.dumps(step_data, ensure_ascii=False),
                "project_name": project_name,
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
    if result.get("status") == "pending_payment":
        return result
    if result.get("status") == "ok" and (result.get("analysis") or "").strip():
        return result
    return None


def _tick_hybrid_poll(
    slug: str,
    project_name: str,
    step_data: dict,
    pdf_hash: str = "",
) -> bool:
    """Опрос статуса; True — нужен st.rerun()."""
    if st.session_state.get(hybrid_status_key(slug)) not in (
        "pending",
        "pending_balance",
        "preparing",
    ):
        return False
    task_id = st.session_state.get(hybrid_task_id_key(slug))
    if not task_id:
        st.session_state[hybrid_status_key(slug)] = "error"
        return True
    try:
        resp = requests.get(
            f"{NGROK_URL}/hybrid-analysis/status/{task_id}",
            params={"project_name": project_name},
            headers=get_headers(),
            timeout=30,
        )
    except requests.RequestException:
        return False
    if resp.status_code == 404:
        st.session_state[hybrid_status_key(slug)] = "error"
        clear_hybrid_session(slug)
        return True
    if resp.status_code != 200:
        return False
    data = resp.json()
    status = data.get("status")
    if status == "pending_balance":
        if st.session_state.get(hybrid_status_key(slug)) != "pending_balance":
            st.session_state[hybrid_status_key(slug)] = "pending_balance"
            return True
        return False
    if status == "pending":
        charged = data.get("flow_rub_charged") or data.get("flow_tokens_charged")
        if charged is not None:
            st.session_state[f"hybrid_rub_charged_{slug}"] = int(charged)
        if st.session_state.get(hybrid_status_key(slug)) != "pending":
            st.session_state[hybrid_status_key(slug)] = "pending"
            return True
        return False
    if status == "ready":
        if st.session_state.get(hybrid_status_key(slug)) != "preparing":
            st.session_state[hybrid_status_key(slug)] = "preparing"
            return True
        result = _fetch_hybrid_finalize_result(task_id, project_name, step_data)
        if result and result.get("status") == "pending_payment":
            st.session_state[hybrid_status_key(slug)] = "pending_payment"
            st.session_state[hybrid_pending_meta_key(slug)] = result
            st.session_state.pop(hybrid_result_key(slug), None)
            return True
        if result and result.get("status") == "payment_required":
            st.session_state[hybrid_status_key(slug)] = "error"
            st.session_state[hybrid_error_ui_key(slug)] = result.get("ui_message") or "Недостаточно средств на балансе."
            return True
        if result:
            st.session_state[hybrid_status_key(slug)] = "ready"
            st.session_state[hybrid_result_key(slug)] = result
            st.session_state.pop(hybrid_error_ui_key(slug), None)
            st.session_state.pop(hybrid_pending_meta_key(slug), None)
            if pdf_hash:
                st.session_state[pdf_scan_hash_key(slug)] = pdf_hash
            return True
        st.session_state[hybrid_status_key(slug)] = "error"
        st.session_state[hybrid_error_ui_key(slug)] = LLM_UI_ERROR_MESSAGE
        return True
    if status == "error":
        st.session_state[hybrid_status_key(slug)] = "error"
        st.session_state[hybrid_error_ui_key(slug)] = (
            (data.get("error_ui") or "").strip()
            or "Анализ временно недоступен."
        )
        st.session_state.pop(hybrid_result_key(slug), None)
        return True
    if status == "timeout":
        st.session_state[hybrid_status_key(slug)] = "timeout"
        st.session_state[hybrid_error_ui_key(slug)] = (data.get("error_ui") or "").strip()
        st.session_state.pop(hybrid_result_key(slug), None)
        return True
    return False


def _start_hybrid_analysis_ui(
    slug: str,
    project_name: str,
    pdf_bytes: bytes,
    pdf_name: str,
    step_data: dict,
) -> None:
    clear_hybrid_session(slug)
    try:
        resp = requests.post(
            f"{NGROK_URL}/hybrid-analysis/start",
            files={"file": (pdf_name, pdf_bytes, "application/pdf")},
            data={"step_data": json.dumps(step_data, ensure_ascii=False)},
            headers=get_headers(),
            timeout=30,
        )
    except requests.RequestException as exc:
        st.error(f"Ошибка соединения: {exc}")
        return
    if resp.status_code == 402:
        st.warning("Недостаточно средств на балансе «Поток». Пополните баланс (виджет «Баланс» вверху или кнопка «Баланс» вверху).")
        return
    if resp.status_code != 200:
        detail = resp.json().get("detail", resp.status_code) if resp.content else resp.status_code
        st.error(f"Не удалось запустить углублённый анализ: {detail}")
        return
    data = resp.json()
    task_id = data.get("task_id")
    if not task_id:
        st.error("Не удалось запустить углублённый анализ.")
        return
    st.session_state[hybrid_task_id_key(slug)] = task_id
    st.session_state[hybrid_status_key(slug)] = data.get("status") or "pending_balance"
    st.session_state[hybrid_started_at_key(slug)] = datetime.datetime.now().isoformat()
    st.rerun()


@st.fragment(run_every=timedelta(seconds=_hybrid_poll_interval_sec()))
def _hybrid_poll_fragment(
    slug: str,
    project_name: str,
    step_data: dict,
    pdf_hash: str,
) -> None:
    if _tick_hybrid_poll(slug, project_name, step_data, pdf_hash):
        st.rerun()


def clear_drawing_criteria_session(slug: str) -> None:
    st.session_state.pop(drawing_criteria_key(slug), None)
    st.session_state.pop(costing_recalc_stamp_key(slug), None)


def store_drawing_criteria_after_analysis(
    slug: str,
    pdf_hash: str,
    drawing_extraction: dict | None,
    expert_text: str = "",
) -> dict:
    """Извлекает и кладёт критерии в session (после успешного expert-analysis)."""
    from drawing_analysis.manufacturing_criteria import extract_manufacturing_criteria

    criteria = extract_manufacturing_criteria(
        drawing_extraction,
        expert_text=expert_text,
    )
    if pdf_hash:
        criteria["pdf_hash"] = pdf_hash
    st.session_state[drawing_criteria_key(slug)] = criteria
    st.session_state[costing_recalc_stamp_key(slug)] = pdf_hash
    return criteria


def persist_drawing_artifacts_to_project(
    project_name: str,
    user_folder_val: str,
    *,
    drawing_extraction: dict | None = None,
    drawing_criteria: dict | None = None,
) -> None:
    """Сохраняет extraction / criteria в data.txt."""
    try:
        from project_store import load_project_data, save_project_data

        folder = user_folder_val or user_folder()
        pdata = load_project_data(project_name, folder) or {}
        if drawing_extraction is not None:
            pdata["drawing_extraction"] = drawing_extraction
        if drawing_criteria is not None:
            pdata["drawing_manufacturing_criteria"] = drawing_criteria
        if pdata:
            save_project_data(project_name, pdata, folder)
    except Exception:
        pass


def restore_drawing_artifacts_to_session(data: dict, slug: str) -> None:
    """Восстановить артефакты чертежа из data.txt в session_state."""
    if not data or not slug:
        return
    extraction = data.get("drawing_extraction")
    if extraction:
        st.session_state[drawing_extraction_key(slug)] = extraction
    criteria = data.get("drawing_manufacturing_criteria")
    if criteria:
        st.session_state[drawing_criteria_key(slug)] = criteria
        pdf_hash = criteria.get("pdf_hash") or ""
        if pdf_hash:
            st.session_state[costing_recalc_stamp_key(slug)] = pdf_hash


def resolve_drawing_criteria_for_costing(
    slug: str,
    project_name: str,
    user_folder_val: str = "",
) -> dict | None:
    """
    Критерии для блока стоимости: только после анализа PDF с тем же hash.
    При смене PDF без анализа — сброс.
    """
    folder = user_folder_val or user_folder()
    base_dir = os.path.join("/opt/sinlex/projects", folder) if folder else "/opt/sinlex/projects"
    _proj_dir, saved_pdf = resolve_pdf_paths(base_dir, project_name)

    if not saved_pdf or not os.path.isfile(saved_pdf):
        clear_drawing_criteria_session(slug)
        return None

    with open(saved_pdf, "rb") as f:
        current_hash = hashlib.sha256(f.read()).hexdigest()

    scan_hash = st.session_state.get(pdf_scan_hash_key(slug))
    criteria = st.session_state.get(drawing_criteria_key(slug))

    if not criteria:
        try:
            from project_store import load_project_data

            pdata = load_project_data(project_name, folder) or {}
            criteria = pdata.get("drawing_manufacturing_criteria")
            if criteria:
                st.session_state[drawing_criteria_key(slug)] = criteria
                ph = criteria.get("pdf_hash") or ""
                if ph:
                    st.session_state[costing_recalc_stamp_key(slug)] = ph
        except Exception:
            criteria = None

    from drawing_analysis.manufacturing_criteria import criteria_applies_to_pdf

    if not criteria_applies_to_pdf(criteria, current_hash, scan_hash):
        if criteria and (criteria.get("pdf_hash") or "") != current_hash:
            clear_drawing_criteria_session(slug)
        return None

    return criteria


def render_drawing_pages_caption(drawing_extraction: dict | None) -> None:
    """Подпись о числе обработанных листов чертежа (без служебных методов извлечения)."""
    if not drawing_extraction:
        return
    parts: list[str] = []
    n = drawing_extraction.get("pages_processed") or drawing_extraction.get("page_count")
    if n:
        parts.append(f"Обработано листов: {n}")
    warnings = drawing_extraction.get("warnings") or []
    if "ocr_timeout" in warnings:
        parts.append("⚠️ таймаут OCR")
    if parts:
        st.caption(" · ".join(parts))


def render_drawing_layout_debug(drawing_extraction: dict | None) -> None:
    """Мини-превью зон layout (этап 3 TZ, только SINLEX_DEBUG=1)."""
    if not drawing_extraction or os.environ.get("SINLEX_DEBUG", "").strip() not in (
        "1",
        "true",
        "yes",
    ):
        return
    layout = drawing_extraction.get("layout") or {}
    if not layout.get("pages"):
        return
    with st.expander("Зоны чертежа (debug)", expanded=False):
        merged = layout.get("merged_zones") or {}
        for zone in ("title_block", "notes", "dimension_area"):
            text = (merged.get(zone) or "").strip()
            if text:
                st.markdown(f"**{zone}**")
                st.text(text[:800] + ("…" if len(text) > 800 else ""))
        fields = drawing_extraction.get("fields") or {}
        src = fields.get("fields_source", "?")
        des = fields.get("designation", "")
        st.caption(f"fields_source={src}, designation={des[:80] if des else '—'}")




def last_saved_analysis_key(slug: str) -> str:
    return f"last_saved_analysis_{slug}"


def tech_card_key(slug: str) -> str:
    return f"tech_card_result_{slug}"


def clear_legacy_expert_session() -> None:
    st.session_state.pop("deep_analysis_current", None)
    st.session_state.pop("last_saved_analysis", None)


def pdf_pending_bytes_key(slug: str) -> str:
    return f"pdf_pending_bytes_{slug}"


def pdf_pending_name_key(slug: str) -> str:
    return f"pdf_pending_name_{slug}"


def pdf_staged_bytes_key(slug: str) -> str:
    return f"pdf_staged_bytes_{slug}"


def pdf_staged_name_key(slug: str) -> str:
    return f"pdf_staged_name_{slug}"


def pdf_file_widget_key(slug: str) -> str:
    return f"pdf_file_{slug}"


def read_uploaded_pdf_bytes(uploaded_file) -> bytes:
    if uploaded_file is None:
        return b""
    data = uploaded_file.getvalue()
    if not data:
        try:
            data = uploaded_file.read()
        except Exception:
            data = b""
    return data or b""


def resolve_pdf_paths(base_dir: str, project_name: str):
    """Каталог проекта и путь к PDF (поддержка старых имён файлов)."""
    safe_pn = safe_dir_name(project_name)
    project_dir = os.path.join(base_dir, safe_pn)
    canonical = os.path.join(project_dir, f"{safe_pn}.pdf")
    if os.path.exists(canonical):
        return project_dir, canonical
    if os.path.isdir(project_dir):
        for fname in os.listdir(project_dir):
            if fname.lower().endswith(".pdf"):
                return project_dir, os.path.join(project_dir, fname)
    return project_dir, canonical


def save_pdf_bytes(project_dir: str, project_name: str, slug: str, pdf_bytes: bytes, pdf_name: str) -> str:
    out_path = os.path.join(project_dir, f"{safe_dir_name(project_name)}.pdf")
    with open(out_path, "wb") as f:
        f.write(pdf_bytes)
    st.session_state[pdf_pending_name_key(slug)] = pdf_name
    st.session_state.pop(pdf_pending_bytes_key(slug), None)
    return out_path


def clear_pdf_pending(slug: str) -> None:
    st.session_state.pop(pdf_pending_bytes_key(slug), None)
    st.session_state.pop(pdf_pending_name_key(slug), None)
    st.session_state.pop(pdf_staged_bytes_key(slug), None)
    st.session_state.pop(pdf_staged_name_key(slug), None)
    st.session_state.pop(f"pdf_upload_error_{slug}", None)
    st.session_state.pop(f"pdf_stashed_notice_{slug}", None)


def pdf_project_name_from_session() -> str:
    """Имя проекта для PDF: приоритет у загруженного STEP (не у устаревшего current_project)."""
    name = st.session_state.get("cached_step_name") or ""
    for ext in (".stp", ".step", ".STP", ".STEP"):
        if name.lower().endswith(ext.lower()):
            return name[: -len(ext)]
    if st.session_state.get("current_project"):
        return str(st.session_state["current_project"])
    return name


@st.fragment
def pdf_upload_fragment(project_name: str, slug: str) -> None:
    """Изолированный перезапуск: выбор PDF не тянет тяжёлую обработку STEP/GLB."""
    render_pdf_uploader(project_name, slug)


def render_pdf_uploader(project_name: str, slug: str) -> None:
    """Выбор PDF с немедленным чтением (виджет должен быть до тяжёлой обработки STEP)."""
    if st.session_state.get("guest_mode") or not st.session_state.get("user_email"):
        st.warning("Войдите в аккаунт для загрузки чертежа.")
        return
    upl_gen = int(st.session_state.get(f"pdf_uploader_gen_{slug}", 0))
    pdf_file = st.file_uploader(
        "📄 Загрузить чертеж",
        type=["pdf"],
        key=f"pdf_drawing_{slug}_{upl_gen}",
    )
    if pdf_file is None:
        return
    pdf_bytes = pdf_file.getvalue() or pdf_file.read()
    if not pdf_bytes:
        st.warning("Не удалось прочитать PDF.")
        return
    pdf_hash = hashlib.sha256(pdf_bytes).hexdigest()
    last_saved_hash_key = f"pdf_saved_hash_{slug}"
    if st.session_state.get(last_saved_hash_key) == pdf_hash:
        return
    pdf_name = pdf_file.name or "drawing.pdf"
    folder = st.session_state.get("user_folder") or ""
    base_dir = os.path.join("/opt/sinlex/projects", folder) if folder else "/opt/sinlex/projects"
    proj_dir, _ = resolve_pdf_paths(base_dir, project_name)
    os.makedirs(proj_dir, exist_ok=True)
    out_path = save_pdf_bytes(proj_dir, project_name, slug, pdf_bytes, pdf_name)
    st.session_state[last_saved_hash_key] = pdf_hash
    st.session_state[f"pdf_saved_path_{slug}"] = out_path
    st.session_state.pop(deep_analysis_key(slug), None)
    st.session_state.pop(drawing_extraction_key(slug), None)
    clear_drawing_criteria_session(slug)
    st.session_state.pop(last_saved_analysis_key(slug), None)
    st.session_state.pop(pdf_scan_hash_key(slug), None)
    st.session_state.pop(tech_card_key(slug), None)
    clear_hybrid_session(slug)
    _purge_hybrid_for_project(project_name, folder)
    clear_legacy_expert_session()
    st.toast(f"Чертёж сохранён: {pdf_name}", icon="✅")
    st.rerun()


def expert_step_data(
    project_name: str,
    user_folder_val: str,
    model_volume,
    dimensions,
    geometry,
) -> dict:
    return {
        "volume": model_volume,
        "dimensions": dimensions if isinstance(dimensions, dict) else {},
        "geometry": geometry if isinstance(geometry, dict) else {},
        "project_name": project_name,
        "user_folder": user_folder_val or "",
        "material": st.session_state.get("mat", ""),
        "workpiece_type": st.session_state.get("wp", ""),
        "diam": st.session_state.get("diam", 0),
        "length": st.session_state.get("len", 0),
        "cost_per_hour": st.session_state.get("cost_h", 0),
    }


def delete_drawing_files(
    project_dir_for_log: str,
    saved_pdf: str,
    slug: str,
    *,
    project_name: str = "",
    user_folder: str = "",
) -> None:
    """Удалить PDF и связанные файлы анализа из папки проекта."""
    pname = (project_name or st.session_state.get("current_project") or "").strip()
    ufolder = (user_folder or st.session_state.get("user_folder") or "").strip()
    if pname and ufolder:
        _purge_hybrid_for_project(pname, ufolder)
    if saved_pdf and os.path.exists(saved_pdf):
        os.remove(saved_pdf)
    log_file = os.path.join(project_dir_for_log, "analysis_log.jsonl")
    if os.path.exists(log_file):
        os.remove(log_file)
    cache_dir = os.path.join(project_dir_for_log, "analysis_cache")
    if os.path.exists(cache_dir):
        shutil.rmtree(cache_dir, ignore_errors=True)
    st.session_state.pop(deep_analysis_key(slug), None)
    st.session_state.pop(drawing_extraction_key(slug), None)
    clear_drawing_criteria_session(slug)
    st.session_state.pop(last_saved_analysis_key(slug), None)
    st.session_state.pop(pdf_scan_hash_key(slug), None)
    st.session_state.pop(f"pdf_saved_path_{slug}", None)
    st.session_state.pop(f"pdf_saved_hash_{slug}", None)
    st.session_state.pop(tech_card_key(slug), None)
    clear_hybrid_session(slug)
    clear_pdf_pending(slug)
    st.session_state.pop(pdf_staged_bytes_key(slug), None)
    st.session_state.pop(pdf_staged_name_key(slug), None)
    clear_legacy_expert_session()
    gen_key = f"pdf_uploader_gen_{slug}"
    st.session_state[gen_key] = int(st.session_state.get(gen_key, 0)) + 1


def render_delete_drawing_button(
    project_dir_for_log: str,
    saved_pdf: str,
    slug: str,
    *,
    project_name: str = "",
    user_folder: str = "",
) -> None:
    if st.button("🗑️ Удалить чертёж", key=f"btn_del_pdf_{slug}", use_container_width=True):
        delete_drawing_files(
            project_dir_for_log,
            saved_pdf,
            slug,
            project_name=project_name,
            user_folder=user_folder,
        )
        st.toast("Чертёж удалён", icon="🗑️")
        st.rerun()


def is_llm_unavailable_message(text: str) -> bool:
    """Отказ LLM (классика, гибрид finalize, техкарта)."""
    if not text:
        return False
    t = str(text).strip()
    if t == LLM_UI_ERROR_MESSAGE or LLM_UI_ERROR_MESSAGE in t:
        return True
    legacy = (
        "Ошибка анализа:",
        "Ошибка экспертного анализа:",
        "Экспертный анализ:",
    )
    return any(t.startswith(p) for p in legacy) and LLM_UI_ERROR_MESSAGE in t


def show_llm_unavailable_error() -> None:
    st.error(LLM_UI_ERROR_MESSAGE)


def show_analysis_error(text: str) -> None:
    """Единый текст для отказа LLM; прочие ошибки — как есть."""
    if is_llm_unavailable_message(text):
        show_llm_unavailable_error()
    else:
        st.error(text)


def show_hybrid_failure(slug: str, hybrid_status: str) -> None:
    """Таймаут Max ≠ отказ LLM (LP-3)."""
    if hybrid_status == "timeout":
        st.error(HYBRID_SUFFLER_TIMEOUT_MESSAGE)
        return
    err_ui = (st.session_state.get(hybrid_error_ui_key(slug)) or "").strip()
    if is_llm_unavailable_message(err_ui):
        show_llm_unavailable_error()
    elif err_ui:
        st.error(err_ui)
    else:
        st.error(HYBRID_SUFFLER_TIMEOUT_MESSAGE)


def is_deep_analysis_error(text: str) -> bool:
    """Текст ошибки API, сохранённый вместо анализа."""
    if not text:
        return False
    t = str(text).strip()
    if is_llm_unavailable_message(t):
        return True
    return t.startswith("Ошибка анализа:") or t.startswith("Ошибка экспертного анализа:")


def load_deep_analysis_from_log(log_file: str, pdf_hash: str):
    """Восстановить текст анализа из analysis_log.jsonl по хешу PDF."""
    if not log_file or not os.path.exists(log_file):
        return None
    try:
        with open(log_file, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        return None
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if entry.get("pdf_hash") == pdf_hash:
            if entry.get("hybrid"):
                continue
            text = entry.get("analysis") or ""
            if text and not is_deep_analysis_error(text):
                return text
    return None




def load_hybrid_result_from_log(log_file: str, pdf_hash: str) -> dict | None:
    """Восстановить результат «Поток» из analysis_log.jsonl (hybrid: true)."""
    if not log_file or not pdf_hash or not os.path.exists(log_file):
        return None
    try:
        with open(log_file, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        return None
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if entry.get("pdf_hash") != pdf_hash or not entry.get("hybrid"):
            continue
        text = (entry.get("analysis") or "").strip()
        if text and not is_deep_analysis_error(text):
            return {
                "status": "ok",
                "analysis": text,
                "restored_from": "analysis_log",
            }
    return None


def restore_hybrid_session_from_persisted(
    slug: str,
    project_name: str,
    user_folder: str,
    pdf_hash: str,
    log_file: str,
) -> bool:
    """Восстановить сессию «Поток» после перезахода (job + log)."""
    cur = (st.session_state.get(hybrid_status_key(slug)) or "idle").strip()
    if cur not in ("", "idle"):
        if st.session_state.get(hybrid_result_key(slug)):
            return False
    if cur in ("", "idle") and st.session_state.get(hybrid_result_key(slug)):
        return True

    from hybrid_analysis import (
        find_latest_hybrid_job,
        hybrid_session_restore_plan,
        hybrid_finalize_result_from_job,
    )

    job = find_latest_hybrid_job(project_name, user_folder, pdf_hash=pdf_hash)
    if job:
        plan = hybrid_session_restore_plan(job)
        if plan:
            st.session_state[hybrid_task_id_key(slug)] = plan["task_id"]
            ui_status = plan.get("ui_status") or "idle"
            rub = plan.get("rub_charged")
            if rub is not None:
                st.session_state[f"hybrid_rub_charged_{slug}"] = int(rub)
            result = plan.get("result")
            if result:
                st.session_state[hybrid_result_key(slug)] = result
                st.session_state[hybrid_status_key(slug)] = "done"
                return True
            if ui_status == "error":
                st.session_state[hybrid_status_key(slug)] = "error"
                st.session_state[hybrid_error_ui_key(slug)] = plan.get("error_ui") or ""
                return True
            if ui_status == "timeout":
                st.session_state[hybrid_status_key(slug)] = "timeout"
                st.session_state[hybrid_error_ui_key(slug)] = plan.get("error_ui") or ""
                return True
            if ui_status in ("pending_balance", "pending", "preparing"):
                st.session_state[hybrid_status_key(slug)] = ui_status
                return True

    log_result = load_hybrid_result_from_log(log_file, pdf_hash)
    if log_result:
        st.session_state[hybrid_result_key(slug)] = log_result
        st.session_state[hybrid_status_key(slug)] = "done"
        if job and (job.get("task_id") or "").strip():
            st.session_state[hybrid_task_id_key(slug)] = job["task_id"]
        return True

    return False


def format_analysis_for_display(text: str) -> str:
    """Для UI: снять legacy «Супер-серверный»; ⚫/🔵 Sinlex AI 1.0/1.2 оставить."""
    try:
        from expert_analyzer import normalize_analysis_display

        return normalize_analysis_display(text or "")
    except Exception:
        return (text or "").lstrip()


def strip_provider_markers(text: str) -> str:
    """Алиас format_analysis_for_display (обратная совместимость)."""
    return format_analysis_for_display(text)


def sanitize_tech_card_for_ui(text: str) -> str:
    """Убрать из техкарты технические имена полей (старый кэш / ответ модели)."""
    if not text:
        return text
    tech_markers = (
        "machining_",
        "cutting_per_",
        "setup_per_",
        "cam_per_part",
        "batch_size",
        "cost_per_unit",
        "machine_hour_rate",
        "workpiece_type",
    )
    out = []
    for line in text.splitlines():
        low = line.lower()
        if any(m in low for m in tech_markers):
            continue
        out.append(line)
    return "\n".join(out).strip()


def hours_ceil(h: float) -> int:
    """Целые часы, округление вверх."""
    if h <= 0:
        return 0
    return int(math.ceil(h))


def inject_tech_card_section5(text: str, quote: dict) -> str:
    """П.5 техкарты — время только в целых часах из расчёта Sinlex."""
    if not quote:
        return text
    batch = int(quote.get("Партия, шт", 1))
    h_part = int(quote.get("Время на 1 деталь, ч", 0))
    h_batch = int(quote.get("Время на партию, ч", 0))
    criteria_note = (quote.get("Критерии чертежа (Sinlex)") or "").strip()
    block = (
        "5. **Итоговое время обработки**\n\n"
        f"Партия: {batch} шт.\n"
        f"Время на 1 деталь: {h_part} ч.\n"
        f"Время на партию: {h_batch} ч."
    )
    if criteria_note:
        block += f"\n\nУчтены критерии чертежа: {criteria_note}"
    pattern = r"5\.\s*\*?\*?Итоговое время обработки\*?\*?.*?(?=\n\d+\.\s|\nDEBUG_|$)"
    if re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL):
        return re.sub(pattern, block, text, count=1, flags=re.IGNORECASE | re.DOTALL)
    return text.rstrip() + "\n\n" + block


def finalize_tech_card_text(text: str, quote: dict) -> str:
    cleaned = sanitize_tech_card_for_ui(strip_provider_markers(text))
    return inject_tech_card_section5(cleaned, quote)


def enrich_costing_quote_with_drawing_criteria(
    quote: dict,
    *,
    drawing_criteria: dict | None = None,
    criteria_breakdown: dict | None = None,
) -> dict:
    """Строки критериев чертежа для техкарты (CR-5). Цифры времени уже с модификаторами."""
    if not quote:
        return quote
    criteria = drawing_criteria or {}
    active = criteria.get("active_codes") or []
    if not active:
        return quote
    out = dict(quote)
    summary = (criteria.get("summary_ru") or "").strip()
    if summary:
        out["Критерии чертежа (Sinlex)"] = summary
    mods = criteria.get("modifiers") or {}
    bd = criteria_breakdown or {}
    ops_add = bd.get("operations_add") or mods.get("operations_add") or []
    if ops_add:
        out["Доп. процессы по чертежу"] = ", ".join(str(o) for o in ops_add)
    measure = float(mods.get("measure_per_part_h") or bd.get("measure_per_part_h") or 0)
    if measure > 0:
        out["Контроль с чертежа, ч/шт"] = round(measure, 2)
    grind = float(bd.get("grind_price_mult") or mods.get("grind_price_mult") or 1.0)
    if grind > 1.0:
        out["Коэфф. шлифования (цена)"] = grind
    return out


def enrich_costing_quote_with_geometry(quote: dict, geometry: dict | None = None) -> dict:
    """Добавить в quote число установов из OCC (отдельно от базового расчёта)."""
    geometry = geometry or {}
    setups = geometry.get("setup_count_total")
    if setups is None:
        return quote
    out = dict(quote)
    out["Количество установов (OCC)"] = int(setups)
    if geometry.get("setup_count_milling"):
        out["Установы фрезерные"] = int(geometry["setup_count_milling"])
    if geometry.get("setup_count_turning"):
        out["Установы токарные"] = int(geometry["setup_count_turning"])
    sp = geometry.get("setup_planes") or {}
    if sp.get("milling", {}).get("flip_required"):
        out["Переворот плиты"] = "да (противоположные стороны)"
    return out


def build_costing_quote_for_tech_card(
    *,
    batch_size: int,
    mhpu: float,
    mht: float,
    cutting_per_part_h: float,
    setup_per_part_h: float,
    cam_per_part_h: float,
    cpu: float,
    tc: float,
    material: str,
    workpiece_type: str,
    cost_per_hour: int,
    geometry: dict | None = None,
) -> dict:
    """Цифры из блока «Стоимость за изделие» для техкарты (только русские подписи)."""
    quote = {
        "Партия, шт": batch_size,
        "Время на 1 деталь, ч": hours_ceil(mhpu),
        "Время на партию, ч": hours_ceil(mht),
        "Материал": material,
        "Тип заготовки": workpiece_type,
        "Станко-час, ₽": cost_per_hour,
        "Цена за 1 шт, ₽": int(cpu),
        "Стоимость партии, ₽": int(tc),
    }
    return enrich_costing_quote_with_geometry(quote, geometry)


def render_pdf_scan_status_banner(scan_result, *, plain: bool = False) -> None:
    """Статус проверки грифов на всю ширину под заголовком."""
    if not scan_result:
        return
    classification = scan_result.get("classification")
    if classification == "safe":
        msg = "✅ Чертёж прошёл проверку"
        if plain:
            _render_dop_plain_notice(msg, "ok")
        else:
            st.success(msg)
    elif classification == "review":
        msg = "⚠️ Требуется проверка"
        if plain:
            _render_dop_plain_notice(msg, "warn")
        else:
            st.warning(msg)
    elif classification == "blocked":
        msg = "🚫 Файл заблокирован!"
        if plain:
            _render_dop_plain_notice(msg, "err")
        else:
            st.error(msg)
    elif scan_result.get("message"):
        msg = scan_result.get("message", "Неизвестный результат проверки")
        if plain:
            _render_dop_plain_notice(msg, "err")
        else:
            st.error(msg)


def process_pdf_scan(
    pdf_bytes,
    pdf_name,
    project_name,
    project_dir_for_log,
    step_data,
    append_log=False,
    slug=None,
):
    """Сохранение PDF, проверка грифов, затем экспертный анализ. Возвращает dict ответа API или None."""
    if not slug:
        slug = project_key_slug(project_name)
    deep_key = deep_analysis_key(slug)
    saved_key = last_saved_analysis_key(slug)
    drawing_path = os.path.join(project_dir_for_log, f"{safe_dir_name(project_name)}.pdf")
    with open(drawing_path, "wb") as f:
        f.write(pdf_bytes)

    with st.spinner("🔍 Проверка грифов и штампа…"):
        resp_scan = requests.post(
            f"{NGROK_URL}/scan-risk",
            files={"file": (pdf_name, pdf_bytes, "application/pdf")},
            data={"step_data": json.dumps(step_data)},
            headers=get_headers(),
            timeout=30,
        )
    if resp_scan.status_code != 200:
        st.error(f"Ошибка сервера при проверке: {resp_scan.status_code}")
        return None
    scan_result = resp_scan.json()
    classification = scan_result.get("classification")
    if classification == "safe":
        deep = ""
        with st.spinner("Анализ чертежа (~20–40 сек)…"):
            try:
                resp_deep = requests.post(
                    f"{NGROK_URL}/expert-analysis",
                    files={"file": (pdf_name, pdf_bytes, "application/pdf")},
                    data={"step_data": json.dumps(step_data)},
                    headers=get_headers(),
                    timeout=120,
                )
            except requests.Timeout:
                st.error("Превышено время ожидания экспертного анализа. Попробуйте ещё раз.")
                return scan_result
            except requests.RequestException as e:
                st.error(f"Ошибка соединения: {e}")
                return scan_result
            if resp_deep.status_code != 200:
                st.error(f"Ошибка экспертного анализа: HTTP {resp_deep.status_code}")
                return scan_result
            deep_result = resp_deep.json()
            if deep_result.get("status") == "ok":
                deep = deep_result.get("analysis", "")
                scan_result["deep_analysis"] = deep
                scan_result["api_used"] = deep_result.get("api_used", "")
                extraction = deep_result.get("drawing_extraction")
                if extraction:
                    scan_result["drawing_extraction"] = extraction
                    st.session_state[drawing_extraction_key(slug)] = extraction
            else:
                msg = deep_result.get("message", "неизвестная ошибка")
                if is_llm_unavailable_message(msg):
                    show_llm_unavailable_error()
                else:
                    st.error(f"Анализ чертежа: {msg}")
                return scan_result
        if deep and is_deep_analysis_error(deep):
            show_analysis_error(deep)
            st.session_state.pop(deep_key, None)
        elif deep:
            log_file = os.path.join(project_dir_for_log, "analysis_log.jsonl")
            new_entry = {
                "timestamp": datetime.datetime.now().isoformat(),
                "pdf_name": pdf_name,
                "pdf_hash": hashlib.sha256(pdf_bytes).hexdigest(),
                "analysis": deep,
                "temperature": 0.05,
            }
            if append_log and os.path.exists(log_file):
                with open(log_file, "a", encoding="utf-8") as f:
                    f.write(json.dumps(new_entry, ensure_ascii=False) + "\n")
            else:
                with open(log_file, "w", encoding="utf-8") as f:
                    f.write(json.dumps(new_entry, ensure_ascii=False) + "\n")
            pdf_hash = hashlib.sha256(pdf_bytes).hexdigest()
            st.session_state[deep_key] = deep
            st.session_state[saved_key] = scan_result
            st.session_state[pdf_scan_hash_key(slug)] = pdf_hash
            extraction_for_crit = (
                st.session_state.get(drawing_extraction_key(slug))
                or scan_result.get("drawing_extraction")
            )
            criteria = store_drawing_criteria_after_analysis(
                slug,
                pdf_hash,
                extraction_for_crit,
                expert_text=deep,
            )
            scan_result["drawing_manufacturing_criteria"] = criteria
            persist_drawing_artifacts_to_project(
                project_name,
                step_data.get("user_folder", "") if step_data else "",
                drawing_extraction=extraction_for_crit,
                drawing_criteria=criteria,
            )
            clear_legacy_expert_session()
    elif classification in ("review", "blocked"):
        st.session_state[saved_key] = scan_result
        st.session_state.pop(deep_key, None)
        clear_drawing_criteria_session(slug)
        st.session_state[pdf_scan_hash_key(slug)] = hashlib.sha256(pdf_bytes).hexdigest()
        clear_legacy_expert_session()
    else:
        st.session_state[saved_key] = scan_result
        st.session_state.pop(deep_key, None)
        clear_drawing_criteria_session(slug)
        clear_legacy_expert_session()
    return scan_result


def _inject_potok_button_styles() -> None:
    """Стили кнопок «Поток» (бирюза) и «Результат» (серый)."""
    st.markdown(
        """
<style>
div[class*="st-key-btn_hybrid_"] button[kind="secondary"],
div[class*="st-key-btn_hybrid_"] button {
    background-color: #14b8a6 !important;
    border-color: #14b8a6 !important;
    color: #ffffff !important;
}
div[class*="st-key-btn_hybrid_"] button:hover:not(:disabled) {
    background-color: #0d9488 !important;
    border-color: #0d9488 !important;
    color: #ffffff !important;
}
div[class*="st-key-btn_hybrid_"] button:focus:not(:disabled) {
    box-shadow: 0 0 0 0.2rem rgba(20, 184, 166, 0.45) !important;
}
div[class*="st-key-btn_hybrid_"] button:disabled {
    background-color: #99f6e4 !important;
    border-color: #99f6e4 !important;
    color: #ffffff !important;
    opacity: 0.85;
}
div[class*="st-key-btn_hybrid_"] button p,
div[class*="st-key-btn_hybrid_"] button div {
    color: #ffffff !important;
}


div[class*="st-key-btn_show_drawing_analysis_"] button[kind="secondary"],
div[class*="st-key-btn_show_drawing_analysis_"] button {
    background-color: #6b7280 !important;
    border-color: #6b7280 !important;
    color: #ffffff !important;
}
div[class*="st-key-btn_show_drawing_analysis_"] button:hover:not(:disabled) {
    background-color: #4b5563 !important;
    border-color: #4b5563 !important;
    color: #ffffff !important;
}
div[class*="st-key-btn_show_drawing_analysis_"] button:focus:not(:disabled) {
    box-shadow: 0 0 0 0.2rem rgba(107, 114, 128, 0.45) !important;
}
div[class*="st-key-btn_show_drawing_analysis_"] button:disabled {
    background-color: #d1d5db !important;
    border-color: #d1d5db !important;
    color: #ffffff !important;
    opacity: 0.85;
}
div[class*="st-key-btn_show_drawing_analysis_"] button p,
div[class*="st-key-btn_show_drawing_analysis_"] button div {
    color: #ffffff !important;
}


div[class*="st-key-btn_scan_pdf_"] button[kind="primary"],
div[class*="st-key-btn_scan_pdf_"] button,
div[class*="st-key-btn_order_placement_"] button[kind="secondary"],
div[class*="st-key-btn_order_placement_"] button {
    background: linear-gradient(135deg, #ff8800 0%, #ff9a2e 100%) !important;
    border: 1px solid #ff8800 !important;
    border-color: #ff8800 !important;
    color: #ffffff !important;
}
div[class*="st-key-btn_scan_pdf_"] button:hover:not(:disabled),
div[class*="st-key-btn_order_placement_"] button:hover:not(:disabled) {
    background: linear-gradient(135deg, #e67a00 0%, #ff8800 100%) !important;
    border-color: #e67a00 !important;
    color: #ffffff !important;
}
div[class*="st-key-btn_scan_pdf_"] button:focus:not(:disabled),
div[class*="st-key-btn_order_placement_"] button:focus:not(:disabled) {
    box-shadow: 0 0 0 0.2rem rgba(255, 136, 0, 0.35) !important;
}
div[class*="st-key-btn_scan_pdf_"] button:disabled,
div[class*="st-key-btn_order_placement_"] button:disabled {
    background: #ffcc99 !important;
    border-color: #ffcc99 !important;
    color: #ffffff !important;
    opacity: 0.85;
}
div[class*="st-key-btn_scan_pdf_"] button p,
div[class*="st-key-btn_scan_pdf_"] button div,
div[class*="st-key-btn_order_placement_"] button p,
div[class*="st-key-btn_order_placement_"] button div {
    color: #ffffff !important;
}

/* Подпись + «?» (popover) под кнопками анализа — без внутренней прокрутки */
[data-testid="stHorizontalBlock"]:has([class*="st-key-potok_pop_"]) {
    overflow: visible !important;
    max-height: none !important;
    align-items: flex-start !important;
}
[data-testid="stHorizontalBlock"]:has([class*="st-key-potok_pop_"]) > [data-testid="column"] {
    overflow: visible !important;
    max-height: none !important;
}
[data-testid="stHorizontalBlock"]:has([class*="st-key-potok_pop_"]) [data-testid="stCaptionContainer"] {
    overflow: visible !important;
    max-height: none !important;
}
div[class*="st-key-potok_pop_"],
div[class*="st-key-potok_pop_"] [data-testid="stVerticalBlock"] {
    margin: 0 !important;
    padding: 0 !important;
    overflow: visible !important;
    max-height: none !important;
}
div[class*="st-key-potok_pop_"] .stPopover > button {
    min-height: 1.2rem !important;
    height: 1.2rem !important;
    width: 1.2rem !important;
    min-width: 1.2rem !important;
    padding: 0 !important;
    font-size: 0.72rem !important;
    font-weight: 700 !important;
    line-height: 1 !important;
    border-radius: 50% !important;
    border: 1px solid rgba(49, 51, 63, 0.35) !important;
    color: rgba(49, 51, 63, 0.65) !important;
    background: #ffffff !important;
}
</style>
""",
        unsafe_allow_html=True,
    )







_DRAWING_ORDER_CAPTION = (
    "Одна кнопка — и деталь в работе: согласуем сроки, уточним детали "
    "и подготовим счёт с вашим менеджером."
)

_DOP_NOTICE_STYLES = {
    "ok": ("sinlex-dop-ok", "#d4edda", "#c3e6cb", "#155724"),
    "warn": ("sinlex-dop-warn", "#fff3cd", "#ffeeba", "#856404"),
    "err": ("sinlex-dop-err", "#f8d7da", "#f5c6cb", "#721c24"),
    "info": ("sinlex-dop-info", "#d1ecf1", "#bee5eb", "#0c5460"),
}


def _render_dop_plain_notice(message: str, kind: str = "ok") -> None:
    """Плоское уведомление без st.success / stAlert (без внутренней прокрутки)."""
    cls, bg, border, color = _DOP_NOTICE_STYLES.get(kind, _DOP_NOTICE_STYLES["ok"])
    safe = (
        message.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
    st.markdown(
        f'<div class="{cls}">{safe}</div>',
        unsafe_allow_html=True,
    )


def _inject_drawing_order_panel_styles() -> None:
    """Стили секции «Работа с чертежом и заказом»."""
    st.markdown(
        """
<style>
#sinlex-drawing-order-panel { display: none !important; }
.sinlex-dop-ok,
.sinlex-dop-warn,
.sinlex-dop-err,
.sinlex-dop-info {
    padding: 0.75rem 1rem;
    border-radius: 0.5rem;
    margin: 0 0 0.75rem 0;
    font-size: 0.875rem;
    line-height: 1.45;
    border: 1px solid;
    overflow: visible !important;
}
.sinlex-dop-ok { background: #d4edda; border-color: #c3e6cb; color: #155724; }
.sinlex-dop-warn { background: #fff3cd; border-color: #ffeeba; color: #856404; }
.sinlex-dop-err { background: #f8d7da; border-color: #f5c6cb; color: #721c24; }
.sinlex-dop-info { background: #d1ecf1; border-color: #bee5eb; color: #0c5460; }
/* Панель чертёж/заказ: никаких вложенных scroll-контейнеров */
[data-testid="stMain"]:has(#sinlex-drawing-order-panel) [data-testid="stHorizontalBlock"] {
    align-items: flex-start !important;
    overflow: visible !important;
    max-height: none !important;
}
[data-testid="stMain"]:has(#sinlex-drawing-order-panel) [data-testid="column"],
[data-testid="stMain"]:has(#sinlex-drawing-order-panel) [data-testid="stColumn"],
[data-testid="stMain"]:has(#sinlex-drawing-order-panel) [data-testid="stVerticalBlock"],
[data-testid="stMain"]:has(#sinlex-drawing-order-panel) [data-testid="stElementContainer"],
[data-testid="stMain"]:has(#sinlex-drawing-order-panel) [data-testid="stCaptionContainer"],
[data-testid="stMain"]:has(#sinlex-drawing-order-panel) [data-testid="stMarkdownContainer"] {
    overflow: visible !important;
    max-height: none !important;
    height: auto !important;
}
</style>
        """,
        unsafe_allow_html=True,
    )


def _render_drawing_result_hint(slug: str, cached: dict, saved_pdf: str) -> None:
    """Подпись под блоком анализа; «?» открывает подсказку про «Поток»."""
    show_potok = hybrid_suffler_ui_enabled() and _hybrid_button_allowed(
        cached, saved_pdf
    )
    if show_potok:
        _inject_potok_button_styles()
        txt_col, q_col = st.columns(
            [0.985, 0.015], gap="small", vertical_alignment="top"
        )
        with txt_col:
            st.caption(
                "Нажмите «Анализировать» или «Поток» — затем нажмите «Результат» для просмотра."
            )
        with q_col:
            with st.popover("?", key=f"potok_pop_{slug}"):
                st.markdown(POTOK_HELP_TOOLTIP)
    else:
        st.caption("Нажмите «Анализировать» — затем нажмите «Результат» для просмотра.")




def _drawing_analysis_complete_for_ui(
    slug: str,
    pdf_hash: str,
    scan_hash_session_key: str,
    *,
    hybrid_pending: bool = False,
) -> bool:
    """Классический или «Поток» уже выведен — кнопки запуска не показываем."""
    if hybrid_pending:
        return False
    hybrid_status = (st.session_state.get(hybrid_status_key(slug)) or "idle").strip()
    if hybrid_status == "done":
        result = st.session_state.get(hybrid_result_key(slug)) or {}
        if (result.get("analysis") or "").strip() and result.get("status") == "ok":
            return True
    deep = st.session_state.get(deep_analysis_key(slug))
    if (
        deep
        and not is_deep_analysis_error(deep)
        and st.session_state.get(scan_hash_session_key) == pdf_hash
        and hybrid_status not in ("pending", "pending_balance", "preparing", "ready")
    ):
        return True
    return False



def resolve_drawing_analysis_text(
    slug: str,
    pdf_hash: str,
    scan_hash_session_key: str,
    *,
    cached: dict | None = None,
    log_file: str = "",
) -> tuple[str | None, dict | None, str]:
    """Текст анализа для модалки: классика или «Поток»."""
    hybrid_status = (st.session_state.get(hybrid_status_key(slug)) or "idle").strip()
    if hybrid_status == "done":
        result = st.session_state.get(hybrid_result_key(slug)) or {}
        analysis = (result.get("analysis") or "").strip()
        if analysis and result.get("status") == "ok" and not _hybrid_result_paywalled(result):
            extraction = (
                st.session_state.get(drawing_extraction_key(slug))
                or result.get("drawing_extraction")
            )
            return analysis, extraction, 'Режим «Поток»'

    deep = st.session_state.get(deep_analysis_key(slug))
    if (not deep or is_deep_analysis_error(deep)) and log_file:
        restored = load_deep_analysis_from_log(log_file, pdf_hash)
        if restored and not st.session_state.get(hybrid_result_key(slug)):
            deep = restored
    if (
        deep
        and not is_deep_analysis_error(deep)
        and st.session_state.get(scan_hash_session_key) == pdf_hash
        and hybrid_status not in ("pending", "pending_balance", "preparing", "ready")
    ):
        extraction = (
            st.session_state.get(drawing_extraction_key(slug))
            or (cached or {}).get("drawing_extraction")
        )
        return deep, extraction, "Sinlex AI"
    return None, None, ""


@st.dialog("Результат анализа чертежа", width="large")
def _drawing_analysis_dialog(
    slug: str,
    analysis_text: str,
    extraction: dict | None,
) -> None:
    st.markdown(format_analysis_for_display(analysis_text))
    if extraction:
        render_drawing_pages_caption(extraction)
        render_drawing_layout_debug(extraction)
    if st.button("Закрыть", key=f"dlg_close_drawing_{slug}", use_container_width=True):
        st.rerun()



def _render_potok_launch_button(
    slug: str,
    project_name: str,
    pdf_bytes: bytes,
    pdf_name: str,
    step_data: dict,
    *,
    disabled: bool = False,
) -> None:
    if st.button(
        "Поток",
        key=f"btn_hybrid_{slug}",
        type="secondary",
        use_container_width=True,
        disabled=disabled,
    ):
        _start_hybrid_analysis_ui(slug, project_name, pdf_bytes, pdf_name, step_data)


def _render_post_analysis_action_buttons(
    slug: str,
    analysis_text: str,
    extraction: dict | None,
    *,
    project_name: str,
    saved_pdf: str,
    step_data: dict,
    cached_scan: dict | None = None,
    hybrid_pending: bool = False,
    defer_to_panel: bool = False,
) -> None:
    """«Результат» + «Поток» в одной строке после успешного анализа."""
    if defer_to_panel:
        _queue_panel_drawing_action(
            slug,
            "post_analysis",
            kwargs={
                "slug": slug,
                "analysis_text": analysis_text,
                "extraction": extraction,
                "project_name": project_name,
                "saved_pdf": saved_pdf,
                "step_data": step_data,
                "cached_scan": cached_scan,
                "hybrid_pending": hybrid_pending,
            },
        )
        return
    show_hybrid = hybrid_suffler_ui_enabled() and _hybrid_button_allowed(
        cached_scan or {}, saved_pdf
    )
    _inject_potok_button_styles()
    pdf_bytes = b""
    pdf_name = ""
    if saved_pdf and os.path.isfile(saved_pdf):
        with open(saved_pdf, "rb") as f:
            pdf_bytes = f.read()
        pdf_name = os.path.basename(saved_pdf)

    if show_hybrid:
        col_result, col_flow = st.columns(2)
    else:
        col_result = st.container()
        col_flow = None

    with col_result:
        if st.button(
            "Результат",
            key=f"btn_show_drawing_analysis_{slug}",
            type="secondary",
            use_container_width=True,
        ):
            _drawing_analysis_dialog(slug, analysis_text, extraction)

    if show_hybrid and col_flow is not None:
        with col_flow:
            _render_potok_launch_button(
                slug,
                project_name,
                pdf_bytes,
                pdf_name,
                step_data,
                disabled=hybrid_pending,
            )


def render_drawing_analysis_compact_success(
    slug: str,
    pdf_hash: str,
    scan_hash_session_key: str,
    *,
    cached: dict | None = None,
    log_file: str = "",
    mode_label: str = "",
    project_name: str = "",
    project_dir_for_log: str = "",
    saved_pdf: str = "",
    step_data: dict | None = None,
    cached_scan: dict | None = None,
    hybrid_pending: bool = False,
    defer_to_panel: bool = False,
) -> None:
    """Уведомление об успехе + «Результат» и «Поток» (без inline st.info)."""
    text, extraction, auto_label = resolve_drawing_analysis_text(
        slug,
        pdf_hash,
        scan_hash_session_key,
        cached=cached,
        log_file=log_file,
    )
    if not text:
        return
    if defer_to_panel:
        _render_dop_plain_notice(
            "Чертёж проанализирован. Результат сохранён в проекте.",
            "ok",
        )
    else:
        st.success("Чертёж проанализирован. Результат сохранён в проекте.")
    caption = mode_label or auto_label
    if caption:
        st.caption(caption)
    _render_post_analysis_action_buttons(
        slug,
        text,
        extraction,
        project_name=project_name,
        saved_pdf=saved_pdf,
        step_data=step_data or {},
        cached_scan=cached_scan if cached_scan is not None else cached,
        hybrid_pending=hybrid_pending,
        defer_to_panel=defer_to_panel,
    )



def _panel_drawing_action_key(slug: str) -> str:
    return f"_sinlex_panel_drawing_action_{slug}"


def _queue_panel_drawing_action(slug: str, kind: str, *, kwargs: dict | None = None) -> None:
    st.session_state[_panel_drawing_action_key(slug)] = {
        "kind": kind,
        "kwargs": kwargs or {},
    }


def _submit_order_placement(
    project_name: str,
    slug: str,
    *,
    model_volume,
    dimensions,
    geometry,
) -> None:
    user_email = (st.session_state.get("user_email") or "").strip()
    folder = user_folder()
    if not user_email or st.session_state.get("guest_mode"):
        st.error("Войдите в аккаунт для размещения заказа.")
        return

    from costing_ui import compute_costing_snapshot
    from order_placement import place_manufacturing_order
    from upload_step import WP_ROD, format_model_dims, normalize_wp_type
    from utils import material_prices

    operations = st.session_state.get("operations") or []
    if not operations:
        ot = st.session_state.get("op_type", "Фрезерная")
        operations = [p.strip() for p in str(ot).split(",") if p.strip()] or ["Фрезерная"]

    wp = normalize_wp_type(st.session_state.get("wp", WP_ROD))
    sm = st.session_state.get("mat", "Сталь 45")
    params = {
        "wp": wp,
        "d1": int(st.session_state.get("diam", 85)),
        "l1": int(st.session_state.get("len", 320)),
        "w1": int(st.session_state.get("wid", 100)),
        "h1": int(st.session_state.get("hei", 50)),
        "cph": int(st.session_state.get("cost_h", 3500)),
        "sm": sm,
        "batch_size": int(st.session_state.get("saved_batch_size", 1)),
        "mp": material_prices.get(sm, 0),
    }
    drawing_criteria = resolve_drawing_criteria_for_costing(slug, project_name, folder)
    snap = st.session_state.get(f"_cost_snapshot_{slug}") or compute_costing_snapshot(
        geometry=geometry or {},
        dimensions=dimensions or {},
        operations=operations,
        model_volume=float(model_volume or 0),
        params=params,
        drawing_criteria=drawing_criteria,
    )
    dims_text = format_model_dims(
        dimensions or {},
        st.session_state.get("model_size"),
        operations,
        wp,
    )
    comment = ""
    if isinstance(drawing_criteria, dict):
        comment = (drawing_criteria.get("summary_ru") or "").strip()

    step_bytes = st.session_state.get("cached_step")
    step_filename = st.session_state.get("cached_step_name") or f"{safe_dir_name(project_name)}.stp"

    with st.spinner("Размещение заказа…"):
        try:
            result = place_manufacturing_order(
                project_name=project_name,
                user_folder=folder,
                user_email=user_email,
                material=snap.get("sm") or sm,
                dimensions_text=dims_text,
                batch_size=int(snap.get("batch_size") or params["batch_size"]),
                unit_price=int(snap.get("cpu") or 0),
                total_price=int(snap.get("tc") or 0),
                comment=comment,
                step_bytes=step_bytes,
                step_filename=step_filename,
            )
        except Exception as exc:
            st.error(f"Не удалось разместить заказ: {exc}")
            return

    if result.get("email_ok") and result.get("sheet_ok"):
        st.success(
            "Заказ принят в производство и передан на обработку. "
            "При необходимости мы уточним детали по указанным контактам. "
            "Для выставления счёта с вами свяжется менеджер и согласует реквизиты."
        )
        st.toast("Заказ в производстве", icon="✅")
        if result.get("order_id"):
            st.session_state.my_order_id = result["order_id"]
        col_go, _ = st.columns([1, 3])
        with col_go:
            if st.button("Открыть в «Мои заказы»", key=f"goto_orders_{slug}"):
                st.session_state.page = "orders"
                st.rerun()
    elif result.get("errors"):
        st.warning(
            "Данные заказа сохранены в проекте, но при отправке возникли ошибки: "
            + "; ".join(result["errors"])
        )
    else:
        st.success("Данные заказа сохранены в папке проекта.")


def _render_order_placement_button(
    slug: str,
    *,
    project_name: str,
    has_model: bool = True,
    model_volume=None,
    dimensions=None,
    geometry=None,
) -> None:
    _inject_potok_button_styles()
    if st.button(
        "Размещение заказа",
        key=f"btn_order_placement_{slug}",
        type="secondary",
        use_container_width=True,
        disabled=not has_model,
    ):
        _submit_order_placement(
            project_name,
            slug,
            model_volume=model_volume,
            dimensions=dimensions,
            geometry=geometry,
        )


def _render_panel_drawing_action_row(
    slug: str,
    *,
    project_name: str,
    has_model: bool = True,
    model_volume=None,
    dimensions=None,
    geometry=None,
) -> None:
    """Строка кнопок: слева анализ / поток, справа размещение заказа."""
    action = st.session_state.pop(_panel_drawing_action_key(slug), None)
    col_l, col_r = st.columns(2, gap="large", vertical_alignment="top")
    with col_l:
        if action:
            kind = action.get("kind")
            kwargs = dict(action.get("kwargs") or {})
            if kind == "pre_analysis":
                render_drawing_action_buttons(defer_to_panel=False, **kwargs)
            elif kind == "post_analysis":
                _render_post_analysis_action_buttons(defer_to_panel=False, **kwargs)
    with col_r:
        _render_order_placement_button(
            slug,
            project_name=project_name,
            has_model=has_model,
            model_volume=model_volume,
            dimensions=dimensions,
            geometry=geometry,
        )





def _queue_panel_draw_footer(
    slug: str,
    *,
    show_hint: bool,
    project_dir_for_log: str,
    saved_pdf: str,
    cached: dict | None,
    project_name: str,
    user_folder: str,
) -> None:
    st.session_state[f"_panel_draw_footer_{slug}"] = {
        "show_hint": show_hint,
        "project_dir_for_log": project_dir_for_log,
        "saved_pdf": saved_pdf,
        "cached": cached or {},
        "project_name": project_name,
        "user_folder": user_folder,
    }



def _render_expert_drawing_panel_footer(slug: str, footer: dict) -> None:
    """Подсказка и удаление чертежа — в левой колонке под кнопками анализа."""
    if footer.get("show_hint"):
        _render_drawing_result_hint(
            slug, footer.get("cached") or {}, footer.get("saved_pdf") or ""
        )
    render_delete_drawing_button(
        footer.get("project_dir_for_log") or "",
        footer.get("saved_pdf") or "",
        slug,
        project_name=footer.get("project_name") or "",
        user_folder=footer.get("user_folder") or "",
    )



def render_order_placement_stub(slug: str, *, has_model: bool = True) -> None:
    """Правая колонка: заглушка (кнопка — в общей строке с анализом)."""
    del slug, has_model  # кнопка в _render_panel_drawing_action_row


def render_drawing_action_buttons(
    project_name: str,
    slug: str,
    project_dir_for_log: str,
    saved_pdf: str,
    step_data: dict,
    scan_hash_session_key: str,
    *,
    cached_scan: dict | None = None,
    hybrid_pending: bool = False,
    defer_to_panel: bool = False,
) -> None:
    """Кнопки «Анализировать» и «Углублённый анализ» (HS-3)."""
    if defer_to_panel:
        if os.path.exists(saved_pdf):
            with open(saved_pdf, "rb") as _pdf_f:
                _pdf_hash = hashlib.sha256(_pdf_f.read()).hexdigest()
            if _drawing_analysis_complete_for_ui(
                slug,
                _pdf_hash,
                scan_hash_session_key,
                hybrid_pending=hybrid_pending,
            ):
                return
        _queue_panel_drawing_action(
            slug,
            "pre_analysis",
            kwargs={
                "project_name": project_name,
                "slug": slug,
                "project_dir_for_log": project_dir_for_log,
                "saved_pdf": saved_pdf,
                "step_data": step_data,
                "scan_hash_session_key": scan_hash_session_key,
                "cached_scan": cached_scan,
                "hybrid_pending": hybrid_pending,
            },
        )
        return
    if not os.path.exists(saved_pdf):
        return
    with open(saved_pdf, "rb") as f:
        pdf_bytes = f.read()
    pdf_hash = hashlib.sha256(pdf_bytes).hexdigest()
    if _drawing_analysis_complete_for_ui(
        slug, pdf_hash, scan_hash_session_key, hybrid_pending=hybrid_pending
    ):
        return
    pdf_name = os.path.basename(saved_pdf)
    show_hybrid = hybrid_suffler_ui_enabled() and _hybrid_button_allowed(
        cached_scan or {}, saved_pdf
    )
    _inject_potok_button_styles()
    if show_hybrid and not hybrid_pending:
        col_classic, col_hybrid = st.columns(2)
    else:
        col_classic = st.container()
        col_hybrid = None

    with col_classic:
        if st.button(
            "🔍 Анализировать",
            key=f"btn_scan_pdf_{slug}",
            type="primary",
            use_container_width=True,
            disabled=hybrid_pending,
        ):
            clear_hybrid_session(slug)
            st.session_state.pop(deep_analysis_key(slug), None)
            st.session_state.pop(last_saved_analysis_key(slug), None)
            st.session_state.pop(tech_card_key(slug), None)
            clear_drawing_criteria_session(slug)
            clear_legacy_expert_session()
            try:
                scan_result = process_pdf_scan(
                    pdf_bytes,
                    pdf_name,
                    project_name,
                    project_dir_for_log,
                    step_data,
                    slug=slug,
                )
                if scan_result:
                    st.session_state[scan_hash_session_key] = hashlib.sha256(
                        pdf_bytes
                    ).hexdigest()
                    if scan_result.get("deep_analysis") or st.session_state.get(
                        deep_analysis_key(slug)
                    ):
                        st.rerun()
            except requests.RequestException as e:
                st.error(f"Ошибка соединения: {e}")
            except Exception as e:
                st.error(f"Ошибка: {e}")

    if show_hybrid and col_hybrid is not None:
        with col_hybrid:
            _render_potok_launch_button(
                slug,
                project_name,
                pdf_bytes,
                pdf_name,
                step_data,
                disabled=hybrid_pending,
            )

def render_analyze_drawing_button(
    project_name: str,
    slug: str,
    project_dir_for_log: str,
    saved_pdf: str,
    step_data: dict,
    scan_hash_session_key: str,
) -> None:
    """Кнопка запуска классического анализа (+ гибрид при ENABLE_HYBRID_SUFFLER)."""
    render_drawing_action_buttons(
        project_name,
        slug,
        project_dir_for_log,
        saved_pdf,
        step_data,
        scan_hash_session_key,
    )


def render_hybrid_analysis_result(
    slug: str,
    project_name: str,
    project_dir_for_log: str,
    pdf_bytes: bytes,
    pdf_name: str,
    step_data: dict,
    pdf_hash: str,
    *,
    saved_pdf: str = "",
    defer_to_panel: bool = False,
) -> None:
    """Показ результата гибридного анализа (отдельно от deep_analysis_{slug})."""
    result = st.session_state.get(hybrid_result_key(slug))
    if not result:
        return
    if _hybrid_result_paywalled(result):
        st.warning(
            "Для просмотра результата «Поток» пополните баланс "
            "(кнопка «Баланс» вверху)."
        )
        if st.button("Пополнить баланс", key=f"flow_topup_hybrid_result_{slug}"):
            st.session_state.show_flow_topup_form = True
            st.rerun()
        return
    analysis = (result.get("analysis") or "").strip()
    if not analysis or result.get("status") != "ok":
        msg = (result.get("message") or "").strip()
        if is_llm_unavailable_message(msg):
            show_llm_unavailable_error()
        else:
            st.error(HYBRID_SUFFLER_TIMEOUT_MESSAGE)
        return
    _persist_hybrid_finalize(
        slug,
        project_name,
        project_dir_for_log,
        pdf_bytes,
        pdf_name,
        step_data,
        result,
    )
    render_drawing_analysis_compact_success(
        slug,
        pdf_hash,
        pdf_scan_hash_key(slug),
        mode_label='Режим «Поток»',
        project_name=project_name,
        project_dir_for_log=project_dir_for_log,
        saved_pdf=saved_pdf or os.path.join(project_dir_for_log, pdf_name),
        step_data=step_data,
        cached_scan=st.session_state.get(last_saved_analysis_key(slug)) or {},
        defer_to_panel=defer_to_panel,
    )


def render_tech_card_button(deep: str, log_file: str, step_data: dict, slug: str) -> None:
    """Техкарта: кнопка до генерации, затем только результат."""
    tech_key = tech_card_key(slug)
    quote = (step_data or {}).get("costing_quote") or {}
    existing = st.session_state.get(tech_key)
    if existing:
        st.markdown("### 🛠️ Технологическая карта")
        st.info(finalize_tech_card_text(existing, quote))
        return

    if st.button(
        "🤖 Сформировать техпроцесс",
        use_container_width=True,
        key=f"btn_tech_card_{slug}",
        type="primary",
    ):
        with st.spinner("Формирую техпроцесс..."):
            log_entries = []
            if os.path.exists(log_file):
                with open(log_file, "r", encoding="utf-8") as f:
                    for line in f:
                        try:
                            log_entries.append(json.loads(line.strip()))
                        except Exception:
                            pass
            resp_tech = requests.post(
                f"{NGROK_URL}/tech-card",
                data={
                    "analysis_text": deep,
                    "step_data": json.dumps(step_data, ensure_ascii=False),
                    "log_data": json.dumps(log_entries, ensure_ascii=False),
                },
                headers=get_headers(),
                timeout=120,
            )
            if resp_tech.status_code == 200:
                tech_result = resp_tech.json()
                if tech_result.get("status") == "ok":
                    st.session_state[tech_key] = finalize_tech_card_text(
                        tech_result["analysis"],
                        quote,
                    )
                    st.rerun()
                else:
                    msg = tech_result.get("message", "неизвестная")
                    if is_llm_unavailable_message(msg):
                        show_llm_unavailable_error()
                    else:
                        st.error(f"Ошибка: {msg}")
            else:
                st.error(f"Ошибка соединения: {resp_tech.status_code}")


def render_expert_analysis_section(
    project_name: str,
    slug: str,
    model_volume,
    dimensions,
    geometry,
    quote=None,
    *,
    panel_mode: bool = False,
) -> None:
    """Результаты экспертного анализа (левая колонка блока чертёж/заказ)."""
    defer = panel_mode
    if panel_mode:
        st.session_state.pop(_panel_drawing_action_key(slug), None)
    folder = st.session_state.get("user_folder", "")
    base_dir = os.path.join("/opt/sinlex/projects", folder) if folder else "/opt/sinlex/projects"
    project_dir_for_log, saved_pdf = resolve_pdf_paths(base_dir, project_name)
    step_data = expert_step_data(project_name, folder, model_volume, dimensions, geometry)
    if quote:
        step_data = {**step_data, "costing_quote": quote}
    scan_hash_key = pdf_scan_hash_key(slug)

    if not os.path.exists(saved_pdf):
        if panel_mode:
            _render_dop_plain_notice(
                "Загрузите чертёж вверху (справа от STEP), затем нажмите «Анализировать».",
                "info",
            )
        else:
            st.info(
                "Загрузите чертёж **вверху** (справа от STEP), затем нажмите **«Анализировать»**."
            )
        return

    with open(saved_pdf, "rb") as f:
        pdf_bytes = f.read()
    pdf_name = os.path.basename(saved_pdf)
    pdf_hash = hashlib.sha256(pdf_bytes).hexdigest()
    log_file = os.path.join(project_dir_for_log, "analysis_log.jsonl")
    cached = st.session_state.get(last_saved_analysis_key(slug)) or {}
    if st.session_state.get(scan_hash_key) == pdf_hash and cached:
        render_pdf_scan_status_banner(cached, plain=panel_mode)

    if st.session_state.pop("flow_pending_unlock_after_topup", False):
        _try_unlock_flow_pending_hybrid(slug, project_name, step_data)

    restore_hybrid_session_from_persisted(
        slug, project_name, folder, pdf_hash, log_file
    )

    hybrid_status = st.session_state.get(hybrid_status_key(slug), "idle")

    if hybrid_status in ("pending", "pending_balance", "preparing"):
        if panel_mode:
            st.markdown(f"_{_hybrid_spinner_label(slug, hybrid_status)}_")
        else:
            st.status(_hybrid_spinner_label(slug, hybrid_status), expanded=True)
        _hybrid_poll_fragment(slug, project_name, step_data, pdf_hash)
        render_drawing_action_buttons(
            project_name,
            slug,
            project_dir_for_log,
            saved_pdf,
            step_data,
            scan_hash_key,
            cached_scan=cached,
            hybrid_pending=True, defer_to_panel=defer)
        if defer:
            _queue_panel_draw_footer(
                slug,
                show_hint=False,
                project_dir_for_log=project_dir_for_log,
                saved_pdf=saved_pdf,
                cached=cached,
                project_name=project_name,
                user_folder=folder,
            )
            return
        render_delete_drawing_button(
            project_dir_for_log,
            saved_pdf,
            slug,
            project_name=project_name,
            user_folder=folder,
        )
        return

    if hybrid_status == "pending_payment":
        if _try_unlock_flow_pending_hybrid(slug, project_name, step_data):
            st.rerun()
        meta = st.session_state.get(hybrid_pending_meta_key(slug)) or {}
        msg = meta.get("ui_message") or (
            f"Нужно **{meta.get('rub_required') or meta.get('tokens_required', '?')}** ₽, на счёте **{meta.get('balance', 0)}** ₽."
        )
        st.warning(msg)
        col_top_a, col_top_b = st.columns(2)
        with col_top_a:
            if st.button("Показать результат", key=f"flow_unlock_{slug}", type="primary"):
                if _try_unlock_flow_pending_hybrid(slug, project_name, step_data):
                    st.rerun()
                else:
                    st.error("Не удалось разблокировать. Проверьте баланс и обновите страницу.")
        with col_top_b:
            if st.button("Пополнить баланс", key=f"flow_topup_from_upload_{slug}"):
                st.session_state.show_flow_topup_form = True
                st.rerun()
        render_drawing_action_buttons(
            project_name,
            slug,
            project_dir_for_log,
            saved_pdf,
            step_data,
            scan_hash_key,
            cached_scan=cached, defer_to_panel=defer)
        if defer:
            _queue_panel_draw_footer(
                slug,
                show_hint=False,
                project_dir_for_log=project_dir_for_log,
                saved_pdf=saved_pdf,
                cached=cached,
                project_name=project_name,
                user_folder=folder,
            )
            return
        render_delete_drawing_button(
            project_dir_for_log,
            saved_pdf,
            slug,
            project_name=project_name,
            user_folder=folder,
        )
        return

    if hybrid_status in ("timeout", "error"):
        show_hybrid_failure(slug, hybrid_status)
        clear_hybrid_session(slug)
        st.session_state[hybrid_status_key(slug)] = "idle"
        render_drawing_action_buttons(
            project_name,
            slug,
            project_dir_for_log,
            saved_pdf,
            step_data,
            scan_hash_key,
            cached_scan=cached, defer_to_panel=defer)
        if defer:
            _queue_panel_draw_footer(
                slug,
                show_hint=False,
                project_dir_for_log=project_dir_for_log,
                saved_pdf=saved_pdf,
                cached=cached,
                project_name=project_name,
                user_folder=folder,
            )
            return
        render_delete_drawing_button(
            project_dir_for_log,
            saved_pdf,
            slug,
            project_name=project_name,
            user_folder=folder,
        )
        return

    if hybrid_status in ("ready", "done"):
        result = st.session_state.get(hybrid_result_key(slug))
        if not result:
            task_id = st.session_state.get(hybrid_task_id_key(slug))
            result = _fetch_hybrid_finalize_result(task_id, project_name, step_data)
            if result:
                st.session_state[hybrid_result_key(slug)] = result
        if result and result.get("status") == "pending_payment":
            st.session_state[hybrid_status_key(slug)] = "pending_payment"
            st.session_state[hybrid_pending_meta_key(slug)] = result
            st.warning(result.get("ui_message") or "Недостаточно средств на балансе для просмотра.")
            if st.button("Пополнить баланс", key=f"flow_topup_ready_{slug}"):
                st.session_state.show_flow_topup_form = True
                st.rerun()
            render_drawing_action_buttons(
                project_name,
                slug,
                project_dir_for_log,
                saved_pdf,
                step_data,
                scan_hash_key,
                cached_scan=cached, defer_to_panel=defer)
            if defer:
                _queue_panel_draw_footer(
                    slug,
                    show_hint=False,
                    project_dir_for_log=project_dir_for_log,
                    saved_pdf=saved_pdf,
                    cached=cached,
                    project_name=project_name,
                    user_folder=folder,
                )
                return
            render_delete_drawing_button(
                project_dir_for_log,
                saved_pdf,
                slug,
                project_name=project_name,
                user_folder=folder,
            )
            return
        if result and _hybrid_result_paywalled(result):
            st.warning(
                "Для просмотра результата «Поток» пополните баланс "
                "(кнопка «Баланс» вверху)."
            )
            if st.button("Пополнить баланс", key=f"flow_topup_paywall_{slug}"):
                st.session_state.show_flow_topup_form = True
                st.rerun()
            render_drawing_action_buttons(
                project_name,
                slug,
                project_dir_for_log,
                saved_pdf,
                step_data,
                scan_hash_key,
                cached_scan=cached, defer_to_panel=defer)
            if defer:
                _queue_panel_draw_footer(
                    slug,
                    show_hint=False,
                    project_dir_for_log=project_dir_for_log,
                    saved_pdf=saved_pdf,
                    cached=cached,
                    project_name=project_name,
                    user_folder=folder,
                )
                return
            render_delete_drawing_button(
                project_dir_for_log,
                saved_pdf,
                slug,
                project_name=project_name,
                user_folder=folder,
            )
            return
        if result and not _hybrid_result_paywalled(result):
            st.session_state[pdf_scan_hash_key(slug)] = pdf_hash
            st.session_state[hybrid_status_key(slug)] = "done"
            render_hybrid_analysis_result(
                slug,
                project_name,
                project_dir_for_log,
                pdf_bytes,
                pdf_name,
                step_data,
                pdf_hash,
                saved_pdf=saved_pdf,
                defer_to_panel=defer,
            )
            render_drawing_action_buttons(
                project_name,
                slug,
                project_dir_for_log,
                saved_pdf,
                step_data,
                scan_hash_key,
                cached_scan=cached, defer_to_panel=defer)
            if defer:
                _queue_panel_draw_footer(
                    slug,
                    show_hint=False,
                    project_dir_for_log=project_dir_for_log,
                    saved_pdf=saved_pdf,
                    cached=cached,
                    project_name=project_name,
                    user_folder=folder,
                )
                return
            render_delete_drawing_button(
                project_dir_for_log,
                saved_pdf,
                slug,
                project_name=project_name,
                user_folder=folder,
            )
            return
        if hybrid_status == "ready":
            st.warning(
                "Углублённый анализ завершён, но текст не загрузился. "
                "Обновите страницу или нажмите «Поток» ещё раз."
            )

    deep = st.session_state.get(deep_analysis_key(slug))
    if not deep or is_deep_analysis_error(deep):
        restored = load_deep_analysis_from_log(log_file, pdf_hash)
        if restored and not st.session_state.get(hybrid_result_key(slug)):
            deep = restored
            st.session_state[deep_analysis_key(slug)] = deep
            st.session_state[scan_hash_key] = pdf_hash
            if not st.session_state.get(drawing_criteria_key(slug)):
                try:
                    from project_store import load_project_data

                    pdata = load_project_data(project_name, folder) or {}
                    restore_drawing_artifacts_to_session(pdata, slug)
                except Exception:
                    pass

    has_classic_analysis = (
        bool(deep)
        and not is_deep_analysis_error(deep)
        and st.session_state.get(scan_hash_key) == pdf_hash
        and hybrid_status != "ready"
    )

    if has_classic_analysis:
        render_drawing_analysis_compact_success(
            slug,
            pdf_hash,
            scan_hash_key,
            cached=cached,
            log_file=log_file,
            project_name=project_name,
            project_dir_for_log=project_dir_for_log,
            saved_pdf=saved_pdf,
            step_data=step_data,
            cached_scan=cached,
            defer_to_panel=defer,
        )
    elif deep and is_deep_analysis_error(deep):
        show_analysis_error(deep)
        st.caption("Повторите анализ или загрузите другой чертёж.")

    if not has_classic_analysis:
        render_drawing_action_buttons(
            project_name,
            slug,
            project_dir_for_log,
            saved_pdf,
            step_data,
            scan_hash_key,
            cached_scan=cached,
            defer_to_panel=defer,
        )

    if defer:
        _queue_panel_draw_footer(
            slug,
            show_hint=not has_classic_analysis
            and not (deep and is_deep_analysis_error(deep)),
            project_dir_for_log=project_dir_for_log,
            saved_pdf=saved_pdf,
            cached=cached,
            project_name=project_name,
            user_folder=folder,
        )
        return

    if not has_classic_analysis and not (deep and is_deep_analysis_error(deep)):
        _render_drawing_result_hint(slug, cached, saved_pdf)

    render_delete_drawing_button(
        project_dir_for_log,
        saved_pdf,
        slug,
        project_name=project_name,
        user_folder=folder,
    )



def render_project_drawing_order_panel(
    project_name: str,
    slug: str,
    model_volume,
    dimensions,
    geometry,
    quote=None,
) -> None:
    """Две колонки: анализ чертежа | размещение заказа (3D-проект)."""
    _inject_drawing_order_panel_styles()
    st.markdown(
        '<div id="sinlex-drawing-order-panel"></div>',
        unsafe_allow_html=True,
    )
    st.markdown("### Работа с чертежом и заказом")
    hdr_draw, hdr_order = st.columns(2, gap="large", vertical_alignment="top")
    with hdr_draw:
        st.markdown("#### Анализ чертежа")
    with hdr_order:
        st.markdown("#### Размещение заказа")

    col_draw, col_order = st.columns(2, gap="large", vertical_alignment="top")
    with col_draw:
        render_expert_analysis_section(
            project_name,
            slug,
            model_volume,
            dimensions,
            geometry,
            quote=quote,
            panel_mode=True,
        )
    with col_order:
        st.caption(_DRAWING_ORDER_CAPTION)

    _render_panel_drawing_action_row(
        slug,
        project_name=project_name,
        has_model=True,
        model_volume=model_volume,
        dimensions=dimensions,
        geometry=geometry,
    )
    footer = st.session_state.pop(f"_panel_draw_footer_{slug}", None)
    if footer:
        ftr_draw, _ftr = st.columns(2, gap="large", vertical_alignment="top")
        with ftr_draw:
            _render_expert_drawing_panel_footer(slug, footer)



def render_tech_card_section(
    project_name: str,
    slug: str,
    model_volume,
    dimensions,
    geometry,
    quote: dict,
) -> None:
    """Технологическая карта — ниже блока стоимости (UI-0 TZ)."""
    folder = st.session_state.get("user_folder", "")
    base_dir = os.path.join("/opt/sinlex/projects", folder) if folder else "/opt/sinlex/projects"
    project_dir_for_log, _saved_pdf = resolve_pdf_paths(base_dir, project_name)
    log_file = os.path.join(project_dir_for_log, "analysis_log.jsonl")
    step_data = expert_step_data(project_name, folder, model_volume, dimensions, geometry)
    if quote:
        step_data = {**step_data, "costing_quote": quote}

    deep = st.session_state.get(deep_analysis_key(slug))
    if not deep or is_deep_analysis_error(deep):
        hybrid = st.session_state.get(hybrid_result_key(slug)) or {}
        deep = (hybrid.get("analysis") or "").strip()
    if not deep or is_deep_analysis_error(deep):
        st.markdown("### 🛠️ Технологическая карта")
        st.caption("Выполните **анализ чертежа** выше — затем можно сформировать техкарту.")
        return

    render_tech_card_button(deep, log_file, step_data, slug)
