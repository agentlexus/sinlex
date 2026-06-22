"""
Оркестрация гибридного углублённого анализа (этап HS-2).

Job-файлы: {project_dir}/hybrid_jobs/{task_id}.json
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

from drawing_analysis.reader import extract_text_from_pdf
from email_logistics import MaxSufflerError, get_hybrid_channel
from email_logistics.config import resolve_active_channel

LOG = logging.getLogger("hybrid_analysis")

_JOB_STATUSES = frozenset({"pending_balance", "pending", "ready", "timeout", "error", "cancelled"})


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


def hybrid_jobs_dir(project_name: str, user_folder: str = "") -> Path:
    override = (
        os.environ.get("HYBRID_JOB_DIR", "").strip()
        or _SECRETS.get("HYBRID_JOB_DIR", "").strip()
    )
    if override:
        base = Path(override.format(project=_project_dir(project_name, user_folder)))
    else:
        base = Path(_project_dir(project_name, user_folder)) / "hybrid_jobs"
    base.mkdir(parents=True, exist_ok=True)
    return base


def job_file_path(project_name: str, user_folder: str, task_id: str) -> Path:
    return hybrid_jobs_dir(project_name, user_folder) / f"{task_id}.json"


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


def apply_released_pending_to_job(
    project_name: str,
    user_folder: str,
    task_id: str,
    result_payload: dict,
    *,
    tokens_debited: int = 0,
) -> None:
    """После release: сохранить готовый анализ в job (без повторного LLM)."""
    try:
        job = load_job(project_name, user_folder, task_id)
    except FileNotFoundError:
        return
    final = dict(result_payload or {})
    final["status"] = "ok"
    if tokens_debited:
        final["tokens_debited"] = int(tokens_debited)
    job["finalize_result"] = final
    job["finalize_status"] = "ok"
    job["finalized_at"] = _now_iso()
    save_job(job)


def _cancel_pending_jobs(project_name: str, user_folder: str, except_task_id: str = "") -> None:
    jobs_dir = hybrid_jobs_dir(project_name, user_folder)
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
    """Поля job для API/UI без внутренних деталей канала."""
    out = {
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
        "balance_inquiry_sent_at": job.get("balance_inquiry_sent_at"),
    }
    if job.get("status") == "ready" and job.get("auto_extraction"):
        out["auto_extraction"] = job.get("auto_extraction")
    return out



def iter_hybrid_jobs(project_name: str, user_folder: str = ""):
    """Все job-файлы проекта (новые первыми по created_at)."""
    jobs_dir = hybrid_jobs_dir(project_name, user_folder)
    items: list[tuple[str, dict]] = []
    for path in jobs_dir.glob("*.json"):
        try:
            with open(path, encoding="utf-8") as f:
                job = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(job, dict):
            items.append((job.get("created_at") or "", job))
    items.sort(key=lambda x: x[0], reverse=True)
    for _, job in items:
        yield job




def purge_hybrid_jobs(
    project_name: str,
    user_folder: str = "",
    *,
    pdf_hash: str = "",
) -> int:
    """Удалить сохранённые job «Поток» при удалении/замене чертежа."""
    project_name = (project_name or "").strip()
    if not project_name:
        return 0
    pdf_hash = (pdf_hash or "").strip()
    jobs_dir = hybrid_jobs_dir(project_name, user_folder)
    removed = 0
    for path in list(jobs_dir.glob("*.json")):
        try:
            with open(path, encoding="utf-8") as f:
                job = json.load(f)
        except (OSError, json.JSONDecodeError):
            try:
                path.unlink(missing_ok=True)
                removed += 1
            except OSError:
                pass
            continue
        if not isinstance(job, dict):
            continue
        if pdf_hash and (job.get("pdf_hash") or "").strip() != pdf_hash:
            continue
        try:
            path.unlink()
            removed += 1
        except OSError:
            job["status"] = "cancelled"
            job["error_message"] = "drawing_removed"
            job["purged_at"] = _now_iso()
            save_job(job)
            removed += 1
    return removed


def find_latest_hybrid_job(
    project_name: str,
    user_folder: str = "",
    *,
    pdf_hash: str = "",
) -> Dict[str, Any] | None:
    """Последний job «Поток» для чертежа (по created_at)."""
    pdf_hash = (pdf_hash or "").strip()
    for job in iter_hybrid_jobs(project_name, user_folder):
        if pdf_hash and (job.get("pdf_hash") or "").strip() != pdf_hash:
            continue
        if job.get("status") == "cancelled":
            continue
        if job.get("purged_at"):
            continue
        if (job.get("error_message") or "").strip() == "drawing_removed":
            continue
        return job
    return None


def hybrid_finalize_result_from_job(job: Dict[str, Any]) -> Dict[str, Any] | None:
    """Готовый результат анализа из сохранённого job (без повторного LLM)."""
    fin = job.get("finalize_result")
    if isinstance(fin, dict):
        analysis = (fin.get("analysis") or "").strip()
        if analysis and fin.get("status") in (None, "ok"):
            out = dict(fin)
            out.setdefault("status", "ok")
            out.setdefault("hybrid_task_id", job.get("task_id"))
            if not out.get("drawing_extraction") and job.get("auto_extraction"):
                out["drawing_extraction"] = job["auto_extraction"]
            return out
    return None


def hybrid_session_restore_plan(job: Dict[str, Any]) -> Dict[str, Any] | None:
    """План восстановления UI-сессии по job на диске."""
    task_id = (job.get("task_id") or "").strip()
    if not task_id:
        return None
    status = (job.get("status") or "").strip()
    fin = hybrid_finalize_result_from_job(job)
    if fin:
        return {
            "task_id": task_id,
            "ui_status": "done",
            "result": fin,
            "rub_charged": job.get("flow_rub_charged") or job.get("flow_tokens_charged"),
        }
    if status in ("pending_balance", "pending"):
        return {
            "task_id": task_id,
            "ui_status": status,
            "rub_charged": job.get("flow_rub_charged") or job.get("flow_tokens_charged"),
        }
    if status == "ready":
        return {
            "task_id": task_id,
            "ui_status": "preparing",
            "rub_charged": job.get("flow_rub_charged") or job.get("flow_tokens_charged"),
        }
    if status == "error":
        return {
            "task_id": task_id,
            "ui_status": "error",
            "error_ui": job.get("error_ui") or "Анализ временно недоступен.",
        }
    if status == "timeout":
        return {
            "task_id": task_id,
            "ui_status": "timeout",
            "error_ui": job.get("error_ui") or "Анализ временно недоступен, попробуйте позже",
        }
    return None



_INSUFFICIENT_TOKENS_UI = "Недостаточно средств на балансе «Поток». Пополните баланс."


def _advance_after_balance_inquiry(
    job: Dict[str, Any],
    project_name: str,
    user_folder: str,
    task_id: str,
) -> Dict[str, Any]:
    """Ответ на служебное письмо: списание токенов, ожидание суфлёра (чертёж уже в письме)."""
    channel_id = (job.get("channel_task_id") or job.get("task_id") or "").strip()
    try:
        bot = get_hybrid_channel()
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
        source="flow_analysis",
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
        LOG.exception("channel missing begin_suffler_watch task_id=%s", task_id)
        job["status"] = "error"
        job["error_message"] = "hybrid_channel"
        job["error_ui"] = "Углублённый анализ временно недоступен. Попробуйте позже."
        save_job(job)
        return job

    job["status"] = "pending"
    job["channel"] = resolve_active_channel()
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
        bot = get_hybrid_channel()
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
    pdf_bytes: bytes,
    step_data: Dict[str, Any],
) -> None:
    """Фон: автоматика чертежа + отправка PDF во внешний канал (email / Max)."""
    try:
        job = load_job(project_name, user_folder, task_id)
    except (FileNotFoundError, ValueError):
        LOG.error("hybrid job missing task_id=%s", task_id)
        return

    if job.get("status") == "cancelled":
        return

    try:
        extraction = extract_text_from_pdf(pdf_bytes)
        job["auto_extraction"] = extraction
        save_job(job)
    except Exception as exc:
        LOG.exception("hybrid auto extraction failed task_id=%s", task_id)
        job["status"] = "error"
        job["error_message"] = "auto_extraction"
        job["error_ui"] = "Углублённый анализ временно недоступен. Попробуйте позже."
        save_job(job)
        return

    try:
        job = load_job(project_name, user_folder, task_id)
        if job.get("status") == "cancelled":
            return
        user_email = (job.get("user_email") or "").strip()
        import payment as pay

        balance = pay.get_flow_token_balance(user_email) if user_email else 0
        channel = get_hybrid_channel()
        channel.send_balance_inquiry(
            project_name,
            task_id,
            pdf_bytes=pdf_bytes,
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
        save_job(job)
        from ops_notify import notify_flow_activated

        notify_flow_activated(user_email)
    except MaxSufflerError as exc:
        job = load_job(project_name, user_folder, task_id)
        job["status"] = "error"
        job["error_message"] = exc.code
        job["error_ui"] = exc.ui_message
        save_job(job)
    except Exception as exc:
        LOG.exception("hybrid send failed task_id=%s", task_id)
        job = load_job(project_name, user_folder, task_id)
        job["status"] = "error"
        job["error_message"] = "hybrid_channel"
        job["error_ui"] = "Углублённый анализ временно недоступен. Попробуйте позже."
        save_job(job)


def start_hybrid_analysis(
    pdf_bytes: bytes,
    step_data: Dict[str, Any],
    project_name: str,
    user_folder: str = "",
    user_email: str = "",
) -> Dict[str, Any]:
    """
    Создаёт job и возвращает task_id (автоматика и канал — в фоне через BackgroundTasks).
    """
    if not pdf_bytes:
        raise ValueError("PDF не передан")
    if not (project_name or "").strip():
        raise ValueError("Не указан проект")

    task_id = str(uuid.uuid4())
    _cancel_pending_jobs(project_name, user_folder, except_task_id=task_id)

    pdf_hash = hashlib.sha256(pdf_bytes).hexdigest()
    pdir = _project_dir(project_name, user_folder)
    os.makedirs(pdir, exist_ok=True)
    from project_store import _safe_dir_name

    pdf_path = os.path.join(pdir, f"{_safe_dir_name(project_name)}.pdf")
    with open(pdf_path, "wb") as f:
        f.write(pdf_bytes)

    timeout = _timeout_seconds()
    job: Dict[str, Any] = {
        "task_id": task_id,
        "project_name": project_name,
        "user_folder": user_folder,
        "pdf_hash": pdf_hash,
        "pdf_path": pdf_path,
        "status": "pending_balance",
        "created_at": _now_iso(),
        "deadline_at": _deadline_iso(timeout),
        "channel_task_id": task_id,
        "auto_extraction": None,
        "suffler_text": None,
        "suffler_parsed": None,
        "error_message": "",
        "error_ui": None,
        "step_data_snapshot": {
            k: step_data.get(k)
            for k in (
                "step_analysis_version",
                "user_folder",
                "material",
                "dimensions",
                "geometry",
                "holes",
                "shafts",
            )
            if step_data.get(k) is not None
        },
        "user_email": (user_email or "").strip(),
    }
    save_job(job)
    return {"task_id": task_id, "status": "pending_balance", "deadline_at": job["deadline_at"]}


def finalize_hybrid_job(
    project_name: str,
    user_folder: str,
    task_id: str,
    step_data: Optional[Dict[str, Any]] = None,
    user_email: str = "",
) -> Dict[str, Any]:
    """При status=ready: deep_analysis (токены списаны до отправки чертежа)."""
    job = refresh_job_status(project_name, user_folder, task_id)
    status = job.get("status")

    if status == "timeout":
        raise HybridJobError(
            "timeout",
            ui_message="Анализ временно недоступен, попробуйте позже",
        )
    if status == "error":
        raise HybridJobError(
            "error",
            ui_message=job.get("error_ui")
            or "Анализ временно недоступен, попробуйте позже",
        )
    if status != "ready":
        raise HybridJobError(
            "pending",
            ui_message="Углублённый анализ ещё выполняется",
        )

    suffler_text = (job.get("suffler_text") or "").strip()
    if not suffler_text:
        raise HybridJobError(
            "error",
            ui_message="Анализ временно недоступен, попробуйте позже",
        )

    pdf_path = job.get("pdf_path") or ""
    if not pdf_path or not os.path.isfile(pdf_path):
        raise HybridJobError("error", ui_message="PDF чертежа не найден")

    with open(pdf_path, "rb") as f:
        pdf_bytes = f.read()

    merged_step = dict(job.get("step_data_snapshot") or {})
    if step_data:
        merged_step.update(step_data)
    merged_step["user_folder"] = user_folder or merged_step.get("user_folder", "")
    merged_step["project_name"] = project_name
    if job.get("auto_extraction"):
        merged_step["drawing_extraction"] = job["auto_extraction"]

    user_email = (user_email or job.get("user_email") or "").strip()

    if job.get("finalize_result") and isinstance(job["finalize_result"], dict):
        cached = job["finalize_result"]
        if cached.get("status") == "ok" or (cached.get("analysis") or "").strip():
            return cached

    import payment as pay

    pending_entry = pay.find_flow_pending_by_task_id(user_email, task_id)
    if pending_entry:
        balance = pay.get_flow_token_balance(user_email)
        return {
            "status": "pending_payment",
            "rub_required": int(pending_entry.get("rub_required") or 0),
            "balance": balance,
            "pending_id": pending_entry.get("pending_id") or "",
            "ui_message": (
                f"Анализ «Поток» выполнен. Для просмотра пополните баланс: "
                f"нужно **{pending_entry.get('rub_required')} ₽, на счёте **{balance}**."
            ),
        }

    from expert_analyzer import deep_analysis

    result = deep_analysis(
        pdf_bytes,
        step_data=merged_step,
        project_name=project_name,
        suffler_text=suffler_text,
        hybrid_task_id=task_id,
    )
    result["hybrid_task_id"] = task_id
    result["suffler_parsed"] = job.get("suffler_parsed")

    charged = int(job.get("flow_tokens_charged") or 0)
    if charged:
        result["tokens_debited"] = charged
        result["flow_balance"] = job.get("flow_balance_after_debit")

    job["finalized_at"] = _now_iso()
    job["finalize_status"] = result.get("status")
    job["finalize_result"] = result
    save_job(job)
    return result


class HybridJobError(Exception):
    def __init__(self, code: str, *, ui_message: str) -> None:
        self.code = code
        self.ui_message = ui_message
        super().__init__(ui_message)
