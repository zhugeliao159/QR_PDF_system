from __future__ import annotations

import logging
import unicodedata
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import UploadFile

from app.config import Settings
from app.database import Database, new_public_key
from app.errors import AppError
from app.models import StoredObject, utc_now_iso
from app.services.binding_service import BindingService, GRADES, SUBJECTS
from app.services.preview_service import PreviewService
from app.storage.base import StorageBackend
from app.storage.local import safe_display_filename


logger = logging.getLogger(__name__)


class BatchImportService:
    def __init__(
        self,
        settings: Settings,
        database: Database,
        storage: StorageBackend,
        binding_service: BindingService,
        preview_service: PreviewService,
    ) -> None:
        self.settings = settings
        self.database = database
        self.storage = storage
        self.binding_service = binding_service
        self.preview_service = preview_service

    @staticmethod
    def _requested_title(filename: str) -> str:
        value = unicodedata.normalize("NFC", Path(filename).stem)
        value = " ".join(value.split()).strip()
        return (value or "未命名解析资料")[:100]

    async def create_batch(
        self,
        uploads: list[UploadFile],
        grade: str,
        subject: str,
        actor: str,
    ) -> dict[str, Any]:
        if not uploads:
            raise AppError(422, "BATCH_FILES_REQUIRED", "请至少选择一份 PDF。")
        if len(uploads) > self.settings.batch_upload_max_files:
            for upload in uploads:
                await upload.close()
            raise AppError(
                422,
                "BATCH_FILE_COUNT_EXCEEDED",
                f"单次最多上传 {self.settings.batch_upload_max_files} 份 PDF。",
            )
        if grade not in GRADES or subject not in SUBJECTS:
            raise AppError(422, "BATCH_METADATA_INVALID", "年级或学科不在允许范围内。")

        filenames = [safe_display_filename(upload.filename) for upload in uploads]
        if any(Path(filename).suffix.lower() != ".pdf" for filename in filenames):
            for upload in uploads:
                await upload.close()
            raise AppError(415, "BATCH_PDF_ONLY", "批量上传只接受 PDF 文件。")

        batch_key = new_public_key()
        staged: list[StoredObject] = []
        total_size = 0
        try:
            for upload in uploads:
                stored = await self.storage.save_batch_upload(
                    upload,
                    batch_key,
                    uuid.uuid4().hex,
                    self.settings.max_upload_size_bytes,
                )
                staged.append(stored)
                total_size += stored.size_bytes
                if total_size > self.settings.batch_upload_max_total_bytes:
                    raise AppError(
                        413,
                        "BATCH_TOTAL_SIZE_EXCEEDED",
                        f"单次批量上传总大小不能超过 {self.settings.batch_upload_max_total_mb} MiB。",
                    )

            now = utc_now_iso()
            with self.database.transaction() as connection:
                batch_id = int(
                    connection.execute(
                        """
                        INSERT INTO batch_imports
                            (batch_key, actor, grade, subject, status, total_items,
                             total_size_bytes, created_at)
                        VALUES (?, ?, ?, ?, 'pending', ?, ?, ?)
                        """,
                        (
                            batch_key,
                            actor,
                            grade,
                            subject,
                            len(staged),
                            total_size,
                            now,
                        ),
                    ).lastrowid
                )
                for number, stored in enumerate(staged, 1):
                    connection.execute(
                        """
                        INSERT INTO batch_import_items
                            (batch_import_id, item_number, original_filename,
                             staging_storage_key, size_bytes, sha256,
                             requested_title, status, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?)
                        """,
                        (
                            batch_id,
                            number,
                            stored.original_filename,
                            stored.relative_path,
                            stored.size_bytes,
                            stored.sha256,
                            self._requested_title(stored.original_filename),
                            now,
                        ),
                    )
        except Exception:
            for stored in staged:
                try:
                    self.storage.delete(stored.relative_path)
                except Exception:
                    logger.exception("could not remove rejected batch upload")
            for upload in uploads[len(staged):]:
                await upload.close()
            raise
        return self.get_batch(batch_key)

    def get_batch(self, batch_key: str) -> dict[str, Any]:
        with self.database.read() as connection:
            batch = connection.execute(
                "SELECT * FROM batch_imports WHERE batch_key = ?", (batch_key,)
            ).fetchone()
            if batch is None:
                raise AppError(404, "BATCH_NOT_FOUND", "批量上传任务不存在。")
            items = connection.execute(
                """
                SELECT i.*, q.public_token AS qr_id, r.display_code
                FROM batch_import_items i
                LEFT JOIN answer_resources r ON r.id = i.resource_id
                LEFT JOIN qr_aliases q
                  ON q.resource_id = r.id AND q.resolve_mode = 'latest'
                WHERE i.batch_import_id = ?
                ORDER BY i.item_number
                """,
                (batch["id"],),
            ).fetchall()
        item_rows = [dict(item) for item in items]
        counts = {
            status: sum(1 for item in item_rows if item["status"] == status)
            for status in ("pending", "processing", "waiting_preview", "completed", "failed")
        }
        return {**dict(batch), "items": item_rows, "counts": counts}

    def _refresh_batch(self, batch_id: int, connection=None) -> None:
        if connection is None:
            with self.database.transaction() as owned:
                self._refresh_batch(batch_id, owned)
            return
        counts = connection.execute(
                """
                SELECT COUNT(*) AS total,
                       SUM(CASE WHEN status IN ('completed', 'failed') THEN 1 ELSE 0 END) AS done,
                       SUM(CASE WHEN status != 'pending' THEN 1 ELSE 0 END) AS started
                FROM batch_import_items WHERE batch_import_id = ?
                """,
                (batch_id,),
        ).fetchone()
        now = utc_now_iso()
        completed = int(counts["done"] or 0) == int(counts["total"] or 0)
        status = "completed" if completed else (
            "processing" if int(counts["started"] or 0) else "pending"
        )
        connection.execute(
                """
                UPDATE batch_imports
                SET status = ?,
                    started_at = CASE WHEN ? = 'processing' THEN COALESCE(started_at, ?) ELSE started_at END,
                    completed_at = CASE WHEN ? = 'completed' THEN ? ELSE NULL END
                WHERE id = ?
                """,
            (status, status, now, status, now, batch_id),
        )

    def recover_stale_items(self) -> int:
        cutoff = (
            datetime.now(timezone.utc)
            - timedelta(seconds=self.settings.batch_import_stale_seconds)
        ).isoformat().replace("+00:00", "Z")
        with self.database.transaction() as connection:
            result = connection.execute(
                """
                UPDATE batch_import_items
                SET status = 'pending', worker_id = NULL, claimed_at = NULL,
                    error_code = 'BATCH_ITEM_STALE',
                    error_message = 'batch worker claim expired'
                WHERE status = 'processing' AND resource_id IS NULL
                  AND claimed_at IS NOT NULL AND claimed_at < ?
                """,
                (cutoff,),
            )
            return result.rowcount

    def _claim_next(self, worker_id: str) -> dict[str, Any] | None:
        self.recover_stale_items()
        now = utc_now_iso()
        with self.database.transaction() as connection:
            row = connection.execute(
                """
                SELECT i.*, b.grade, b.subject, b.actor, b.id AS batch_id
                FROM batch_import_items i
                JOIN batch_imports b ON b.id = i.batch_import_id
                WHERE i.status = 'pending'
                ORDER BY i.id LIMIT 1
                """
            ).fetchone()
            if row is None:
                return None
            result = connection.execute(
                """
                UPDATE batch_import_items
                SET status = 'processing', worker_id = ?, claimed_at = ?,
                    error_code = NULL, error_message = NULL
                WHERE id = ? AND status = 'pending'
                """,
                (worker_id, now, row["id"]),
            )
            if result.rowcount != 1:
                return None
            self._refresh_batch(row["batch_id"], connection)
        return dict(row)

    @staticmethod
    def _clean_error(error: Exception) -> tuple[str, str]:
        code = error.code if isinstance(error, AppError) else "BATCH_IMPORT_FAILED"
        message = str(error).replace("\r", " ").replace("\n", " ").strip()
        return code, (message or "PDF 处理失败")[:300]

    def _delete_failed_resource(self, resource_id: int) -> None:
        moved: list[tuple[str, str]] = []
        preview_dirs: set[Path] = set()
        with self.database.read() as connection:
            asset_ids = [
                int(row["asset_id"])
                for row in connection.execute(
                    "SELECT asset_id FROM answer_revisions WHERE resource_id = ? AND asset_id IS NOT NULL",
                    (resource_id,),
                ).fetchall()
            ]
            file_rows = connection.execute(
                """
                SELECT a.storage_key FROM assets a
                JOIN answer_revisions v ON v.asset_id = a.id
                WHERE v.resource_id = ?
                UNION ALL
                SELECT p.storage_key FROM preview_pages p
                JOIN preview_sets s ON s.id = p.preview_set_id
                JOIN answer_revisions v ON v.id = s.revision_id
                WHERE v.resource_id = ?
                """,
                (resource_id, resource_id),
            ).fetchall()
            preview_keys = connection.execute(
                """
                SELECT s.preview_key FROM preview_sets s
                JOIN answer_revisions v ON v.id = s.revision_id
                WHERE v.resource_id = ?
                """,
                (resource_id,),
            ).fetchall()
        paths = [row["storage_key"] for row in file_rows]
        paths.extend(f"previews/{row['preview_key']}/manifest.json" for row in preview_keys)
        try:
            for path in dict.fromkeys(paths):
                candidate = self.storage.resolve(path, must_exist=False)
                if candidate.is_file():
                    moved.append((self.storage.move_to_trash(path), path))
                    if path.startswith("previews/"):
                        preview_dirs.add(candidate.parent)
            with self.database.transaction() as connection:
                connection.execute(
                    "UPDATE answer_resources SET current_published_revision_id = NULL WHERE id = ?",
                    (resource_id,),
                )
                connection.execute(
                    "DELETE FROM preview_jobs WHERE revision_id IN (SELECT id FROM answer_revisions WHERE resource_id = ?)",
                    (resource_id,),
                )
                connection.execute(
                    "DELETE FROM preview_pages WHERE preview_set_id IN (SELECT s.id FROM preview_sets s JOIN answer_revisions v ON v.id = s.revision_id WHERE v.resource_id = ?)",
                    (resource_id,),
                )
                connection.execute(
                    "DELETE FROM preview_sets WHERE revision_id IN (SELECT id FROM answer_revisions WHERE resource_id = ?)",
                    (resource_id,),
                )
                connection.execute("DELETE FROM audit_events WHERE resource_id = ?", (resource_id,))
                connection.execute("DELETE FROM qr_aliases WHERE resource_id = ?", (resource_id,))
                connection.execute("DELETE FROM answer_revisions WHERE resource_id = ?", (resource_id,))
                for asset_id in asset_ids:
                    connection.execute("DELETE FROM assets WHERE id = ?", (asset_id,))
                connection.execute("DELETE FROM answer_resources WHERE id = ?", (resource_id,))
        except Exception:
            for trash_path, original_path in reversed(moved):
                self.storage.restore_from_trash(trash_path, original_path)
            raise
        for trash_path, _ in moved:
            self.storage.delete(trash_path)
        for directory in preview_dirs:
            try:
                directory.rmdir()
            except OSError:
                pass

    def _mark_failed(self, item: dict[str, Any], error: Exception) -> None:
        code, message = self._clean_error(error)
        if item.get("resource_id"):
            try:
                self._delete_failed_resource(int(item["resource_id"]))
            except Exception:
                logger.exception("could not clean failed batch resource")
                code, message = "BATCH_CLEANUP_REQUIRED", "失败资料清理未完成，请联系管理员。"
        elif item.get("staging_storage_key"):
            try:
                self.storage.delete(item["staging_storage_key"])
            except Exception:
                logger.exception("could not clean failed staged upload")
        now = utc_now_iso()
        with self.database.transaction() as connection:
            current = connection.execute(
                "SELECT batch_import_id FROM batch_import_items WHERE id = ?", (item["id"],)
            ).fetchone()
            connection.execute(
                """
                UPDATE batch_import_items
                SET status = 'failed', resource_id = NULL, revision_id = NULL,
                    worker_id = NULL, claimed_at = NULL, staging_storage_key = NULL,
                    error_code = ?, error_message = ?, completed_at = ?
                WHERE id = ?
                """,
                (code, message, now, item["id"]),
            )
            self._refresh_batch(current["batch_import_id"], connection)

    def process_next(self, worker_id: str) -> bool:
        item = self._claim_next(worker_id)
        if item is None:
            return False
        try:
            stored = StoredObject(
                relative_path=item["staging_storage_key"],
                stored_filename=Path(item["staging_storage_key"]).name,
                original_filename=item["original_filename"],
                mime_type="application/pdf",
                size_bytes=item["size_bytes"],
                sha256=item["sha256"],
            )
            created = self.binding_service.create_staged_batch_binding(
                stored,
                item["requested_title"],
                item["grade"],
                item["subject"],
                item["actor"],
                item["id"],
            )
            self.preview_service.request_preview(created["revision_id"])
        except Exception as error:
            refreshed = {**item}
            with self.database.read() as connection:
                row = connection.execute(
                    "SELECT * FROM batch_import_items WHERE id = ?", (item["id"],)
                ).fetchone()
                if row is not None:
                    refreshed.update(dict(row))
            self._mark_failed(refreshed, error)
        return True

    def finalize_next(self) -> bool:
        with self.database.read() as connection:
            row = connection.execute(
                """
                SELECT i.*, b.actor, b.id AS batch_id
                FROM batch_import_items i
                JOIN batch_imports b ON b.id = i.batch_import_id
                WHERE i.status = 'waiting_preview'
                ORDER BY i.id LIMIT 1
                """
            ).fetchone()
        if row is None:
            return False
        item = dict(row)
        status = self.preview_service.status_for_revision(item["revision_id"])
        if status is None:
            self.preview_service.request_preview(item["revision_id"])
            return True
        if status["status"] == "failed":
            self._mark_failed(
                item,
                AppError(422, status.get("error_code") or "PREVIEW_FAILED", "PDF 预览生成失败。"),
            )
            return True
        if status["status"] != "completed":
            return False
        now = utc_now_iso()
        try:
            with self.database.transaction() as connection:
                resource = connection.execute(
                    "SELECT row_version FROM answer_resources WHERE id = ?",
                    (item["resource_id"],),
                ).fetchone()
                if resource is None:
                    raise AppError(404, "RESOURCE_NOT_FOUND", "批量资料不存在。")
                self.binding_service.revision_service.publish_in_connection(
                    connection,
                    item["resource_id"],
                    item["revision_id"],
                    resource["row_version"],
                    item["actor"],
                    "publish_revision",
                )
                connection.execute(
                    """
                    UPDATE batch_import_items
                    SET status = 'completed', worker_id = NULL, claimed_at = NULL,
                        staging_storage_key = NULL, completed_at = ?
                    WHERE id = ? AND status = 'waiting_preview'
                    """,
                    (now, item["id"]),
                )
                self._refresh_batch(item["batch_id"], connection)
        except Exception as error:
            self._mark_failed(item, error)
        return True
