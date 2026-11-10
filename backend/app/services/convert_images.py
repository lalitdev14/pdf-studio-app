"""Image -> PDF and PDF -> image."""
from __future__ import annotations

import io
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError
from pdf2image import convert_from_path
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from ..config import get_settings
from ..errors import AppError, CorruptFile, InvalidRequest, UnsupportedFormat
from ..validation import safe_name, stem_of
from .common import (
    MAX_PAGE_PT, MM, PAGE_SIZES, ServiceContext, check_page_limit, displayed_size, hex_to_rgb,
    open_reader, parse_pages, prepare_pdf, unique_name,
)

MAX_FRAMES = 500
MARGIN_MM = {"none": 0.0, "small": 10.0, "medium": 20.0, "large": 30.0}
_heif_registered = False


def _register_heif() -> None:
    global _heif_registered
    if _heif_registered:
        return
    try:
        from pillow_heif import register_heif_opener  # type: ignore

        register_heif_opener()
        _heif_registered = True
    except ImportError as exc:
        raise UnsupportedFormat(
            "HEIC/HEIF images need the 'pillow-heif' package on the server (pip install pillow-heif).",
            "heic_unavailable",
        ) from exc


def _flatten_to_rgb(im: Image.Image, bg: tuple[int, int, int]) -> Image.Image:
    if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
        im = im.convert("RGBA")
        base = Image.new("RGB", im.size, bg)
        base.paste(im, mask=im.getchannel("A"))
        return base
    if im.mode in ("I;16", "I;16L", "I;16B", "I"):
        return im.point(lambda i: i * (1 / 256)).convert("L").convert("RGB")
    if im.mode == "F":
        return im.convert("L").convert("RGB")
    return im.convert("RGB")


def _rotate(im: Image.Image, deg: int) -> Image.Image:
    return {
        0: im,
        90: im.transpose(Image.Transpose.ROTATE_270),  # clockwise, as shown in the UI
        180: im.transpose(Image.Transpose.ROTATE_180),
        270: im.transpose(Image.Transpose.ROTATE_90),
    }[deg % 360]


def _load_frames(path: Path, kind: str, rotation: int, bg: tuple[int, int, int], quality: int, name: str):
    """Yield (ImageReader, width_pt, height_pt) for each frame of an image file."""
    if kind == "heic":
        _register_heif()
    try:
        im = Image.open(path)
        if getattr(im, "n_frames", 1) == 1:
            im.load()
    except UnidentifiedImageError as exc:
        raise CorruptFile(f"'{name}' is not a readable image.") from exc
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise InvalidRequest(f"'{name}' has too many pixels to process safely.", "image_too_large") from exc
    except (OSError, SyntaxError, ValueError) as exc:
        raise CorruptFile(f"'{name}' is corrupted or truncated.") from exc

    n = min(getattr(im, "n_frames", 1), MAX_FRAMES)
    for i in range(n):
        try:
            im.seek(i)
            frame = im.copy()
            dpi_info = frame.info.get("dpi") or im.info.get("dpi")
        except (EOFError, OSError, SyntaxError) as exc:
            raise CorruptFile(f"'{name}' is corrupted or truncated.") from exc
        orientation = frame.getexif().get(0x0112, 1) if hasattr(frame, "getexif") else 1
        passthrough = (
            kind == "jpeg" and n == 1 and rotation == 0 and orientation in (1, None)
            and quality >= 100 and frame.mode in ("RGB", "L")
        )
        frame = ImageOps.exif_transpose(frame)
        frame = _rotate(frame, rotation)
        try:
            dx, dy = (float(dpi_info[0]), float(dpi_info[1])) if dpi_info else (96.0, 96.0)
        except (TypeError, ValueError, IndexError):
            dx = dy = 96.0
        if dx < 10 or dy < 10:
            dx = dy = 96.0
        w_pt, h_pt = frame.size[0] * 72.0 / dx, frame.size[1] * 72.0 / dy
        if rotation % 180 == 90 and dx != dy:  # keep physical size consistent after rotating
            w_pt, h_pt = frame.size[0] * 72.0 / dy, frame.size[1] * 72.0 / dx

        if passthrough:
            reader = ImageReader(io.BytesIO(path.read_bytes()))
        elif kind == "png" and quality >= 100 and frame.mode in ("RGB", "L", "P", "1"):
            reader = ImageReader(frame.convert("RGB"))
        else:
            rgb = _flatten_to_rgb(frame, bg)
            buf = io.BytesIO()
            rgb.save(buf, "JPEG", quality=quality, optimize=True)
            buf.seek(0)
            reader = ImageReader(buf)
        yield reader, w_pt, h_pt


def _page_dims(opts: dict, img_w: float, img_h: float, margin: float) -> tuple[float, float]:
    size = opts["page_size"]
    if size == "image":
        w, h = img_w + 2 * margin, img_h + 2 * margin
        scale = min(1.0, MAX_PAGE_PT / max(w, h))
        return w * scale, h * scale
    if size == "custom":  # exactly as typed: width x height (orientation does not apply)
        return opts["custom_width_mm"] * MM, opts["custom_height_mm"] * MM
    w, h = PAGE_SIZES[size]
    short, long_ = min(w, h), max(w, h)
    orient = opts["orientation"]
    if orient == "auto":
        orient = "landscape" if img_w > img_h else "portrait"
    return (long_, short) if orient == "landscape" else (short, long_)


