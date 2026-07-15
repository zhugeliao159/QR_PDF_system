from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


def _env_int(name: str, default: int, minimum: int = 1) -> int:
    raw = os.getenv(name, str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if value < minimum:
        raise ValueError(f"{name} must be at least {minimum}")
    return value


def _env_float(name: str, default: float, minimum: float = 0.0) -> float:
    raw = os.getenv(name, str(default))
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number") from exc
    if value < minimum:
        raise ValueError(f"{name} must be at least {minimum}")
    return value


@dataclass(frozen=True)
class Settings:
    public_base_url: str
    max_upload_size_mb: int
    max_pdf_pages: int
    max_binding_versions: int
    default_qr_size_mm: float
    default_qr_margin_mm: float
    database_path: Path
    storage_root: Path
    input_dir: Path
    output_dir: Path

    @classmethod
    def from_env(cls) -> "Settings":
        public_base_url = os.getenv(
            "PUBLIC_BASE_URL", "http://127.0.0.1:18081"
        ).rstrip("/")
        parsed = urlparse(public_base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("PUBLIC_BASE_URL must be an absolute http(s) URL")
        if parsed.query or parsed.fragment:
            raise ValueError("PUBLIC_BASE_URL cannot include a query or fragment")

        return cls(
            public_base_url=public_base_url,
            max_upload_size_mb=_env_int("MAX_UPLOAD_SIZE_MB", 100),
            max_pdf_pages=_env_int("MAX_PDF_PAGES", 500),
            max_binding_versions=_env_int("MAX_BINDING_VERSIONS", 5),
            default_qr_size_mm=_env_float("DEFAULT_QR_SIZE_MM", 20, 0.1),
            default_qr_margin_mm=_env_float("DEFAULT_QR_MARGIN_MM", 10),
            database_path=Path(
                os.getenv("PDF_WORKER_DATABASE_PATH", "/data/db/app.db")
            ),
            storage_root=Path(
                os.getenv("PDF_WORKER_STORAGE_ROOT", "/data/storage")
            ),
            input_dir=Path(os.getenv("PDF_INPUT_DIR", "/data/input")),
            output_dir=Path(os.getenv("PDF_OUTPUT_DIR", "/data/output")),
        )

    @property
    def max_upload_size_bytes(self) -> int:
        return self.max_upload_size_mb * 1024 * 1024

    @property
    def bindings_dir(self) -> Path:
        return self.storage_root / "bindings"

    @property
    def source_pdfs_dir(self) -> Path:
        return self.storage_root / "source-pdfs"

    @property
    def generated_pdfs_dir(self) -> Path:
        return self.storage_root / "generated-pdfs"

    @property
    def trash_dir(self) -> Path:
        return self.storage_root / ".trash"

    def ensure_directories(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        for path in (
            self.storage_root,
            self.bindings_dir,
            self.source_pdfs_dir,
            self.generated_pdfs_dir,
            self.trash_dir,
            self.input_dir,
            self.output_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)
