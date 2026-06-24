"""Embedded HTML pages (3D viewer, PDF upload) and legacy /3d-viewer."""
import json
from html import escape
from urllib.parse import quote, urlencode

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse

import os
import sys

from api.auth_accounts import resolve_user_email
from api.config import API_KEY, BASE_DIR
from api.services.casting_fs import ensure_casting_glb_async, resolve_casting_project_dir, user_casting_dir
from api.services.projects_fs import ensure_project_glb_async, resolve_project_dir, user_projects_dir
from api.templates import render_template
from api.three_static import browser_api_prefix, three_importmap_json


_PAGE_MODULES = os.path.join(BASE_DIR, "page_modules")
if _PAGE_MODULES not in sys.path:
    sys.path.insert(0, _PAGE_MODULES)


def _enhanced_viewer_html(
    *,
    glb_path: str,
    glb_url: str,
    glb_fetch_rel: str,
    height: int,
    casting_ctx: dict | None = None,
    project_name: str = "",
    stock_glb_fetch_rel: str = "",
    stock_glb_url: str = "",
) -> str:
    from upload_limits import GLB_INLINE_MAX_BYTES
    from viewer_3d import build_three_viewer_html

    with open(glb_path, "rb") as f:
        raw = f.read()
    glb_bytes = raw if len(raw) <= GLB_INLINE_MAX_BYTES else b""
    return build_three_viewer_html(
        glb_bytes,
        glb_url,
        glb_fetch_rel,
        height=height,
        glb_size=len(raw),
        casting_ctx=casting_ctx,
        stock_glb_fetch_rel=stock_glb_fetch_rel,
        stock_glb_url=stock_glb_url,
    )


async def _serve_enhanced_3d_embed(
    request: Request,
    project_name: str,
    storage: str,
    key: str,
    email: str,
    sid: str,
    folder: str,
    height: int,
    casting: int = 0,
    allowance_mm: float = 0,
    shrink_pct: float = 0,
    dim_x: float = 0,
    dim_y: float = 0,
    dim_z: float = 0,
) -> HTMLResponse:
    if key != API_KEY:
        return HTMLResponse(
            "<p style='color:red;padding:1rem;font-family:sans-serif'>Неверный ключ API</p>",
            status_code=401,
        )
    height = max(320, min(int(height or 420), 900))
    try:
        user_email = resolve_user_email(None, key, email, sid)
        if storage == "casting":
            user_dir = user_casting_dir(user_email, folder)
            safe_name, pdir = resolve_casting_project_dir(user_dir, project_name)
            await ensure_casting_glb_async(user_email, project_name, folder)
            api_segment = "casting"
        else:
            user_dir = user_projects_dir(user_email, folder)
            safe_name, pdir = resolve_project_dir(user_dir, project_name)
            await ensure_project_glb_async(user_email, project_name, folder)
            api_segment = "projects"
        glb_path = os.path.join(pdir, f"{safe_name}.glb")
        if not os.path.isfile(glb_path):
            raise HTTPException(404, "GLB не найден")
    except HTTPException as e:
        return HTMLResponse(
            f"<p style='color:red;padding:1rem;font-family:sans-serif'>{escape(str(e.detail))}</p>",
            status_code=e.status_code,
        )

    glb_q = quote(safe_name, safe="")
    email_q = quote(user_email, safe="")
    folder_q = quote(folder, safe="") if folder else ""
    sid_q = quote(sid, safe="") if sid else ""
    prefix = browser_api_prefix(request) or "https://sinlex.tech/api"
    glb_url = f"{prefix}/{api_segment}/glb/{glb_q}?key={key}&email={email_q}"
    if sid_q:
        glb_url += f"&sid={sid_q}"
    if folder_q:
        glb_url += f"&folder={folder_q}"
    glb_fetch_rel = f"/api/{api_segment}/glb/{glb_q}?key={key}&email={email_q}"
    if sid_q:
        glb_fetch_rel += f"&sid={sid_q}"
    if folder_q:
        glb_fetch_rel += f"&folder={folder_q}"

    casting_ctx = None
    stock_rel = ""
    stock_abs = ""
    if storage == "casting" or int(casting or 0):
        casting_ctx = {
            "allowance_mm": float(allowance_mm or 0),
            "shrink_pct": float(shrink_pct or 0),
            "dimensions": {"x": float(dim_x or 0), "y": float(dim_y or 0), "z": float(dim_z or 0)},
        }
        from viewer_3d import build_stock_glb_urls

        stock_rel, stock_abs = build_stock_glb_urls(
            project_name,
            float(allowance_mm or 0),
            email=user_email,
            sid=sid,
            folder=folder,
        )

    html = _enhanced_viewer_html(
        glb_path=glb_path,
        glb_url=glb_url,
        glb_fetch_rel=glb_fetch_rel,
        height=height,
        casting_ctx=casting_ctx,
        project_name=project_name,
        stock_glb_fetch_rel=stock_rel,
        stock_glb_url=stock_abs,
    )
    return HTMLResponse(content=html)

