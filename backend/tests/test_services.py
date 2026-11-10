"""Real-document tests for every PDF operation. Outputs are reopened and rendered."""
from __future__ import annotations

import base64
import io
import time
from pathlib import Path

import pikepdf
import pytest
from PIL import Image, ImageDraw, ImageFont
from pydantic import ValidationError
from pypdf import PdfReader, PdfWriter
from reportlab.lib.pagesizes import A4, letter

from app.errors import AppError, CorruptFile, InvalidRequest
from app.services.common import parse_pages
from conftest import (
    assert_valid_pdf, make_image, make_noise_image, make_pdf, page_texts, run_op,
)


def out_path(ctx, i=0) -> Path:
    return ctx.outputs[i].path


# ------------------------------------------------------------------ page ranges
def test_parse_pages():
    assert parse_pages("1-3,5", 6) == [0, 1, 2, 4]
    assert parse_pages("4-", 6) == [3, 4, 5]
    assert parse_pages("-2", 6) == [0, 1]
    assert parse_pages("odd", 5) == [0, 2, 4]
    assert parse_pages("even", 5) == [1, 3]
    assert parse_pages("", 3) == [0, 1, 2]
    for bad in ("0", "7", "3-1", "a", "1-9"):
        with pytest.raises(InvalidRequest):
            parse_pages(bad, 6)


# --------------------------------------------------------------- image -> pdf
def test_image_to_pdf_all_formats_combined(tmp):
    files = [
        make_image(tmp / "a.jpg", fmt="JPEG"),
        make_image(tmp / "b.png", mode="RGBA", fmt="PNG"),
        make_image(tmp / "c.bmp", fmt="BMP"),
        make_image(tmp / "d.webp", fmt="WEBP"),
        make_image(tmp / "e.tif", fmt="TIFF"),
        make_image(tmp / "f.gif.png", mode="L", fmt="PNG"),
    ]
    ctx = run_op("image-to-pdf", files, tmp / "w")
    assert len(ctx.outputs) == 1
    assert assert_valid_pdf(out_path(ctx), pages=6) == 6
    box = PdfReader(str(out_path(ctx))).pages[0].mediabox
    assert (round(float(box.width)), round(float(box.height))) == (595, 842)


def test_image_to_pdf_multipage_tiff_and_separate(tmp):
    a = Image.new("RGB", (200, 100), "red")
    b = Image.new("RGB", (200, 100), "blue")
    a.save(tmp / "multi.tif", save_all=True, append_images=[b])
    single = make_image(tmp / "s.png", fmt="PNG")
    ctx = run_op("image-to-pdf", [tmp / "multi.tif", single], tmp / "w", mode="combined")
    assert_valid_pdf(out_path(ctx), pages=3)
    ctx = run_op("image-to-pdf", [tmp / "multi.tif", single], tmp / "w2", mode="separate")
    assert [o.name for o in ctx.outputs] == ["multi.pdf", "s.pdf"]
    assert_valid_pdf(out_path(ctx, 0), pages=2)
    assert_valid_pdf(out_path(ctx, 1), pages=1)


def test_image_to_pdf_layout_options(tmp):
    img = make_image(tmp / "w.png", size=(800, 400), fmt="PNG")
    ctx = run_op("image-to-pdf", [img], tmp / "a", orientation="landscape", page_size="letter")
    box = PdfReader(str(out_path(ctx))).pages[0].mediabox
    assert float(box.width) > float(box.height) and round(float(box.width)) == 792
    ctx = run_op("image-to-pdf", [img], tmp / "b", orientation="auto")
    assert float(PdfReader(str(out_path(ctx))).pages[0].mediabox.width) > 800  # auto -> landscape A4
    ctx = run_op("image-to-pdf", [img], tmp / "c", page_size="custom", custom_width_mm=100, custom_height_mm=50)
    box = PdfReader(str(out_path(ctx))).pages[0].mediabox
    assert round(float(box.width) / 2.8346) == 100
    ctx = run_op("image-to-pdf", [img], tmp / "d", page_size="image", margin="none")
    box = PdfReader(str(out_path(ctx))).pages[0].mediabox
    assert round(float(box.width) / float(box.height), 2) == 2.0
    for fit in ("fit", "fill", "original"):
        ctx = run_op("image-to-pdf", [img], tmp / f"f{fit}", fit=fit, background="#ffeecc", page_numbers=True,
                     margin="custom", margin_mm=5, quality=100)
        assert_valid_pdf(out_path(ctx), pages=1)


def test_image_to_pdf_rotation_swaps_dimensions(tmp):
    img = make_image(tmp / "w.jpg", size=(800, 400), fmt="JPEG")
    ctx = run_op("image-to-pdf", [img], tmp / "a", page_size="image", margin="none", rotations=[90])
    box = PdfReader(str(out_path(ctx))).pages[0].mediabox
    assert float(box.height) == pytest.approx(2 * float(box.width), rel=0.01)


def test_image_to_pdf_rejects_corrupt_image(tmp):
    bad = tmp / "bad.png"
    bad.write_bytes(b"\x89PNG\r\n\x1a\n" + b"garbage" * 50)
    with pytest.raises(CorruptFile):
        run_op("image-to-pdf", [bad], tmp / "w")


