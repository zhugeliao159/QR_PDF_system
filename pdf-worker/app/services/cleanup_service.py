from __future__ import annotations

import os
import shutil
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app.config import Settings
from app.database import Database
from app.services.preview_service import PreviewService
from app.storage.base import StorageBackend


def iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def directory_size(path: Path) -> int:
    total = 0
    if not path.exists():
        return 0
    for item in path.rglob("*"):
        if item.is_file() and not item.is_symlink():
            total += item.stat().st_size
    return total


@dataclass(frozen=True)
class CleanupItem:
    category: str
    object_id: str
    bytes: int = 0


@dataclass
class CleanupPlan:
    items: list[CleanupItem] = field(default_factory=list)
    skipped: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    @property
    def total_bytes(self) -> int:
        return sum(item.bytes for item in self.items)

    def counts(self) -> dict[str, int]:
        result: dict[str, int] = {}
        for item in self.items:
            result[item.category] = result.get(item.category, 0) + 1
        return result


class CleanupService:
    def __init__(
        self,
        settings: Settings,
        database: Database,
        storage: StorageBackend,
        preview_service: PreviewService,
    ) -> None:
        self.settings = settings
        self.database = database
        self.storage = storage
        self.preview_service = preview_service

    def _cutoffs(self) -> dict[str, str]:
        now = datetime.now(timezone.utc)
        return {
            "now": iso(now),
            "stale": iso(now - timedelta(seconds=self.settings.preview_job_stale_seconds)),
            "idle": iso(now - timedelta(minutes=self.settings.viewer_session_idle_minutes)),
            "session": iso(now - timedelta(days=self.settings.viewer_session_retention_days)),
            "viewer_event": iso(now - timedelta(days=self.settings.viewer_access_event_retention_days)),
            "audit_event": iso(now - timedelta(days=self.settings.audit_event_retention_days)),
            "temp": iso(now - timedelta(hours=24)),
        }

    def plan(self) -> CleanupPlan:
        cutoffs = self._cutoffs()
        plan = CleanupPlan(
            warnings=[
                "默认仅 dry-run；--apply 会在每个删除动作前重新检查数据库引用。",
                "不会删除 current、pinned、固定引用、active draft 或其 completed 预览。",
            ]
        )
        with self.database.read() as connection:
            stale = connection.execute(
                """
                SELECT id, job_key FROM preview_jobs
                WHERE status = 'processing' AND claimed_at IS NOT NULL AND claimed_at < ?
                """,
                (cutoffs["stale"],),
            ).fetchall()
            for row in stale:
                plan.items.append(CleanupItem("stale_processing_job", str(row["id"])))

            superseded = connection.execute(
                """
                SELECT s.id, s.preview_key, COALESCE(SUM(p.size_bytes), 0) AS bytes
                FROM preview_sets s
                LEFT JOIN preview_pages p ON p.preview_set_id = s.id
                WHERE s.status = 'superseded'
                GROUP BY s.id
                """
            ).fetchall()
            for row in superseded:
                plan.items.append(
                    CleanupItem("superseded_preview_set", str(row["id"]), int(row["bytes"]))
                )

            orphan_sets = connection.execute(
                """
                SELECT s.id, s.preview_key, COALESCE(SUM(p.size_bytes), 0) AS bytes
                FROM preview_sets s
                LEFT JOIN answer_revisions v ON v.id = s.revision_id
                LEFT JOIN preview_pages p ON p.preview_set_id = s.id
                WHERE v.id IS NULL GROUP BY s.id
                """
            ).fetchall()
            for row in orphan_sets:
                plan.items.append(
                    CleanupItem("orphan_preview_set", str(row["id"]), int(row["bytes"]))
                )

            expiring = connection.execute(
                """
                SELECT id FROM viewer_sessions
                WHERE status = 'active' AND (expires_at < ? OR last_seen_at < ?)
                """,
                (cutoffs["now"], cutoffs["idle"]),
            ).fetchall()
            for row in expiring:
                plan.items.append(CleanupItem("expire_viewer_session", str(row["id"])))

            old_events = connection.execute(
                "SELECT id FROM viewer_access_events WHERE created_at < ?",
                (cutoffs["viewer_event"],),
            ).fetchall()
            for row in old_events:
                plan.items.append(CleanupItem("expired_viewer_access_event", str(row["id"])))

            old_sessions = connection.execute(
                """
                SELECT s.id FROM viewer_sessions s
                WHERE s.status IN ('expired', 'revoked', 'blocked')
                  AND s.last_seen_at < ?
                  AND NOT EXISTS (
                    SELECT 1 FROM viewer_access_events e
                    WHERE e.viewer_session_id = s.id AND e.created_at >= ?
                  )
                """,
                (cutoffs["session"], cutoffs["viewer_event"]),
            ).fetchall()
            for row in old_sessions:
                plan.items.append(CleanupItem("expired_viewer_session", str(row["id"])))

            old_audits = connection.execute(
                "SELECT id FROM audit_events WHERE created_at < ?",
                (cutoffs["audit_event"],),
            ).fetchall()
            for row in old_audits:
                plan.items.append(CleanupItem("expired_audit_event", str(row["id"])))

            orphan_assets = connection.execute(
                """
                SELECT a.id, a.storage_key, a.size_bytes
                FROM assets a
                WHERE NOT EXISTS (SELECT 1 FROM answer_revisions v WHERE v.asset_id = a.id)
                  AND NOT EXISTS (SELECT 1 FROM preview_sets s WHERE s.source_asset_id = a.id)
                """
            ).fetchall()
            for row in orphan_assets:
                plan.items.append(
                    CleanupItem("orphan_asset", str(row["id"]), int(row["size_bytes"]))
                )

            plan.skipped = {
                "current_revision_assets": int(connection.execute(
                    "SELECT COUNT(DISTINCT asset_id) FROM answer_revisions v JOIN answer_resources r ON r.current_published_revision_id = v.id WHERE v.asset_id IS NOT NULL"
                ).fetchone()[0]),
                "pinned_or_fixed_revisions": int(connection.execute(
                    "SELECT COUNT(DISTINCT v.id) FROM answer_revisions v WHERE EXISTS (SELECT 1 FROM qr_aliases q WHERE q.pinned_revision_id = v.id) OR EXISTS (SELECT 1 FROM revision_references rr WHERE rr.revision_id = v.id)"
                ).fetchone()[0]),
                "active_draft_assets": int(connection.execute(
                    "SELECT COUNT(DISTINCT asset_id) FROM answer_revisions WHERE status = 'draft' AND asset_id IS NOT NULL"
                ).fetchone()[0]),
                "completed_previews": int(connection.execute(
                    "SELECT COUNT(*) FROM preview_sets WHERE status = 'completed'"
                ).fetchone()[0]),
            }
            job_states = {
                row["job_key"]: (row["status"], row["claimed_at"])
                for row in connection.execute(
                    "SELECT job_key, status, claimed_at FROM preview_jobs"
                ).fetchall()
            }

        for path in self.settings.previews_dir.glob(".tmp-*"):
            if not path.is_dir() or path.is_symlink():
                continue
            key = path.name.removeprefix(".tmp-")
            state = job_states.get(key)
            safe = state is None or state[0] != "processing" or (
                state[1] is not None and state[1] < cutoffs["stale"]
            )
            if safe:
                plan.items.append(CleanupItem("preview_temp_directory", key, directory_size(path)))

        cache_root = self.settings.storage_root / "cache" / "watermarked"
        if cache_root.is_dir() and not cache_root.is_symlink():
            for path in cache_root.iterdir():
                if path.is_dir() and not path.is_symlink():
                    plan.items.append(
                        CleanupItem("expired_watermark_cache", path.name, directory_size(path))
                    )
        return plan

    def _safe_remove_directory(self, path: Path, parent: Path) -> None:
        candidate = path.resolve(strict=False)
        root = parent.resolve()
        if candidate.parent != root or candidate.is_symlink():
            raise RuntimeError("cleanup path escaped its expected parent")
        shutil.rmtree(candidate, ignore_errors=False)

    def _delete_preview_set(self, set_id: int) -> bool:
        with self.database.read() as connection:
            row = connection.execute(
                "SELECT id, preview_key, status FROM preview_sets WHERE id = ?",
                (set_id,),
            ).fetchone()
        if row is None or row["status"] not in {"superseded"}:
            return False
        directory = self.settings.previews_dir / row["preview_key"]
        trash = self.settings.trash_dir / f"preview-{uuid.uuid4().hex}.trash"
        moved = False
        if directory.exists():
            if directory.resolve(strict=False).parent != self.settings.previews_dir.resolve():
                raise RuntimeError("preview cleanup path escaped preview root")
            os.replace(directory, trash)
            moved = True
        try:
            with self.database.transaction() as connection:
                current = connection.execute(
                    "SELECT status FROM preview_sets WHERE id = ?", (set_id,)
                ).fetchone()
                if current is None or current["status"] != "superseded":
                    raise RuntimeError("preview set became protected during cleanup")
                connection.execute("DELETE FROM preview_pages WHERE preview_set_id = ?", (set_id,))
                connection.execute("UPDATE preview_jobs SET preview_set_id = NULL WHERE preview_set_id = ?", (set_id,))
                connection.execute("DELETE FROM preview_sets WHERE id = ?", (set_id,))
        except Exception:
            if moved:
                os.replace(trash, directory)
            raise
        if moved:
            self._safe_remove_directory(trash, self.settings.trash_dir)
        return True

    def _delete_orphan_asset(self, asset_id: int) -> bool:
        with self.database.read() as connection:
            row = connection.execute(
                """
                SELECT a.id, a.storage_key FROM assets a
                WHERE a.id = ?
                  AND NOT EXISTS (SELECT 1 FROM answer_revisions v WHERE v.asset_id = a.id)
                  AND NOT EXISTS (SELECT 1 FROM preview_sets s WHERE s.source_asset_id = a.id)
                """,
                (asset_id,),
            ).fetchone()
        if row is None:
            return False
        trash_path: str | None = None
        try:
            path = self.storage.resolve(row["storage_key"], must_exist=False)
            if path.is_file():
                trash_path = self.storage.move_to_trash(row["storage_key"])
            with self.database.transaction() as connection:
                cursor = connection.execute(
                    """
                    DELETE FROM assets WHERE id = ?
                      AND NOT EXISTS (SELECT 1 FROM answer_revisions v WHERE v.asset_id = assets.id)
                      AND NOT EXISTS (SELECT 1 FROM preview_sets s WHERE s.source_asset_id = assets.id)
                    """,
                    (asset_id,),
                )
                if cursor.rowcount != 1:
                    raise RuntimeError("asset became referenced during cleanup")
        except Exception:
            if trash_path is not None:
                self.storage.restore_from_trash(trash_path, row["storage_key"])
            raise
        if trash_path is not None:
            self.storage.delete(trash_path)
        return True

    def apply(self) -> dict[str, int]:
        applied: dict[str, int] = {}
        recovered = self.preview_service.recover_stale_jobs()
        if recovered:
            applied["stale_processing_job"] = recovered
        plan = self.plan()

        with self.database.transaction() as connection:
            cursor = connection.execute(
                "DELETE FROM viewer_access_events WHERE created_at < ?",
                (self._cutoffs()["viewer_event"],),
            )
            if cursor.rowcount:
                applied["expired_viewer_access_event"] = cursor.rowcount
            cursor = connection.execute(
                """
                UPDATE viewer_sessions SET status = 'expired'
                WHERE status = 'active' AND (expires_at < ? OR last_seen_at < ?)
                """,
                (self._cutoffs()["now"], self._cutoffs()["idle"]),
            )
            if cursor.rowcount:
                applied["expire_viewer_session"] = cursor.rowcount
            cursor = connection.execute(
                """
                DELETE FROM viewer_sessions
                WHERE status IN ('expired', 'revoked', 'blocked') AND last_seen_at < ?
                  AND NOT EXISTS (SELECT 1 FROM viewer_access_events e WHERE e.viewer_session_id = viewer_sessions.id)
                """,
                (self._cutoffs()["session"],),
            )
            if cursor.rowcount:
                applied["expired_viewer_session"] = cursor.rowcount
            cursor = connection.execute(
                "DELETE FROM audit_events WHERE created_at < ?",
                (self._cutoffs()["audit_event"],),
            )
            if cursor.rowcount:
                applied["expired_audit_event"] = cursor.rowcount

        for item in plan.items:
            if item.category in {"superseded_preview_set", "orphan_preview_set"}:
                if self._delete_preview_set(int(item.object_id)):
                    applied[item.category] = applied.get(item.category, 0) + 1
            elif item.category == "orphan_asset":
                if self._delete_orphan_asset(int(item.object_id)):
                    applied[item.category] = applied.get(item.category, 0) + 1
            elif item.category == "preview_temp_directory":
                path = self.settings.previews_dir / f".tmp-{item.object_id}"
                if path.is_dir() and not path.is_symlink():
                    self._safe_remove_directory(path, self.settings.previews_dir)
                    applied[item.category] = applied.get(item.category, 0) + 1
            elif item.category == "expired_watermark_cache":
                root = self.settings.storage_root / "cache" / "watermarked"
                path = root / item.object_id
                if path.is_dir() and not path.is_symlink():
                    self._safe_remove_directory(path, root)
                    applied[item.category] = applied.get(item.category, 0) + 1
        return applied
