#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
ARCHIVE=${1:-"$ROOT/../qr-stage05-$STAMP.tar.gz"}
case "$ARCHIVE" in /*) ;; *) ARCHIVE="$ROOT/$ARCHIVE" ;; esac
if [ -e "$ARCHIVE" ] || [ -e "$ARCHIVE.tmp" ]; then
  echo "备份目标已存在：$ARCHIVE" >&2
  exit 1
fi
TMP=$(mktemp -d "${TMPDIR:-/tmp}/stage05-backup.XXXXXX")
trap 'rm -rf -- "$TMP"' EXIT HUP INT TERM
PAYLOAD="$TMP/stage05"
mkdir -p "$PAYLOAD/db" "$PAYLOAD/storage" "$PAYLOAD/config"

DB_TEMP=".stage05-backup-$STAMP.db"
docker compose exec -T pdf-worker \
  python scripts/backup_sqlite.py /data/db/app.db "/data/db/$DB_TEMP" >/dev/null
cp "data/pdf-worker/db/$DB_TEMP" "$PAYLOAD/db/app.db"
rm -f "data/pdf-worker/db/$DB_TEMP"

for directory in bindings previews batch-imports source-pdfs generated-pdfs; do
  if [ -d "data/pdf-worker/storage/$directory" ]; then
    cp -a "data/pdf-worker/storage/$directory" "$PAYLOAD/storage/$directory"
  fi
done
if [ -d "$PAYLOAD/storage/previews" ]; then
  find "$PAYLOAD/storage/previews" -mindepth 1 -maxdepth 1 -type d -name '.tmp-*' -exec rm -rf -- {} +
fi
cp .env compose.yaml .env.example "$PAYLOAD/config/"
git rev-parse HEAD > "$PAYLOAD/config/git-commit.txt"

BACKUP_ROOT="$PAYLOAD" python3 - <<'PY'
import json
import os
import sqlite3
from pathlib import Path

root = Path(os.environ["BACKUP_ROOT"])
connection = sqlite3.connect(root / "db" / "app.db")
integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
if integrity != "ok":
    raise SystemExit(f"SQLite integrity check failed: {integrity}")
queries = {
    "resources": "SELECT COUNT(*) FROM answer_resources",
    "revisions": "SELECT COUNT(*) FROM answer_revisions",
    "assets": "SELECT COUNT(*) FROM assets",
    "preview_sets": "SELECT COUNT(*) FROM preview_sets",
    "preview_pages": "SELECT COUNT(*) FROM preview_pages",
    "dynamic_aliases": "SELECT COUNT(*) FROM qr_aliases WHERE resolve_mode='latest'",
    "fixed_aliases": "SELECT COUNT(*) FROM qr_aliases WHERE resolve_mode='pinned'",
}
counts = {name: connection.execute(sql).fetchone()[0] for name, sql in queries.items()}
(root / "counts.json").write_text(json.dumps(counts, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY

(cd "$PAYLOAD" && find . -type f ! -name manifest.sha256 -print0 | sort -z | xargs -0 sha256sum > manifest.sha256)
mkdir -p "$(dirname -- "$ARCHIVE")"
tar -czf "$ARCHIVE.tmp" -C "$TMP" stage05
chmod 600 "$ARCHIVE.tmp"
mv "$ARCHIVE.tmp" "$ARCHIVE"
echo "备份完成：$ARCHIVE"
echo "包含 SQLite Backup API 副本、原始 Asset、基础预览、配置、数量清单和 SHA-256。"
