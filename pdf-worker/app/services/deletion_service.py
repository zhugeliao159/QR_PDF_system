from __future__ import annotations

import logging
import os
import shutil
import uuid
from pathlib import Path
from typing import Any

from app.config import Settings
from app.database import Database
from app.errors import AppError
from app.models import utc_now_iso
from app.storage.base import StorageBackend


logger = logging.getLogger(__name__)


class PermanentDeletionService:
    def __init__(
        self,
        settings: Settings,
        database: Database,
        storage: StorageBackend,
    ) -> None:
        self.settings = settings
        self.database = database
        self.storage = storage

    @staticmethod
    def _blockers(connection, resource_id: int, legacy_binding_id: int | None) -> list[str]:
        reasons: list[str] = []
        revision_ids = "SELECT id FROM answer_revisions WHERE resource_id = ?"
        if connection.execute(
            f"SELECT 1 FROM revision_references WHERE revision_id IN ({revision_ids}) LIMIT 1",
            (resource_id,),
        ).fetchone():
            reasons.append("存在固定二维码或版本引用")
        if connection.execute(
            "SELECT 1 FROM qr_aliases WHERE resource_id = ? AND resolve_mode = 'pinned' LIMIT 1",
            (resource_id,),
        ).fetchone():
            reasons.append("存在固定二维码")
        if connection.execute(
            "SELECT 1 FROM pdf_jobs_v2 WHERE resource_id = ? LIMIT 1", (resource_id,)
        ).fetchone():
            reasons.append("已关联练习册 PDF 任务")
        if connection.execute(
            f"SELECT 1 FROM preview_jobs WHERE revision_id IN ({revision_ids}) AND status IN ('pending', 'processing') LIMIT 1",
            (resource_id,),
        ).fetchone():
            reasons.append("预览正在处理")
        if connection.execute(
            """
            SELECT 1 FROM batch_import_items
            WHERE resource_id = ? AND status IN ('pending', 'processing', 'waiting_preview')
            LIMIT 1
            """,
            (resource_id,),
        ).fetchone():
            reasons.append("批量导入正在处理")
        if legacy_binding_id is not None:
            if connection.execute(
                "SELECT 1 FROM pdf_jobs WHERE binding_id = ? LIMIT 1",
                (legacy_binding_id,),
            ).fetchone():
                reasons.append("旧版数据已关联练习册 PDF 任务")
            if connection.execute(
                """
                SELECT 1 FROM version_references vr
                JOIN file_versions v ON v.id = vr.version_id
                WHERE v.binding_id = ? LIMIT 1
                """,
                (legacy_binding_id,),
            ).fetchone():
                reasons.append("旧版数据存在固定引用")
        return list(dict.fromkeys(reasons))

    def preflight(self, qr_ids: list[str]) -> list[dict[str, Any]]:
        unique_ids = list(dict.fromkeys(value.strip() for value in qr_ids if value.strip()))
        results: list[dict[str, Any]] = []
        with self.database.read() as connection:
            for qr_id in unique_ids:
                row = connection.execute(
                    """
                    SELECT r.id AS resource_id, r.name AS title, r.display_code,
                           r.legacy_binding_id, q.public_token AS qr_id
                    FROM qr_aliases q
                    JOIN answer_resources r ON r.id = q.resource_id
                    WHERE q.public_token = ? AND q.resolve_mode = 'latest'
                    """,
                    (qr_id,),
                ).fetchone()
                if row is None:
                    results.append(
                        {
                            "qr_id": qr_id,
                            "title": "未知资料",
                            "display_code": "—",
                            "eligible": False,
                            "reasons": ["资料不存在或已经删除"],
                        }
                    )
                    continue
                item = dict(row)
                reasons = self._blockers(
                    connection, item["resource_id"], item["legacy_binding_id"]
                )
                results.append({**item, "eligible": not reasons, "reasons": reasons})
        return results

    def _move_preview_directories(self, preview_keys: list[str]) -> list[tuple[Path, Path]]:
        moved: list[tuple[Path, Path]] = []
        preview_root = self.settings.previews_dir.resolve()
        trash_root = self.settings.trash_dir.resolve()
        for key in preview_keys:
            source = (preview_root / key).resolve(strict=False)
            if source.parent != preview_root or not source.is_dir():
                continue
            target = trash_root / f"{uuid.uuid4().hex}.preview-trash"
            os.replace(source, target)
            moved.append((target, source))
        return moved

    def delete_one(self, qr_id: str, actor: str) -> dict[str, Any]:
        with self.database.read() as connection:
            resource = connection.execute(
                """
                SELECT r.*, q.public_token AS qr_id
                FROM qr_aliases q
                JOIN answer_resources r ON r.id = q.resource_id
                WHERE q.public_token = ? AND q.resolve_mode = 'latest'
                """,
                (qr_id,),
            ).fetchone()
            if resource is None:
                return {"qr_id": qr_id, "deleted": False, "reason": "资料不存在或已经删除"}
            resource = dict(resource)
            reasons = self._blockers(
                connection, resource["id"], resource["legacy_binding_id"]
            )
            if reasons:
                return {
                    "qr_id": qr_id,
                    "title": resource["name"],
                    "display_code": resource["display_code"],
                    "deleted": False,
                    "reason": "；".join(reasons),
                }
            revisions = connection.execute(
                "SELECT id, asset_id FROM answer_revisions WHERE resource_id = ?",
                (resource["id"],),
            ).fetchall()
            revision_ids = [int(row["id"]) for row in revisions]
            asset_ids = list(dict.fromkeys(int(row["asset_id"]) for row in revisions if row["asset_id"] is not None))
            asset_rows = []
            if asset_ids:
                placeholders = ",".join("?" for _ in asset_ids)
                asset_rows = connection.execute(
                    f"""
                    SELECT a.id, a.storage_key FROM assets a
                    WHERE a.id IN ({placeholders}) AND NOT EXISTS (
                        SELECT 1 FROM answer_revisions other
                        WHERE other.asset_id = a.id AND other.resource_id != ?
                    )
                    """,
                    [*asset_ids, resource["id"]],
                ).fetchall()
            preview_keys = [
                str(row["preview_key"])
                for row in connection.execute(
                    """
                    SELECT s.preview_key FROM preview_sets s
                    JOIN answer_revisions v ON v.id = s.revision_id
                    WHERE v.resource_id = ?
                    """,
                    (resource["id"],),
                ).fetchall()
            ]

        moved_files: list[tuple[str, str]] = []
        moved_dirs: list[tuple[Path, Path]] = []
        try:
            for row in asset_rows:
                path = self.storage.resolve(row["storage_key"], must_exist=False)
                if path.is_file():
                    moved_files.append(
                        (self.storage.move_to_trash(row["storage_key"]), row["storage_key"])
                    )
            moved_dirs = self._move_preview_directories(preview_keys)
            with self.database.transaction() as connection:
                current = connection.execute(
                    "SELECT id, legacy_binding_id FROM answer_resources WHERE id = ?",
                    (resource["id"],),
                ).fetchone()
                if current is None:
                    raise AppError(404, "RESOURCE_NOT_FOUND", "资料已经删除。")
                reasons = self._blockers(
                    connection, resource["id"], current["legacy_binding_id"]
                )
                if reasons:
                    raise AppError(409, "RESOURCE_DELETE_BLOCKED", "；".join(reasons))

                session_ids = [
                    int(row["id"])
                    for row in connection.execute(
                        """
                        SELECT vs.id FROM viewer_sessions vs
                        JOIN qr_aliases q ON q.id = vs.qr_alias_id
                        WHERE q.resource_id = ?
                        """,
                        (resource["id"],),
                    ).fetchall()
                ]
                for session_id in session_ids:
                    connection.execute(
                        "DELETE FROM viewer_access_events WHERE viewer_session_id = ?",
                        (session_id,),
                    )
                connection.execute(
                    "DELETE FROM viewer_sessions WHERE qr_alias_id IN (SELECT id FROM qr_aliases WHERE resource_id = ?)",
                    (resource["id"],),
                )
                connection.execute(
                    "DELETE FROM preview_jobs WHERE revision_id IN (SELECT id FROM answer_revisions WHERE resource_id = ?)",
                    (resource["id"],),
                )
                connection.execute(
                    "DELETE FROM preview_pages WHERE preview_set_id IN (SELECT s.id FROM preview_sets s JOIN answer_revisions v ON v.id = s.revision_id WHERE v.resource_id = ?)",
                    (resource["id"],),
                )
                connection.execute(
                    "DELETE FROM preview_sets WHERE revision_id IN (SELECT id FROM answer_revisions WHERE resource_id = ?)",
                    (resource["id"],),
                )
                connection.execute(
                    """
                    UPDATE audit_events
                    SET resource_id = NULL, revision_id = NULL, qr_alias_id = NULL
                    WHERE resource_id = ? OR qr_alias_id IN (
                        SELECT id FROM qr_aliases WHERE resource_id = ?
                    )
                    """,
                    (resource["id"], resource["id"]),
                )
                connection.execute(
                    "UPDATE answer_resources SET current_published_revision_id = NULL WHERE id = ?",
                    (resource["id"],),
                )
                connection.execute("DELETE FROM qr_aliases WHERE resource_id = ?", (resource["id"],))
                connection.execute("DELETE FROM answer_revisions WHERE resource_id = ?", (resource["id"],))
                for asset_id in asset_ids:
                    still_used = connection.execute(
                        "SELECT 1 FROM answer_revisions WHERE asset_id = ? LIMIT 1", (asset_id,)
                    ).fetchone()
                    if still_used is None:
                        connection.execute("DELETE FROM assets WHERE id = ?", (asset_id,))

                legacy_binding_id = current["legacy_binding_id"]
                if legacy_binding_id is not None:
                    connection.execute(
                        "UPDATE bindings SET current_version_id = NULL WHERE id = ?",
                        (legacy_binding_id,),
                    )
                    connection.execute(
                        "DELETE FROM file_versions WHERE binding_id = ?",
                        (legacy_binding_id,),
                    )
                    connection.execute("DELETE FROM bindings WHERE id = ?", (legacy_binding_id,))
                connection.execute("DELETE FROM answer_resources WHERE id = ?", (resource["id"],))
                connection.execute(
                    """
                    INSERT INTO audit_events
                        (event_type, actor, summary, created_at)
                    VALUES ('permanent_delete_resource', ?, ?, ?)
                    """,
                    (
                        actor,
                        f"永久删除资料 {resource['display_code']}（{resource['name']}）",
                        utc_now_iso(),
                    ),
                )
        except Exception:
            for trash, original in reversed(moved_dirs):
                if trash.exists() and not original.exists():
                    os.replace(trash, original)
            for trash, original in reversed(moved_files):
                self.storage.restore_from_trash(trash, original)
            raise

        for trash, _ in moved_files:
            self.storage.delete(trash)
        for trash, _ in moved_dirs:
            shutil.rmtree(trash, ignore_errors=True)
        logger.info(
            "resource permanently deleted display_code=%s actor=%s",
            resource["display_code"],
            actor,
        )
        return {
            "qr_id": qr_id,
            "title": resource["name"],
            "display_code": resource["display_code"],
            "deleted": True,
        }

    def delete_many(self, qr_ids: list[str], actor: str) -> list[dict[str, Any]]:
        results = []
        for qr_id in dict.fromkeys(qr_ids):
            try:
                results.append(self.delete_one(qr_id, actor))
            except AppError as exc:
                results.append({"qr_id": qr_id, "deleted": False, "reason": exc.message})
            except Exception:
                logger.exception("permanent deletion failed qr_id=%s", qr_id)
                results.append(
                    {"qr_id": qr_id, "deleted": False, "reason": "删除失败，资料保持不变。"}
                )
        deleted_count = sum(1 for result in results if result["deleted"])
        skipped = [result for result in results if not result["deleted"]]
        skipped_summary = "；".join(
            f"{result.get('display_code') or result['qr_id']}：{result.get('reason', '未删除')}"
            for result in skipped
        )
        summary = f"批量永久删除完成：成功 {deleted_count} 条，跳过 {len(skipped)} 条"
        if skipped_summary:
            summary = f"{summary}；{skipped_summary}"[:1000]
        with self.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO audit_events (event_type, actor, summary, created_at)
                VALUES ('permanent_delete_batch', ?, ?, ?)
                """,
                (actor, summary, utc_now_iso()),
            )
        return results
