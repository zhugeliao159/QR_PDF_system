from __future__ import annotations

import hashlib
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from io import BytesIO

from fastapi.testclient import TestClient
from PIL import Image

from app.main import create_app
from conftest import create_binding, csrf_from, login_admin, pdf_bytes, prepare_preview


def protected_pdf(client, pages: int = 1):
    binding = create_binding(client, pdf_bytes(pages=pages), "会话测试.pdf")
    prepare_preview(client, binding["qr_id"])
    return binding


def open_viewer(client, token: str):
    response = client.get(f"/q/{token}")
    assert response.status_code == 200, response.text
    return response, client.cookies.get(client.app.state.settings.viewer_cookie_name)


def session_row(client):
    with client.app.state.database.read() as connection:
        return dict(connection.execute("SELECT * FROM viewer_sessions ORDER BY id DESC").fetchone())


def test_cookie_flags_and_anonymous_trace(client):
    binding = protected_pdf(client)
    response, raw = open_viewer(client, binding["qr_id"])
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie
    assert "samesite=lax" in cookie
    assert "path=/" in cookie
    assert "max-age=1800" in cookie
    assert "secure" not in cookie
    assert raw not in response.text
    assert re.search(r"本次匿名预览编号：V-[A-Z2-9]{8}", response.text)


def test_secure_cookie_is_configurable(settings):
    configured = replace(settings, viewer_cookie_secure=True)
    with TestClient(create_app(configured)) as client:
        binding = protected_pdf(client)
        response = client.get(f"/q/{binding['qr_id']}")
        assert "secure" in response.headers["set-cookie"].lower()


def test_database_never_stores_raw_token_ip_or_user_agent(client):
    binding = protected_pdf(client)
    response = client.get(
        f"/q/{binding['qr_id']}",
        headers={"user-agent": "Stage05C Secret Browser"},
    )
    raw = client.cookies.get("viewer_session")
    row = session_row(client)
    assert raw not in repr(row)
    assert row["session_key_hash"] != raw and len(row["session_key_hash"]) == 64
    assert row["user_agent_hash"] and "Secret Browser" not in row["user_agent_hash"]
    assert row["network_fingerprint_hash"] is None
    assert raw not in response.text


def test_optional_network_fingerprint_is_only_hmac(settings):
    configured = replace(settings, viewer_store_network_fingerprint=True)
    with TestClient(create_app(configured)) as client:
        binding = protected_pdf(client)
        open_viewer(client, binding["qr_id"])
        value = session_row(client)["network_fingerprint_hash"]
        assert value and len(value) == 64
        assert "testclient" not in value


def test_manifest_and_page_require_cookie(client):
    binding = protected_pdf(client)
    token = binding["qr_id"]
    assert client.get(f"/q/{token}/manifest").status_code == 401
    assert client.get(f"/q/{token}/pages/1").status_code == 401


def test_invalid_cookie_is_blocked(client):
    binding = protected_pdf(client)
    client.cookies.set("viewer_session", "forwarded-but-invalid")
    assert client.get(f"/q/{binding['qr_id']}/pages/1").status_code == 401


def test_session_cannot_cross_alias(client):
    first = protected_pdf(client)
    second = protected_pdf(client)
    open_viewer(client, first["qr_id"])
    response = client.get(f"/q/{second['qr_id']}/pages/1")
    assert response.status_code == 403
    assert "不属于这份资料" in response.text


def test_absolute_expiry_and_event(client):
    binding = protected_pdf(client)
    open_viewer(client, binding["qr_id"])
    with client.app.state.database.transaction() as connection:
        connection.execute(
            "UPDATE viewer_sessions SET expires_at = ?",
            ((datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),),
        )
    response = client.get(f"/q/{binding['qr_id']}/manifest")
    assert response.status_code == 401 and "已过期" in response.text
    assert session_row(client)["status"] == "expired"


