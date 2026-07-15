from __future__ import annotations

import secrets
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator


SCHEMA_VERSION = 4
DISPLAY_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"

LEGACY_SCHEMA_SQL = """
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

DECOUPLED_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS answer_resources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    resource_key TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    display_code TEXT NOT NULL UNIQUE,
    grade TEXT NOT NULL DEFAULT '未分类',
    subject TEXT NOT NULL DEFAULT '未分类',
    textbook_version TEXT,
    chapter TEXT,
    note TEXT,
    current_published_revision_id INTEGER,
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'inactive')),
    row_version INTEGER NOT NULL DEFAULT 1 CHECK (row_version >= 1),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    legacy_binding_id INTEGER UNIQUE,
    FOREIGN KEY (current_published_revision_id)
        REFERENCES answer_revisions(id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS assets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_key TEXT NOT NULL UNIQUE,
    storage_backend TEXT NOT NULL DEFAULT 'local'
        CHECK (storage_backend = 'local'),
    storage_key TEXT NOT NULL UNIQUE,
    original_filename TEXT NOT NULL,
    mime_type TEXT NOT NULL,
    size_bytes INTEGER NOT NULL CHECK (size_bytes > 0),
    sha256 TEXT NOT NULL,
    created_at TEXT NOT NULL,
    legacy_version_id INTEGER UNIQUE
);

CREATE TABLE IF NOT EXISTS answer_revisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    revision_key TEXT NOT NULL UNIQUE,
    resource_id INTEGER NOT NULL,
    revision_number INTEGER NOT NULL CHECK (revision_number >= 1),
    target_type TEXT NOT NULL CHECK (target_type IN ('file', 'external_url')),
    asset_id INTEGER,
    external_url TEXT,
    status TEXT NOT NULL CHECK (status IN ('draft', 'published', 'withdrawn')),
    change_note TEXT,
    created_at TEXT NOT NULL,
    published_at TEXT,
    legacy_version_id INTEGER UNIQUE,
    FOREIGN KEY (resource_id) REFERENCES answer_resources(id) ON DELETE RESTRICT,
    FOREIGN KEY (asset_id) REFERENCES assets(id) ON DELETE RESTRICT,
    UNIQUE (resource_id, revision_number),
    CHECK (
        (target_type = 'file' AND asset_id IS NOT NULL AND external_url IS NULL)
        OR
        (target_type = 'external_url' AND asset_id IS NULL AND external_url IS NOT NULL)
    )
);

CREATE INDEX IF NOT EXISTS idx_answer_revisions_resource
    ON answer_revisions(resource_id, revision_number DESC);

CREATE TABLE IF NOT EXISTS qr_aliases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    public_token TEXT NOT NULL UNIQUE,
    display_code TEXT NOT NULL UNIQUE,
    label TEXT,
    resource_id INTEGER NOT NULL,
    resolve_mode TEXT NOT NULL CHECK (resolve_mode IN ('latest', 'pinned')),
    pinned_revision_id INTEGER,
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'inactive')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    legacy_binding_id INTEGER UNIQUE,
    FOREIGN KEY (resource_id) REFERENCES answer_resources(id) ON DELETE RESTRICT,
    FOREIGN KEY (pinned_revision_id) REFERENCES answer_revisions(id) ON DELETE RESTRICT,
    CHECK (
        (resolve_mode = 'latest' AND pinned_revision_id IS NULL)
        OR
        (resolve_mode = 'pinned' AND pinned_revision_id IS NOT NULL)
    )
);

CREATE INDEX IF NOT EXISTS idx_qr_aliases_resource
    ON qr_aliases(resource_id, resolve_mode);

CREATE TABLE IF NOT EXISTS revision_references (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    revision_id INTEGER NOT NULL,
    reference_type TEXT NOT NULL CHECK (
        reference_type IN ('legacy_fixed_link', 'pdf_job_fixed', 'manual_pin')
    ),
    source_job_id TEXT NOT NULL DEFAULT '',
    legacy_binding_id INTEGER,
    legacy_version_id INTEGER,
    created_at TEXT NOT NULL,
    FOREIGN KEY (revision_id) REFERENCES answer_revisions(id) ON DELETE RESTRICT,
    UNIQUE (revision_id, reference_type, source_job_id)
);

CREATE INDEX IF NOT EXISTS idx_revision_references_revision
    ON revision_references(revision_id);

CREATE TABLE IF NOT EXISTS audit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    resource_id INTEGER,
    revision_id INTEGER,
    qr_alias_id INTEGER,
    actor TEXT NOT NULL,
    summary TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (resource_id) REFERENCES answer_resources(id) ON DELETE RESTRICT,
    FOREIGN KEY (revision_id) REFERENCES answer_revisions(id) ON DELETE SET NULL,
    FOREIGN KEY (qr_alias_id) REFERENCES qr_aliases(id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_audit_events_resource
    ON audit_events(resource_id, created_at DESC);

CREATE TABLE IF NOT EXISTS pdf_jobs_v2 (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL UNIQUE,
    resource_id INTEGER NOT NULL,
    qr_mode TEXT NOT NULL DEFAULT 'dynamic'
        CHECK (qr_mode IN ('dynamic', 'fixed')),
    qr_revision_id INTEGER,
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
    legacy_job_id INTEGER UNIQUE,
    FOREIGN KEY (resource_id) REFERENCES answer_resources(id) ON DELETE RESTRICT,
    FOREIGN KEY (qr_revision_id) REFERENCES answer_revisions(id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_pdf_jobs_v2_resource
    ON pdf_jobs_v2(resource_id, created_at DESC);
"""

