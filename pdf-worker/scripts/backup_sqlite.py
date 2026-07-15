from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path


def backup(source_path: Path, destination_path: Path) -> None:
    source_path = source_path.resolve()
    destination_path = destination_path.resolve()
    if source_path == destination_path:
        raise ValueError("source and destination must be different")
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    if destination_path.exists():
        raise FileExistsError(f"backup already exists: {destination_path}")

    source = sqlite3.connect(f"file:{source_path}?mode=ro", uri=True)
    destination = sqlite3.connect(destination_path)
    try:
        source.backup(destination)
        result = destination.execute("PRAGMA integrity_check").fetchone()[0]
        if result != "ok":
            raise RuntimeError(f"backup integrity check failed: {result}")
    finally:
        destination.close()
        source.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a consistent SQLite backup")
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    backup(args.source, args.destination)
    print(args.destination.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
