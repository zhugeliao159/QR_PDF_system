from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.database import Database, new_public_key
from app.errors import AppError
from app.models import StoredObject, utc_now_iso
from app.storage.base import StorageBackend


@dataclass(frozen=True)
class ResolvedAnswer:
    alias: dict[str, Any]
    resource: dict[str, Any]
    revision: dict[str, Any]
    asset: dict[str, Any]


@dataclass(frozen=True)
class ResolvedContent:
    resource: dict[str, Any]
    revision: dict[str, Any]
    asset: dict[str, Any]


class AssetService:
    def __init__(self, database: Database, storage: StorageBackend) -> None:
        self.database = database
        self.storage = storage

    @staticmethod
    def create(
        connection: sqlite3.Connection,
        stored: StoredObject,
        created_at: str,
    ) -> int:
        cursor = connection.execute(
            """
            INSERT INTO assets
                (asset_key, storage_backend, storage_key, original_filename,
                 mime_type, size_bytes, sha256, created_at)
            VALUES (?, 'local', ?, ?, ?, ?, ?, ?)
            """,
            (
                new_public_key(), stored.relative_path, stored.original_filename,
                stored.mime_type, stored.size_bytes, stored.sha256, created_at,
            ),
        )
        return int(cursor.lastrowid)

    def get(self, asset_id: int) -> dict[str, Any]:
        with self.database.read() as connection:
            row = connection.execute(
                "SELECT * FROM assets WHERE id = ?", (asset_id,)
            ).fetchone()
        if row is None:
            raise AppError(503, "ASSET_MISSING", "answer asset does not exist")
        return dict(row)

    def path(self, asset: dict[str, Any]) -> Path:
        if asset["storage_backend"] != "local":
            raise AppError(500, "STORAGE_BACKEND_UNSUPPORTED", "storage backend is unsupported")
        return self.storage.resolve(asset["storage_key"])

    @staticmethod
    def is_referenced(connection: sqlite3.Connection, asset_id: int) -> bool:
        return connection.execute(
            "SELECT 1 FROM answer_revisions WHERE asset_id = ? LIMIT 1", (asset_id,)
        ).fetchone() is not None


