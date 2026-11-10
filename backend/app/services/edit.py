"""PDF editor: applies the annotation list produced by the web editor.

Two clearly different kinds of change exist:

* **Overlay annotations** (text, shapes, highlights, drawings, images, signatures,
  dates) are drawn *on top of* the existing page content. The original text stays in
  the file underneath. ``comment`` creates a real PDF sticky-note annotation.
* **Replace** (type ``replace``) truly removes the original text/pixels in a region
  and writes new text in its place. This needs PyMuPDF; without it the request
  fails with a clear message instead of faking the edit.
"""
from __future__ import annotations

import base64
import binascii
import io
import math
import re
from collections import defaultdict

from PIL import Image, UnidentifiedImageError
from pypdf import PdfWriter
from pypdf.annotations import Text as TextAnnotation
from reportlab.lib.utils import ImageReader, simpleSplit
from reportlab.pdfgen import canvas

from ..errors import CorruptFile, DependencyMissing, InvalidRequest
from ..validation import stem_of
from .common import ServiceContext, displayed_size, hex_to_rgb, open_reader, page_box, prepare_pdf
from .overlay import apply_overlays, finish_overlay, font_for, new_overlay

_DATA_URL = re.compile(r"^data:image/(?:png|jpe?g|webp);base64,([A-Za-z0-9+/=\s]+)$")
MAX_IMAGE_BYTES = 10 * 1024 * 1024


def _decode_image(data_url: str | None) -> ImageReader:
    m = _DATA_URL.match(data_url or "")
    if not m:
        raise InvalidRequest("An image annotation has no valid image (PNG, JPEG or WebP).", "invalid_image")
    try:
        raw = base64.b64decode(m.group(1), validate=False)
        if len(raw) > MAX_IMAGE_BYTES:
            raise InvalidRequest("An inserted image is larger than 10 MB.", "image_too_large")
        pil = Image.open(io.BytesIO(raw))
        pil.load()
        return ImageReader(pil.convert("RGBA"))
    except (binascii.Error, UnidentifiedImageError, OSError, ValueError) as exc:
        raise CorruptFile("An inserted image could not be read.") from exc


def _draw(c: canvas.Canvas, a: dict, W: float, H: float) -> None:
    t = a["type"]
    rgb = hex_to_rgb(a["color"])
    x, top = a["x"] * W, H - a["y"] * H
    w, h = a["w"] * W, a["h"] * H
    c.saveState()
    c.setStrokeColorRGB(*rgb)
    c.setFillColorRGB(*rgb)
    c.setLineWidth(a["stroke_width"])
    c.setLineCap(1)
    c.setLineJoin(1)
    alpha = a["opacity"]

    if t in ("text", "date", "textbox"):
        text = a["text"]
        if not text.strip():
            c.restoreState()
            return
        size = a["size"]
        font = font_for(text, a["font"], a["bold"], a["italic"])
        c.setFont(font, size)
        c.setFillAlpha(alpha)
        wrap = w if w > 0 else None
        lines: list[str] = []
        for para in text.split("\n"):
            lines += (simpleSplit(para, font, size, wrap) or [""]) if wrap else [para]
        pad = 4 if t == "textbox" else 0
        if t == "textbox":
            box_h = h if h > 0 else len(lines) * size * 1.2 + 2 * pad
            box_w = w if w > 0 else max(c.stringWidth(ln, font, size) for ln in lines) + 2 * pad
            c.setLineWidth(max(0.5, a["stroke_width"] / 2))
            c.rect(x, top - box_h, box_w, box_h, stroke=1, fill=0)
        base = top - pad - size * 0.85
        for k, line in enumerate(lines):
            c.drawString(x + pad, base - k * size * 1.2, line)

    elif t == "highlight":
        c.setFillAlpha(alpha if alpha < 1 else 0.35)
        c.rect(x, top - h, w, h, stroke=0, fill=1)

    elif t in ("underline", "strike"):
        c.setFillAlpha(alpha)
        yy = top - h if t == "underline" else top - h / 2
        c.setLineWidth(a["stroke_width"])
        c.line(x, yy, x + w, yy)

    elif t in ("rect", "ellipse"):
        c.setStrokeAlpha(alpha)
        fill = a.get("fill")
        if fill:
            c.setFillColorRGB(*hex_to_rgb(fill))
            c.setFillAlpha(min(alpha, 0.6))
        if t == "rect":
            c.rect(x, top - h, w, h, stroke=1 if a["stroke_width"] > 0 else 0, fill=1 if fill else 0)
        else:
            c.ellipse(x, top - h, x + w, top, stroke=1 if a["stroke_width"] > 0 else 0, fill=1 if fill else 0)

    elif t in ("line", "arrow"):
        if a.get("x2") is None or a.get("y2") is None:
            c.restoreState()
            return
        x2, y2 = a["x2"] * W, H - a["y2"] * H
        c.setStrokeAlpha(alpha)
        c.setFillAlpha(alpha)
        c.line(x, top, x2, y2)
        if t == "arrow":
            ang = math.atan2(y2 - top, x2 - x)
            size = max(9.0, a["stroke_width"] * 4.5)
            p = c.beginPath()
            p.moveTo(x2, y2)
            p.lineTo(x2 - size * math.cos(ang - 0.4), y2 - size * math.sin(ang - 0.4))
            p.lineTo(x2 - size * math.cos(ang + 0.4), y2 - size * math.sin(ang + 0.4))
            p.close()
            c.drawPath(p, stroke=0, fill=1)

    elif t == "freehand":
        pts = a.get("points") or []
        if len(pts) >= 2:
            c.setStrokeAlpha(alpha)
            p = c.beginPath()
            p.moveTo(pts[0][0] * W, H - pts[0][1] * H)
            for px, py in pts[1:]:
                p.lineTo(px * W, H - py * H)
            c.drawPath(p, stroke=1, fill=0)

    elif t == "image":
        if w > 0 and h > 0:
            c.setFillAlpha(alpha)
            c.drawImage(_decode_image(a.get("image")), x, top - h, w, h, mask="auto")

    c.restoreState()


