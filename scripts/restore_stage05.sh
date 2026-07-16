#!/bin/sh
set -eu

usage() {
  echo "用法：$0 BACKUP.tar.gz [--target DIR] [--apply]" >&2
  exit 2
}

[ "$#" -ge 1 ] || usage
ARCHIVE=$1
shift
TARGET=""
APPLY=false
while [ "$#" -gt 0 ]; do
  case "$1" in
    --target) [ "$#" -ge 2 ] || usage; TARGET=$2; shift 2 ;;
    --apply) APPLY=true; shift ;;
    *) usage ;;
  esac
done
[ -f "$ARCHIVE" ] || { echo "找不到备份：$ARCHIVE" >&2; exit 1; }

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
TMP=$(mktemp -d "${TMPDIR:-/tmp}/stage05-restore.XXXXXX")
trap 'rm -rf -- "$TMP"' EXIT HUP INT TERM
tar -xzf "$ARCHIVE" -C "$TMP"
PAYLOAD="$TMP/stage05"
[ -f "$PAYLOAD/manifest.sha256" ] && [ -f "$PAYLOAD/db/app.db" ] || {
  echo "备份结构不完整" >&2; exit 1;
}
(cd "$PAYLOAD" && sha256sum -c manifest.sha256 >/dev/null)

RESTORE_ROOT="$PAYLOAD" python3 - <<'PY'
import hashlib
import json
import os
import sqlite3
from pathlib import Path

root = Path(os.environ["RESTORE_ROOT"])
connection = sqlite3.connect(root / "db" / "app.db")
if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
    raise SystemExit("恢复副本 SQLite integrity_check 失败")
expected = json.loads((root / "counts.json").read_text(encoding="utf-8"))
queries = {
    "resources": "SELECT COUNT(*) FROM answer_resources",
    "revisions": "SELECT COUNT(*) FROM answer_revisions",
    "assets": "SELECT COUNT(*) FROM assets",
    "preview_sets": "SELECT COUNT(*) FROM preview_sets",
    "preview_pages": "SELECT COUNT(*) FROM preview_pages",
    "dynamic_aliases": "SELECT COUNT(*) FROM qr_aliases WHERE resolve_mode='latest'",
    "fixed_aliases": "SELECT COUNT(*) FROM qr_aliases WHERE resolve_mode='pinned'",
}
actual = {name: connection.execute(sql).fetchone()[0] for name, sql in queries.items()}
if actual != expected:
    raise SystemExit(f"恢复数量不一致：{actual} != {expected}")
broken = connection.execute(
    """
    SELECT COUNT(*) FROM qr_aliases q
    LEFT JOIN answer_resources r ON r.id=q.resource_id
    LEFT JOIN answer_revisions v ON v.id=CASE WHEN q.resolve_mode='pinned'
      THEN q.pinned_revision_id ELSE r.current_published_revision_id END
    WHERE r.id IS NULL OR (q.status='active' AND v.id IS NULL)
    """
).fetchone()[0]
if broken:
    raise SystemExit(f"恢复副本存在 {broken} 个失效动态/固定 alias")
for row in connection.execute("SELECT storage_key, sha256 FROM assets"):
    path = root / "storage" / row[0]
    if not path.is_file():
        raise SystemExit(f"恢复副本缺少 Asset：{row[0]}")
    if hashlib.sha256(path.read_bytes()).hexdigest() != row[1]:
        raise SystemExit(f"恢复副本 Asset SHA-256 不一致：{row[0]}")
for row in connection.execute("SELECT storage_key, sha256 FROM preview_pages"):
    path = root / "storage" / row[0]
    if not path.is_file():
        raise SystemExit(f"恢复副本缺少 PreviewPage：{row[0]}")
    if hashlib.sha256(path.read_bytes()).hexdigest() != row[1]:
        raise SystemExit(f"恢复副本 PreviewPage SHA-256 不一致：{row[0]}")
print("恢复校验 PASS", actual)
PY

if [ "$APPLY" = false ]; then
  if [ -n "$TARGET" ]; then
    case "$TARGET" in /*) ;; *) TARGET="$PWD/$TARGET" ;; esac
    [ ! -e "$TARGET" ] || { echo "演练目标已存在：$TARGET" >&2; exit 1; }
    mkdir -p "$TARGET"
    cp -a "$PAYLOAD/." "$TARGET/"
    echo "恢复演练副本已写入：$TARGET"
  else
    echo "dry-run：完整性、数量、Alias 与全部文件 SHA-256 已验证；未写入目标。"
  fi
  exit 0
fi

[ -z "$TARGET" ] || { echo "--apply 不接受 --target" >&2; exit 1; }
[ "${STAGE05_RESTORE_CONFIRM:-}" = "RESTORE_STAGE05" ] || {
  echo "正式恢复还需设置 STAGE05_RESTORE_CONFIRM=RESTORE_STAGE05" >&2; exit 1;
}
cd "$ROOT"
if docker compose ps --status running --services | grep -Eq '^(pdf-worker|preview-worker)$'; then
  echo "正式恢复前必须停止 pdf-worker 与 preview-worker" >&2
  exit 1
fi
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
ROLLBACK="data/pdf-worker/restore-rollback-$STAMP"
mkdir -p "$ROLLBACK"
[ ! -e data/pdf-worker/db/app.db ] || cp -a data/pdf-worker/db/app.db "$ROLLBACK/app.db"
[ ! -d data/pdf-worker/storage ] || mv data/pdf-worker/storage "$ROLLBACK/storage"
[ ! -f .env ] || cp -a .env "$ROLLBACK/.env"
[ ! -f compose.yaml ] || cp -a compose.yaml "$ROLLBACK/compose.yaml"
mkdir -p data/pdf-worker/db
cp "$PAYLOAD/db/app.db" data/pdf-worker/db/app.db.restore
mv data/pdf-worker/db/app.db.restore data/pdf-worker/db/app.db
cp -a "$PAYLOAD/storage" data/pdf-worker/storage
cp "$PAYLOAD/config/.env" .env.restore && chmod 600 .env.restore && mv .env.restore .env
cp "$PAYLOAD/config/compose.yaml" compose.yaml.restore && mv compose.yaml.restore compose.yaml
echo "正式恢复完成；启动前请复核。原数据保存在：$ROLLBACK"
