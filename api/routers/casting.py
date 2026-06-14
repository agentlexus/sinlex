"""Casting project CRUD (separate from 3D /projects)."""
import json
import os
import shutil

from fastapi import APIRouter, File, Header, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from api.auth_accounts import get_user_casting_dir, get_user_casting_file, resolve_user_email
from api.services.casting_fs import ensure_casting_glb, ensure_casting_stock_glb, resolve_casting_project_dir, user_casting_dir
from project_dates import build_project_record, migrate_projects_file, sort_projects_by_created

router = APIRouter(tags=["casting"])


@router.get("/casting/projects")
async def get_casting_projects(x_user_email: str = Header(None)):
    projects_file = get_user_casting_file(x_user_email)
    if not os.path.exists(projects_file):
        return {"projects": []}
    user_dir = get_user_casting_dir(x_user_email)
    os.makedirs(user_dir, exist_ok=True)
    migrate_projects_file(projects_file, user_dir)
    with open(projects_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    data["projects"] = sort_projects_by_created(data.get("projects") or [])
    return data


@router.get("/casting/glb/{project_name}")
async def get_casting_glb(
    project_name: str,
    x_user_email: str = Header(None),
    key: str = Query(""),
    email: str = Query(""),
    sid: str = Query(""),
    folder: str = Query(""),
):
    try:
        user_email = resolve_user_email(x_user_email, key, email, sid)
        glb_path = ensure_casting_glb(user_email, project_name, folder)
        return FileResponse(glb_path, media_type="model/gltf-binary")
    except HTTPException as e:
        return JSONResponse({"detail": str(e.detail)}, status_code=e.status_code)




@router.get("/casting/stock-glb/{project_name}")
async def get_casting_stock_glb(
    project_name: str,
    allowance_mm: float = Query(..., gt=0),
    x_user_email: str = Header(None),
    key: str = Query(""),
    email: str = Query(""),
    sid: str = Query(""),
    folder: str = Query(""),
):
    try:
        user_email = resolve_user_email(x_user_email, key, email, sid)
        glb_path = ensure_casting_stock_glb(user_email, project_name, allowance_mm, folder)
        return FileResponse(glb_path, media_type="model/gltf-binary")
    except HTTPException as e:
        return JSONResponse({"detail": str(e.detail)}, status_code=e.status_code)

@router.post("/casting/save")
async def save_casting_project(
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
    casting_type: str = "",
    casting_material: str = "",
    shrink_pct: float = 0,
    allowance_mm: float = 0,
    batch_size: int = 1,
    x_user_email: str = Header(None),
):
    user_dir = get_user_casting_dir(x_user_email)
    os.makedirs(user_dir, exist_ok=True)
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
            from casting_stock_glb import invalidate_stock_glbs
            invalidate_stock_glbs(os.path.dirname(step_path))
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
        "casting_type": casting_type or "ЛПД",
        "casting_material": casting_material or material,
        "shrink_pct": shrink_pct,
        "allowance_mm": allowance_mm,
        "batch_size": max(1, int(batch_size or 1)),
        "project_type": "casting",
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
    record["project_type"] = "casting"
    record["batch_size"] = max(1, int(batch_size or 1))
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

    try:
        from project_store import merge_user_fields, save_project_data
        from api.auth_accounts import get_user_folder
        folder = get_user_folder(x_user_email=x_user_email)
        existing = {}
        data_path_dir = os.path.join(user_dir, project_id)
        data_txt = os.path.join(data_path_dir, "data.txt")
        if os.path.isfile(data_txt):
            from project_store import load_project_data
            existing = load_project_data(name, folder, storage="casting")
        rec = merge_user_fields(
            existing,
            material=casting_material or material,
            casting_type=casting_type or "ЛПД",
            casting_material=casting_material or material,
            shrink_pct=shrink_pct or None,
            allowance_mm=allowance_mm or None,
            batch_size=max(1, int(batch_size or 1)),
            volume=volume,
        )
        save_project_data(name, rec, folder, storage="casting")
        from casting_io import write_casting_artifacts
        write_casting_artifacts(
            name,
            folder,
            meta={
                "casting_type": casting_type or "ЛПД",
                "casting_material": casting_material or material,
                "shrink_pct": shrink_pct,
                "allowance_mm": allowance_mm,
                "batch_size": max(1, int(batch_size or 1)),
            },
            costing={"total_cost": int(total_cost), "cost_per_unit": int(cost_per_unit)},
        )
    except Exception:
        pass

    if is_new_slot:
        access_state = pay.register_project_created(x_user_email, name)
    return {"status": "ok", "access": access_state}


@router.get("/casting/file/{project_name}")
async def get_casting_file(project_name: str, x_user_email: str = Header(None)):
    user_dir = get_user_casting_dir(x_user_email)
    safe_name, pdir = resolve_casting_project_dir(user_dir, project_name)
    step_path = os.path.join(pdir, f"{safe_name}.stp")
    if os.path.exists(step_path):
        return FileResponse(step_path, media_type="application/octet-stream")
    return JSONResponse({"error": "Файл не найден"}, status_code=404)


@router.delete("/casting/{project_name}")
async def delete_casting_project(project_name: str, x_user_email: str = Header(None)):
    user_dir = get_user_casting_dir(x_user_email)
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
