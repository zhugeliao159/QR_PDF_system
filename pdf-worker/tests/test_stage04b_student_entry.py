from __future__ import annotations

import hashlib

from conftest import create_binding, pdf_bytes, prepare_preview


def create_pdf_binding(client, content: bytes | None = None, filename="高一数学解析.pdf"):
    return create_binding(client, content or pdf_bytes(), filename)


def test_student_page_is_chinese_mobile_and_starts_preview_automatically(client):
    binding = create_pdf_binding(client)
    token = binding["qr_id"]
    prepare_preview(client, token)
    response = client.get(f"/q/{token}")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store, max-age=0"
    assert response.headers["content-security-policy"].startswith("default-src 'self'")
    assert 'lang="zh-CN"' in response.text
    assert 'name="viewport"' in response.text
    assert f'src="/q/{token}/pages/1"' in response.text
    assert 'loading="eager"' in response.text
    assert "/static/js/student.js" in response.text
    assert "<object" not in response.text
    assert "下载文件" not in response.text
    assert binding["sha256"] not in response.text
    assert "storage_key" not in response.text
    assert "cdn" not in response.text.lower()

    script = client.get("/static/js/student.js")
    assert script.status_code == 200
    assert "IntersectionObserver" in script.text
    assert "dataset.src" in script.text


def test_dynamic_content_tracks_current_without_exposing_original(client):
    original = pdf_bytes()
    updated = pdf_bytes(pages=2)
    binding = create_pdf_binding(client, original, "旧解析.pdf")
    token = binding["qr_id"]
    old = prepare_preview(client, token)
    old_key = old.revision["revision_key"]

    before = client.get(f"/q/{token}/manifest").json()
    assert before["page_count"] == 1
    assert client.get(f"/content/{old_key}").status_code == 403
    content_link = client.get(f"/q/{token}/content", follow_redirects=False)
    assert content_link.status_code == 307
    assert content_link.headers["location"] == f"/q/{token}"

    replaced = client.put(
        f"/bindings/{token}/file",
        files={"file": ("新解析.pdf", updated, "application/pdf")},
    )
    assert replaced.status_code == 200
    prepare_preview(client, token)
    after = client.get(f"/q/{token}/manifest").json()
    assert after["page_count"] == 2
    assert client.get(f"/content/{old_key}").status_code == 403


def test_original_content_requires_admin_and_keeps_chinese_filename(admin_client):
    content = pdf_bytes()
    binding = create_pdf_binding(admin_client, content, "学术英语 第一章.pdf")
    resolved = prepare_preview(admin_client, binding["qr_id"])
    key = resolved.revision["revision_key"]
    response = admin_client.get(f"/admin/revisions/{key}/original")
    assert response.status_code == 200
    assert response.content == content
    assert response.headers["cache-control"] == "private, no-store, max-age=0"
    assert response.headers["content-disposition"].startswith("inline;")
    assert "filename*=UTF-8''" in response.headers["content-disposition"]
    assert hashlib.sha256(response.content).hexdigest() == binding["sha256"]

    admin_client.post("/admin/logout", data={"csrf_token": admin_client.cookies.get("unused", "")})
    admin_client.cookies.clear()
    assert admin_client.get(f"/content/{key}").status_code == 403
    assert admin_client.get(f"/admin/revisions/{key}/original", follow_redirects=False).status_code == 303


def test_fixed_qr_uses_independent_pinned_preview(client):
    original = pdf_bytes()
    binding = create_pdf_binding(client, original)
    token = binding["qr_id"]
    prepare_preview(client, token)
    version_id = binding["current_version"]["version_id"]
    fixed_qr = client.get(f"/bindings/{token}/versions/{version_id}/qr.png")
    fixed_url = fixed_qr.headers["content-location"]
    pinned_token = fixed_url.rsplit("/", 1)[-1]

    updated = pdf_bytes(pages=2)
    client.put(
        f"/bindings/{token}/file",
        files={"file": ("new.pdf", updated, "application/pdf")},
    )
    prepare_preview(client, token)
    assert client.get(f"/q/{pinned_token}/manifest").json()["page_count"] == 1
    assert client.get(f"/q/{token}/manifest").json()["page_count"] == 2
    assert client.get(f"/q/{pinned_token}/pages/1").content != original
    with client.app.state.database.read() as connection:
        alias = connection.execute(
            "SELECT * FROM qr_aliases WHERE public_token = ?", (pinned_token,)
        ).fetchone()
        assert alias["pinned_revision_id"] == version_id


def test_new_dynamic_qr_and_legacy_routes_open_preview(client):
    binding = create_pdf_binding(client)
    token = binding["qr_id"]
    prepare_preview(client, token)
    version_id = binding["current_version"]["version_id"]
    dynamic = client.get(f"/r/{token}", follow_redirects=False)
    assert dynamic.status_code == 307
    assert dynamic.headers["location"] == f"/q/{token}"
    fixed = client.get(f"/r/{token}/versions/{version_id}", follow_redirects=False)
    assert fixed.status_code == 307
    assert fixed.headers["location"].startswith("/q/")
    assert client.get(fixed.headers["location"]).status_code == 200


def test_student_error_pages_are_chinese_and_do_not_leak_paths(client, settings):
    missing = client.get("/q/not-a-real-token")
    assert missing.status_code == 404
    assert "没有找到对应的解析资料" in missing.text
    assert "Traceback" not in missing.text
    assert "/admin" not in missing.text

    binding = create_pdf_binding(client)
    token = binding["qr_id"]
    preparing = client.get(f"/q/{token}")
    assert preparing.status_code == 503
    assert "正在准备中" in preparing.text
    assert preparing.headers["retry-after"] == "30"

    prepare_preview(client, token)
    resolved = client.app.state.resolver_service.resolve_latest(token)
    path, _ = client.app.state.preview_service.student_page(
        resolved.revision["id"], resolved.asset["id"], resolved.asset["sha256"], 1
    )
    path.unlink()
    missing_page = client.get(f"/q/{token}")
    assert missing_page.status_code == 503
    assert "请稍后重试" in missing_page.text
    assert str(settings.storage_root) not in missing_page.text


def test_resource_inactive_is_distinct_from_alias_inactive(client):
    binding = create_pdf_binding(client)
    resolved = client.app.state.resolver_service.resolve_latest(binding["qr_id"])
    with client.app.state.database.transaction() as connection:
        connection.execute(
            "UPDATE answer_resources SET status = 'inactive' WHERE id = ?",
            (resolved.resource["id"],),
        )
    response = client.get(f"/q/{binding['qr_id']}")
    assert response.status_code == 410
    assert "该解析资料暂时不可用" in response.text
