"""Minimal ASGI test client (no httpx needed) and an app factory.

The route table is the same one FastAPI gets in main.py; here it is mounted on a bare
Starlette app so the full HTTP layer (multipart parsing, middleware, jobs, downloads)
is exercised end to end.
"""
from __future__ import annotations

import asyncio
import json as jsonlib
import os
import time
import uuid
from urllib.parse import urlsplit

from starlette.applications import Starlette
from starlette.routing import Route


def build_app(**env):
    for k, v in env.items():
        os.environ[k] = str(v)
    from app import config
    from app.api import build_routes
    from app.setup import install
    from app.state import reset_services

    reset_services()
    config.reset_settings()
    app = Starlette(routes=[Route(p, e, methods=m) for p, m, e in build_routes()])
    install(app)
    return app


class Resp:
    def __init__(self, status: int, headers: dict[str, str], body: bytes):
        self.status, self.headers, self.body = status, headers, body

    def json(self):
        return jsonlib.loads(self.body)

    @property
    def error(self) -> dict:
        return self.json()["error"]


def multipart(fields: dict[str, str] | None, files: list[tuple[str, str, bytes]] | None) -> tuple[bytes, str]:
    boundary = "----pdfstudio" + uuid.uuid4().hex
    out = bytearray()
    for k, v in (fields or {}).items():
        out += f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
    for field, filename, data in files or []:
        out += (f'--{boundary}\r\nContent-Disposition: form-data; name="{field}"; filename="{filename}"\r\n'
                "Content-Type: application/octet-stream\r\n\r\n").encode() + data + b"\r\n"
    out += f"--{boundary}--\r\n".encode()
    return bytes(out), f"multipart/form-data; boundary={boundary}"


class Client:
    def __init__(self, app, ip: str = "10.0.0.1"):
        self.app, self.ip = app, ip

    def request(self, method: str, url: str, *, json=None, files=None, fields=None, headers=None, raw=None) -> Resp:
        parts = urlsplit(url)
        hdrs = {k.lower(): v for k, v in (headers or {}).items()}
        body = b""
        if json is not None:
            body, hdrs["content-type"] = jsonlib.dumps(json).encode(), "application/json"
        elif files is not None or fields is not None:
            body, hdrs["content-type"] = multipart(fields, files)
        elif raw is not None:
            body = raw
        hdrs["content-length"] = str(len(body))
        scope = {
            "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": method,
            "path": parts.path, "raw_path": parts.path.encode(), "query_string": parts.query.encode(),
            "headers": [(k.encode(), v.encode()) for k, v in hdrs.items()], "client": (self.ip, 1234),
            "server": ("test", 80), "scheme": "http", "root_path": "",
        }

        async def run() -> Resp:
            sent = False
            status, rheaders, chunks = 0, {}, []

            async def receive():
                nonlocal sent
                if not sent:
                    sent = True
                    return {"type": "http.request", "body": body, "more_body": False}
                await asyncio.sleep(3600)
                return {"type": "http.disconnect"}

            async def send(msg):
                nonlocal status
                if msg["type"] == "http.response.start":
                    status = msg["status"]
                    rheaders.update({k.decode().lower(): v.decode() for k, v in msg["headers"]})
                elif msg["type"] == "http.response.body":
                    chunks.append(msg.get("body", b""))

            await self.app(scope, receive, send)
            return Resp(status, rheaders, b"".join(chunks))

        return asyncio.run(run())

    def get(self, url, **kw):
        return self.request("GET", url, **kw)

    def post(self, url, **kw):
        return self.request("POST", url, **kw)

    def delete(self, url, **kw):
        return self.request("DELETE", url, **kw)

    # ------------------------------------------------------------ conveniences
    def upload(self, name: str, data: bytes) -> dict:
        r = self.post("/api/files", files=[("files", name, data)])
        assert r.status == 201, r.body
        return r.json()["files"][0]

    def run(self, path: str, files=None, ids=None, options=None, headers=None, wait=True, timeout=120) -> dict:
        if files is not None:
            r = self.post(path, files=[("files", n, d) for n, d in files],
                          fields={"options": jsonlib.dumps(options or {}), "file_ids": jsonlib.dumps(ids or [])},
                          headers=headers)
        else:
            r = self.post(path, json={"file_ids": ids or [], "options": options or {}}, headers=headers)
        assert r.status == 202, (r.status, r.body)
        job = r.json()
        return self.wait(job["id"], timeout) if wait else job

    def wait(self, job_id: str, timeout=120) -> dict:
        end = time.time() + timeout
        while time.time() < end:
            job = self.get(f"/api/jobs/{job_id}").json()
            if job["status"] in ("done", "failed", "cancelled"):
                return job
            time.sleep(0.05)
        raise TimeoutError(job_id)
