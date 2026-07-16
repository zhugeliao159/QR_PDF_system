from __future__ import annotations

import hashlib
import shutil
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.database import new_public_key
from app.main import create_app
from app.scripts.audit_public_original_access import audit_client, public_get_routes
from app.services.backup_service import (
    database_counts,
    validate_snapshot,
    verify_manifest,
    write_manifest,
)
from app.services.cleanup_service import CleanupService
from conftest import create_binding, csrf_from, pdf_bytes, png_bytes, prepare_preview


STUDENT_HEADERS = {
    "cache-control": "private, no-store, max-age=0",
    "pragma": "no-cache",
    "x-content-type-options": "nosniff",
    "referrer-policy": "no-referrer",
    "x-frame-options": "DENY",
    "permissions-policy": "camera=(), microphone=(), geolocation=()",
    "cross-origin-resource-policy": "same-origin",
}


def target_for(client, token: str) -> dict:
    resolved = client.app.state.resolver_service.resolve_latest(token)
    return {
        "public_token": token,
        "revision_key": resolved.revision["revision_key"],
        "asset_key": resolved.asset["asset_key"],
        "storage_key": resolved.asset["storage_key"],
        "sha256": resolved.asset["sha256"],
        "mime_type": resolved.asset["mime_type"],
        "size_bytes": resolved.asset["size_bytes"],
    }


def cleanup_service(client) -> CleanupService:
    return CleanupService(
        client.app.state.settings,
        client.app.state.database,
        client.app.state.storage,
        client.app.state.preview_service,
    )


def assert_student_headers(response, html: bool = False):
    for name, value in STUDENT_HEADERS.items():
        assert response.headers[name] == value
    if html:
        csp = response.headers["content-security-policy"]
        for directive in (
            "default-src 'self'", "img-src 'self' blob:", "font-src 'self'",
            "object-src 'none'", "frame-src 'none'", "frame-ancestors 'none'",
            "base-uri 'none'", "form-action 'self'",
        ):
            assert directive in csp
        assert "unsafe-eval" not in csp and "unsafe-inline" not in csp


def test_public_get_route_inventory_excludes_management(client):
    routes = public_get_routes(client.app)
    assert "/q/{public_token}" in routes
    assert "/q/{public_token}/manifest" in routes
    assert "/q/{public_token}/pages/{page_number}" in routes
    assert "/health" in routes
    assert not any(path.startswith(("/admin", "/bindings", "/pdf/jobs")) for path in routes)


@pytest.mark.parametrize(
    ("filename", "mime_type", "content"),
    [
        ("中文原件.pdf", "application/pdf", pdf_bytes()),
        ("中文原图.png", "image/png", png_bytes("purple")),
    ],
)
def test_public_original_access_audit_for_pdf_and_image(client, settings, filename, mime_type, content):
    response = client.post("/bindings", files={"file": (filename, content, mime_type)})
    assert response.status_code == 201, response.text
    token = response.json()["qr_id"]
    prepare_preview(client, token)
    client.cookies.clear()
    ok, lines = audit_client(client, target_for(client, token), str(settings.storage_root))
    assert ok, lines


def test_all_student_success_and_error_responses_have_security_headers(client):
    binding = create_binding(client, pdf_bytes(), "安全头.pdf")
    prepare_preview(client, binding["qr_id"])
    entry = client.get(f"/q/{binding['qr_id']}")
    manifest = client.get(f"/q/{binding['qr_id']}/manifest")
    page = client.get(f"/q/{binding['qr_id']}/pages/1")
    missing = client.get("/q/not-found")
    for response, html in ((entry, True), (manifest, False), (page, False), (missing, True)):
        assert_student_headers(response, html)


def test_concurrent_viewer_audit_writes_do_not_leak_sqlite_lock_errors(client):
    binding = create_binding(client, pdf_bytes(), "viewer-write-contention.pdf")
    resolved = prepare_preview(client, binding["qr_id"])
    service = client.app.state.viewer_session_service
    tokens = [service.create(resolved, "stage05d-load", "127.0.0.1")[0] for _ in range(40)]
    client.app.state.database.busy_timeout_ms = 1

    with ThreadPoolExecutor(max_workers=40) as executor:
        sessions = list(
            executor.map(lambda token: service.validate(binding["qr_id"], token), tokens)
        )

    assert len(sessions) == 40
    assert len({session["id"] for session in sessions}) == 40


