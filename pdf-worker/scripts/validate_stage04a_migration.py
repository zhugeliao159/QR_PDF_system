from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any


def _count(connection: sqlite3.Connection, table: str) -> int:
    return int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def _mapped_reference_type(value: str) -> str:
    if value in {"pdf_job", "pdf_job_fixed"}:
        return "pdf_job_fixed"
    if value == "manual_pin":
        return "manual_pin"
    return "legacy_fixed_link"


def _hash_file(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            size += len(chunk)
            digest.update(chunk)
    return size, digest.hexdigest()


def validate(database_path: Path, storage_root: Path) -> dict[str, Any]:
    database_path = database_path.resolve()
    storage_root = storage_root.resolve()
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")

    errors: list[str] = []
    counts: dict[str, int] = {}
    mismatches = {
        "resource_mapping": 0,
        "revision_mapping": 0,
        "asset_mapping": 0,
        "reference_mapping": 0,
        "pdf_job_mapping": 0,
        "missing_files": 0,
        "sha256": 0,
        "size_bytes": 0,
        "current_revision": 0,
        "public_token": 0,
        "foreign_keys": 0,
    }

    try:
        schema_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        integrity_check = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
        foreign_key_rows = connection.execute("PRAGMA foreign_key_check").fetchall()
        mismatches["foreign_keys"] = len(foreign_key_rows)

        table_names = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        required = {
            "bindings",
            "file_versions",
            "version_references",
            "pdf_jobs",
            "answer_resources",
            "assets",
            "answer_revisions",
            "qr_aliases",
            "revision_references",
            "audit_events",
            "pdf_jobs_v2",
        }
        missing_tables = sorted(required - table_names)
        if missing_tables:
            errors.append("missing tables: " + ", ".join(missing_tables))
            return {
                "status": "FAIL",
                "database": str(database_path),
                "storage_root": str(storage_root),
                "schema_version": schema_version,
                "integrity_check": integrity_check,
                "counts": counts,
                "mismatches": mismatches,
                "errors": errors,
            }

        counts.update(
            {
                "legacy_bindings": _count(connection, "bindings"),
                "answer_resources": int(
                    connection.execute(
                        "SELECT COUNT(*) FROM answer_resources "
                        "WHERE legacy_binding_id IS NOT NULL"
                    ).fetchone()[0]
                ),
                "answer_resources_total": _count(connection, "answer_resources"),
                "legacy_dynamic_qr": _count(connection, "bindings"),
                "latest_qr_aliases": int(
                    connection.execute(
                        "SELECT COUNT(*) FROM qr_aliases WHERE resolve_mode = 'latest' "
                        "AND legacy_binding_id IS NOT NULL"
                    ).fetchone()[0]
                ),
                "qr_aliases_total": _count(connection, "qr_aliases"),
                "legacy_file_versions": _count(connection, "file_versions"),
                "answer_revisions": int(
                    connection.execute(
                        "SELECT COUNT(*) FROM answer_revisions "
                        "WHERE legacy_version_id IS NOT NULL"
                    ).fetchone()[0]
                ),
                "answer_revisions_total": _count(connection, "answer_revisions"),
                "assets": int(
                    connection.execute(
                        "SELECT COUNT(*) FROM assets WHERE legacy_version_id IS NOT NULL"
                    ).fetchone()[0]
                ),
                "assets_total": _count(connection, "assets"),
                "legacy_version_references": _count(connection, "version_references"),
                "revision_references": int(
                    connection.execute(
                        "SELECT COUNT(*) FROM revision_references "
                        "WHERE legacy_version_id IS NOT NULL"
                    ).fetchone()[0]
                ),
                "revision_references_total": _count(connection, "revision_references"),
                "legacy_pdf_jobs": _count(connection, "pdf_jobs"),
                "pdf_jobs_v2": int(
                    connection.execute(
                        "SELECT COUNT(*) FROM pdf_jobs_v2 WHERE legacy_job_id IS NOT NULL"
                    ).fetchone()[0]
                ),
                "pdf_jobs_v2_total": _count(connection, "pdf_jobs_v2"),
            }
        )

        bindings = connection.execute("SELECT * FROM bindings ORDER BY id").fetchall()
        for binding in bindings:
            resource = connection.execute(
                "SELECT * FROM answer_resources WHERE legacy_binding_id = ?",
                (binding["id"],),
            ).fetchone()
            alias = connection.execute(
                "SELECT * FROM qr_aliases WHERE legacy_binding_id = ?",
                (binding["id"],),
            ).fetchone()
            expected_status = "active" if binding["is_active"] else "inactive"
            if resource is None or any(
                (
                    resource["name"] != binding["title"],
                    resource["display_code"] != binding["display_code"],
                    resource["grade"] != binding["grade"],
                    resource["subject"] != binding["subject"],
                    resource["textbook_version"] != binding["textbook_version"],
                    resource["chapter"] != binding["chapter"],
                    resource["note"] != binding["note"],
                    resource["status"] != expected_status,
                )
            ):
                mismatches["resource_mapping"] += 1
            if resource is None or (
                resource["current_published_revision_id"]
                != binding["current_version_id"]
            ):
                mismatches["current_revision"] += 1
            if alias is None or any(
                (
                    alias["public_token"] != binding["qr_id"],
                    alias["resource_id"] != binding["id"],
                    alias["resolve_mode"] != "latest",
                    alias["pinned_revision_id"] is not None,
                    alias["status"] != expected_status,
                )
            ):
                mismatches["public_token"] += 1

        physical_files: set[str] = set()
        versions = connection.execute("SELECT * FROM file_versions ORDER BY id").fetchall()
        for version in versions:
            revision = connection.execute(
                "SELECT * FROM answer_revisions WHERE legacy_version_id = ?",
                (version["id"],),
            ).fetchone()
            asset = connection.execute(
                "SELECT * FROM assets WHERE legacy_version_id = ?", (version["id"],)
            ).fetchone()
            if revision is None or any(
                (
                    revision["resource_id"] != version["binding_id"],
                    revision["revision_number"] != version["version_number"],
                    revision["target_type"] != "file",
                    revision["status"] != "published",
                    revision["external_url"] is not None,
                    revision["change_note"] != version["note"],
                    revision["created_at"] != version["created_at"],
                )
            ):
                mismatches["revision_mapping"] += 1
            if asset is None or any(
                (
                    asset["storage_backend"] != "local",
                    asset["storage_key"] != version["storage_path"],
                    asset["original_filename"] != version["original_filename"],
                    asset["mime_type"] != version["mime_type"],
                    asset["size_bytes"] != version["size_bytes"],
                    asset["sha256"] != version["sha256"],
                    revision is not None and revision["asset_id"] != asset["id"],
                )
            ):
                mismatches["asset_mapping"] += 1

            try:
                candidate = (storage_root / version["storage_path"]).resolve()
                if not candidate.is_relative_to(storage_root) or not candidate.is_file():
                    mismatches["missing_files"] += 1
                    continue
                physical_files.add(str(candidate))
                actual_size, actual_hash = _hash_file(candidate)
                if actual_size != version["size_bytes"]:
                    mismatches["size_bytes"] += 1
                if actual_hash != version["sha256"]:
                    mismatches["sha256"] += 1
            except OSError as exc:
                mismatches["missing_files"] += 1
                errors.append(f"cannot read {version['storage_path']}: {exc}")

        counts["legacy_physical_files"] = len(physical_files)

        references = connection.execute(
            "SELECT * FROM version_references ORDER BY id"
        ).fetchall()
        for reference in references:
            migrated = connection.execute(
                """
                SELECT 1 FROM revision_references
                WHERE legacy_version_id = ? AND reference_type = ?
                  AND source_job_id = ?
                """,
                (
                    reference["version_id"],
                    _mapped_reference_type(reference["reference_type"]),
                    reference["source_job_id"],
                ),
            ).fetchone()
            if migrated is None:
                mismatches["reference_mapping"] += 1

        jobs = connection.execute("SELECT * FROM pdf_jobs ORDER BY id").fetchall()
        for job in jobs:
            migrated = connection.execute(
                "SELECT * FROM pdf_jobs_v2 WHERE legacy_job_id = ?", (job["id"],)
            ).fetchone()
            if migrated is None or any(
                (
                    migrated["job_id"] != job["job_id"],
                    migrated["resource_id"] != job["binding_id"],
                    migrated["qr_mode"] != job["qr_mode"],
                    migrated["qr_revision_id"] != job["qr_version_id"],
                    migrated["source_storage_path"] != job["source_storage_path"],
                    migrated["output_storage_path"] != job["output_storage_path"],
                    migrated["output_sha256"] != job["output_sha256"],
                )
            ):
                mismatches["pdf_job_mapping"] += 1

        count_pairs = (
            ("legacy_bindings", "answer_resources"),
            ("legacy_dynamic_qr", "latest_qr_aliases"),
            ("legacy_file_versions", "answer_revisions"),
            ("legacy_file_versions", "assets"),
            ("legacy_version_references", "revision_references"),
            ("legacy_pdf_jobs", "pdf_jobs_v2"),
        )
        for old_name, new_name in count_pairs:
            if counts[old_name] != counts[new_name]:
                errors.append(
                    f"count mismatch: {old_name}={counts[old_name]}, "
                    f"{new_name}={counts[new_name]}"
                )
        if integrity_check != "ok":
            errors.append(f"integrity_check={integrity_check}")
        if schema_version < 3:
            errors.append(f"schema_version={schema_version}, expected at least 3")

        passed = not errors and not any(mismatches.values())
        return {
            "status": "PASS" if passed else "FAIL",
            "database": str(database_path),
            "storage_root": str(storage_root),
            "schema_version": schema_version,
            "integrity_check": integrity_check,
            "counts": counts,
            "mismatches": mismatches,
            "errors": errors,
        }
    finally:
        connection.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate the Stage 4A migration")
    parser.add_argument("database", type=Path)
    parser.add_argument("storage_root", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = validate(args.database, args.storage_root)
    payload = json.dumps(result, ensure_ascii=False, indent=2)
    print(payload)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
