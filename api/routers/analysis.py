"""PDF scan, expert analysis, tech card, manufacturing brief."""
import json

from fastapi import APIRouter, File, Form, Header, HTTPException, Request, UploadFile

from expert_analyzer import deep_analysis, manufacturing_brief, tech_card_analysis
from risk_scanner import scan_pdf_bytes

from api.auth_accounts import get_user_folder

router = APIRouter(tags=["analysis"])


@router.post("/scan-risk")
async def scan_risk_endpoint(
    file: UploadFile = File(...),
    step_data: str = Form("{}"),
    x_user_email: str = Header(None),
):
    get_user_folder(x_user_email)
    pdf_bytes = await file.read()
    step_data_dict = json.loads(step_data) if step_data else {}
    try:
        step_data_dict["user_folder"] = get_user_folder(x_user_email)
    except HTTPException:
        step_data_dict.setdefault("user_folder", "")
    return scan_pdf_bytes(pdf_bytes, step_data_dict)


@router.post("/expert-analysis")
async def expert_analysis_endpoint(
    file: UploadFile = File(None),
    step_data: str = Form("{}"),
    x_user_email: str = Header(None),
):
    user_folder = ""
    try:
        user_folder = get_user_folder(x_user_email)
    except HTTPException:
        pass
    step_data_dict = json.loads(step_data) if step_data else {}
    try:
        step_data_dict["user_folder"] = user_folder or step_data_dict.get("user_folder", "")
    except Exception:
        step_data_dict.setdefault("user_folder", "")
    project_name = step_data_dict.get("project_name", "")
    pdf_bytes = await file.read() if file is not None else b""
    if not pdf_bytes:
        raise HTTPException(status_code=400, detail="PDF не передан")
    try:
        return deep_analysis(pdf_bytes, step_data=step_data_dict, project_name=project_name)
    except Exception as e:
        return {"status": "error", "message": str(e), "api_used": None}


@router.post("/tech-card")
async def tech_card_endpoint(
    analysis_text: str = Form(""),
    step_data: str = Form("{}"),
    log_data: str = Form("[]"),
    x_user_email: str = Header(None),
):
    get_user_folder(x_user_email)
    step_dict = json.loads(step_data) if step_data else {}
    log_list = json.loads(log_data) if log_data else []
    return tech_card_analysis(analysis_text, step_dict, log_list)


@router.post("/manufacturing-brief")
async def manufacturing_brief_endpoint(request: Request, x_user_email: str = Header(None)):
    user_folder = ""
    try:
        user_folder = get_user_folder(x_user_email)
    except HTTPException:
        pass
    try:
        body = await request.json()
    except Exception:
        body = {}
    project_name = str(body.get("project_name") or "")
    context = body.get("context") if isinstance(body.get("context"), dict) else {}
    return manufacturing_brief(context, project_name=project_name, user_folder=user_folder)