def test_image_to_pdf_option_validation(tmp):
    img = make_image(tmp / "a.png", fmt="PNG")
    with pytest.raises(ValidationError):
        run_op("image-to-pdf", [img], tmp / "w", page_size="custom")
    with pytest.raises(ValidationError):
        run_op("image-to-pdf", [img], tmp / "w", background="red")
    with pytest.raises(ValidationError):
        run_op("image-to-pdf", [img], tmp / "w", margin_mm=-3)


# --------------------------------------------------------------- pdf -> image
def test_pdf_to_image(tmp):
    pdf = make_pdf(tmp / "d.pdf", 3)
    ctx = run_op("pdf-to-image", [pdf], tmp / "w", dpi=72, format="png")
    assert len(ctx.outputs) == 3
    im = Image.open(out_path(ctx))
    assert im.size == (595, 842) or abs(im.size[0] - 595) <= 1
    ctx = run_op("pdf-to-image", [pdf], tmp / "w2", dpi=150, format="jpg", pages="2-3")
    assert [o.name for o in ctx.outputs] == ["d-page-002.jpg", "d-page-003.jpg"]
    assert Image.open(out_path(ctx)).size[0] == pytest.approx(1240, abs=2)
    ctx = run_op("pdf-to-image", [pdf], tmp / "w3", dpi=100, format="webp", pages="1")
    assert Image.open(out_path(ctx)).format == "WEBP"


def test_pdf_to_image_render_limit(tmp, monkeypatch):
    from app import config

    monkeypatch.setenv("MAX_RENDER_PIXELS", "1000000")
    config.reset_settings()
    try:
        pdf = make_pdf(tmp / "d.pdf", 1)
        with pytest.raises(InvalidRequest, match="lower DPI"):
            run_op("pdf-to-image", [pdf], tmp / "w", dpi=300)
    finally:
        monkeypatch.delenv("MAX_RENDER_PIXELS")
        config.reset_settings()


# ------------------------------------------------------------------- merge/split
def test_merge_order_and_page_selection(tmp):
    a = make_pdf(tmp / "a.pdf", 3, label="AAA")
    b = make_pdf(tmp / "b.pdf", 2, label="BBB")
    ctx = run_op("merge", [b, a], tmp / "w")
    assert_valid_pdf(out_path(ctx), pages=5)
    texts = page_texts(out_path(ctx))
    assert "BBB 1" in texts[0] and "BBB 2" in texts[1] and "AAA 1" in texts[2]
    ctx = run_op("merge", [a, b], tmp / "w2", pages=["2-3", "1"])
    texts = page_texts(out_path(ctx))
    assert len(texts) == 3 and "AAA 2" in texts[0] and "AAA 3" in texts[1] and "BBB 1" in texts[2]
    with pytest.raises(InvalidRequest):
        run_op("merge", [a], tmp / "w3")


def test_split_modes(tmp):
    pdf = make_pdf(tmp / "doc.pdf", 7, label="P")

    def names(ctx):
        return [o.name for o in ctx.outputs]

    ctx = run_op("split", [pdf], tmp / "a", mode="ranges", ranges="1-3,5,6-7")
    assert names(ctx) == ["doc_pages_1-3.pdf", "doc_page_5.pdf", "doc_pages_6-7.pdf"]
    assert [len(PdfReader(str(o.path)).pages) for o in ctx.outputs] == [3, 1, 2]
    ctx = run_op("split", [pdf], tmp / "b", mode="every")
    assert len(ctx.outputs) == 7
    ctx = run_op("split", [pdf], tmp / "c", mode="groups", group_size=3)
    assert [len(PdfReader(str(o.path)).pages) for o in ctx.outputs] == [3, 3, 1]
    ctx = run_op("split", [pdf], tmp / "d", mode="odd")
    assert "P 1" in page_texts(out_path(ctx))[0] and len(PdfReader(str(out_path(ctx))).pages) == 4
    ctx = run_op("split", [pdf], tmp / "e", mode="even")
    assert "P 2" in page_texts(out_path(ctx))[0] and len(PdfReader(str(out_path(ctx))).pages) == 3
    ctx = run_op("split", [pdf], tmp / "f", mode="extract", pages="7,2")
    assert [t[:6] for t in page_texts(out_path(ctx))] == ["P 7 of", "P 2 of"]
    for o in ctx.outputs:
        assert_valid_pdf(o.path)
    with pytest.raises(InvalidRequest):
        run_op("split", [pdf], tmp / "g", mode="ranges", ranges="1-9")


# -------------------------------------------------------- rotate / organise / blank
def test_rotate_selected_and_per_page(tmp):
    pdf = make_pdf(tmp / "d.pdf", 4)
    ctx = run_op("rotate", [pdf], tmp / "a", angle=90, pages="2-3")
    rots = [int(p.get("/Rotate", 0)) for p in PdfReader(str(out_path(ctx))).pages]
    assert rots == [0, 90, 90, 0]
    assert_valid_pdf(out_path(ctx), pages=4)
    ctx = run_op("rotate", [out_path(ctx)], tmp / "b", angle=270, pages="all")
    assert [int(p.get("/Rotate", 0)) % 360 for p in PdfReader(str(out_path(ctx))).pages] == [270, 0, 0, 270]
    ctx = run_op("rotate", [pdf], tmp / "c", per_page={1: 180, 4: 90})
    assert [int(p.get("/Rotate", 0)) for p in PdfReader(str(out_path(ctx))).pages] == [180, 0, 0, 90]


