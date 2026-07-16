from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any


COUNT_QUERIES = {
    "resources": "SELECT COUNT(*) FROM answer_resources",
    "revisions": "SELECT COUNT(*) FROM answer_revisions",
    "assets": "SELECT COUNT(*) FROM assets",
    "preview_sets": "SELECT COUNT(*) FROM preview_sets",
    "preview_pages": "SELECT COUNT(*) FROM preview_pages",
    "dynamic_aliases": "SELECT COUNT(*) FROM qr_aliases WHERE resolve_mode='latest'",
    "fixed_aliases": "SELECT COUNT(*) FROM qr_aliases WHERE resolve_mode='pinned'",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def database_counts(database_path: Path) -> dict[str, int]:
    connection = sqlite3.connect(database_path)
    try:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise RuntimeError(f"SQLite integrity_check failed: {integrity}")
        return {
            name: int(connection.execute(query).fetchone()[0])
            for name, query in COUNT_QUERIES.items()
        }
    finally:
        connection.close()


def write_manifest(root: Path, manifest_name: str = "manifest.json") -> Path:
    root = root.resolve()
    entries: dict[str, dict[str, Any]] = {}
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root).as_posix()
        if relative == manifest_name:
            continue
        entries[relative] = {"sha256": sha256_file(path), "size_bytes": path.stat().st_size}
    manifest = root / manifest_name
    manifest.write_text(
        json.dumps({"files": entries}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def verify_manifest(root: Path, manifest_name: str = "manifest.json") -> dict[str, Any]:
    root = root.resolve()
    payload = json.loads((root / manifest_name).read_text(encoding="utf-8"))
    expected: dict[str, dict[str, Any]] = payload["files"]
    actual_files = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and path.relative_to(root).as_posix() != manifest_name
    }
    if actual_files != set(expected):
        raise RuntimeError("backup manifest file set mismatch")
    for relative, metadata in expected.items():
        path = root / relative
        if path.stat().st_size != metadata["size_bytes"]:
            raise RuntimeError(f"backup size mismatch: {relative}")
        if sha256_file(path) != metadata["sha256"]:
            raise RuntimeError(f"backup SHA-256 mismatch: {relative}")
    return payload


def validate_snapshot(root: Path, expected_counts: dict[str, int] | None = None) -> dict[str, int]:
    root = root.resolve()
    database_path = root / "db" / "app.db"
    counts = database_counts(database_path)
    if expected_counts is not None and counts != expected_counts:
        raise RuntimeError(f"restored counts mismatch: {counts} != {expected_counts}")
    connection = sqlite3.connect(database_path)
    try:
        broken_aliases = int(connection.execute(
            """
            SELECT COUNT(*) FROM qr_aliases q
            LEFT JOIN answer_resources r ON r.id=q.resource_id
            LEFT JOIN answer_revisions v ON v.id=CASE WHEN q.resolve_mode='pinned'
              THEN q.pinned_revision_id ELSE r.current_published_revision_id END
            WHERE r.id IS NULL OR (q.status='active' AND v.id IS NULL)
            """
        ).fetchone()[0])
        if broken_aliases:
            raise RuntimeError(f"snapshot has {broken_aliases} broken aliases")
        for storage_key, digest in connection.execute("SELECT storage_key, sha256 FROM assets"):
            path = root / "storage" / storage_key
            if not path.is_file() or sha256_file(path) != digest:
                raise RuntimeError(f"snapshot Asset mismatch: {storage_key}")
        for storage_key, digest in connection.execute("SELECT storage_key, sha256 FROM preview_pages"):
            path = root / "storage" / storage_key
            if not path.is_file() or sha256_file(path) != digest:
                raise RuntimeError(f"snapshot PreviewPage mismatch: {storage_key}")
    finally:
        connection.close()
    return counts
