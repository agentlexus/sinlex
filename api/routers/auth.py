"""Auth register/login."""
import base64
import json
import os
import hashlib
import time
import secrets
import re


from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel

from auth_store import delete_session

from api.auth_accounts import (
    folder_from_company_name,
    hash_password,
    load_accounts,
    resolve_company_folder,
    save_accounts,
)
from api.config import PROJECTS_ROOT

router = APIRouter(prefix="/auth", tags=["auth"])


_PENDING_FILE = "/opt/sinlex/data/landing_register_pending.json"
_PENDING_TTL_SEC = 15 * 60
_MAX_ATTEMPTS = 8
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _norm_email(email: str) -> str:
    return (email or "").strip().lower()


def _load_pending() -> dict:
    try:
        if os.path.isfile(_PENDING_FILE):
            with open(_PENDING_FILE, encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, dict) else {}
    except Exception:
        return {}
    return {}


def _save_pending(data: dict) -> None:
    os.makedirs(os.path.dirname(_PENDING_FILE), exist_ok=True)
    tmp = _PENDING_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, _PENDING_FILE)


def _gc_pending(data: dict) -> dict:
    now = time.time()
    out = {}
    for k, v in (data or {}).items():
        if not isinstance(v, dict):
            continue
        if now - float(v.get("created_at", 0) or 0) > _PENDING_TTL_SEC:
            continue
        out[k] = v
    return out


def _hash_code(code: str, salt: str) -> str:
    return hashlib.sha256((salt + ":" + (code or "").strip()).encode("utf-8")).hexdigest()


def _send_register_code(email_to: str, code: str) -> None:
    from api.register_email import send_register_code_email

    send_register_code_email(email_to, code)



class AuthRequest(BaseModel):
    email: str
    password: str
    company_name: str = ""


class RegisterCodeStartRequest(BaseModel):
    email: str
    first_name: str = ""
    last_name: str = ""
    company_name: str = ""
    phone: str = ""


class RegisterCodeConfirmRequest(BaseModel):
    email: str
    code: str
    password: str = ""
    first_name: str = ""
    last_name: str = ""
    company_name: str = ""
    phone: str = ""



@router.post("/register")
async def auth_register(data: AuthRequest):
    accounts = load_accounts()
    if data.email in accounts:
        raise HTTPException(400, "Email already registered")
    folder, company = resolve_company_folder(data.company_name, data.email)
    accounts[data.email] = {
        "password_hash": hash_password(data.password),
        "company_name": company,
        "folder": folder,
    }
    save_accounts(accounts)
    from ops_notify import notify_user_registered

    notify_user_registered(data.email)
    user_dir = os.path.join(PROJECTS_ROOT, folder)
    os.makedirs(user_dir, exist_ok=True)
    with open(os.path.join(user_dir, "projects.json"), "w", encoding="utf-8") as f:
        json.dump({"projects": []}, f)
    return {"status": "ok", "folder": folder, "company_name": company}


@router.post("/login")
async def auth_login(data: AuthRequest):
    accounts = load_accounts()
    acc = accounts.get(data.email)
    if not acc or acc["password_hash"] != hash_password(data.password):
        raise HTTPException(401, "Invalid credentials")
    token = base64.b64encode(data.email.encode()).decode()
    return {
        "status": "ok",
        "token": token,
        "folder": acc["folder"],
        "company_name": acc.get("company_name", ""),
    }



@router.get("/logout")
async def auth_logout(request: Request):
    """Сброс сессии и редирект на лендинг (/)."""
    sid = request.cookies.get("sinlex_sid") or request.query_params.get("sid")
    if sid:
        delete_session(sid)
    response = RedirectResponse(url="/", status_code=302)
    response.delete_cookie("sinlex_sid", path="/")
    return response


