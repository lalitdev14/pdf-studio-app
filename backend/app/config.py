"""Runtime configuration, read from environment variables (see .env.example)."""
from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def _bool(name: str, default: bool = False) -> bool:
    v = os.environ.get(name)
    if v is None:
        return default
    return v.strip().lower() in {"1", "true", "yes", "on"}


def _load_secret(data_dir: Path) -> str:
    env = os.environ.get("SECRET_KEY")
    if env:
        return env
    path = data_dir / ".secret"
    if path.exists():
        return path.read_text().strip()
    value = secrets.token_urlsafe(48)
    path.write_text(value)
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return value


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    secret_key: str
    max_file_mb: int
    max_request_mb: int
    max_files_per_request: int
    file_ttl_minutes: int
    download_link_ttl_seconds: int
    cors_origins: tuple[str, ...]
    rate_limit_mutating_per_min: int
    rate_limit_read_per_min: int
    trust_proxy: bool
    max_workers: int
    max_pages: int
    max_image_pixels: int
    max_render_pixels: int
    libreoffice_timeout: int
    libreoffice_concurrency: int
    subprocess_timeout: int
    frontend_dist: Path | None
    expose_reset_token: bool
    auth_token_ttl_hours: int
    unicode_font_path: str | None

    @property
    def max_file_bytes(self) -> int:
        return self.max_file_mb * 1024 * 1024

    @property
    def max_request_bytes(self) -> int:
        return self.max_request_mb * 1024 * 1024

    @property
    def file_ttl_seconds(self) -> int:
        return self.file_ttl_minutes * 60

    @property
    def files_dir(self) -> Path:
        return self.data_dir / "files"

    @property
    def work_dir(self) -> Path:
        return self.data_dir / "work"

    @property
    def user_files_dir(self) -> Path:
        return self.data_dir / "user_files"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "app.db"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    data_dir = Path(os.environ.get("DATA_DIR", "./data")).resolve()
    for sub in ("", "files", "work", "user_files"):
        (data_dir / sub).mkdir(parents=True, exist_ok=True)

    dist = os.environ.get("FRONTEND_DIST")
    dist_path = Path(dist).resolve() if dist else None
    if dist_path is not None and not dist_path.is_dir():
        dist_path = None

    origins = tuple(
        o.strip()
        for o in os.environ.get(
            "CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
        ).split(",")
        if o.strip()
    )
    return Settings(
        data_dir=data_dir,
        secret_key=_load_secret(data_dir),
        max_file_mb=_int("MAX_FILE_MB", 100),
        max_request_mb=_int("MAX_REQUEST_MB", 300),
        max_files_per_request=_int("MAX_FILES_PER_REQUEST", 50),
        file_ttl_minutes=_int("FILE_TTL_MINUTES", 60),
        download_link_ttl_seconds=_int("DOWNLOAD_LINK_TTL_SECONDS", 3600),
        cors_origins=origins,
        rate_limit_mutating_per_min=_int("RATE_LIMIT_MUTATING_PER_MIN", 60),
        rate_limit_read_per_min=_int("RATE_LIMIT_READ_PER_MIN", 1200),
        trust_proxy=_bool("TRUST_PROXY", False),
        max_workers=_int("MAX_WORKERS", 4),
        max_pages=_int("MAX_PAGES", 2000),
        max_image_pixels=_int("MAX_IMAGE_PIXELS", 178_956_970),
        max_render_pixels=_int("MAX_RENDER_PIXELS", 120_000_000),
        libreoffice_timeout=_int("LIBREOFFICE_TIMEOUT", 180),
        libreoffice_concurrency=_int("LIBREOFFICE_CONCURRENCY", 2),
        subprocess_timeout=_int("SUBPROCESS_TIMEOUT", 300),
        frontend_dist=dist_path,
        expose_reset_token=_bool("EXPOSE_RESET_TOKEN", False),
        auth_token_ttl_hours=_int("AUTH_TOKEN_TTL_HOURS", 24 * 7),
        unicode_font_path=os.environ.get("UNICODE_FONT_PATH"),
    )


def reset_settings() -> None:
    """Clear the settings cache (used by tests)."""
    get_settings.cache_clear()
