from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import fitz

from app.config import Settings
from app.database import Database, new_display_code, new_public_key
from app.services.decoupled import AssetService
from app.services.preview_service import PreviewService
from app.storage.local import LocalStorageBackend


MARKER = "Stage 05D Worker Recovery Rehearsal"


def services():
    settings = Settings.from_env()
    database = Database(settings.database_path)
    storage = LocalStorageBackend(settings)
    preview = PreviewService(settings, database, storage, AssetService(database, storage))
    metadata_path = settings.database_path.parent / ".stage05d-recovery.json"
    return settings, database, storage, preview, metadata_path


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def setup(pages: int) -> None:
    settings, database, _, preview, metadata_path = services()
    if metadata_path.exists():
        raise RuntimeError("已有 Stage 05D 恢复演练未清理")
    asset_key = new_public_key()
    directory = settings.bindings_dir / "stage05d-recovery"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{asset_key}.pdf"
    document = fitz.open()
    for number in range(1, pages + 1):
        page = document.new_page(width=595, height=842)
        for line in range(1, 35):
            page.insert_text((35, 20 + line * 22), f"Stage 05D recovery page {number} line {line} x^2 + y^2")
    document.save(path)
    document.close()
    payload = path.read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    with database.transaction() as connection:
        resource_cursor = connection.execute(
            """
            INSERT INTO answer_resources
                (resource_key, name, display_code, grade, subject, status,
                 row_version, created_at, updated_at)
            VALUES (?, ?, ?, '未分类', '未分类', 'inactive', 1, ?, ?)
            """,
            (new_public_key(), MARKER, new_display_code(), now, now),
        )
        resource_id = int(resource_cursor.lastrowid)
        asset_cursor = connection.execute(
            """
            INSERT INTO assets
                (asset_key, storage_backend, storage_key, original_filename,
                 mime_type, size_bytes, sha256, created_at)
            VALUES (?, 'local', ?, 'stage05d-worker-recovery.pdf',
                    'application/pdf', ?, ?, ?)
            """,
            (
                asset_key,
                path.relative_to(settings.storage_root).as_posix(),
                len(payload),
                digest,
                now,
            ),
        )
        asset_id = int(asset_cursor.lastrowid)
        revision_cursor = connection.execute(
            """
            INSERT INTO answer_revisions
                (revision_key, resource_id, revision_number, target_type,
                 asset_id, status, created_at)
            VALUES (?, ?, 1, 'file', ?, 'draft', ?)
            """,
            (new_public_key(), resource_id, asset_id, now),
        )
        revision_id = int(revision_cursor.lastrowid)
        alias_cursor = connection.execute(
            """
            INSERT INTO qr_aliases
                (public_token, display_code, label, resource_id, resolve_mode,
                 status, created_at, updated_at)
            VALUES (?, ?, ?, ?, 'latest', 'inactive', ?, ?)
            """,
            (new_public_key(), new_display_code(), MARKER, resource_id, now, now),
        )
        alias_id = int(alias_cursor.lastrowid)
    request = preview.request_preview(revision_id)
    metadata_path.write_text(json.dumps({
        "resource_id": resource_id,
        "asset_id": asset_id,
        "revision_id": revision_id,
        "alias_id": alias_id,
        "job_id": request.job_id,
        "preview_set_id": request.preview_set_id,
        "asset_path": str(path),
        "asset_sha256": digest,
        "pages": pages,
    }), encoding="utf-8")
    print(f"SETUP job={request.job_id} pages={pages}")


def wait_for(expected: str, timeout: int) -> None:
    _, database, _, _, metadata_path = services()
    metadata = load(metadata_path)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with database.read() as connection:
            row = connection.execute(
                "SELECT status, attempts FROM preview_jobs WHERE id = ?",
                (metadata["job_id"],),
            ).fetchone()
        if row and row["status"] == expected:
            print(f"STATUS {expected} attempts={row['attempts']}")
            return
        time.sleep(0.1)
    raise RuntimeError(f"预览任务未在 {timeout}s 内进入 {expected}")


def mark_stale() -> None:
    settings, database, _, _, metadata_path = services()
    metadata = load(metadata_path)
    stale = datetime.now(timezone.utc) - timedelta(seconds=settings.preview_job_stale_seconds + 1)
    with database.transaction() as connection:
        row = connection.execute(
            "SELECT status FROM preview_jobs WHERE id = ?", (metadata["job_id"],)
        ).fetchone()
        if row is None or row["status"] != "processing":
            raise RuntimeError("任务不是中断后的 processing 状态")
        connection.execute(
            "UPDATE preview_jobs SET claimed_at = ? WHERE id = ?",
            (stale.isoformat().replace("+00:00", "Z"), metadata["job_id"]),
        )
    print("MARKED_STALE")


