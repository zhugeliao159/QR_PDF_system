from __future__ import annotations

from dataclasses import replace

from fastapi.testclient import TestClient

from app.auth.password import hash_password
from app.admin.routes import DELETION_ATTEMPTS, DELETION_LOCKED_UNTIL
from app.main import create_app
from conftest import csrf_from, login_admin, pdf_bytes


def _run_batch(client: TestClient, batch_key: str) -> dict:
    batch_service = client.app.state.batch_import_service
    preview_service = client.app.state.preview_service
    for _ in range(30):
        worked = batch_service.finalize_next()
        worked = batch_service.process_next("test-batch-worker") or worked
        worked = preview_service.process_next("test-preview-worker") or worked
        batch = batch_service.get_batch(batch_key)
        if batch["status"] == "completed":
            return batch
        assert worked
    raise AssertionError("batch did not complete")


def test_batch_upload_uses_pdf_names_and_smallest_suffix(admin_client):
    create_page = admin_client.get("/admin/materials/new")
    create_csrf = csrf_from(create_page)
    existing = admin_client.post(
        "/admin/materials/new",
        data={"csrf_token": create_csrf, "title": "答案", "grade": "未分类", "subject": "未分类"},
        files={"file": ("existing.pdf", pdf_bytes(), "application/pdf")},
        follow_redirects=False,
    )
    assert existing.status_code == 303

    page = admin_client.get("/admin/materials/import")
    csrf = csrf_from(page)
    response = admin_client.post(
        "/admin/materials/import",
        data={"csrf_token": csrf, "grade": "高一", "subject": "数学"},
        files=[
            ("files", ("答案.pdf", pdf_bytes(), "application/pdf")),
            ("files", ("答案.pdf", pdf_bytes(), "application/pdf")),
        ],
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text
    batch_key = response.headers["location"].rsplit("/", 1)[-1]
    batch = _run_batch(admin_client, batch_key)
    assert [item["resolved_title"] for item in batch["items"]] == ["答案(1)", "答案(2)"]
    assert all(item["status"] == "completed" for item in batch["items"])
    listing = admin_client.get("/admin/materials", params={"q": "答案(2)", "page_size": 100})
    assert listing.status_code == 200
    assert "答案(2)" in listing.text


def test_batch_partial_failure_does_not_leave_failed_resource(admin_client):
    csrf = csrf_from(admin_client.get("/admin/materials/import"))
    response = admin_client.post(
        "/admin/materials/import",
        data={"csrf_token": csrf, "grade": "未分类", "subject": "未分类"},
        files=[
            ("files", ("正常.pdf", pdf_bytes(), "application/pdf")),
            ("files", ("损坏.pdf", b"not-a-pdf", "application/pdf")),
        ],
        follow_redirects=False,
    )
    batch_key = response.headers["location"].rsplit("/", 1)[-1]
    batch = _run_batch(admin_client, batch_key)
    assert batch["counts"]["completed"] == 1
    assert batch["counts"]["failed"] == 1
    with admin_client.app.state.database.read() as connection:
        assert connection.execute("SELECT COUNT(*) FROM answer_resources").fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM batch_import_items WHERE status = 'failed' AND resource_id IS NULL"
        ).fetchone()[0] == 1


def test_batch_rejects_more_than_configured_file_count(admin_settings):
    limited = replace(admin_settings, batch_upload_max_files=1)
    with TestClient(create_app(limited)) as client:
        login_admin(client)
        csrf = csrf_from(client.get("/admin/materials/import"))
        response = client.post(
            "/admin/materials/import",
            data={"csrf_token": csrf},
            files=[
                ("files", ("one.pdf", pdf_bytes(), "application/pdf")),
                ("files", ("two.pdf", pdf_bytes(), "application/pdf")),
            ],
        )
        assert response.status_code == 422
        assert "最多上传 1 份" in response.text


def test_batch_accepts_100_and_rejects_101_files(admin_client):
    content = pdf_bytes()
    csrf = csrf_from(admin_client.get("/admin/materials/import"))
    accepted = admin_client.post(
        "/admin/materials/import",
        data={"csrf_token": csrf},
        files=[("files", (f"答案-{number}.pdf", content, "application/pdf")) for number in range(100)],
        follow_redirects=False,
    )
    assert accepted.status_code == 303
    batch_key = accepted.headers["location"].rsplit("/", 1)[-1]
    assert admin_client.app.state.batch_import_service.get_batch(batch_key)["total_items"] == 100

    csrf = csrf_from(admin_client.get("/admin/materials/import"))
    rejected = admin_client.post(
        "/admin/materials/import",
        data={"csrf_token": csrf},
        files=[("files", (f"超限-{number}.pdf", content, "application/pdf")) for number in range(101)],
    )
    assert rejected.status_code == 422
    assert "最多上传 100 份" in rejected.text


