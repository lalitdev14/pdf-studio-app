"""Metadata editing, form/annotation flattening, repair and PDF comparison."""
from __future__ import annotations

import difflib
import io
import shutil

import pikepdf
from PIL import Image, ImageChops, ImageFilter
from pdf2image import convert_from_path
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from ..config import get_settings
from ..errors import AppError, CorruptFile, InvalidRequest
from ..validation import stem_of
from .common import ServiceContext, pdf_text_pages, prepare_pdf, run_cmd

_META_KEYS = {
    "title": "/Title", "author": "/Author", "subject": "/Subject", "keywords": "/Keywords",
    "creator": "/Creator", "producer": "/Producer",
}


def metadata(ctx: ServiceContext) -> None:
    o = ctx.options
    inp = ctx.pdf_input()
    path = prepare_pdf(ctx, inp, o.get("password"))
    with pikepdf.open(path) as pdf:
        if o["clear_all"]:
            for k in list(pdf.docinfo.keys()):
                del pdf.docinfo[k]
            if "/Metadata" in pdf.Root:
                del pdf.Root["/Metadata"]
        changed = []
        for field, key in _META_KEYS.items():
            val = o.get(field)
            if val is None:
                continue
            if val == "":
                if key in pdf.docinfo:
                    del pdf.docinfo[key]
            else:
                pdf.docinfo[key] = val
            changed.append(field)
        if changed and "/Metadata" in pdf.Root:
            del pdf.Root["/Metadata"]  # stale XMP would contradict the new Info dictionary
        if not changed and not o["clear_all"]:
            raise InvalidRequest("Change at least one metadata field.")
        out = ctx.new_path(".pdf")
        pdf.save(out)
        ctx.meta["fields_changed"] = changed or ["all cleared"]
        ctx.meta["metadata"] = {str(k).lstrip("/"): str(v) for k, v in pdf.docinfo.items()}
    ctx.add_output(out, f"{stem_of(inp.name)}_metadata.pdf")


def flatten(ctx: ServiceContext) -> None:
    o = ctx.options
    inp = ctx.pdf_input()
    path = prepare_pdf(ctx, inp, o.get("password"))
    with pikepdf.open(path) as pdf:
        had_form = "/AcroForm" in pdf.Root
        try:
            if had_form:
                pdf.generate_appearance_streams()
            pdf.flatten_annotations(o["mode"])
        except (pikepdf.PdfError, RuntimeError) as exc:
            raise AppError("flatten_failed", "This PDF's forms/annotations could not be flattened.", 422) from exc
        if "/AcroForm" in pdf.Root:
            del pdf.Root["/AcroForm"]
        out = ctx.new_path(".pdf")
        pdf.save(out)
    ctx.add_output(out, f"{stem_of(inp.name)}_flattened.pdf")
    ctx.meta["had_form"] = had_form


def repair(ctx: ServiceContext) -> None:
    inp = ctx.pdf_input() if ctx.inputs and ctx.inputs[0].kind == "pdf" else None
    if inp is None:
        raise InvalidRequest("Upload the damaged PDF file.")
    out = ctx.new_path(".pdf")
    warnings: list[str] = []
    try:
        with pikepdf.open(inp.path, attempt_recovery=True) as pdf:
            warnings = list(pdf.get_warnings())[:10]
            if len(pdf.pages) == 0:
                raise pikepdf.PdfError("no pages")
            pdf.save(out)
    except pikepdf.PasswordError:
        raise AppError("password_required", "This PDF is password protected; unlock it first.", 422)
    except (pikepdf.PdfError, OSError, RuntimeError):
        # second chance: qpdf's own reconstruction (exit code 3 = completed with warnings)
        run_cmd(["qpdf", str(inp.path), str(out)], get_settings().subprocess_timeout, ok_codes=(0, 3))
        try:
            with pikepdf.open(out) as pdf:
                if len(pdf.pages) == 0:
                    raise pikepdf.PdfError("no pages")
        except (pikepdf.PdfError, OSError) as exc:
            raise CorruptFile("This PDF is too damaged to repair.") from exc
    with pikepdf.open(out) as check:
        pages = len(check.pages)
    ctx.add_output(out, f"{stem_of(inp.name)}_repaired.pdf")
    ctx.meta.update(pages=pages, repair_warnings=warnings)
    if warnings:
        ctx.warnings.append(f"{len(warnings)} structural problem(s) were found and fixed.")


