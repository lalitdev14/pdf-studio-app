"""Upload validation: file-signature (magic byte) sniffing and name sanitising.

We never trust the client-supplied extension or Content-Type. The kind of a file
is decided only from its bytes.
"""
from __future__ import annotations

import re
import zipfile
from pathlib import Path

IMAGE_KINDS = {"jpeg", "png", "webp", "bmp", "tiff", "heic"}
WORD_KINDS = {"docx", "doc", "odt"}
EXCEL_KINDS = {"xlsx", "xls", "ods"}
PPT_KINDS = {"pptx", "ppt", "odp"}
OFFICE_KINDS = WORD_KINDS | EXCEL_KINDS | PPT_KINDS
ALL_KINDS = {"pdf", "p12"} | IMAGE_KINDS | OFFICE_KINDS

MIME = {
    "pdf": "application/pdf",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
    "bmp": "image/bmp",
    "tiff": "image/tiff",
    "heic": "image/heic",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "doc": "application/msword",
    "xls": "application/vnd.ms-excel",
    "ppt": "application/vnd.ms-powerpoint",
    "odt": "application/vnd.oasis.opendocument.text",
    "ods": "application/vnd.oasis.opendocument.spreadsheet",
    "odp": "application/vnd.oasis.opendocument.presentation",
    "zip": "application/zip",
    "txt": "text/plain; charset=utf-8",
    "p12": "application/x-pkcs12",
}

EXT = {"jpeg": ".jpg", "tiff": ".tif", "heic": ".heic"}

_OLE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_HEIC_BRANDS = {b"heic", b"heix", b"hevc", b"hevx", b"heim", b"heis", b"mif1", b"msf1", b"heif"}
_ODF = {
    b"application/vnd.oasis.opendocument.text": "odt",
    b"application/vnd.oasis.opendocument.spreadsheet": "ods",
    b"application/vnd.oasis.opendocument.presentation": "odp",
}


def ext_for(kind: str) -> str:
    return EXT.get(kind, "." + kind)


def sniff(path: Path, name_hint: str = "") -> str | None:
    """Return the detected kind or None when the file is not a supported type."""
    try:
        with open(path, "rb") as f:
            head = f.read(4096)
    except OSError:
        return None
    if not head:
        return None

    if b"%PDF-" in head[:1024]:
        return "pdf"
    if head[:3] == b"\xff\xd8\xff":
        return "jpeg"
    if head[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "webp"
    if head[:2] == b"BM" and len(head) > 26:
        return "bmp"
    if head[:4] in (b"II*\x00", b"MM\x00*", b"II+\x00", b"MM\x00+"):
        return "tiff"
    if head[4:8] == b"ftyp" and head[8:12] in _HEIC_BRANDS:
        return "heic"
    if head[:8] == _OLE:
        ext = Path(name_hint).suffix.lower().lstrip(".")
        return ext if ext in {"doc", "xls", "ppt"} else None
    if head[:4] == b"PK\x03\x04":
        return _sniff_zip(path)
    if head[:2] in (b"\x30\x82", b"\x30\x83", b"\x30\x80") and Path(name_hint).suffix.lower() in {".p12", ".pfx"}:
        return "p12"
    return None


def _sniff_zip(path: Path) -> str | None:
    try:
        with zipfile.ZipFile(path) as z:
            names = set(z.namelist())
            if "word/document.xml" in names:
                return "docx"
            if "xl/workbook.xml" in names:
                return "xlsx"
            if "ppt/presentation.xml" in names:
                return "pptx"
            if "mimetype" in names:
                mt = z.read("mimetype")[:100].strip()
                return _ODF.get(mt)
    except (zipfile.BadZipFile, OSError, KeyError, RuntimeError):
        return None
    return None


_BAD = re.compile(r"[^\w.\-() \[\]]+", re.UNICODE)


def safe_name(name: str | None, fallback: str = "file") -> str:
    """A display-safe file name (never used as an on-disk path)."""
    base = Path((name or "").replace("\\", "/")).name
    base = _BAD.sub("_", base).strip(" .")
    if not base:
        base = fallback
    if len(base) > 150:
        stem, dot, ext = base.rpartition(".")
        base = (stem[:140] + dot + ext[:8]) if dot else base[:150]
    return base


def stem_of(name: str) -> str:
    s = Path(name).stem
    return safe_name(s, "document")
