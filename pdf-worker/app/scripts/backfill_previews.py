from __future__ import annotations

import argparse
import socket
from typing import Any

from app.config import Settings
from app.database import Database
from app.services.decoupled import AssetService
from app.services.preview_service import PreviewService
from app.storage.local import LocalStorageBackend


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="为已有文件答案创建私有 WebP 预览任务。"
    )
    parser.add_argument("--dry-run", action="store_true", help="仅列出候选版本，不写数据库或文件")
    parser.add_argument("--limit", type=int, default=20, help="本次最多处理的版本数（默认 20）")
    parser.add_argument("--revision-key", help="只处理指定 revision_key")
    parser.add_argument("--only-current", action="store_true", help="只处理当前已发布版本")
    parser.add_argument("--only-published", action="store_true", help="处理全部已发布版本")
    parser.add_argument("--include-history", action="store_true", help="包含历史已发布版本")
    parser.add_argument("--resume", action="store_true", help="提交后同步处理队列，便于小批量恢复")
    parser.add_argument("--failed-only", action="store_true", help="只重试存在失败预览的版本")
    return parser


def find_candidates(database: Database, args: argparse.Namespace) -> list[dict[str, Any]]:
    clauses = [
        "v.target_type = 'file'",
        "a.mime_type IN ('application/pdf', 'image/png', 'image/jpeg', 'image/webp')",
    ]
    parameters: list[Any] = []
    if args.revision_key:
        clauses.append("v.revision_key = ?")
        parameters.append(args.revision_key)
    if args.only_current or not (args.only_published or args.include_history or args.revision_key):
        clauses.append("r.current_published_revision_id = v.id")
    elif args.only_published or args.include_history:
        clauses.append("v.status = 'published'")
    if args.failed_only:
        clauses.append(
            "EXISTS (SELECT 1 FROM preview_sets fs WHERE fs.revision_id = v.id AND fs.status = 'failed')"
        )
    if args.limit < 1:
        raise SystemExit("--limit 必须至少为 1")
    where = " AND ".join(clauses)
    with database.read() as connection:
        rows = connection.execute(
            f"""
            SELECT v.id, v.revision_key, v.revision_number, v.status,
                   r.display_code, r.name
            FROM answer_revisions v
            JOIN answer_resources r ON r.id = v.resource_id
            JOIN assets a ON a.id = v.asset_id
            WHERE {where}
            ORDER BY r.id, v.revision_number
            LIMIT ?
            """,
            [*parameters, args.limit],
        ).fetchall()
    return [dict(row) for row in rows]


def main() -> int:
    args = build_parser().parse_args()
    settings = Settings.from_env()
    settings.ensure_directories()
    database = Database(settings.database_path)
    database.initialize()
    storage = LocalStorageBackend(settings)
    storage.ensure_directories()
    service = PreviewService(settings, database, storage, AssetService(database, storage))
    candidates = find_candidates(database, args)
    print(f"候选版本：{len(candidates)}")
    for row in candidates:
        print(
            f"- {row['display_code']} 第 {row['revision_number']} 版 "
            f"({row['revision_key']})"
        )
    if args.dry_run:
        print("dry-run：未创建任务，未修改数据库或预览文件。")
        return 0

    created = reused = 0
    for row in candidates:
        request = service.request_preview(row["id"], force=args.failed_only)
        if request.reused:
            reused += 1
        else:
            created += 1
        print(
            f"{row['revision_key']}：{request.status} "
            f"({'复用已有结果或任务' if request.reused else '已创建预览任务'})"
        )
    processed = 0
    if args.resume:
        processed = service.process_until_idle(
            f"backfill:{socket.gethostname()}", max_jobs=max(len(candidates), 1)
        )
    print(
        f"回填汇总：候选 {len(candidates)}，新建 {created}，复用 {reused}，"
        f"同步处理 {processed}。"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
