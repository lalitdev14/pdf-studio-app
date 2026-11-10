"""Process-wide services (settings, file store, job manager, auth) plus the expiry sweeper."""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass

from .auth import AuthService
from .config import Settings, get_settings
from .jobs import Job, JobManager
from .signing import RateLimiter
from .storage import FileStore

log = logging.getLogger("pdfstudio")


@dataclass
class Services:
    settings: Settings
    store: FileStore
    jobs: JobManager
    auth: AuthService
    limiter: RateLimiter
    stop: threading.Event


_services: Services | None = None
_lock = threading.Lock()


def get_services() -> Services:
    global _services
    with _lock:
        if _services is None:
            s = get_settings()
            store = FileStore(s.files_dir, s.file_ttl_seconds)
            auth = AuthService(s)

            def on_finish(job: Job) -> None:
                if job.owner is not None and job.status in ("done", "failed"):
                    auth.add_history(job.owner, job.op, job.status, job.outputs)

            _services = Services(s, store, JobManager(store, s, on_finish), auth, RateLimiter(), threading.Event())
            threading.Thread(target=_sweeper, args=(_services,), name="sweeper", daemon=True).start()
        return _services


def _sweeper(svc: Services) -> None:
    while not svc.stop.wait(60):
        try:
            svc.store.sweep()
            svc.jobs.sweep()
        except Exception:  # noqa: BLE001
            log.exception("sweeper failed")


def reset_services() -> None:
    """Tear everything down (tests)."""
    global _services
    with _lock:
        if _services is not None:
            _services.stop.set()
            _services.jobs.shutdown()
        _services = None
