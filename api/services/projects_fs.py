"""Project directories and projects.json on disk."""
import os

from fastapi import HTTPException

from api.auth_accounts import get_user_project_dir
from api.config import PROJECTS_ROOT
from api.services.step_convert import ensure_glb_from_stp


def user_projects_dir(user_email: str, user_folder: str = "") -> str:
    if user_folder:
        safe = user_folder.replace("..", "").strip("/\\")
        return os.path.join(PROJECTS_ROOT, safe)
    return get_user_project_dir(user_email)


def resolve_project_dir(user_dir: str, project_name: str) -> tuple:
    from urllib.parse import unquote

    project_name = unquote(project_name).strip()
    safe_name = project_name.replace(" ", "_").replace("/", "_")
    pdir = os.path.join(user_dir, safe_name)
    if os.path.isdir(pdir):
        return safe_name, pdir
    if not os.path.isdir(user_dir):
        raise HTTPException(404, "Папка пользователя не найдена")
    want = safe_name.lower()
    for name in os.listdir(user_dir):
        if name in ("projects.json",) or name.startswith("."):
            continue
        full = os.path.join(user_dir, name)
        if not os.path.isdir(full):
            continue
        if name.lower() == want or name.replace(" ", "_").lower() == want:
            return name, full
    raise HTTPException(404, f"Проект не найден: {project_name}")


def ensure_project_glb(
    user_email: str,
    project_name: str,
    user_folder: str = "",
) -> str:
    user_dir = user_projects_dir(user_email, user_folder)
    safe_name, pdir = resolve_project_dir(user_dir, project_name)
    glb_path = os.path.join(pdir, f"{safe_name}.glb")
    stp_path = os.path.join(pdir, f"{safe_name}.stp")
    ensure_glb_from_stp(stp_path, glb_path)
    return glb_path
