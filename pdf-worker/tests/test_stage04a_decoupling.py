import hashlib
import importlib.util
import inspect
import sqlite3
from pathlib import Path

import pytest

from app.database import Database, LEGACY_SCHEMA_SQL
from app.services.binding_service import BindingService
from app.services.pdf_service import PdfService
from conftest import create_binding


def load_migration_validator():
    script = Path(__file__).parents[1] / "scripts" / "validate_stage04a_migration.py"
    spec = importlib.util.spec_from_file_location("stage04a_validator", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def create_v2_database(path, storage_root):
    stored = storage_root / "bindings" / "old-qr" / "answer.bin"
    stored.parent.mkdir(parents=True)
    stored.write_bytes(b"stage04a-preserved")
    digest = hashlib.sha256(stored.read_bytes()).hexdigest()
    connection = sqlite3.connect(path)
    connection.executescript(LEGACY_SCHEMA_SQL)
    connection.execute(
        """
        INSERT INTO bindings
            (id, qr_id, current_version_id, title, display_code, grade, subject,
             textbook_version, chapter, created_at, updated_at, note, is_active)
        VALUES (7, 'old-qr', NULL, '旧答案', 'QR-OLD4-0001', '高一', '数学',
                '人教版', '第一章', '2026-01-01Z', '2026-01-02Z', '旧备注', 1)
        """
    )
    connection.execute(
        """
        INSERT INTO file_versions
            (id, binding_id, version_number, original_filename, stored_filename,
             storage_path, mime_type, size_bytes, sha256, created_at, note,
             storage_backend)
        VALUES (11, 7, 1, '旧答案.txt', 'answer.bin',
                'bindings/old-qr/answer.bin', 'text/plain', ?, ?,
                '2026-01-01Z', '第一版', 'local')
        """,
        (stored.stat().st_size, digest),
    )
    connection.execute("UPDATE bindings SET current_version_id = 11 WHERE id = 7")
    connection.execute(
        """
        INSERT INTO version_references
            (version_id, reference_type, source_job_id, created_at)
        VALUES (11, 'qr_download', '', '2026-01-03Z')
        """
    )
    connection.execute(
        """
        INSERT INTO pdf_jobs
            (id, job_id, binding_id, qr_mode, qr_version_id,
             source_original_filename, source_storage_path, output_storage_path,
             page_number, position, size_mm, margin_mm, status, created_at,
             completed_at, output_size_bytes, output_sha256)
        VALUES (13, 'old-job', 7, 'fixed', 11, '练习.pdf',
                'source-pdfs/old.pdf', 'generated-pdfs/old.pdf', 1,
                'bottom-right', 20, 10, 'completed', '2026-01-03Z',
                '2026-01-03Z', 20, 'jobhash')
        """
    )
    connection.execute("PRAGMA user_version = 2")
    connection.commit()
    connection.close()
    return digest, stored.stat().st_size


def test_stage04a_migration_preserves_identity_content_and_references(tmp_path):
    path = tmp_path / "db" / "app.db"
    path.parent.mkdir(parents=True)
    digest, size = create_v2_database(path, tmp_path / "storage")
    database = Database(path)
    database.initialize()
    assert database.last_backup_path and database.last_backup_path.is_file()
    stage04_backup_path = next(
        item for item in (path.parent / "backups").iterdir() if "stage04a-v2" in item.name
    )
    backup = sqlite3.connect(stage04_backup_path)
    assert backup.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert backup.execute("PRAGMA user_version").fetchone()[0] == 2
    backup.close()
    stage05_backup = sqlite3.connect(database.last_backup_path)
    assert stage05_backup.execute("PRAGMA user_version").fetchone()[0] == 3
    stage05_backup.close()

    with database.read() as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 4
        resource = connection.execute("SELECT * FROM answer_resources").fetchone()
        revision = connection.execute("SELECT * FROM answer_revisions").fetchone()
        asset = connection.execute("SELECT * FROM assets").fetchone()
        alias = connection.execute("SELECT * FROM qr_aliases").fetchone()
        reference = connection.execute("SELECT * FROM revision_references").fetchone()
        job = connection.execute("SELECT * FROM pdf_jobs_v2").fetchone()
        assert resource["id"] == resource["legacy_binding_id"] == 7
        assert resource["current_published_revision_id"] == 11
        assert len(resource["resource_key"]) == 32
        assert revision["id"] == revision["legacy_version_id"] == 11
        assert revision["status"] == "published"
        assert revision["target_type"] == "file"
        assert asset["size_bytes"] == size
        assert asset["sha256"] == digest
        assert asset["storage_key"] == "bindings/old-qr/answer.bin"
        assert alias["public_token"] == "old-qr"
        assert alias["resolve_mode"] == "latest"
        assert reference["revision_id"] == 11
        assert reference["reference_type"] == "legacy_fixed_link"
        assert job["job_id"] == "old-job"
        assert job["resource_id"] == 7
        assert job["qr_revision_id"] == 11
        assert connection.execute("SELECT COUNT(*) FROM bindings").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM file_versions").fetchone()[0] == 1

    backups = list((path.parent / "backups").iterdir())
    Database(path).initialize()
    assert list((path.parent / "backups").iterdir()) == backups

    validator = load_migration_validator()
    result = validator.validate(path, tmp_path / "storage")
    assert result["status"] == "PASS"
    assert result["counts"]["legacy_bindings"] == 1
    assert result["counts"]["answer_revisions"] == 1
    assert not any(result["mismatches"].values())


def test_stage04a_validator_detects_changed_content(tmp_path):
    path = tmp_path / "db" / "app.db"
    path.parent.mkdir(parents=True)
    create_v2_database(path, tmp_path / "storage")
    Database(path).initialize()
    stored = tmp_path / "storage" / "bindings" / "old-qr" / "answer.bin"
    stored.write_bytes(b"changed-after-migration")

    result = load_migration_validator().validate(path, tmp_path / "storage")
    assert result["status"] == "FAIL"
    assert result["mismatches"]["sha256"] == 1
    assert result["mismatches"]["size_bytes"] == 1


def test_failed_stage04a_migration_rolls_back_without_clearing_legacy_data(tmp_path):
    path = tmp_path / "db" / "app.db"
    path.parent.mkdir(parents=True)
    create_v2_database(path, tmp_path / "storage")

    class FailingDatabase(Database):
        def _migrate_v2_to_v3(self, connection):
            super()._migrate_v2_to_v3(connection)
            raise RuntimeError("injected migration failure")

    with pytest.raises(RuntimeError, match="injected migration failure"):
        FailingDatabase(path).initialize()
    connection = sqlite3.connect(path)
    assert connection.execute("PRAGMA user_version").fetchone()[0] == 2
    assert connection.execute("SELECT COUNT(*) FROM bindings").fetchone()[0] == 1
    assert connection.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='answer_resources'"
    ).fetchone()[0] == 0
    connection.close()


