"""Read-only helpers used by the info / thumbnail / text-line endpoints."""
from __future__ import annotations

import html
import re
from pathlib import Path

import pikepdf
from pdf2image import convert_from_path

from ..config import get_settings
from ..errors import AppError, NotFound
from .common import run_cmd
from .security import describe_security


def _inherited(obj, key: str):
    seen = 0
    while obj is not None and seen < 64:
        if key in obj:
            return obj[key]
        obj = obj.get("/Parent")
        seen += 1
    return None


def pdf_info(path: Path) -> dict:
    sec = describe_security(path)
    if sec.get("needs_password") or sec.get("unreadable"):
        return {"pages": None, "page_sizes": [], "metadata": {}, "security": sec}
    sizes = []
    meta: dict[str, str] = {}
    with pikepdf.open(path) as pdf:
        for page in pdf.pages:
            box = page.cropbox
            w, h = abs(float(box[2]) - float(box[0])), abs(float(box[3]) - float(box[1]))
            rot = _inherited(page.obj, "/Rotate")
            rot = int(rot) % 360 if rot is not None else 0
            if rot in (90, 270):
                w, h = h, w
            sizes.append({"w": round(w, 2), "h": round(h, 2), "rotation": rot})
        for k, v in pdf.docinfo.items():
            meta[str(k).lstrip("/")] = str(v)[:500]
    return {"pages": len(sizes), "page_sizes": sizes, "metadata": meta, "security": sec}


def render_thumbnail(path: Path, page_no: int, width: int, cache_dir: Path) -> Path:
    width = max(48, min(int(width), 2400))
    out = cache_dir / f"p{page_no}_{width}.jpg"
    if out.exists():
        return out
    try:
        imgs = convert_from_path(
            str(path), first_page=page_no, last_page=page_no, size=(width, None), thread_count=1, timeout=60
        )
    except Exception as exc:
        raise AppError("render_failed", "This page could not be rendered (is the PDF password protected?).", 422) from exc
    if not imgs:
        raise NotFound(f"Page {page_no} does not exist.", "page_not_found")
    imgs[0].convert("RGB").save(out, "JPEG", quality=82)
    return out


_PAGE = re.compile(r'<page width="([\d.]+)" height="([\d.]+)">')
_LINE = re.compile(r'<line xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">(.*?)</line>', re.S)
_WORD = re.compile(r"<word[^>]*>(.*?)</word>", re.S)


def text_lines(path: Path, page_no: int) -> dict:
    """Text lines of one page with positions as fractions of the page (top-left origin).

    Used by the editor to let users pick existing text to replace. Empty for
    scanned pages: run OCR first.
    """
    proc = run_cmd(
        ["pdftotext", "-f", str(page_no), "-l", str(page_no), "-bbox-layout", str(path), "-"],
        get_settings().subprocess_timeout,
    )
    xml = proc.stdout.decode("utf-8", "replace")
    pm = _PAGE.search(xml)
    if not pm:
        raise NotFound(f"Page {page_no} does not exist.", "page_not_found")
    W, H = float(pm.group(1)), float(pm.group(2))
    lines = []
    for m in _LINE.finditer(xml):
        x0, y0, x1, y1 = (float(m.group(i)) for i in range(1, 5))
        words = [html.unescape(w).strip() for w in _WORD.findall(m.group(5))]
        text = " ".join(w for w in words if w)
        if text:
            lines.append({
                "x": x0 / W, "y": y0 / H, "w": (x1 - x0) / W, "h": (y1 - y0) / H,
                "text": text, "size": round((y1 - y0) * 0.88, 1),
            })
    return {"page": page_no, "width": W, "height": H, "lines": lines}