def test_static_student_assets_have_resource_security_headers(client):
    for path in ("/static/css/student.css", "/static/js/student.js"):
        response = client.get(path)
        assert response.status_code == 200
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["referrer-policy"] == "no-referrer"
        assert response.headers["cross-origin-resource-policy"] == "same-origin"


def test_internal_student_error_is_chinese_and_redacted(settings, monkeypatch):
    with TestClient(create_app(settings), raise_server_exceptions=False) as client:
        binding = create_binding(client, pdf_bytes(), "内部错误.pdf")
        prepare_preview(client, binding["qr_id"])
        client.get(f"/q/{binding['qr_id']}")
        monkeypatch.setattr(
            client.app.state.watermark_service,
            "render",
            lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("/secret/storage_key SQL")),
        )
        response = client.get(f"/q/{binding['qr_id']}/pages/1")
        assert response.status_code == 500
        assert "系统处理失败" in response.text
        assert "storage_key" not in response.text and "Traceback" not in response.text
        assert_student_headers(response, True)


def test_cleanup_dry_run_does_not_modify_data(client):
    binding = create_binding(client, pdf_bytes(), "dry-run.pdf")
    prepare_preview(client, binding["qr_id"])
    service = cleanup_service(client)
    with client.app.state.database.read() as connection:
        before = tuple(connection.execute(
            "SELECT (SELECT COUNT(*) FROM assets), (SELECT COUNT(*) FROM preview_sets), (SELECT COUNT(*) FROM viewer_sessions)"
        ).fetchone())
    files_before = sorted(path.relative_to(client.app.state.settings.storage_root) for path in client.app.state.settings.storage_root.rglob("*") if path.is_file())
    plan = service.plan()
    assert plan.skipped["current_revision_assets"] == 1
    with client.app.state.database.read() as connection:
        after = tuple(connection.execute(
            "SELECT (SELECT COUNT(*) FROM assets), (SELECT COUNT(*) FROM preview_sets), (SELECT COUNT(*) FROM viewer_sessions)"
        ).fetchone())
    files_after = sorted(path.relative_to(client.app.state.settings.storage_root) for path in client.app.state.settings.storage_root.rglob("*") if path.is_file())
    assert before == after and files_before == files_after


def test_current_pinned_and_active_draft_assets_are_protected(admin_client):
    binding = create_binding(admin_client, pdf_bytes(), "保护.pdf")
    token = binding["qr_id"]
    current = prepare_preview(admin_client, token)
    admin_client.app.state.binding_service.fixed_alias_token(token, current.revision["id"])
    page = admin_client.get(f"/admin/materials/{token}/replace")
    created = admin_client.post(
        f"/admin/materials/{token}/replace",
        data={"csrf_token": csrf_from(page), "content_type": "pdf"},
        files={"file": ("草稿.pdf", pdf_bytes(pages=2), "application/pdf")},
        follow_redirects=False,
    )
    assert created.status_code == 303
    service = cleanup_service(admin_client)
    plan = service.plan()
    assert plan.skipped["current_revision_assets"] == 1
    assert plan.skipped["pinned_or_fixed_revisions"] >= 1
    assert plan.skipped["active_draft_assets"] == 1
    service.apply()
    with admin_client.app.state.database.read() as connection:
        assert connection.execute("SELECT COUNT(*) FROM assets").fetchone()[0] == 2
        assert connection.execute("SELECT COUNT(*) FROM answer_revisions WHERE status='draft'").fetchone()[0] == 1


def test_orphan_asset_can_be_cleaned_and_apply_is_idempotent(client, settings):
    path = settings.bindings_dir / "orphan" / "unused.bin"
    path.parent.mkdir(parents=True, exist_ok=True)
    content = b"orphan-stage05d"
    path.write_bytes(content)
    with client.app.state.database.transaction() as connection:
        asset_id = int(connection.execute(
            """
            INSERT INTO assets (asset_key, storage_backend, storage_key, original_filename,
                                mime_type, size_bytes, sha256, created_at)
            VALUES (?, 'local', ?, 'unused.bin', 'application/octet-stream', ?, ?, ?)
            """,
            (
                new_public_key(), path.relative_to(settings.storage_root).as_posix(), len(content),
                hashlib.sha256(content).hexdigest(), datetime.now(timezone.utc).isoformat(),
            ),
        ).lastrowid)
    service = cleanup_service(client)
    assert any(item.category == "orphan_asset" and item.object_id == str(asset_id) for item in service.plan().items)
    assert service.apply()["orphan_asset"] == 1
    assert not path.exists()
    assert service.apply() == {}