PREVIEW_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS preview_sets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    preview_key TEXT NOT NULL UNIQUE,
    revision_id INTEGER NOT NULL,
    source_asset_id INTEGER NOT NULL,
    source_sha256 TEXT NOT NULL,
    renderer_version TEXT NOT NULL,
    render_config_hash TEXT NOT NULL,
    status TEXT NOT NULL CHECK (
        status IN ('pending', 'processing', 'completed', 'failed', 'superseded')
    ),
    page_count INTEGER NOT NULL DEFAULT 0 CHECK (page_count >= 0),
    total_size_bytes INTEGER NOT NULL DEFAULT 0 CHECK (total_size_bytes >= 0),
    created_at TEXT NOT NULL,
    completed_at TEXT,
    error_code TEXT,
    error_message TEXT,
    FOREIGN KEY (revision_id) REFERENCES answer_revisions(id) ON DELETE RESTRICT,
    FOREIGN KEY (source_asset_id) REFERENCES assets(id) ON DELETE RESTRICT,
    CHECK (status != 'completed' OR page_count > 0),
    CHECK (status != 'completed' OR completed_at IS NOT NULL)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_preview_sets_completed_config
    ON preview_sets(revision_id, renderer_version, render_config_hash)
    WHERE status = 'completed';

CREATE INDEX IF NOT EXISTS idx_preview_sets_revision_status
    ON preview_sets(revision_id, status, created_at DESC);

CREATE TABLE IF NOT EXISTS preview_pages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    preview_set_id INTEGER NOT NULL,
    page_number INTEGER NOT NULL CHECK (page_number >= 1),
    storage_backend TEXT NOT NULL DEFAULT 'local' CHECK (storage_backend = 'local'),
    storage_key TEXT NOT NULL UNIQUE,
    mime_type TEXT NOT NULL CHECK (mime_type = 'image/webp'),
    width INTEGER NOT NULL CHECK (width > 0),
    height INTEGER NOT NULL CHECK (height > 0),
    size_bytes INTEGER NOT NULL CHECK (size_bytes > 0),
    sha256 TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (preview_set_id) REFERENCES preview_sets(id) ON DELETE RESTRICT,
    UNIQUE (preview_set_id, page_number)
);

CREATE INDEX IF NOT EXISTS idx_preview_pages_set_number
    ON preview_pages(preview_set_id, page_number);

CREATE TABLE IF NOT EXISTS preview_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_key TEXT NOT NULL UNIQUE,
    revision_id INTEGER NOT NULL,
    preview_set_id INTEGER,
    renderer_version TEXT NOT NULL,
    render_config_hash TEXT NOT NULL,
    status TEXT NOT NULL CHECK (
        status IN ('pending', 'processing', 'completed', 'failed', 'cancelled')
    ),
    total_pages INTEGER,
    rendered_pages INTEGER NOT NULL DEFAULT 0 CHECK (rendered_pages >= 0),
    attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    max_attempts INTEGER NOT NULL DEFAULT 2 CHECK (max_attempts >= 1),
    claimed_at TEXT,
    worker_id TEXT,
    error_code TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT,
    FOREIGN KEY (revision_id) REFERENCES answer_revisions(id) ON DELETE RESTRICT,
    FOREIGN KEY (preview_set_id) REFERENCES preview_sets(id) ON DELETE SET NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_preview_jobs_active_config
    ON preview_jobs(revision_id, renderer_version, render_config_hash)
    WHERE status IN ('pending', 'processing');

