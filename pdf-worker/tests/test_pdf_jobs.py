import hashlib
from io import BytesIO

import fitz
import pytest

from conftest import create_binding, create_pdf_job, pdf_bytes


@pytest.mark.parametrize(
    "position", ["top-left", "top-right", "bottom-left", "bottom-right"]
)
def test_pdf_job_writes_qr_to_each_corner(client, position):
    binding = create_binding(client)
    response = create_pdf_job(client, binding["qr_id"], position=position)
    assert response.status_code == 201, response.text
    job = response.json()
    assert job["status"] == "completed"
    assert job["position"] == position
    assert len(job["output_sha256"]) == 64

    download = client.get(f"/pdf/jobs/{job['job_id']}/download")
    assert download.status_code == 200
    assert hashlib.sha256(download.content).hexdigest() == job["output_sha256"]
    with fitz.open(stream=download.content, filetype="pdf") as document:
        assert document.page_count == 1
        page = document[0]
        images = page.get_images(full=True)
        assert images
        rects = page.get_image_rects(images[-1][0])
        assert rects
        center = rects[-1].irect.tl + (rects[-1].irect.br - rects[-1].irect.tl) / 2
        left = center.x < page.rect.width / 2
        top = center.y < page.rect.height / 2
        assert left == position.endswith("left")
        assert top == position.startswith("top")


def test_pdf_job_uses_selected_page_and_survives_rotation(client):
    binding = create_binding(client)
    response = create_pdf_job(
        client,
        binding["qr_id"],
        content=pdf_bytes(pages=2, rotation=90),
        page=2,
        position="top-right",
    )
    assert response.status_code == 201, response.text
    output = client.get(response.json()["download_url"].split("test.local:18081")[-1])
    with fitz.open(stream=output.content, filetype="pdf") as document:
        assert not document[0].get_images()
        assert document[1].get_images()


def test_job_query_and_missing_download(client):
    assert client.get("/pdf/jobs/unknown").status_code == 404
    binding = create_binding(client)
    job = create_pdf_job(client, binding["qr_id"]).json()
    assert client.get(f"/pdf/jobs/{job['job_id']}").json() == job
