"""Чат-уточнения «Поток»: вопрос с чертежом → ответ канала → пересборка отчёта LLM."""

from __future__ import annotations

import json
import logging
import os
import uuid
import threading
from typing import Any, Dict, Optional

from flow_data_store import (
    append_channel_response,
    append_chat_turn,
    load_flow_data,
    set_report,
)
from flow_drawing_io import drawing_hash, extract_text_from_drawing, safe_drawing_filename
from flow_norm_analysis import (
    HybridJobError,
    load_job,
    save_job,
    _timeout_seconds,
    _deadline_iso,
    _now_iso,
)
from flow_norm_hours import FLOW_NORM_PROJECT, refine_flow_report
from flow_norm_logistics import MaxSufflerError, get_flow_norm_channel

LOG = logging.getLogger("flow_norm_chat")


def _drawing_path_from_job(job: Dict[str, Any]) -> str:
    path = (job.get("drawing_path") or job.get("pdf_path") or "").strip()
    if path and os.path.isfile(path):
        return path
    raise HybridJobError("error", ui_message="Файл чертежа не найден")


def _read_drawing(job: Dict[str, Any]) -> tuple[bytes, str]:
    path = _drawing_path_from_job(job)
    name = (job.get("drawing_filename") or os.path.basename(path) or "drawing.pdf").strip()
    with open(path, "rb") as f:
        data = f.read()
    if not data:
        raise HybridJobError("error", ui_message="Пустой файл чертежа")
    return data, safe_drawing_filename(name)


def start_flow_chat(
    project_name: str,
    user_folder: str,
    master_task_id: str,
    question: str,
) -> Dict[str, Any]:
    """Отправить вопрос в цепочку с вложением чертежа."""
    q = (question or "").strip()
    if not q:
        raise ValueError("Введите вопрос")
    tid = (master_task_id or "").strip()
    if not tid:
        raise ValueError("Нет активной задачи")

    job = load_job(project_name, user_folder, tid)
    if job.get("status") not in ("ready",) and not job.get("finalize_result"):
        raise HybridJobError("error", ui_message="Сначала дождитесь завершения анализа")

    drawing_bytes, drawing_name = _read_drawing(job)
    drawing_path = _drawing_path_from_job(job)

    chat_id = f"{tid}-q{uuid.uuid4().hex[:8]}"
    channel = get_flow_norm_channel()
    thread_mid = (job.get("thread_message_id") or "").strip()
    try:
        channel.send_chat_question(
            project_name,
            tid,
            chat_id=chat_id,
            question=q,
            drawing_bytes=drawing_bytes,
            drawing_filename=drawing_name,
            reply_to_message_id=thread_mid,
            user_folder=user_folder,
        )
    except MaxSufflerError as exc:
        raise HybridJobError("error", ui_message=exc.ui_message) from exc

    chats = job.setdefault("chats", [])
    chats.append(
        {
            "chat_id": chat_id,
            "question": q,
            "status": "pending",
            "created_at": _now_iso(),
        }
    )
    job["active_chat_id"] = chat_id
    save_job(job)

    append_chat_turn(drawing_path, q, answer="", chat_id=chat_id)
    set_report(
        drawing_path,
        job={"master_task_id": tid, "active_chat_id": chat_id},
    )

    return {
        "chat_id": chat_id,
        "master_task_id": tid,
        "status": "pending",
        "deadline_at": _deadline_iso(_timeout_seconds()),
    }


def _spawn_refine_thread(*, project_name: str, user_folder: str, master_task_id: str, chat_id: str, drawing_path: str, latest_text: str) -> None:
    def _run() -> None:
        try:
            job = load_job(project_name, user_folder, master_task_id)
            norm_inputs = job.get("norm_inputs_snapshot") or {}
            refined = refine_flow_report(
                project_name,
                user_folder,
                master_task_id,
                norm_inputs,
                latest_channel_text=latest_text,
                drawing_path=drawing_path,
            )

            for ch in job.get("chats") or []:
                if ch.get("chat_id") == chat_id:
                    ch["status"] = "done"
                    ch["refined_at"] = _now_iso()
                    break

            job["finalize_result"] = refined
            chat_results = job.setdefault("chat_results", {})
            if isinstance(chat_results, dict):
                chat_results[chat_id] = refined
            job.pop("active_chat_id", None)
            save_job(job)
        except Exception:
            LOG.exception("flow chat refine thread failed")

    threading.Thread(
        target=_run,
        name=f"flow-refine-{chat_id[-8:]}",
        daemon=True,
    ).start()



