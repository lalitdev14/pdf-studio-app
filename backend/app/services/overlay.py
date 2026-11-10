"""Stamp content onto existing pages: watermarks, page numbers, headers/footers.

Overlays are drawn with ReportLab and merged with pypdf. Everything we add is
wrapped in marked-content ``/Artifact`` tags, which makes the stamps recognisable
to screen readers and lets ``remove_watermark`` strip watermarks cleanly.
"""
from __future__ import annotations

import io
import math
import re
from datetime import date
from pathlib import Path

from PIL import Image, UnidentifiedImageError
from pypdf import PdfReader, PdfWriter, Transformation
from pypdf.generic import ContentStream
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from ..config import get_settings
from ..errors import AppError, CorruptFile, InvalidRequest
from ..validation import stem_of
from .common import ServiceContext, hex_to_rgb, open_reader, page_box, parse_pages, prepare_pdf

# --------------------------------------------------------------------- fonts
_BASE14 = {
    "helvetica": ("Helvetica", "Helvetica-Bold", "Helvetica-Oblique", "Helvetica-BoldOblique"),
    "times": ("Times-Roman", "Times-Bold", "Times-Italic", "Times-BoldItalic"),
    "courier": ("Courier", "Courier-Bold", "Courier-Oblique", "Courier-BoldOblique"),
}
_UNICODE_CANDIDATES = [
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    ("/usr/share/fonts/dejavu/DejaVuSans.ttf", "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf"),
    ("/Library/Fonts/Arial Unicode.ttf", "/Library/Fonts/Arial Unicode.ttf"),
    ("C:\\Windows\\Fonts\\arial.ttf", "C:\\Windows\\Fonts\\arialbd.ttf"),
]
_registered: dict[bool, str | None] = {}


def _unicode_font(bold: bool) -> str | None:
    if bold in _registered:
        return _registered[bold]
    pairs = list(_UNICODE_CANDIDATES)
    custom = get_settings().unicode_font_path
    if custom:
        pairs.insert(0, (custom, custom))
    name = None
    for regular, bold_path in pairs:
        p = Path(bold_path if bold else regular)
        if p.exists():
            try:
                name = f"PSUni{'B' if bold else 'R'}"
                pdfmetrics.registerFont(TTFont(name, str(p)))
                break
            except Exception:
                name = None
    _registered[bold] = name
    return name


def font_for(text: str, family: str = "helvetica", bold: bool = False, italic: bool = False) -> str:
    names = _BASE14.get(family, _BASE14["helvetica"])
    base = names[(1 if bold else 0) + (2 if italic else 0)]
    try:
        text.encode("cp1252")
        return base
    except UnicodeEncodeError:
        uni = _unicode_font(bold)
        if uni:
            return uni
        raise InvalidRequest(
            "This text contains characters the built-in PDF fonts cannot draw. "
            "Install a Unicode font on the server (e.g. fonts-dejavu-core) or set UNICODE_FONT_PATH.",
            "unsupported_text",
        )


# ------------------------------------------------------------ overlay plumbing
def new_overlay(w: float, h: float) -> tuple[canvas.Canvas, io.BytesIO]:
    buf = io.BytesIO()
    return canvas.Canvas(buf, pagesize=(w, h), pageCompression=0), buf


def finish_overlay(c: canvas.Canvas, buf: io.BytesIO) -> bytes:
    c.showPage()
    c.save()
    return buf.getvalue()


def artifact_begin(c: canvas.Canvas, subtype: str) -> None:
    c._code.append(f"/Artifact <</Type /Pagination /Subtype /{subtype}>> BDC")  # noqa: SLF001


def artifact_end(c: canvas.Canvas) -> None:
    c._code.append("EMC")  # noqa: SLF001


def apply_overlays(writer: PdfWriter, indices, make_overlay, over: bool = True) -> None:
    for i in indices:
        page = writer.pages[i]
        if int(page.get("/Rotate", 0) or 0) % 360:
            page.transfer_rotation_to_content()
        left, bottom, w, h = page_box(page)
        data = make_overlay(i, w, h)
        if not data:
            continue
        ov = PdfReader(io.BytesIO(data)).pages[0]
        if left or bottom:
            page.merge_transformed_page(ov, Transformation().translate(left, bottom), over=over)
        else:
            page.merge_page(ov, over=over)


def _save(writer: PdfWriter, path: Path) -> None:
    with open(path, "wb") as f:
        writer.write(f)


