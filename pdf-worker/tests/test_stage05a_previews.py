from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.errors import AppError
from app.main import create_app
from app.scripts.backfill_previews import find_candidates
from app.services.preview_renderers import PdfPreviewRenderer, PreviewRenderConfig
from conftest import (
    create_binding,
    csrf_from,
    encrypted_pdf_bytes,
    login_admin,
    pdf_bytes,
    png_bytes,
)


def revision_for(client, qr_id: str):
    return client.app.state.resolver_service.resolve_latest(qr_id)


def complete_preview(client, revision_id: int):
    request = client.app.state.preview_service.request_preview(revision_id)
    processed = client.app.state.preview_service.process_until_idle("test-preview-worker")
    assert processed >= 1
    status = client.app.state.preview_service.status_for_revision(revision_id)
    assert status is not None
    return request, status


def jpeg_with_orientation() -> bytes:
    result = BytesIO()
    image = Image.new("RGB", (12, 24), "blue")
    exif = Image.Exif()
    exif[274] = 6
    image.save(result, format="JPEG", exif=exif)
    image.close()
    return result.getvalue()


def webp_bytes() -> bytes:
    result = BytesIO()
    image = Image.new("RGB", (20, 10), "purple")
    image.save(result, format="WEBP")
    image.close()
    return result.getvalue()


def transparent_png() -> bytes:
    result = BytesIO()
    image = Image.new("RGBA", (10, 10), (255, 0, 0, 0))
    image.save(result, format="PNG")
    image.close()
    return result.getvalue()