def verify() -> None:
    settings, database, _, _, metadata_path = services()
    metadata = load(metadata_path)
    with database.read() as connection:
        job = connection.execute("SELECT * FROM preview_jobs WHERE id = ?", (metadata["job_id"],)).fetchone()
        completed = connection.execute(
            "SELECT COUNT(*) FROM preview_sets WHERE revision_id = ? AND status = 'completed'",
            (metadata["revision_id"],),
        ).fetchone()[0]
        pages = connection.execute(
            "SELECT COUNT(*) FROM preview_pages WHERE preview_set_id = ?",
            (metadata["preview_set_id"],),
        ).fetchone()[0]
    if job["status"] != "completed" or job["attempts"] != 2:
        raise RuntimeError("恢复后的 job 状态或 attempts 不正确")
    if completed != 1 or pages != metadata["pages"]:
        raise RuntimeError("恢复产生重复 PreviewSet 或页面记录不完整")
    path = Path(metadata["asset_path"])
    if hashlib.sha256(path.read_bytes()).hexdigest() != metadata["asset_sha256"]:
        raise RuntimeError("恢复演练修改了原始 Asset")
    temp_dirs = list(settings.previews_dir.glob(".tmp-*"))
    if any(item.name.endswith(str(job["job_key"])) for item in temp_dirs):
        raise RuntimeError("恢复后仍残留任务临时目录")
    print(f"VERIFY PASS completed_sets={completed} pages={pages} attempts=2")


def cleanup() -> None:
    settings, database, _, _, metadata_path = services()
    if not metadata_path.exists():
        print("CLEANUP nothing")
        return
    metadata = load(metadata_path)
    with database.read() as connection:
        resource = connection.execute(
            "SELECT name, status, current_published_revision_id FROM answer_resources WHERE id = ?",
            (metadata["resource_id"],),
        ).fetchone()
        alias = connection.execute(
            "SELECT status FROM qr_aliases WHERE id = ?", (metadata["alias_id"],)
        ).fetchone()
    if resource is None or resource["name"] != MARKER or resource["status"] != "inactive":
        raise RuntimeError("拒绝清理非 Stage 05D 演练资源")
    if resource["current_published_revision_id"] is not None or alias["status"] != "inactive":
        raise RuntimeError("拒绝清理已发布或 active 演练资源")
    preview_dirs: list[Path] = []
    with database.transaction() as connection:
        for row in connection.execute(
            "SELECT preview_key FROM preview_sets WHERE revision_id = ?",
            (metadata["revision_id"],),
        ).fetchall():
            preview_dirs.append(settings.previews_dir / row["preview_key"])
        connection.execute(
            "DELETE FROM preview_pages WHERE preview_set_id IN (SELECT id FROM preview_sets WHERE revision_id = ?)",
            (metadata["revision_id"],),
        )
        connection.execute("DELETE FROM preview_jobs WHERE revision_id = ?", (metadata["revision_id"],))
        connection.execute("DELETE FROM preview_sets WHERE revision_id = ?", (metadata["revision_id"],))
        connection.execute("DELETE FROM qr_aliases WHERE id = ?", (metadata["alias_id"],))
        connection.execute("DELETE FROM answer_revisions WHERE id = ?", (metadata["revision_id"],))
        connection.execute("DELETE FROM assets WHERE id = ?", (metadata["asset_id"],))
        connection.execute("DELETE FROM answer_resources WHERE id = ?", (metadata["resource_id"],))
    for path in preview_dirs:
        if path.resolve(strict=False).parent == settings.previews_dir.resolve():
            shutil.rmtree(path, ignore_errors=True)
    asset_path = Path(metadata["asset_path"])
    if asset_path.resolve(strict=False).is_relative_to(settings.bindings_dir.resolve()):
        asset_path.unlink(missing_ok=True)
        try:
            asset_path.parent.rmdir()
        except OSError:
            pass
    metadata_path.unlink(missing_ok=True)
    print("CLEANUP PASS")


def main() -> int:
    parser = argparse.ArgumentParser(description="Stage 05D Preview Worker 中断恢复演练")
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--setup", action="store_true")
    modes.add_argument("--wait-processing", action="store_true")
    modes.add_argument("--mark-stale", action="store_true")
    modes.add_argument("--wait-completed", action="store_true")
    modes.add_argument("--verify", action="store_true")
    modes.add_argument("--cleanup", action="store_true")
    parser.add_argument("--pages", type=int, default=120)
    parser.add_argument("--timeout", type=int, default=120)
    args = parser.parse_args()
    if args.setup:
        setup(args.pages)
    elif args.wait_processing:
        wait_for("processing", args.timeout)
    elif args.mark_stale:
        mark_stale()
    elif args.wait_completed:
        wait_for("completed", args.timeout)
    elif args.verify:
        verify()
    else:
        cleanup()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
