from __future__ import annotations

import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator


SCHEMA_VERSION = 2
DISPLAY_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS bindings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    qr_id TEXT NOT NULL UNIQUE,
    current_version_id INTEGER,
    title TEXT NOT NULL,
    display_code TEXT NOT NULL UNIQUE,
    grade TEXT NOT NULL DEFAULT '未分类',
    subject TEXT NOT NULL DEFAULT '未分类',
    textbook_version TEXT,
    chapter TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    note TEXT,
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    FOREIGN KEY (current_version_id) REFERENCES file_versions(id)
);

CREATE TABLE IF NOT EXISTS file_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    binding_id INTEGER NOT NULL,
    version_number INTEGER NOT NULL,
    original_filename TEXT NOT NULL,
    stored_filename TEXT NOT NULL,
    storage_path TEXT NOT NULL UNIQUE,
    mime_type TEXT NOT NULL,
    size_bytes INTEGER NOT NULL CHECK (size_bytes > 0),
    sha256 TEXT NOT NULL,
    created_at TEXT NOT NULL,
    note TEXT,
    storage_backend TEXT NOT NULL DEFAULT 'local',
    FOREIGN KEY (binding_id) REFERENCES bindings(id) ON DELETE RESTRICT,
    UNIQUE (binding_id, version_number)
);

CREATE INDEX IF NOT EXISTS idx_file_versions_binding
    ON file_versions(binding_id, version_number DESC);

CREATE TABLE IF NOT EXISTS pdf_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL UNIQUE,
    binding_id INTEGER NOT NULL,
    qr_mode TEXT NOT NULL DEFAULT 'dynamic'
        CHECK (qr_mode IN ('dynamic', 'fixed')),
    qr_version_id INTEGER,
    source_original_filename TEXT NOT NULL,
    source_storage_path TEXT NOT NULL UNIQUE,
    output_storage_path TEXT UNIQUE,
    page_number INTEGER NOT NULL,
    position TEXT NOT NULL,
    size_mm REAL NOT NULL,
    margin_mm REAL NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('processing', 'completed', 'failed')),
    error_code TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL,
    completed_at TEXT,
    output_size_bytes INTEGER,
    output_sha256 TEXT,
    FOREIGN KEY (binding_id) REFERENCES bindings(id) ON DELETE RESTRICT,
    FOREIGN KEY (qr_version_id) REFERENCES file_versions(id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_pdf_jobs_binding
    ON pdf_jobs(binding_id, created_at DESC);

CREATE TABLE IF NOT EXISTS version_references (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    version_id INTEGER NOT NULL,
    reference_type TEXT NOT NULL,
    source_job_id TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    FOREIGN KEY (version_id) REFERENCES file_versions(id) ON DELETE RESTRICT,
    UNIQUE (version_id, reference_type, source_job_id)
);

CREATE INDEX IF NOT EXISTS idx_version_references_version
    ON version_references(version_id);
"""


def new_display_code() -> str:
    raw = "".join(secrets.choice(DISPLAY_CODE_ALPHABET) for _ in range(8))
    return f"QR-{raw[:4]}-{raw[4:]}"


class Database:
    def __init__(self, path: Path, busy_timeout_ms: int = 5000) -> None:
        self.path = path
        self.busy_timeout_ms = busy_timeout_ms
        self.last_backup_path: Path | None = None

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=self.busy_timeout_ms / 1000)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(f"PRAGMA busy_timeout = {self.busy_timeout_ms}")
        return connection

    def _backup(self, version: int) -> Path:
        backup_dir = self.path.parent / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup_path = backup_dir / f"app-before-stage03-v{version}-{stamp}.db"
        suffix = 1
        while backup_path.exists():
            backup_path = backup_dir / f"app-before-stage03-v{version}-{stamp}-{suffix}.db"
            suffix += 1
        source = sqlite3.connect(self.path)
        destination = sqlite3.connect(backup_path)
        try:
            source.backup(destination)
        finally:
            destination.close()
            source.close()
        self.last_backup_path = backup_path
        return backup_path

    @staticmethod
    def _unique_display_code(connection: sqlite3.Connection) -> str:
        for _ in range(100):
            code = new_display_code()
            found = connection.execute(
                "SELECT 1 FROM bindings WHERE display_code = ?", (code,)
            ).fetchone()
            if found is None:
                return code
        raise RuntimeError("could not allocate a unique display code")

    def _migrate_v1_to_v2(self, connection: sqlite3.Connection) -> None:
        connection.execute("ALTER TABLE bindings ADD COLUMN title TEXT")
        connection.execute("ALTER TABLE bindings ADD COLUMN display_code TEXT")
        connection.execute(
            "ALTER TABLE bindings ADD COLUMN grade TEXT NOT NULL DEFAULT '未分类'"
        )
        connection.execute(
            "ALTER TABLE bindings ADD COLUMN subject TEXT NOT NULL DEFAULT '未分类'"
        )
        connection.execute("ALTER TABLE bindings ADD COLUMN textbook_version TEXT")
        connection.execute("ALTER TABLE bindings ADD COLUMN chapter TEXT")
        connection.execute(
            "ALTER TABLE pdf_jobs ADD COLUMN qr_mode TEXT NOT NULL DEFAULT 'dynamic'"
        )
        connection.execute("ALTER TABLE pdf_jobs ADD COLUMN qr_version_id INTEGER")
        connection.execute(
            """CREATE TABLE version_references (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                version_id INTEGER NOT NULL,
                reference_type TEXT NOT NULL,
                source_job_id TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                FOREIGN KEY (version_id) REFERENCES file_versions(id) ON DELETE RESTRICT,
                UNIQUE (version_id, reference_type, source_job_id)
            )"""
        )
        connection.execute(
            "CREATE INDEX idx_version_references_version ON version_references(version_id)"
        )
        rows = connection.execute(
            """
            SELECT b.id, v.original_filename
            FROM bindings b
            LEFT JOIN file_versions v ON v.id = b.current_version_id
            ORDER BY b.id
            """
        ).fetchall()
        for row in rows:
            filename = row["original_filename"] or "未命名解析资料"
            title = Path(filename).stem.strip() or "未命名解析资料"
            connection.execute(
                "UPDATE bindings SET title = ?, display_code = ? WHERE id = ?",
                (title[:100], self._unique_display_code(connection), row["id"]),
            )
        connection.execute(
            "CREATE UNIQUE INDEX idx_bindings_display_code ON bindings(display_code)"
        )
        connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        if version > SCHEMA_VERSION:
            raise RuntimeError(
                f"database schema version {version} is newer than supported "
                f"version {SCHEMA_VERSION}"
            )
        if version == 0:
            with self.connect() as connection:
                connection.executescript(SCHEMA_SQL)
                connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
                connection.commit()
            return
        if version == 1:
            self._backup(version)
            with self.connect() as connection:
                try:
                    connection.execute("BEGIN IMMEDIATE")
                    self._migrate_v1_to_v2(connection)
                    connection.commit()
                except Exception:
                    connection.rollback()
                    raise
            return
        if version < SCHEMA_VERSION:
            raise RuntimeError(
                f"database schema migration from {version} is not implemented"
            )

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @contextmanager
    def read(self) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            yield connection
        finally:
            connection.close()

    def check_read_write(self) -> None:
        with self.transaction() as connection:
            connection.execute("SELECT 1")