def test_organize_reorder_delete_duplicate_insert(tmp):
    base = make_pdf(tmp / "base.pdf", 4, label="B")
    other = make_pdf(tmp / "other.pdf", 2, label="X")
    entries = [
        {"src": 0, "page": 3}, {"src": 0, "page": 1, "rotate": 90}, {"src": 0, "page": 1},
        {"src": 1, "page": 2}, {"src": 0, "page": 4},
    ]  # page 2 deleted, page 1 duplicated, page 3 first, a page of another PDF inserted
    ctx = run_op("organize", [base, other], tmp / "w", pages=entries)
    assert assert_valid_pdf(out_path(ctx), pages=5) == 5
    texts = page_texts(out_path(ctx))
    assert [t.split(" of")[0].strip() for t in texts] == ["B 3", "B 1", "B 1", "X 2", "B 4"]
    assert int(PdfReader(str(out_path(ctx))).pages[1].get("/Rotate", 0)) == 90
    with pytest.raises(InvalidRequest):
        run_op("organize", [base], tmp / "w2", pages=[{"src": 0, "page": 9}])
    with pytest.raises(InvalidRequest):
        run_op("organize", [base], tmp / "w3", pages=[{"src": 3, "page": 1}])


def test_blank_pages(tmp):
    pdf = make_pdf(tmp / "d.pdf", 2, size=letter)
    ctx = run_op("blank-pages", [pdf], tmp / "w", positions=[0, 1, 2], count=2)
    assert assert_valid_pdf(out_path(ctx)) == 8
    texts = page_texts(out_path(ctx))
    assert texts[0].strip() == "" and "Page 1" in texts[2] and texts[3].strip() == ""
    assert round(float(PdfReader(str(out_path(ctx))).pages[0].mediabox.width)) == 612
    with pytest.raises(InvalidRequest):
        run_op("blank-pages", [pdf], tmp / "w2", positions=[5])


# --------------------------------------------------------------------- resize
def _dark_bbox(pdf: Path, dpi=72):
    from pdf2image import convert_from_path

    im = convert_from_path(str(pdf), dpi=dpi, first_page=1, last_page=1)[0].convert("L")
    return im.size, im.point(lambda p: 255 if p < 200 else 0).getbbox()


def test_resize_to_a5_scales_content_and_links(tmp):
    def link(c, i):
        c.linkURL("https://example.com", (72, 600, 272, 640), relative=0)

    pdf = make_pdf(tmp / "d.pdf", 2, extra=link)
    ctx = run_op("resize", [pdf], tmp / "w", size="a5", orientation="portrait", mode="fit")
    assert_valid_pdf(out_path(ctx), pages=2)
    r = PdfReader(str(out_path(ctx)))
    box = r.pages[0].mediabox
    assert (round(float(box.width)), round(float(box.height))) == (420, 595)
    (w, h), bbox = _dark_bbox(out_path(ctx))
    assert bbox and bbox[0] >= 0 and bbox[2] <= w and bbox[3] <= h  # content stays on the page
    rect = [float(v) for v in r.pages[0]["/Annots"][0].get_object()["/Rect"]]
    scale = 420 / 595.28
    assert rect[0] == pytest.approx(72 * scale, abs=1.5) and rect[2] == pytest.approx(272 * scale, abs=1.5)


def test_resize_selected_pages_margin_and_custom(tmp):
    pdf = make_pdf(tmp / "d.pdf", 3)
    ctx = run_op("resize", [pdf], tmp / "w", size="custom", custom_width_mm=100, custom_height_mm=150,
                 pages="2", margin_mm=10, orientation="portrait")
    r = PdfReader(str(out_path(ctx)))
    sizes = [(round(float(p.mediabox.width)), round(float(p.mediabox.height))) for p in r.pages]
    assert sizes[0] == (595, 842) and sizes[2] == (595, 842) and sizes[1] == (283, 425)
    ctx = run_op("resize", [pdf], tmp / "w2", size="letter", orientation="landscape", mode="stretch")
    assert_valid_pdf(out_path(ctx), pages=3)
    assert float(PdfReader(str(out_path(ctx))).pages[0].mediabox.width) == pytest.approx(792)


def test_resize_rotated_page(tmp):
    src = make_pdf(tmp / "d.pdf", 1)
    w = PdfWriter(clone_from=str(src))
    w.pages[0].rotate(90)
    with open(tmp / "r.pdf", "wb") as f:
        w.write(f)
    ctx = run_op("resize", [tmp / "r.pdf"], tmp / "w", size="a4", orientation="auto")
    assert_valid_pdf(out_path(ctx), pages=1)
    assert float(PdfReader(str(out_path(ctx))).pages[0].mediabox.width) > 800  # landscape kept


