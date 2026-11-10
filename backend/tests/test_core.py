"""Unit tests for validation, signing, storage and the rate limiter."""
from __future__ import annotations

import io
import time
import zipfile

import pytest

from app.errors import NotFound
from app.signing import RateLimiter, make_token, read_token, sign_download, verify_download
from app.storage import FileStore
from app.validation import safe_name, sniff
from conftest import make_image, make_pdf


def test_sniff_detects_by_content_not_extension(tmp):
    pdf = make_pdf(tmp / "x.bin", 1)
    assert sniff(pdf, "photo.jpg") == "pdf"
    for fmt, kind, ext in (("JPEG", "jpeg", "jpg"), ("PNG", "png", "png"), ("BMP", "bmp", "bmp"),
                           ("TIFF", "tiff", "tif"), ("WEBP", "webp", "webp")):
        f = make_image(tmp / f"i.{ext}", fmt=fmt)
        assert sniff(f, "document.pdf") == kind
    for name, data in {
        "exe": b"MZ\x90\x00" + b"\x00" * 64, "html": b"<html><script>1</script></html>", "empty": b"",
        "sh": b"#!/bin/sh\nrm -rf /\n", "svg": b"<svg onload=alert(1)></svg>", "zip": b"PK\x03\x04" + b"\x00" * 30,
    }.items():
        p = tmp / name
        p.write_bytes(data)
        assert sniff(p, name + ".pdf") is None, name


def test_sniff_office_formats(tmp):
    from docx import Document
    import openpyxl
    from pptx import Presentation

    Document().save(tmp / "a.docx")
    openpyxl.Workbook().save(tmp / "a.xlsx")
    Presentation().save(tmp / "a.pptx")
    assert sniff(tmp / "a.docx") == "docx" and sniff(tmp / "a.xlsx") == "xlsx" and sniff(tmp / "a.pptx") == "pptx"
    with zipfile.ZipFile(tmp / "evil.zip", "w") as z:
        z.writestr("payload.exe", b"x")
    assert sniff(tmp / "evil.zip") is None
    (tmp / "legacy.doc").write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 100)
    assert sniff(tmp / "legacy.doc", "legacy.doc") == "doc" and sniff(tmp / "legacy.doc", "legacy.pdf") is None


def test_safe_name():
    assert safe_name("../../etc/passwd") == "passwd"
    assert safe_name("C:\\Users\\me\\report final.pdf") == "report final.pdf"
    assert safe_name("a<b>|c?.pdf") == "a_b_c_.pdf"
    assert safe_name("") == "file" and safe_name("...") == "file"
    assert len(safe_name("x" * 400 + ".pdf")) <= 150 and safe_name("x" * 400 + ".pdf").endswith(".pdf")


def test_download_signatures():
    sec = "s3cret"
    exp, sig = sign_download(sec, "file1", 60)
    assert verify_download(sec, "file1", exp, sig)
    assert not verify_download(sec, "file2", exp, sig)
    assert not verify_download("other", "file1", exp, sig)
    assert not verify_download(sec, "file1", exp + 1, sig)
    assert not verify_download(sec, "file1", None, sig) and not verify_download(sec, "file1", exp, None)
    e2, s2 = sign_download(sec, "file1", 60, now=time.time() - 120)
    assert not verify_download(sec, "file1", e2, s2)


def test_tokens():
    t = make_token("k", {"uid": 7}, 60)
    assert read_token("k", t)["uid"] == 7
    assert read_token("wrong", t) is None and read_token("k", t + "x") is None
    assert read_token("k", make_token("k", {"uid": 7}, 60, now=time.time() - 3600)) is None
    assert read_token("k", None) is None and read_token("k", "garbage") is None
    payload, sig = t.split(".")
    forged = payload[:-2] + "AA." + sig
    assert read_token("k", forged) is None


def test_rate_limiter_window():
    rl = RateLimiter()
    assert [rl.allow("a", 3, 10, now=t)[0] for t in (0, 1, 2, 3)] == [True, True, True, False]
    assert rl.allow("a", 3, 10, now=10.5)[0] is True  # oldest hit left the window
    ok, retry = rl.allow("b", 1, 10, now=0)
    ok2, retry2 = rl.allow("b", 1, 10, now=4)
    assert ok and not ok2 and retry2 == pytest.approx(6)


def test_store_isolation_and_id_validation(tmp):
    store = FileStore(tmp / "store", 60)
    fid, blob = store.begin()
    blob.write_bytes(b"%PDF-1.4")
    rec = store.commit(fid, "a.pdf", 8, "pdf", "x", "upload")
    assert store.get(fid).path == blob and len(fid) >= 32
    for bad in ("../../etc/passwd", "..", "", "a/b", "x" * 5, "a" * 22 + "/../b"):
        with pytest.raises(NotFound):
            store.get(bad)
    other = FileStore(tmp / "store", 60)  # a restart: metadata is re-read from disk
    assert other.get(fid).name == "a.pdf"
    store.delete(fid)
    with pytest.raises(NotFound):
        store.get(fid)
    assert not (tmp / "store" / fid).exists()
