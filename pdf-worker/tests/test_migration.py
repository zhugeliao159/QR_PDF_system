import sqlite3

from app.database import Database


def create_v1_database(path):
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE bindings (id INTEGER PRIMARY KEY AUTOINCREMENT, qr_id TEXT NOT NULL UNIQUE,
          current_version_id INTEGER, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
          note TEXT, is_active INTEGER NOT NULL DEFAULT 1);
        CREATE TABLE file_versions (id INTEGER PRIMARY KEY AUTOINCREMENT, binding_id INTEGER NOT NULL,
          version_number INTEGER NOT NULL, original_filename TEXT NOT NULL, stored_filename TEXT NOT NULL,
          storage_path TEXT NOT NULL UNIQUE, mime_type TEXT NOT NULL, size_bytes INTEGER NOT NULL,
          sha256 TEXT NOT NULL, created_at TEXT NOT NULL, note TEXT, storage_backend TEXT NOT NULL);
        CREATE TABLE pdf_jobs (id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL UNIQUE,
          binding_id INTEGER NOT NULL, source_original_filename TEXT NOT NULL,
          source_storage_path TEXT NOT NULL UNIQUE, output_storage_path TEXT UNIQUE,
          page_number INTEGER NOT NULL, position TEXT NOT NULL, size_mm REAL NOT NULL,
          margin_mm REAL NOT NULL, status TEXT NOT NULL, error_code TEXT, error_message TEXT,
          created_at TEXT NOT NULL, completed_at TEXT, output_size_bytes INTEGER, output_sha256 TEXT);
        INSERT INTO bindings(qr_id,current_version_id,created_at,updated_at,note,is_active)
          VALUES('old-qr',NULL,'2026-01-01Z','2026-01-01Z',NULL,1);
        INSERT INTO file_versions(binding_id,version_number,original_filename,stored_filename,
          storage_path,mime_type,size_bytes,sha256,created_at,note,storage_backend)
          VALUES(1,1,'旧资料.pdf','safe.bin','bindings/old/safe.bin','application/pdf',10,
          'abc','2026-01-01Z',NULL,'local');
        UPDATE bindings SET current_version_id=1 WHERE id=1;
        INSERT INTO pdf_jobs(job_id,binding_id,source_original_filename,source_storage_path,
          page_number,position,size_mm,margin_mm,status,created_at)
          VALUES('old-job',1,'book.pdf','source-pdfs/old.pdf',1,'bottom-right',20,10,'completed','2026-01-01Z');
        PRAGMA user_version=1;
        """
    )
    connection.commit()
    connection.close()


def test_v1_migration_preserves_data_and_is_idempotent(tmp_path):
    path = tmp_path / "app.db"
    create_v1_database(path)
    database = Database(path)
    database.initialize()
    assert database.last_backup_path and database.last_backup_path.is_file()
    with database.read() as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 4
        binding = connection.execute("SELECT * FROM bindings").fetchone()
        assert binding["title"] == "旧资料"
        assert binding["display_code"].startswith("QR-")
        assert binding["grade"] == "未分类"
        assert connection.execute("SELECT COUNT(*) FROM file_versions").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM pdf_jobs").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM answer_resources").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM answer_revisions").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM assets").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM qr_aliases").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM pdf_jobs_v2").fetchone()[0] == 1
    backups_before = list((tmp_path / "backups").iterdir())
    assert any("stage03-v1" in path.name for path in backups_before)
    assert any("stage04a-v2" in path.name for path in backups_before)
    assert any("stage05a-v3" in path.name for path in backups_before)
    Database(path).initialize()
    assert list((tmp_path / "backups").iterdir()) == backups_before
