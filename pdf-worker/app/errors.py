from __future__ import annotations

from typing import Any


class AppError(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details or {}


class UploadTooLargeError(AppError):
    def __init__(self, max_size_mb: int) -> None:
        super().__init__(
            413,
            "UPLOAD_TOO_LARGE",
            f"file exceeds the {max_size_mb} MiB upload limit",
            {"max_upload_size_mb": max_size_mb},
        )