# ------------------------------------------------------------------ compression
def _pdf_with_photo(path: Path, tmp: Path) -> Path:
    photo = make_noise_image(tmp / "photo.png")
    from reportlab.pdfgen import canvas

    c = canvas.Canvas(str(path), pagesize=A4)
    c.drawString(72, 800, "photo page")
    c.drawImage(str(photo), 36, 300, 520, 390)
    c.showPage()
    c.save()
    return path


def test_compress_image_pdf_reduces_and_stays_valid(tmp):
    pdf = _pdf_with_photo(tmp / "photo.pdf", tmp)
    original = pdf.stat().st_size
    sizes = {}
    for level in ("low", "recommended", "high"):
        ctx = run_op("compress", [pdf], tmp / level, level=level)
        assert ctx.meta["reduced"] is True and ctx.meta["images_recompressed"] >= 1
        assert out_path(ctx).stat().st_size < original
        assert ctx.meta["original_size"] == original
        assert ctx.meta["compressed_size"] == out_path(ctx).stat().st_size
        assert ctx.meta["reduction_pct"] == pytest.approx(100 * (1 - out_path(ctx).stat().st_size / original), abs=0.2)
        assert_valid_pdf(out_path(ctx), pages=1)
        assert "photo page" in page_texts(out_path(ctx))[0]
        sizes[level] = out_path(ctx).stat().st_size
    assert sizes["high"] < sizes["recommended"] < sizes["low"]


def test_compress_never_claims_a_reduction_that_did_not_happen(tmp):
    pdf = make_pdf(tmp / "text.pdf", 1)  # uncompressed content streams: the first pass legitimately shrinks it
    first = run_op("compress", [pdf], tmp / "w1", level="high")
    assert first.meta["reduced"] is True
    already = out_path(first)
    ctx = run_op("compress", [already], tmp / "w2", level="high")  # nothing left to gain
    assert ctx.meta["reduced"] is False and ctx.meta["reduction_pct"] == 0.0
    assert out_path(ctx).stat().st_size == already.stat().st_size  # original returned untouched
    assert out_path(ctx).read_bytes() == already.read_bytes()
    assert ctx.outputs[0].name.endswith("_unchanged.pdf")
    assert ctx.warnings and "unchanged" in ctx.warnings[0]
    assert_valid_pdf(out_path(ctx))


# ------------------------------------------------------------------- security
def test_protect_and_unlock(tmp):
    pdf = make_pdf(tmp / "d.pdf", 2)
    ctx = run_op("protect", [pdf], tmp / "p", user_password="secret", owner_password="boss",
                 allow_print=False, allow_copy=False, allow_edit=False)
    enc = out_path(ctx)
    with pytest.raises(pikepdf.PasswordError):
        pikepdf.open(enc)
    with pikepdf.open(enc, password="secret") as p:
        assert p.is_encrypted and not p.allow.extract and not p.allow.print_highres
        assert p.encryption.R == 6
    # services need the password to read it; we never guess
    with pytest.raises(AppError) as e:
        run_op("rotate", [enc], tmp / "r1", angle=90)
    assert e.value.code == "password_required"
    with pytest.raises(AppError) as e:
        run_op("rotate", [enc], tmp / "r2", angle=90, password="nope")
    assert e.value.code == "wrong_password"
    ctx2 = run_op("pdf-to-image", [enc], tmp / "i", dpi=50, password="secret", pages="1")
    assert len(ctx2.outputs) == 1
    with pytest.raises(AppError) as e:
        run_op("unlock", [enc], tmp / "u0", password="bad", confirm_authorized=True)
    assert e.value.code == "wrong_password"
    ctx3 = run_op("unlock", [enc], tmp / "u1", password="secret", confirm_authorized=True)
    with pikepdf.open(out_path(ctx3)) as p:
        assert not p.is_encrypted
    assert_valid_pdf(out_path(ctx3), pages=2)


def test_protect_requires_owner_password_when_restricting_and_unlock_needs_confirmation(tmp):
    pdf = make_pdf(tmp / "d.pdf", 1)
    with pytest.raises(ValidationError):
        run_op("protect", [pdf], tmp / "w", user_password="x", allow_print=False)
    with pytest.raises(ValidationError):
        run_op("unlock", [pdf], tmp / "w", password="x")
    ctx = run_op("protect", [pdf], tmp / "ok", user_password="x")  # no restrictions needs no owner pw
    with pikepdf.open(out_path(ctx), password="x") as p:
        assert p.allow.print_highres


# -------------------------------------------------- watermark / numbers / header
def test_watermark_add_and_remove_roundtrip(tmp):
    pdf = make_pdf(tmp / "d.pdf", 3)
    ctx = run_op("watermark", [pdf], tmp / "a", text="DRAFT COPY", pages="1-2", opacity=0.3)
    wm = out_path(ctx)
    assert_valid_pdf(wm, pages=3)
    t = page_texts(wm)
    assert "DRAFT COPY" in t[0] and "DRAFT COPY" in t[1] and "DRAFT COPY" not in t[2]
    ctx2 = run_op("remove-watermark", [wm], tmp / "b", confirm_authorized=True)
    assert ctx2.meta["watermarks_removed"] == 2
    t2 = page_texts(out_path(ctx2))
    assert all("DRAFT COPY" not in x for x in t2) and "Page 1 of 3" in t2[0]
    assert_valid_pdf(out_path(ctx2), pages=3)
    with pytest.raises(AppError) as e:
        run_op("remove-watermark", [pdf], tmp / "c", confirm_authorized=True)
    assert e.value.code == "no_watermark_found"
    with pytest.raises(ValidationError):
        run_op("remove-watermark", [wm], tmp / "d")


