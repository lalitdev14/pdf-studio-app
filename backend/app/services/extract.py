"""Text/image extraction and OCR."""
from __future__ import annotations

import io
import re
from pathlib import Path

from pdf2image import convert_from_path
from PIL import Image
from pypdf import PdfReader, PdfWriter

from ..config import get_settings
from ..errors import AppError, DependencyMissing, InvalidRequest
from ..validation import stem_of
from .common import (
    ServiceContext, open_reader, parse_pages, pdf_text_pages, prepare_pdf, run_cmd, unique_name,
)


def _tesseract():
    try:
        import pytesseract
    except ImportError as exc:  # pragma: no cover
        raise DependencyMissing("OCR needs the 'pytesseract' package and the Tesseract engine.") from exc
    return pytesseract


def _check_lang(pytesseract, lang: str) -> None:
    try:
        available = set(pytesseract.get_languages(config=""))
    except Exception as exc:
        raise DependencyMissing("The Tesseract OCR engine is not installed on the server.") from exc
    missing = [p for p in lang.split("+") if p not in available]
    if missing:
        raise InvalidRequest(
            f"OCR language data missing on the server: {', '.join(missing)}. Available: {', '.join(sorted(available))}.",
            "ocr_language_unavailable",
        )


def _render(path: Path, page_no: int, dpi: int) -> Image.Image:
    imgs = convert_from_path(str(path), dpi=dpi, first_page=page_no, last_page=page_no, thread_count=1)
    if not imgs:
        raise AppError("render_failed", f"Page {page_no} could not be rendered for OCR.", 422)
    return imgs[0].convert("RGB")


def extract_text(ctx: ServiceContext) -> None:
    o = ctx.options
    s = get_settings()
    inp = ctx.pdf_input()
    path = prepare_pdf(ctx, inp, o.get("password"))
    n = len(open_reader(path).pages)
    sel = parse_pages(o["pages"], n)
    texts = pdf_text_pages(path, s.subprocess_timeout, layout=o["layout"])
    texts += [""] * (n - len(texts))
    blank = [i + 1 for i in sel if not texts[i].strip()]
    ocr_done: list[int] = []
    if o["ocr_fallback"] and blank:
        pt = _tesseract()
        _check_lang(pt, o["ocr_lang"])
        for k, pno in enumerate(blank):
            ctx.check_cancel()
            img = _render(path, pno, 300)
            texts[pno - 1] = pt.image_to_string(img, lang=o["ocr_lang"], timeout=s.subprocess_timeout)
            ocr_done.append(pno)
            ctx.progress(90 * (k + 1) / len(blank), f"OCR page {pno}")
        blank = [p for p in blank if p not in ocr_done]
    body = "".join(f"--- Page {i + 1} ---\n{texts[i].rstrip()}\n\n" for i in sel)
    out = ctx.new_path(".txt")
    out.write_text(body, encoding="utf-8")
    ctx.add_output(out, f"{stem_of(inp.name)}.txt", "txt")
    ctx.meta.update(pages=len(sel), pages_without_text=blank, pages_ocr=ocr_done, characters=len(body))
    if blank:
        ctx.warnings.append(
            f"{len(blank)} page(s) have no text layer (scanned images?): {', '.join(map(str, blank[:20]))}. "
            "Run the OCR tool or enable OCR fallback."
        )


def extract_images(ctx: ServiceContext) -> None:
    s = get_settings()
    inp = ctx.pdf_input()
    path = prepare_pdf(ctx, inp, ctx.options.get("password"))
    outdir = ctx.workdir / "imgs"
    outdir.mkdir(exist_ok=True)
    run_cmd(["pdfimages", "-all", "-p", str(path), str(outdir / "img")], s.subprocess_timeout)
    found = sorted(outdir.glob("img-*"))
    if not found:
        raise AppError("no_images", "No embedded images were found in this PDF.", 422)
    used: set[str] = set()
    stem = stem_of(inp.name)
    kinds = {"jpg": "jpeg", "png": "png", "tif": "tiff", "jp2": "jp2"}
    count = 0
    for f in found:
        m = re.fullmatch(r"img-(\d+)-(\d+)\.(\w+)", f.name)
        if not m:
            continue
        page, idx, ext = int(m.group(1)), int(m.group(2)), m.group(3).lower()
        name = unique_name(used, f"{stem}-p{page}-{idx + 1}.{ext}")
        ctx.add_output(f, name, kinds.get(ext, ext))
        count += 1
    ctx.meta["images"] = count


def ocr(ctx: ServiceContext) -> None:
    o = ctx.options
    s = get_settings()
    inp = ctx.pdf_input()
    path = prepare_pdf(ctx, inp, o.get("password"))
    reader = open_reader(path)
    n = len(reader.pages)
    sel = set(parse_pages(o["pages"], n))
    pt = _tesseract()
    _check_lang(pt, o["lang"])
    writer = PdfWriter()
    texts: list[str] = []
    done = skipped = 0
    for i in range(n):
        ctx.check_cancel()
        page = reader.pages[i]
        has_text = False
        if o["skip_text_pages"]:
            try:
                has_text = len((page.extract_text() or "").strip()) >= 8
            except Exception:
                has_text = False
        if i not in sel or has_text:
            writer.add_page(page)
            if o["output"] != "pdf":
                texts.append((page.extract_text() or "") if has_text else "")
            skipped += 1
        else:
            img = _render(path, i + 1, o["dpi"])
            try:
                data = pt.image_to_pdf_or_hocr(img, lang=o["lang"], extension="pdf",
                                               config=f"--dpi {o['dpi']}", timeout=s.subprocess_timeout)
            except pt.TesseractError as exc:
                raise AppError("ocr_failed", f"OCR failed on page {i + 1}.", 422) from exc
            except RuntimeError as exc:  # pytesseract timeout
                raise AppError("timeout", f"OCR timed out on page {i + 1}.", 422) from exc
            finally:
                img.close()
            ocr_page = PdfReader(io.BytesIO(data)).pages[0]
            writer.add_page(ocr_page)
            if o["output"] != "pdf":
                texts.append(ocr_page.extract_text() or "")
            done += 1
        ctx.progress(95 * (i + 1) / n, f"OCR page {i + 1} of {n}")
    stem = stem_of(inp.name)
    if o["output"] in ("pdf", "both"):
        out = ctx.new_path(".pdf")
        with open(out, "wb") as f:
            writer.write(f)
        ctx.add_output(out, f"{stem}_searchable.pdf")
    if o["output"] in ("txt", "both"):
        t = ctx.new_path(".txt")
        t.write_text("".join(f"--- Page {i + 1} ---\n{x.rstrip()}\n\n" for i, x in enumerate(texts)), encoding="utf-8")
        ctx.add_output(t, f"{stem}_ocr.txt", "txt")
    ctx.meta.update(pages_ocr=done, pages_skipped=skipped)
    if not done:
        ctx.warnings.append("Every selected page already had a text layer, so nothing needed OCR.")
