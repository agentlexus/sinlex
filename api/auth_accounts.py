"""User accounts (accounts.json) and folder resolution."""
import hashlib
import json
import os

from fastapi import Header, HTTPException

from api.config import ACCOUNTS_FILE, CASTING_ROOT, PROJECTS_ROOT


def load_accounts():
    if not os.path.exists(ACCOUNTS_FILE):
        with open(ACCOUNTS_FILE, "w", encoding="utf-8") as f:
            json.dump({}, f)
    with open(ACCOUNTS_FILE, encoding="utf-8") as f:
        return json.load(f)


def save_accounts(acc):
    with open(ACCOUNTS_FILE, "w", encoding="utf-8") as f:
        json.dump(acc, f, indent=2)


def hash_password(password: str) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode(), b"sinlex_salt_static", 100000
    ).hex()


def get_user_folder(x_user_email: str = Header(None)) -> str:
    if not x_user_email:
        raise HTTPException(401, "X-User-Email header required")
    accounts = load_accounts()
    acc = accounts.get(x_user_email)
    if not acc:
        raise HTTPException(401, "Unknown user email")
    return acc["folder"]


def get_user_project_dir(user_email: str) -> str:
    folder = get_user_folder(x_user_email=user_email)
    return os.path.join(PROJECTS_ROOT, folder)


def get_user_projects_file(user_email: str) -> str:
    return os.path.join(get_user_project_dir(user_email), "projects.json")

def get_user_casting_dir(user_email: str) -> str:
    folder = get_user_folder(x_user_email=user_email)
    return os.path.join(CASTING_ROOT, folder)


def get_user_casting_file(user_email: str) -> str:
    return os.path.join(get_user_casting_dir(user_email), "projects.json")



def resolve_user_email(
    x_user_email: str = None,
    key: str = "",
    email: str = "",
    sid: str = "",
) -> str:
    if x_user_email:
        return x_user_email
    if sid:
        try:
            from auth_store import get_session

            sess = get_session(sid)
            if sess and sess.get("email"):
                return sess["email"]
        except Exception:
            pass
    from api.config import API_KEY

    if key == API_KEY and email:
        from urllib.parse import unquote

        email = unquote(email).strip()
        accounts = load_accounts()
        if email in accounts:
            return email
        el = email.lower()
        for k in accounts:
            if k.lower() == el:
                return k
    raise HTTPException(401, "Войдите в аккаунт или откройте проект заново")


import re

_CYR_LAT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "yo",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}


def transliterate(text: str) -> str:
    return "".join(_CYR_LAT.get(c.lower(), c) for c in text or "")


def folder_from_company_name(company_name: str, fallback_email: str = "") -> str:
    """Каталог projects/<folder> — из названия компании (как в app.py)."""
    raw = re.sub(r"[^a-zA-Zа-яА-Я0-9 _-]", "", (company_name or "").strip())
    safe = transliterate(raw).strip().replace(" ", "_").lower()
    if safe:
        return safe
    email = (fallback_email or "").strip().lower()
    return transliterate(email.replace("@", "_").replace(".", "_")) or "company"


def resolve_company_folder(company_name: str, fallback_email: str = "") -> tuple[str, str]:
    """(folder, company_name) — при существующей папке компании подключаем к ней."""
    folder = folder_from_company_name(company_name, fallback_email)
    name = (company_name or "").strip()
    for acc in load_accounts().values():
        if acc.get("folder") == folder:
            existing = (acc.get("company_name") or name).strip()
            return folder, existing or name or folder
    if not name and fallback_email:
        name = fallback_email.split("@")[0].capitalize()
    return folder, name