def test_idle_expiry(client):
    binding = protected_pdf(client)
    open_viewer(client, binding["qr_id"])
    old = datetime.now(timezone.utc) - timedelta(minutes=11)
    with client.app.state.database.transaction() as connection:
        connection.execute("UPDATE viewer_sessions SET last_seen_at = ?", (old.isoformat(),))
    assert client.get(f"/q/{binding['qr_id']}/pages/1").status_code == 401


def test_revoked_session_is_blocked(client):
    binding = protected_pdf(client)
    open_viewer(client, binding["qr_id"])
    row = session_row(client)
    assert client.app.state.viewer_session_service.revoke(row["id"])
    assert client.get(f"/q/{binding['qr_id']}/pages/1").status_code == 403


def test_dynamic_session_pins_old_revision_until_new_entry(client):
    binding = protected_pdf(client)
    token = binding["qr_id"]
    open_viewer(client, token)
    assert client.get(f"/q/{token}/manifest").json()["page_count"] == 1
    client.put(
        f"/bindings/{token}/file",
        files={"file": ("第二版.pdf", pdf_bytes(pages=2), "application/pdf")},
    )
    prepare_preview(client, token)
    assert client.get(f"/q/{token}/manifest").json()["page_count"] == 1
    open_viewer(client, token)
    assert client.get(f"/q/{token}/manifest").json()["page_count"] == 2


def test_two_sessions_have_unique_trace_and_watermarked_pixels(client):
    binding = protected_pdf(client)
    token = binding["qr_id"]
    open_viewer(client, token)
    first_row = session_row(client)
    first = client.get(f"/q/{token}/pages/1").content
    open_viewer(client, token)
    second_row = session_row(client)
    second = client.get(f"/q/{token}/pages/1").content
    assert first_row["trace_code"] != second_row["trace_code"]
    assert first != second
    for payload in (first, second):
        with Image.open(BytesIO(payload)) as image:
            assert image.format == "WEBP" and image.width > 0 and image.height > 0


def test_watermark_text_contains_trace_but_not_token_or_ip(client):
    binding = protected_pdf(client)
    _, raw = open_viewer(client, binding["qr_id"])
    row = session_row(client)
    label = client.app.state.watermark_service.text(
        binding["display_code"], row["trace_code"]
    )
    assert row["trace_code"] in label
    assert binding["display_code"] in label
    assert raw not in label
    assert "testclient" not in label and "127.0.0.1" not in label


def test_base_preview_is_immutable_after_watermark(client):
    binding = protected_pdf(client)
    token = binding["qr_id"]
    resolved = client.app.state.resolver_service.resolve_latest(token)
    path, _ = client.app.state.preview_service.student_page(
        resolved.revision["id"], resolved.asset["id"], resolved.asset["sha256"], 1
    )
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    open_viewer(client, token)
    client.get(f"/q/{token}/pages/1")
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


def test_ascii_fallback_is_reported(client):
    binding = protected_pdf(client)
    service = client.app.state.watermark_service
    assert service.chinese_watermark_available is False
    assert service.text(binding["display_code"], "V-TEST2345").startswith("PREVIEW ONLY")
    payload = client.get("/capabilities").json()["configuration"]["watermark"]
    assert payload["fallback"] == "ASCII"


def test_manifest_rate_limit_returns_chinese_429(settings):
    configured = replace(settings, viewer_manifest_rate_limit_per_minute=1)
    with TestClient(create_app(configured)) as client:
        binding = protected_pdf(client)
        open_viewer(client, binding["qr_id"])
        assert client.get(f"/q/{binding['qr_id']}/manifest").status_code == 200
        limited = client.get(f"/q/{binding['qr_id']}/manifest")
        assert limited.status_code == 429
        assert limited.headers["retry-after"] == "60"
        assert "请求过于频繁" in limited.text


