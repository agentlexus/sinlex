"""Casting project directories and projects.json on disk."""
import os

from fastapi import HTTPException

from api.auth_accounts import get_user_casting_dir
from api.config import CASTING_ROOT
from api.services.step_convert import ensure_glb_from_stp


def user_casting_dir(user_email: str, user_folder: str = "") -> str:
    if user_folder:
        safe = user_folder.replace("..", "").strip("/\\")
        return os.path.join(CASTING_ROOT, safe)
    return get_user_casting_dir(user_email)


def resolve_casting_project_dir(user_dir: str, project_name: str) -> tuple:
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
    raise HTTPException(404, f"Литьевой проект не найден: {project_name}")


def ensure_casting_glb(
    user_email: str,
    project_name: str,
    user_folder: str = "",
) -> str:
    user_dir = user_casting_dir(user_email, user_folder)
    safe_name, pdir = resolve_casting_project_dir(user_dir, project_name)
    glb_path = os.path.join(pdir, f"{safe_name}.glb")
    stp_path = os.path.join(pdir, f"{safe_name}.stp")
    ensure_glb_from_stp(stp_path, glb_path)
    return glb_path
def ensure_casting_stock_glb(
    user_email: str,
    project_name: str,
    allowance_mm: float,
    user_folder: str = "",
) -> str:
    """GLB заготовки с OCC offset; кэш {name}.stock_{N}.glb."""
    from casting_stock_glb import ensure_stock_glb_cached, stock_glb_path

    allowance = float(allowance_mm)
    if allowance <= 0:
        raise HTTPException(422, "allowance_mm must be > 0")

    user_dir = user_casting_dir(user_email, user_folder)
    safe_name, pdir = resolve_casting_project_dir(user_dir, project_name)
    stp_path = os.path.join(pdir, f"{safe_name}.stp")
    part_glb = ensure_casting_glb(user_email, project_name, user_folder)
    out_path = stock_glb_path(pdir, safe_name, allowance)

    try:
        return ensure_stock_glb_cached(stp_path, part_glb, out_path, allowance)
    except Exception as exc:
        from casting_allowance_offset import AllowanceOffsetError

        if isinstance(exc, AllowanceOffsetError):
            raise HTTPException(
                503,
                f"OCC offset не сошёлся: {exc}",
                headers={"X-Stock-Fallback": "bbox"},
            ) from exc
        raise HTTPException(500, f"Не удалось построить stock GLB: {exc}") from exc

