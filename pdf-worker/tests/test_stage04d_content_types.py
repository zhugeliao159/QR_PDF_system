from __future__ import annotations

import re
import sqlite3
from dataclasses import replace
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.errors import AppError
from app.main import create_app
from app.services.external_url import ExternalUrlValidator
from conftest import (
    create_binding,
    csrf_from,
    login_admin,
    pdf_bytes,
    png_bytes,
    prepare_preview,
)


PUBLIC_IP = "93.184.216.34"


def image_bytes(image_format: str, size=(24, 18), color="navy") -> bytes:
    output = BytesIO()
    Image.new("RGB", size, color=color).save(output, format=image_format)
    return output.getvalue()


def create_file_draft(
    client,
    qr_id: str,
    content: bytes,
    filename: str,
    mime_type: str,
    content_type: str,
):
    page = client.get(f"/admin/materials/{qr_id}/replace")
    response = client.post(
        f"/admin/materials/{qr_id}/replace",
        data={
            "csrf_token": csrf_from(page),
            "content_type": content_type,
            "note": "Stage 4D 草稿",
        },
        files={"file": (filename, content, mime_type)},
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text
    return response.headers["location"].split("/drafts/", 1)[1].split("?", 1)[0]


def page_state(response) -> int:
    match = re.search(r'name="page_state" value="(\d+)"', response.text)
    assert match, response.text
    return int(match.group(1))


def publish_draft(client, qr_id: str, revision_key: str, external=False):
    page = client.get(f"/admin/materials/{qr_id}/drafts/{revision_key}")
    data = {
        "csrf_token": csrf_from(page),
        "page_state": page_state(page),
    }
    if external:
        data["external_confirm"] = "yes"
    response = client.post(
        f"/admin/materials/{qr_id}/drafts/{revision_key}/publish",
        data=data,
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text
    return response


def configured_external_settings(admin_settings, **values):
    defaults = {
        "allow_external_urls": True,
        "external_url_allowed_hosts": ("allowed.example", "second.example"),
        "external_url_require_https": True,
        "protected_preview_external_url_policy": "warn",
    }
    defaults.update(values)
    return replace(admin_settings, **defaults)


def install_public_dns(client):
    calls = []

    def resolver(hostname: str, port: int):
        calls.append((hostname, port))
        return {PUBLIC_IP}

    client.app.state.external_url_validator.resolver = resolver
    return calls


@pytest.mark.parametrize(
    ("image_format", "filename", "declared_mime", "expected_mime"),
    [
        ("PNG", "答案图.png", "application/octet-stream", "image/png"),
        ("JPEG", "答案图.jpg", "image/jpeg", "image/jpeg"),
        ("WEBP", "答案图.webp", "image/webp", "image/webp"),
    ],
)
def test_png_jpeg_webp_create_private_drafts(
    admin_client, image_format, filename, declared_mime, expected_mime
):
    binding = create_binding(admin_client, b"old-answer", "old.txt")
    qr_id = binding["qr_id"]
    key = create_file_draft(
        admin_client,
        qr_id,
        image_bytes(image_format),
        filename,
        declared_mime,
        "image",
    )
    preview = admin_client.get(f"/admin/materials/{qr_id}/drafts/{key}")
    assert preview.status_code == 200
    assert "<img" in preview.text
    assert filename in preview.text
    assert admin_client.get(f"/content/{key}").status_code == 404
    assert admin_client.app.state.asset_service.path(
        admin_client.app.state.resolver_service.resolve_latest(qr_id).asset
    ).read_bytes() == b"old-answer"
    with admin_client.app.state.database.read() as connection:
        row = connection.execute(
            """SELECT v.status, a.mime_type FROM answer_revisions v
               JOIN assets a ON a.id = v.asset_id WHERE v.revision_key = ?""",
            (key,),
        ).fetchone()
        assert dict(row) == {"status": "draft", "mime_type": expected_mime}


def test_published_image_loads_as_private_webp_preview(admin_client):
    binding = create_binding(admin_client, b"old-answer")
    qr_id = binding["qr_id"]
    content = png_bytes("green")
    key = create_file_draft(
        admin_client, qr_id, content, "中文答案.png", "image/png", "image"
    )
    publish_draft(admin_client, qr_id, key)
    prepare_preview(admin_client, qr_id)

    page = admin_client.get(f"/q/{qr_id}")
    assert page.status_code == 200
    assert "preview-image" in page.text
    image = admin_client.get(f"/q/{qr_id}/pages/1")
    assert image.content != content
    assert image.headers["content-type"] == "image/webp"
    assert image.headers["cache-control"] == "private, no-store, max-age=0"
    assert image.headers["content-disposition"] == "inline"


def binding_hash(content: bytes) -> str:
    import hashlib

    return hashlib.sha256(content).hexdigest()


def test_fixed_image_alias_survives_new_pdf_publish(admin_client):
    binding = create_binding(admin_client, b"old-answer")
    qr_id = binding["qr_id"]
    image = png_bytes("blue")
    image_key = create_file_draft(
        admin_client, qr_id, image, "答案.png", "image/png", "image"
    )
    publish_draft(admin_client, qr_id, image_key)
    prepare_preview(admin_client, qr_id)
    image_revision = admin_client.app.state.resolver_service.resolve_latest(qr_id).revision
    fixed_token = admin_client.app.state.binding_service.fixed_alias_token(
        qr_id, image_revision["id"]
    )
    pdf = pdf_bytes()
    pdf_key = create_file_draft(
        admin_client, qr_id, pdf, "新版.pdf", "application/pdf", "pdf"
    )
    publish_draft(admin_client, qr_id, pdf_key)
    prepare_preview(admin_client, qr_id)

    assert admin_client.get(f"/q/{qr_id}/pages/1").headers["content-type"] == "image/webp"
    assert admin_client.get(f"/q/{fixed_token}/pages/1").headers["content-type"] == "image/webp"
    assert admin_client.get(f"/q/{qr_id}/pages/1").content != pdf
    assert admin_client.get(f"/q/{fixed_token}/pages/1").content != image


@pytest.mark.parametrize(
    ("content", "filename", "mime_type", "error_text"),
    [
        (b"broken", "broken.png", "image/png", "图片无法打开"),
        (pdf_bytes(), "pretend.png", "image/png", "请选择 PNG、JPEG 或 WebP"),
        (b"<svg></svg>", "answer.svg", "image/svg+xml", "图片无法打开"),
        (image_bytes("GIF"), "answer.gif", "image/gif", "只支持 PNG、JPEG 和 WebP"),
    ],
)
def test_invalid_and_unsupported_images_are_rejected(
    admin_client, content, filename, mime_type, error_text
):
    binding = create_binding(admin_client, b"old")
    page = admin_client.get(f"/admin/materials/{binding['qr_id']}/replace")
    response = admin_client.post(
        f"/admin/materials/{binding['qr_id']}/replace",
        data={"csrf_token": csrf_from(page), "content_type": "image"},
        files={"file": (filename, content, mime_type)},
    )
    assert response.status_code == 415
    assert error_text in response.text
    assert admin_client.app.state.asset_service.path(
        admin_client.app.state.resolver_service.resolve_latest(binding["qr_id"]).asset
    ).read_bytes() == b"old"


def test_image_size_pixel_limit_and_path_filename(admin_settings):
    limited = replace(admin_settings, max_image_size_mb=1, max_image_pixels=100)
    with TestClient(create_app(limited)) as client:
        login_admin(client)
        binding = create_binding(client, b"old")
        qr_id = binding["qr_id"]
        page = client.get(f"/admin/materials/{qr_id}/replace")
        too_large = client.post(
            f"/admin/materials/{qr_id}/replace",
            data={"csrf_token": csrf_from(page), "content_type": "image"},
            files={"file": ("large.png", b"x" * (1024 * 1024 + 1), "image/png")},
        )
        assert too_large.status_code == 413

        page = client.get(f"/admin/materials/{qr_id}/replace")
        too_many_pixels = client.post(
            f"/admin/materials/{qr_id}/replace",
            data={"csrf_token": csrf_from(page), "content_type": "image"},
            files={"file": ("pixels.png", image_bytes("PNG", (11, 10)), "image/png")},
        )
        assert too_many_pixels.status_code == 413
        assert "图片像素过大" in too_many_pixels.text

        page = client.get(f"/admin/materials/{qr_id}/replace")
        safe = client.post(
            f"/admin/materials/{qr_id}/replace",
            data={"csrf_token": csrf_from(page), "content_type": "image"},
            files={"file": ("../../答案.png", image_bytes("PNG", (10, 10)), "image/png")},
            follow_redirects=False,
        )
        assert safe.status_code == 303
        with client.app.state.database.read() as connection:
            filename = connection.execute(
                "SELECT original_filename FROM assets ORDER BY id DESC LIMIT 1"
            ).fetchone()["original_filename"]
        assert filename == "答案.png"


def test_external_url_option_is_hidden_and_creation_disabled_by_default(admin_client):
    binding = create_binding(admin_client, b"old")
    page = admin_client.get(f"/admin/materials/{binding['qr_id']}/replace")
    assert "使用外部网页" not in page.text
    response = admin_client.post(
        f"/admin/materials/{binding['qr_id']}/replace",
        data={
            "csrf_token": csrf_from(page),
            "content_type": "external_url",
            "external_url": "https://allowed.example/answer",
        },
    )
    assert response.status_code == 403
    assert "外部网页功能当前未启用" in response.text


@pytest.mark.parametrize(
    "url",
    [
        "file:///tmp/answer.pdf",
        "javascript:alert(1)",
        "data:text/html,answer",
        "ftp://allowed.example/answer",
        "https://user:password@allowed.example/answer",
        "https://allowed.example:99999/answer",
        "https://allowed.example/answer\nX-Test: injected",
    ],
)
def test_external_url_rejects_dangerous_schemes_credentials_ports_and_controls(
    admin_settings, url
):
    settings = configured_external_settings(admin_settings)
    validator = ExternalUrlValidator(settings, resolver=lambda host, port: {PUBLIC_IP})
    with pytest.raises(AppError):
        validator.validate(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://localhost/answer",
        "https://answer.local/answer",
        "https://127.0.0.1/answer",
        "https://[::1]/answer",
        "https://192.168.1.8/answer",
        "https://10.0.0.8/answer",
        "https://169.254.1.1/answer",
        "https://224.0.0.1/answer",
        "https://100.64.0.9/answer",
    ],
)
def test_external_url_blocks_local_private_link_local_multicast_and_tailscale(
    admin_settings, url
):
    settings = configured_external_settings(
        admin_settings, external_url_allowed_hosts=()
    )
    validator = ExternalUrlValidator(settings)
    with pytest.raises(AppError) as error:
        validator.validate(url)
    assert error.value.code in {"EXTERNAL_URL_HOST_BLOCKED", "EXTERNAL_URL_ADDRESS_BLOCKED"}


def test_external_url_dns_and_allowlist_fail_closed(admin_settings):
    settings = configured_external_settings(admin_settings)
    validator = ExternalUrlValidator(settings, resolver=lambda host, port: {PUBLIC_IP})
    assert validator.validate("https://allowed.example/answer").hostname == "allowed.example"
    with pytest.raises(AppError, match="not allowed"):
        validator.validate("https://outside.example/answer")

    mixed = ExternalUrlValidator(settings, resolver=lambda host, port: {PUBLIC_IP, "10.0.0.1"})
    with pytest.raises(AppError) as mixed_error:
        mixed.validate("https://allowed.example/answer")
    assert mixed_error.value.code == "EXTERNAL_URL_ADDRESS_BLOCKED"

    failing = ExternalUrlValidator(
        settings, resolver=lambda host, port: (_ for _ in ()).throw(OSError("dns failed"))
    )
    with pytest.raises(AppError) as dns_error:
        failing.validate("https://allowed.example/answer")
    assert dns_error.value.code == "EXTERNAL_URL_DNS_FAILED"


def test_private_http_requires_explicit_test_configuration(admin_settings):
    base = configured_external_settings(admin_settings, external_url_allowed_hosts=())
    with pytest.raises(AppError):
        ExternalUrlValidator(base).validate("http://192.168.1.8/answer")
    allowed = replace(base, allow_private_http_external_urls=True)
    result = ExternalUrlValidator(allowed).validate("http://192.168.1.8/answer")
    assert result.private_http is True
    with pytest.raises(AppError):
        ExternalUrlValidator(allowed, resolver=lambda host, port: {PUBLIC_IP}).validate(
            "http://public.example/answer"
        )


def test_external_draft_publish_click_redirect_fixed_alias_and_audit(admin_settings):
    settings = configured_external_settings(admin_settings)
    with TestClient(create_app(settings)) as client:
        login_admin(client)
        dns_calls = install_public_dns(client)
        binding = create_binding(client, b"old-answer")
        qr_id = binding["qr_id"]
        page = client.get(f"/admin/materials/{qr_id}/replace")
        assert "使用外部网页" in page.text
        first_url = "https://allowed.example/answer?access_token=secret"
        created = client.post(
            f"/admin/materials/{qr_id}/replace",
            data={
                "csrf_token": csrf_from(page),
                "content_type": "external_url",
                "external_url": first_url,
                "note": "外部答案",
            },
            follow_redirects=False,
        )
        assert created.status_code == 303, created.text
        first_key = created.headers["location"].split("/drafts/", 1)[1].split("?", 1)[0]
        preview = client.get(created.headers["location"])
        assert "此版本将打开外部网页" in preview.text
        assert "allowed.example" in preview.text
        assert "<iframe" not in preview.text
        assert client.app.state.asset_service.path(
            client.app.state.resolver_service.resolve_latest(qr_id).asset
        ).read_bytes() == b"old-answer"

        unconfirmed = client.post(
            f"/admin/materials/{qr_id}/drafts/{first_key}/publish",
            data={"csrf_token": csrf_from(preview), "page_state": page_state(preview)},
        )
        assert unconfirmed.status_code == 422
        assert "适合学生访问" in unconfirmed.text
        publish_draft(client, qr_id, first_key, external=True)

        student = client.get(f"/q/{qr_id}")
        assert student.status_code == 200
        assert "外部网站内容" in student.text
        assert "确认并打开外部网站" in student.text
        assert first_url not in student.text
        assert "<iframe" not in student.text
        clicked = client.get(f"/q/{qr_id}/content", follow_redirects=False)
        assert clicked.status_code == 307
        assert clicked.headers["location"] == first_url
        assert clicked.headers["referrer-policy"] == "no-referrer"
        override = client.get(
            f"/q/{qr_id}/content?target=http://127.0.0.1", follow_redirects=False
        )
        assert override.status_code == 307
        assert override.headers["location"] == first_url

        current = client.app.state.resolver_service.resolve_latest(qr_id)
        fixed_token = client.app.state.binding_service.fixed_alias_token(
            qr_id, current.revision["id"]
        )
        page = client.get(f"/admin/materials/{qr_id}/replace")
        second_url = "https://second.example/new-answer"
        second = client.post(
            f"/admin/materials/{qr_id}/replace",
            data={
                "csrf_token": csrf_from(page),
                "content_type": "external_url",
                "external_url": second_url,
            },
            follow_redirects=False,
        )
        second_key = second.headers["location"].split("/drafts/", 1)[1].split("?", 1)[0]
        publish_draft(client, qr_id, second_key, external=True)
        assert client.get(f"/q/{qr_id}/content", follow_redirects=False).headers["location"] == second_url
        assert client.get(
            f"/q/{fixed_token}/content", follow_redirects=False
        ).headers["location"] == first_url
        versions = client.get(f"/admin/materials/{qr_id}/versions")
        republished = client.post(
            f"/admin/materials/{qr_id}/versions/{first_key}/republish",
            data={
                "csrf_token": csrf_from(versions),
                "page_state": page_state(versions),
                "external_confirm": "yes",
            },
            follow_redirects=False,
        )
        assert republished.status_code == 303
        assert client.get(
            f"/q/{qr_id}/content", follow_redirects=False
        ).headers["location"] == first_url
        assert dns_calls

        with client.app.state.database.read() as connection:
            events = [
                row["event_type"]
                for row in connection.execute(
                    "SELECT event_type FROM audit_events ORDER BY id"
                ).fetchall()
            ]
            summaries = [
                row["summary"]
                for row in connection.execute(
                    "SELECT summary FROM audit_events ORDER BY id"
                ).fetchall()
            ]
        assert "create_external_url_draft" in events
        assert "publish_external_url_revision" in events
        assert "republish_external_url_revision" in events
        assert all("access_token=secret" not in summary for summary in summaries)


def test_external_validation_failure_is_audited_without_query(admin_settings):
    settings = configured_external_settings(admin_settings)
    with TestClient(create_app(settings)) as client:
        login_admin(client)
        install_public_dns(client)
        binding = create_binding(client, b"old")
        page = client.get(f"/admin/materials/{binding['qr_id']}/replace")
        response = client.post(
            f"/admin/materials/{binding['qr_id']}/replace",
            data={
                "csrf_token": csrf_from(page),
                "content_type": "external_url",
                "external_url": "https://outside.example/answer?token=secret",
            },
        )
        assert response.status_code == 422
        with client.app.state.database.read() as connection:
            event = connection.execute(
                """SELECT summary FROM audit_events
                   WHERE event_type = 'external_url_validation_failed'"""
            ).fetchone()
        assert event is not None
        assert "outside.example" in event["summary"]
        assert "token=secret" not in event["summary"]


def test_revision_database_constraints_reject_invalid_target_combinations(client):
    binding = create_binding(client, b"old")
    resolved = client.app.state.resolver_service.resolve_latest(binding["qr_id"])
    resource_id = resolved.resource["id"]
    asset_id = resolved.asset["id"]
    statements = [
        ("file", None, None),
        ("file", asset_id, "https://example.com"),
        ("external_url", asset_id, "https://example.com"),
        ("external_url", None, None),
    ]
    for number, (target_type, candidate_asset, external_url) in enumerate(
        statements, start=100
    ):
        connection = client.app.state.database.connect()
        try:
            with pytest.raises(sqlite3.IntegrityError):
                connection.execute(
                    """INSERT INTO answer_revisions
                       (revision_key, resource_id, revision_number, target_type,
                        asset_id, external_url, status, change_note, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, 'draft', NULL, '2026-07-15T00:00:00Z')""",
                    (
                        f"invalid-{number}", resource_id, number, target_type,
                        candidate_asset, external_url,
                    ),
                )
                connection.commit()
        finally:
            connection.rollback()
            connection.close()