def test_page_rate_and_session_quota(settings):
    configured = replace(
        settings,
        viewer_page_rate_limit_per_minute=1,
        viewer_session_max_page_requests=1,
    )
    with TestClient(create_app(configured)) as client:
        binding = protected_pdf(client)
        open_viewer(client, binding["qr_id"])
        assert client.get(f"/q/{binding['qr_id']}/pages/1").status_code == 200
        assert client.get(f"/q/{binding['qr_id']}/pages/1").status_code == 429
        row = session_row(client)
        assert row["page_requests"] == 1 and row["denied_requests"] == 1


def test_global_concurrent_page_gate_is_six(client):
    binding = protected_pdf(client)
    open_viewer(client, binding["qr_id"])
    session = client.app.state.viewer_session_service.validate(
        binding["qr_id"], client.cookies.get("viewer_session")
    )

    def hold(number: int) -> int:
        try:
            with client.app.state.viewer_session_service.page_access(session, number):
                time.sleep(0.15)
            return 200
        except Exception as exc:
            return getattr(exc, "status_code", 500)

    with ThreadPoolExecutor(max_workers=7) as pool:
        statuses = list(pool.map(hold, range(1, 8)))
    assert statuses.count(200) == 6
    assert statuses.count(429) == 1


def test_normal_lazy_page_sequence_is_not_limited(client):
    binding = protected_pdf(client, pages=3)
    page, _ = open_viewer(client, binding["qr_id"])
    assert 'src="/q/' in page.text and 'data-src="/q/' in page.text
    assert [client.get(f"/q/{binding['qr_id']}/pages/{number}").status_code for number in (1, 2, 3)] == [200, 200, 200]


def test_access_events_are_minimal_and_redacted(client):
    binding = protected_pdf(client)
    open_viewer(client, binding["qr_id"])
    client.get(f"/q/{binding['qr_id']}/manifest")
    client.get(f"/q/{binding['qr_id']}/pages/1")
    with client.app.state.database.read() as connection:
        rows = connection.execute(
            "SELECT event_type, details FROM viewer_access_events ORDER BY id"
        ).fetchall()
    assert [row["event_type"] for row in rows] == [
        "session_created", "manifest_viewed", "page_viewed"
    ]
    assert all(row["details"] == "{}" for row in rows)


def test_event_retention_cleanup(client):
    binding = protected_pdf(client)
    open_viewer(client, binding["qr_id"])
    old = (datetime.now(timezone.utc) - timedelta(days=31)).isoformat()
    with client.app.state.database.transaction() as connection:
        connection.execute("UPDATE viewer_access_events SET created_at = ?", (old,))
    assert client.app.state.viewer_session_service.cleanup_events() == 1


def test_no_watermarked_disk_cache_is_created(client, settings):
    binding = protected_pdf(client)
    open_viewer(client, binding["qr_id"])
    client.get(f"/q/{binding['qr_id']}/pages/1")
    assert not (settings.storage_root / "cache" / "watermarked").exists()


def test_admin_can_query_without_seeing_secrets_and_revoke(admin_client):
    binding = protected_pdf(admin_client)
    _, raw = open_viewer(admin_client, binding["qr_id"])
    row = session_row(admin_client)
    page = admin_client.get(f"/admin/viewer-sessions?q={row['trace_code']}")
    assert page.status_code == 200
    assert row["trace_code"] in page.text and binding["display_code"] in page.text
    assert raw not in page.text and row["session_key_hash"] not in page.text
    revoked = admin_client.post(
        f"/admin/viewer-sessions/{row['id']}/revoke",
        data={"csrf_token": csrf_from(page)},
        follow_redirects=False,
    )
    assert revoked.status_code == 303
    assert admin_client.get(f"/q/{binding['qr_id']}/pages/1").status_code == 403


def test_original_file_is_still_admin_only(client):
    binding = protected_pdf(client)
    resolved = client.app.state.resolver_service.resolve_latest(binding["qr_id"])
    open_viewer(client, binding["qr_id"])
    assert client.get(f"/content/{resolved.revision['revision_key']}").status_code == 403
    assert client.get(
        f"/admin/revisions/{resolved.revision['revision_key']}/original",
        follow_redirects=False,
    ).status_code == 303
