"""Middleware and error handlers shared by the FastAPI app and the test Starlette app."""
from __future__ import annotations

import logging

from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from .config import get_settings
from .errors import AppError
from .middleware import GuardMiddleware
from .state import get_services


async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    return JSONResponse({"error": exc.to_dict()}, status_code=exc.status)


async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    logging.getLogger("pdfstudio").exception("unhandled error on %s", request.url.path)
    return JSONResponse({"error": {"code": "internal_error", "message": "Something went wrong."}}, status_code=500)


def install(app) -> None:
    s = get_settings()
    svc = get_services()
    app.add_exception_handler(AppError, app_error_handler)
    app.add_exception_handler(Exception, unhandled_error_handler)
    app.add_middleware(GuardMiddleware, settings=s, limiter=svc.limiter)
    app.add_middleware(  # outermost, so 413/429 responses also carry CORS headers
        CORSMiddleware, allow_origins=list(s.cors_origins), allow_credentials=False,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"], allow_headers=["*"],
        expose_headers=["Content-Disposition"],
    )
