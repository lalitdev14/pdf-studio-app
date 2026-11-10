"""Office <-> PDF conversions.

* Word/Excel/PowerPoint/OpenDocument -> PDF uses headless LibreOffice (isolated
  profile per run, hard timeout, limited concurrency, never a shell).
* PDF -> Word/Excel/PowerPoint is a *reconstruction from extracted content*, not a
  layout-faithful conversion. This is stated in the job result.
"""
from __future__ import annotations

import os
import shutil
import signal
import subprocess
import threading
from pathlib import Path

from ..config import get_settings
from ..errors import AppError, DependencyMissing, InvalidRequest
from ..validation import OFFICE_KINDS, ext_for, stem_of
from .common import ServiceContext, displayed_size, open_reader, parse_pages, pdf_text_pages, prepare_pdf

_sem: threading.BoundedSemaphore | None = None
_sem_lock = threading.Lock()


def _semaphore() -> threading.BoundedSemaphore:
    global _sem
    with _sem_lock:
        if _sem is None:
            _sem = threading.BoundedSemaphore(max(1, get_settings().libreoffice_concurrency))
        return _sem


def office_to_pdf(ctx: ServiceContext) -> None:
    s = get_settings()
    inp = ctx.inputs[0]
    if inp.kind not in OFFICE_KINDS:
        raise InvalidRequest(f"'{inp.name}' is not a Word, Excel or PowerPoint document.")
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        raise DependencyMissing("LibreOffice is not installed on the server, so Office conversion is unavailable.")

    work = ctx.workdir / "lo"
    work.mkdir(parents=True, exist_ok=True)
    src = work / f"input{ext_for(inp.kind)}"
    shutil.copyfile(inp.path, src)
    profile = work / "profile"
    cmd = [
        soffice, f"-env:UserInstallation={profile.as_uri()}", "--headless", "--norestore", "--nolockcheck",
        "--nodefault", "--nofirststartwizard", "--convert-to", "pdf", "--outdir", str(work), str(src),
    ]
    env = {"HOME": str(work), "PATH": os.environ.get("PATH", ""), "LANG": "C.UTF-8"}
    ctx.progress(10, "Starting LibreOffice")
    with _semaphore():
        ctx.check_cancel()
        proc = subprocess.Popen(cmd, cwd=str(work), env=env, stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
        try:
            proc.communicate(timeout=s.libreoffice_timeout)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                proc.kill()
            proc.communicate()
            raise AppError("timeout", "The document took too long to convert and was stopped.", 422)
    result = work / "input.pdf"
    if not result.exists() or result.stat().st_size == 0:
        raise AppError("conversion_failed", "LibreOffice could not convert this document. It may be corrupted or password protected.", 422)
    out = ctx.new_path(".pdf")
    shutil.move(str(result), str(out))
    shutil.rmtree(work, ignore_errors=True)
    ctx.add_output(out, f"{stem_of(inp.name)}.pdf")
    ctx.progress(100)


# --------------------------------------------------------------- PDF -> Office
_NOTE = "Rebuilt from the text in the PDF; fonts, columns and exact layout are not preserved."


def _paragraphs(text: str) -> list[str]:
    paras, cur = [], []
    for line in text.splitlines():
        if line.strip():
            cur.append(line.strip())
        elif cur:
            paras.append(" ".join(cur))
            cur = []
    if cur:
        paras.append(" ".join(cur))
    return paras


def _render_page(path: Path, page_no: int, dpi: int, out: Path) -> Path:
    from pdf2image import convert_from_path

    img = convert_from_path(str(path), dpi=dpi, first_page=page_no, last_page=page_no)[0].convert("RGB")
    img.save(out, "PNG")
    img.close()
    return out


def pdf_to_docx(ctx: ServiceContext) -> None:
    from docx import Document
    from docx.shared import Inches

    s = get_settings()
    inp = ctx.pdf_input()
    path = prepare_pdf(ctx, inp, ctx.options.get("password"))
    n = len(open_reader(path).pages)
    texts = pdf_text_pages(path, s.subprocess_timeout, layout=False)
    texts += [""] * (n - len(texts))
    doc = Document()
    image_pages: list[int] = []
    for i in range(n):
        ctx.check_cancel()
        paras = _paragraphs(texts[i])
        if paras:
            for p in paras:
                doc.add_paragraph(p)
        else:  # scanned page: keep its content as a picture so nothing is lost
            image_pages.append(i + 1)
            png = _render_page(path, i + 1, 130, ctx.new_path(".png"))
            doc.add_picture(str(png), width=Inches(6.3))
        if i < n - 1:
            doc.add_page_break()
        ctx.progress(95 * (i + 1) / n, f"Page {i + 1} of {n}")
    out = ctx.new_path(".docx")
    doc.save(out)
    ctx.add_output(out, f"{stem_of(inp.name)}.docx", "docx")
    ctx.meta.update(pages=n, pages_as_images=image_pages, note=_NOTE)
    ctx.warnings.append(_NOTE + (f" Pages without text were inserted as pictures: {image_pages[:20]}." if image_pages else ""))


def pdf_to_xlsx(ctx: ServiceContext) -> None:
    import pdfplumber
    from openpyxl import Workbook

    s = get_settings()
    inp = ctx.pdf_input()
    path = prepare_pdf(ctx, inp, ctx.options.get("password"))
    wb = Workbook()
    wb.remove(wb.active)
    tables_found = 0

    def put(ws, row: int, col: int, value) -> None:
        cell = ws.cell(row=row, column=col)
        text = "" if value is None else str(value).strip()
        try:
            num = float(text.replace(",", "")) if text and text.replace(",", "").replace(".", "", 1).lstrip("-").isdigit() else None
        except ValueError:
            num = None
        if num is not None:
            cell.value = num
        else:
            cell.value = text
            cell.data_type = "s"  # never let PDF text become a spreadsheet formula

    with pdfplumber.open(str(path)) as pdf:
        total = len(pdf.pages)
        for i, page in enumerate(pdf.pages):
            ctx.check_cancel()
            for t_idx, table in enumerate(page.extract_tables() or [], 1):
                if not table or not any(any(c for c in row) for row in table):
                    continue
                ws = wb.create_sheet(f"p{i + 1}_t{t_idx}"[:31])
                for r, row in enumerate(table, 1):
                    for c, val in enumerate(row, 1):
                        put(ws, r, c, val)
                tables_found += 1
            ctx.progress(90 * (i + 1) / total, f"Page {i + 1} of {total}")
    if not tables_found:  # fall back to line-by-line text so the user still gets the content
        ws = wb.create_sheet("Text")
        row = 1
        for pno, text in enumerate(pdf_text_pages(path, s.subprocess_timeout, layout=True), 1):
            for line in text.splitlines():
                if line.strip():
                    put(ws, row, 1, pno)
                    put(ws, row, 2, line.rstrip())
                    row += 1
        ctx.warnings.append("No tables were detected, so the text was placed line by line (column A = page).")
    out = ctx.new_path(".xlsx")
    wb.save(out)
    ctx.add_output(out, f"{stem_of(inp.name)}.xlsx", "xlsx")
    ctx.meta.update(tables_found=tables_found)


def pdf_to_pptx(ctx: ServiceContext) -> None:
    from pptx import Presentation
    from pptx.util import Emu, Pt

    s = get_settings()
    inp = ctx.pdf_input()
    mode = ctx.options.get("mode", "image")
    path = prepare_pdf(ctx, inp, ctx.options.get("password"))
    reader = open_reader(path)
    n = len(reader.pages)
    w0, h0 = displayed_size(reader.pages[0])
    k = 960.0 / max(w0, h0)
    prs = Presentation()
    prs.slide_width, prs.slide_height = Emu(int(w0 * k * 12700)), Emu(int(h0 * k * 12700))
    texts = pdf_text_pages(path, s.subprocess_timeout, layout=False)
    texts += [""] * (n - len(texts))
    for i in range(n):
        ctx.check_cancel()
        slide = prs.slides.add_slide(prs.slide_layouts[6])
        sw, sh = prs.slide_width, prs.slide_height
        if mode == "image":
            png = _render_page(path, i + 1, 150, ctx.new_path(".png"))
            pw, ph = displayed_size(reader.pages[i])
            ratio = min(sw / pw, sh / ph)
            dw, dh = int(pw * ratio), int(ph * ratio)
            slide.shapes.add_picture(str(png), (sw - dw) // 2, (sh - dh) // 2, dw, dh)
            slide.notes_slide.notes_text_frame.text = texts[i][:5000]
        else:
            box = slide.shapes.add_textbox(Emu(int(sw * 0.05)), Emu(int(sh * 0.05)), Emu(int(sw * 0.9)), Emu(int(sh * 0.9)))
            tf = box.text_frame
            tf.word_wrap = True
            body = texts[i].strip()
            size = 18 if len(body) < 600 else 12 if len(body) < 1800 else 9
            for j, para in enumerate(_paragraphs(body) or ["(no text on this page)"]):
                p = tf.paragraphs[0] if j == 0 else tf.add_paragraph()
                p.text = para
                for r in p.runs:
                    r.font.size = Pt(size)
        ctx.progress(95 * (i + 1) / n, f"Slide {i + 1} of {n}")
    out = ctx.new_path(".pptx")
    prs.save(out)
    ctx.add_output(out, f"{stem_of(inp.name)}.pptx", "pptx")
    ctx.meta.update(pages=n, mode=mode)
    if mode == "image":
        ctx.warnings.append("Each page is a picture on its slide (not editable); the page text is in the speaker notes.")
    else:
        ctx.warnings.append(_NOTE)
