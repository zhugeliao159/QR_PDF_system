from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class StoredObject:
    relative_path: str
    stored_filename: str
    original_filename: str
    mime_type: str
    size_bytes: int
    sha256: str