def test_watermark_tile_image_under_and_rotated_page(tmp):
    pdf = make_pdf(tmp / "d.pdf", 1)
    w = PdfWriter(clone_from=str(pdf))
    w.pages[0].rotate(90)
    with open(tmp / "rot.pdf", "wb") as f:
        w.write(f)
    ctx = run_op("watermark", [tmp / "rot.pdf"], tmp / "a", text="TILE", position="tile", layer="under", font_size=20)
    assert_valid_pdf(out_path(ctx), pages=1)
    logo = make_image(tmp / "logo.png", mode="RGBA", fmt="PNG")
    ctx = run_op("watermark", [pdf, logo], tmp / "b", kind="image", opacity=0.4, image_scale_pct=30)
    assert_valid_pdf(out_path(ctx), pages=1)
    ctx = run_op("remove-watermark", [out_path(ctx)], tmp / "c", confirm_authorized=True)
    assert ctx.meta["watermarks_removed"] == 1
    with pytest.raises(InvalidRequest):
        run_op("watermark", [pdf], tmp / "d", kind="image")


def test_page_numbers_and_header_footer(tmp):
    pdf = make_pdf(tmp / "doc.pdf", 3)
    ctx = run_op("page-numbers", [pdf], tmp / "a", format="Page {n} of {total}", start_at=1, position="bottom-right")
    assert "Page 2 of 3" in page_texts(out_path(ctx))[1]
    ctx = run_op("page-numbers", [pdf], tmp / "b", format="- {n} -", skip_first=True, start_at=0)
    t = page_texts(out_path(ctx))
    assert "- 0 -" not in t[0] and "- 1 -" in t[1] and "- 2 -" in t[2]
    ctx = run_op("header-footer", [pdf], tmp / "c", header_center="CONFIDENTIAL", footer_left="{filename}",
                 footer_right="{n}/{total}", pages="2-3")
    t = page_texts(out_path(ctx))
    assert "CONFIDENTIAL" not in t[0] and "CONFIDENTIAL" in t[1] and "doc.pdf" in t[2] and "3/3" in t[2]
    with pytest.raises(InvalidRequest):
        run_op("header-footer", [pdf], tmp / "d")


def test_overlays_on_rotated_page_land_on_the_visible_bottom(tmp):
    from pdf2image import convert_from_path

    pdf = make_pdf(tmp / "d.pdf", 1)
    w = PdfWriter(clone_from=str(pdf))
    w.pages[0].rotate(90)
    with open(tmp / "rot.pdf", "wb") as f:
        w.write(f)
    ctx = run_op("page-numbers", [tmp / "rot.pdf"], tmp / "a", format="NUMBERMARK", font_size=20, color="#ff0000")
    im = convert_from_path(str(out_path(ctx)), dpi=72)[0].convert("RGB")
    W, H = im.size
    red = [(x, y) for x in range(0, W, 2) for y in range(0, H, 2) if im.getpixel((x, y))[0] > 200 and im.getpixel((x, y))[1] < 80]
    assert red, "stamp not visible"
    ys = [y for _, y in red]
    assert min(ys) > H * 0.85  # at the bottom of the *displayed* page


# ---------------------------------------------------------------------- editor
def _red_bbox(pdf: Path, dpi=72):
    from pdf2image import convert_from_path

    im = convert_from_path(str(pdf), dpi=dpi, first_page=1, last_page=1)[0].convert("RGB")
    W, H = im.size
    pts = [(x, y) for x in range(W) for y in range(H) if (lambda p: p[0] > 200 and p[1] < 60 and p[2] < 60)(im.getpixel((x, y)))]
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return (W, H), (min(xs), min(ys), max(xs), max(ys)) if pts else None


@pytest.mark.parametrize("rotation", [0, 90, 270])
def test_edit_rect_lands_where_the_user_drew_it(tmp, rotation):
    pdf = make_pdf(tmp / "d.pdf", 1)
    if rotation:
        w = PdfWriter(clone_from=str(pdf))
        w.pages[0].rotate(rotation)
        with open(tmp / "r.pdf", "wb") as f:
            w.write(f)
        pdf = tmp / "r.pdf"
    ann = {"type": "rect", "page": 1, "x": 0.10, "y": 0.20, "w": 0.30, "h": 0.10, "color": "#ff0000",
           "fill": "#ff0000", "stroke_width": 1}
    ctx = run_op("edit", [pdf], tmp / "w", annotations=[ann])
    assert_valid_pdf(out_path(ctx), pages=1)
    (W, H), (x0, y0, x1, y1) = _red_bbox(out_path(ctx))
    assert x0 / W == pytest.approx(0.10, abs=0.02) and y0 / H == pytest.approx(0.20, abs=0.02)
    assert (x1 - x0) / W == pytest.approx(0.30, abs=0.03) and (y1 - y0) / H == pytest.approx(0.10, abs=0.03)


