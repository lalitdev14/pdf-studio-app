"""Signed download links, auth tokens and the rate limiter. Standard library only."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import threading
import time
from collections import defaultdict, deque


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _mac(secret: str, message: str) -> str:
    return _b64(hmac.new(secret.encode(), message.encode(), hashlib.sha256).digest())


# ---------------------------------------------------------------- download links
def sign_download(secret: str, file_id: str, ttl_seconds: int, now: float | None = None) -> tuple[int, str]:
    exp = int((now if now is not None else time.time()) + ttl_seconds)
    return exp, _mac(secret, f"dl.{file_id}.{exp}")


def verify_download(secret: str, file_id: str, exp: str | int | None, sig: str | None,
                    now: float | None = None) -> bool:
    try:
        exp_i = int(exp)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False
    if not sig or exp_i < (now if now is not None else time.time()):
        return False
    return hmac.compare_digest(_mac(secret, f"dl.{file_id}.{exp_i}"), sig)


# ------------------------------------------------------------------- auth tokens
def make_token(secret: str, payload: dict, ttl_seconds: int, now: float | None = None) -> str:
    body = dict(payload)
    body["exp"] = int((now if now is not None else time.time()) + ttl_seconds)
    raw = _b64(json.dumps(body, separators=(",", ":")).encode())
    return f"{raw}.{_mac(secret, 'tok.' + raw)}"


def read_token(secret: str, token: str | None, now: float | None = None) -> dict | None:
    if not token or "." not in token:
        return None
    raw, _, sig = token.partition(".")
    if not hmac.compare_digest(_mac(secret, "tok." + raw), sig):
        return None
    try:
        body = json.loads(_unb64(raw))
    except (ValueError, json.JSONDecodeError):
        return None
    if not isinstance(body, dict) or body.get("exp", 0) < (now if now is not None else time.time()):
        return None
    return body


# ------------------------------------------------------------------ rate limiting
class RateLimiter:
    """Sliding-window limiter, per key, in memory (use Redis for multi-process)."""

    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str, limit: int, window: float = 60.0, now: float | None = None) -> tuple[bool, float]:
        t = now if now is not None else time.monotonic()
        with self._lock:
            q = self._hits[key]
            while q and q[0] <= t - window:
                q.popleft()
            if len(q) >= limit:
                return False, max(0.0, window - (t - q[0]))
            q.append(t)
            if len(self._hits) > 20000:  # crude memory guard
                self._prune(t, window)
            return True, 0.0

    def _prune(self, t: float, window: float) -> None:
        for k in [k for k, q in self._hits.items() if not q or q[-1] <= t - window]:
            self._hits.pop(k, None)