CREATE INDEX IF NOT EXISTS idx_preview_jobs_status_created
    ON preview_jobs(status, created_at);
"""

SCHEMA_SQL = LEGACY_SCHEMA_SQL + DECOUPLED_SCHEMA_SQL + PREVIEW_SCHEMA_SQL


def new_display_code() -> str:
    raw = "".join(secrets.choice(DISPLAY_CODE_ALPHABET) for _ in range(8))
    return f"QR-{raw[:4]}-{raw[4:]}"


def new_public_key() -> str:
    return uuid.uuid4().hex


class Database:
    def __init__(self, path: Path, busy_timeout_ms: int = 5000) -> None:
        self.path = path
        self.busy_timeout_ms = busy_timeout_ms
        self.last_backup_path: Path | None = None

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=self.busy_timeout_ms / 1000)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute(f"PRAGMA busy_timeout = {self.busy_timeout_ms}")
        return connection

    def _backup(self, stage: str, version: int) -> Path:
        backup_dir = self.path.parent / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup_path = backup_dir / f"app-before-{stage}-v{version}-{stamp}.db"
        suffix = 1
        while backup_path.exists():
            backup_path = backup_dir / (
                f"app-before-{stage}-v{version}-{stamp}-{suffix}.db"
            )
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
    def _unique_display_code(
        connection: sqlite3.Connection, table: str = "bindings"
    ) -> str:
        if table not in {"bindings", "answer_resources", "qr_aliases"}:
            raise ValueError("unsupported display-code table")
        for _ in range(100):
            code = new_display_code()
            found = connection.execute(
                f"SELECT 1 FROM {table} WHERE display_code = ?", (code,)
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
        connection.execute("PRAGMA user_version = 2")

    @staticmethod
    def _mapped_reference_type(value: str) -> str:
        if value in {"pdf_job", "pdf_job_fixed"}:
            return "pdf_job_fixed"
        if value in {"manual_pin"}:
            return "manual_pin"
        return "legacy_fixed_link"

    def _migrate_v2_to_v3(self, connection: sqlite3.Connection) -> None:
        for statement in DECOUPLED_SCHEMA_SQL.split(";"):
            if statement.strip():
                connection.execute(statement)
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

        bindings = connection.execute(
            "SELECT * FROM bindings ORDER BY id"
        ).fetchall()
        for binding in bindings:
            resource_key = new_public_key()
            connection.execute(
                """
                INSERT INTO answer_resources
                    (id, resource_key, name, display_code, grade, subject,
                     textbook_version, chapter, note,
                     current_published_revision_id, status, row_version,
                     created_at, updated_at, legacy_binding_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, 1, ?, ?, ?)
                """,
                (
                    binding["id"], resource_key, binding["title"],
                    binding["display_code"], binding["grade"], binding["subject"],
                    binding["textbook_version"], binding["chapter"], binding["note"],
                    "active" if binding["is_active"] else "inactive",
                    binding["created_at"], binding["updated_at"], binding["id"],
                ),
            )

            versions = connection.execute(
                "SELECT * FROM file_versions WHERE binding_id = ? ORDER BY id",
                (binding["id"],),
            ).fetchall()
            for version in versions:
                connection.execute(
                    """
                    INSERT INTO assets
                        (id, asset_key, storage_backend, storage_key,
                         original_filename, mime_type, size_bytes, sha256,
                         created_at, legacy_version_id)
                    VALUES (?, ?, 'local', ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        version["id"], new_public_key(), version["storage_path"],
                        version["original_filename"], version["mime_type"],
                        version["size_bytes"], version["sha256"],
                        version["created_at"], version["id"],
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO answer_revisions
                        (id, revision_key, resource_id, revision_number,
                         target_type, asset_id, external_url, status, change_note,
                         created_at, published_at, legacy_version_id)
                    VALUES (?, ?, ?, ?, 'file', ?, NULL, 'published', ?, ?, ?, ?)
                    """,
                    (
                        version["id"], new_public_key(), binding["id"],
                        version["version_number"], version["id"], version["note"],
                        version["created_at"], version["created_at"], version["id"],
                    ),
                )

            if binding["current_version_id"] is not None:
                connection.execute(
                    """
                    UPDATE answer_resources
                    SET current_published_revision_id = ?
                    WHERE id = ?
                    """,
                    (binding["current_version_id"], binding["id"]),
                )

            alias_cursor = connection.execute(
                """
                INSERT INTO qr_aliases
                    (id, public_token, display_code, label, resource_id,
                     resolve_mode, pinned_revision_id, status,
                     created_at, updated_at, legacy_binding_id)
                VALUES (?, ?, ?, ?, ?, 'latest', NULL, ?, ?, ?, ?)
                """,
                (
                    binding["id"], binding["qr_id"], binding["display_code"],
                    binding["title"], binding["id"],
                    "active" if binding["is_active"] else "inactive",
                    binding["created_at"], binding["updated_at"], binding["id"],
                ),
            )
            connection.execute(
                """
                INSERT INTO audit_events
                    (event_type, resource_id, revision_id, qr_alias_id,
                     actor, summary, created_at)
                VALUES ('migration_stage04a', ?, ?, ?, 'system', ?, ?)
                """,
                (
                    binding["id"], binding["current_version_id"],
                    int(alias_cursor.lastrowid),
                    f"从 legacy binding {binding['id']} 迁移", now,
                ),
            )

        references = connection.execute(
            "SELECT * FROM version_references ORDER BY id"
        ).fetchall()
        for reference in references:
            revision = connection.execute(
                "SELECT resource_id FROM answer_revisions WHERE id = ?",
                (reference["version_id"],),
            ).fetchone()
            connection.execute(
                """
                INSERT INTO revision_references
                    (revision_id, reference_type, source_job_id,
                     legacy_binding_id, legacy_version_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    reference["version_id"],
                    self._mapped_reference_type(reference["reference_type"]),
                    reference["source_job_id"], revision["resource_id"],
                    reference["version_id"], reference["created_at"],
                ),
            )

        jobs = connection.execute("SELECT * FROM pdf_jobs ORDER BY id").fetchall()
        for job in jobs:
            connection.execute(
                """
                INSERT INTO pdf_jobs_v2
                    (id, job_id, resource_id, qr_mode, qr_revision_id,
                     source_original_filename, source_storage_path,
                     output_storage_path, page_number, position, size_mm,
                     margin_mm, status, error_code, error_message, created_at,
                     completed_at, output_size_bytes, output_sha256, legacy_job_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job["id"], job["job_id"], job["binding_id"], job["qr_mode"],
                    job["qr_version_id"], job["source_original_filename"],
                    job["source_storage_path"], job["output_storage_path"],
                    job["page_number"], job["position"], job["size_mm"],
                    job["margin_mm"], job["status"], job["error_code"],
                    job["error_message"], job["created_at"], job["completed_at"],
                    job["output_size_bytes"], job["output_sha256"], job["id"],
                ),
            )

        connection.execute("PRAGMA user_version = 3")

    @staticmethod
    def _migrate_v3_to_v4(connection: sqlite3.Connection) -> None:
        for statement in PREVIEW_SCHEMA_SQL.split(";"):
            if statement.strip():
                connection.execute(statement)
        connection.execute("PRAGMA user_version = 4")

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
            self._backup("stage03", version)
            with self.connect() as connection:
                try:
                    connection.execute("BEGIN IMMEDIATE")
                    self._migrate_v1_to_v2(connection)
                    connection.commit()
                except Exception:
                    connection.rollback()
                    raise
            version = 2

        if version == 2:
            self._backup("stage04a", version)
            with self.connect() as connection:
                try:
                    connection.execute("BEGIN IMMEDIATE")
                    self._migrate_v2_to_v3(connection)
                    connection.commit()
                except Exception:
                    connection.rollback()
                    raise
            version = 3

        if version == 3:
            self._backup("stage05a", version)
            with self.connect() as connection:
                try:
                    connection.execute("BEGIN IMMEDIATE")
                    self._migrate_v3_to_v4(connection)
                    connection.commit()
                except Exception:
                    connection.rollback()
                    raise
            version = 4

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
