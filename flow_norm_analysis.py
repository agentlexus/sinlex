"""
Оркестрация нормировки «Поток» (2D, отдельная страница).

Job-файлы: {project_dir}/flow_norm_jobs/{task_id}.json
Канал: flow_norm_logistics (отдельное email-состояние).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from flow_drawing_io import (
    FLOW_DRAWING_EXTENSIONS,
    extract_text_from_drawing,
    safe_drawing_filename,
)
from flow_norm_logistics import MaxSufflerError, get_flow_norm_channel
from hybrid_analysis import HybridJobError

LOG = logging.getLogger("flow_norm_analysis")

_INSUFFICIENT_TOKENS_UI = "Недостаточно средств на балансе «Поток». Пополните баланс."


def _load_secrets() -> Dict[str, str]:
    out: Dict[str, str] = {}
    path = os.environ.get("SINLEX_SECRETS_FILE", "/opt/sinlex/secrets.env")
    if not os.path.isfile(path):
        return out
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip().strip('"').strip("'")
    except OSError:
        pass
    return out


_SECRETS = _load_secrets()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _timeout_seconds() -> int:
    raw = (
        os.environ.get("SUFFLER_TIMEOUT_SECONDS")
        or _SECRETS.get("SUFFLER_TIMEOUT_SECONDS")
        or "3600"
    )
    try:
        return max(60, int(str(raw).strip()))
    except (TypeError, ValueError):
        return 3600


def _project_dir(project_name: str, user_folder: str = "") -> str:
    from project_store import _safe_dir_name, projects_base_dir

    safe = _safe_dir_name(project_name)
    return os.path.join(projects_base_dir(user_folder), safe)


def flow_norm_jobs_dir(project_name: str, user_folder: str = "") -> Path:
    override = (
        os.environ.get("FLOW_NORM_JOB_DIR", "").strip()
        or _SECRETS.get("FLOW_NORM_JOB_DIR", "").strip()
    )
    if override:
        base = Path(override.format(project=_project_dir(project_name, user_folder)))
    else:
        base = Path(_project_dir(project_name, user_folder)) / "flow_norm_jobs"
    base.mkdir(parents=True, exist_ok=True)
    return base


def job_file_path(project_name: str, user_folder: str, task_id: str) -> Path:
    return flow_norm_jobs_dir(project_name, user_folder) / f"{task_id}.json"


def load_job(project_name: str, user_folder: str, task_id: str) -> Dict[str, Any]:
    path = job_file_path(project_name, user_folder, task_id)
    if not path.is_file():
        raise FileNotFoundError(task_id)
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("invalid job")
    return data


def save_job(job: Dict[str, Any]) -> None:
    task_id = (job.get("task_id") or "").strip()
    project_name = job.get("project_name") or ""
    user_folder = job.get("user_folder") or ""
    if not task_id or not project_name:
        raise ValueError("job missing task_id or project_name")
    path = job_file_path(project_name, user_folder, task_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _cancel_pending_jobs(project_name: str, user_folder: str, except_task_id: str = "") -> None:
    jobs_dir = flow_norm_jobs_dir(project_name, user_folder)
    for path in jobs_dir.glob("*.json"):
        try:
            with open(path, encoding="utf-8") as f:
                job = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        if job.get("status") not in ("pending", "pending_balance"):
            continue
        tid = (job.get("task_id") or "").strip()
        if except_task_id and tid == except_task_id:
            continue
        job["status"] = "cancelled"
        job["error_message"] = "superseded"
        save_job(job)


def _deadline_iso(seconds: int) -> str:
    dt = datetime.now(timezone.utc) + timedelta(seconds=seconds)
    return dt.isoformat()


def _is_past_deadline(job: Dict[str, Any]) -> bool:
    raw = (job.get("deadline_at") or "").strip()
    if not raw:
        return False
    try:
        deadline = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) >= deadline
    except ValueError:
        return False


def job_to_public(job: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "task_id": job.get("task_id"),
        "project_name": job.get("project_name"),
        "user_folder": job.get("user_folder"),
        "pdf_hash": job.get("pdf_hash"),
        "status": job.get("status"),
        "created_at": job.get("created_at"),
        "deadline_at": job.get("deadline_at"),
        "channel_task_id": job.get("channel_task_id"),
        "suffler_text": job.get("suffler_text"),
        "suffler_parsed": job.get("suffler_parsed"),
        "auto_ready": bool(job.get("auto_extraction")),
        "error_ui": job.get("error_ui"),
        "flow_tokens_charged": job.get("flow_tokens_charged"),
        "flow_rub_charged": job.get("flow_rub_charged"),
        "flow_balance_after_debit": job.get("flow_balance_after_debit"),
        "balance_inquiry_sent_at": job.get("balance_inquiry_sent_at"),
        "flow_mode": "norm_hours_2d",
    }


def _advance_after_balance_inquiry(
    job: Dict[str, Any],
    project_name: str,
    user_folder: str,
    task_id: str,
) -> Dict[str, Any]:
    channel_id = (job.get("channel_task_id") or job.get("task_id") or "").strip()
    try:
        bot = get_flow_norm_channel()
    except MaxSufflerError as exc:
        job["status"] = "error"
        job["error_message"] = exc.code
        job["error_ui"] = exc.ui_message
        save_job(job)
        return job

    try:
        tokens_raw = bot.check_balance_response(channel_id)
    except MaxSufflerError as exc:
        job["status"] = "error"
        job["error_message"] = exc.code
        job["error_ui"] = exc.ui_message
        save_job(job)
        return job

    if tokens_raw is None:
        return job

    rub_to_charge = int(tokens_raw)
    if rub_to_charge <= 0:
        job["status"] = "error"
        job["error_message"] = "insufficient_tokens"
        job["error_ui"] = _INSUFFICIENT_TOKENS_UI
        save_job(job)
        return job

    user_email = (job.get("user_email") or "").strip()
    if not user_email:
        job["status"] = "error"
        job["error_message"] = "no_user_email"
        job["error_ui"] = _INSUFFICIENT_TOKENS_UI
        save_job(job)
        return job

    import payment as pay

    debit = pay.debit_flow_tokens(
        user_email,
        rub_to_charge,
        source="flow_norm_2d",
        project=project_name,
        task_id=task_id,
    )
    if debit.get("ok") is False:
        job["status"] = "error"
        job["error_message"] = "insufficient_tokens"
        job["error_ui"] = _INSUFFICIENT_TOKENS_UI
        save_job(job)
        return job

    job["flow_rub_charged"] = rub_to_charge
    job["flow_tokens_charged"] = rub_to_charge
    job["flow_balance_after_debit"] = debit.get("balance")

    try:
        bot.begin_suffler_watch(
            task_id,
            project_name,
            user_folder=user_folder,
        )
    except MaxSufflerError as exc:
        job["status"] = "error"
        job["error_message"] = exc.code
        job["error_ui"] = exc.ui_message
        save_job(job)
        return job
    except AttributeError:
        LOG.exception("flow_norm channel missing begin_suffler_watch task_id=%s", task_id)
        job["status"] = "error"
        job["error_message"] = "flow_norm_channel"
        job["error_ui"] = "Нормировка временно недоступна. Попробуйте позже."
        save_job(job)
        return job

    st = bot._load_state()
    meta = (st.get("inquiry_meta") or {}).get(channel_id) or {}
    job["thread_message_id"] = meta.get("message_id") or job.get("thread_message_id") or ""
    job["status"] = "pending"
    job["channel"] = "flow_norm_email"
    job["drawing_sent_at"] = job.get("balance_inquiry_sent_at") or _now_iso()
    save_job(job)
    return job


def refresh_job_status(project_name: str, user_folder: str, task_id: str) -> Dict[str, Any]:
    job = load_job(project_name, user_folder, task_id)
    status = job.get("status")

    if status in ("ready", "timeout", "error", "cancelled"):
        return job

    if _is_past_deadline(job) and status in ("pending", "pending_balance"):
        job["status"] = "timeout"
        job["suffler_text"] = None
        save_job(job)
        return job

    if status == "pending_balance":
        return _advance_after_balance_inquiry(job, project_name, user_folder, task_id)

    if status != "pending":
        return job

    channel_id = (job.get("channel_task_id") or job.get("task_id") or "").strip()
    try:
        bot = get_flow_norm_channel()
    except MaxSufflerError as exc:
        job["status"] = "error"
        job["error_message"] = exc.code
        job["error_ui"] = exc.ui_message
        save_job(job)
        return job

    try:
        text = bot.check_response(channel_id)
    except MaxSufflerError as exc:
        job["status"] = "error"
        job["error_message"] = exc.code
        job["error_ui"] = exc.ui_message
        save_job(job)
        return job

    if text:
        job["suffler_text"] = text
        job["suffler_parsed"] = bot.parse_response(text)
        job["status"] = "ready"
        save_job(job)
    return job


def run_start_background(
    task_id: str,
    project_name: str,
    user_folder: str,
    drawing_bytes: bytes,
    norm_inputs: Dict[str, Any],
    drawing_filename: str = "drawing.pdf",
) -> None:
    try:
        job = load_job(project_name, user_folder, task_id)
    except (FileNotFoundError, ValueError):
        LOG.error("flow_norm job missing task_id=%s", task_id)
        return

    if job.get("status") == "cancelled":
        return

    try:
        extraction = extract_text_from_drawing(drawing_bytes, drawing_filename)
        job["auto_extraction"] = extraction
        save_job(job)
    except Exception:
        LOG.exception("flow_norm auto extraction failed task_id=%s", task_id)
        job["status"] = "error"
        job["error_message"] = "auto_extraction"
        job["error_ui"] = "Нормировка временно недоступна. Попробуйте позже."
        save_job(job)
        return

    try:
        job = load_job(project_name, user_folder, task_id)
        if job.get("status") == "cancelled":
            return
        user_email = (job.get("user_email") or "").strip()
        import payment as pay

        balance = pay.get_flow_token_balance(user_email) if user_email else 0
        channel = get_flow_norm_channel()
        channel.send_balance_inquiry(
            project_name,
            task_id,
            pdf_bytes=drawing_bytes,
            user_balance=balance,
            user_email=user_email,
            user_folder=user_folder,
        )
        job = load_job(project_name, user_folder, task_id)
        if job.get("status") == "cancelled":
            return
        job["status"] = "pending_balance"
        job["balance_inquiry_sent_at"] = _now_iso()
        job["channel_task_id"] = task_id
        job["norm_inputs_snapshot"] = dict(norm_inputs or {})
        save_job(job)
    except MaxSufflerError as exc:
        job = load_job(project_name, user_folder, task_id)
        job["status"] = "error"
        job["error_message"] = exc.code
        job["error_ui"] = exc.ui_message
        save_job(job)
    except Exception:
        LOG.exception("flow_norm send failed task_id=%s", task_id)
        job = load_job(project_name, user_folder, task_id)
        job["status"] = "error"
        job["error_message"] = "flow_norm_channel"
        job["error_ui"] = "Нормировка временно недоступна. Попробуйте позже."
        save_job(job)


def start_flow_norm_analysis(
    drawing_bytes: bytes,
    norm_inputs: Dict[str, Any],
    project_name: str,
    user_folder: str = "",
    user_email: str = "",
    drawing_filename: str = "",
) -> Dict[str, Any]:
    if not drawing_bytes:
        raise ValueError("Файл чертежа не передан")
    if not (project_name or "").strip():
        raise ValueError("Не указан проект")

    task_id = str(uuid.uuid4())
    _cancel_pending_jobs(project_name, user_folder, except_task_id=task_id)

    fname = safe_drawing_filename(drawing_filename or "drawing.pdf")
    ext = os.path.splitext(fname)[1].lower()
    if ext not in FLOW_DRAWING_EXTENSIONS:
        raise ValueError("Допустимы PDF, PNG, JPG, JPEG")
    pdf_hash = hashlib.sha256(drawing_bytes).hexdigest()
    pdir = _project_dir(project_name, user_folder)
    os.makedirs(pdir, exist_ok=True)
    from project_store import _safe_dir_name

    pdf_path = os.path.join(pdir, fname)
    with open(pdf_path, "wb") as f:
        f.write(drawing_bytes)

    timeout = _timeout_seconds()
    job: Dict[str, Any] = {
        "task_id": task_id,
        "project_name": project_name,
        "user_folder": user_folder,
        "pdf_hash": pdf_hash,
        "drawing_hash": pdf_hash,
        "pdf_path": pdf_path,
        "drawing_path": pdf_path,
        "drawing_filename": fname,
        "status": "pending_balance",
        "created_at": _now_iso(),
        "deadline_at": _deadline_iso(timeout),
        "channel_task_id": task_id,
        "channel": "flow_norm_email",
        "auto_extraction": None,
        "suffler_text": None,
        "suffler_parsed": None,
        "error_message": "",
        "error_ui": None,
        "norm_inputs_snapshot": dict(norm_inputs or {}),
        "user_email": (user_email or "").strip(),
        "flow_mode": "norm_hours_2d",
    }
    save_job(job)
    return {"task_id": task_id, "status": "pending_balance", "deadline_at": job["deadline_at"]}
