"""Cryptographic (PKCS#12) PDF signatures via the optional pyHanko package.

Image/handwritten signatures are placed with the editor (`image` annotations);
this module is for certificate-based digital signatures.
"""
from __future__ import annotations

from ..errors import AppError, DependencyMissing, InvalidRequest
from ..validation import stem_of
from .common import ServiceContext, prepare_pdf


def sign(ctx: ServiceContext) -> None:
    try:
        from pyhanko.sign import signers
        from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
    except ImportError as exc:
        raise DependencyMissing("Digital signatures need the 'pyHanko' package on the server (pip install pyhanko).") from exc

    o = ctx.options
    inp = ctx.pdf_input()
    if len(ctx.inputs) < 2 or ctx.inputs[1].kind != "p12":
        raise InvalidRequest("Upload your .p12 / .pfx certificate as the second file.")
    path = prepare_pdf(ctx, inp, o.get("password"))
    try:
        signer = signers.SimpleSigner.load_pkcs12(
            pfx_file=str(ctx.inputs[1].path), passphrase=(o.get("p12_password") or "").encode() or None
        )
    except Exception as exc:
        raise AppError("invalid_certificate", "The certificate could not be opened. Check the file and its password.", 422) from exc
    if signer is None:
        raise AppError("invalid_certificate", "The certificate could not be opened. Check the file and its password.", 422)
    out = ctx.new_path(".pdf")
    with open(path, "rb") as src:
        writer = IncrementalPdfFileWriter(src)
        meta = signers.PdfSignatureMetadata(
            field_name="Signature1", reason=o.get("reason") or None, location=o.get("location") or None
        )
        result = signers.sign_pdf(writer, meta, signer=signer)
        with open(out, "wb") as dst:
            dst.write(result.getbuffer())
    ctx.add_output(out, f"{stem_of(inp.name)}_signed.pdf")
    ctx.meta["note"] = "Cryptographically signed. Editing the file afterwards invalidates the signature."
