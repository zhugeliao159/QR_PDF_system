from __future__ import annotations

import unicodedata
from pathlib import Path

from app.errors import AppError
from app.storage.local import safe_display_filename


def pdf_identity(filename: str | None) -> tuple[str, str, str]:
    """Return the safe filename, visible name and stable matching key."""
    safe_name = safe_display_filename(filename)
    if Path(safe_name).suffix.lower() != ".pdf":
        raise AppError(415, "PDF_ONLY", "只支持 PDF 文件。")
    display_name = unicodedata.normalize("NFC", Path(safe_name).stem).strip()
    if not display_name:
        raise AppError(422, "PDF_NAME_REQUIRED", "PDF 文件名不能为空。")
    display_name = display_name[:240]
    return safe_name, display_name, display_name.casefold()