def test_new_compatibility_writes_use_only_decoupled_business_tables(client):
    binding = create_binding(client, b"new-content", "new.txt")
    with client.app.state.database.read() as connection:
        assert connection.execute("SELECT COUNT(*) FROM answer_resources").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM answer_revisions").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM assets").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM qr_aliases").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM bindings").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM file_versions").fetchone()[0] == 0
        alias = connection.execute("SELECT public_token FROM qr_aliases").fetchone()
        assert alias["public_token"] == binding["qr_id"]


def test_revision_cleanup_preserves_audit_history(client):
    binding = create_binding(client, b"v1")
    first_revision_id = binding["current_version"]["version_id"]
    for number in range(2, 8):
        response = client.put(
            f"/bindings/{binding['qr_id']}/file",
            files={
                "file": (
                    f"v{number}.txt",
                    f"v{number}".encode(),
                    "text/plain",
                )
            },
        )
        assert response.status_code == 200

    with client.app.state.database.read() as connection:
        assert connection.execute(
            "SELECT 1 FROM answer_revisions WHERE id = ?", (first_revision_id,)
        ).fetchone() is None
        event = connection.execute(
            "SELECT revision_id FROM audit_events WHERE event_type = 'create_resource'"
        ).fetchone()
        assert event is not None
        assert event["revision_id"] is None


def test_cross_resource_current_and_pin_are_rejected_by_services(client):
    first = create_binding(client, b"first")
    second = create_binding(client, b"second")
    first_resolved = client.app.state.resolver_service.resolve_latest(first["qr_id"])
    second_resolved = client.app.state.resolver_service.resolve_latest(second["qr_id"])
    with pytest.raises(Exception) as switch_error:
        client.app.state.revision_service.switch_current(
            first_resolved.resource["id"], second_resolved.revision["id"]
        )
    assert getattr(switch_error.value, "status_code", None) == 404
    with pytest.raises(Exception) as pin_error:
        client.app.state.revision_service.pin(
            first_resolved.resource["id"],
            second_resolved.revision["id"],
            "manual_pin",
        )
    assert getattr(pin_error.value, "status_code", None) == 404


def test_resolver_is_structured_and_storage_path_stays_out_of_binding_response(client):
    binding = create_binding(client, b"resolved")
    resolved = client.app.state.resolver_service.resolve_latest(binding["qr_id"])
    assert resolved.alias["public_token"] == binding["qr_id"]
    assert resolved.resource["current_published_revision_id"] == resolved.revision["id"]
    assert resolved.asset["sha256"] == binding["sha256"]
    assert "storage_path" not in binding
    assert "storage_key" not in binding


def test_compatibility_services_do_not_query_legacy_business_tables():
    binding_source = inspect.getsource(BindingService)
    pdf_source = inspect.getsource(PdfService)
    forbidden = ("FROM bindings", "FROM file_versions", "INTO bindings", "INTO file_versions")
    assert not any(token in binding_source for token in forbidden)
    assert not any(token in pdf_source for token in forbidden)
