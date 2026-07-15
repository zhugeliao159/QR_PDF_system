from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ErrorBody(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorEnvelope(BaseModel):
    error: ErrorBody


class FileVersionOut(BaseModel):
    version_id: int
    version_number: int
    original_filename: str
    mime_type: str
    size_bytes: int
    sha256: str
    created_at: str
    is_current: bool
    note: str | None = None
    is_pinned: bool = False


class BindingOut(BaseModel):
    qr_id: str
    qr_url: str
    qr_png_url: str
    is_active: bool
    current_version: FileVersionOut
    version_count: int
    original_filename: str
    size_bytes: int
    sha256: str
    created_at: str
    updated_at: str
    note: str | None = None
    title: str
    display_code: str
    grade: str
    subject: str
    textbook_version: str | None = None
    chapter: str | None = None


class PdfJobOut(BaseModel):
    job_id: str
    status: Literal["processing", "completed", "failed"]
    qr_id: str
    source_filename: str
    page: int
    position: str
    size_mm: float
    margin_mm: float
    download_url: str | None = None
    output_size_bytes: int | None = None
    output_sha256: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    created_at: str
    completed_at: str | None = None
    qr_mode: Literal["dynamic", "fixed"] = "dynamic"
    qr_version_id: int | None = None