def test_edit_all_annotation_types(tmp):
    pdf = make_pdf(tmp / "d.pdf", 2)
    png = io.BytesIO()
    Image.new("RGBA", (40, 20), (0, 0, 255, 200)).save(png, "PNG")
    data_url = "data:image/png;base64," + base64.b64encode(png.getvalue()).decode()
    base = {"page": 1, "x": 0.1, "y": 0.1, "w": 0.2, "h": 0.05}
    anns = [
        {**base, "type": "text", "text": "Hello overlay\nsecond line", "size": 16, "bold": True, "color": "#112233"},
        {**base, "type": "date", "text": "2026-01-02", "y": 0.3},
        {**base, "type": "textbox", "text": "boxed", "y": 0.4, "w": 0.3},
        {**base, "type": "highlight", "y": 0.5, "color": "#ffee00"},
        {**base, "type": "underline", "y": 0.55},
        {**base, "type": "strike", "y": 0.6},
        {**base, "type": "ellipse", "y": 0.65, "fill": "#00ff00"},
        {**base, "type": "line", "x2": 0.6, "y2": 0.8},
        {**base, "type": "arrow", "x2": 0.7, "y2": 0.9},
        {**base, "type": "freehand", "points": [(0.1, 0.1), (0.2, 0.15), (0.3, 0.1)]},
        {**base, "type": "image", "image": data_url, "y": 0.7},
        {**base, "type": "comment", "text": "Please review", "page": 2},
    ]
    ctx = run_op("edit", [pdf], tmp / "w", annotations=anns)
    assert_valid_pdf(out_path(ctx), pages=2)
    t = page_texts(out_path(ctx))
    assert "Hello overlay" in t[0] and "2026-01-02" in t[0] and "boxed" in t[0] and "Page 1 of 2" in t[0]
    a = PdfReader(str(out_path(ctx))).pages[1]["/Annots"]
    assert any(x.get_object().get("/Subtype") == "/Text" and "Please review" in str(x.get_object().get("/Contents")) for x in a)
    assert ctx.meta["annotations_applied"] == 12


def test_edit_validation(tmp):
    pdf = make_pdf(tmp / "d.pdf", 1)
    with pytest.raises(InvalidRequest):
        run_op("edit", [pdf], tmp / "a", annotations=[{"type": "text", "page": 5, "text": "x"}])
    with pytest.raises(ValidationError):
        run_op("edit", [pdf], tmp / "b", annotations=[{"type": "nonsense", "page": 1}])
    with pytest.raises(InvalidRequest):
        run_op("edit", [pdf], tmp / "c", annotations=[{"type": "image", "page": 1, "w": .1, "h": .1, "image": "data:text/html;base64,AAAA"}])
    with pytest.raises(CorruptFile):
        run_op("edit", [pdf], tmp / "d", annotations=[{"type": "image", "page": 1, "w": .1, "h": .1, "image": "data:image/png;base64,AAAA"}])


def test_edit_replace_text_needs_pymupdf_or_works(tmp):
    pdf = make_pdf(tmp / "d.pdf", 1)
    ann = {"type": "replace", "page": 1, "x": 0.1, "y": 0.1, "w": 0.4, "h": 0.04, "text": "Replaced!", "size": 14}
    try:
        import fitz  # noqa: F401
    except ImportError:
        with pytest.raises(AppError) as e:
            run_op("edit", [pdf], tmp / "w", annotations=[ann])
        assert e.value.code == "dependency_missing"
        return
    ctx = run_op("edit", [pdf], tmp / "w", annotations=[ann])
    assert "Replaced!" in page_texts(out_path(ctx))[0]


# ----------------------------------------------------------- extraction / OCR
def test_extract_text_and_images(tmp):
    pdf = make_pdf(tmp / "d.pdf", 2, label="Alpha")
    ctx = run_op("extract-text", [pdf], tmp / "a", layout=True)
    body = out_path(ctx).read_text()
    assert "--- Page 1 ---" in body and "Alpha 2 of 2" in body and ctx.meta["pages_without_text"] == []
    scanned = _pdf_with_photo(tmp / "photo.pdf", tmp)
    ctx = run_op("extract-text", [scanned], tmp / "b", pages="1")
    assert ctx.meta["pages_without_text"] == [] and "photo page" in out_path(ctx).read_text()
    ctx = run_op("extract-images", [scanned], tmp / "c")
    assert ctx.meta["images"] >= 1
    assert Image.open(out_path(ctx)).size == (1600, 1200)
    with pytest.raises(AppError) as e:
        run_op("extract-images", [pdf], tmp / "d")
    assert e.value.code == "no_images"


def _scan_pdf(tmp: Path, text="HELLO WORLD OCR TEST") -> Path:
    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 70)
    im = Image.new("RGB", (1654, 400), "white")
    ImageDraw.Draw(im).text((60, 150), text, fill="black", font=font)
    im.save(tmp / "scan.png")
    ctx = run_op("image-to-pdf", [tmp / "scan.png"], tmp / "mk", page_size="image", margin="none", quality=100)
    return out_path(ctx)


