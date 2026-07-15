import pytest

from conftest import (
    create_binding,
    create_pdf_job,
    encrypted_pdf_bytes,
    pdf_bytes,
)


@pytest.mark.parametrize(
    ("fields", "code"),
    [
        ({"page": 0}, "PDF_PAGE_OUT_OF_RANGE"),
        ({"position": "middle"}, "INVALID_QR_POSITION"),
        ({"size_mm": 9}, "INVALID_QR_SIZE"),
        ({"size_mm": 51}, "INVALID_QR_SIZE"),
        ({"margin_mm": -1}, "INVALID_QR_MARGIN"),
        ({"margin_mm": 51}, "INVALID_QR_MARGIN"),
    ],
)
def test_parameter_validation(client, fields, code):
    binding = create_binding(client)
    response = create_pdf_job(client, binding["qr_id"], **fields)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == code


def test_page_range_and_page_too_small(client):
    binding = create_binding(client)
    outside = create_pdf_job(client, binding["qr_id"], page=2)
    assert outside.status_code == 422
    assert outside.json()["error"]["code"] == "PDF_PAGE_OUT_OF_RANGE"
    too_small = create_pdf_job(
        client,
        binding["qr_id"],
        content=pdf_bytes(width=100, height=100),
        size_mm=50,
        margin_mm=10,
    )
    assert too_small.status_code == 422
    assert too_small.json()["error"]["code"] == "QR_DOES_NOT_FIT_PAGE"


@pytest.mark.parametrize(
    ("content", "filename", "mime", "code"),
    [
        (b"not a pdf", "exercise.pdf", "application/pdf", "INVALID_PDF_FILE"),
        (b"%PDF-broken", "exercise.pdf", "application/pdf", "INVALID_PDF_FILE"),
        (pdf_bytes(), "exercise.bin", "application/pdf", "PDF_EXTENSION_REQUIRED"),
        (pdf_bytes(), "exercise.pdf", "text/plain", "PDF_MIME_TYPE_REQUIRED"),
        (encrypted_pdf_bytes(), "exercise.pdf", "application/pdf", "PDF_ENCRYPTED"),
    ],
)
def test_invalid_pdf_creates_failed_job(client, content, filename, mime, code):
    binding = create_binding(client)
    response = client.post(
        "/pdf/jobs",
        data={"qr_id": binding["qr_id"]},
        files={"file": (filename, content, mime)},
    )
    assert response.status_code in {415, 422}
    error = response.json()["error"]
    assert error["code"] == code
    job_id = error["details"]["job_id"]
    job = client.get(f"/pdf/jobs/{job_id}").json()
    assert job["status"] == "failed"
    assert job["error_code"] == code
    assert client.get(f"/pdf/jobs/{job_id}/download").status_code == 409


def test_empty_and_oversized_uploads(client):
    binding = create_binding(client)
    empty = client.post(
        "/pdf/jobs",
        data={"qr_id": binding["qr_id"]},
        files={"file": ("exercise.pdf", b"", "application/pdf")},
    )
    assert empty.status_code == 400
    assert empty.json()["error"]["code"] == "EMPTY_FILE"
    oversized = client.post(
        "/pdf/jobs",
        data={"qr_id": binding["qr_id"]},
        files={"file": ("exercise.pdf", b"x" * (1024 * 1024 + 1), "application/pdf")},
    )
    assert oversized.status_code == 413
    assert oversized.json()["error"]["code"] == "UPLOAD_TOO_LARGE"


def test_pdf_page_limit(client):
    binding = create_binding(client)
    response = create_pdf_job(client, binding["qr_id"], content=pdf_bytes(pages=6))
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "PDF_TOO_MANY_PAGES"
