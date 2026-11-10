"""Merge, split, rotate, organise, blank pages and resize."""
from __future__ import annotations

from pypdf import PdfReader, PdfWriter, Transformation
from pypdf.generic import ArrayObject, FloatObject, NameObject

from ..config import get_settings
from ..errors import InvalidRequest
from ..validation import stem_of
from .common import (
    MM, PAGE_SIZES, ServiceContext, check_page_limit, displayed_size, open_reader, page_box,
    parse_groups, parse_pages, prepare_pdf, rect, unique_name,
)


def _write(writer: PdfWriter, path) -> None:
    with open(path, "wb") as f:
        writer.write(f)


# ------------------------------------------------------------------- merge
def merge(ctx: ServiceContext) -> None:
    o = ctx.options
    if len(ctx.inputs) < 2:
        raise InvalidRequest("Add at least two PDF files to merge.")
    settings = get_settings()
    writer = PdfWriter()
    specs, pws = o.get("pages") or [], o.get("passwords") or []
    total = 0
    for i, inp in enumerate(ctx.inputs):
        ctx.check_cancel()
        ctx.pdf_input(i)
        path = prepare_pdf(ctx, inp, pws[i] if i < len(pws) and pws[i] else None)
        reader = open_reader(path)
        idx = parse_pages(specs[i] if i < len(specs) else "", len(reader.pages))
        total += len(idx)
        check_page_limit(total, settings.max_pages)
        writer.append(reader, pages=idx, import_outline=False)
        ctx.progress(90 * (i + 1) / len(ctx.inputs), f"Added {inp.name}")
    out = ctx.new_path(".pdf")
    _write(writer, out)
    ctx.add_output(out, "merged.pdf")
    ctx.meta["pages"] = total


# ------------------------------------------------------------------- split
def split(ctx: ServiceContext) -> None:
    o = ctx.options
    inp = ctx.pdf_input()
    path = prepare_pdf(ctx, inp, o.get("password"))
    reader = open_reader(path)
    n = len(reader.pages)
    stem = stem_of(inp.name)
    mode = o["mode"]
    pad = max(2, len(str(n)))

    jobs: list[tuple[list[int], str]] = []  # (page indices, output name)
    if mode == "every":
        jobs = [([i], f"{stem}_page_{i + 1:0{pad}d}.pdf") for i in range(n)]
    elif mode == "groups":
        size = o["group_size"]
        for start in range(0, n, size):
            idx = list(range(start, min(start + size, n)))
            jobs.append((idx, f"{stem}_pages_{idx[0] + 1}-{idx[-1] + 1}.pdf"))
    elif mode == "odd":
        jobs = [(parse_pages("odd", n), f"{stem}_odd_pages.pdf")]
    elif mode == "even":
        if n < 2:
            raise InvalidRequest("This document has no even pages.")
        jobs = [(parse_pages("even", n), f"{stem}_even_pages.pdf")]
    elif mode == "extract":
        idx = parse_pages(o.get("pages"), n)
        jobs = [(idx, f"{stem}_extracted.pdf")]
    else:  # ranges
        for group, part in zip(parse_groups(o.get("ranges", ""), n), o["ranges"].replace(" ", "").split(",")):
            jobs.append((group, f"{stem}_pages_{part}.pdf" if len(group) > 1 else f"{stem}_page_{group[0] + 1}.pdf"))

    used: set[str] = set()
    for k, (idx, name) in enumerate(jobs):
        ctx.check_cancel()
        w = PdfWriter()
        w.append(reader, pages=idx, import_outline=False)
        out = ctx.new_path(".pdf")
        _write(w, out)
        ctx.add_output(out, unique_name(used, name))
        ctx.progress(100 * (k + 1) / len(jobs), f"Created {k + 1} of {len(jobs)}")
    ctx.meta["files"] = len(jobs)


# ------------------------------------------------------------------ rotate
def rotate(ctx: ServiceContext) -> None:
    o = ctx.options
    inp = ctx.pdf_input()
    path = prepare_pdf(ctx, inp, o.get("password"))
    reader = open_reader(path)
    n = len(reader.pages)
    writer = PdfWriter(clone_from=reader)
    amounts: dict[int, int] = {}
    if o.get("per_page"):
        for page_no, ang in o["per_page"].items():
            if page_no > n:
                raise InvalidRequest(f"Page {page_no} is outside this document (1-{n}).", "invalid_pages")
            amounts[page_no - 1] = ang
    else:
        for i in parse_pages(o["pages"], n):
            amounts[i] = o["angle"]
    for i, ang in amounts.items():
        if ang % 360:
            writer.pages[i].rotate(ang)
    out = ctx.new_path(".pdf")
    _write(writer, out)
    ctx.add_output(out, f"{stem_of(inp.name)}_rotated.pdf")
    ctx.meta["pages_rotated"] = len([a for a in amounts.values() if a % 360])


