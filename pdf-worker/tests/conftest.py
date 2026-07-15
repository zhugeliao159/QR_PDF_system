from __future__ import annotations

from io import BytesIO

import fitz
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.config import Settings
from app.main import create_app


@pytest.fixture
def settings(tmp_path):
    return Settings(
        public_base_url="http://test.local:18081",
        max_upload_size_mb=1,
        max_pdf_pages=5,
        max_binding_versions=5,
        default_qr_size_mm=20,
        default_qr_margin_mm=10,
        database_path=tmp_path / "db" / "app.db",
        storage_root=tmp_path / "storage",
        input_dir=tmp_path / "input",
        output_dir=tmp_path / "output",
    )


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings)) as test_client:
        yield test_client


def pdf_bytes(pages=1, width=595, height=842, rotation=0):
    document = fitz.open()
    for number in range(1, pages + 1):
        page = document.new_page(width=width, height=height)
        page.insert_text((72, 72), f"Exercise page {number}")
        if rotation:
            page.set_rotation(rotation)
    data = document.tobytes()
    document.close()
    return data


def encrypted_pdf_bytes():
    document = fitz.open()
    document.new_page()
    data = document.tobytes(
        encryption=fitz.PDF_ENCRYPT_AES_256,
        owner_pw="owner",
        user_pw="secret",
    )
    document.close()
    return data


def png_bytes(color="red"):
    output = BytesIO()
    Image.new("RGB", (16, 16), color=color).save(output, format="PNG")
    return output.getvalue()


def create_binding(client, content=b"answer-v1", filename="answer.txt"):
    response = client.post(
        "/bindings",
        files={"file": (filename, content, "application/octet-stream")},
    )
    assert response.status_code == 201, response.text
    return response.json()


def create_pdf_job(client, qr_id, content=None, **fields):
    data = {
        "qr_id": qr_id,
        "page": "1",
        "position": "bottom-right",
        "size_mm": "20",
        "margin_mm": "10",
    }
    data.update({key: str(value) for key, value in fields.items()})
    return client.post(
        "/pdf/jobs",
        data=data,
        files={"file": ("exercise.pdf", content or pdf_bytes(), "application/pdf")},
    )