def test_ocr_makes_scanned_pdf_searchable(tmp):
    scan = _scan_pdf(tmp)
    assert page_texts(scan)[0].strip() == ""
    ctx = run_op("extract-text", [scan], tmp / "t")
    assert ctx.meta["pages_without_text"] == [1] and ctx.warnings
    ctx = run_op("ocr", [scan], tmp / "o", lang="eng", output="both", dpi=200)
    assert ctx.meta["pages_ocr"] == 1
    pdf_out = next(o.path for o in ctx.outputs if o.name.endswith(".pdf"))
    assert_valid_pdf(pdf_out, pages=1)
    assert "hello" in page_texts(pdf_out)[0].lower()
    txt = next(o.path for o in ctx.outputs if o.name.endswith(".txt")).read_text().lower()
    assert "hello" in txt and "world" in txt
    ctx = run_op("ocr", [pdf_out], tmp / "o2")  # already has text -> skipped
    assert ctx.meta["pages_ocr"] == 0 and ctx.warnings
    ctx = run_op("extract-text", [scan], tmp / "t2", ocr_fallback=True)
    assert "hello" in out_path(ctx).read_text().lower()
    with pytest.raises(InvalidRequest, match="language"):
        run_op("ocr", [scan], tmp / "o3", lang="xyz")


# ------------------------------------------------- metadata / flatten / repair
def test_metadata_edit_and_clear(tmp):
    pdf = make_pdf(tmp / "d.pdf", 1)
    ctx = run_op("metadata", [pdf], tmp / "a", title="My Title", author="Me", keywords="a,b")
    with pikepdf.open(out_path(ctx)) as p:
        assert str(p.docinfo["/Title"]) == "My Title" and str(p.docinfo["/Author"]) == "Me"
    ctx = run_op("metadata", [out_path(ctx)], tmp / "b", clear_all=True)
    with pikepdf.open(out_path(ctx)) as p:
        assert "/Title" not in p.docinfo and "/Author" not in p.docinfo
    with pytest.raises(InvalidRequest):
        run_op("metadata", [pdf], tmp / "c")


def test_flatten_form_fields(tmp):
    from reportlab.pdfgen import canvas

    p = tmp / "form.pdf"
    c = canvas.Canvas(str(p), pagesize=A4)
    c.drawString(72, 780, "Name:")
    c.acroForm.textfield(name="name", value="Ada Lovelace", x=120, y=770, width=200, height=22, borderStyle="inset")
    c.showPage()
    c.save()
    with pikepdf.open(p) as pdf:
        assert "/AcroForm" in pdf.Root
    ctx = run_op("flatten", [p], tmp / "w")
    assert_valid_pdf(out_path(ctx), pages=1)
    with pikepdf.open(out_path(ctx)) as pdf:
        assert "/AcroForm" not in pdf.Root
        assert not any(a.get("/Subtype") == "/Widget" for pg in pdf.pages for a in pg.get("/Annots", []))
    assert "Ada Lovelace" in page_texts(out_path(ctx))[0]


def test_repair_damaged_pdfs(tmp):
    pdf = make_pdf(tmp / "d.pdf", 3)
    data = pdf.read_bytes()
    cut = tmp / "truncated.pdf"
    cut.write_bytes(data[: len(data) - 150])  # lose the xref table and trailer
    ctx = run_op("repair", [cut], tmp / "a")
    assert assert_valid_pdf(out_path(ctx), pages=3) == 3
    assert "Page 3 of 3" in page_texts(out_path(ctx))[2]
    bad_xref = tmp / "badxref.pdf"
    bad_xref.write_bytes(data.replace(b"startxref", b"startxref\n9999999", 1))
    ctx = run_op("repair", [bad_xref], tmp / "b")
    assert_valid_pdf(out_path(ctx), pages=3)
    junk = tmp / "junk.pdf"
    junk.write_bytes(b"%PDF-1.4\nthis is not really a pdf at all")
    with pytest.raises(AppError):
        run_op("repair", [junk], tmp / "c")
    with pytest.raises(CorruptFile):
        run_op("rotate", [junk], tmp / "d")


# ---------------------------------------------------------------------- compare
def test_compare_documents(tmp):
    a = make_pdf(tmp / "a.pdf", 3, label="Doc")

    def extra(c, i):
        if i == 1:
            c.setFont("Helvetica", 30)
            c.drawString(72, 300, "CHANGED PAGE TWO")

    b = make_pdf(tmp / "b.pdf", 3, label="Doc", extra=extra)
    ctx = run_op("compare", [a, b], tmp / "w")
    assert ctx.meta["identical"] is False and ctx.meta["visual_diff_pages"] == [2] and ctx.meta["text_diff_pages"] == [2]
    assert_valid_pdf(out_path(ctx, 0))
    assert "CHANGED PAGE TWO" in out_path(ctx, 1).read_text()
    ctx = run_op("compare", [a, a], tmp / "w2")
    assert ctx.meta["identical"] is True
    c4 = make_pdf(tmp / "c.pdf", 4, label="Doc")
    ctx = run_op("compare", [a, c4], tmp / "w3")
    assert ctx.meta["pages_only_in_b"] == [4] and ctx.meta["identical"] is False
    with pytest.raises(InvalidRequest):
        run_op("compare", [a], tmp / "w4")


