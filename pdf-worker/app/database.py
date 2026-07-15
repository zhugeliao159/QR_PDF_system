from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


SCHEMA_VERSION = 1

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS bindings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    qr_id TEXT NOT NULL UNIQUE,
    current_version_id INTEGER,
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
    FOREIGN KEY (binding_id) REFERENCES bindings(id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_pdf_jobs_binding
    ON pdf_jobs(binding_id, created_at DESC);
"""


class Database:
    def __init__(self, path: Path, busy_timeout_ms: int = 5000) -> None:
        self.path = path
        self.busy_timeout_ms = busy_timeout_ms

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=self.busy_timeout_ms / 1000)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(f"PRAGMA busy_timeout = {self.busy_timeout_ms}")
        return connection

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
                connection.executescript(SCHEMA_SQL)
                connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
                connection.commit()
            elif version < SCHEMA_VERSION:
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
