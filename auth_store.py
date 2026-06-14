"""Серверные сессии авторизации (переживают обновление страницы Streamlit)."""
import json
import os
import secrets
import time

SESSIONS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".sessions")
SESSION_TTL_SEC = 30 * 24 * 3600  # 30 дней


def _session_path(sid: str) -> str:
    safe = "".join(c for c in sid if c.isalnum() or c in "-_")
    return os.path.join(SESSIONS_DIR, f"{safe}.json")


def create_session(email: str, folder: str, company: str = "", original_email: str = "") -> str:
    os.makedirs(SESSIONS_DIR, exist_ok=True)
    sid = secrets.token_urlsafe(32)
    data = {
        "email": email,
        "folder": folder,
        "company": company,
        "original_email": original_email or email,
        "created": time.time(),
        "expires": time.time() + SESSION_TTL_SEC,
    }
    with open(_session_path(sid), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    return sid


def get_session(sid: str):
    if not sid or len(sid) > 128:
        return None
    path = _session_path(sid)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None
    if time.time() > data.get("expires", 0):
        try:
            os.unlink(path)
        except OSError:
            pass
        return None
    return data


def delete_session(sid: str) -> None:
    if not sid:
        return
    path = _session_path(sid)
    if os.path.isfile(path):
        try:
            os.unlink(path)
        except OSError:
            pass
