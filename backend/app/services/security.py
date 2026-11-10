"""Password protection / removal. We only ever open files with a password the
user supplies; there is deliberately no cracking or bypass logic here."""
from __future__ import annotations

import secrets

import pikepdf

from ..errors import AppError, CorruptFile
from ..validation import stem_of
from .common import ServiceContext


def _open(inp, password):
    try:
        return pikepdf.open(inp.path, password=password or "")
    except pikepdf.PasswordError:
        raise AppError(
            "wrong_password" if password else "password_required",
            "The password is incorrect." if password else f"'{inp.name}' is password protected. Enter its password.",
            422,
        )
    except (pikepdf.PdfError, OSError) as exc:
        raise CorruptFile(f"'{inp.name}' could not be read.") from exc


def protect(ctx: ServiceContext) -> None:
    o = ctx.options
    inp = ctx.pdf_input()
    restricted = not (o["allow_print"] and o["allow_copy"] and o["allow_edit"])
    owner = o.get("owner_password") or (secrets.token_urlsafe(24) if restricted else o["user_password"])
    perms = pikepdf.Permissions(
        accessibility=True,
        extract=o["allow_copy"],
        modify_annotation=o["allow_edit"],
        modify_assembly=o["allow_edit"],
        modify_form=o["allow_edit"],
        modify_other=o["allow_edit"],
        print_lowres=o["allow_print"],
        print_highres=o["allow_print"],
    )
    with _open(inp, o.get("password")) as pdf:
        out = ctx.new_path(".pdf")
        pdf.save(out, encryption=pikepdf.Encryption(user=o["user_password"], owner=owner, R=6, allow=perms))
    ctx.add_output(out, f"{stem_of(inp.name)}_protected.pdf")
    ctx.meta.update(
        encryption="AES-256 (PDF 2.0, revision 6)",
        allow_print=o["allow_print"], allow_copy=o["allow_copy"], allow_edit=o["allow_edit"],
    )


def unlock(ctx: ServiceContext) -> None:
    o = ctx.options
    inp = ctx.pdf_input()
    with _open(inp, o.get("password")) as pdf:
        was_encrypted = pdf.is_encrypted
        out = ctx.new_path(".pdf")
        pdf.save(out)
    ctx.add_output(out, f"{stem_of(inp.name)}_unlocked.pdf")
    ctx.meta["was_encrypted"] = was_encrypted
    if not was_encrypted:
        ctx.warnings.append("This PDF was not password protected.")


def describe_security(path) -> dict:
    """Security status for the info endpoint."""
    try:
        with pikepdf.open(path) as pdf:
            if not pdf.is_encrypted:
                return {"encrypted": False, "needs_password": False}
            enc = pdf.encryption
            a = pdf.allow
            return {
                "encrypted": True,
                "needs_password": False,  # opened with the empty user password
                "method": f"R{enc.R} / {enc.bits}-bit",
                "allow_print": bool(a.print_lowres or a.print_highres),
                "allow_copy": bool(a.extract),
                "allow_edit": bool(a.modify_other),
            }
    except pikepdf.PasswordError:
        return {"encrypted": True, "needs_password": True}
    except Exception:
        return {"encrypted": False, "needs_password": False, "unreadable": True}