def image_to_pdf(ctx: ServiceContext) -> None:
    o = ctx.options
    settings = get_settings()
    Image.MAX_IMAGE_PIXELS = settings.max_image_pixels
    if not ctx.inputs:
        raise InvalidRequest("Add at least one image.")
    bg = hex_to_rgb(o["background"], (1, 1, 1))
    bg255 = tuple(int(round(c * 255)) for c in bg)
    margin = (o["margin_mm"] if o["margin"] == "custom" else MARGIN_MM[o["margin"]]) * MM
    rotations = o.get("rotations") or []
    separate = o["mode"] == "separate"

    combined_path = ctx.new_path(".pdf")
    combined: canvas.Canvas | None = None
    used: set[str] = set()
    page_no = 0
    total = len(ctx.inputs)

    for idx, inp in enumerate(ctx.inputs):
        ctx.check_cancel()
        if inp.kind not in {"jpeg", "png", "webp", "bmp", "tiff", "heic"}:
            raise UnsupportedFormat(f"'{inp.name}' is not a supported image.")
        rot = rotations[idx] if idx < len(rotations) else 0
        sep_path = ctx.new_path(".pdf") if separate else None
        c = canvas.Canvas(str(sep_path), pageCompression=1) if separate else combined
        if not separate and c is None:
            combined = c = canvas.Canvas(str(combined_path), pageCompression=1)
        frames = 0
        for reader, iw, ih in _load_frames(inp.path, inp.kind, rot, bg255, o["quality"], inp.name):
            page_no += 1
            frames += 1
            check_page_limit(page_no, settings.max_pages)
            W, H = _page_dims(o, iw, ih, margin)
            cw, ch = W - 2 * margin, H - 2 * margin
            if cw <= 10 or ch <= 10:
                raise InvalidRequest("The margins are too large for this page size.", "margins_too_large")
            c.setPageSize((W, H))
            if bg != (1.0, 1.0, 1.0):
                c.setFillColorRGB(*bg)
                c.rect(0, 0, W, H, stroke=0, fill=1)
            if o["fit"] == "fill":
                s = max(cw / iw, ch / ih)
            elif o["fit"] == "original":
                s = 1.0 if (iw <= cw and ih <= ch) else min(cw / iw, ch / ih)
            else:
                s = min(cw / iw, ch / ih)
            dw, dh = iw * s, ih * s
            x, y = margin + (cw - dw) / 2, margin + (ch - dh) / 2
            c.saveState()
            if o["fit"] == "fill":
                p = c.beginPath()
                p.rect(margin, margin, cw, ch)
                c.clipPath(p, stroke=0, fill=0)
            c.drawImage(reader, x, y, dw, dh)
            c.restoreState()
            if o["page_numbers"]:
                c.setFillColorRGB(0.35, 0.35, 0.35)
                c.setFont("Helvetica", 9)
                c.drawCentredString(W / 2, max(8, margin / 2 - 3), str(page_no))
            c.showPage()
        if frames == 0:
            raise CorruptFile(f"'{inp.name}' contains no readable image data.")
        if separate:
            c.save()
            ctx.add_output(sep_path, unique_name(used, stem_of(inp.name) + ".pdf"))
        ctx.progress(100 * (idx + 1) / total, f"Converted {idx + 1} of {total}")

    if not separate and combined is not None:
        combined.save()
        name = safe_name(o.get("output_name") or "images", "images")
        ctx.add_output(combined_path, name if name.lower().endswith(".pdf") else name + ".pdf")
    ctx.meta["pages"] = page_no


def pdf_to_image(ctx: ServiceContext) -> None:
    o = ctx.options
    settings = get_settings()
    Image.MAX_IMAGE_PIXELS = max(settings.max_image_pixels, settings.max_render_pixels + 1)
    inp = ctx.pdf_input()
    path = prepare_pdf(ctx, inp, o.get("password"))
    reader = open_reader(path)
    n = len(reader.pages)
    pages = parse_pages(o["pages"], n)
    dpi, fmt, q = o["dpi"], o["format"], o["quality"]
    ext = {"png": "png", "jpg": "jpg", "webp": "webp"}[fmt]
    stem = stem_of(inp.name)
    pad = max(3, len(str(n)))

    for i, pidx in enumerate(pages):
        ctx.check_cancel()
        w, h = displayed_size(reader.pages[pidx])
        px = (w / 72 * dpi) * (h / 72 * dpi)
        if px > settings.max_render_pixels:
            raise InvalidRequest(
                f"Page {pidx + 1} would be {px / 1e6:.0f} megapixels at {dpi} DPI "
                f"(limit {settings.max_render_pixels / 1e6:.0f}). Choose a lower DPI.",
                "render_too_large",
            )
        try:
            imgs = convert_from_path(str(path), dpi=dpi, first_page=pidx + 1, last_page=pidx + 1, thread_count=1)
        except Exception as exc:
            raise CorruptFile(f"Page {pidx + 1} could not be rendered.") from exc
        if not imgs:
            raise CorruptFile(f"Page {pidx + 1} could not be rendered.")
        img = imgs[0]
        out = ctx.new_path("." + ext)
        if fmt == "png":
            img.convert("RGB").save(out, "PNG", dpi=(dpi, dpi))
        elif fmt == "jpg":
            img.convert("RGB").save(out, "JPEG", quality=q, optimize=True, dpi=(dpi, dpi))
        else:
            img.convert("RGB").save(out, "WEBP", quality=q)
        img.close()
        ctx.add_output(out, f"{stem}-page-{pidx + 1:0{pad}d}.{ext}", {"png": "png", "jpg": "jpeg", "webp": "webp"}[fmt])
        ctx.progress(100 * (i + 1) / len(pages), f"Rendered page {pidx + 1}")
    ctx.meta["pages"] = len(pages)
