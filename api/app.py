"""FastAPI application factory for Sinlex visual API."""
import os

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from api.config import API_KEY, BASE_DIR
from api.routers import analysis, auth, cad, casting, embed, flow_norm, hybrid_analysis, payments, projects
from api.three_static import ensure_three_static

ensure_three_static()


def create_app() -> FastAPI:
    app = FastAPI()

    @app.get("/")
    async def api_root():
        return RedirectResponse(url="https://sinlex.tech/", status_code=302)

    static_dir = os.path.join(BASE_DIR, "static")
    if os.path.isdir(static_dir):
        app.mount("/static", StaticFiles(directory=static_dir), name="static")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def check_api_key(request: Request, call_next):
        if request.method == "OPTIONS":
            return await call_next(request)
        path = request.url.path
        if path in ("/", "") or path.startswith("/docs") or path.startswith("/openapi.json"):
            return await call_next(request)
        if path.startswith("/auth"):
            return await call_next(request)
        if path.startswith("/embed/") or path.startswith("/static/"):
            return await call_next(request)
        if path.startswith("/payments/webhook/"):
            return await call_next(request)
        if path.startswith("/projects/glb/") and request.query_params.get("key") == API_KEY:
            return await call_next(request)
        if path.startswith("/casting/glb/") and request.query_params.get("key") == API_KEY:
            return await call_next(request)
        if path.startswith("/casting/stock-glb/") and request.query_params.get("key") == API_KEY:
            return await call_next(request)
        if path.endswith("/drawing") and request.method == "POST":
            qkey = request.query_params.get("key") or ""
            if qkey == API_KEY:
                return await call_next(request)
        api_key = request.headers.get("X-API-Key") or request.query_params.get("key") or ""
        if api_key != API_KEY:
            return JSONResponse(content={"detail": "Unauthorized"}, status_code=401)
        return await call_next(request)

    @app.middleware("http")
    async def embed_frame_headers(request: Request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/embed/"):
            response.headers["Content-Security-Policy"] = (
                "frame-ancestors 'self' https://sinlex.tech https://www.sinlex.tech http://* https://*"
            )
        return response

    app.include_router(auth.router)
    app.include_router(cad.router)
    app.include_router(analysis.router)
    app.include_router(hybrid_analysis.router)
    app.include_router(flow_norm.router)
    app.include_router(projects.router)
    app.include_router(casting.router)
    app.include_router(embed.router)
    app.include_router(payments.router)

    return app


app = create_app()
