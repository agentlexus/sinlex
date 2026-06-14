"""Гибридный углублённый анализ чертежа (этап HS-2)."""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, BackgroundTasks, File, Form, Header, HTTPException, UploadFile

from api.auth_accounts import get_user_folder
from hybrid_analysis import (
    HybridJobError,
    finalize_hybrid_job,
    job_to_public,
    refresh_job_status,
    run_start_background,
    start_hybrid_analysis,
)

LOG = logging.getLogger("api.hybrid_analysis")

router = APIRouter(tags=["hybrid-analysis"])


def _resolve_user_folder(x_user_email: str | None) -> str:
    try:
        return get_user_folder(x_user_email)
    except HTTPException:
        return ""


@router.post("/hybrid-analysis/start")
async def hybrid_start(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    step_data: str = Form("{}"),
    x_user_email: str = Header(None),
):
    email = (x_user_email or "").strip()
    user_folder = _resolve_user_folder(x_user_email)
    step_data_dict = json.loads(step_data) if step_data else {}
    step_data_dict["user_folder"] = user_folder or step_data_dict.get("user_folder", "")
    project_name = str(step_data_dict.get("project_name") or "").strip()
    if not project_name:
        raise HTTPException(status_code=400, detail="Не указан проект")
    pdf_bytes = await file.read()
    if not pdf_bytes:
        raise HTTPException(status_code=400, detail="PDF не передан")
    try:
        out = start_hybrid_analysis(
            pdf_bytes,
            step_data_dict,
            project_name,
            user_folder=user_folder,
            user_email=email,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    background_tasks.add_task(
        run_start_background,
        out["task_id"],
        project_name,
        user_folder,
        pdf_bytes,
        step_data_dict,
    )
    return out


@router.get("/hybrid-analysis/status/{task_id}")
async def hybrid_status(
    task_id: str,
    project_name: str,
    x_user_email: str = Header(None),
    user_folder: str = "",
):
    uf = user_folder or _resolve_user_folder(x_user_email)
    if not (project_name or "").strip():
        raise HTTPException(status_code=400, detail="Не указан проект")
    try:
        job = refresh_job_status(project_name.strip(), uf, task_id.strip())
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Задача не найдена") from None
    return job_to_public(job)


@router.post("/hybrid-analysis/finalize/{task_id}")
async def hybrid_finalize(
    task_id: str,
    step_data: str = Form("{}"),
    project_name: str = Form(""),
    x_user_email: str = Header(None),
):
    uf = _resolve_user_folder(x_user_email)
    step_data_dict = json.loads(step_data) if step_data else {}
    step_data_dict["user_folder"] = uf or step_data_dict.get("user_folder", "")
    pname = (project_name or step_data_dict.get("project_name") or "").strip()
    if not pname:
        raise HTTPException(status_code=400, detail="Не указан проект")
    email = (x_user_email or "").strip()
    try:
        return finalize_hybrid_job(
            pname, uf, task_id.strip(), step_data_dict, user_email=email
        )
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Задача не найдена") from None
    except HybridJobError as exc:
        code = 408 if exc.code == "timeout" else 400 if exc.code == "pending" else 503
        raise HTTPException(status_code=code, detail=exc.ui_message) from exc
    except Exception as exc:
        LOG.exception("hybrid finalize failed task_id=%s", task_id)
        raise HTTPException(
            status_code=503,
            detail="Анализ временно недоступен, попробуйте позже",
        ) from exc
