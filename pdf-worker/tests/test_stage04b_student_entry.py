from __future__ import annotations

import hashlib

from conftest import create_binding, pdf_bytes


def create_pdf_binding(client, content: bytes | None = None, filename="高一数学解析.pdf"):
    return create_binding(client, content or pdf_bytes(), filename)


def test_student_page_is_chinese_mobile_and_starts_pdf_automatically(client):
    binding = create_pdf_binding(client)
    token = binding["qr_id"]
    response = client.get(f"/q/{token}")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store, must-revalidate"
    assert 'lang="zh-CN"' in response.text
    assert 'name="viewport"' in response.text
    assert "<object" in response.text
    assert "data-student-content" in response.text
    assert "/static/js/student.js" in response.text
    assert "window.location" not in response.text
    assert "全屏打开" in response.text
    assert "下载文件" in response.text
    assert "当前浏览器无法直接显示 PDF" in response.text
    assert token not in response.text
    assert binding["sha256"] not in response.text
    assert "storage_key" not in response.text
    assert "https://" not in response.text
    assert "cdn" not in response.text.lower()

    script = client.get("/static/js/student.js")
    assert script.status_code == 200
    assert "window.location.pathname" in script.text
    assert "viewer.data = contentUrl" in script.text


def test_dynamic_content_tracks_current_and_old_content_is_immutable(client):
    original = pdf_bytes()
    updated = pdf_bytes(pages=2)
    binding = create_pdf_binding(client, original, "旧解析.pdf")
    token = binding["qr_id"]
    resolved = client.app.state.resolver_service.resolve_latest(token)
    old_key = resolved.revision["revision_key"]

    dynamic_before = client.get(f"/q/{token}/content", follow_redirects=False)
    assert dynamic_before.status_code == 307
    assert dynamic_before.headers["cache-control"] == "no-store, must-revalidate"
    assert dynamic_before.headers["location"] == f"/content/{old_key}"
    assert client.get(dynamic_before.headers["location"]).content == original

    replaced = client.put(
        f"/bindings/{token}/file",
        files={"file": ("新解析.pdf", updated, "application/pdf")},
    )
    assert replaced.status_code == 200
    new_resolved = client.app.state.resolver_service.resolve_latest(token)
    assert new_resolved.revision["revision_key"] != old_key

    dynamic_after = client.get(f"/q/{token}/content", follow_redirects=False)
    assert dynamic_after.headers["location"] == (
        f"/content/{new_resolved.revision['revision_key']}"
    )
    assert client.get(dynamic_after.headers["location"]).content == updated
    assert client.get(f"/content/{old_key}").content == original


def test_immutable_content_etag_cache_and_chinese_filename(client):
    content = pdf_bytes()
    binding = create_pdf_binding(client, content, "学术英语 第一章.pdf")
    resolved = client.app.state.resolver_service.resolve_latest(binding["qr_id"])
    url = f"/content/{resolved.revision['revision_key']}"
    response = client.get(url)
    expected_etag = f'"{hashlib.sha256(content).hexdigest()}"'
    assert response.status_code == 200
    assert response.content == content
    assert response.headers["etag"] == expected_etag
    assert response.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert response.headers["content-type"].startswith("application/pdf")
    assert response.headers["content-disposition"].startswith("inline;")
    assert "filename*=UTF-8''" in response.headers["content-disposition"]

    not_modified = client.get(url, headers={"If-None-Match": expected_etag})
    assert not_modified.status_code == 304
    assert not_modified.content == b""
    assert not_modified.headers["etag"] == expected_etag
    assert not_modified.headers["cache-control"].endswith("immutable")

    download = client.get(url + "?download=true")
    assert download.headers["content-disposition"].startswith("attachment;")


