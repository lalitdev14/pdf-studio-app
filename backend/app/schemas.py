"""Pydantic option models, one per operation. The frontend sends them as JSON in
the ``options`` form field. Unknown keys are ignored; invalid values produce a
422 with a readable message."""
from __future__ import annotations

import re
from typing import Literal

from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator, model_validator

HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


class Opts(BaseModel):
    model_config = ConfigDict(extra="ignore")


class PdfOpts(Opts):
    password: str | None = Field(default=None, max_length=256)  # to open an encrypted input


def _hex(v: str) -> str:
    if not HEX.match(v):
        raise ValueError("must be a #rrggbb colour")
    return v


Color = Annotated[str, AfterValidator(_hex)]


# ---------------------------------------------------------------- conversions
class ImageToPdfOptions(Opts):
    mode: Literal["combined", "separate"] = "combined"
    page_size: Literal["a3", "a4", "a5", "letter", "legal", "custom", "image"] = "a4"
    custom_width_mm: float | None = Field(default=None, gt=10, le=5000)
    custom_height_mm: float | None = Field(default=None, gt=10, le=5000)
    orientation: Literal["portrait", "landscape", "auto"] = "portrait"
    fit: Literal["fit", "fill", "original"] = "fit"
    margin: Literal["none", "small", "medium", "large", "custom"] = "small"
    margin_mm: float = Field(default=10, ge=0, le=100)
    background: Color = "#ffffff"
    quality: int = Field(default=90, ge=10, le=100)
    page_numbers: bool = False
    rotations: list[int] = Field(default_factory=list, max_length=500)
    output_name: str | None = Field(default=None, max_length=120)


    @field_validator("rotations")
    @classmethod
    def _rot(cls, v):
        if any(r % 90 for r in v):
            raise ValueError("rotations must be multiples of 90")
        return [r % 360 for r in v]

    @model_validator(mode="after")
    def _custom(self):
        if self.page_size == "custom" and not (self.custom_width_mm and self.custom_height_mm):
            raise ValueError("custom page size needs custom_width_mm and custom_height_mm")
        return self


class PdfToImageOptions(PdfOpts):
    format: Literal["png", "jpg", "webp"] = "png"
    dpi: int = Field(default=150, ge=36, le=600)
    quality: int = Field(default=85, ge=10, le=100)
    pages: str = "all"


class PdfToOfficeOptions(PdfOpts):
    mode: Literal["text", "image"] = "text"  # pptx: "text" boxes vs full-page picture


class ExtractTextOptions(PdfOpts):
    pages: str = "all"
    layout: bool = True
    ocr_fallback: bool = False
    ocr_lang: str = "eng"


class ExtractImagesOptions(PdfOpts):
    pass


# --------------------------------------------------------------- page tools
class MergeOptions(Opts):
    pages: list[str] = Field(default_factory=list, max_length=100)  # per input, "" = all
    passwords: list[str] = Field(default_factory=list, max_length=100)


class SplitOptions(PdfOpts):
    mode: Literal["ranges", "every", "groups", "odd", "even", "extract"] = "ranges"
    ranges: str = ""  # "1-3,4-6,9" -> one file per part (mode=ranges)
    pages: str = ""  # selection for mode=extract
    group_size: int = Field(default=2, ge=1, le=1000)


class RotateOptions(PdfOpts):
    angle: Literal[90, 180, 270] = 90
    pages: str = "all"
    per_page: dict[int, int] = Field(default_factory=dict)  # {pageNo: angle} overrides

    @field_validator("per_page")
    @classmethod
    def _pp(cls, v):
        for k, a in v.items():
            if k < 1 or a % 90:
                raise ValueError("per_page needs 1-based pages and multiples of 90")
        return {k: a % 360 for k, a in v.items()}


class OrganizeEntry(Opts):
    src: int = Field(default=0, ge=0, le=20)
    page: int = Field(ge=1)
    rotate: int = 0

    @field_validator("rotate")
    @classmethod
    def _r(cls, v):
        if v % 90:
            raise ValueError("rotate must be a multiple of 90")
        return v % 360


class OrganizeOptions(Opts):
    pages: list[OrganizeEntry] = Field(min_length=1, max_length=5000)
    passwords: list[str] = Field(default_factory=list, max_length=21)


class BlankPagesOptions(PdfOpts):
    positions: list[int] = Field(default_factory=lambda: [0], max_length=500)  # 0 = before page 1
    count: int = Field(default=1, ge=1, le=50)
    size: Literal["match", "a4", "letter"] = "match"


class ResizeOptions(PdfOpts):
    size: Literal["a0", "a1", "a2", "a3", "a4", "a5", "letter", "legal", "tabloid", "custom"] = "a4"
    custom_width_mm: float | None = Field(default=None, gt=10, le=5000)
    custom_height_mm: float | None = Field(default=None, gt=10, le=5000)
    orientation: Literal["portrait", "landscape", "auto"] = "auto"
    mode: Literal["fit", "fill", "stretch"] = "fit"
    margin_mm: float = Field(default=0, ge=0, le=100)
    pages: str = "all"

    @model_validator(mode="after")
    def _custom(self):
        if self.size == "custom" and not (self.custom_width_mm and self.custom_height_mm):
            raise ValueError("custom size needs custom_width_mm and custom_height_mm")
        return self


class CompressOptions(PdfOpts):
    level: Literal["low", "recommended", "high"] = "recommended"
    strip_metadata: bool = True


# -------------------------------------------------------------- security
class ProtectOptions(PdfOpts):
    user_password: str = Field(min_length=1, max_length=128)
    owner_password: str | None = Field(default=None, max_length=128)
    allow_print: bool = True
    allow_copy: bool = True
    allow_edit: bool = True

    @model_validator(mode="after")
    def _owner(self):
        restricted = not (self.allow_print and self.allow_copy and self.allow_edit)
        if restricted and not self.owner_password:
            raise ValueError("Set an owner password when restricting permissions, otherwise nobody can lift the restrictions later.")
        return self


