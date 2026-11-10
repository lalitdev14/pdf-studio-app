"""PDF compression: re-encode oversized raster images, drop dead weight, pack objects.

Honesty rule: if the result is not smaller than the input we return the original
file unchanged and say so; we never present a non-reduction as a success.
"""
from __future__ import annotations

import io
import shutil

import pikepdf
from PIL import Image
from pikepdf import Name, PdfImage

from ..errors import CorruptFile
from ..validation import stem_of
from .common import ServiceContext, prepare_pdf

LEVELS = {
    #            JPEG quality, longest image side in px (None = keep size)
    "low": (85, None),
    "recommended": (70, 1800),
    "high": (50, 1100),
}
MIN_STREAM_BYTES = 12_000  # not worth touching tiny images
MIN_GAIN = 0.90  # replace an image only if the new stream is <= 90 % of the old one


def _channels(cs) -> int | None:
    try:
        if isinstance(cs, pikepdf.Name):
            return {"/DeviceGray": 1, "/DeviceRGB": 3, "/DeviceCMYK": 4, "/CalGray": 1, "/CalRGB": 3}.get(str(cs))
        if isinstance(cs, pikepdf.Array) and len(cs) >= 2:
            kind = str(cs[0])
            if kind == "/ICCBased":
                return int(cs[1].get("/N"))
            if kind in ("/CalRGB", "/CalGray"):
                return 3 if kind == "/CalRGB" else 1
    except Exception:
        return None
    return None


def _recompress_images(pdf: pikepdf.Pdf, jpeg_q: int, max_side: int | None, ctx: ServiceContext) -> tuple[int, int]:
    total = changed = 0
    for obj in pdf.objects:
        if not isinstance(obj, pikepdf.Stream):
            continue
        try:
            if obj.get("/Subtype") != "/Image":
                continue
            total += 1
            if obj.get("/ImageMask") or "/Mask" in obj or "/Decode" in obj:
                continue
            filt = obj.get("/Filter")
            filters = [str(f) for f in filt] if isinstance(filt, pikepdf.Array) else ([str(filt)] if filt else [])
            if any(f in ("/JPXDecode", "/CCITTFaxDecode", "/JBIG2Decode") for f in filters):
                continue
            raw_len = len(obj.read_raw_bytes())
            if raw_len < MIN_STREAM_BYTES or int(obj.get("/BitsPerComponent", 8)) == 1:
                continue
            pil = PdfImage(obj).as_pil_image()
        except Exception:
            continue  # unreadable image: leave as is
        try:
            if pil.mode not in ("RGB", "L"):
                pil = pil.convert("RGB")
            if max_side and max(pil.size) > max_side:
                pil.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
            buf = io.BytesIO()
            pil.save(buf, "JPEG", quality=jpeg_q, optimize=True)
            data = buf.getvalue()
            if len(data) > raw_len * MIN_GAIN:
                continue
            channels = 3 if pil.mode == "RGB" else 1
            obj.write(data, filter=Name.DCTDecode, decode_parms=None)
            obj.Width, obj.Height = pil.size
            obj.BitsPerComponent = 8
            if _channels(obj.get("/ColorSpace")) != channels:
                obj.ColorSpace = Name.DeviceRGB if channels == 3 else Name.DeviceGray
            changed += 1
        except Exception:
            continue
        if changed % 10 == 0:
            ctx.check_cancel()
    return total, changed


def compress(ctx: ServiceContext) -> None:
    o = ctx.options
    inp = ctx.pdf_input()
    src = prepare_pdf(ctx, inp, o.get("password"))
    original_size = inp.path.stat().st_size
    jpeg_q, max_side = LEVELS[o["level"]]

    try:
        pdf = pikepdf.open(src)
    except pikepdf.PdfError as exc:
        raise CorruptFile("The PDF could not be read.") from exc
    with pdf:
        ctx.progress(10, "Analysing images")
        total_images, changed = _recompress_images(pdf, jpeg_q, max_side, ctx)
        ctx.progress(70, "Optimising structure")
        if o["strip_metadata"]:
            if "/Metadata" in pdf.Root:
                del pdf.Root["/Metadata"]
            if "/PieceInfo" in pdf.Root:
                del pdf.Root["/PieceInfo"]
            for page in pdf.pages:
                for key in ("/Thumb", "/PieceInfo"):
                    if key in page.obj:
                        del page.obj[key]
        out = ctx.new_path(".pdf")
        pdf.save(
            out,
            compress_streams=True,
            recompress_flate=True,
            object_stream_mode=pikepdf.ObjectStreamMode.generate,
        )

    new_size = out.stat().st_size
    ctx.meta.update(
        original_size=original_size, images_total=total_images, images_recompressed=changed
    )
    if new_size < original_size:
        pct = round(100.0 * (original_size - new_size) / original_size, 1)
        ctx.meta.update(compressed_size=new_size, reduction_pct=pct, reduced=True)
        ctx.meta["message"] = f"Reduced from {original_size:,} to {new_size:,} bytes ({pct}% smaller)."
        ctx.add_output(out, f"{stem_of(inp.name)}_compressed.pdf")
        if o["level"] != "high" and changed:
            ctx.meta["message"] += " Choose High compression for a smaller file at lower image quality."
    else:
        # Do not claim success: hand back the untouched original.
        keep = ctx.new_path(".pdf")
        shutil.copyfile(inp.path, keep)
        ctx.meta.update(compressed_size=original_size, reduction_pct=0.0, reduced=False)
        reason = (
            "This PDF is already well optimised"
            + (" (it contains no images that can be shrunk further)" if not total_images else "")
            + ". Compressing it more would require lowering image quality, which would hurt readability, "
            "so the original file is returned unchanged."
        )
        if o["level"] != "high" and total_images:
            reason += " You can try High compression."
        ctx.meta["message"] = reason
        ctx.warnings.append(reason)
        ctx.add_output(keep, f"{stem_of(inp.name)}_unchanged.pdf")
    ctx.progress(100)