# ---------------------------------------------------------------- compare
def compare(ctx: ServiceContext) -> None:
    o = ctx.options
    s = get_settings()
    if len(ctx.inputs) != 2:
        raise InvalidRequest("Upload exactly two PDF files to compare.")
    a_in, b_in = ctx.pdf_input(0), ctx.pdf_input(1)
    pws = o.get("passwords") or []
    pa = prepare_pdf(ctx, a_in, pws[0] if len(pws) > 0 and pws[0] else None)
    pb = prepare_pdf(ctx, b_in, pws[1] if len(pws) > 1 and pws[1] else None)
    ta = pdf_text_pages(pa, s.subprocess_timeout)
    tb = pdf_text_pages(pb, s.subprocess_timeout)
    na, nb = len(ta), len(tb)
    total = max(na, nb)
    max_visual = 150
    changed: list[int] = []
    text_changed: list[int] = []
    only_in: dict[str, list[int]] = {"a": list(range(nb + 1, na + 1)), "b": list(range(na + 1, nb + 1))}
    diff_lines: list[str] = []
    report_pages: list[tuple[int, Image.Image]] = []

    for i in range(min(na, nb)):
        ctx.check_cancel()
        la, lb = ta[i].splitlines(), tb[i].splitlines()
        if la != lb:
            text_changed.append(i + 1)
            diff_lines.append(f"=== Page {i + 1} ===")
            diff_lines += list(difflib.unified_diff(la, lb, "A", "B", lineterm="", n=0))
        if i < max_visual:
            ia = convert_from_path(str(pa), dpi=o["dpi"], first_page=i + 1, last_page=i + 1)[0].convert("RGB")
            ib = convert_from_path(str(pb), dpi=o["dpi"], first_page=i + 1, last_page=i + 1)[0].convert("RGB")
            if ib.size != ia.size:
                ib = ib.resize(ia.size, Image.Resampling.LANCZOS)
            mask = ImageChops.difference(ia, ib).convert("L").point(lambda p, t=o["sensitivity"]: 255 if p > t else 0)
            if mask.getbbox():
                changed.append(i + 1)
                grow = mask.filter(ImageFilter.MaxFilter(7))
                red = Image.new("RGB", ia.size, (255, 40, 40))
                marked = Image.composite(red, ia, grow)
                sheet = Image.new("RGB", (ia.width * 3 + 40, ia.height), (255, 255, 255))
                sheet.paste(ia, (0, 0))
                sheet.paste(ib, (ia.width + 20, 0))
                sheet.paste(marked, (ia.width * 2 + 40, 0))
                report_pages.append((i + 1, sheet))
        ctx.progress(90 * (i + 1) / max(1, min(na, nb)), f"Compared page {i + 1}")

    identical = not changed and not text_changed and na == nb
    stem_a, stem_b = stem_of(a_in.name), stem_of(b_in.name)

    # report PDF
    out = ctx.new_path(".pdf")
    c = canvas.Canvas(str(out), pagesize=(595.28, 841.89), pageCompression=1)
    c.setFont("Helvetica-Bold", 18)
    c.drawString(50, 780, "PDF comparison report")
    c.setFont("Helvetica", 11)
    lines = [
        f"A: {a_in.name}  ({na} pages)",
        f"B: {b_in.name}  ({nb} pages)",
        f"Result: {'documents are identical' if identical else 'differences found'}",
        f"Pages with visual differences: {', '.join(map(str, changed)) or 'none'}"
        + (f" (first {max_visual} pages checked)" if min(na, nb) > max_visual else ""),
        f"Pages with text differences: {', '.join(map(str, text_changed)) or 'none'}",
    ]
    if only_in["a"]:
        lines.append(f"Pages only in A: {only_in['a'][0]}-{only_in['a'][-1]}")
    if only_in["b"]:
        lines.append(f"Pages only in B: {only_in['b'][0]}-{only_in['b'][-1]}")
    for k, ln in enumerate(lines):
        c.drawString(50, 750 - k * 18, ln[:110])
    c.setFont("Helvetica-Oblique", 9)
    c.drawString(50, 750 - len(lines) * 18 - 10, "Following pages: A | B | differences highlighted in red.")
    c.showPage()
    for pno, sheet in report_pages:
        w, h = sheet.size
        scale = 780.0 / w
        c.setPageSize((800, h * scale + 50))
        c.setFont("Helvetica-Bold", 11)
        c.drawString(10, h * scale + 28, f"Page {pno}:   A  |  B  |  differences")
        buf = io.BytesIO()
        sheet.save(buf, "JPEG", quality=80)
        buf.seek(0)
        c.drawImage(ImageReader(buf), 10, 10, 780, h * scale)
        c.showPage()
    c.save()
    ctx.add_output(out, f"compare_{stem_a}_vs_{stem_b}.pdf")

    txt = ctx.new_path(".txt")
    txt.write_text("\n".join(diff_lines) if diff_lines else "No text differences.\n", encoding="utf-8")
    ctx.add_output(txt, f"compare_{stem_a}_vs_{stem_b}_text.txt", "txt")
    ctx.meta.update(
        identical=identical, pages_a=na, pages_b=nb, visual_diff_pages=changed, text_diff_pages=text_changed,
        pages_only_in_a=only_in["a"], pages_only_in_b=only_in["b"],
    )
