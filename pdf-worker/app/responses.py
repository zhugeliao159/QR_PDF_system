from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from urllib.parse import quote

from fastapi.responses import FileResponse


def content_disposition(filename: str, disposition: str = "attachment") -> str:
    normalized = unicodedata.normalize("NFC", filename)
    decomposed = unicodedata.normalize("NFKD", normalized)
    fallback = "".join(
        char if 32 <= ord(char) < 127 and char not in {'"', "\\", "/", ";"} else "_"
        for char in decomposed
    )
    fallback = re.sub(r"_+", "_", fallback).strip(" ._") or "download"
    fallback = fallback[:180]
    encoded = quote(normalized, safe="")
    return f'{disposition}; filename="{fallback}"; filename*=UTF-8\'\'{encoded}'


def download_response(
    path: Path,
    filename: str,
    media_type: str,
    disposition: str = "attachment",
    cache_control: str = "no-store",
) -> FileResponse:
    return FileResponse(
        path,
        media_type=media_type,
        headers={
            "Content-Disposition": content_disposition(filename, disposition),
            "Cache-Control": cache_control,
            "X-Content-Type-Options": "nosniff",
        },
    )