@router.post("/register-code/start")
async def register_code_start(data: RegisterCodeStartRequest):
    email = _norm_email(data.email)
    if not email or not _EMAIL_RE.match(email):
        raise HTTPException(400, "Invalid email")

    accounts = load_accounts()
    if email in accounts:
        # already registered — do not leak extra details
        return {"status": "ok"}

    pending = _gc_pending(_load_pending())
    code = f"{secrets.randbelow(1000000):06d}"
    salt = secrets.token_hex(16)
    pending[email] = {
        "created_at": time.time(),
        "salt": salt,
        "code_hash": _hash_code(code, salt),
        "attempts": 0,
        "first_name": (data.first_name or "").strip()[:80],
        "last_name": (data.last_name or "").strip()[:80],
        "company_name": (data.company_name or "").strip()[:120],
        "phone": (data.phone or "").strip()[:40],
    }
    _save_pending(pending)

    try:
        _send_register_code(email, code)
    except Exception:
        # keep pending, but report failure
        raise HTTPException(500, "Email send failed")

    return {"status": "ok"}


def _ensure_project_dir(folder: str) -> None:
    user_dir = os.path.join(PROJECTS_ROOT, folder)
    os.makedirs(user_dir, exist_ok=True)
    pj = os.path.join(user_dir, "projects.json")
    if not os.path.isfile(pj):
        with open(pj, "w", encoding="utf-8") as f:
            json.dump({"projects": []}, f)


def _finish_register_session(email: str) -> JSONResponse:
    from auth_store import create_session

    acc = load_accounts().get(email) or {}
    folder = (acc.get("folder") or "").strip()
    if not folder:
        folder, _ = resolve_company_folder(acc.get("company_name", ""), email)
    _ensure_project_dir(folder)

    sid = create_session(
        email=email,
        folder=folder,
        company=acc.get("company_name", ""),
        original_email=email,
    )
    resp = JSONResponse({"status": "ok", "redirect": "/app/"})
    resp.set_cookie(
        "sinlex_sid",
        sid,
        max_age=30 * 24 * 3600,
        httponly=True,
        secure=True,
        samesite="Lax",
        path="/",
    )
    return resp


@router.post("/register-code/confirm")
async def register_code_confirm(data: RegisterCodeConfirmRequest):
    email = _norm_email(data.email)
    code = (data.code or "").strip()
    if not email or not _EMAIL_RE.match(email) or not code:
        raise HTTPException(400, "Invalid request")

    accounts = load_accounts()
    if email in accounts:
        return _finish_register_session(email)

    pending = _gc_pending(_load_pending())
    item = pending.get(email)
    if not isinstance(item, dict):
        raise HTTPException(400, "Code expired")

    item["attempts"] = int(item.get("attempts") or 0) + 1
    if item["attempts"] > _MAX_ATTEMPTS:
        pending.pop(email, None)
        _save_pending(pending)
        raise HTTPException(429, "Too many attempts")

    salt = item.get("salt") or ""
    expected = item.get("code_hash") or ""
    if not salt or _hash_code(code, salt) != expected:
        pending[email] = item
        _save_pending(pending)
        raise HTTPException(400, "Invalid code")

    password = (data.password or "").strip()
    if len(password) < 8:
        raise HTTPException(400, "Пароль не менее 8 символов")

    company_raw = (data.company_name or item.get("company_name") or "").strip()
    folder, company = resolve_company_folder(company_raw, email)
    accounts[email] = {
        "password_hash": hash_password(password),
        "company_name": company,
        "folder": folder,
        "first_name": (data.first_name or item.get("first_name") or "").strip()[:80],
        "last_name": (data.last_name or item.get("last_name") or "").strip()[:80],
        "phone": (data.phone or item.get("phone") or "").strip()[:40],
    }
    save_accounts(accounts)
    from ops_notify import notify_user_registered

    notify_user_registered(email)
    _ensure_project_dir(folder)

    pending.pop(email, None)
    _save_pending(pending)

    return _finish_register_session(email)
