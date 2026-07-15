from __future__ import annotations

import logging
import sqlite3
import uuid
from dataclasses import replace
from pathlib import Path
from typing import Any

import fitz
from fastapi import UploadFile
from PIL import Image, UnidentifiedImageError

from app.config import Settings
from app.database import Database
from app.errors import AppError
from app.models import StoredObject, utc_now_iso
from app.services.qr_service import QrService
from app.storage.base import StorageBackend


logger = logging.getLogger(__name__)
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff"}
GRADES = {"未分类", "高一", "高二", "高三", "高中通用"}
SUBJECTS = {
    "未分类", "语文", "数学", "英语", "物理", "化学", "生物", "思想政治",
    "历史", "地理", "信息技术", "通用技术", "其他",
}


class BindingService:
    def __init__(
        self,
        settings: Settings,
        database: Database,
        storage: StorageBackend,
        qr_service: QrService,
    ) -> None:
        self.settings = settings
        self.database = database
        self.storage = storage
        self.qr_service = qr_service

    def _validate_binding_file(self, stored: StoredObject) -> StoredObject:
        path = self.storage.resolve(stored.relative_path)
        suffix = Path(stored.original_filename).suffix.lower()
        with path.open("rb") as stream:
            header = stream.read(16)

        is_pdf = header.startswith(b"%PDF-")
        if suffix == ".pdf" or stored.mime_type == "application/pdf" or is_pdf:
            if not is_pdf:
                raise AppError(
                    415,
                    "INVALID_PDF_FILE",
                    "file is declared as PDF but does not contain a PDF header",
                )
            try:
                with fitz.open(path) as document:
                    if document.needs_pass:
                        raise AppError(
                            422,
                            "ENCRYPTED_BINDING_FILE",
                            "encrypted PDF files are not supported as binding files",
                        )
                    if document.page_count <= 0:
                        raise AppError(422, "EMPTY_PDF", "PDF has no pages")
            except AppError:
                raise
            except Exception as exc:
                raise AppError(422, "INVALID_PDF_FILE", "PDF cannot be opened") from exc
            return replace(stored, mime_type="application/pdf")

        if stored.mime_type.startswith("image/") or suffix in IMAGE_SUFFIXES:
            try:
                with Image.open(path) as image:
                    image.verify()
                    detected = Image.MIME.get(image.format, stored.mime_type)
            except (OSError, UnidentifiedImageError) as exc:
                raise AppError(415, "INVALID_IMAGE_FILE", "image cannot be opened") from exc
            return replace(stored, mime_type=detected)

        return stored

    @staticmethod
    def _version_out(row: sqlite3.Row, current_version_id: int) -> dict[str, Any]:
        return {
            "version_id": row["id"],
            "version_number": row["version_number"],
            "original_filename": row["original_filename"],
            "mime_type": row["mime_type"],
            "size_bytes": row["size_bytes"],
            "sha256": row["sha256"],
            "created_at": row["created_at"],
            "is_current": row["id"] == current_version_id,
            "note": row["note"],
            "is_pinned": bool(row["is_pinned"]) if "is_pinned" in row.keys() else False,
        }

    @staticmethod
    def _clean_metadata(
        title: str,
        grade: str,
        subject: str,
        textbook_version: str | None,
        chapter: str | None,
        note: str | None,
    ) -> dict[str, str | None]:
        cleaned_title = title.strip()
        if not 1 <= len(cleaned_title) <= 100:
            raise AppError(422, "INVALID_TITLE", "title must contain 1 to 100 characters")
        if grade not in GRADES:
            raise AppError(422, "INVALID_GRADE", "grade is not supported")
        if subject not in SUBJECTS:
            raise AppError(422, "INVALID_SUBJECT", "subject is not supported")

        def optional(value: str | None, limit: int, field: str) -> str | None:
            cleaned = (value or "").strip()
            if len(cleaned) > limit:
                raise AppError(422, f"INVALID_{field.upper()}", f"{field} is too long")
            return cleaned or None

        return {
            "title": cleaned_title,
            "grade": grade,
            "subject": subject,
            "textbook_version": optional(textbook_version, 100, "textbook_version"),
            "chapter": optional(chapter, 200, "chapter"),
            "note": optional(note, 500, "note"),
        }

    def _binding_row(self, qr_id: str, allow_inactive: bool = False) -> sqlite3.Row:
        with self.database.read() as connection:
            row = connection.execute(
                """
                SELECT b.*, v.id AS version_id, v.version_number,
                       v.original_filename, v.mime_type, v.size_bytes, v.sha256,
                       v.created_at AS version_created_at, v.note AS version_note,
                       v.storage_path
                FROM bindings b
                LEFT JOIN file_versions v ON v.id = b.current_version_id
                WHERE b.qr_id = ?
                """,
                (qr_id,),
            ).fetchone()
        if row is None:
            raise AppError(404, "BINDING_NOT_FOUND", "binding does not exist")
        if not row["is_active"] and not allow_inactive:
            raise AppError(410, "BINDING_INACTIVE", "binding is inactive")
        if row["version_id"] is None:
            raise AppError(409, "CURRENT_VERSION_MISSING", "current version is unavailable")
        return row

    def get_binding(self, qr_id: str, allow_inactive: bool = False) -> dict[str, Any]:
        row = self._binding_row(qr_id, allow_inactive)
        with self.database.read() as connection:
            version_count = connection.execute(
                "SELECT COUNT(*) FROM file_versions WHERE binding_id = ?",
                (row["id"],),
            ).fetchone()[0]
            version_row = connection.execute(
                """
                SELECT v.*, EXISTS(
                    SELECT 1 FROM version_references r WHERE r.version_id = v.id
                ) AS is_pinned
                FROM file_versions v WHERE v.id = ?
                """,
                (row["version_id"],),
            ).fetchone()
        current = self._version_out(version_row, row["version_id"])
        return {
            "qr_id": row["qr_id"],
            "qr_url": self.qr_service.qr_url(row["qr_id"]),
            "qr_png_url": self.qr_service.qr_png_url(row["qr_id"]),
            "is_active": bool(row["is_active"]),
            "current_version": current,
            "version_count": version_count,
            "original_filename": current["original_filename"],
            "size_bytes": current["size_bytes"],
            "sha256": current["sha256"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "note": row["note"],
            "title": row["title"],
            "display_code": row["display_code"],
            "grade": row["grade"],
            "subject": row["subject"],
            "textbook_version": row["textbook_version"],
            "chapter": row["chapter"],
        }

    async def create_binding(
        self,
        upload: UploadFile,
        note: str | None = None,
        title: str | None = None,
        grade: str = "未分类",
        subject: str = "未分类",
        textbook_version: str | None = None,
        chapter: str | None = None,
    ) -> dict[str, Any]:
        qr_id = uuid.uuid4().hex
        stored = await self.storage.save_binding_upload(
            upload, qr_id, self.settings.max_upload_size_bytes
        )
        try:
            stored = self._validate_binding_file(stored)
            metadata = self._clean_metadata(
                title or Path(stored.original_filename).stem or "未命名解析资料",
                grade,
                subject,
                textbook_version,
                chapter,
                note,
            )
            now = utc_now_iso()
            with self.database.transaction() as connection:
                display_code = self.database._unique_display_code(connection)
                cursor = connection.execute(
                    """
                    INSERT INTO bindings
                        (qr_id, current_version_id, title, display_code, grade, subject,
                         textbook_version, chapter, created_at, updated_at, note, is_active)
                    VALUES (?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                    """,
                    (
                        qr_id, metadata["title"], display_code, metadata["grade"],
                        metadata["subject"], metadata["textbook_version"],
                        metadata["chapter"], now, now, metadata["note"],
                    ),
                )
                binding_id = int(cursor.lastrowid)
                version_cursor = connection.execute(
                    """
                    INSERT INTO file_versions
                        (binding_id, version_number, original_filename, stored_filename,
                         storage_path, mime_type, size_bytes, sha256, created_at, note,
                         storage_backend)
                    VALUES (?, 1, ?, ?, ?, ?, ?, ?, ?, ?, 'local')
                    """,
                    (
                        binding_id,
                        stored.original_filename,
                        stored.stored_filename,
                        stored.relative_path,
                        stored.mime_type,
                        stored.size_bytes,
                        stored.sha256,
                        now,
                        metadata["note"],
                    ),
                )
                connection.execute(
                    "UPDATE bindings SET current_version_id = ? WHERE id = ?",
                    (int(version_cursor.lastrowid), binding_id),
                )
        except Exception:
            self.storage.delete(stored.relative_path)
            raise

        logger.info("binding created qr_id=%s version=1", qr_id)
        return self.get_binding(qr_id)

    async def replace_file(
        self, qr_id: str, upload: UploadFile, note: str | None = None
    ) -> dict[str, Any]:
        binding = self._binding_row(qr_id)
        stored = await self.storage.save_binding_upload(
            upload, qr_id, self.settings.max_upload_size_bytes
        )
        try:
            stored = self._validate_binding_file(stored)
            now = utc_now_iso()
            with self.database.transaction() as connection:
                current = connection.execute(
                    "SELECT id, is_active FROM bindings WHERE id = ?", (binding["id"],)
                ).fetchone()
                if current is None:
                    raise AppError(404, "BINDING_NOT_FOUND", "binding does not exist")
                if not current["is_active"]:
                    raise AppError(410, "BINDING_INACTIVE", "binding is inactive")
                version_number = int(
                    connection.execute(
                        "SELECT COALESCE(MAX(version_number), 0) + 1 "
                        "FROM file_versions WHERE binding_id = ?",
                        (binding["id"],),
                    ).fetchone()[0]
                )
                cursor = connection.execute(
                    """
                    INSERT INTO file_versions
                        (binding_id, version_number, original_filename, stored_filename,
                         storage_path, mime_type, size_bytes, sha256, created_at, note,
                         storage_backend)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'local')
                    """,
                    (
                        binding["id"],
                        version_number,
                        stored.original_filename,
                        stored.stored_filename,
                        stored.relative_path,
                        stored.mime_type,
                        stored.size_bytes,
                        stored.sha256,
                        now,
                        note,
                    ),
                )
                connection.execute(
                    """
                    UPDATE bindings
                    SET current_version_id = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (int(cursor.lastrowid), now, binding["id"]),
                )
        except Exception:
            self.storage.delete(stored.relative_path)
            raise

        self._cleanup_old_versions(binding["id"])
        logger.info(
            "binding file replaced qr_id=%s version=%s", qr_id, version_number
        )
        return self.get_binding(qr_id)

    def _cleanup_old_versions(self, binding_id: int) -> None:
        while True:
            with self.database.read() as connection:
                binding = connection.execute(
                    "SELECT current_version_id FROM bindings WHERE id = ?", (binding_id,)
                ).fetchone()
                count = int(
                    connection.execute(
                        """
                        SELECT COUNT(*) FROM file_versions v
                        WHERE v.binding_id = ? AND NOT EXISTS (
                            SELECT 1 FROM version_references r WHERE r.version_id = v.id
                        )
                        """,
                        (binding_id,),
                    ).fetchone()[0]
                )
                if count <= self.settings.max_binding_versions:
                    return
                candidate = connection.execute(
                    """
                    SELECT v.id, v.storage_path FROM file_versions v
                    WHERE v.binding_id = ? AND v.id != ? AND NOT EXISTS (
                        SELECT 1 FROM version_references r WHERE r.version_id = v.id
                    )
                    ORDER BY version_number ASC
                    LIMIT 1
                    """,
                    (binding_id, binding["current_version_id"]),
                ).fetchone()
            if candidate is None:
                logger.error("version cleanup found no removable version binding_id=%s", binding_id)
                return

            try:
                trash_path = self.storage.move_to_trash(candidate["storage_path"])
            except Exception:
                logger.exception(
                    "version cleanup could not move file binding_id=%s version_id=%s",
                    binding_id,
                    candidate["id"],
                )
                return

            try:
                with self.database.transaction() as connection:
                    current = connection.execute(
                        "SELECT current_version_id FROM bindings WHERE id = ?",
                        (binding_id,),
                    ).fetchone()
                    if current["current_version_id"] == candidate["id"]:
                        raise RuntimeError("cleanup candidate became current")
                    connection.execute(
                        "DELETE FROM file_versions WHERE id = ? AND binding_id = ?",
                        (candidate["id"], binding_id),
                    )
            except Exception:
                self.storage.restore_from_trash(trash_path, candidate["storage_path"])
                logger.exception(
                    "version cleanup database update failed binding_id=%s version_id=%s",
                    binding_id,
                    candidate["id"],
                )
                return

            try:
                self.storage.delete(trash_path)
            except Exception:
                logger.exception(
                    "version cleanup left trash file binding_id=%s version_id=%s",
                    binding_id,
                    candidate["id"],
                )

    def list_versions(
        self, qr_id: str, allow_inactive: bool = False
    ) -> list[dict[str, Any]]:
        binding = self._binding_row(qr_id, allow_inactive)
        with self.database.read() as connection:
            rows = connection.execute(
                """
                SELECT v.*, EXISTS(
                    SELECT 1 FROM version_references r WHERE r.version_id = v.id
                ) AS is_pinned
                FROM file_versions v
                WHERE v.binding_id = ?
                ORDER BY version_number DESC
                """,
                (binding["id"],),
            ).fetchall()
        return [self._version_out(row, binding["current_version_id"]) for row in rows]

    def rollback(self, qr_id: str, version_id: int) -> dict[str, Any]:
        binding = self._binding_row(qr_id)
        with self.database.read() as connection:
            target = connection.execute(
                "SELECT * FROM file_versions WHERE id = ? AND binding_id = ?",
                (version_id, binding["id"]),
            ).fetchone()
        if target is None:
            raise AppError(404, "VERSION_NOT_FOUND", "version does not exist")
        self.storage.resolve(target["storage_path"])
        now = utc_now_iso()
        with self.database.transaction() as connection:
            connection.execute(
                """
                UPDATE bindings
                SET current_version_id = ?, updated_at = ?
                WHERE id = ?
                """,
                (version_id, now, binding["id"]),
            )
        logger.info("binding rolled back qr_id=%s version_id=%s", qr_id, version_id)
        return self.get_binding(qr_id)

    def current_file(self, qr_id: str) -> tuple[Path, str, str]:
        binding = self._binding_row(qr_id)
        path = self.storage.resolve(binding["storage_path"])
        return path, binding["original_filename"], binding["mime_type"]

    def version_file(self, qr_id: str, version_id: int) -> tuple[Path, str, str]:
        binding = self._binding_row(qr_id)
        with self.database.read() as connection:
            version = connection.execute(
                "SELECT * FROM file_versions WHERE id = ? AND binding_id = ?",
                (version_id, binding["id"]),
            ).fetchone()
        if version is None:
            raise AppError(404, "VERSION_NOT_FOUND", "version does not exist")
        return (
            self.storage.resolve(version["storage_path"]),
            version["original_filename"],
            version["mime_type"],
        )

    def pin_version(
        self,
        qr_id: str,
        version_id: int,
        reference_type: str,
        source_job_id: str = "",
    ) -> None:
        binding = self._binding_row(qr_id)
        with self.database.transaction() as connection:
            version = connection.execute(
                "SELECT id FROM file_versions WHERE id = ? AND binding_id = ?",
                (version_id, binding["id"]),
            ).fetchone()
            if version is None:
                raise AppError(404, "VERSION_NOT_FOUND", "version does not exist")
            connection.execute(
                """
                INSERT OR IGNORE INTO version_references
                    (version_id, reference_type, source_job_id, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (version_id, reference_type, source_job_id, utc_now_iso()),
            )

    def current_version_id(self, qr_id: str) -> int:
        return int(self._binding_row(qr_id)["version_id"])

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
                "(b.title LIKE ? OR b.display_code LIKE ? OR v.original_filename LIKE ? "
                "OR b.textbook_version LIKE ? OR b.chapter LIKE ?)"
            )
            pattern = f"%{search.strip()}%"
            parameters.extend([pattern] * 5)
        if grade:
            clauses.append("b.grade = ?")
            parameters.append(grade)
        if subject:
            clauses.append("b.subject = ?")
            parameters.append(subject)
        if status in {"active", "inactive"}:
            clauses.append("b.is_active = ?")
            parameters.append(1 if status == "active" else 0)
        where = " AND ".join(clauses)
        with self.database.read() as connection:
            total = int(
                connection.execute(
                    f"""SELECT COUNT(*) FROM bindings b
                    LEFT JOIN file_versions v ON v.id = b.current_version_id
                    WHERE {where}""",
                    parameters,
                ).fetchone()[0]
            )
            rows = connection.execute(
                f"""
                SELECT b.*, v.original_filename, v.version_number, v.size_bytes
                FROM bindings b
                LEFT JOIN file_versions v ON v.id = b.current_version_id
                WHERE {where}
                ORDER BY b.updated_at DESC
                LIMIT ? OFFSET ?
                """,
                [*parameters, page_size, (max(page, 1) - 1) * page_size],
            ).fetchall()
        return [dict(row) for row in rows], total

    def update_metadata(
        self,
        qr_id: str,
        title: str,
        grade: str,
        subject: str,
        textbook_version: str | None,
        chapter: str | None,
        note: str | None,
    ) -> dict[str, Any]:
        binding = self._binding_row(qr_id)
        metadata = self._clean_metadata(
            title, grade, subject, textbook_version, chapter, note
        )
        with self.database.transaction() as connection:
            connection.execute(
                """
                UPDATE bindings SET title = ?, grade = ?, subject = ?,
                    textbook_version = ?, chapter = ?, note = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    metadata["title"], metadata["grade"], metadata["subject"],
                    metadata["textbook_version"], metadata["chapter"],
                    metadata["note"], utc_now_iso(), binding["id"],
                ),
            )
        return self.get_binding(qr_id)

    def set_active(self, qr_id: str, active: bool) -> dict[str, Any]:
        with self.database.read() as connection:
            row = connection.execute(
                "SELECT id FROM bindings WHERE qr_id = ?", (qr_id,)
            ).fetchone()
        if row is None:
            raise AppError(404, "BINDING_NOT_FOUND", "binding does not exist")
        with self.database.transaction() as connection:
            connection.execute(
                "UPDATE bindings SET is_active = ?, updated_at = ? WHERE id = ?",
                (1 if active else 0, utc_now_iso(), row["id"]),
            )
        return self.get_binding(qr_id) if active else {"qr_id": qr_id, "is_active": False}
