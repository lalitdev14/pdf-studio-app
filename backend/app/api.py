"""HTTP handlers and the route table.

Handlers are plain Starlette ``async def handler(request) -> Response`` functions.
``ROUTES`` is registered on FastAPI in ``main.py`` (and on a bare Starlette app in the
tests), so the whole API layer is framework-neutral and testable.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Awaitable, Callable

from pydantic import ValidationError
from starlette.background import BackgroundTask
from starlette.datastructures import UploadFile
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response

from . import __version__
from .errors import (
    AppError, Forbidden, InvalidRequest, NotFound, TooLarge, Unauthorized, UnsupportedFormat,
)
from .jobs import Job
from .services import OPERATIONS, OpSpec
from .services.common import unique_name
from .services.inspect_pdf import pdf_info, render_thumbnail, text_lines
from .signing import sign_download, verify_download
from .state import Services, get_services
from .storage import FileRecord
from .validation import safe_name, sniff

Handler = Callable[[Request], Awaitable[Response]]


# ------------------------------------------------------------------ utilities
def svc() -> Services:
    return get_services()


def public_file(s: Services, rec: FileRecord) -> dict:
    exp, sig = sign_download(s.settings.secret_key, rec.id, s.settings.download_link_ttl_seconds)
    return {
        "id": rec.id, "name": rec.name, "size": rec.size, "kind": rec.kind, "mime": rec.mime,
        "url": f"/api/files/{rec.id}/download?exp={exp}&sig={sig}", "expires": exp,
    }


def public_job(s: Services, job: Job) -> dict:
    d = job.snapshot()
    for o in d["outputs"]:
        exp, sig = sign_download(s.settings.secret_key, o["id"], s.settings.download_link_ttl_seconds)
        o["url"] = f"/api/files/{o['id']}/download?exp={exp}&sig={sig}"
    return d


def ok(data, status: int = 200) -> JSONResponse:
    return JSONResponse(data, status_code=status)


async def read_json(request: Request, limit: int = 64 * 1024) -> dict:
    body = bytearray()
    async for chunk in request.stream():
        body += chunk
        if len(body) > limit:
            raise TooLarge("The request body is too large.")
    try:
        data = json.loads(bytes(body) or b"{}")
    except (ValueError, UnicodeDecodeError) as exc:
        raise InvalidRequest("The request body is not valid JSON.", "invalid_json") from exc
    if not isinstance(data, dict):
        raise InvalidRequest("The request body must be a JSON object.", "invalid_json")
    return data


def current_user(request: Request) -> dict | None:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return svc().auth.user_from_token(auth[7:].strip())
    return None


def require_user(request: Request) -> dict:
    user = current_user(request)
    if not user:
        raise Unauthorized()
    return user


def friendly_validation(exc: ValidationError) -> str:
    parts = []
    for e in exc.errors()[:4]:
        loc = ".".join(str(x) for x in e["loc"] if x != "__root__")
        msg = e["msg"].removeprefix("Value error, ")
        parts.append(f"{loc}: {msg}" if loc else msg)
    return "; ".join(parts)


async def save_upload(s: Services, up: UploadFile, max_bytes: int) -> FileRecord:
    name = safe_name(up.filename, "upload")
    file_id, blob = s.store.begin()
    digest, size = hashlib.sha256(), 0
    try:
        with open(blob, "wb") as f:
            while True:
                chunk = await up.read(1 << 20)
                if not chunk:
                    break
                size += len(chunk)
                if size > max_bytes:
                    raise TooLarge(f"'{name}' is larger than the {max_bytes // (1024 * 1024)} MB file limit.")
                digest.update(chunk)
                f.write(chunk)
        if size == 0:
            raise InvalidRequest(f"'{name}' is empty.", "empty_file")
        kind = sniff(blob, name)
        if not kind:
            raise UnsupportedFormat(
                f"'{name}' is not a supported file type. Supported: PDF, JPG, PNG, WEBP, BMP, TIFF, HEIC, "
                "Word, Excel and PowerPoint documents."
            )
        return s.store.commit(file_id, name, size, kind, digest.hexdigest(), "upload")
    except BaseException:
        s.store.abort(file_id)
        raise


async def read_uploads(request: Request, s: Services) -> tuple[list[FileRecord], dict, list[str]]:
    """Parse a multipart request -> (new upload records, form fields, file_ids)."""
    ctype = request.headers.get("content-type", "")
    if not ctype.startswith("multipart/form-data"):
        raise InvalidRequest("Send the files as multipart/form-data.", "invalid_content_type")
    form = await request.form(max_files=s.settings.max_files_per_request, max_fields=40, max_part_size=16 * 1024 * 1024)
    saved: list[FileRecord] = []
    try:
        total = 0
        for up in form.getlist("files"):
            if not isinstance(up, UploadFile):
                continue
            rec = await save_upload(s, up, s.settings.max_file_bytes)
            saved.append(rec)
            total += rec.size
            if total > s.settings.max_request_bytes:
                raise TooLarge(f"The upload is larger than the {s.settings.max_request_mb} MB request limit.")
        fields = {k: v for k, v in form.items() if isinstance(v, str)}
        return saved, fields, []
    except BaseException:
        for r in saved:
            s.store.abort(r.id)
        raise
    finally:
        await form.close()


# ------------------------------------------------------------------ health
async def health(request: Request) -> Response:
    s = svc().settings
    have = lambda mod: importlib.util.find_spec(mod) is not None  # noqa: E731
    return ok({
        "status": "ok", "version": __version__,
        "limits": {"max_file_mb": s.max_file_mb, "max_request_mb": s.max_request_mb,
                   "max_files": s.max_files_per_request, "max_pages": s.max_pages,
                   "file_ttl_minutes": s.file_ttl_minutes},
        "features": {
            "ocr": bool(shutil.which("tesseract")),
            "office": bool(shutil.which("soffice") or shutil.which("libreoffice")),
            "replace_text": have("fitz"),
            "digital_signature": have("pyhanko"),
            "heic": have("pillow_heif"),
        },
    })


# ------------------------------------------------------------------- files
async def upload_files(request: Request) -> Response:
    s = svc()
    saved, _, _ = await read_uploads(request, s)
    if not saved:
        raise InvalidRequest("No files were uploaded.", "no_files")
    return ok({"files": [public_file(s, r) for r in saved]}, 201)


async def file_info(request: Request) -> Response:
    s = svc()
    rec = s.store.get(request.path_params["file_id"])
    data = public_file(s, rec)
    if rec.kind == "pdf":
        data.update(pdf_info(rec.path))
    return ok(data)


async def file_download(request: Request) -> Response:
    s = svc()
    fid = request.path_params["file_id"]
    q = request.query_params
    if not verify_download(s.settings.secret_key, fid, q.get("exp"), q.get("sig")):
        raise Forbidden("This download link is invalid or has expired.", "invalid_link")
    rec = s.store.get(fid)
    inline = q.get("inline") == "1" and (rec.kind == "pdf" or rec.kind in ("png", "jpeg", "webp"))
    return FileResponse(
        rec.path, media_type=rec.mime, filename=rec.name,
        content_disposition_type="inline" if inline else "attachment",
        headers={"Cache-Control": "private, max-age=300"},
    )


async def file_delete(request: Request) -> Response:
    s = svc()
    fid = request.path_params["file_id"]
    q = request.query_params
    if not verify_download(s.settings.secret_key, fid, q.get("exp"), q.get("sig")):
        raise Forbidden("This link is invalid or has expired.", "invalid_link")
    s.store.delete(fid)
    return ok({"deleted": fid})


async def page_thumbnail(request: Request) -> Response:
    s = svc()
    fid = request.path_params["file_id"]
    rec = s.store.get(fid)
    if rec.kind != "pdf":
        raise InvalidRequest("Thumbnails are only available for PDF files.")
    try:
        page = int(request.path_params["page"])
        width = int(request.query_params.get("width", 220))
    except ValueError as exc:
        raise InvalidRequest("Invalid page or width.") from exc
    if page < 1:
        raise InvalidRequest("Pages start at 1.")
    path = render_thumbnail(rec.path, page, width, s.store.aux_dir(fid, "thumbs"))
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=3600"})


async def page_text_lines(request: Request) -> Response:
    s = svc()
    rec = s.store.get(request.path_params["file_id"])
    if rec.kind != "pdf":
        raise InvalidRequest("Only PDF files have text lines.")
    page = int(request.path_params["page"]) if str(request.path_params["page"]).isdigit() else 0
    if page < 1:
        raise InvalidRequest("Pages start at 1.")
    return ok(text_lines(rec.path, page))


# -------------------------------------------------------------- operations
async def _parse_op_request(request: Request, s: Services) -> tuple[list[FileRecord], list[str], dict]:
    """-> (new uploads, referenced file ids, raw options)."""
    ctype = request.headers.get("content-type", "")
    if ctype.startswith("application/json"):
        data = await read_json(request, limit=40 * 1024 * 1024)
        ids = data.get("file_ids") or []
        opts = data.get("options") or {}
        if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids) or not isinstance(opts, dict):
            raise InvalidRequest("file_ids must be a list of strings and options an object.", "invalid_request")
        return [], ids, opts
    saved, fields, _ = await read_uploads(request, s)
    try:
        ids = json.loads(fields.get("file_ids") or "[]")
        opts = json.loads(fields.get("options") or "{}")
        if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids) or not isinstance(opts, dict):
            raise ValueError
    except ValueError as exc:
        for r in saved:
            s.store.abort(r.id)
        raise InvalidRequest("file_ids must be a JSON list and options a JSON object.", "invalid_request") from exc
    return saved, ids, opts


def make_op_handler(spec: OpSpec) -> Handler:
    async def handler(request: Request) -> Response:
        s = svc()
        user = current_user(request)
        uploads, ids, raw = await _parse_op_request(request, s)
        try:
            records = [s.store.get(i) for i in ids] + uploads
            if len(records) < spec.min_files or len(records) > spec.max_files:
                want = f"{spec.min_files}" if spec.min_files == spec.max_files else f"{spec.min_files}-{spec.max_files}"
                raise InvalidRequest(f"This tool needs {want} file(s); you sent {len(records)}.", "wrong_file_count")
            for i, rec in enumerate(records):
                allowed = spec.first if i == 0 else (spec.rest or spec.first)
                if rec.kind not in allowed:
                    raise UnsupportedFormat(
                        f"'{rec.name}' is a {rec.kind.upper()} file, but this tool needs {' / '.join(sorted(allowed)).upper()}."
                    )
            try:
                options = spec.model.model_validate(raw).model_dump()
            except ValidationError as exc:
                raise InvalidRequest(friendly_validation(exc), "invalid_options") from exc
        except BaseException:
            for r in uploads:
                s.store.abort(r.id)
            raise
        job = s.jobs.submit(spec, records, options, owner=user["id"] if user else None)
        return ok(public_job(s, job), 202)

    return handler


# -------------------------------------------------------------------- jobs
def _job_or_404(s: Services, job_id: str) -> Job:
    job = s.jobs.get(job_id)
    if not job:
        raise NotFound("Job not found or expired.", "job_not_found")
    return job


async def job_status(request: Request) -> Response:
    s = svc()
    return ok(public_job(s, _job_or_404(s, request.path_params["job_id"])))


async def job_cancel(request: Request) -> Response:
    s = svc()
    _job_or_404(s, request.path_params["job_id"])
    return ok(public_job(s, s.jobs.cancel(request.path_params["job_id"])))


async def job_zip(request: Request) -> Response:
    s = svc()
    job = _job_or_404(s, request.path_params["job_id"])
    if job.status != "done" or not job.outputs:
        raise InvalidRequest("This job has no finished files to download.", "job_not_done")
    fd, tmp_name = tempfile.mkstemp(suffix=".zip", dir=s.settings.work_dir)
    os.close(fd)
    used: set[str] = set()
    with zipfile.ZipFile(tmp_name, "w", zipfile.ZIP_DEFLATED) as z:
        for o in job.outputs:
            rec = s.store.get(o["id"])
            z.write(rec.path, unique_name(used, rec.name))
    return FileResponse(
        tmp_name, media_type="application/zip", filename=f"pdf-studio-{job.op}.zip",
        background=BackgroundTask(lambda: Path(tmp_name).unlink(missing_ok=True)),
    )


# -------------------------------------------------------------------- auth
async def auth_register(request: Request) -> Response:
    d = await read_json(request)
    return ok(svc().auth.register(str(d.get("email", "")), str(d.get("password", ""))), 201)


async def auth_login(request: Request) -> Response:
    d = await read_json(request)
    return ok(svc().auth.login(str(d.get("email", "")), str(d.get("password", ""))))


async def auth_me(request: Request) -> Response:
    return ok({"user": require_user(request)})


async def auth_forgot(request: Request) -> Response:
    s = svc()
    d = await read_json(request)
    token = s.auth.request_reset(str(d.get("email", "")))
    body: dict = {"message": "If that email has an account, a reset link has been sent."}
    if token and s.settings.expose_reset_token:  # development only: no mail server is bundled
        body["dev_reset_token"] = token
    return ok(body)


async def auth_reset(request: Request) -> Response:
    d = await read_json(request)
    svc().auth.reset_password(str(d.get("token", "")), str(d.get("password", "")))
    return ok({"message": "Password updated. You can sign in now."})


async def auth_password(request: Request) -> Response:
    u = require_user(request)
    d = await read_json(request)
    return ok(svc().auth.change_password(u["id"], str(d.get("old_password", "")), str(d.get("new_password", ""))))


async def auth_delete(request: Request) -> Response:
    u = require_user(request)
    d = await read_json(request)
    svc().auth.delete_account(u["id"], str(d.get("password", "")))
    return ok({"deleted": True})


async def me_history(request: Request) -> Response:
    return ok({"items": svc().auth.list_history(require_user(request)["id"])})


async def me_history_clear(request: Request) -> Response:
    svc().auth.clear_history(require_user(request)["id"])
    return ok({"cleared": True})


async def me_files(request: Request) -> Response:
    return ok({"files": svc().auth.list_saved(require_user(request)["id"])})


async def me_files_save(request: Request) -> Response:
    s = svc()
    u = require_user(request)
    d = await read_json(request)
    rec = s.store.get(str(d.get("file_id", "")))
    return ok(s.auth.save_file(u["id"], rec.path, rec.id, rec.name, rec.size, rec.kind), 201)


async def me_files_open(request: Request) -> Response:
    """Copy a saved file back into the temporary store so tools/editor can use it."""
    s = svc()
    u = require_user(request)
    path, row = s.auth.saved_path(u["id"], request.path_params["file_id"])
    file_id, blob = s.store.begin()
    shutil.copyfile(path, blob)
    with open(blob, "rb") as fh:
        digest = hashlib.file_digest(fh, "sha256").hexdigest()
    rec = s.store.commit(file_id, row["name"], row["size"], row["kind"], digest, "upload")
    return ok(public_file(s, rec), 201)


async def me_files_download(request: Request) -> Response:
    s = svc()
    u = require_user(request)
    path, row = s.auth.saved_path(u["id"], request.path_params["file_id"])
    return FileResponse(path, filename=row["name"], media_type="application/octet-stream")


async def me_files_delete(request: Request) -> Response:
    s = svc()
    s.auth.delete_saved(require_user(request)["id"], request.path_params["file_id"])
    return ok({"deleted": True})


# ------------------------------------------------------------ route table
def build_routes() -> list[tuple[str, list[str], Handler]]:
    routes: list[tuple[str, list[str], Handler]] = [
        ("/api/health", ["GET"], health),
        ("/api/files", ["POST"], upload_files),
        ("/api/files/{file_id}/info", ["GET"], file_info),
        ("/api/files/{file_id}/download", ["GET"], file_download),
        ("/api/files/{file_id}", ["DELETE"], file_delete),
        ("/api/files/{file_id}/pages/{page}/thumbnail", ["GET"], page_thumbnail),
        ("/api/files/{file_id}/pages/{page}/text-lines", ["GET"], page_text_lines),
        ("/api/jobs/{job_id}", ["GET"], job_status),
        ("/api/jobs/{job_id}/cancel", ["POST"], job_cancel),
        ("/api/jobs/{job_id}/zip", ["GET"], job_zip),
        ("/api/auth/register", ["POST"], auth_register),
        ("/api/auth/login", ["POST"], auth_login),
        ("/api/auth/me", ["GET"], auth_me),
        ("/api/auth/forgot", ["POST"], auth_forgot),
        ("/api/auth/reset", ["POST"], auth_reset),
        ("/api/auth/password", ["POST"], auth_password),
        ("/api/auth/account", ["DELETE"], auth_delete),
        ("/api/me/history", ["GET"], me_history),
        ("/api/me/history", ["DELETE"], me_history_clear),
        ("/api/me/files", ["GET"], me_files),
        ("/api/me/files", ["POST"], me_files_save),
        ("/api/me/files/{file_id}/open", ["POST"], me_files_open),
        ("/api/me/files/{file_id}/download", ["GET"], me_files_download),
        ("/api/me/files/{file_id}", ["DELETE"], me_files_delete),
    ]
    for spec in OPERATIONS.values():
        routes.append((spec.path, ["POST"], make_op_handler(spec)))
    return routes
