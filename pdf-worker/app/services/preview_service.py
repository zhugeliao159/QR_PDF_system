from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from PIL import Image, UnidentifiedImageError

from app.config import Settings
from app.database import Database, new_public_key
from app.errors import AppError
from app.models import utc_now_iso
from app.services.decoupled import AssetService
from app.services.preview_renderers import (
    ImagePreviewRenderer,
    PdfPreviewRenderer,
    PreviewRenderConfig,
    PreviewRenderer,
)
from app.storage.base import StorageBackend


@dataclass(frozen=True)
class PreviewRequest:
    preview_set_id: int
    preview_key: str
    job_id: int | None
    job_key: str | None
    status: str
    reused: bool


class PreviewService:
    """Creates private, immutable preview derivatives without changing revision state."""

    def __init__(
        self,
        settings: Settings,
        database: Database,
        storage: StorageBackend,
        asset_service: AssetService,
    ) -> None:
        self.settings = settings
        self.database = database
        self.storage = storage
        self.asset_service = asset_service

    @property
    def render_config(self) -> PreviewRenderConfig:
        return PreviewRenderConfig.from_settings(self.settings)

    def _config_hash(self) -> str:
        encoded = json.dumps(
            self.render_config.as_dict(), ensure_ascii=True, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _clean_error_message(error: Exception) -> str:
        message = str(error).replace("\n", " ").replace("\r", " ").strip()
        return (message or "preview generation failed")[:500]

    @staticmethod
    def _revision_asset(connection: sqlite3.Connection, revision_id: int) -> dict[str, Any]:
        row = connection.execute(
            """
            SELECT v.id AS revision_id, v.revision_key, v.target_type, v.status AS revision_status,
                   a.id AS asset_id, a.storage_backend, a.storage_key, a.mime_type,
                   a.size_bytes, a.sha256, a.original_filename
            FROM answer_revisions v
            LEFT JOIN assets a ON a.id = v.asset_id
            WHERE v.id = ?
            """,
            (revision_id,),
        ).fetchone()
        if row is None:
            raise AppError(404, "PREVIEW_REVISION_NOT_FOUND", "answer revision does not exist")
        if row["target_type"] != "file" or row["asset_id"] is None:
            raise AppError(
                422,
                "PREVIEW_TARGET_UNSUPPORTED",
                "only private file revisions can generate previews",
            )
        if row["mime_type"] not in {
            "application/pdf",
            "image/png",
            "image/jpeg",
            "image/webp",
        }:
            raise AppError(
                415,
                "PREVIEW_FILE_TYPE_UNSUPPORTED",
                "this file type cannot generate a preview",
            )
        return dict(row)

    def request_preview(self, revision_id: int, *, force: bool = False) -> PreviewRequest:
        config = self.render_config
        config_hash = self._config_hash()
        now = utc_now_iso()
        with self.database.transaction() as connection:
            source = self._revision_asset(connection, revision_id)
            completed = connection.execute(
                """
                SELECT * FROM preview_sets
                WHERE revision_id = ? AND source_asset_id = ? AND source_sha256 = ?
                  AND renderer_version = ? AND render_config_hash = ?
                  AND status = 'completed'
                ORDER BY id DESC LIMIT 1
                """,
                (
                    revision_id,
                    source["asset_id"],
                    source["sha256"],
                    config.renderer_version,
                    config_hash,
                ),
            ).fetchone()
            if completed is not None and not force:
                return PreviewRequest(
                    preview_set_id=completed["id"],
                    preview_key=completed["preview_key"],
                    job_id=None,
                    job_key=None,
                    status="completed",
                    reused=True,
                )

            active = connection.execute(
                """
                SELECT j.*, s.preview_key FROM preview_jobs j
                JOIN preview_sets s ON s.id = j.preview_set_id
                WHERE j.revision_id = ? AND j.renderer_version = ?
                  AND j.render_config_hash = ?
                  AND j.status IN ('pending', 'processing')
                ORDER BY j.id DESC LIMIT 1
                """,
                (revision_id, config.renderer_version, config_hash),
            ).fetchone()
            if active is not None:
                return PreviewRequest(
                    preview_set_id=active["preview_set_id"],
                    preview_key=active["preview_key"],
                    job_id=active["id"],
                    job_key=active["job_key"],
                    status=active["status"],
                    reused=True,
                )

            if completed is not None:
                connection.execute(
                    "UPDATE preview_sets SET status = 'superseded' WHERE id = ?",
                    (completed["id"],),
                )

            preview_key = new_public_key()
            preview_set_id = int(
                connection.execute(
                    """
                    INSERT INTO preview_sets
                        (preview_key, revision_id, source_asset_id, source_sha256,
                         renderer_version, render_config_hash, status, page_count,
                         total_size_bytes, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, 'pending', 0, 0, ?)
                    """,
                    (
                        preview_key,
                        revision_id,
                        source["asset_id"],
                        source["sha256"],
                        config.renderer_version,
                        config_hash,
                        now,
                    ),
                ).lastrowid
            )
            job_key = new_public_key()
            job_id = int(
                connection.execute(
                    """
                    INSERT INTO preview_jobs
                        (job_key, revision_id, preview_set_id, renderer_version,
                         render_config_hash, status, rendered_pages, attempts,
                         max_attempts, created_at)
                    VALUES (?, ?, ?, ?, ?, 'pending', 0, 0, ?, ?)
                    """,
                    (
                        job_key,
                        revision_id,
                        preview_set_id,
                        config.renderer_version,
                        config_hash,
                        self.settings.preview_job_max_attempts,
                        now,
                    ),
                ).lastrowid
            )
        return PreviewRequest(
            preview_set_id=preview_set_id,
            preview_key=preview_key,
            job_id=job_id,
            job_key=job_key,
            status="pending",
            reused=False,
        )

    def status_for_revision(self, revision_id: int) -> dict[str, Any] | None:
        with self.database.read() as connection:
            row = connection.execute(
                """
                SELECT s.id, s.status, s.page_count, s.total_size_bytes,
                       s.renderer_version, s.created_at, s.completed_at,
                       s.error_code, j.job_key, j.rendered_pages, j.total_pages,
                       j.attempts, j.max_attempts, j.status AS job_status
                FROM preview_sets s
                LEFT JOIN preview_jobs j ON j.preview_set_id = s.id
                WHERE s.revision_id = ?
                ORDER BY s.id DESC, j.id DESC LIMIT 1
                """,
                (revision_id,),
            ).fetchone()
        return dict(row) if row is not None else None

    def list_pages(self, revision_id: int) -> list[dict[str, Any]]:
        with self.database.read() as connection:
            rows = connection.execute(
                """
                SELECT p.page_number, p.mime_type, p.width, p.height, p.size_bytes,
                       p.sha256
                FROM preview_pages p
                JOIN preview_sets s ON s.id = p.preview_set_id
                WHERE s.revision_id = ? AND s.status = 'completed'
                ORDER BY s.completed_at DESC, p.page_number ASC
                """,
                (revision_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def completed_preview(
        self,
        revision_id: int,
        source_asset_id: int,
        source_sha256: str,
        *,
        verify_files: bool = False,
    ) -> dict[str, Any]:
        """Return one complete preview while keeping every storage identifier private."""
        with self.database.read() as connection:
            preview = connection.execute(
                """
                SELECT id, status, page_count, total_size_bytes, completed_at,
                       renderer_version, source_asset_id, source_sha256
                FROM preview_sets
                WHERE revision_id = ? AND source_asset_id = ? AND source_sha256 = ?
                  AND status = 'completed'
                ORDER BY completed_at DESC, id DESC LIMIT 1
                """,
                (revision_id, source_asset_id, source_sha256),
            ).fetchone()
            if preview is None:
                latest = connection.execute(
                    """
                    SELECT status FROM preview_sets
                    WHERE revision_id = ?
                    ORDER BY id DESC LIMIT 1
                    """,
                    (revision_id,),
                ).fetchone()
                if latest is not None and latest["status"] == "failed":
                    raise AppError(
                        503,
                        "PREVIEW_FAILED",
                        "preview generation failed",
                    )
                raise AppError(
                    503,
                    "PREVIEW_NOT_READY",
                    "preview content is not ready",
                )
            pages = connection.execute(
                """
                SELECT page_number, storage_backend, storage_key, mime_type,
                       width, height, size_bytes, sha256
                FROM preview_pages
                WHERE preview_set_id = ?
                ORDER BY page_number
                """,
                (preview["id"],),
            ).fetchall()

        page_rows = [dict(page) for page in pages]
        expected = list(range(1, int(preview["page_count"]) + 1))
        if not expected or [page["page_number"] for page in page_rows] != expected:
            raise AppError(
                503,
                "PREVIEW_INCOMPLETE",
                "preview page records are incomplete",
            )
        for page in page_rows:
            path = self.storage.resolve(page["storage_key"])
            if not path.is_file() or path.stat().st_size != page["size_bytes"]:
                raise AppError(
                    503,
                    "PREVIEW_PAGE_MISSING",
                    "preview page file is missing",
                )
            if verify_files:
                self._verify_page_file(path, page)
        return {"preview": dict(preview), "pages": page_rows}

    def _verify_page_file(self, path: Path, page: dict[str, Any]) -> None:
        try:
            with Image.open(path) as image:
                image.load()
                if image.format != "WEBP" or image.size != (page["width"], page["height"]):
                    raise AppError(
                        503,
                        "PREVIEW_PAGE_INVALID",
                        "preview page file is invalid",
                    )
        except AppError:
            raise
        except (OSError, UnidentifiedImageError) as exc:
            raise AppError(
                503,
                "PREVIEW_PAGE_INVALID",
                "preview page file cannot be opened",
            ) from exc
        if self._sha256(path) != page["sha256"]:
            raise AppError(
                503,
                "PREVIEW_PAGE_HASH_MISMATCH",
                "preview page checksum does not match",
            )

    def student_page(
        self,
        revision_id: int,
        source_asset_id: int,
        source_sha256: str,
        page_number: int,
    ) -> tuple[Path, dict[str, Any]]:
        bundle = self.completed_preview(
            revision_id,
            source_asset_id,
            source_sha256,
        )
        if page_number < 1 or page_number > len(bundle["pages"]):
            raise AppError(404, "PREVIEW_PAGE_NOT_FOUND", "preview page does not exist")
        page = bundle["pages"][page_number - 1]
        path = self.storage.resolve(page["storage_key"])
        self._verify_page_file(path, page)
        return path, page

    def page_path(self, revision_id: int, page_number: int) -> tuple[Path, dict[str, Any]]:
        with self.database.read() as connection:
            row = connection.execute(
                """
                SELECT p.* FROM preview_pages p
                JOIN preview_sets s ON s.id = p.preview_set_id
                WHERE s.revision_id = ? AND s.status = 'completed' AND p.page_number = ?
                ORDER BY s.completed_at DESC LIMIT 1
                """,
                (revision_id, page_number),
            ).fetchone()
        if row is None:
            raise AppError(404, "PREVIEW_PAGE_NOT_FOUND", "preview page does not exist")
        page = dict(row)
        return self.storage.resolve(page["storage_key"]), page

    def _temp_dir(self, job_key: str) -> Path:
        return self.settings.previews_dir / f".tmp-{job_key}"

    def _final_dir(self, preview_key: str) -> Path:
        return self.settings.previews_dir / preview_key

    def _discard_dir(self, path: Path) -> None:
        root = self.settings.previews_dir.resolve()
        candidate = path.resolve(strict=False)
        if candidate.parent != root:
            raise AppError(500, "PREVIEW_PATH_INVALID", "preview temporary path is invalid")
        shutil.rmtree(candidate, ignore_errors=True)

    def recover_stale_jobs(self) -> int:
        cutoff = (
            datetime.now(timezone.utc) - timedelta(seconds=self.settings.preview_job_stale_seconds)
        ).isoformat().replace("+00:00", "Z")
        stale: list[dict[str, Any]] = []
        now = utc_now_iso()
        with self.database.transaction() as connection:
            rows = connection.execute(
                """
                SELECT j.id, j.job_key, j.preview_set_id, j.attempts, j.max_attempts
                FROM preview_jobs j
                WHERE j.status = 'processing' AND j.claimed_at IS NOT NULL
                  AND j.claimed_at < ?
                """,
                (cutoff,),
            ).fetchall()
            for row in rows:
                stale.append(dict(row))
                terminal = row["attempts"] >= row["max_attempts"]
                job_status = "failed" if terminal else "pending"
                preview_status = "failed" if terminal else "pending"
                connection.execute(
                    """
                    UPDATE preview_jobs
                    SET status = ?, claimed_at = NULL, worker_id = NULL,
                        completed_at = CASE WHEN ? THEN ? ELSE completed_at END,
                        error_code = 'PREVIEW_JOB_STALE',
                        error_message = 'preview worker claim expired'
                    WHERE id = ? AND status = 'processing'
                    """,
                    (job_status, 1 if terminal else 0, now, row["id"]),
                )
                connection.execute(
                    """
                    UPDATE preview_sets
                    SET status = ?, error_code = 'PREVIEW_JOB_STALE',
                        error_message = 'preview worker claim expired'
                    WHERE id = ? AND status = 'processing'
                    """,
                    (preview_status, row["preview_set_id"]),
                )
        for job in stale:
            self._discard_dir(self._temp_dir(job["job_key"]))
        return len(stale)

    def _claim_next(self, worker_id: str) -> dict[str, Any] | None:
        now = utc_now_iso()
        with self.database.transaction() as connection:
            job = connection.execute(
                """
                SELECT j.*, s.preview_key, s.source_asset_id, s.source_sha256,
                       a.storage_backend, a.storage_key, a.mime_type, a.size_bytes,
                       a.sha256 AS asset_sha256
                FROM preview_jobs j
                JOIN preview_sets s ON s.id = j.preview_set_id
                JOIN assets a ON a.id = s.source_asset_id
                WHERE j.status = 'pending'
                ORDER BY j.created_at, j.id
                LIMIT 1
                """
            ).fetchone()
            if job is None:
                return None
            result = connection.execute(
                """
                UPDATE preview_jobs
                SET status = 'processing', attempts = attempts + 1,
                    claimed_at = ?, worker_id = ?,
                    started_at = COALESCE(started_at, ?),
                    error_code = NULL, error_message = NULL
                WHERE id = ? AND status = 'pending'
                """,
                (now, worker_id, now, job["id"]),
            )
            if result.rowcount != 1:
                return None
            connection.execute(
                """
                UPDATE preview_sets
                SET status = 'processing', error_code = NULL, error_message = NULL
                WHERE id = ? AND status IN ('pending', 'failed')
                """,
                (job["preview_set_id"],),
            )
            claimed = connection.execute(
                """
                SELECT j.*, s.preview_key, s.source_asset_id, s.source_sha256,
                       a.storage_backend, a.storage_key, a.mime_type, a.size_bytes,
                       a.sha256 AS asset_sha256
                FROM preview_jobs j
                JOIN preview_sets s ON s.id = j.preview_set_id
                JOIN assets a ON a.id = s.source_asset_id
                WHERE j.id = ?
                """,
                (job["id"],),
            ).fetchone()
        return dict(claimed)

    def _update_progress(self, job_id: int, total_pages: int, rendered_pages: int) -> None:
        with self.database.transaction() as connection:
            connection.execute(
                """
                UPDATE preview_jobs
                SET total_pages = ?, rendered_pages = ?
                WHERE id = ? AND status = 'processing'
                """,
                (total_pages, rendered_pages, job_id),
            )

    def _renderer_for(self, mime_type: str) -> PreviewRenderer:
        if mime_type == "application/pdf":
            return PdfPreviewRenderer()
        if mime_type in {"image/png", "image/jpeg", "image/webp"}:
            return ImagePreviewRenderer(self.settings)
        raise AppError(
            415,
            "PREVIEW_FILE_TYPE_UNSUPPORTED",
            "this file type cannot generate a preview",
        )

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
        return digest.hexdigest()

    def _write_manifest(self, directory: Path, job: dict[str, Any], pages: list[dict[str, Any]]) -> None:
        manifest = {
            "preview_key": job["preview_key"],
            "renderer_version": job["renderer_version"],
            "page_count": len(pages),
            "pages": [
                {
                    "page_number": page["page_number"],
                    "filename": Path(page["storage_key"]).name,
                    "sha256": page["sha256"],
                    "size_bytes": page["size_bytes"],
                }
                for page in pages
            ],
        }
        (directory / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    def _complete(self, job: dict[str, Any], result) -> None:
        if not result.pages:
            raise AppError(422, "PREVIEW_EMPTY", "preview renderer did not produce pages")
        page_numbers = [page.page_number for page in result.pages]
        if page_numbers != list(range(1, len(page_numbers) + 1)):
            raise AppError(422, "PREVIEW_PAGE_SEQUENCE_INVALID", "preview pages are not consecutive")
        temp_dir = self._temp_dir(job["job_key"])
        final_dir = self._final_dir(job["preview_key"])
        pages = [
            {
                "page_number": page.page_number,
                "storage_key": f"previews/{job['preview_key']}/{page.filename}",
                "mime_type": page.mime_type,
                "width": page.width,
                "height": page.height,
                "size_bytes": page.size_bytes,
                "sha256": page.sha256,
            }
            for page in result.pages
        ]
        self._write_manifest(temp_dir, job, pages)
        moved = False
        now = utc_now_iso()
        try:
            with self.database.transaction() as connection:
                current = connection.execute(
                    "SELECT status FROM preview_jobs WHERE id = ?", (job["id"],)
                ).fetchone()
                if current is None or current["status"] != "processing":
                    raise AppError(409, "PREVIEW_JOB_NOT_CLAIMED", "preview job is no longer claimed")
                if final_dir.exists():
                    raise AppError(409, "PREVIEW_STORAGE_COLLISION", "preview output already exists")
                for page in pages:
                    connection.execute(
                        """
                        INSERT INTO preview_pages
                            (preview_set_id, page_number, storage_backend, storage_key,
                             mime_type, width, height, size_bytes, sha256, created_at)
                        VALUES (?, ?, 'local', ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            job["preview_set_id"],
                            page["page_number"],
                            page["storage_key"],
                            page["mime_type"],
                            page["width"],
                            page["height"],
                            page["size_bytes"],
                            page["sha256"],
                            now,
                        ),
                    )
                connection.execute(
                    """
                    UPDATE preview_sets
                    SET status = 'completed', page_count = ?, total_size_bytes = ?,
                        completed_at = ?, error_code = NULL, error_message = NULL
                    WHERE id = ? AND status = 'processing'
                    """,
                    (len(pages), result.total_size_bytes, now, job["preview_set_id"]),
                )
                connection.execute(
                    """
                    UPDATE preview_jobs
                    SET status = 'completed', total_pages = ?, rendered_pages = ?,
                        completed_at = ?, error_code = NULL, error_message = NULL
                    WHERE id = ? AND status = 'processing'
                    """,
                    (len(pages), len(pages), now, job["id"]),
                )
                os.replace(temp_dir, final_dir)
                moved = True
        except Exception:
            if moved:
                self._discard_dir(final_dir)
            raise

    def _fail(self, job: dict[str, Any], error: Exception) -> None:
        error_code = error.code if isinstance(error, AppError) else "PREVIEW_RENDER_FAILED"
        error_message = self._clean_error_message(error)
        now = utc_now_iso()
        with self.database.transaction() as connection:
            current = connection.execute(
                "SELECT attempts, max_attempts FROM preview_jobs WHERE id = ?", (job["id"],)
            ).fetchone()
            if current is None:
                return
            terminal = current["attempts"] >= current["max_attempts"]
            job_status = "failed" if terminal else "pending"
            preview_status = "failed" if terminal else "pending"
            connection.execute(
                """
                UPDATE preview_jobs
                SET status = ?, claimed_at = NULL, worker_id = NULL,
                    completed_at = CASE WHEN ? THEN ? ELSE NULL END,
                    error_code = ?, error_message = ?
                WHERE id = ?
                """,
                (job_status, 1 if terminal else 0, now, error_code, error_message, job["id"]),
            )
            connection.execute(
                """
                UPDATE preview_sets
                SET status = ?, error_code = ?, error_message = ?
                WHERE id = ? AND status = 'processing'
                """,
                (preview_status, error_code, error_message, job["preview_set_id"]),
            )

    def process_next(self, worker_id: str) -> bool:
        self.recover_stale_jobs()
        job = self._claim_next(worker_id)
        if job is None:
            return False
        temp_dir = self._temp_dir(job["job_key"])
        try:
            self._discard_dir(temp_dir)
            temp_dir.mkdir(parents=True, exist_ok=False)
            if job["source_sha256"] != job["asset_sha256"]:
                raise AppError(
                    409,
                    "PREVIEW_SOURCE_HASH_MISMATCH",
                    "source asset metadata changed before rendering",
                )
            path = self.storage.resolve(job["storage_key"])
            if self._sha256(path) != job["source_sha256"]:
                raise AppError(
                    409,
                    "PREVIEW_SOURCE_HASH_MISMATCH",
                    "source asset content changed before rendering",
                )
            renderer = self._renderer_for(job["mime_type"])
            result = renderer.render(
                path,
                temp_dir,
                self.render_config,
                lambda total, completed: self._update_progress(job["id"], total, completed),
            )
            self._complete(job, result)
        except Exception as exc:
            self._discard_dir(temp_dir)
            self._fail(job, exc)
        return True

    def process_until_idle(self, worker_id: str, max_jobs: int | None = None) -> int:
        processed = 0
        while max_jobs is None or processed < max_jobs:
            if not self.process_next(worker_id):
                break
            processed += 1
        return processed