# ---------------------------------------------------------------- watermark
def watermark(ctx: ServiceContext) -> None:
    o = ctx.options
    inp = ctx.pdf_input()
    path = prepare_pdf(ctx, inp, o.get("password"))
    reader = open_reader(path)
    n = len(reader.pages)
    writer = PdfWriter(clone_from=reader)
    sel = parse_pages(o["pages"], n)
    rgb = hex_to_rgb(o["color"], (0.5, 0.5, 0.5))
    img_reader = None
    img_ratio = 1.0
    text = o["text"]
    font = None

    if o["kind"] == "image":
        if len(ctx.inputs) < 2:
            raise InvalidRequest("Upload an image to use as the watermark.")
        try:
            pil = Image.open(ctx.inputs[1].path)
            pil.load()
            pil = pil.convert("RGBA")
        except (UnidentifiedImageError, OSError, ValueError) as exc:
            raise CorruptFile("The watermark image could not be read.") from exc
        img_ratio = pil.size[1] / pil.size[0]
        img_reader = ImageReader(pil)
    else:
        if not text.strip():
            raise InvalidRequest("Enter the watermark text.")
        font = font_for(text, "helvetica", bold=True)

    def make(i: int, W: float, H: float) -> bytes:
        c, buf = new_overlay(W, H)
        artifact_begin(c, "Watermark")
        c.setFillAlpha(o["opacity"])
        c.translate(W / 2, H / 2)
        c.rotate(o["rotation"])
        if img_reader is not None:
            dw = W * o["image_scale_pct"] / 100.0
            dh = dw * img_ratio
            positions = [(0.0, 0.0)] if o["position"] == "center" else _grid(W, H, dw * 1.5, dh * 1.8)
            for gx, gy in positions:
                c.drawImage(img_reader, gx - dw / 2, gy - dh / 2, dw, dh, mask="auto")
        else:
            c.setFont(font, o["font_size"])
            c.setFillColorRGB(*rgb)
            tw = pdfmetrics.stringWidth(text, font, o["font_size"])
            positions = [(0.0, 0.0)] if o["position"] == "center" else _grid(W, H, tw * 1.5, o["font_size"] * 3)
            for gx, gy in positions:
                c.drawCentredString(gx, gy - o["font_size"] * 0.3, text)
        artifact_end(c)
        return finish_overlay(c, buf)

    apply_overlays(writer, sel, make, over=o["layer"] == "over")
    out = ctx.new_path(".pdf")
    _save(writer, out)
    ctx.add_output(out, f"{stem_of(inp.name)}_watermarked.pdf")
    ctx.meta["pages_stamped"] = len(sel)


def _grid(W: float, H: float, step_x: float, step_y: float) -> list[tuple[float, float]]:
    """Grid of centre points around the (rotated) page centre covering the page."""
    reach = math.hypot(W, H) / 2 + max(step_x, step_y)
    step_x, step_y = max(step_x, 8.0), max(step_y, 8.0)
    pts = []
    y = -reach
    row = 0
    while y <= reach and len(pts) < 600:
        x = -reach + (step_x / 2 if row % 2 else 0)
        while x <= reach and len(pts) < 600:
            pts.append((x, y))
            x += step_x
        y += step_y
        row += 1
    return pts


# ------------------------------------------------------- remove watermark
_BEGIN = re.compile(
    rb"(?P<tag>/[^\s/<>\[\]()]+)\s*(?P<props>/[^\s/<>\[\]()]+|<<(?:[^<>]|<<[^<>]*>>)*>>)?\s*(?P<op>BDC|BMC)(?![A-Za-z0-9])",
    re.S,
)
_EMC = re.compile(rb"(?<![A-Za-z0-9])EMC(?![A-Za-z0-9])")
_IS_WM = re.compile(rb"/Subtype\s*/Watermark")


def strip_watermark_blocks(data: bytes) -> tuple[bytes, int]:
    """Remove ``/Artifact <</Subtype /Watermark>> BDC ... EMC`` blocks (nesting-aware)."""
    events = []
    for m in _BEGIN.finditer(data):
        is_wm = m.group("tag") == b"/Artifact" and bool(m.group("props")) and bool(_IS_WM.search(m.group("props")))
        events.append((m.start(), m.end(), "b", is_wm))
    for m in _EMC.finditer(data):
        events.append((m.start(), m.end(), "e", False))
    events.sort()
    stack: list[tuple[int, bool]] = []
    cuts: list[tuple[int, int]] = []
    for start, end, kind, is_wm in events:
        if kind == "b":
            stack.append((start, is_wm))
        elif stack:
            b_start, b_wm = stack.pop()
            if b_wm:
                cuts.append((b_start, end))
    if not cuts:
        return data, 0
    cuts.sort()
    merged: list[list[int]] = []
    for s, e in cuts:  # drop cuts nested inside an earlier cut
        if merged and s < merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])
    out, pos = bytearray(), 0
    for s, e in merged:
        out += data[pos:s]
        pos = e
    out += data[pos:]
    return bytes(out), len(merged)


