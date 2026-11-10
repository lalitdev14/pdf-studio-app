"""Application errors. Every AppError becomes a JSON response with a stable code."""
from __future__ import annotations


class AppError(Exception):
    status = 400

    def __init__(self, code: str, message: str, status: int | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        if status is not None:
            self.status = status

    def to_dict(self) -> dict:
        return {"code": self.code, "message": self.message}


class InvalidRequest(AppError):
    status = 422

    def __init__(self, message: str, code: str = "invalid_request"):
        super().__init__(code, message)


class UnsupportedFormat(AppError):
    status = 415

    def __init__(self, message: str, code: str = "unsupported_format"):
        super().__init__(code, message)


class TooLarge(AppError):
    status = 413

    def __init__(self, message: str, code: str = "too_large"):
        super().__init__(code, message)


class CorruptFile(AppError):
    status = 422

    def __init__(self, message: str, code: str = "corrupt_file"):
        super().__init__(code, message)


class NotFound(AppError):
    status = 404

    def __init__(self, message: str = "Not found", code: str = "not_found"):
        super().__init__(code, message)


class Unauthorized(AppError):
    status = 401

    def __init__(self, message: str = "Authentication required", code: str = "unauthorized"):
        super().__init__(code, message)


class Forbidden(AppError):
    status = 403

    def __init__(self, message: str = "Forbidden", code: str = "forbidden"):
        super().__init__(code, message)


class DependencyMissing(AppError):
    status = 501

    def __init__(self, message: str, code: str = "dependency_missing"):
        super().__init__(code, message)


class JobCancelled(Exception):
    """Raised inside a service when the user cancelled the job."""
