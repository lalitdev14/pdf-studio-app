"""Background job execution with progress, cancellation and de-duplication."""
from __future__ import annotations

import hashlib
import json
import logging
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import pikepdf
from PIL import Image, UnidentifiedImageError
from pypdf.errors import PyPdfError

from .config import Settings
from .errors import AppError, JobCancelled
from .services import OpSpec
from .services.common import InputFile, ServiceContext
from .storage import FileRecord, FileStore

log = logging.getLogger("pdfstudio.jobs")

ACTIVE = ("queued", "running")


@dataclass
class Job:
    id: str
    op: str
    key: str
    owner: int | None
    created: float = field(default_factory=time.time)
    updated: float = field(default_factory=time.time)
    status: str = "queued"  # queued | running | done | failed | cancelled
    progress: float = 0.0
    message: str = ""
    outputs: list[dict] = field(default_factory=list)
    error: dict | None = None
    meta: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    cancel_event: threading.Event = field(default_factory=threading.Event)

    def snapshot(self) -> dict:
        return {
            "id": self.id, "op": self.op, "status": self.status, "progress": round(self.progress, 1),
            "message": self.message, "outputs": list(self.outputs), "error": self.error, "meta": self.meta,
            "warnings": list(self.warnings), "created": self.created, "updated": self.updated,
        }


def _job_key(op: str, options: dict, inputs: list[FileRecord]) -> str:
    h = hashlib.sha256()
    h.update(op.encode())
    h.update(json.dumps(options, sort_keys=True, default=str).encode())
    for rec in inputs:
        h.update(b"|" + (rec.sha256 or rec.id).encode())
    return h.hexdigest()


class JobManager:
    def __init__(self, store: FileStore, settings: Settings, on_finish: Callable[[Job], None] | None = None):
        self.store = store
        self.settings = settings
        self.on_finish = on_finish
        self._pool = ThreadPoolExecutor(max_workers=settings.max_workers, thread_name_prefix="job")
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    # ----------------------------------------------------------------- public
    def submit(self, spec: OpSpec, inputs: list[FileRecord], options: dict, owner: int | None = None) -> Job:
        key = _job_key(spec.op, options, inputs)
        with self._lock:
            for j in self._jobs.values():  # same request already in flight -> reuse it
                if j.key == key and j.owner == owner and j.status in ACTIVE:
                    return j
            job = Job(id=self.store.new_id(), op=spec.op, key=key, owner=owner)
            self._jobs[job.id] = job
        self._pool.submit(self._run, job, spec, inputs, options)
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def cancel(self, job_id: str) -> Job | None:
        job = self.get(job_id)
        if job and job.status in ACTIVE:
            job.cancel_event.set()
            job.message = "Cancelling…"
        return job

    def sweep(self, now: float | None = None) -> int:
        t = now if now is not None else time.time()
        with self._lock:
            old = [k for k, j in self._jobs.items() if j.status not in ACTIVE and t - j.updated > self.settings.file_ttl_seconds]
            for k in old:
                del self._jobs[k]
        for d in self.settings.work_dir.glob("*"):  # orphaned work dirs (crash/restart)
            try:
                if d.is_dir() and t - d.stat().st_mtime > max(3600, self.settings.file_ttl_seconds):
                    shutil.rmtree(d, ignore_errors=True)
            except OSError:
                pass
        return len(old)

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)

    # --------------------------------------------------------------- internals
    def _set(self, job: Job, **kw) -> None:
        for k, v in kw.items():
            setattr(job, k, v)
        job.updated = time.time()

    def _run(self, job: Job, spec: OpSpec, inputs: list[FileRecord], options: dict) -> None:
        if job.cancel_event.is_set():
            self._set(job, status="cancelled", message="Cancelled")
            return
        self._set(job, status="running", message="Starting")
        workdir = self.settings.work_dir / job.id
        try:
            ctx = ServiceContext(
                [InputFile(r.path, r.name, r.kind, r.id) for r in inputs],
                options, workdir,
                progress_cb=lambda pct, msg: self._set(job, progress=pct, message=msg or job.message),
                cancel_event=job.cancel_event,
            )
            spec.func(ctx)
            ctx.check_cancel()
            if not ctx.outputs:
                raise AppError("no_output", "The operation produced no output.", 500)
            outs = []
            for o in ctx.outputs:
                if not Path(o.path).exists():
                    raise AppError("no_output", "The operation did not produce its output file.", 500)
                rec = self.store.add_output(o.path, o.name, o.kind)
                outs.append({"id": rec.id, "name": rec.name, "size": rec.size, "kind": rec.kind, "mime": rec.mime})
            self._set(job, status="done", progress=100.0, message="Done", outputs=outs,
                      meta=ctx.meta, warnings=ctx.warnings)
        except JobCancelled:
            self._set(job, status="cancelled", message="Cancelled")
        except AppError as exc:
            self._fail(job, exc.to_dict())
        except (PyPdfError, pikepdf.PdfError) as exc:
            log.info("job %s: unreadable pdf: %s", job.op, exc)
            self._fail(job, {"code": "corrupt_pdf", "message": "The PDF is damaged or uses a feature that cannot be processed. Try the Repair tool first."})
        except (UnidentifiedImageError, Image.DecompressionBombError) as exc:
            log.info("job %s: bad image: %s", job.op, exc)
            self._fail(job, {"code": "bad_image", "message": "An image could not be read or is too large."})
        except MemoryError:
            self._fail(job, {"code": "out_of_memory", "message": "The file is too large to process. Try fewer pages or a lower resolution."})
        except Exception:  # noqa: BLE001 - never leak internals to the client
            log.exception("job %s (%s) crashed", job.id, job.op)
            self._fail(job, {"code": "internal_error", "message": "Something went wrong while processing this file."})
        finally:
            shutil.rmtree(workdir, ignore_errors=True)
            if self.on_finish:
                try:
                    self.on_finish(job)
                except Exception:  # noqa: BLE001
                    log.exception("on_finish hook failed")

    def _fail(self, job: Job, error: dict) -> None:
        self._set(job, status="failed", message=error["message"], error=error)