router = APIRouter(tags=["embed"])


def pdf_upload_form_html(api_base: str, project: str, email: str, key: str) -> str:
    base = (api_base or "/api").rstrip("/")
    q = urlencode({"key": key, "email": email, "html": "1"})
    action = f"{base}/projects/{quote(project, safe='')}/drawing?{q}"
    return render_template(
        "pdf_upload.html",
        TITLE=escape(project),
        ACTION=action,
    )


@router.get("/embed/pdf-upload")
async def embed_pdf_upload(
    request: Request,
    project: str = Query(""),
    key: str = Query(""),
    email: str = Query(""),
):
    if key != API_KEY:
        return HTMLResponse(
            "<p style='color:red;padding:1rem;font-family:sans-serif'>Неверный ключ API</p>",
            status_code=401,
        )
    if not project.strip() or not email.strip():
        return HTMLResponse(
            "<p style='color:red;padding:1rem;font-family:sans-serif'>"
            "Не указан проект или email</p>",
            status_code=400,
        )
    prefix = browser_api_prefix(request) or "https://sinlex.tech/api"
    return HTMLResponse(
        content=pdf_upload_form_html(prefix, project.strip(), email.strip(), key)
    )


@router.get("/embed/3d/{project_name}")
async def embed_3d_viewer(
    request: Request,
    project_name: str,
    key: str = Query(""),
    email: str = Query(""),
    sid: str = Query(""),
    folder: str = Query(""),
):
    if key != API_KEY:
        return HTMLResponse(
            "<p style='color:red;padding:1rem'>Неверный ключ API</p>",
            status_code=401,
        )
    try:
        user_email = resolve_user_email(None, key, email, sid)
        safe_name, _ = resolve_project_dir(
            user_projects_dir(user_email, folder),
            project_name,
        )
        await ensure_project_glb_async(user_email, project_name, folder)
    except HTTPException as e:
        return HTMLResponse(
            f"<p style='color:red;padding:1rem;font-family:sans-serif'>{e.detail}</p>",
            status_code=e.status_code,
        )

    glb_q = quote(safe_name, safe="")
    email_q = quote(user_email, safe="")
    folder_q = quote(folder, safe="") if folder else ""
    sid_q = quote(sid, safe="") if sid else ""
    prefix = browser_api_prefix(request)
    glb_url = f"{prefix}/projects/glb/{glb_q}?key={key}&email={email_q}"
    if sid_q:
        glb_url += f"&sid={sid_q}"
    if folder_q:
        glb_url += f"&folder={folder_q}"

    html = render_template(
        "embed_3d.html",
        IMPORTMAP=three_importmap_json(prefix),
        GLB_URL_JSON=json.dumps(glb_url),
    )
    return HTMLResponse(content=html)


@router.get("/embed/3d-viewer/{project_name}")
async def embed_3d_viewer_enhanced(
    request: Request,
    project_name: str,
    key: str = Query(""),
    email: str = Query(""),
    sid: str = Query(""),
    folder: str = Query(""),
    storage: str = Query("projects"),
    height: int = Query(420),
    casting: int = Query(0),
    allowance_mm: float = Query(0),
    shrink_pct: float = Query(0),
    dim_x: float = Query(0),
    dim_y: float = Query(0),
    dim_z: float = Query(0),
):
    storage_norm = (storage or "projects").strip().lower()
    if storage_norm not in ("projects", "casting"):
        storage_norm = "projects"
    return await _serve_enhanced_3d_embed(
        request,
        project_name,
        storage_norm,
        key,
        email,
        sid,
        folder,
        height,
        casting=1 if storage_norm == "casting" else 0,
        allowance_mm=allowance_mm,
        shrink_pct=shrink_pct,
        dim_x=dim_x,
        dim_y=dim_y,
        dim_z=dim_z,
    )


@router.get("/embed/3d-casting/{project_name}")
async def embed_3d_casting_viewer(
    request: Request,
    project_name: str,
    key: str = Query(""),
    email: str = Query(""),
    sid: str = Query(""),
    folder: str = Query(""),
    height: int = Query(520),
    allowance_mm: float = Query(0),
    shrink_pct: float = Query(0),
    dim_x: float = Query(0),
    dim_y: float = Query(0),
    dim_z: float = Query(0),
):
    return await _serve_enhanced_3d_embed(
        request,
        project_name,
        "casting",
        key,
        email,
        sid,
        folder,
        height,
        casting=1,
        allowance_mm=allowance_mm,
        shrink_pct=shrink_pct,
        dim_x=dim_x,
        dim_y=dim_y,
        dim_z=dim_z,
    )


@router.get("/3d-viewer")
async def viewer(model_url: str = ""):
    html = render_template(
        "viewer_simple.html",
        IMPORTMAP=three_importmap_json(),
        MODEL_URL_JSON=json.dumps(model_url),
    )
    return HTMLResponse(content=html)
