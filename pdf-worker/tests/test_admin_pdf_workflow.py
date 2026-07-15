from conftest import create_binding, csrf_from, pdf_bytes


def test_admin_pdf_dynamic_and_fixed_workflow(admin_client):
    binding = create_binding(admin_client, pdf_bytes(), "答案.pdf")
    page = admin_client.get(f"/admin/pdf/new?material={binding['qr_id']}")
    assert binding["title"] in page.text
    assert "自动更新到最新版" in page.text
    assert "锁定当前版本" in page.text
    csrf = csrf_from(page)
    missing_confirmation = admin_client.post(
        "/admin/pdf/new",
        data={
            "csrf_token": csrf, "qr_id": binding["qr_id"], "qr_mode": "dynamic",
            "page": "1", "position": "bottom-right", "size_mm": "20", "margin_mm": "10",
        },
        files={"file": ("练习册.pdf", pdf_bytes(), "application/pdf")},
    )
    assert missing_confirmation.status_code == 422
    assert "仅用于测试" in missing_confirmation.text

    generated = admin_client.post(
        "/admin/pdf/new",
        data={
            "csrf_token": csrf, "qr_id": binding["qr_id"], "qr_mode": "fixed",
            "page": "1", "position": "bottom-right", "size_mm": "20", "margin_mm": "10",
            "test_confirmed": "yes",
        },
        files={"file": ("练习册.pdf", pdf_bytes(), "application/pdf")},
        follow_redirects=False,
    )
    assert generated.status_code == 303, generated.text
    result = admin_client.get(generated.headers["location"])
    assert "练习册二维码已添加" in result.text
    assert "锁定当前版本" in result.text
    assert "任务标识" in result.text
    job_id = generated.headers["location"].rsplit("/", 1)[-1]
    assert admin_client.get(f"/admin/pdf/jobs/{job_id}/preview").headers["content-type"] == "image/png"
    assert admin_client.get(f"/admin/pdf/jobs/{job_id}/download").status_code == 200