class UnlockOptions(PdfOpts):
    confirm_authorized: bool = False

    @model_validator(mode="after")
    def _c(self):
        if not self.confirm_authorized:
            raise ValueError("Confirm that you are authorised to remove this password.")
        return self


class SignOptions(PdfOpts):
    p12_password: str = Field(default="", max_length=256)
    reason: str = Field(default="", max_length=200)
    location: str = Field(default="", max_length=200)


# --------------------------------------------------------- stamping / overlays
class WatermarkOptions(PdfOpts):
    kind: Literal["text", "image"] = "text"
    text: str = Field(default="CONFIDENTIAL", max_length=200)
    font_size: float = Field(default=64, ge=6, le=400)
    color: Color = "#888888"
    opacity: float = Field(default=0.25, ge=0.02, le=1.0)
    rotation: float = Field(default=45, ge=-180, le=180)
    position: Literal["center", "tile"] = "center"
    layer: Literal["over", "under"] = "over"
    image_scale_pct: float = Field(default=50, ge=5, le=100)
    pages: str = "all"



class RemoveWatermarkOptions(PdfOpts):
    pages: str = "all"
    confirm_authorized: bool = False

    @model_validator(mode="after")
    def _c(self):
        if not self.confirm_authorized:
            raise ValueError("Confirm that you are authorised to remove this watermark.")
        return self


Pos = Literal["bottom-center", "bottom-left", "bottom-right", "top-center", "top-left", "top-right"]


class PageNumbersOptions(PdfOpts):
    format: str = Field(default="{n}", max_length=100)  # tokens: {n} {total}
    position: Pos = "bottom-center"
    start_at: int = Field(default=1, ge=-999, le=99999)
    skip_first: bool = False
    font: Literal["helvetica", "times", "courier"] = "helvetica"
    font_size: float = Field(default=10, ge=4, le=72)
    color: Color = "#333333"
    margin_pt: float = Field(default=28, ge=0, le=200)
    pages: str = "all"



class HeaderFooterOptions(PdfOpts):
    header_left: str = Field(default="", max_length=200)
    header_center: str = Field(default="", max_length=200)
    header_right: str = Field(default="", max_length=200)
    footer_left: str = Field(default="", max_length=200)
    footer_center: str = Field(default="", max_length=200)
    footer_right: str = Field(default="", max_length=200)  # tokens: {n} {total} {date} {filename}
    font: Literal["helvetica", "times", "courier"] = "helvetica"
    font_size: float = Field(default=10, ge=4, le=72)
    color: Color = "#333333"
    margin_pt: float = Field(default=28, ge=0, le=200)
    skip_first: bool = False
    pages: str = "all"



# ------------------------------------------------------------------ editor
class Annotation(Opts):
    id: str = ""
    type: Literal[
        "text", "textbox", "date", "highlight", "underline", "strike", "rect", "ellipse",
        "line", "arrow", "freehand", "image", "comment", "replace",
    ]
    page: int = Field(ge=1)
    x: float = Field(default=0, ge=-0.5, le=1.5)  # fractions of the displayed page, top-left origin
    y: float = Field(default=0, ge=-0.5, le=1.5)
    w: float = Field(default=0, ge=0, le=2)
    h: float = Field(default=0, ge=0, le=2)
    x2: float | None = None
    y2: float | None = None
    points: list[tuple[float, float]] | None = Field(default=None, max_length=8000)
    text: str = Field(default="", max_length=5000)
    font: Literal["helvetica", "times", "courier"] = "helvetica"
    bold: bool = False
    italic: bool = False
    size: float = Field(default=14, ge=3, le=300)  # points
    color: str = "#000000"
    fill: str | None = None
    stroke_width: float = Field(default=2, ge=0.1, le=60)
    opacity: float = Field(default=1.0, ge=0.02, le=1.0)
    image: str | None = Field(default=None, max_length=14_000_000)  # data URL

    @field_validator("color")
    @classmethod
    def _col(cls, v):
        return _hex(v)

    @field_validator("fill")
    @classmethod
    def _fill(cls, v):
        return None if v in (None, "") else _hex(v)


class EditOptions(PdfOpts):
    annotations: list[Annotation] = Field(max_length=3000)


# ---------------------------------------------------------- misc utilities
class OcrOptions(PdfOpts):
    lang: str = Field(default="eng", pattern=r"^[a-zA-Z_]{2,12}(\+[a-zA-Z_]{2,12}){0,3}$")
    dpi: int = Field(default=300, ge=100, le=400)
    skip_text_pages: bool = True
    output: Literal["pdf", "txt", "both"] = "pdf"
    pages: str = "all"


class MetadataOptions(PdfOpts):
    title: str | None = Field(default=None, max_length=500)
    author: str | None = Field(default=None, max_length=500)
    subject: str | None = Field(default=None, max_length=500)
    keywords: str | None = Field(default=None, max_length=1000)
    creator: str | None = Field(default=None, max_length=500)
    producer: str | None = Field(default=None, max_length=500)
    clear_all: bool = False


class FlattenOptions(PdfOpts):
    mode: Literal["all", "screen", "print"] = "all"


class RepairOptions(Opts):
    pass


class CompareOptions(Opts):
    dpi: int = Field(default=80, ge=40, le=200)
    sensitivity: int = Field(default=40, ge=5, le=200)  # pixel difference threshold
    passwords: list[str] = Field(default_factory=list, max_length=2)


class NoOptions(Opts):
    pass
