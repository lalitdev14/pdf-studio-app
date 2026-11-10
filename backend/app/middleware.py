"""ASGI middleware: rate limiting, request-size guard and security headers."""
from __future__ import annotations

from starlette.responses import JSONResponse

from .config import Settings
from .signing import RateLimiter

CSP = (
    "default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; "
    "script-src 'self'; worker-src 'self' blob:; connect-src 'self' blob:; object-src 'none'; "
    "frame-ancestors 'none'; base-uri 'self'"
)
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def client_ip(scope, trust_proxy: bool) -> str:
    if trust_proxy:
        for k, v in scope.get("headers", []):
            if k == b"x-forwarded-for":
                return v.decode("latin-1").split(",")[0].strip()
    client = scope.get("client")
    return client[0] if client else "unknown"


class GuardMiddleware:
    def __init__(self, app, settings: Settings, limiter: RateLimiter):
        self.app, self.s, self.limiter = app, settings, limiter

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        path, method = scope["path"], scope["method"]
        is_api = path.startswith("/api/")
        if is_api and method != "OPTIONS":
            ip = client_ip(scope, self.s.trust_proxy)
            mutating = method not in SAFE_METHODS
            limit = self.s.rate_limit_mutating_per_min if mutating else self.s.rate_limit_read_per_min
            ok, retry = self.limiter.allow(f"{'w' if mutating else 'r'}:{ip}", limit)
            if not ok:
                resp = JSONResponse(
                    {"error": {"code": "rate_limited", "message": "Too many requests. Please wait a moment and try again."}},
                    status_code=429, headers={"Retry-After": str(int(retry) + 1)},
                )
                return await resp(scope, receive, send)
            if mutating:
                for k, v in scope.get("headers", []):
                    if k == b"content-length":
                        try:
                            too_big = int(v) > self.s.max_request_bytes + 1_000_000
                        except ValueError:
                            too_big = True
                        if too_big:
                            resp = JSONResponse(
                                {"error": {"code": "too_large", "message": f"The upload is larger than the {self.s.max_request_mb} MB request limit."}},
                                status_code=413,
                            )
                            return await resp(scope, receive, send)

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                present = {k.lower() for k, _ in headers}

                def add(name: bytes, value: str):
                    if name not in present:
                        headers.append((name, value.encode()))

                add(b"x-content-type-options", "nosniff")
                add(b"referrer-policy", "no-referrer")
                add(b"x-frame-options", "DENY")
                if is_api:
                    add(b"cache-control", "no-store")
                else:
                    add(b"content-security-policy", CSP)
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_wrapper)
