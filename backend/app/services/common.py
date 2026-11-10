"""Shared helpers for all PDF services.

A service is a plain function ``fn(ctx: ServiceContext) -> None`` that reads
``ctx.inputs`` / ``ctx.options`` and registers results with ``ctx.add_output``.
Services never touch the HTTP layer or the file store, so they are unit-testable.
"""
from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import pikepdf
from pypdf import PdfReader
from pypdf.generic import RectangleObject

from ..errors import AppError, CorruptFile, InvalidRequest, JobCancelled
from ..validation import MIME, ext_for

# 1 pt = 1/72 in; sizes in points (portrait: width, height)
PAGE_SIZES: dict[str, tuple[float, float]] = {
    "a0": (2383.94, 3370.39),
    "a1": (1683.78, 2383.94),
    "a2": (1190.55, 1683.78),
    "a3": (841.89, 1190.55),
    "a4": (595.28, 841.89),
    "a5": (419.53, 595.28),
    "letter": (612.0, 792.0),
    "legal": (612.0, 1008.0),
    "tabloid": (792.0, 1224.0),
}
MM = 72.0 / 25.4
MAX_PAGE_PT = 14400.0  # PDF spec practical limit (200 in)


@dataclass
class InputFile:
    path: Path
    name: str
    kind: str
    id: str | None = None


@dataclass
class OutputSpec:
    path: Path
    name: str
    mime: str
    kind: str


class ServiceContext:
    def __init__(
        self,
        inputs: list[InputFile],
        options: dict,
        workdir: Path,
        progress_cb: Callable[[float, str], None] | None = None,
        cancel_event: threading.Event | None = None,
    ):
        self.inputs = list(inputs)
        self.options = dict(options)
        self.workdir = Path(workdir)
        self.workdir.mkdir(parents=True, exist_ok=True)
        self._cb = progress_cb
        self._cancel = cancel_event or threading.Event()
        self.outputs: list[OutputSpec] = []
        self.meta: dict = {}
        self.warnings: list[str] = []
        self._n = 0

    def opt(self, key: str, default=None):
        v = self.options.get(key, default)
        return default if v is None else v

    def progress(self, pct: float, message: str = "") -> None:
        if self._cb:
            self._cb(max(0.0, min(100.0, pct)), message)

    def check_cancel(self) -> None:
        if self._cancel.is_set():
            raise JobCancelled()

    def new_path(self, suffix: str = "") -> Path:
        self._n += 1
        return self.workdir / f"tmp{self._n:05d}{suffix}"

    def add_output(self, path: Path, name: str, kind: str = "pdf") -> None:
        self.outputs.append(OutputSpec(Path(path), name, MIME.get(kind, "application/octet-stream"), kind))

    def pdf_input(self, index: int = 0) -> InputFile:
        if index >= len(self.inputs):
            raise InvalidRequest("A PDF file is required.")
        inp = self.inputs[index]
        if inp.kind != "pdf":
            raise InvalidRequest(f"'{inp.name}' is not a PDF file.")
        return inp


# ----------------------------------------------------------------- PDF opening
def prepare_pdf(ctx: ServiceContext, inp: InputFile, password: str | None = None) -> Path:
    """Return a path to an *unencrypted* readable copy of the PDF.

    Encrypted files are decrypted with the password the user supplied. We never
    try to guess or bypass passwords.
    """
    try:
        pdf = pikepdf.open(inp.path, password=password or "")
    except pikepdf.PasswordError:
        if password:
            raise AppError("wrong_password", f"The password for '{inp.name}' is incorrect.", 422)
        raise AppError(
            "password_required",
            f"'{inp.name}' is password protected. Enter its password to continue.",
            422,
        )
    except (pikepdf.PdfError, OSError, ValueError, RuntimeError) as exc:
        raise CorruptFile(f"'{inp.name}' could not be read. It may be corrupted (try the Repair tool).") from exc
    with pdf:
        if not pdf.is_encrypted:
            return inp.path
        out = ctx.new_path(".pdf")
        pdf.save(out)  # no `encryption` argument -> saved without encryption
        return out


def open_reader(path: Path) -> PdfReader:
    try:
        r = PdfReader(str(path), strict=False)
        len(r.pages)
        return r
    except Exception as exc:  # pypdf raises many different exception types
        raise CorruptFile("The PDF could not be read. It may be corrupted.") from exc


def check_page_limit(n: int, limit: int) -> None:
    if n > limit:
        raise InvalidRequest(f"This operation supports at most {limit} pages (got {n}).", "too_many_pages")


