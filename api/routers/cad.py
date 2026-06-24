"""STEP conversion and analysis endpoints."""
import asyncio
import os
import sys
import tempfile

from fastapi import APIRouter, File, Header, HTTPException, Query, UploadFile
from fastapi.responses import Response

from api.auth_accounts import get_user_folder
from api.config import BASE_DIR
from api.services.cad_executor import run_cad
from api.services.step_convert import step_bytes_to_glb_response
from page_modules.upload_limits import STEP_ANALYZE_TIMEOUT_SEC, STEP_GLB_TIMEOUT_SEC

router = APIRouter(tags=["cad"])

_STEP_TIMEOUT_DETAIL = "Превышено время обработки STEP"


def _analyze_step_bytes(content: bytes, *, casting: bool) -> dict:
    if BASE_DIR not in sys.path:
        sys.path.insert(0, BASE_DIR)
    from step_analyzer import analyze_step

    return analyze_step(content, force_wall_thickness=casting)


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

        glb_data, volume, dims = await run_cad(
            step_bytes_to_glb_response,
            step_path,
            glb_path,
            timeout=STEP_GLB_TIMEOUT_SEC,
        )
        response = Response(content=glb_data, media_type="model/gltf-binary")
        response.headers["X-Model-Volume"] = str(round(volume, 6))
        response.headers["X-Model-Dimensions"] = json.dumps(dims)
        return response
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail=_STEP_TIMEOUT_DETAIL) from None
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
        result = await run_cad(
            _analyze_step_bytes,
            content,
            casting=casting,
            timeout=STEP_ANALYZE_TIMEOUT_SEC,
        )
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
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail=_STEP_TIMEOUT_DETAIL) from None
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