def test_batch_enforces_total_size_limit(admin_settings):
    limited = replace(admin_settings, batch_upload_max_total_mb=1)
    with TestClient(create_app(limited)) as client:
        login_admin(client)
        csrf = csrf_from(client.get("/admin/materials/import"))
        oversized = b"%PDF-1.7\n" + (b"x" * 600_000)
        response = client.post(
            "/admin/materials/import",
            data={"csrf_token": csrf},
            files=[
                ("files", ("one.pdf", oversized, "application/pdf")),
                ("files", ("two.pdf", oversized, "application/pdf")),
            ],
        )
        assert response.status_code == 413
        with client.app.state.database.read() as connection:
            assert connection.execute("SELECT COUNT(*) FROM batch_imports").fetchone()[0] == 0


def test_permanent_delete_requires_secondary_password_and_skips_references(admin_settings):
    secured = replace(
        admin_settings,
        deletion_password_hash=hash_password("Stage06DeletePassword!"),
    )
    with TestClient(create_app(secured)) as client:
        login_admin(client)
        created = []
        for title in ("可删除答案", "受保护答案"):
            csrf = csrf_from(client.get("/admin/materials/new"))
            response = client.post(
                "/admin/materials/new",
                data={"csrf_token": csrf, "title": title, "grade": "未分类", "subject": "未分类"},
                files={"file": (f"{title}.pdf", pdf_bytes(), "application/pdf")},
                follow_redirects=False,
            )
            token = response.headers["location"].split("/")[3].split("?")[0]
            created.append(token)
        protected = client.app.state.resolver_service.resolve_latest(created[1])
        with client.app.state.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO revision_references
                    (revision_id, reference_type, source_job_id, created_at)
                VALUES (?, 'manual_pin', '', '2026-01-01T00:00:00Z')
                """,
                (protected.revision["id"],),
            )

        list_page = client.get("/admin/materials")
        csrf = csrf_from(list_page)
        confirm = client.post(
            "/admin/materials/delete/confirm",
            data={"csrf_token": csrf, "qr_ids": created},
        )
        confirm_csrf = csrf_from(confirm)
        wrong = client.post(
            "/admin/materials/delete/apply",
            data={
                "csrf_token": confirm_csrf,
                "qr_ids": created,
                "deletion_password": "wrong password",
                "confirmation": "永久删除",
            },
        )
        assert wrong.status_code == 401
        assert client.app.state.resolver_service.resolve_latest(created[0]).resource["name"] == "可删除答案"

        correct_csrf = csrf_from(wrong)
        result = client.post(
            "/admin/materials/delete/apply",
            data={
                "csrf_token": correct_csrf,
                "qr_ids": created,
                "deletion_password": "Stage06DeletePassword!",
                "confirmation": "永久删除",
            },
        )
        assert result.status_code == 200
        assert "已永久删除" in result.text
        assert "存在固定二维码或版本引用" in result.text
        assert client.get(f"/q/{created[0]}").status_code == 404
        assert client.app.state.resolver_service.resolve_latest(created[1]).resource["name"] == "受保护答案"


def test_public_app_excludes_management_surfaces(settings):
    with TestClient(create_app(settings, public_only=True)) as client:
        assert client.get("/health").json()["service"] == "student-public"
        assert client.get("/admin", follow_redirects=False).status_code == 404
        assert client.get("/admin/login", follow_redirects=False).status_code == 404
        assert client.get("/bindings", follow_redirects=False).status_code == 404
        assert client.get("/pdf/jobs", follow_redirects=False).status_code == 404
        assert client.get("/capabilities", follow_redirects=False).status_code == 404
        assert client.get("/content/missing").status_code == 404
        assert client.get("/static/css/student.css").status_code == 200
        assert client.get("/static/js/student.js").status_code == 200
        assert client.get("/static/css/admin.css").status_code == 404
        assert client.get("/static/js/admin.js").status_code == 404


def test_deletion_password_failures_are_audited_and_rate_limited(admin_settings):
    DELETION_ATTEMPTS.clear()
    DELETION_LOCKED_UNTIL.clear()
    secured = replace(
        admin_settings,
        deletion_password_hash=hash_password("Stage06DeletePassword!"),
    )
    with TestClient(create_app(secured)) as client:
        login_admin(client)
        csrf = csrf_from(client.get("/admin/materials"))
        confirm = client.post(
            "/admin/materials/delete/confirm",
            data={"csrf_token": csrf, "qr_ids": "missing-token"},
        )
        csrf = csrf_from(confirm)
        for _ in range(5):
            response = client.post(
                "/admin/materials/delete/apply",
                data={
                    "csrf_token": csrf,
                    "qr_ids": "missing-token",
                    "deletion_password": "wrong password",
                    "confirmation": "永久删除",
                },
            )
            assert response.status_code == 401
            csrf = csrf_from(response)
        locked = client.post(
            "/admin/materials/delete/apply",
            data={
                "csrf_token": csrf,
                "qr_ids": "missing-token",
                "deletion_password": "Stage06DeletePassword!",
                "confirmation": "永久删除",
            },
        )
        assert locked.status_code == 429
        with client.app.state.database.read() as connection:
            assert connection.execute(
                "SELECT COUNT(*) FROM audit_events WHERE event_type = 'permanent_delete_auth_failed'"
            ).fetchone()[0] == 5
    DELETION_ATTEMPTS.clear()
    DELETION_LOCKED_UNTIL.clear()