class AnswerResourceService:
    def __init__(self, database: Database) -> None:
        self.database = database

    @staticmethod
    def create(
        connection: sqlite3.Connection,
        *,
        resource_key: str,
        name: str,
        display_code: str,
        grade: str,
        subject: str,
        textbook_version: str | None,
        chapter: str | None,
        note: str | None,
        created_at: str,
    ) -> int:
        cursor = connection.execute(
            """
            INSERT INTO answer_resources
                (resource_key, name, display_code, grade, subject,
                 textbook_version, chapter, note,
                 current_published_revision_id, status, row_version,
                 created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, 'active', 1, ?, ?)
            """,
            (
                resource_key, name, display_code, grade, subject,
                textbook_version, chapter, note, created_at, created_at,
            ),
        )
        return int(cursor.lastrowid)

    def get(self, resource_id: int) -> dict[str, Any]:
        with self.database.read() as connection:
            row = connection.execute(
                "SELECT * FROM answer_resources WHERE id = ?", (resource_id,)
            ).fetchone()
        if row is None:
            raise AppError(404, "RESOURCE_NOT_FOUND", "answer resource does not exist")
        return dict(row)

    def list_materials(
        self,
        search: str = "",
        grade: str = "",
        subject: str = "",
        status: str = "",
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        clauses = ["1 = 1"]
        parameters: list[Any] = []
        if search.strip():
            clauses.append(
                "(r.name LIKE ? OR r.display_code LIKE ? OR a.original_filename LIKE ? "
                "OR r.textbook_version LIKE ? OR r.chapter LIKE ?)"
            )
            pattern = f"%{search.strip()}%"
            parameters.extend([pattern] * 5)
        if grade:
            clauses.append("r.grade = ?")
            parameters.append(grade)
        if subject:
            clauses.append("r.subject = ?")
            parameters.append(subject)
        if status in {"active", "inactive"}:
            clauses.append("r.status = ?")
            parameters.append(status)
        where = " AND ".join(clauses)
        with self.database.read() as connection:
            total = int(
                connection.execute(
                    f"""SELECT COUNT(*) FROM answer_resources r
                    LEFT JOIN answer_revisions v
                      ON v.id = r.current_published_revision_id
                    LEFT JOIN assets a ON a.id = v.asset_id
                    WHERE {where}""",
                    parameters,
                ).fetchone()[0]
            )
            rows = connection.execute(
                f"""
                SELECT r.id, r.resource_key, r.name AS title, r.display_code,
                       r.grade, r.subject, r.textbook_version, r.chapter,
                       r.note, r.created_at, r.updated_at,
                       CASE WHEN r.status = 'active' THEN 1 ELSE 0 END AS is_active,
                       q.public_token AS qr_id,
                       a.original_filename, v.revision_number AS version_number,
                       a.size_bytes
                FROM answer_resources r
                JOIN qr_aliases q
                  ON q.resource_id = r.id AND q.resolve_mode = 'latest'
                LEFT JOIN answer_revisions v
                  ON v.id = r.current_published_revision_id
                LEFT JOIN assets a ON a.id = v.asset_id
                WHERE {where}
                ORDER BY r.updated_at DESC
                LIMIT ? OFFSET ?
                """,
                [*parameters, page_size, (max(page, 1) - 1) * page_size],
            ).fetchall()
        return [dict(row) for row in rows], total

    def update_metadata(
        self, resource_id: int, metadata: dict[str, str | None]
    ) -> None:
        with self.database.transaction() as connection:
            result = connection.execute(
                """
                UPDATE answer_resources
                SET name = ?, grade = ?, subject = ?, textbook_version = ?,
                    chapter = ?, note = ?, updated_at = ?, row_version = row_version + 1
                WHERE id = ?
                """,
                (
                    metadata["title"], metadata["grade"], metadata["subject"],
                    metadata["textbook_version"], metadata["chapter"], metadata["note"],
                    utc_now_iso(), resource_id,
                ),
            )
            if result.rowcount != 1:
                raise AppError(404, "RESOURCE_NOT_FOUND", "answer resource does not exist")

    def set_active(self, resource_id: int, active: bool) -> None:
        status = "active" if active else "inactive"
        now = utc_now_iso()
        with self.database.transaction() as connection:
            result = connection.execute(
                """
                UPDATE answer_resources
                SET status = ?, updated_at = ?, row_version = row_version + 1
                WHERE id = ?
                """,
                (status, now, resource_id),
            )
            if result.rowcount != 1:
                raise AppError(404, "RESOURCE_NOT_FOUND", "answer resource does not exist")
            connection.execute(
                "UPDATE qr_aliases SET status = ?, updated_at = ? WHERE resource_id = ?",
                (status, now, resource_id),
            )


class AnswerRevisionService:
    def __init__(self, database: Database, asset_service: AssetService) -> None:
        self.database = database
        self.asset_service = asset_service

    def create_published(
        self,
        connection: sqlite3.Connection,
        resource_id: int,
        stored: StoredObject,
        note: str | None,
        created_at: str,
    ) -> tuple[int, int]:
        resource = connection.execute(
            "SELECT id, status FROM answer_resources WHERE id = ?", (resource_id,)
        ).fetchone()
        if resource is None:
            raise AppError(404, "RESOURCE_NOT_FOUND", "answer resource does not exist")
        if resource["status"] != "active":
            raise AppError(410, "RESOURCE_INACTIVE", "answer resource is inactive")
        version_number = int(
            connection.execute(
                "SELECT COALESCE(MAX(revision_number), 0) + 1 "
                "FROM answer_revisions WHERE resource_id = ?",
                (resource_id,),
            ).fetchone()[0]
        )
        asset_id = self.asset_service.create(connection, stored, created_at)
        cursor = connection.execute(
            """
            INSERT INTO answer_revisions
                (revision_key, resource_id, revision_number, target_type,
                 asset_id, external_url, status, change_note,
                 created_at, published_at)
            VALUES (?, ?, ?, 'file', ?, NULL, 'published', ?, ?, ?)
            """,
            (
                new_public_key(), resource_id, version_number, asset_id,
                note, created_at, created_at,
            ),
        )
        revision_id = int(cursor.lastrowid)
        connection.execute(
            """
            UPDATE answer_resources
            SET current_published_revision_id = ?, updated_at = ?,
                row_version = row_version + 1
            WHERE id = ?
            """,
            (revision_id, created_at, resource_id),
        )
        return revision_id, version_number

    def list(self, resource_id: int) -> list[dict[str, Any]]:
        with self.database.read() as connection:
            rows = connection.execute(
                """
                SELECT v.*, a.original_filename, a.mime_type, a.size_bytes,
                       a.sha256, a.storage_key,
                       EXISTS(
                           SELECT 1 FROM revision_references rr
                           WHERE rr.revision_id = v.id
                       ) AS is_pinned
                FROM answer_revisions v
                JOIN assets a ON a.id = v.asset_id
                WHERE v.resource_id = ?
                ORDER BY v.revision_number DESC
                """,
                (resource_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def switch_current(self, resource_id: int, revision_id: int) -> None:
        with self.database.transaction() as connection:
            target = connection.execute(
                """
                SELECT v.id, v.status, v.asset_id
                FROM answer_revisions v
                WHERE v.id = ? AND v.resource_id = ?
                """,
                (revision_id, resource_id),
            ).fetchone()
            if target is None:
                raise AppError(404, "VERSION_NOT_FOUND", "version does not exist")
            if target["status"] != "published":
                raise AppError(409, "VERSION_NOT_PUBLISHED", "version is not published")
            asset = connection.execute(
                "SELECT * FROM assets WHERE id = ?", (target["asset_id"],)
            ).fetchone()
            if asset is None:
                raise AppError(503, "ASSET_MISSING", "answer asset does not exist")
            self.asset_service.path(dict(asset))
            result = connection.execute(
                """
                UPDATE answer_resources
                SET current_published_revision_id = ?, updated_at = ?,
                    row_version = row_version + 1
                WHERE id = ?
                """,
                (revision_id, utc_now_iso(), resource_id),
            )
            if result.rowcount != 1:
                raise AppError(404, "RESOURCE_NOT_FOUND", "answer resource does not exist")

    def pin(
        self,
        resource_id: int,
        revision_id: int,
        reference_type: str,
        source_job_id: str = "",
    ) -> None:
        if reference_type not in {"legacy_fixed_link", "pdf_job_fixed", "manual_pin"}:
            raise ValueError("unsupported revision reference type")
        with self.database.transaction() as connection:
            target = connection.execute(
                "SELECT id FROM answer_revisions WHERE id = ? AND resource_id = ?",
                (revision_id, resource_id),
            ).fetchone()
            if target is None:
                raise AppError(404, "VERSION_NOT_FOUND", "version does not exist")
            connection.execute(
                """
                INSERT OR IGNORE INTO revision_references
                    (revision_id, reference_type, source_job_id, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (revision_id, reference_type, source_job_id, utc_now_iso()),
            )


class QrResolverService:
    def __init__(self, database: Database) -> None:
        self.database = database

    def _alias_and_resource(
        self, public_token: str, allow_inactive: bool
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        with self.database.read() as connection:
            row = connection.execute(
                """
                SELECT q.id AS alias_id, q.public_token, q.display_code AS alias_display_code,
                       q.label, q.resource_id, q.resolve_mode, q.pinned_revision_id,
                       q.status AS alias_status, q.created_at AS alias_created_at,
                       q.updated_at AS alias_updated_at,
                       r.*
                FROM qr_aliases q
                JOIN answer_resources r ON r.id = q.resource_id
                WHERE q.public_token = ?
                """,
                (public_token,),
            ).fetchone()
        if row is None:
            raise AppError(404, "BINDING_NOT_FOUND", "binding does not exist")
        if not allow_inactive and (
            row["alias_status"] != "active" or row["status"] != "active"
        ):
            raise AppError(410, "BINDING_INACTIVE", "binding is inactive")
        alias = {
            "id": row["alias_id"],
            "public_token": row["public_token"],
            "display_code": row["alias_display_code"],
            "label": row["label"],
            "resource_id": row["resource_id"],
            "resolve_mode": row["resolve_mode"],
            "pinned_revision_id": row["pinned_revision_id"],
            "status": row["alias_status"],
            "created_at": row["alias_created_at"],
            "updated_at": row["alias_updated_at"],
        }
        resource = {
            key: row[key]
            for key in (
                "id", "resource_key", "name", "display_code", "grade", "subject",
                "textbook_version", "chapter", "note",
                "current_published_revision_id", "status", "row_version",
                "created_at", "updated_at", "legacy_binding_id",
            )
        }
        return alias, resource

    def _resolved(
        self,
        alias: dict[str, Any],
        resource: dict[str, Any],
        revision_id: int | None,
    ) -> ResolvedAnswer:
        if revision_id is None:
            raise AppError(503, "CURRENT_VERSION_MISSING", "current version is unavailable")
        with self.database.read() as connection:
            row = connection.execute(
                """
                SELECT v.*, a.asset_key, a.storage_backend, a.storage_key,
                       a.original_filename, a.mime_type, a.size_bytes, a.sha256,
                       a.created_at AS asset_created_at
                FROM answer_revisions v
                LEFT JOIN assets a ON a.id = v.asset_id
                WHERE v.id = ? AND v.resource_id = ?
                """,
                (revision_id, resource["id"]),
            ).fetchone()
        if row is None:
            raise AppError(404, "VERSION_NOT_FOUND", "version does not exist")
        if row["status"] != "published":
            raise AppError(404, "PUBLISHED_VERSION_MISSING", "published version is unavailable")
        if row["target_type"] != "file" or row["asset_id"] is None:
            raise AppError(409, "VERSION_TARGET_UNSUPPORTED", "version target is unsupported")
        if row["asset_key"] is None:
            raise AppError(503, "ASSET_MISSING", "answer asset does not exist")
        revision = {
            key: row[key]
            for key in (
                "id", "revision_key", "resource_id", "revision_number",
                "target_type", "asset_id", "external_url", "status",
                "change_note", "created_at", "published_at", "legacy_version_id",
            )
        }
        asset = {
            "id": row["asset_id"],
            "asset_key": row["asset_key"],
            "storage_backend": row["storage_backend"],
            "storage_key": row["storage_key"],
            "original_filename": row["original_filename"],
            "mime_type": row["mime_type"],
            "size_bytes": row["size_bytes"],
            "sha256": row["sha256"],
            "created_at": row["asset_created_at"],
        }
        return ResolvedAnswer(alias, resource, revision, asset)

    def resolve_latest(
        self, public_token: str, allow_inactive: bool = False
    ) -> ResolvedAnswer:
        alias, resource = self._alias_and_resource(public_token, allow_inactive)
        revision_id = (
            alias["pinned_revision_id"]
            if alias["resolve_mode"] == "pinned"
            else resource["current_published_revision_id"]
        )
        return self._resolved(alias, resource, revision_id)

    def resolve_revision(
        self,
        public_token: str,
        revision_id: int,
        allow_inactive: bool = False,
    ) -> ResolvedAnswer:
        alias, resource = self._alias_and_resource(public_token, allow_inactive)
        return self._resolved(alias, resource, revision_id)

    def resolve_content(self, revision_key: str) -> ResolvedContent:
        with self.database.read() as connection:
            row = connection.execute(
                """
                SELECT v.*, r.resource_key, r.name, r.display_code,
                       r.grade, r.subject, r.textbook_version, r.chapter,
                       r.note AS resource_note,
                       r.current_published_revision_id, r.status AS resource_status,
                       r.row_version, r.created_at AS resource_created_at,
                       r.updated_at AS resource_updated_at,
                       a.asset_key, a.storage_backend, a.storage_key,
                       a.original_filename, a.mime_type, a.size_bytes, a.sha256,
                       a.created_at AS asset_created_at
                FROM answer_revisions v
                JOIN answer_resources r ON r.id = v.resource_id
                LEFT JOIN assets a ON a.id = v.asset_id
                WHERE v.revision_key = ?
                """,
                (revision_key,),
            ).fetchone()
        if row is None:
            raise AppError(404, "VERSION_NOT_FOUND", "version does not exist")
        if row["resource_status"] != "active":
            raise AppError(410, "BINDING_INACTIVE", "binding is inactive")
        if row["status"] != "published":
            raise AppError(404, "PUBLISHED_VERSION_MISSING", "published version is unavailable")
        if row["target_type"] != "file" or row["asset_id"] is None:
            raise AppError(404, "VERSION_TARGET_UNSUPPORTED", "version target is unsupported")
        if row["asset_key"] is None:
            raise AppError(503, "ASSET_MISSING", "answer asset does not exist")
        resource = {
            "id": row["resource_id"],
            "resource_key": row["resource_key"],
            "name": row["name"],
            "display_code": row["display_code"],
            "grade": row["grade"],
            "subject": row["subject"],
            "textbook_version": row["textbook_version"],
            "chapter": row["chapter"],
            "note": row["resource_note"],
            "current_published_revision_id": row["current_published_revision_id"],
            "status": row["resource_status"],
            "row_version": row["row_version"],
            "created_at": row["resource_created_at"],
            "updated_at": row["resource_updated_at"],
        }
        revision = {
            key: row[key]
            for key in (
                "id", "revision_key", "resource_id", "revision_number",
                "target_type", "asset_id", "external_url", "status",
                "change_note", "created_at", "published_at", "legacy_version_id",
            )
        }
        asset = {
            "id": row["asset_id"],
            "asset_key": row["asset_key"],
            "storage_backend": row["storage_backend"],
            "storage_key": row["storage_key"],
            "original_filename": row["original_filename"],
            "mime_type": row["mime_type"],
            "size_bytes": row["size_bytes"],
            "sha256": row["sha256"],
            "created_at": row["asset_created_at"],
        }
        return ResolvedContent(resource, revision, asset)

    def get_or_create_pinned_alias(
        self,
        resource_id: int,
        revision_id: int,
        label: str | None = None,
        source_job_id: str = "",
    ) -> dict[str, Any]:
        now = utc_now_iso()
        with self.database.transaction() as connection:
            revision = connection.execute(
                """
                SELECT id, status FROM answer_revisions
                WHERE id = ? AND resource_id = ?
                """,
                (revision_id, resource_id),
            ).fetchone()
            if revision is None:
                raise AppError(404, "VERSION_NOT_FOUND", "version does not exist")
            if revision["status"] != "published":
                raise AppError(409, "VERSION_NOT_PUBLISHED", "version is not published")
            existing = connection.execute(
                """
                SELECT * FROM qr_aliases
                WHERE resource_id = ? AND resolve_mode = 'pinned'
                  AND pinned_revision_id = ? AND status = 'active'
                ORDER BY id LIMIT 1
                """,
                (resource_id, revision_id),
            ).fetchone()
            if existing is not None:
                alias = dict(existing)
            else:
                display_code = self.database._unique_display_code(
                    connection, "qr_aliases"
                )
                cursor = connection.execute(
                    """
                    INSERT INTO qr_aliases
                        (public_token, display_code, label, resource_id,
                         resolve_mode, pinned_revision_id, status,
                         created_at, updated_at)
                    VALUES (?, ?, ?, ?, 'pinned', ?, 'active', ?, ?)
                    """,
                    (
                        new_public_key(), display_code, label, resource_id,
                        revision_id, now, now,
                    ),
                )
                alias = dict(
                    connection.execute(
                        "SELECT * FROM qr_aliases WHERE id = ?",
                        (int(cursor.lastrowid),),
                    ).fetchone()
                )
                connection.execute(
                    """
                    INSERT INTO audit_events
                        (event_type, resource_id, revision_id, qr_alias_id,
                         actor, summary, created_at)
                    VALUES ('create_pinned_alias', ?, ?, ?, 'legacy-api', ?, ?)
                    """,
                    (
                        resource_id, revision_id, alias["id"],
                        "创建锁定版本二维码入口", now,
                    ),
                )
            connection.execute(
                """
                INSERT OR IGNORE INTO revision_references
                    (revision_id, reference_type, source_job_id, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    revision_id,
                    "pdf_job_fixed" if source_job_id else "manual_pin",
                    source_job_id,
                    now,
                ),
            )
        return alias