def refresh_chat_status(
    project_name: str,
    user_folder: str,
    chat_id: str,
) -> Dict[str, Any]:
    cid = (chat_id or "").strip()
    if not cid:
        raise ValueError("chat_id required")

    master_tid = cid.rsplit("-q", 1)[0] if "-q" in cid else ""
    job = load_job(project_name, user_folder, master_tid) if master_tid else None
    if not job:
        raise FileNotFoundError(cid)

    chat_results = job.get("chat_results") or {}
    if isinstance(chat_results, dict) and chat_results.get(cid):
        return {"chat_id": cid, "status": "ok", "master_task_id": master_tid, "result": chat_results[cid]}

    for ch in job.get("chats") or []:
        if ch.get("chat_id") == cid and ch.get("status") == "refining":
            # После рестарта сервера поток мог не запуститься — запустим один раз
            if not ch.get("refine_thread_spawned"):
                ch["refine_thread_spawned"] = True
                save_job(job)
                _spawn_refine_thread(
                    project_name=project_name,
                    user_folder=user_folder,
                    master_task_id=master_tid,
                    chat_id=cid,
                    drawing_path=_drawing_path_from_job(job),
                    latest_text=ch.get("answer_text") or "",
                )
            return {"chat_id": cid, "status": "pending", "master_task_id": master_tid}

    channel = get_flow_norm_channel()
    try:
        text = channel.check_chat_response(cid)
    except MaxSufflerError as exc:
        raise HybridJobError("error", ui_message=exc.ui_message) from exc

    if not text:
        return {"chat_id": cid, "status": "pending", "master_task_id": master_tid}

    drawing_path = _drawing_path_from_job(job)
    append_channel_response(drawing_path, text, task_id=cid)

    for ch in job.get("chats") or []:
        if ch.get("chat_id") == cid:
            ch["status"] = "refining"
            ch["answer_text"] = text
            ch["refine_started_at"] = _now_iso()
            break
    save_job(job)

    append_chat_turn(
        drawing_path,
        _question_for_chat(job, cid),
        answer=text,
        chat_id=cid,
    )

    _spawn_refine_thread(
        project_name=project_name,
        user_folder=user_folder,
        master_task_id=master_tid,
        chat_id=cid,
        drawing_path=drawing_path,
        latest_text=text,
    )

    return {"chat_id": cid, "status": "pending", "master_task_id": master_tid}





def _question_for_chat(job: Dict[str, Any], chat_id: str) -> str:
    for ch in job.get("chats") or []:
        if ch.get("chat_id") == chat_id:
            return (ch.get("question") or "").strip()
    return ""


def persist_initial_flow_data(
    job: Dict[str, Any],
    result: Dict[str, Any],
) -> None:
    """После первого finalize — записать flow_data.md."""
    try:
        path = _drawing_path_from_job(job)
    except HybridJobError:
        return

    from flow_data_store import init_flow_data, load_flow_data

    fname = job.get("drawing_filename") or os.path.basename(path)
    h = job.get("pdf_hash") or job.get("drawing_hash") or ""
    data = load_flow_data(path) or init_flow_data(path, fname, h)

    suffler = (job.get("suffler_text") or "").strip()
    if suffler:
        existing = {r.get("task_id") for r in data.get("channel_responses") or []}
        if job.get("task_id") not in existing:
            append_channel_response(path, suffler, task_id=job.get("task_id") or "")
            data = load_flow_data(path) or data

    analysis_text = result.get("analysis") or ""
    set_report(
        path,
        analysis={"report_markdown": analysis_text, "api_used": result.get("api_used")},
        norm_calc=result.get("norm_calc"),
        structured=result.get("structured"),
        finalize=result,
        job={
            "master_task_id": job.get("task_id"),
            "thread_message_id": job.get("thread_message_id"),
            "pdf_hash": h,
        },
    )