def page_box(page) -> tuple[float, float, float, float]:
    """(left, bottom, width, height) of the visible area (CropBox) in raw page space."""
    box = page.cropbox if "/CropBox" in page else page.mediabox
    try:
        left, bottom = float(box.left), float(box.bottom)
        w, h = float(box.width), float(box.height)
    except Exception:
        left, bottom, w, h = 0.0, 0.0, 612.0, 792.0
    return left, bottom, abs(w), abs(h)


def displayed_size(page) -> tuple[float, float]:
    """Visible (width, height) in points after /Rotate is applied."""
    _, _, w, h = page_box(page)
    rot = int(page.get("/Rotate", 0) or 0) % 360
    return (h, w) if rot in (90, 270) else (w, h)


# ----------------------------------------------------------------- page ranges
def parse_pages(spec: str | None, total: int) -> list[int]:
    """Parse '1-3,5,8-' / 'odd' / 'even' / 'all' into 0-based indices (order kept)."""
    s = (spec or "").strip().lower().replace(" ", "")
    if s in ("", "all", "*"):
        return list(range(total))
    if s == "odd":
        return list(range(0, total, 2))
    if s == "even":
        return list(range(1, total, 2))
    out: list[int] = []
    for part in s.split(","):
        if not part:
            continue
        m = re.fullmatch(r"(\d*)-(\d*)", part)
        if m:
            a = int(m.group(1)) if m.group(1) else 1
            b = int(m.group(2)) if m.group(2) else total
        elif part.isdigit():
            a = b = int(part)
        else:
            raise InvalidRequest(f"'{part}' is not a valid page or range. Use e.g. 1-3,5,8-", "invalid_pages")
        if a < 1 or b < 1 or a > total or b > total:
            raise InvalidRequest(f"Page '{part}' is outside this document (1-{total}).", "invalid_pages")
        if a > b:
            raise InvalidRequest(f"Range '{part}' is backwards.", "invalid_pages")
        out.extend(range(a - 1, b))
    if not out:
        raise InvalidRequest("No pages selected.", "invalid_pages")
    return out


def parse_groups(spec: str, total: int) -> list[list[int]]:
    """'1-3,4-6,9' -> [[0,1,2],[3,4,5],[8]]: one group per comma-separated part."""
    groups = []
    for part in (spec or "").replace(" ", "").split(","):
        if part:
            groups.append(parse_pages(part, total))
    if not groups:
        raise InvalidRequest("Enter at least one page range.", "invalid_pages")
    return groups


def hex_to_rgb(value: str, default=(0.0, 0.0, 0.0)) -> tuple[float, float, float]:
    m = re.fullmatch(r"#?([0-9a-fA-F]{6})", (value or "").strip())
    if not m:
        return default
    h = m.group(1)
    return tuple(int(h[i : i + 2], 16) / 255.0 for i in (0, 2, 4))  # type: ignore[return-value]


def rect(left: float, bottom: float, right: float, top: float) -> RectangleObject:
    return RectangleObject([left, bottom, right, top])


def unique_name(used: set[str], name: str) -> str:
    if name not in used:
        used.add(name)
        return name
    stem, dot, ext = name.rpartition(".")
    if not dot:
        stem, ext = name, ""
    i = 2
    while True:
        cand = f"{stem}-{i}{dot}{ext}"
        if cand not in used:
            used.add(cand)
            return cand
        i += 1


# --------------------------------------------------------------- subprocesses
def run_cmd(args: list[str], timeout: int, cwd: Path | None = None, ok_codes: tuple[int, ...] = (0,)):
    """Run an external tool without a shell, with a timeout. Returns CompletedProcess."""
    import subprocess

    try:
        proc = subprocess.run(
            args, capture_output=True, timeout=timeout, cwd=str(cwd) if cwd else None, check=False,
            stdin=subprocess.DEVNULL,
        )
    except FileNotFoundError as exc:
        raise AppError("dependency_missing", f"Required tool '{args[0]}' is not installed on the server.", 501) from exc
    except subprocess.TimeoutExpired as exc:
        raise AppError("timeout", f"'{Path(args[0]).name}' took too long and was stopped.", 422) from exc
    if proc.returncode not in ok_codes:
        msg = proc.stderr.decode("utf-8", "replace").strip().splitlines()
        raise AppError("tool_failed", f"'{Path(args[0]).name}' failed: {msg[-1][:200] if msg else 'unknown error'}", 422)
    return proc


def pdf_text_pages(path: Path, timeout: int, layout: bool = True) -> list[str]:
    """Text of every page using poppler's pdftotext (one call, pages split on form feed)."""
    args = ["pdftotext", "-enc", "UTF-8"]
    if layout:
        args.append("-layout")
    args += [str(path), "-"]
    proc = run_cmd(args, timeout)
    pages = proc.stdout.decode("utf-8", "replace").split("\f")
    if pages and pages[-1] == "":
        pages.pop()
    return pages
