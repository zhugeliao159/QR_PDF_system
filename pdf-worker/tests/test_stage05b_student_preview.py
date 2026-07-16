from __future__ import annotations

import re
from dataclasses import replace

from fastapi.testclient import TestClient

from app.main import create_app
from app.scripts.audit_preview_cutover import audit
from conftest import (
    create_binding,
    csrf_from,
    login_admin,
    pdf_bytes,
    prepare_preview,
)


def create_pdf_draft(client, qr_id: str, payload: bytes, filename: str = "新版解析.pdf"):
    page = client.get(f"/admin/materials/{qr_id}/replace")
    response = client.post(
        f"/admin/materials/{qr_id}/replace",
        data={"csrf_token": csrf_from(page), "content_type": "pdf"},
        files={"file": (filename, payload, "application/pdf")},
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text
    return response.headers["location"].split("/drafts/", 1)[1].split("?", 1)[0]


def page_state(response) -> int:
    match = re.search(r'name="page_state" value="(\d+)"', response.text)
    assert match, response.text
    return int(match.group(1))


def test_manifest_and_pages_expose_only_private_webp_derivatives(client):
    original = pdf_bytes(pages=3)
    binding = create_binding(client, original, "三页解析.pdf")
    token = binding["qr_id"]
    resolved = prepare_preview(client, token)

    page = client.get(f"/q/{token}")
    assert page.status_code == 200
    assert f'src="/q/{token}/pages/1"' in page.text
    assert f'data-src="/q/{token}/pages/2"' in page.text
    assert "data-download" not in page.text
    assert "下载文件" not in page.text
    assert "application/pdf" not in page.text
    assert resolved.revision["revision_key"] not in page.text
    assert resolved.asset["asset_key"] not in page.text
    assert resolved.asset["sha256"] not in page.text

    manifest = client.get(f"/q/{token}/manifest")
    assert manifest.status_code == 200
    assert set(manifest.json()) == {
        "page_count",
        "revision_display",
        "content_kind",
        "generated_at",
    }
    assert manifest.json()["page_count"] == 3
    assert manifest.headers["cache-control"] == "private, no-store, max-age=0"

    image = client.get(f"/q/{token}/pages/1")
    assert image.status_code == 200
    assert image.headers["content-type"] == "image/webp"
    assert image.headers["content-disposition"] == "inline"
    assert image.headers["pragma"] == "no-cache"
    assert image.content != original
    assert client.get(f"/content/{resolved.revision['revision_key']}").status_code == 403


def test_dynamic_fixed_and_legacy_routes_preserve_revision_semantics(client):
    binding = create_binding(client, pdf_bytes(), "第一版.pdf")
    token = binding["qr_id"]
    first = prepare_preview(client, token)
    fixed_token = client.app.state.binding_service.fixed_alias_token(
        token, first.revision["id"]
    )
    client.put(
        f"/bindings/{token}/file",
        files={"file": ("第二版.pdf", pdf_bytes(pages=2), "application/pdf")},
    )
    prepare_preview(client, token)

    assert client.get(f"/q/{token}/manifest").json()["page_count"] == 2
    assert client.get(f"/q/{fixed_token}/manifest").json()["page_count"] == 1
    legacy = client.get(f"/r/{token}", follow_redirects=False)
    assert legacy.status_code == 307 and legacy.headers["location"] == f"/q/{token}"
    legacy_fixed = client.get(
        f"/r/{token}/versions/{first.revision['id']}", follow_redirects=False
    )
    assert legacy_fixed.status_code == 307
    assert client.get(f"{legacy_fixed.headers['location']}/manifest").json()["page_count"] == 1


def test_preview_not_ready_failed_and_page_range_errors_are_chinese(client):
    binding = create_binding(client, pdf_bytes(), "等待预览.pdf")
    token = binding["qr_id"]
    preparing = client.get(f"/q/{token}")
    assert preparing.status_code == 503
    assert "解析内容正在准备中" in preparing.text

    resolved = client.app.state.resolver_service.resolve_latest(token)
    request = client.app.state.preview_service.request_preview(resolved.revision["id"])
    with client.app.state.database.transaction() as connection:
        connection.execute(
            "UPDATE preview_sets SET status = 'failed' WHERE id = ?",
            (request.preview_set_id,),
        )
        connection.execute(
            "UPDATE preview_jobs SET status = 'failed' WHERE id = ?",
            (request.job_id,),
        )
    failed = client.get(f"/q/{token}")
    assert failed.status_code == 503
    assert "请联系资料提供方" in failed.text

    retry = client.app.state.preview_service.request_preview(resolved.revision["id"])
    assert retry.status == "pending"
    client.app.state.preview_service.process_until_idle("stage05b-test-worker")
    outside = client.get(f"/q/{token}/pages/99")
    assert outside.status_code == 404
    assert "没有找到这一页" in outside.text


def test_external_url_is_disabled_for_students_by_default(admin_settings):
    settings = replace(
        admin_settings,
        allow_external_urls=True,
        external_url_allowed_hosts=("allowed.example",),
        protected_preview_external_url_policy="disable",
    )
    with TestClient(create_app(settings)) as client:
        login_admin(client)
        client.app.state.external_url_validator.resolver = lambda host, port: {"93.184.216.34"}
        binding = create_binding(client, pdf_bytes(), "旧版.pdf")
        qr_id = binding["qr_id"]
        page = client.get(f"/admin/materials/{qr_id}/replace")
        created = client.post(
            f"/admin/materials/{qr_id}/replace",
            data={
                "csrf_token": csrf_from(page),
                "content_type": "external_url",
                "external_url": "https://allowed.example/answer",
            },
            follow_redirects=False,
        )
        key = created.headers["location"].split("/drafts/", 1)[1].split("?", 1)[0]
        draft = client.get(created.headers["location"])
        published = client.post(
            f"/admin/materials/{qr_id}/drafts/{key}/publish",
            data={
                "csrf_token": csrf_from(draft),
                "page_state": page_state(draft),
                "external_confirm": "yes",
            },
            follow_redirects=False,
        )
        assert published.status_code == 303
        student = client.get(f"/q/{qr_id}")
        assert "该内容暂不支持受控在线预览" in student.text
        assert "https://allowed.example" not in student.text
        assert client.get(f"/q/{qr_id}/content").status_code == 403


def test_publish_gate_checks_preview_files_and_can_recover(admin_settings):
    settings = replace(admin_settings, require_preview_before_publish=True)
    with TestClient(create_app(settings)) as client:
        login_admin(client)
        binding = create_binding(client, pdf_bytes(), "已发布.pdf")
        qr_id = binding["qr_id"]
        key = create_pdf_draft(client, qr_id, pdf_bytes(pages=2))
        draft = client.app.state.binding_service.draft_details(qr_id, key)
        page = client.get(f"/admin/materials/{qr_id}/drafts/{key}")
        blocked = client.post(
            f"/admin/materials/{qr_id}/drafts/{key}/publish",
            data={"csrf_token": csrf_from(page), "page_state": draft["row_version"]},
        )
        assert blocked.status_code == 409
        assert "学生预览尚未生成完成" in blocked.text

        client.app.state.preview_service.request_preview(draft["version_id"])
        client.app.state.preview_service.process_until_idle("stage05b-gate-worker")
        path, _ = client.app.state.preview_service.page_path(draft["version_id"], 1)
        path.write_bytes(b"corrupt")
        page = client.get(f"/admin/materials/{qr_id}/drafts/{key}")
        corrupted = client.post(
            f"/admin/materials/{qr_id}/drafts/{key}/publish",
            data={"csrf_token": csrf_from(page), "page_state": draft["row_version"]},
        )
        assert corrupted.status_code == 409

        client.app.state.preview_service.request_preview(draft["version_id"], force=True)
        client.app.state.preview_service.process_until_idle("stage05b-gate-worker")
        page = client.get(f"/admin/materials/{qr_id}/drafts/{key}")
        published = client.post(
            f"/admin/materials/{qr_id}/drafts/{key}/publish",
            data={"csrf_token": csrf_from(page), "page_state": draft["row_version"]},
            follow_redirects=False,
        )
        assert published.status_code == 303


def test_cutover_audit_detects_supported_and_unsupported_active_files(settings, client):
    binding = create_binding(client, pdf_bytes(), "可预览.pdf")
    prepare_preview(client, binding["qr_id"])
    ok, lines = audit(settings)
    assert ok is True
    assert any("latest 1/1" in line for line in lines)

    create_binding(client, b"legacy", "legacy.txt")
    ok, lines = audit(settings)
    assert ok is False
    assert any("UNSUPPORTED" in line for line in lines)
