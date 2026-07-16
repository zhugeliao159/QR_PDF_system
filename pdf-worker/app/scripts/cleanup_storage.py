from __future__ import annotations

import argparse

from app.config import Settings
from app.database import Database
from app.services.cleanup_service import CleanupService
from app.services.decoupled import AssetService
from app.services.preview_service import PreviewService
from app.storage.local import LocalStorageBackend


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="安全清理预览、会话和无引用 Asset。默认 dry-run。")
    mode = result.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="仅输出计划（默认）")
    mode.add_argument("--apply", action="store_true", help="重新检查引用后执行清理")
    return result


def build_service(settings: Settings) -> CleanupService:
    database = Database(settings.database_path)
    storage = LocalStorageBackend(settings)
    asset_service = AssetService(database, storage)
    preview_service = PreviewService(settings, database, storage, asset_service)
    return CleanupService(settings, database, storage, preview_service)


def main() -> int:
    args = parser().parse_args()
    settings = Settings.from_env()
    service = build_service(settings)
    plan = service.plan()
    print("清理模式：", "APPLY" if args.apply else "DRY-RUN")
    print(f"计划对象：{len(plan.items)}，预计释放：{plan.total_bytes} 字节")
    for category, count in sorted(plan.counts().items()):
        print(f"- {category}: {count}")
    print("保护并跳过：")
    for reason, count in sorted(plan.skipped.items()):
        print(f"- {reason}: {count}")
    for warning in plan.warnings:
        print(f"警告：{warning}")
    if not args.apply:
        print("dry-run：未修改数据库或文件。")
        return 0
    applied = service.apply()
    print("实际清理：")
    for category, count in sorted(applied.items()):
        print(f"- {category}: {count}")
    if not applied:
        print("- 无；当前没有可安全清理对象。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
