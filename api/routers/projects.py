"""Project CRUD, GLB, drawings, files."""
import json
import os
import shutil

from fastapi import APIRouter, File, Header, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from api.auth_accounts import (
    get_user_folder,
    get_user_project_dir,
    get_user_projects_file,
    resolve_user_email,
)
from api.services.projects_fs import ensure_project_glb_async
from project_dates import (
    build_project_record,
    migrate_projects_data,
    migrate_projects_file,
    sort_projects_by_created,
)
from api.templates import render_template

router = APIRouter(tags=["projects"])


@router.get("/projects")
async def get_projects(x_user_email: str = Header(None)):
    projects_file = get_user_projects_file(x_user_email)
    if not os.path.exists(projects_file):
        return {"projects": []}
    user_dir = get_user_project_dir(x_user_email)
    migrate_projects_file(projects_file, user_dir)
    with open(projects_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    data["projects"] = sort_projects_by_created(data.get("projects") or [])
    return data


@router.get("/projects/glb/{project_name}")
async def get_project_glb(
    project_name: str,
    x_user_email: str = Header(None),
    key: str = Query(""),
    email: str = Query(""),
    sid: str = Query(""),
    folder: str = Query(""),
):
    try:
        user_email = resolve_user_email(x_user_email, key, email, sid)
        glb_path = await ensure_project_glb_async(user_email, project_name, folder)
        return FileResponse(glb_path, media_type="model/gltf-binary")
    except HTTPException as e:
        return JSONResponse({"detail": str(e.detail)}, status_code=e.status_code)


@router.post("/projects/save")
async def save_project(
    file: UploadFile = File(None),
    name: str = "",
    material: str = "",
    volume: float = 0,
    workpiece_type: str = "",
    diam: float = 0,
    length: float = 0,
    width: float = 0,
    height: float = 0,
    cost_per_hour: float = 2500,
    cost_per_unit: int = 0,
    total_cost: int = 0,
    machining_hours: str = "",
    x_user_email: str = Header(None),
):
    user_dir = get_user_project_dir(x_user_email)
    project_id = name.replace(" ", "_").replace("/", "_")
    step_path = os.path.join(user_dir, project_id, f"{project_id}.stp")
    step_changed = False
    if file:
        content = await file.read()
        if os.path.isfile(step_path):
            with open(step_path, "rb") as f:
                step_changed = f.read() != content
        else:
            step_changed = True
        if step_changed:
            os.makedirs(os.path.dirname(step_path), exist_ok=True)
            with open(step_path, "wb") as f:
                f.write(content)
    projects_file = os.path.join(user_dir, "projects.json")
    data = (
        json.load(open(projects_file, "r", encoding="utf-8"))
        if os.path.exists(projects_file)
        else {"projects": []}
    )
    import payment as pay

    pay.load_env()
    is_new_slot = pay.is_new_project_slot(x_user_email, name)
    gate = pay.can_create_new_project(x_user_email, is_new_project=is_new_slot)
    fields = {
        "name": name,
        "material": material,
        "volume": volume,
        "workpiece_type": workpiece_type,
        "diam": diam,
        "length": length,
        "width": width,
        "height": height,
        "cost_per_hour": cost_per_hour,
        "cost_per_unit": cost_per_unit,
        "total_cost": total_cost,
        "machining_hours": machining_hours,
    }
    existing_idx = next(
        (i for i, p in enumerate(data["projects"]) if p.get("name") == name),
        None,
    )
    existing = data["projects"][existing_idx] if existing_idx is not None else None
    record, changed = build_project_record(
        fields,
        existing=existing,
        user_dir=user_dir,
        is_new=existing is None,
        step_changed=step_changed,
    )
    if existing is None:
        data["projects"].append(record)
        changed = True
    elif changed:
        data["projects"][existing_idx] = record
    if changed:
        data["projects"] = sort_projects_by_created(data["projects"])
        with open(projects_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    access_state = gate.get("state") or {}
    if is_new_slot:
        access_state = pay.register_project_created(x_user_email, name)
    return {"status": "ok", "access": access_state}


@router.post("/projects/{project_name}/drawing")
async def upload_project_drawing(
    project_name: str,
    file: UploadFile = File(...),
    x_user_email: str = Header(None),
    email: str = Query(""),
    html: str = Query("0"),
):
    user_email = (x_user_email or email or "").strip()
    if not user_email:
        raise HTTPException(status_code=401, detail="Укажите email (заголовок или ?email=)")
    user_dir = get_user_project_dir(user_email)
    project_id = project_name.replace(" ", "_").replace("/", "_")
    project_dir = os.path.join(user_dir, project_id)
    os.makedirs(project_dir, exist_ok=True)
    content = await file.read()
    if not content or len(content) < 20:
        raise HTTPException(status_code=400, detail="Файл пустой или слишком маленький")
    fname = (file.filename or "").strip()
    if fname and not fname.lower().endswith(".pdf") and not content.startswith(b"%PDF"):
        raise HTTPException(status_code=400, detail="Нужен файл PDF")
    pdf_path = os.path.join(project_dir, f"{project_id}.pdf")
    with open(pdf_path, "wb") as f:
        f.write(content)
    result = {
        "ok": True,
        "size": len(content),
        "filename": fname or f"{project_id}.pdf",
        "path": pdf_path,
    }
    if str(html).lower() in ("1", "true", "yes"):
        kb = len(content) // 1024
        safe_name = (fname or project_id).replace("<", "")
        return HTMLResponse(
            render_template(
                "drawing_success.html",
                SAFE_NAME=safe_name,
                KB=str(kb),
            )
        )
    return result


@router.get("/projects/file/{project_name}")
async def get_project_file(project_name: str, x_user_email: str = Header(None)):
    user_dir = get_user_project_dir(x_user_email)
    safe_name = project_name.replace(" ", "_").replace("/", "_")
    step_path = os.path.join(user_dir, safe_name, f"{safe_name}.stp")
    if os.path.exists(step_path):
        return FileResponse(step_path, media_type="application/octet-stream")
    return JSONResponse({"error": "Файл не найден"}, status_code=404)


@router.delete("/projects/{project_name}")
async def delete_project(project_name: str, x_user_email: str = Header(None)):
    user_dir = get_user_project_dir(x_user_email)
    project_id = project_name.replace(" ", "_").replace("/", "_")
    project_dir = os.path.join(user_dir, project_id)
    if os.path.exists(project_dir):
        shutil.rmtree(project_dir)
    projects_file = os.path.join(user_dir, "projects.json")
    if os.path.exists(projects_file):
        data = json.load(open(projects_file, "r", encoding="utf-8"))
        data["projects"] = [p for p in data["projects"] if p.get("name") != project_name]
        with open(projects_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    return {"status": "ok"}


@router.put("/projects/{project_name}/rename")
async def rename_project(project_name: str, new_name: str, x_user_email: str = Header(None)):
    user_dir = get_user_project_dir(x_user_email)
    old_id = project_name.replace(" ", "_").replace("/", "_")
    new_id = new_name.replace(" ", "_").replace("/", "_")
    for ext in [".stp", ".glb"]:
        old_path = os.path.join(user_dir, f"{old_id}{ext}")
        new_path = os.path.join(user_dir, f"{new_id}{ext}")
        if os.path.exists(old_path):
            os.rename(old_path, new_path)
    projects_file = os.path.join(user_dir, "projects.json")
    if os.path.exists(projects_file):
        with open(projects_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        for p in data["projects"]:
            if p.get("name") == project_name:
                p["name"] = new_name
        with open(projects_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    return {"status": "ok"}
