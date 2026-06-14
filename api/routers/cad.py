"""STEP conversion and analysis endpoints."""
import os
import sys
import tempfile

from fastapi import APIRouter, File, Header, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response

from api.auth_accounts import get_user_folder
from api.config import BASE_DIR
from api.services.step_convert import ensure_glb_from_stp, step_bytes_to_glb_response

router = APIRouter(tags=["cad"])

SHOWCASE_WHEEL_STP = (
    "/opt/sinlex/projects/sinlex_admin/100.020_-_Колесо_компрессора/"
    "100.020_-_Колесо_компрессора.stp"
)
SHOWCASE_WHEEL_GLB = os.path.join(BASE_DIR, "data", "showcase", "wheel-compressor.glb")


@router.get("/showcase/wheel-compressor.glb")
async def showcase_wheel_compressor_glb():
    os.makedirs(os.path.dirname(SHOWCASE_WHEEL_GLB), exist_ok=True)
    ensure_glb_from_stp(SHOWCASE_WHEEL_STP, SHOWCASE_WHEEL_GLB)
    return FileResponse(SHOWCASE_WHEEL_GLB, media_type="model/gltf-binary")


@router.post("/step-to-glb")
async def step_to_glb(file: UploadFile = File(...), x_user_email: str = Header(None)):
    get_user_folder(x_user_email)
    with tempfile.NamedTemporaryFile(delete=False, suffix=".stp") as tmp:
        content = await file.read()
        tmp.write(content)
        step_path = tmp.name
    glb_path = step_path.replace(".stp", ".glb")
    try:
        import json

        glb_data, volume, dims = step_bytes_to_glb_response(step_path, glb_path)
        response = Response(content=glb_data, media_type="model/gltf-binary")
        response.headers["X-Model-Volume"] = str(round(volume, 6))
        response.headers["X-Model-Dimensions"] = json.dumps(dims)
        return response
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    finally:
        for p in [step_path, glb_path]:
            if os.path.exists(p):
                os.unlink(p)


@router.post("/analyze-step")
async def analyze_step_endpoint(
    file: UploadFile = File(...),
    x_user_email: str = Header(None),
    casting: bool = Query(False, description="Литьё: всегда считать тонкостенность (OCC ray-casting)"),
):
    get_user_folder(x_user_email)
    content = await file.read()
    try:
        if BASE_DIR not in sys.path:
            sys.path.insert(0, BASE_DIR)
        from step_analyzer import analyze_step

        result = analyze_step(content, force_wall_thickness=casting)
        if result.get("error") and not result.get("volume"):
            raise HTTPException(status_code=500, detail=result["error"])
        dims = result.get("dimensions", {})
        ms = result.get("model_size") or {}
        if ms.get("format") == "rod" and ms.get("diameter"):
            result["main_dim"] = f"⌀{ms['diameter']:.0f} × {ms.get('length', 0):.0f} мм"
        else:
            result["main_dim"] = (
                f"{dims.get('x', 0):.0f} × {dims.get('y', 0):.0f} × {dims.get('z', 0):.0f} мм"
            )
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
