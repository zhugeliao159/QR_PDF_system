from __future__ import annotations

from app.config import Settings
from app.database import Database
from app.errors import AppError
from app.services.decoupled import AssetService
from app.services.preview_service import PreviewService
from app.storage.local import LocalStorageBackend


SUPPORTED_MIME_TYPES = {
    "application/pdf",
    "image/png",
    "image/jpeg",
    "image/webp",
}


def active_alias_inventory(database: Database) -> list[dict]:
    with database.read() as connection:
        rows = connection.execute(
            """
            SELECT q.resolve_mode, q.display_code AS alias_code,
                   r.display_code AS resource_code, r.name,
                   v.id AS revision_id, v.revision_number, v.target_type,
                   a.id AS asset_id, a.mime_type, a.sha256
            FROM qr_aliases q
            JOIN answer_resources r ON r.id = q.resource_id
            JOIN answer_revisions v ON v.id = CASE
                WHEN q.resolve_mode = 'pinned' THEN q.pinned_revision_id
                ELSE r.current_published_revision_id
            END
            LEFT JOIN assets a ON a.id = v.asset_id
            WHERE q.status = 'active' AND r.status = 'active'
            ORDER BY q.resolve_mode, r.id, v.revision_number, q.id
            """
        ).fetchall()
    return [dict(row) for row in rows]


def audit(settings: Settings) -> tuple[bool, list[str]]:
    database = Database(settings.database_path)
    storage = LocalStorageBackend(settings)
    service = PreviewService(settings, database, storage, AssetService(database, storage))
    rows = active_alias_inventory(database)
    lines: list[str] = []
    failures: list[str] = []
    totals = {"latest": 0, "pinned": 0}
    ready = {"latest": 0, "pinned": 0}
    external = 0

    for row in rows:
        mode = row["resolve_mode"]
        label = f"{row['resource_code']} 第 {row['revision_number']} 版 ({mode})"
        if row["target_type"] == "external_url":
            external += 1
            lines.append(f"EXTERNAL {label}：按 {settings.protected_preview_external_url_policy} 策略处理")
            continue
        totals[mode] += 1
        if row["mime_type"] not in SUPPORTED_MIME_TYPES:
            failures.append(f"UNSUPPORTED {label}：{row['mime_type'] or 'unknown'}")
            continue
        try:
            service.completed_preview(
                row["revision_id"],
                row["asset_id"],
                row["sha256"],
                verify_files=True,
            )
        except AppError as exc:
            failures.append(f"{exc.code} {label}")
        else:
            ready[mode] += 1
            lines.append(f"READY {label}")

    lines.append(
        "覆盖率：latest {}/{}，pinned {}/{}，external {}。".format(
            ready["latest"], totals["latest"], ready["pinned"], totals["pinned"], external
        )
    )
    lines.extend(failures)
    return not failures, lines


def main() -> int:
    settings = Settings.from_env()
    ok, lines = audit(settings)
    for line in lines:
        print(line)
    print("PASS：可以切换学生预览。" if ok else "FAIL：存在正在使用但不可完整预览的文件版本。")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