# ---------------------------------------------------------------- organise
def organize(ctx: ServiceContext) -> None:
    o = ctx.options
    pws = o.get("passwords") or []
    readers: list[PdfReader] = []
    for i, inp in enumerate(ctx.inputs):
        ctx.pdf_input(i)
        path = prepare_pdf(ctx, inp, pws[i] if i < len(pws) and pws[i] else None)
        readers.append(open_reader(path))
    entries = o["pages"]
    check_page_limit(len(entries), get_settings().max_pages)
    writer = PdfWriter()
    for k, e in enumerate(entries):
        ctx.check_cancel()
        src, page_no = e["src"], e["page"]
        if src >= len(readers):
            raise InvalidRequest(f"Page entry {k + 1} refers to a file that was not uploaded.", "invalid_pages")
        if page_no > len(readers[src].pages):
            raise InvalidRequest(
                f"Page {page_no} does not exist in '{ctx.inputs[src].name}' ({len(readers[src].pages)} pages).",
                "invalid_pages",
            )
        new_page = writer.add_page(readers[src].pages[page_no - 1])
        if e["rotate"]:
            new_page.rotate(e["rotate"])
        if k % 25 == 0:
            ctx.progress(90 * (k + 1) / len(entries))
    out = ctx.new_path(".pdf")
    _write(writer, out)
    ctx.add_output(out, f"{stem_of(ctx.inputs[0].name)}_organized.pdf")
    ctx.meta["pages"] = len(entries)


# ------------------------------------------------------------ blank pages
def blank_pages(ctx: ServiceContext) -> None:
    o = ctx.options
    inp = ctx.pdf_input()
    path = prepare_pdf(ctx, inp, o.get("password"))
    reader = open_reader(path)
    n = len(reader.pages)
    positions = sorted(set(o["positions"]))
    if any(p < 0 or p > n for p in positions):
        raise InvalidRequest(f"Insert positions must be between 0 and {n}.", "invalid_pages")
    writer = PdfWriter()

    def blank(neighbor_idx: int) -> None:
        if o["size"] == "a4":
            w, h = PAGE_SIZES["a4"]
        elif o["size"] == "letter":
            w, h = PAGE_SIZES["letter"]
        else:
            w, h = displayed_size(reader.pages[min(max(neighbor_idx, 0), n - 1)])
        for _ in range(o["count"]):
            writer.add_blank_page(width=w, height=h)

    if 0 in positions:
        blank(0)
    for i in range(n):
        writer.add_page(reader.pages[i])
        if (i + 1) in positions:
            blank(i)
    check_page_limit(len(writer.pages), get_settings().max_pages)
    out = ctx.new_path(".pdf")
    _write(writer, out)
    ctx.add_output(out, f"{stem_of(inp.name)}_with_blanks.pdf")
    ctx.meta["pages"] = len(writer.pages)


# ------------------------------------------------------------------ resize
def _transform_annotations(page, sx: float, sy: float, tx: float, ty: float) -> None:
    annots = page.get("/Annots")
    if not annots:
        return
    for a in annots:
        try:
            obj = a.get_object()
            r = [float(v) for v in obj["/Rect"]]
            xs = [r[0] * sx + tx, r[2] * sx + tx]
            ys = [r[1] * sy + ty, r[3] * sy + ty]
            obj[NameObject("/Rect")] = ArrayObject([FloatObject(min(xs)), FloatObject(min(ys)),
                                                    FloatObject(max(xs)), FloatObject(max(ys))])
            qp = obj.get("/QuadPoints")
            if qp:
                pts = [float(v) for v in qp]
                new = []
                for k in range(0, len(pts) - 1, 2):
                    new += [FloatObject(pts[k] * sx + tx), FloatObject(pts[k + 1] * sy + ty)]
                obj[NameObject("/QuadPoints")] = ArrayObject(new)
        except Exception:
            continue  # annotation without a usable rect: leave untouched


def resize(ctx: ServiceContext) -> None:
    o = ctx.options
    inp = ctx.pdf_input()
    path = prepare_pdf(ctx, inp, o.get("password"))
    reader = open_reader(path)
    n = len(reader.pages)
    writer = PdfWriter(clone_from=reader)
    selected = set(parse_pages(o["pages"], n))
    if o["size"] == "custom":
        base_w, base_h = o["custom_width_mm"] * MM, o["custom_height_mm"] * MM
    else:
        base_w, base_h = PAGE_SIZES[o["size"]]
    short, long_ = min(base_w, base_h), max(base_w, base_h)
    margin = o["margin_mm"] * MM
    mode = o["mode"]

    for done, i in enumerate(sorted(selected), 1):
        ctx.check_cancel()
        page = writer.pages[i]
        if int(page.get("/Rotate", 0) or 0) % 360:
            page.transfer_rotation_to_content()
        left, bottom, w, h = page_box(page)
        orient = o["orientation"]
        if orient == "auto":
            orient = "landscape" if w > h else "portrait"
        W, H = (long_, short) if orient == "landscape" else (short, long_)
        cw, ch = W - 2 * margin, H - 2 * margin
        if cw <= 10 or ch <= 10:
            raise InvalidRequest("The margins are too large for this page size.", "margins_too_large")
        if mode == "stretch":
            sx, sy = cw / w, ch / h
        elif mode == "fill":
            sx = sy = max(cw / w, ch / h)
        else:
            sx = sy = min(cw / w, ch / h)
        tx = margin + (cw - w * sx) / 2 - left * sx
        ty = margin + (ch - h * sy) / 2 - bottom * sy
        page.add_transformation(Transformation().scale(sx, sy).translate(tx, ty))
        _transform_annotations(page, sx, sy, tx, ty)
        box = rect(0, 0, W, H)
        for key in ("mediabox", "cropbox", "trimbox", "bleedbox", "artbox"):
            setattr(page, key, box)
        ctx.progress(95 * done / len(selected))
    out = ctx.new_path(".pdf")
    _write(writer, out)
    ctx.add_output(out, f"{stem_of(inp.name)}_resized.pdf")
    ctx.meta["pages_resized"] = len(selected)