_FITZ_FONTS = {
    ("helvetica", False, False): "helv", ("helvetica", True, False): "hebo",
    ("helvetica", False, True): "heit", ("helvetica", True, True): "hebi",
    ("times", False, False): "tiro", ("times", True, False): "tibo",
    ("times", False, True): "tiit", ("times", True, True): "tibi",
    ("courier", False, False): "cour", ("courier", True, False): "cobo",
    ("courier", False, True): "coit", ("courier", True, True): "cobi",
}


def _replace_text(src, dst, items: list[dict]) -> None:
    try:
        import fitz  # PyMuPDF
    except ImportError as exc:
        raise DependencyMissing(
            "Replacing existing text needs PyMuPDF on the server (pip install PyMuPDF). "
            "Overlay text (Add text) works without it."
        ) from exc
    doc = fitz.open(str(src))
    try:
        for a in items:
            page = doc[a["page"] - 1]
            if page.rotation:
                raise InvalidRequest(
                    f"Page {a['page']} is rotated. Rotate it back to 0° before replacing its text.", "rotated_page"
                )
            W, H = page.rect.width, page.rect.height
            r = fitz.Rect(a["x"] * W, a["y"] * H, (a["x"] + a["w"]) * W, (a["y"] + a["h"]) * H)
            if r.is_empty or r.width < 2 or r.height < 2:
                raise InvalidRequest("The text region to replace is too small.", "invalid_region")
            try:
                a["text"].encode("latin-1")
            except UnicodeEncodeError as exc:
                raise InvalidRequest("Replacement text may only use Latin-1 characters.", "unsupported_text") from exc
            page.add_redact_annot(r, fill=(1, 1, 1))
            page.apply_redactions(images=getattr(fitz, "PDF_REDACT_IMAGE_PIXELS", 2))
            fontname = _FITZ_FONTS[(a["font"], a["bold"], a["italic"])]
            size = a["size"]
            for _ in range(8):  # shrink until it fits
                rc = page.insert_textbox(r, a["text"], fontsize=size, fontname=fontname,
                                         color=hex_to_rgb(a["color"]), align=0)
                if rc >= 0:
                    break
                size *= 0.9
            else:
                raise InvalidRequest("The new text does not fit in the selected area.", "text_does_not_fit")
        doc.save(str(dst), deflate=True)
    finally:
        doc.close()


def edit(ctx: ServiceContext) -> None:
    o = ctx.options
    inp = ctx.pdf_input()
    path = prepare_pdf(ctx, inp, o.get("password"))
    n = len(open_reader(path).pages)
    anns: list[dict] = o["annotations"]
    for a in anns:
        if a["page"] > n:
            raise InvalidRequest(f"An annotation refers to page {a['page']}, but the document has {n} pages.", "invalid_pages")

    replaces = [a for a in anns if a["type"] == "replace"]
    if replaces:
        replaced = ctx.new_path(".pdf")
        _replace_text(path, replaced, replaces)
        path = replaced
    overlays = [a for a in anns if a["type"] != "replace"]

    reader = open_reader(path)
    writer = PdfWriter(clone_from=reader)
    by_page: dict[int, list[dict]] = defaultdict(list)
    for a in overlays:
        by_page[a["page"] - 1].append(a)

    def make(i: int, W: float, H: float) -> bytes | None:
        c, buf = new_overlay(W, H)
        for a in by_page[i]:
            if a["type"] != "comment":
                _draw(c, a, W, H)
        return finish_overlay(c, buf)

    apply_overlays(writer, sorted(by_page), make)

    for i, items in by_page.items():  # sticky notes: real PDF annotations
        page = writer.pages[i]
        left, bottom, W, H = page_box(page)
        for a in items:
            if a["type"] != "comment":
                continue
            px, py = left + a["x"] * W, bottom + H - a["y"] * H
            writer.add_annotation(
                page_number=i,
                annotation=TextAnnotation(
                    rect=(px, py - 22, px + 22, py), text=a["text"] or "Comment", open=False
                ),
            )

    out = ctx.new_path(".pdf")
    with open(out, "wb") as f:
        writer.write(f)
    ctx.add_output(out, f"{stem_of(inp.name)}_edited.pdf")
    ctx.meta.update(
        annotations_applied=len(overlays), text_replaced=len(replaces),
        note="Overlay annotations sit on top of the page; original text remains underneath. "
        "Use 'Replace text' to change existing text.",
    )
