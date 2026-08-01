from __future__ import annotations

from fastapi.testclient import TestClient

from conftest import csrf_from, pdf_bytes


def _reserve(client: TestClient, filename: str, content: bytes) -> dict:
    page = client.get("/admin/materials/import")
    response = client.post(
        "/admin/materials/import/reserve",
        json={
            "csrf_token": csrf_from(page),
            "files": [{"filename": filename, "size": len(content)}],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _upload(client: TestClient, reserved: dict, filename: str, content: bytes) -> None:
    csrf = csrf_from(client.get("/admin/materials/import"))
    response = client.post(
        reserved["items"][0]["upload_url"],
        data={"csrf_token": csrf},
        files={"file": (filename, content, "application/pdf")},
    )
    assert response.status_code == 200, response.text


def _finish(client: TestClient, batch_key: str) -> dict:
    batch_service = client.app.state.batch_import_service
    preview_service = client.app.state.preview_service
    for _ in range(30):
        worked = batch_service.finalize_next()
        worked = batch_service.process_next("test-batch") or worked
        worked = preview_service.process_next("test-preview") or worked
        batch = batch_service.get_batch(batch_key)
        if batch["status"] == "completed":
            return batch
        assert worked
    raise AssertionError("batch did not complete")


def test_qr_is_persisted_before_upload_and_same_name_reuses_it(admin_client):
    first_pdf = pdf_bytes(1)
    first = _reserve(admin_client, "代数答案.pdf", first_pdf)
    qr_id = first["items"][0]["qr_id"]

    batch = admin_client.app.state.batch_import_service.get_batch(first["batch_key"])
    assert batch["items"][0]["status"] == "waiting_upload"
    assert admin_client.get(f"/q/{qr_id}").status_code == 202
    qr_response = admin_client.get(first["items"][0]["qr_download_url"])
    assert qr_response.status_code == 200
    qr_path = admin_client.app.state.settings.qr_codes_dir / f"{qr_id}.png"
    assert qr_path.read_bytes() == qr_response.content

    _upload(admin_client, first, "代数答案.pdf", first_pdf)
    completed = _finish(admin_client, first["batch_key"])
    assert completed["counts"]["completed"] == 1
    original = admin_client.app.state.binding_service.get_binding(qr_id)
    assert original["title"] == "代数答案"
    assert admin_client.get(f"/q/{qr_id}").status_code == 200

    second_pdf = pdf_bytes(2)
    second = _reserve(admin_client, "代数答案.PDF", second_pdf)
    assert second["items"][0]["qr_id"] == qr_id
    assert admin_client.get(f"/q/{qr_id}").status_code == 200
    _upload(admin_client, second, "代数答案.PDF", second_pdf)
    _finish(admin_client, second["batch_key"])

    updated = admin_client.app.state.binding_service.get_binding(qr_id)
    assert updated["sha256"] != original["sha256"]
    assert qr_path.read_bytes() == qr_response.content


def test_failed_same_name_replacement_keeps_current_file(admin_client):
    good_pdf = pdf_bytes()
    first = _reserve(admin_client, "稳定内容.pdf", good_pdf)
    _upload(admin_client, first, "稳定内容.pdf", good_pdf)
    _finish(admin_client, first["batch_key"])
    qr_id = first["items"][0]["qr_id"]
    original = admin_client.app.state.binding_service.get_binding(qr_id)

    broken = b"not-a-pdf"
    replacement = _reserve(admin_client, "稳定内容.pdf", broken)
    _upload(admin_client, replacement, "稳定内容.pdf", broken)
    batch = _finish(admin_client, replacement["batch_key"])
    assert batch["counts"]["failed"] == 1
    current = admin_client.app.state.binding_service.get_binding(qr_id)
    assert current["sha256"] == original["sha256"]
    assert admin_client.get(f"/q/{qr_id}").status_code == 200


def test_upload_ui_contains_only_filename_workflow(admin_client):
    page = admin_client.get("/admin/materials/import")
    assert "生成二维码并开始上传" in page.text
    assert 'name="grade"' not in page.text
    assert 'name="subject"' not in page.text
    assert 'name="title"' not in page.text

    pdf_page = admin_client.get("/admin/pdf/new")
    assert 'value="fixed"' not in pdf_page.text
    assert "永久二维码" in pdf_page.text


def test_single_upload_api_uses_filename_and_replaces_same_name(client):
    first = client.post(
        "/bindings",
        files={"file": ("单份答案.pdf", pdf_bytes(1), "application/pdf")},
    )
    assert first.status_code == 201, first.text
    original = first.json()
    second = client.post(
        "/bindings",
        files={"file": ("单份答案.PDF", pdf_bytes(2), "application/pdf")},
    )
    assert second.status_code == 201, second.text
    updated = second.json()
    assert updated["qr_id"] == original["qr_id"]
    assert updated["title"] == "单份答案"
    assert updated["sha256"] != original["sha256"]
