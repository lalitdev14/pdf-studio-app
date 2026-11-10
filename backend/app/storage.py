"""Temporary file store.

Every stored file lives in its own directory ``<root>/<id>/`` as ``blob`` plus
``meta.json``. IDs are 192-bit random tokens, the client file name is only kept
as display metadata and is never used to build a path. Files expire after a
configurable TTL and are removed by ``sweep()``.
"""
from __future__ import annotations

import json
import logging
import re
import secrets
import shutil
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from .errors import NotFound
from .validation import MIME

log = logging.getLogger("pdfstudio.storage")

ID_RE = re.compile(r"^[A-Za-z0-9_-]{22,64}$")


@dataclass
class FileRecord:
    id: str
    name: str
    size: int
    kind: str
    sha256: str
    created: float
    source: str  # "upload" | "output"
    path: Path

    @property
    def mime(self) -> str:
        return MIME.get(self.kind, "application/octet-stream")

    def meta(self) -> dict:
        d = asdict(self)
        d.pop("path")
        return d


class FileStore:
    def __init__(self, root: Path, ttl_seconds: int):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.ttl = ttl_seconds
        self._lock = threading.Lock()
        self._cache: dict[str, FileRecord] = {}

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def new_id() -> str:
        return secrets.token_urlsafe(24)

    def _dir(self, file_id: str) -> Path:
        if not ID_RE.match(file_id or ""):
            raise NotFound("File not found", "file_not_found")
        return self.root / file_id

    # ------------------------------------------------------------------- create
    def begin(self) -> tuple[str, Path]:
        """Reserve an id and return the blob path to write into."""
        file_id = self.new_id()
        d = self._dir(file_id)
        d.mkdir(parents=True, exist_ok=False)
        return file_id, d / "blob"

    def commit(self, file_id: str, name: str, size: int, kind: str, sha256: str, source: str) -> FileRecord:
        d = self._dir(file_id)
        rec = FileRecord(file_id, name, size, kind, sha256, time.time(), source, d / "blob")
        (d / "meta.json").write_text(json.dumps(rec.meta()))
        with self._lock:
            self._cache[file_id] = rec
        return rec

    def abort(self, file_id: str) -> None:
        try:
            shutil.rmtree(self._dir(file_id), ignore_errors=True)
        except NotFound:
            pass
        with self._lock:
            self._cache.pop(file_id, None)

    def add_output(self, src: Path, name: str, kind: str, sha256: str = "") -> FileRecord:
        file_id, blob = self.begin()
        shutil.move(str(src), str(blob))
        size = blob.stat().st_size
        return self.commit(file_id, name, size, kind, sha256, "output")

    # --------------------------------------------------------------------- read
    def get(self, file_id: str) -> FileRecord:
        d = self._dir(file_id)
        with self._lock:
            rec = self._cache.get(file_id)
        if rec and rec.path.exists():
            return rec
        meta = d / "meta.json"
        if not meta.exists() or not (d / "blob").exists():
            raise NotFound("File not found or expired", "file_not_found")
        try:
            data = json.loads(meta.read_text())
            rec = FileRecord(path=d / "blob", **data)
        except (ValueError, TypeError) as exc:
            raise NotFound("File not found or expired", "file_not_found") from exc
        with self._lock:
            self._cache[file_id] = rec
        return rec

    def aux_dir(self, file_id: str, name: str) -> Path:
        """Per-file scratch dir (thumbnail cache etc.); removed with the file."""
        self.get(file_id)
        p = self._dir(file_id) / name
        p.mkdir(exist_ok=True)
        return p

    def delete(self, file_id: str) -> None:
        d = self._dir(file_id)
        if not d.exists():
            raise NotFound("File not found or expired", "file_not_found")
        shutil.rmtree(d, ignore_errors=True)
        with self._lock:
            self._cache.pop(file_id, None)

    # ------------------------------------------------------------------ expiry
    def sweep(self, now: float | None = None) -> int:
        """Delete expired files. Returns the number removed."""
        t = now if now is not None else time.time()
        removed = 0
        for d in self.root.iterdir():
            if not d.is_dir():
                continue
            try:
                meta = d / "meta.json"
                created = json.loads(meta.read_text())["created"] if meta.exists() else d.stat().st_mtime
            except (ValueError, KeyError, OSError):
                created = d.stat().st_mtime
            if t - created > self.ttl:
                shutil.rmtree(d, ignore_errors=True)
                with self._lock:
                    self._cache.pop(d.name, None)
                removed += 1
        return removed
