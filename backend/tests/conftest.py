"""Shared fixtures. Tests create real PDFs/images and run the real services."""
from __future__ import annotations

import io
import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

# The data dir must be configured before the app package reads settings.
_TMP = tempfile.mkdtemp(prefix="pdfstudio-test-")
os.environ["DATA_DIR"] = _TMP
os.environ.setdefault("RATE_LIMIT_MUTATING_PER_MIN", "100000")
os.environ.setdefault("RATE_LIMIT_READ_PER_MIN", "100000")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pikepdf  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402
from pypdf import PdfReader  # noqa: E402
from reportlab.lib.pagesizes import A4  # noqa: E402
from reportlab.pdfgen import canvas  # noqa: E402

from app.services import OPERATIONS  # noqa: E402
from app.services.common import InputFile, ServiceContext  # noqa: E402
from app.validation import sniff  # noqa: E402


def pytest_sessionfinish(session, exitstatus):
    shutil.rmtree(_TMP, ignore_errors=True)


@pytest.fixture()
def tmp(tmp_path):
    return tmp_path


def make_pdf(path: Path, pages: int = 3, size=A4, label: str = "Page", extra=None) -> Path:
    c = canvas.Canvas(str(path), pagesize=size)
    for i in range(pages):
        c.setFont("Helvetica", 24)
        c.drawString(72, size[1] - 100, f"{label} {i + 1} of {pages}")
        c.setFont("Helvetica", 11)
        for k in range(10):
            c.drawString(72, size[1] - 140 - k * 16, f"Body line {k} lorem ipsum dolor sit amet")
        if extra:
            extra(c, i)
        c.showPage()
    c.save()
    return path


def make_image(path: Path, color=(200, 30, 30), size=(400, 300), fmt=None, mode="RGB", **save_kw) -> Path:
    fill = (*color, 128) if mode == "RGBA" else (color[0] if mode == "L" else color)
    im = Image.new(mode, size, fill)
    d = ImageDraw.Draw(im)
    d.rectangle([10, 10, size[0] // 2, size[1] // 2], outline=(255, 255, 255) if mode != "L" else 255)
    im.save(path, fmt, **save_kw)
    return path


def make_noise_image(path: Path, size=(1600, 1200)) -> Path:
    """Photo-like content (compressible only lossily)."""
    import random

    rnd = random.Random(7)
    im = Image.new("RGB", size)
    px = im.load()
    for x in range(0, size[0]):
        for y in range(0, size[1]):
            px[x, y] = ((x * 3 + rnd.randint(0, 40)) % 256, (y * 2 + rnd.randint(0, 40)) % 256, ((x + y) + rnd.randint(0, 40)) % 256)
    im.save(path, "PNG")
    return path


def run_op(op: str, files: list[Path], workdir: Path, **options):
    """Run a registered operation synchronously and return the context."""
    spec = OPERATIONS[op]
    opts = spec.model.model_validate(options).model_dump()
    inputs = []
    for f in files:
        kind = sniff(f, f.name)
        assert kind, f"test file {f} not recognised"
        inputs.append(InputFile(Path(f), f.name, kind))
    ctx = ServiceContext(inputs, opts, workdir)
    spec.func(ctx)
    return ctx


def assert_valid_pdf(path: Path, pages: int | None = None) -> int:
    """The output must reopen in two independent parsers and render page 1."""
    with pikepdf.open(path) as pdf:
        n = len(pdf.pages)
    assert n >= 1
    assert len(PdfReader(str(path), strict=False).pages) == n
    if pages is not None:
        assert n == pages, f"expected {pages} pages, got {n}"
    from pdf2image import convert_from_path

    imgs = convert_from_path(str(path), dpi=30, first_page=1, last_page=1)
    assert imgs and imgs[0].size[0] > 0
    return n


def page_texts(path: Path) -> list[str]:
    return [(p.extract_text() or "") for p in PdfReader(str(path), strict=False).pages]
