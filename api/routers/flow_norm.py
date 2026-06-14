"""API нормировки «Поток» (2D, отдельная страница)."""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, BackgroundTasks, File, Form, Header, HTTPException, UploadFile

from api.auth_accounts import get_user_folder
from flow_norm_analysis import (
    HybridJobError,
    job_to_public,
    refresh_job_status,
    run_start_background,
    start_flow_norm_analysis,
)
from flow_drawing_io import FLOW_DRAWING_EXTENSIONS, safe_drawing_filename
from flow_norm_chat import refresh_chat_status, start_flow_chat
from flow_norm_hours import FLOW_NORM_PROJECT, finalize_flow_norm_analysis

LOG = logging.getLogger("api.flow_norm")

router = APIRouter(tags=["flow-norm"])


def _resolve_user_folder(x_user_email: str | None) -> str:
    try:
        return get_user_folder(x_user_email)
    except HTTPException:
        return ""


@router.post("/flow-norm/start")
async def flow_norm_start(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    norm_inputs: str = Form("{}"),
    project_name: str = Form(""),
    x_user_email: str = Header(None),
):
    email = (x_user_email or "").strip()
    user_folder = _resolve_user_folder(x_user_email)
    pname = (project_name or FLOW_NORM_PROJECT).strip() or FLOW_NORM_PROJECT
    try:
        inputs = json.loads(norm_inputs) if norm_inputs else {}
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="norm_inputs: invalid JSON") from exc
    if not isinstance(inputs, dict):
        inputs = {}
    drawing_bytes = await file.read()
    if not drawing_bytes:
        raise HTTPException(status_code=400, detail="Файл чертежа не передан")
    fname = safe_drawing_filename(file.filename or "drawing.pdf")
    ext = __import__("os").path.splitext(fname)[1].lower()
    if ext not in FLOW_DRAWING_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Допустимы PDF, PNG, JPG, JPEG")
    try:
        out = start_flow_norm_analysis(
            drawing_bytes,
            inputs,
            pname,
            user_folder=user_folder,
            user_email=email,
            drawing_filename=fname,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    background_tasks.add_task(
        run_start_background,
        out["task_id"],
        pname,
        user_folder,
        drawing_bytes,
        inputs,
        fname,
    )
    return out


@router.get("/flow-norm/status/{task_id}")
async def flow_norm_status(
    task_id: str,
    project_name: str = "",
    x_user_email: str = Header(None),
    user_folder: str = "",
):
    uf = user_folder or _resolve_user_folder(x_user_email)
    pname = (project_name or FLOW_NORM_PROJECT).strip() or FLOW_NORM_PROJECT
    try:
        job = refresh_job_status(pname, uf, task_id.strip())
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Задача не найдена") from None
    return job_to_public(job)


@router.post("/flow-norm/finalize/{task_id}")
async def flow_norm_finalize(
    task_id: str,
    norm_inputs: str = Form("{}"),
    project_name: str = Form(""),
    x_user_email: str = Header(None),
):
    uf = _resolve_user_folder(x_user_email)
    pname = (project_name or FLOW_NORM_PROJECT).strip() or FLOW_NORM_PROJECT
    try:
        inputs = json.loads(norm_inputs) if norm_inputs else {}
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="norm_inputs: invalid JSON") from exc
    if not isinstance(inputs, dict):
        inputs = {}
    inputs["user_folder"] = uf
    email = (x_user_email or "").strip()
    try:
        return finalize_flow_norm_analysis(
            pname,
            uf,
            task_id.strip(),
            inputs,
            user_email=email,
        )
    except HybridJobError as exc:
        if exc.code == "pending":
            job = refresh_job_status(pname, uf, task_id.strip())
            pub = job_to_public(job)
            pub["status"] = "pending"
            pub["ui_message"] = exc.ui_message
            return pub
        raise HTTPException(
            status_code=400 if exc.code in ("error", "timeout") else 409,
            detail=exc.ui_message,
        ) from exc


@router.post("/flow-norm/chat")
async def flow_norm_chat(
    task_id: str = Form(...),
    question: str = Form(...),
    project_name: str = Form(""),
    x_user_email: str = Header(None),
):
    uf = _resolve_user_folder(x_user_email)
    pname = (project_name or FLOW_NORM_PROJECT).strip() or FLOW_NORM_PROJECT
    q = (question or "").strip()
    if not q:
        raise HTTPException(status_code=400, detail="Введите вопрос")
    try:
        return start_flow_chat(pname, uf, task_id.strip(), q)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except HybridJobError as exc:
        raise HTTPException(status_code=400, detail=exc.ui_message) from exc


@router.get("/flow-norm/chat/status/{chat_id}")
async def flow_norm_chat_status(
    chat_id: str,
    project_name: str = "",
    x_user_email: str = Header(None),
):
    uf = _resolve_user_folder(x_user_email)
    pname = (project_name or FLOW_NORM_PROJECT).strip() or FLOW_NORM_PROJECT
    try:
        return refresh_chat_status(pname, uf, chat_id.strip())
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Чат не найден") from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except HybridJobError as exc:
        raise HTTPException(status_code=400, detail=exc.ui_message) from exc