def remove_watermark(ctx: ServiceContext) -> None:
    o = ctx.options
    inp = ctx.pdf_input()
    path = prepare_pdf(ctx, inp, o.get("password"))
    reader = open_reader(path)
    writer = PdfWriter(clone_from=reader)
    sel = parse_pages(o["pages"], len(reader.pages))
    removed = 0
    for i in sel:
        ctx.check_cancel()
        page = writer.pages[i]
        contents = page.get_contents()
        if contents is None:
            continue
        new, count = strip_watermark_blocks(contents.get_data())
        if count:
            cs = ContentStream(None, writer)
            cs.set_data(new)
            page.replace_contents(cs)
            removed += count
    if not removed:
        raise AppError(
            "no_watermark_found",
            "No removable watermark was found. Only watermarks that are tagged as artifacts "
            "(like the ones added by this tool or by Acrobat) can be removed safely; watermarks "
            "baked into images or page content cannot be separated from the page.",
            422,
        )
    out = ctx.new_path(".pdf")
    _save(writer, out)
    ctx.add_output(out, f"{stem_of(inp.name)}_no_watermark.pdf")
    ctx.meta["watermarks_removed"] = removed


# ------------------------------------------------------------- page numbers
def _anchor(pos: str, W: float, H: float, margin: float, size: float) -> tuple[float, float, str]:
    vert, horiz = pos.split("-")
    y = margin if vert == "bottom" else H - margin - size * 0.8
    if horiz == "left":
        return margin, y, "left"
    if horiz == "right":
        return W - margin, y, "right"
    return W / 2, y, "center"


def _draw_aligned(c: canvas.Canvas, x: float, y: float, text: str, align: str) -> None:
    if align == "left":
        c.drawString(x, y, text)
    elif align == "right":
        c.drawRightString(x, y, text)
    else:
        c.drawCentredString(x, y, text)


def page_numbers(ctx: ServiceContext) -> None:
    o = ctx.options
    inp = ctx.pdf_input()
    path = prepare_pdf(ctx, inp, o.get("password"))
    reader = open_reader(path)
    n = len(reader.pages)
    writer = PdfWriter(clone_from=reader)
    sel = [i for i in parse_pages(o["pages"], n) if not (o["skip_first"] and i == 0)]
    rgb = hex_to_rgb(o["color"], (0.2, 0.2, 0.2))

    def make(i: int, W: float, H: float) -> bytes:
        label = o["format"].replace("{n}", str(o["start_at"] + i)).replace("{total}", str(n))
        font = font_for(label, o["font"])
        c, buf = new_overlay(W, H)
        artifact_begin(c, "Footer" if o["position"].startswith("bottom") else "Header")
        c.setFont(font, o["font_size"])
        c.setFillColorRGB(*rgb)
        x, y, align = _anchor(o["position"], W, H, o["margin_pt"], o["font_size"])
        _draw_aligned(c, x, y, label, align)
        artifact_end(c)
        return finish_overlay(c, buf)

    apply_overlays(writer, sel, make)
    out = ctx.new_path(".pdf")
    _save(writer, out)
    ctx.add_output(out, f"{stem_of(inp.name)}_numbered.pdf")
    ctx.meta["pages_stamped"] = len(sel)


# ----------------------------------------------------------- header / footer
def header_footer(ctx: ServiceContext) -> None:
    o = ctx.options
    inp = ctx.pdf_input()
    path = prepare_pdf(ctx, inp, o.get("password"))
    reader = open_reader(path)
    n = len(reader.pages)
    writer = PdfWriter(clone_from=reader)
    fields = {
        ("top", "left"): o["header_left"], ("top", "center"): o["header_center"], ("top", "right"): o["header_right"],
        ("bottom", "left"): o["footer_left"], ("bottom", "center"): o["footer_center"],
        ("bottom", "right"): o["footer_right"],
    }
    if not any(v.strip() for v in fields.values()):
        raise InvalidRequest("Enter at least one header or footer text.")
    sel = [i for i in parse_pages(o["pages"], n) if not (o["skip_first"] and i == 0)]
    rgb = hex_to_rgb(o["color"], (0.2, 0.2, 0.2))
    today = date.today().isoformat()
    filename = inp.name

    def fill(t: str, i: int) -> str:
        return (t.replace("{n}", str(i + 1)).replace("{total}", str(n))
                .replace("{date}", today).replace("{filename}", filename))

    def make(i: int, W: float, H: float) -> bytes:
        c, buf = new_overlay(W, H)
        c.setFillColorRGB(*rgb)
        for (vert, horiz), tpl in fields.items():
            if not tpl.strip():
                continue
            text = fill(tpl, i)
            c.setFont(font_for(text, o["font"]), o["font_size"])
            artifact_begin(c, "Header" if vert == "top" else "Footer")
            x, y, align = _anchor(f"{vert}-{horiz}", W, H, o["margin_pt"], o["font_size"])
            _draw_aligned(c, x, y, text, align)
            artifact_end(c)
        return finish_overlay(c, buf)

    apply_overlays(writer, sel, make)
    out = ctx.new_path(".pdf")
    _save(writer, out)
    ctx.add_output(out, f"{stem_of(inp.name)}_header_footer.pdf")
    ctx.meta["pages_stamped"] = len(sel)
