from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import UploadFile

from app.config import Settings
from app.database import Database, new_public_key
from app.errors import AppError
from app.models import StoredObject, utc_now_iso
from app.services.binding_service import BindingService
from app.services.pdf_identity import pdf_identity
from app.services.preview_service import PreviewService
from app.storage.base import StorageBackend


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

    def reserve_batch(
        self, files: list[dict[str, Any]], actor: str
    ) -> dict[str, Any]:
        if not files:
            raise AppError(422, "BATCH_FILES_REQUIRED", "请至少选择一份 PDF。")
        if len(files) > self.settings.batch_upload_max_files:
            raise AppError(
                422,
                "BATCH_FILE_COUNT_EXCEEDED",
                f"单次最多上传 {self.settings.batch_upload_max_files} 份 PDF。",
            )

        manifest: list[dict[str, Any]] = []
        seen: set[str] = set()
        total_size = 0
        for raw in files:
            safe_name, visible_name, name_key = pdf_identity(
                str(raw.get("filename") or "")
            )
            size = int(raw.get("size") or 0)
            if size <= 0:
                raise AppError(422, "EMPTY_FILE", f"{safe_name} 是空文件。")
            if size > self.settings.max_upload_size_bytes:
                raise AppError(
                    413, "UPLOAD_TOO_LARGE", f"{safe_name} 超过单文件大小限制。"
                )
            if name_key in seen:
                raise AppError(
                    422,
                    "DUPLICATE_BATCH_NAME",
                    f"本批次中出现重复文件名：{visible_name}",
                )
            seen.add(name_key)
            total_size += size
            manifest.append(
                {
                    "filename": safe_name,
                    "name": visible_name,
                    "name_key": name_key,
                    "size": size,
                }
            )
        if total_size > self.settings.batch_upload_max_total_bytes:
            raise AppError(
                413,
                "BATCH_TOTAL_SIZE_EXCEEDED",
                f"单次批量上传总大小不能超过 {self.settings.batch_upload_max_total_mb} MiB。",
            )

        batch_key = new_public_key()
        identities: list[dict[str, Any]] = []
        now = utc_now_iso()
        with self.database.transaction() as connection:
            batch_id = int(
                connection.execute(
                    """
                    INSERT INTO batch_imports
                        (batch_key, actor, grade, subject, status, total_items,
                         total_size_bytes, created_at)
                    VALUES (?, ?, '未分类', '未分类', 'pending', ?, ?, ?)
                    """,
                    (batch_key, actor, len(manifest), total_size, now),
                ).lastrowid
            )
            for number, item in enumerate(manifest, 1):
                identity = self.binding_service.reserve_pdf_in_connection(
                    connection, item["filename"], actor
                )
                identities.append(identity)
                connection.execute(
                    """
                    INSERT INTO batch_import_items
                        (batch_import_id, item_number, original_filename,
                         staging_storage_key, size_bytes, sha256,
                         requested_title, resolved_title, status,
                         resource_id, created_at)
                    VALUES (?, ?, ?, NULL, ?, '', ?, ?, 'pending', ?, ?)
                    """,
                    (
                        batch_id,
                        number,
                        item["filename"],
                        item["size"],
                        item["name"],
                        identity["name"],
                        identity["resource_id"],
                        now,
                    ),
                )
        for identity in identities:
            self.binding_service.qr_service.png(identity["qr_id"])
        return self.get_batch(batch_key)

    async def store_item_upload(
        self, batch_key: str, item_number: int, upload: UploadFile
    ) -> dict[str, Any]:
        with self.database.read() as connection:
            row = connection.execute(
                """
                SELECT i.*, b.id AS batch_id
                FROM batch_import_items i
                JOIN batch_imports b ON b.id = i.batch_import_id
                WHERE b.batch_key = ? AND i.item_number = ?
                """,
                (batch_key, item_number),
            ).fetchone()
        if row is None:
            await upload.close()
            raise AppError(404, "BATCH_ITEM_NOT_FOUND", "上传项目不存在。")
        item = dict(row)
        if item["status"] != "pending" or item["staging_storage_key"] is not None:
            await upload.close()
            raise AppError(
                409, "BATCH_ITEM_ALREADY_UPLOADED", "该文件已经上传或正在处理。"
            )
        safe_name, _, name_key = pdf_identity(upload.filename)
        _, _, expected_key = pdf_identity(item["original_filename"])
        if name_key != expected_key:
            await upload.close()
            raise AppError(
                409, "BATCH_FILENAME_MISMATCH", "上传文件名与预留名称不一致。"
            )

        stored = await self.storage.save_batch_upload(
            upload,
            batch_key,
            uuid.uuid4().hex,
            self.settings.max_upload_size_bytes,
        )
        try:
            with self.database.transaction() as connection:
                current = connection.execute(
                    "SELECT status, staging_storage_key FROM batch_import_items WHERE id = ?",
                    (item["id"],),
                ).fetchone()
                if (
                    current is None
                    or current["status"] != "pending"
                    or current["staging_storage_key"] is not None
                ):
                    raise AppError(
                        409,
                        "BATCH_ITEM_ALREADY_UPLOADED",
                        "该文件已经上传或正在处理。",
                    )
                actual_total = int(
                    connection.execute(
                        """
                        SELECT COALESCE(SUM(
                            CASE WHEN id = ? THEN ? ELSE size_bytes END
                        ), 0)
                        FROM batch_import_items WHERE batch_import_id = ?
                        """,
                        (item["id"], stored.size_bytes, item["batch_id"]),
                    ).fetchone()[0]
                )
                if actual_total > self.settings.batch_upload_max_total_bytes:
                    raise AppError(
                        413,
                        "BATCH_TOTAL_SIZE_EXCEEDED",
                        "批量文件总大小超过限制。",
                    )
                connection.execute(
                    """
                    UPDATE batch_import_items
                    SET original_filename = ?, staging_storage_key = ?,
                        size_bytes = ?, sha256 = ?
                    WHERE id = ?
                    """,
                    (
                        safe_name,
                        stored.relative_path,
                        stored.size_bytes,
                        stored.sha256,
                        item["id"],
                    ),
                )
                connection.execute(
                    "UPDATE batch_imports SET total_size_bytes = ? WHERE id = ?",
                    (actual_total, item["batch_id"]),
                )
        except Exception:
            self.storage.delete(stored.relative_path)
            raise
        return self.get_batch(batch_key)

    async def create_batch(
        self,
        uploads: list[UploadFile],
        grade: str,
        subject: str,
        actor: str,
    ) -> dict[str, Any]:
        del grade, subject
        batch = self.reserve_batch(
            [
                {
                    "filename": upload.filename,
                    "size": getattr(upload, "size", 0) or 1,
                }
                for upload in uploads
            ],
            actor,
        )
        for number, upload in enumerate(uploads, 1):
            await self.store_item_upload(batch["batch_key"], number, upload)
        return self.get_batch(batch["batch_key"])

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
        item_rows: list[dict[str, Any]] = []
        for raw in items:
            item = dict(raw)
            if item["status"] == "pending" and item["staging_storage_key"] is None:
                item["status"] = "waiting_upload"
            item_rows.append(item)
        statuses = (
            "waiting_upload",
            "pending",
            "processing",
            "waiting_preview",
            "completed",
            "failed",
        )
        counts = {
            status: sum(1 for item in item_rows if item["status"] == status)
            for status in statuses
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
                WHERE status = 'processing'
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
                SELECT i.*, b.actor, b.id AS batch_id
                FROM batch_import_items i
                JOIN batch_imports b ON b.id = i.batch_import_id
                WHERE i.status = 'pending' AND i.staging_storage_key IS NOT NULL
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
                  AND staging_storage_key IS NOT NULL
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

    def _cleanup_failed_draft(self, item: dict[str, Any]) -> None:
        revision_id = item.get("revision_id")
        if revision_id is None:
            return
        with self.database.transaction() as connection:
            connection.execute(
                "DELETE FROM preview_jobs WHERE revision_id = ?", (revision_id,)
            )
            connection.execute(
                "DELETE FROM preview_pages WHERE preview_set_id IN "
                "(SELECT id FROM preview_sets WHERE revision_id = ?)",
                (revision_id,),
            )
            connection.execute(
                "DELETE FROM preview_sets WHERE revision_id = ?", (revision_id,)
            )
            row = connection.execute(
                """
                SELECT v.revision_key, v.status, q.public_token AS qr_id
                FROM answer_revisions v
                JOIN qr_aliases q
                  ON q.resource_id = v.resource_id AND q.resolve_mode = 'latest'
                WHERE v.id = ?
                """,
                (revision_id,),
            ).fetchone()
        if row is not None and row["status"] == "draft":
            self.binding_service.discard_draft(
                row["qr_id"], row["revision_key"], "batch-worker"
            )

    def _mark_failed(self, item: dict[str, Any], error: Exception) -> None:
        code, message = self._clean_error(error)
        try:
            self._cleanup_failed_draft(item)
        except Exception:
            logger.exception("could not clean failed batch draft")
            code, message = "BATCH_CLEANUP_REQUIRED", "失败草稿清理未完成，请联系管理员。"
        if item.get("staging_storage_key"):
            try:
                self.storage.delete(item["staging_storage_key"])
            except Exception:
                logger.exception("could not clean failed staged upload")
        now = utc_now_iso()
        with self.database.transaction() as connection:
            current = connection.execute(
                "SELECT batch_import_id FROM batch_import_items WHERE id = ?",
                (item["id"],),
            ).fetchone()
            if current is None:
                return
            connection.execute(
                """
                UPDATE batch_import_items
                SET status = 'failed', revision_id = NULL,
                    worker_id = NULL, claimed_at = NULL,
                    staging_storage_key = NULL,
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
            created = self.binding_service.create_staged_batch_revision(
                stored,
                int(item["resource_id"]),
                item["actor"],
                int(item["id"]),
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
                AppError(
                    422,
                    status.get("error_code") or "PREVIEW_FAILED",
                    "PDF 预览生成失败。",
                ),
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
                    raise AppError(404, "RESOURCE_NOT_FOUND", "二维码资料不存在。")
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
            self.binding_service._cleanup_old_versions(int(item["resource_id"]))
        except Exception as error:
            self._mark_failed(item, error)
        return True