def test_schema4_preview_constraints_and_pdf_pages(client):
    binding = create_binding(client, pdf_bytes(pages=3), "three-pages.pdf")
    resolved = revision_for(client, binding["qr_id"])
    original_path = client.app.state.asset_service.path(resolved.asset)
    original_bytes = original_path.read_bytes()
    original_hash = hashlib.sha256(original_bytes).hexdigest()

    first = client.app.state.preview_service.request_preview(resolved.revision["id"])
    duplicate = client.app.state.preview_service.request_preview(resolved.revision["id"])
    assert duplicate.reused is True
    assert duplicate.job_id == first.job_id
    client.app.state.preview_service.process_until_idle("test-preview-worker")

    status = client.app.state.preview_service.status_for_revision(resolved.revision["id"])
    assert status["status"] == "completed"
    assert status["page_count"] == 3
    assert status["rendered_pages"] == 3
    pages = client.app.state.preview_service.list_pages(resolved.revision["id"])
    assert [page["page_number"] for page in pages] == [1, 2, 3]
    for page in pages:
        path, metadata = client.app.state.preview_service.page_path(
            resolved.revision["id"], page["page_number"]
        )
        assert path.suffix == ".webp"
        assert hashlib.sha256(path.read_bytes()).hexdigest() == metadata["sha256"]
        with Image.open(path) as image:
            assert image.format == "WEBP"
            image.load()
    assert original_path.read_bytes() == original_bytes
    assert hashlib.sha256(original_path.read_bytes()).hexdigest() == original_hash
    completed = client.app.state.preview_service.request_preview(resolved.revision["id"])
    assert completed.reused is True and completed.status == "completed"

    with client.app.state.database.connect() as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO preview_pages
                    (preview_set_id, page_number, storage_backend, storage_key,
                     mime_type, width, height, size_bytes, sha256, created_at)
                SELECT preview_set_id, page_number, storage_backend, storage_key,
                       mime_type, width, height, size_bytes, sha256, created_at
                FROM preview_pages LIMIT 1
                """
            )
            connection.commit()


@pytest.mark.parametrize(
    ("payload", "filename", "expected_size"),
    [
        (png_bytes("green"), "答案图.png", (16, 16)),
        (jpeg_with_orientation(), "答案图.jpg", (24, 12)),
        (webp_bytes(), "答案图.webp", (20, 10)),
    ],
)
def test_images_are_reencoded_to_webp_without_original_metadata(
    client, payload, filename, expected_size
):
    binding = create_binding(client, payload, filename)
    resolved = revision_for(client, binding["qr_id"])
    _, status = complete_preview(client, resolved.revision["id"])
    assert status["status"] == "completed"
    path, page = client.app.state.preview_service.page_path(resolved.revision["id"], 1)
    assert path.read_bytes() != payload
    with Image.open(path) as image:
        image.load()
        assert image.format == "WEBP"
        assert image.size == expected_size
        assert not image.getexif()
    assert page["mime_type"] == "image/webp"


def test_transparent_image_is_reencoded_with_white_background(client):
    binding = create_binding(client, transparent_png(), "transparent.png")
    resolved = revision_for(client, binding["qr_id"])
    complete_preview(client, resolved.revision["id"])
    path, _ = client.app.state.preview_service.page_path(resolved.revision["id"], 1)
    with Image.open(path) as image:
        image.load()
        red, green, blue = image.convert("RGB").getpixel((5, 5))
    assert min(red, green, blue) > 240


def test_encrypted_broken_and_over_page_limit_pdfs_are_rejected(settings, tmp_path):
    renderer = PdfPreviewRenderer()
    config = PreviewRenderConfig.from_settings(settings)
    encrypted = tmp_path / "encrypted.pdf"
    encrypted.write_bytes(encrypted_pdf_bytes())
    with pytest.raises(AppError) as encrypted_error:
        renderer.render(encrypted, tmp_path / "encrypted-output", config)
    assert encrypted_error.value.code == "PREVIEW_PDF_ENCRYPTED"

    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"%PDF-1.7\nbroken")
    with pytest.raises(AppError) as broken_error:
        renderer.render(broken, tmp_path / "broken-output", config)
    assert broken_error.value.code in {"PREVIEW_PDF_INVALID", "PREVIEW_PDF_RENDER_FAILED"}

    over_limit = tmp_path / "over-limit.pdf"
    over_limit.write_bytes(pdf_bytes(pages=settings.preview_max_pages + 1))
    with pytest.raises(AppError) as limit_error:
        renderer.render(over_limit, tmp_path / "limit-output", config)
    assert limit_error.value.code == "PREVIEW_PDF_PAGE_LIMIT"


def test_failed_preview_removes_temp_output_and_stale_job_recovers(client):
    payload = pdf_bytes()
    binding = create_binding(client, payload, "recover.pdf")
    resolved = revision_for(client, binding["qr_id"])
    request = client.app.state.preview_service.request_preview(resolved.revision["id"])
    with client.app.state.database.transaction() as connection:
        connection.execute(
            "UPDATE preview_jobs SET max_attempts = 1 WHERE id = ?", (request.job_id,)
        )
    source = client.app.state.asset_service.path(resolved.asset)
    source.write_bytes(b"changed after preview job creation")
    client.app.state.preview_service.process_next("test-preview-worker")
    status = client.app.state.preview_service.status_for_revision(resolved.revision["id"])
    assert status["status"] == "failed"
    assert not list(client.app.state.settings.previews_dir.glob(".tmp-*"))

    retry = client.app.state.preview_service.request_preview(resolved.revision["id"])
    source.write_bytes(payload)
    with client.app.state.database.transaction() as connection:
        stale = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat().replace("+00:00", "Z")
        connection.execute(
            """
            UPDATE preview_jobs SET status = 'processing', attempts = 1, claimed_at = ?
            WHERE id = ?
            """,
            (stale, retry.job_id),
        )
        connection.execute(
            "UPDATE preview_sets SET status = 'processing' WHERE id = ?", (retry.preview_set_id,)
        )
    assert client.app.state.preview_service.recover_stale_jobs() == 1
    client.app.state.preview_service.process_until_idle("recovery-worker")
    recovered = client.app.state.preview_service.status_for_revision(resolved.revision["id"])
    assert recovered["status"] == "completed"
    with client.app.state.database.read() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM preview_sets WHERE revision_id = ? AND status = 'completed'",
            (resolved.revision["id"],),
        ).fetchone()[0] == 1


def test_backfill_dry_run_is_read_only_and_admin_preview_status(admin_client):
    payload = pdf_bytes()
    binding = create_binding(admin_client, payload, "backfill.pdf")
    create_binding(admin_client, b"legacy text content", "legacy.txt")
    before = None
    with admin_client.app.state.database.read() as connection:
        before = connection.execute("SELECT COUNT(*) FROM preview_jobs").fetchone()[0]
    args = type(
        "Args",
        (),
        {
            "revision_key": None,
            "only_current": True,
            "only_published": False,
            "include_history": False,
            "failed_only": False,
            "limit": 10,
        },
    )()
    candidates = find_candidates(admin_client.app.state.database, args)
    assert len(candidates) == 1
    assert candidates[0]["revision_key"] == revision_for(
        admin_client, binding["qr_id"]
    ).revision["revision_key"]
    with admin_client.app.state.database.read() as connection:
        assert connection.execute("SELECT COUNT(*) FROM preview_jobs").fetchone()[0] == before

    detail = admin_client.get(f"/admin/materials/{binding['qr_id']}")
    assert "尚未生成预览" in detail.text
    key = revision_for(admin_client, binding["qr_id"]).revision["revision_key"]
    created = admin_client.post(
        f"/admin/materials/{binding['qr_id']}/versions/{key}/previews",
        data={"csrf_token": csrf_from(detail)},
        follow_redirects=False,
    )
    assert created.status_code == 303
    admin_client.app.state.preview_service.process_until_idle("admin-preview-worker")
    page = admin_client.get(
        f"/admin/materials/{binding['qr_id']}/versions/{key}/previews"
    )
    assert "预览生成完成" in page.text
    assert "preview_key" not in page.text
    student = admin_client.get(f"/q/{binding['qr_id']}")
    assert student.status_code == 200
    derivative = admin_client.get(f"/q/{binding['qr_id']}/pages/1")
    assert derivative.headers["content-type"] == "image/webp"
    assert derivative.content != payload


def test_preview_can_be_required_before_draft_publish(admin_settings):
    protected = replace(admin_settings, require_preview_before_publish=True)
    with TestClient(create_app(admin_settings)) as bootstrap:
        login_admin(bootstrap)
        binding = create_binding(bootstrap, pdf_bytes(), "published.pdf")
    with TestClient(create_app(protected)) as client:
        login_admin(client)
        page = client.get(f"/admin/materials/{binding['qr_id']}/replace")
        created = client.post(
            f"/admin/materials/{binding['qr_id']}/replace",
            data={"csrf_token": csrf_from(page), "content_type": "pdf"},
            files={"file": ("draft.pdf", pdf_bytes(), "application/pdf")},
            follow_redirects=False,
        )
        key = created.headers["location"].split("/drafts/", 1)[1].split("?", 1)[0]
        resolved = client.app.state.resolver_service.resolve_latest(binding["qr_id"])
        draft = client.app.state.revision_service.get_by_key(
            resolved.resource["id"], key
        )
        with client.app.state.database.read() as connection:
            resource = connection.execute(
                "SELECT id, row_version FROM answer_resources WHERE id = ?",
                (resolved.resource["id"],),
            ).fetchone()
        with pytest.raises(AppError) as blocked:
            client.app.state.revision_service.publish(
                resource["id"], draft["id"], resource["row_version"], "test"
            )
        assert blocked.value.code == "PREVIEW_REQUIRED"
        complete_preview(client, draft["id"])
        client.app.state.revision_service.publish(
            resource["id"], draft["id"], resource["row_version"], "test"
        )
