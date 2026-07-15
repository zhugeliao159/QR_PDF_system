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
from app.database import Database, new_public_key
from app.errors import AppError
from app.models import StoredObject, utc_now_iso
from app.services.decoupled import (
    AnswerResourceService,
    AnswerRevisionService,
    AssetService,
    QrResolverService,
    ResolvedAnswer,
)
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
    """Compatibility facade backed exclusively by the decoupled Stage 04A model."""

    def __init__(
        self,
        settings: Settings,
        database: Database,
        storage: StorageBackend,
        qr_service: QrService,
        resource_service: AnswerResourceService | None = None,
        revision_service: AnswerRevisionService | None = None,
        asset_service: AssetService | None = None,
        resolver_service: QrResolverService | None = None,
    ) -> None:
        self.settings = settings
        self.database = database
        self.storage = storage
        self.qr_service = qr_service
        self.asset_service = asset_service or AssetService(database, storage)
        self.resource_service = resource_service or AnswerResourceService(database)
        self.revision_service = revision_service or AnswerRevisionService(
            database, self.asset_service
        )
        self.resolver_service = resolver_service or QrResolverService(database)

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
    def _version_out(row: dict[str, Any], current_revision_id: int) -> dict[str, Any]:
        return {
            "version_id": row["id"],
            "version_number": row["revision_number"],
            "original_filename": row["original_filename"],
            "mime_type": row["mime_type"],
            "size_bytes": row["size_bytes"],
            "sha256": row["sha256"],
            "created_at": row["created_at"],
            "is_current": row["id"] == current_revision_id,
            "note": row["change_note"],
            "is_pinned": bool(row.get("is_pinned", False)),
            "revision_key": row["revision_key"],
            "status": row["status"],
            "published_at": row["published_at"],
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

    @staticmethod
    def _compatibility_row(resolved: ResolvedAnswer) -> dict[str, Any]:
        resource = resolved.resource
        revision = resolved.revision
        asset = resolved.asset
        return {
            "id": resource["id"],
            "qr_id": resolved.alias["public_token"],
            "current_version_id": resource["current_published_revision_id"],
            "version_id": revision["id"],
            "version_number": revision["revision_number"],
            "original_filename": asset["original_filename"],
            "mime_type": asset["mime_type"],
            "size_bytes": asset["size_bytes"],
            "sha256": asset["sha256"],
            "version_created_at": revision["created_at"],
            "version_note": revision["change_note"],
            "storage_path": asset["storage_key"],
            "title": resource["name"],
            "display_code": resource["display_code"],
            "grade": resource["grade"],
            "subject": resource["subject"],
            "textbook_version": resource["textbook_version"],
            "chapter": resource["chapter"],
            "note": resource["note"],
            "created_at": resource["created_at"],
            "updated_at": resource["updated_at"],
            "is_active": 1 if resource["status"] == "active" else 0,
            "resource_key": resource["resource_key"],
            "revision_key": revision["revision_key"],
            "row_version": resource["row_version"],
        }

    def _binding_row(self, qr_id: str, allow_inactive: bool = False) -> dict[str, Any]:
        resolved = self.resolver_service.resolve_latest(qr_id, allow_inactive)
        return self._compatibility_row(resolved)

    def get_binding(self, qr_id: str, allow_inactive: bool = False) -> dict[str, Any]:
        resolved = self.resolver_service.resolve_latest(qr_id, allow_inactive)
        row = self._compatibility_row(resolved)
        with self.database.read() as connection:
            version_count = int(
                connection.execute(
                    "SELECT COUNT(*) FROM answer_revisions WHERE resource_id = ?",
                    (row["id"],),
                ).fetchone()[0]
            )
            pinned = connection.execute(
                "SELECT 1 FROM revision_references WHERE revision_id = ? LIMIT 1",
                (row["version_id"],),
            ).fetchone() is not None
        version_row = {
            **resolved.revision,
            **resolved.asset,
            "id": resolved.revision["id"],
            "created_at": resolved.revision["created_at"],
            "is_pinned": pinned,
        }
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
            "row_version": row["row_version"],
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
        actor: str = "legacy-api",
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
                display_code = self.database._unique_display_code(
                    connection, "answer_resources"
                )
                resource_id = self.resource_service.create(
                    connection,
                    resource_key=new_public_key(),
                    name=str(metadata["title"]),
                    display_code=display_code,
                    grade=str(metadata["grade"]),
                    subject=str(metadata["subject"]),
                    textbook_version=metadata["textbook_version"],
                    chapter=metadata["chapter"],
                    note=metadata["note"],
                    created_at=now,
                )
                draft = self.revision_service.create_draft(
                    connection,
                    resource_id,
                    stored,
                    metadata["note"],
                    now,
                    actor,
                )
                alias_cursor = connection.execute(
                    """
                    INSERT INTO qr_aliases
                        (public_token, display_code, label, resource_id,
                         resolve_mode, pinned_revision_id, status,
                         created_at, updated_at)
                    VALUES (?, ?, ?, ?, 'latest', NULL, 'active', ?, ?)
                    """,
                    (qr_id, display_code, metadata["title"], resource_id, now, now),
                )
                connection.execute(
                    """
                    INSERT INTO audit_events
                        (event_type, resource_id, revision_id, qr_alias_id,
                         actor, summary, created_at)
                    VALUES ('create_resource', ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        resource_id, draft["id"], int(alias_cursor.lastrowid), actor,
                        "通过兼容流程创建资料并立即发布首个版本", now,
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO audit_events
                        (event_type, resource_id, revision_id, qr_alias_id,
                         actor, summary, created_at)
                    VALUES ('create_qr_alias', ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        resource_id,
                        draft["id"],
                        int(alias_cursor.lastrowid),
                        actor,
                        "创建动态二维码入口",
                        now,
                    ),
                )
                self.revision_service.publish_in_connection(
                    connection,
                    resource_id,
                    draft["id"],
                    1,
                    actor,
                    "legacy_immediate_publish",
                )
        except Exception:
            self.storage.delete(stored.relative_path)
            raise

        logger.info("answer resource created public_token=%s version=1", qr_id)
        return self.get_binding(qr_id)

    async def replace_file(
        self,
        qr_id: str,
        upload: UploadFile,
        note: str | None = None,
        actor: str = "legacy-api",
    ) -> dict[str, Any]:
        binding = self._binding_row(qr_id)
        stored = await self.storage.save_binding_upload(
            upload, qr_id, self.settings.max_upload_size_bytes
        )
        try:
            stored = self._validate_binding_file(stored)
            now = utc_now_iso()
            with self.database.transaction() as connection:
                draft = self.revision_service.create_draft(
                    connection, binding["id"], stored, note, now, actor
                )
                self.revision_service.publish_in_connection(
                    connection,
                    binding["id"],
                    draft["id"],
                    binding["row_version"],
                    actor,
                    "legacy_immediate_publish",
                )
                version_number = draft["revision_number"]
        except Exception:
            self.storage.delete(stored.relative_path)
            raise

        self._cleanup_old_versions(binding["id"])
        logger.info(
            "answer revision replaced public_token=%s version=%s", qr_id, version_number
        )
        return self.get_binding(qr_id)

    async def create_draft(
        self,
        qr_id: str,
        upload: UploadFile,
        note: str | None,
        actor: str,
    ) -> dict[str, Any]:
        binding = self._binding_row(qr_id)
        stored = await self.storage.save_binding_upload(
            upload, qr_id, self.settings.max_upload_size_bytes
        )
        try:
            stored = self._validate_binding_file(stored)
            now = utc_now_iso()
            with self.database.transaction() as connection:
                draft = self.revision_service.create_draft(
                    connection, binding["id"], stored, note, now, actor
                )
        except Exception:
            self.storage.delete(stored.relative_path)
            raise
        logger.info(
            "answer draft created public_token=%s revision_number=%s",
            qr_id,
            draft["revision_number"],
        )
        return self.draft_details(qr_id, draft["revision_key"])

    def draft_details(self, qr_id: str, revision_key: str) -> dict[str, Any]:
        binding = self._binding_row(qr_id, allow_inactive=True)
        revision = self.revision_service.get_by_key(binding["id"], revision_key)
        if revision["status"] != "draft":
            raise AppError(409, "VERSION_NOT_DRAFT", "version is not a draft")
        return {
            **self._version_out(revision, binding["version_id"]),
            "row_version": binding["row_version"],
            "qr_id": qr_id,
        }

    def draft_file(self, qr_id: str, revision_key: str) -> tuple[Path, str, str]:
        binding = self._binding_row(qr_id, allow_inactive=True)
        revision = self.revision_service.get_by_key(binding["id"], revision_key)
        if revision["status"] != "draft":
            raise AppError(409, "VERSION_NOT_DRAFT", "version is not a draft")
        return (
            self.storage.resolve(revision["storage_key"]),
            revision["original_filename"],
            revision["mime_type"],
        )

    def publish_draft(
        self,
        qr_id: str,
        revision_key: str,
        expected_row_version: int,
        actor: str,
    ) -> dict[str, Any]:
        binding = self._binding_row(qr_id, allow_inactive=True)
        revision = self.revision_service.get_by_key(binding["id"], revision_key)
        self.revision_service.publish(
            binding["id"], revision["id"], expected_row_version, actor
        )
        logger.info(
            "answer draft published public_token=%s revision_number=%s",
            qr_id,
            revision["revision_number"],
        )
        return self.get_binding(qr_id, allow_inactive=True)

    def republish_revision(
        self,
        qr_id: str,
        revision_key: str,
        expected_row_version: int,
        actor: str,
    ) -> dict[str, Any]:
        binding = self._binding_row(qr_id, allow_inactive=True)
        revision = self.revision_service.get_by_key(binding["id"], revision_key)
        self.revision_service.publish(
            binding["id"],
            revision["id"],
            expected_row_version,
            actor,
            republish=True,
        )
        logger.info(
            "answer revision republished public_token=%s revision_number=%s",
            qr_id,
            revision["revision_number"],
        )
        return self.get_binding(qr_id, allow_inactive=True)

    def discard_draft(self, qr_id: str, revision_key: str, actor: str) -> None:
        binding = self._binding_row(qr_id, allow_inactive=True)
        candidate = self.revision_service.get_by_key(binding["id"], revision_key)
        trash_path: str | None = None
        delete_asset = False
        try:
            with self.database.transaction() as connection:
                revision = connection.execute(
                    """
                    SELECT v.*, a.storage_key
                    FROM answer_revisions v
                    JOIN assets a ON a.id = v.asset_id
                    WHERE v.resource_id = ? AND v.revision_key = ?
                    """,
                    (binding["id"], revision_key),
                ).fetchone()
                if revision is None:
                    raise AppError(404, "VERSION_NOT_FOUND", "version does not exist")
                if revision["status"] != "draft":
                    raise AppError(409, "VERSION_NOT_DRAFT", "version is not a draft")
                resource = connection.execute(
                    "SELECT current_published_revision_id FROM answer_resources WHERE id = ?",
                    (binding["id"],),
                ).fetchone()
                if resource["current_published_revision_id"] == revision["id"]:
                    raise AppError(409, "CURRENT_VERSION_PROTECTED", "current version cannot be discarded")
                if connection.execute(
                    "SELECT 1 FROM revision_references WHERE revision_id = ? LIMIT 1",
                    (revision["id"],),
                ).fetchone():
                    raise AppError(409, "VERSION_REFERENCED", "referenced version cannot be discarded")
                reference_count = int(
                    connection.execute(
                        "SELECT COUNT(*) FROM answer_revisions WHERE asset_id = ?",
                        (revision["asset_id"],),
                    ).fetchone()[0]
                )
                delete_asset = reference_count == 1
                if delete_asset:
                    trash_path = self.storage.move_to_trash(revision["storage_key"])
                connection.execute(
                    """
                    INSERT INTO audit_events
                        (event_type, resource_id, revision_id, actor, summary, created_at)
                    VALUES ('discard_draft', ?, ?, ?, ?, ?)
                    """,
                    (
                        binding["id"],
                        revision["id"],
                        actor,
                        f"放弃第 {revision['revision_number']} 版答案草稿",
                        utc_now_iso(),
                    ),
                )
                connection.execute(
                    "DELETE FROM answer_revisions WHERE id = ?", (revision["id"],)
                )
                if delete_asset:
                    connection.execute(
                        "DELETE FROM assets WHERE id = ?", (revision["asset_id"],)
                    )
        except Exception:
            if trash_path is not None:
                self.storage.restore_from_trash(trash_path, candidate["storage_key"])
            raise
        if trash_path is not None:
            try:
                self.storage.delete(trash_path)
            except Exception:
                logger.exception(
                    "discarded draft left trash asset resource_id=%s revision_key=%s",
                    binding["id"],
                    revision_key,
                )

    def audit_events(self, qr_id: str, limit: int = 50) -> list[dict[str, Any]]:
        binding = self._binding_row(qr_id, allow_inactive=True)
        return self.revision_service.audit_events(binding["id"], limit)

    def _cleanup_old_versions(self, resource_id: int) -> None:
        while True:
            with self.database.read() as connection:
                resource = connection.execute(
                    "SELECT current_published_revision_id FROM answer_resources WHERE id = ?",
                    (resource_id,),
                ).fetchone()
                if resource is None:
                    return
                count = int(
                    connection.execute(
                        """
                        SELECT COUNT(*) FROM answer_revisions v
                        WHERE v.resource_id = ? AND v.status = 'published' AND NOT EXISTS (
                            SELECT 1 FROM revision_references r
                            WHERE r.revision_id = v.id
                        )
                        """,
                        (resource_id,),
                    ).fetchone()[0]
                )
                if count <= self.settings.max_binding_versions:
                    return
                candidate = connection.execute(
                    """
                    SELECT v.id, v.asset_id, a.storage_key
                    FROM answer_revisions v
                    JOIN assets a ON a.id = v.asset_id
                    WHERE v.resource_id = ? AND v.status = 'published' AND v.id != ? AND NOT EXISTS (
                        SELECT 1 FROM revision_references r
                        WHERE r.revision_id = v.id
                    )
                    ORDER BY v.revision_number ASC
                    LIMIT 1
                    """,
                    (resource_id, resource["current_published_revision_id"]),
                ).fetchone()
            if candidate is None:
                logger.error(
                    "revision cleanup found no removable revision resource_id=%s",
                    resource_id,
                )
                return

            try:
                trash_path = self.storage.move_to_trash(candidate["storage_key"])
            except Exception:
                logger.exception(
                    "revision cleanup could not move asset resource_id=%s revision_id=%s",
                    resource_id,
                    candidate["id"],
                )
                return

            delete_asset = False
            try:
                with self.database.transaction() as connection:
                    current = connection.execute(
                        "SELECT current_published_revision_id FROM answer_resources WHERE id = ?",
                        (resource_id,),
                    ).fetchone()
                    if current["current_published_revision_id"] == candidate["id"]:
                        raise RuntimeError("cleanup candidate became current")
                    if connection.execute(
                        "SELECT 1 FROM revision_references WHERE revision_id = ?",
                        (candidate["id"],),
                    ).fetchone():
                        raise RuntimeError("cleanup candidate became referenced")
                    connection.execute(
                        "DELETE FROM answer_revisions WHERE id = ? AND resource_id = ?",
                        (candidate["id"], resource_id),
                    )
                    delete_asset = not self.asset_service.is_referenced(
                        connection, candidate["asset_id"]
                    )
                    if delete_asset:
                        connection.execute(
                            "DELETE FROM assets WHERE id = ?", (candidate["asset_id"],)
                        )
            except Exception:
                self.storage.restore_from_trash(trash_path, candidate["storage_key"])
                logger.exception(
                    "revision cleanup database update failed resource_id=%s revision_id=%s",
                    resource_id,
                    candidate["id"],
                )
                return

            if delete_asset:
                try:
                    self.storage.delete(trash_path)
                except Exception:
                    logger.exception(
                        "revision cleanup left trash asset resource_id=%s revision_id=%s",
                        resource_id,
                        candidate["id"],
                    )
            else:
                self.storage.restore_from_trash(trash_path, candidate["storage_key"])

    def list_versions(
        self, qr_id: str, allow_inactive: bool = False
    ) -> list[dict[str, Any]]:
        binding = self._binding_row(qr_id, allow_inactive)
        rows = self.revision_service.list(binding["id"])
        return [self._version_out(row, binding["version_id"]) for row in rows]

    def rollback(self, qr_id: str, version_id: int) -> dict[str, Any]:
        binding = self._binding_row(qr_id)
        with self.database.read() as connection:
            revision = connection.execute(
                "SELECT revision_key FROM answer_revisions WHERE id = ? AND resource_id = ?",
                (version_id, binding["id"]),
            ).fetchone()
        if revision is None:
            raise AppError(404, "VERSION_NOT_FOUND", "version does not exist")
        self.republish_revision(
            qr_id,
            revision["revision_key"],
            binding["row_version"],
            "legacy-api",
        )
        with self.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO audit_events
                    (event_type, resource_id, revision_id, actor, summary, created_at)
                VALUES ('legacy_republish', ?, ?, 'legacy-api', ?, ?)
                """,
                (binding["id"], version_id, "兼容回滚流程重新发布历史版本", utc_now_iso()),
            )
        logger.info("answer revision republished public_token=%s revision_id=%s", qr_id, version_id)
        return self.get_binding(qr_id)

    def current_file(self, qr_id: str) -> tuple[Path, str, str]:
        resolved = self.resolver_service.resolve_latest(qr_id)
        return (
            self.asset_service.path(resolved.asset),
            resolved.asset["original_filename"],
            resolved.asset["mime_type"],
        )

    def version_file(self, qr_id: str, version_id: int) -> tuple[Path, str, str]:
        resolved = self.resolver_service.resolve_revision(qr_id, version_id)
        return (
            self.asset_service.path(resolved.asset),
            resolved.asset["original_filename"],
            resolved.asset["mime_type"],
        )

    def pin_version(
        self,
        qr_id: str,
        version_id: int,
        reference_type: str,
        source_job_id: str = "",
    ) -> None:
        binding = self._binding_row(qr_id)
        mapped = {
            "fixed_qr": "manual_pin",
            "qr_download": "manual_pin",
            "pdf_job": "pdf_job_fixed",
            "pdf_job_fixed": "pdf_job_fixed",
            "manual_pin": "manual_pin",
            "legacy_fixed_link": "legacy_fixed_link",
        }.get(reference_type)
        if mapped is None:
            raise ValueError("unsupported revision reference type")
        self.revision_service.pin(
            binding["id"], version_id, mapped, source_job_id
        )

    def fixed_alias_token(
        self, qr_id: str, version_id: int, source_job_id: str = ""
    ) -> str:
        resolved = self.resolver_service.resolve_revision(qr_id, version_id)
        alias = self.resolver_service.get_or_create_pinned_alias(
            resolved.resource["id"],
            resolved.revision["id"],
            f"{resolved.resource['name']} 第 {resolved.revision['revision_number']} 版",
            source_job_id,
        )
        return str(alias["public_token"])

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
        return self.resource_service.list_materials(
            search, grade, subject, status, page, page_size
        )

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
        self.resource_service.update_metadata(binding["id"], metadata)
        return self.get_binding(qr_id)

    def set_active(
        self, qr_id: str, active: bool, actor: str = "legacy-api"
    ) -> dict[str, Any]:
        resolved = self.resolver_service.resolve_latest(qr_id, allow_inactive=True)
        self.resource_service.set_active(resolved.resource["id"], active, actor)
        return self.get_binding(qr_id) if active else {"qr_id": qr_id, "is_active": False}