def test_fixed_qr_uses_independent_pinned_alias(client):
    original = pdf_bytes()
    binding = create_pdf_binding(client, original)
    token = binding["qr_id"]
    version_id = binding["current_version"]["version_id"]
    fixed_qr = client.get(f"/bindings/{token}/versions/{version_id}/qr.png")
    assert fixed_qr.status_code == 200
    fixed_url = fixed_qr.headers["content-location"]
    assert fixed_url.startswith("http://test.local:18081/q/")
    pinned_token = fixed_url.rsplit("/", 1)[-1]
    assert pinned_token != token
    assert len(pinned_token) == 32

    first = client.app.state.resolver_service.resolve_latest(pinned_token)
    assert first.alias["resolve_mode"] == "pinned"
    assert first.revision["id"] == version_id
    again = client.get(f"/bindings/{token}/versions/{version_id}/qr.png")
    assert again.headers["content-location"] == fixed_url

    updated = pdf_bytes(pages=2)
    client.put(
        f"/bindings/{token}/file",
        files={"file": ("new.pdf", updated, "application/pdf")},
    )
    pinned_content = client.get(
        f"/q/{pinned_token}/content", follow_redirects=True
    )
    latest_content = client.get(f"/q/{token}/content", follow_redirects=True)
    assert pinned_content.content == original
    assert latest_content.content == updated

    with client.app.state.database.read() as connection:
        alias = connection.execute(
            "SELECT * FROM qr_aliases WHERE public_token = ?", (pinned_token,)
        ).fetchone()
        assert alias["pinned_revision_id"] == version_id
        assert connection.execute(
            "SELECT 1 FROM revision_references WHERE revision_id = ?",
            (version_id,),
        ).fetchone() is not None


def test_new_dynamic_qr_uses_q_and_legacy_routes_still_work(client):
    content = pdf_bytes()
    binding = create_pdf_binding(client, content)
    token = binding["qr_id"]
    version_id = binding["current_version"]["version_id"]
    assert binding["qr_url"] == f"http://test.local:18081/q/{token}"
    assert client.app.state.qr_service.legacy_url(token).endswith(f"/r/{token}")
    assert client.get(f"/r/{token}").content == content
    assert client.get(f"/r/{token}/versions/{version_id}").content == content


def test_student_error_pages_are_chinese_and_do_not_leak_paths(client, settings):
    missing = client.get("/q/not-a-real-token")
    assert missing.status_code == 404
    assert "没有找到对应的解析资料" in missing.text
    assert "Traceback" not in missing.text
    assert "/admin" not in missing.text

    binding = create_pdf_binding(client)
    token = binding["qr_id"]
    resource_id = client.app.state.resolver_service.resolve_latest(token).resource["id"]
    with client.app.state.database.transaction() as connection:
        connection.execute(
            "UPDATE qr_aliases SET status = 'inactive' WHERE public_token = ?",
            (token,),
        )
    inactive_alias = client.get(f"/q/{token}")
    assert inactive_alias.status_code == 410
    assert "该解析资料暂时不可用" in inactive_alias.text

    with client.app.state.database.transaction() as connection:
        connection.execute(
            "UPDATE qr_aliases SET status = 'active' WHERE public_token = ?",
            (token,),
        )
        connection.execute(
            "UPDATE answer_resources SET status = 'inactive' WHERE id = ?",
            (resource_id,),
        )
    inactive_resource = client.get(f"/q/{token}")
    assert inactive_resource.status_code == 410

    with client.app.state.database.transaction() as connection:
        connection.execute("UPDATE answer_resources SET status = 'active'")
        connection.execute(
            "UPDATE answer_resources SET current_published_revision_id = NULL"
        )
    unpublished = client.get(f"/q/{token}")
    assert unpublished.status_code == 503
    assert "这份解析暂未发布" in unpublished.text

    with client.app.state.database.transaction() as connection:
        revision = connection.execute(
            "SELECT * FROM answer_revisions ORDER BY id DESC LIMIT 1"
        ).fetchone()
        connection.execute(
            "UPDATE answer_resources SET current_published_revision_id = ?",
            (revision["id"],),
        )
        storage_key = connection.execute(
            "SELECT storage_key FROM assets WHERE id = ?", (revision["asset_id"],)
        ).fetchone()[0]
    settings.storage_root.joinpath(storage_key).unlink()
    missing_asset = client.get(f"/content/{revision['revision_key']}")
    assert missing_asset.status_code == 503
    assert "解析文件暂时无法打开" in missing_asset.text
    assert str(settings.storage_root) not in missing_asset.text


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
