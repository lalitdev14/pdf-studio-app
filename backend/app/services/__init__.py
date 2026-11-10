"""Operation registry: one entry per tool. The HTTP layer is generated from it."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .. import schemas as S
from ..validation import IMAGE_KINDS, OFFICE_KINDS
from . import compress as _compress
from . import convert_images, edit as _edit, extract, maintenance, office, overlay, pages, security, sign as _sign

PDF = frozenset({"pdf"})
IMG = frozenset(IMAGE_KINDS)


@dataclass(frozen=True)
class OpSpec:
    op: str
    path: str
    func: Callable
    model: type
    min_files: int = 1
    max_files: int = 1
    first: frozenset = PDF  # accepted kinds for the first file
    rest: frozenset | None = None  # accepted kinds for the others (default: same as first)
    description: str = ""


def _ops() -> list[OpSpec]:
    return [
        OpSpec("image-to-pdf", "/api/convert/image-to-pdf", convert_images.image_to_pdf, S.ImageToPdfOptions, 1, 200, IMG),
        OpSpec("pdf-to-image", "/api/convert/pdf-to-image", convert_images.pdf_to_image, S.PdfToImageOptions),
        OpSpec("merge", "/api/pdf/merge", pages.merge, S.MergeOptions, 2, 50),
        OpSpec("split", "/api/pdf/split", pages.split, S.SplitOptions),
        OpSpec("compress", "/api/pdf/compress", _compress.compress, S.CompressOptions),
        OpSpec("resize", "/api/pdf/resize", pages.resize, S.ResizeOptions),
        OpSpec("rotate", "/api/pdf/rotate", pages.rotate, S.RotateOptions),
        OpSpec("organize", "/api/pdf/organize", pages.organize, S.OrganizeOptions, 1, 21),
        OpSpec("blank-pages", "/api/pdf/blank-pages", pages.blank_pages, S.BlankPagesOptions),
        OpSpec("edit", "/api/pdf/edit", _edit.edit, S.EditOptions),
        OpSpec("watermark", "/api/pdf/watermark", overlay.watermark, S.WatermarkOptions, 1, 2, PDF, IMG),
        OpSpec("remove-watermark", "/api/pdf/remove-watermark", overlay.remove_watermark, S.RemoveWatermarkOptions),
        OpSpec("page-numbers", "/api/pdf/page-numbers", overlay.page_numbers, S.PageNumbersOptions),
        OpSpec("header-footer", "/api/pdf/header-footer", overlay.header_footer, S.HeaderFooterOptions),
        OpSpec("ocr", "/api/pdf/ocr", extract.ocr, S.OcrOptions),
        OpSpec("extract-text", "/api/pdf/extract-text", extract.extract_text, S.ExtractTextOptions),
        OpSpec("extract-images", "/api/pdf/extract-images", extract.extract_images, S.ExtractImagesOptions),
        OpSpec("protect", "/api/pdf/protect", security.protect, S.ProtectOptions),
        OpSpec("unlock", "/api/pdf/unlock", security.unlock, S.UnlockOptions),
        OpSpec("sign", "/api/pdf/sign", _sign.sign, S.SignOptions, 2, 2, PDF, frozenset({"p12"})),
        OpSpec("metadata", "/api/pdf/metadata", maintenance.metadata, S.MetadataOptions),
        OpSpec("flatten", "/api/pdf/flatten", maintenance.flatten, S.FlattenOptions),
        OpSpec("repair", "/api/pdf/repair", maintenance.repair, S.RepairOptions),
        OpSpec("compare", "/api/pdf/compare", maintenance.compare, S.CompareOptions, 2, 2),
        OpSpec("office-to-pdf", "/api/convert/office-to-pdf", office.office_to_pdf, S.NoOptions, 1, 1, frozenset(OFFICE_KINDS)),
        OpSpec("pdf-to-word", "/api/convert/pdf-to-word", office.pdf_to_docx, S.PdfToOfficeOptions),
        OpSpec("pdf-to-excel", "/api/convert/pdf-to-excel", office.pdf_to_xlsx, S.PdfToOfficeOptions),
        OpSpec("pdf-to-powerpoint", "/api/convert/pdf-to-powerpoint", office.pdf_to_pptx, S.PdfToOfficeOptions),
    ]


OPERATIONS: dict[str, OpSpec] = {s.op: s for s in _ops()}
