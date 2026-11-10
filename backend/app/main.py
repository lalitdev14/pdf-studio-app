"""Application entry point:  uvicorn app.main:app"""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse

from . import __version__
from .api import build_routes
from .config import get_settings
from .setup import install

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(title="PDF Studio API", version=__version__, docs_url="/api/docs", openapi_url="/api/openapi.json")
    for path, methods, endpoint in build_routes():
        app.add_api_route(path, endpoint, methods=methods, include_in_schema=False)
    install(app)

    dist = s.frontend_dist
    if dist:
        index = dist / "index.html"

        async def spa(request: Request):
            rel = request.path_params.get("full_path", "")
            if rel.startswith("api/"):
                return JSONResponse({"error": {"code": "not_found", "message": "Not found"}}, status_code=404)
            target = (dist / rel).resolve()
            if rel and target.is_file() and dist.resolve() in target.parents:
                return FileResponse(target)
            return FileResponse(index)

        app.add_api_route("/{full_path:path}", spa, methods=["GET"], include_in_schema=False)
    return app


app = create_app()
