from __future__ import annotations

import argparse
from pathlib import Path

from app.database import Database


def main() -> int:
    parser = argparse.ArgumentParser(description="Run idempotent database migrations")
    parser.add_argument("database", type=Path)
    args = parser.parse_args()
    database = Database(args.database)
    database.initialize()
    connection = database.connect()
    try:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
    finally:
        connection.close()
    print(f"schema_version={version}")
    if database.last_backup_path:
        print(f"backup={database.last_backup_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