def test_superseded_preview_set_can_be_cleaned_without_current_preview(client):
    binding = create_binding(client, pdf_bytes(), "superseded.pdf")
    resolved = prepare_preview(client, binding["qr_id"])
    client.app.state.preview_service.request_preview(resolved.revision["id"], force=True)
    client.app.state.preview_service.process_until_idle("stage05d-force")
    service = cleanup_service(client)
    assert service.plan().counts()["superseded_preview_set"] == 1
    assert service.apply()["superseded_preview_set"] == 1
    with client.app.state.database.read() as connection:
        assert connection.execute("SELECT COUNT(*) FROM preview_sets WHERE status='completed'").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM preview_sets WHERE status='superseded'").fetchone()[0] == 0
    assert client.get(f"/q/{binding['qr_id']}").status_code == 200


def test_expired_session_events_and_watermark_cache_can_be_cleaned(client, settings):
    binding = create_binding(client, pdf_bytes(), "expired.pdf")
    prepare_preview(client, binding["qr_id"])
    client.get(f"/q/{binding['qr_id']}")
    old = (datetime.now(timezone.utc) - timedelta(days=31)).isoformat()
    with client.app.state.database.transaction() as connection:
        connection.execute("UPDATE viewer_sessions SET status='expired', last_seen_at=?, expires_at=?", (old, old))
        connection.execute("UPDATE viewer_access_events SET created_at=?", (old,))
    cache = settings.storage_root / "cache" / "watermarked" / "expired-session"
    cache.mkdir(parents=True)
    (cache / "page-1.webp").write_bytes(b"expired")
    applied = cleanup_service(client).apply()
    assert applied["expired_viewer_access_event"] == 1
    assert applied["expired_viewer_session"] == 1
    assert applied["expired_watermark_cache"] == 1
    assert not cache.exists()


def test_stale_processing_job_recovers_without_duplicates_or_asset_change(client, settings):
    binding = create_binding(client, pdf_bytes(pages=3), "worker-recovery.pdf")
    token = binding["qr_id"]
    resolved = client.app.state.resolver_service.resolve_latest(token)
    source_path = client.app.state.storage.resolve(resolved.asset["storage_key"])
    before = hashlib.sha256(source_path.read_bytes()).hexdigest()
    request = client.app.state.preview_service.request_preview(resolved.revision["id"])
    claimed = client.app.state.preview_service._claim_next("interrupted-worker")
    assert claimed and claimed["id"] == request.job_id
    temp = settings.previews_dir / f".tmp-{claimed['job_key']}"
    temp.mkdir()
    (temp / "partial.webp").write_bytes(b"partial")
    stale = (datetime.now(timezone.utc) - timedelta(seconds=settings.preview_job_stale_seconds + 1)).isoformat()
    with client.app.state.database.transaction() as connection:
        connection.execute("UPDATE preview_jobs SET claimed_at=? WHERE id=?", (stale, claimed["id"]))
    applied = cleanup_service(client).apply()
    assert applied["stale_processing_job"] == 1
    assert not temp.exists()
    client.app.state.preview_service.process_until_idle("recovery-worker")
    with client.app.state.database.read() as connection:
        assert connection.execute("SELECT COUNT(*) FROM preview_sets WHERE revision_id=? AND status='completed'", (resolved.revision["id"],)).fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM preview_pages p JOIN preview_sets s ON s.id=p.preview_set_id WHERE s.revision_id=?", (resolved.revision["id"],)).fetchone()[0] == 3
    assert hashlib.sha256(source_path.read_bytes()).hexdigest() == before


def test_backup_manifest_and_restored_snapshot_match_counts_and_hashes(client, settings, tmp_path):
    binding = create_binding(client, pdf_bytes(pages=2), "备份恢复.pdf")
    prepare_preview(client, binding["qr_id"])
    client.app.state.binding_service.fixed_alias_token(
        binding["qr_id"], binding["current_version"]["version_id"]
    )
    snapshot = tmp_path / "snapshot"
    (snapshot / "db").mkdir(parents=True)
    source = sqlite3.connect(settings.database_path)
    destination = sqlite3.connect(snapshot / "db" / "app.db")
    source.backup(destination)
    destination.close()
    source.close()
    shutil.copytree(settings.storage_root, snapshot / "storage")
    expected = database_counts(snapshot / "db" / "app.db")
    write_manifest(snapshot)
    verify_manifest(snapshot)
    restored = tmp_path / "restored"
    shutil.copytree(snapshot, restored)
    verify_manifest(restored)
    assert validate_snapshot(restored, expected) == expected
