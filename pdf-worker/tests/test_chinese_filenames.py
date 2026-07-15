from urllib.parse import quote

import pytest

from app.responses import content_disposition
from app.storage.local import safe_display_filename
from conftest import create_pdf_job, pdf_bytes


@pytest.mark.parametrize(
    "filename",
    ["高一数学第一章解析.pdf", "物理练习册（必修一）.pdf", "答案 v2 最终版.pdf"],
)
def test_chinese_filename_round_trip(client, filename):
    response = client.post(
        "/bindings",
        files={"file": (filename, pdf_bytes(), "application/pdf")},
    )
    assert response.status_code == 201, response.text
    binding = response.json()
    assert binding["original_filename"] == filename
    download = client.get(f"/r/{binding['qr_id']}")
    disposition = download.headers["content-disposition"]
    assert 'filename="' in disposition
    assert f"filename*=UTF-8''{quote(filename, safe='')}" in disposition


def test_pdf_output_chinese_filename(client):
    binding = client.post(
        "/bindings", files={"file": ("答案.pdf", pdf_bytes(), "application/pdf")}
    ).json()
    response = client.post(
        "/pdf/jobs",
        data={"qr_id": binding["qr_id"]},
        files={"file": ("物理练习册（必修一）.pdf", pdf_bytes(), "application/pdf")},
    )
    output = client.get(f"/pdf/jobs/{response.json()['job_id']}/download")
    assert "filename*=UTF-8''" in output.headers["content-disposition"]
    assert quote("物理练习册（必修一）_with_qr.pdf", safe="") in output.headers["content-disposition"]


def test_filename_sanitization_and_mojibake_repair():
    assert safe_display_filename("../高一数学.pdf") == "高一数学.pdf"
    assert "\n" not in safe_display_filename("bad\nname.pdf")
    assert safe_display_filename("é«˜ä¸€æ•°å­¦.pdf") == "高一数学.pdf"
    header = content_disposition('bad\r\n"name.pdf')
    assert "\r" not in header and "\n" not in header