# ------------------------------------------------------------ Office conversion
def test_pdf_to_word_excel_powerpoint(tmp):
    import openpyxl
    from docx import Document
    from pptx import Presentation

    pdf = make_pdf(tmp / "d.pdf", 2, label="Report")
    ctx = run_op("pdf-to-word", [pdf], tmp / "a")
    doc = Document(str(out_path(ctx)))
    assert any("Report 2" in p.text for p in doc.paragraphs)
    ctx = run_op("pdf-to-excel", [pdf], tmp / "b")
    wb = openpyxl.load_workbook(out_path(ctx))
    assert any("Report 1" in str(c.value) for row in wb["Text"].iter_rows() for c in row)
    ctx = run_op("pdf-to-powerpoint", [pdf], tmp / "c", mode="image")
    prs = Presentation(str(out_path(ctx)))
    assert len(prs.slides) == 2 and "Report 1" in prs.slides[0].notes_slide.notes_text_frame.text
    ctx = run_op("pdf-to-powerpoint", [pdf], tmp / "d", mode="text")
    prs = Presentation(str(out_path(ctx)))
    assert any("Report 2" in sh.text_frame.text for sh in prs.slides[1].shapes if sh.has_text_frame)


def test_pdf_to_excel_extracts_tables_and_blocks_formula_injection(tmp):
    import openpyxl
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle
    from reportlab.lib import colors

    p = tmp / "t.pdf"
    data = [["Item", "Qty", "Note"], ["Apples", "3", "=HYPERLINK(\"http://evil\")"], ["Pears", "12", "ok"]]
    t = Table(data)
    t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 1, colors.black)]))
    SimpleDocTemplate(str(p)).build([t])
    ctx = run_op("pdf-to-excel", [p], tmp / "w")
    wb = openpyxl.load_workbook(out_path(ctx))
    ws = wb[wb.sheetnames[0]]
    assert ctx.meta["tables_found"] >= 1 and ws["A2"].value == "Apples" and ws["B2"].value == 3
    assert ws["C2"].data_type != "f"


@pytest.mark.slow
def test_office_to_pdf_with_libreoffice(tmp):
    import shutil

    if not (shutil.which("soffice") or shutil.which("libreoffice")):
        pytest.skip("LibreOffice not installed")
    from docx import Document

    d = Document()
    d.add_paragraph("Hello from Word")
    d.save(tmp / "in.docx")
    ctx = run_op("office-to-pdf", [tmp / "in.docx"], tmp / "w")
    assert_valid_pdf(out_path(ctx), pages=1)
    assert "Hello from Word" in page_texts(out_path(ctx))[0]


# ----------------------------------------------------------------- inspection
def test_info_thumbnails_and_text_lines(tmp):
    from app.services.inspect_pdf import pdf_info, render_thumbnail, text_lines

    pdf = make_pdf(tmp / "d.pdf", 2, label="Info")
    info = pdf_info(pdf)
    assert info["pages"] == 2 and info["page_sizes"][0]["w"] == pytest.approx(595.28, abs=0.1)
    assert info["security"]["encrypted"] is False
    th = render_thumbnail(pdf, 2, 200, tmp)
    assert Image.open(th).size[0] == 200
    assert render_thumbnail(pdf, 2, 200, tmp) == th
    lines = text_lines(pdf, 1)
    assert lines["lines"][0]["text"].startswith("Info 1 of 2")
    assert 0 < lines["lines"][0]["x"] < 0.3 and 0 < lines["lines"][0]["y"] < 0.2
    ctx = run_op("protect", [pdf], tmp / "p", user_password="pw")
    assert pdf_info(out_path(ctx))["security"] == {"encrypted": True, "needs_password": True}


# --------------------------------------------------------------- large inputs
def test_large_document_pipeline(tmp):
    pdf = make_pdf(tmp / "big.pdf", 300, label="Big")
    t0 = time.time()
    ctx = run_op("merge", [pdf, pdf], tmp / "m")
    merged = out_path(ctx)
    assert assert_valid_pdf(merged, pages=600) == 600
    ctx = run_op("split", [merged], tmp / "s", mode="groups", group_size=100)
    assert len(ctx.outputs) == 6
    ctx = run_op("rotate", [merged], tmp / "r", angle=90)
    assert_valid_pdf(out_path(ctx), pages=600)
    ctx = run_op("compress", [merged], tmp / "c")
    assert_valid_pdf(out_path(ctx), pages=600)
    ctx = run_op("page-numbers", [pdf], tmp / "n", format="{n}/{total}")
    assert "300/300" in page_texts(out_path(ctx))[299]
    assert time.time() - t0 < 120


def test_page_limit_enforced(tmp, monkeypatch):
    from app import config

    monkeypatch.setenv("MAX_PAGES", "5")
    config.reset_settings()
    try:
        pdf = make_pdf(tmp / "d.pdf", 4)
        with pytest.raises(InvalidRequest) as e:
            run_op("merge", [pdf, pdf], tmp / "w")
        assert e.value.code == "too_many_pages"
    finally:
        monkeypatch.delenv("MAX_PAGES")
        config.reset_settings()
