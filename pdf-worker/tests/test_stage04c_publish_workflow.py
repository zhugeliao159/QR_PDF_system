from __future__ import annotations

import re
import threading
from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient

from app.main import create_app
from app.errors import AppError
from conftest import create_binding, csrf_from, login_admin


def create_admin_draft(client, qr_id: str, content: bytes, filename: str = "draft.txt"):
    page = client.get(f"/admin/materials/{qr_id}/replace")
    response = client.post(
        f"/admin/materials/{qr_id}/replace",
        data={"csrf_token": csrf_from(page), "note": "待审核答案"},
        files={"file": (filename, content, "text/plain")},
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text
    match = re.search(r"/drafts/([a-f0-9]+)", response.headers["location"])
    assert match
    return match.group(1)


def row_version_from(response) -> int:
    match = re.search(r'name="page_state" value="(\d+)"', response.text)
    assert match, response.text
    return int(match.group(1))


def test_admin_upload_creates_private_draft_without_changing_student_answer(admin_client):
    binding = create_binding(admin_client, b"published-v1", "v1.txt")
    qr_id = binding["qr_id"]
    old_revision_key = admin_client.app.state.resolver_service.resolve_latest(
        qr_id
    ).revision["revision_key"]

    draft_key = create_admin_draft(admin_client, qr_id, b"draft-v2", "v2.txt")

    assert admin_client.get(f"/q/{qr_id}/content", follow_redirects=True).content == b"published-v1"
    assert admin_client.get(f"/content/{old_revision_key}").content == b"published-v1"
    assert admin_client.get(f"/content/{draft_key}").status_code == 404
    preview = admin_client.get(f"/admin/materials/{qr_id}/drafts/{draft_key}")
    assert preview.status_code == 200
    assert "此草稿尚未发布" in preview.text
    assert admin_client.get(
        f"/admin/materials/{qr_id}/drafts/{draft_key}/file"
    ).content == b"draft-v2"

    with admin_client.app.state.database.read() as connection:
        resource = connection.execute(
            "SELECT current_published_revision_id FROM answer_resources"
        ).fetchone()
        draft = connection.execute(
            "SELECT id, status FROM answer_revisions WHERE revision_key = ?",
            (draft_key,),
        ).fetchone()
        assert draft["status"] == "draft"
        assert resource["current_published_revision_id"] != draft["id"]


def test_draft_preview_requires_login(admin_settings):
    with TestClient(create_app(admin_settings)) as client:
        login_admin(client)
        binding = create_binding(client, b"published")
        draft_key = create_admin_draft(client, binding["qr_id"], b"draft")
        client.post(
            "/admin/logout",
            data={"csrf_token": csrf_from(client.get("/admin"))},
        )
        response = client.get(
            f"/admin/materials/{binding['qr_id']}/drafts/{draft_key}",
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert response.headers["location"] == "/admin/login"


def test_publish_atomically_switches_dynamic_answer_and_preserves_old_content(admin_client):
    binding = create_binding(admin_client, b"published-v1", "v1.txt")
    qr_id = binding["qr_id"]
    old_revision_key = admin_client.app.state.resolver_service.resolve_latest(
        qr_id
    ).revision["revision_key"]
    fixed_token = admin_client.app.state.binding_service.fixed_alias_token(
        qr_id, binding["current_version"]["version_id"]
    )
    draft_key = create_admin_draft(admin_client, qr_id, b"published-v2", "v2.txt")
    preview = admin_client.get(f"/admin/materials/{qr_id}/drafts/{draft_key}")

    response = admin_client.post(
        f"/admin/materials/{qr_id}/drafts/{draft_key}/publish",
        data={
            "csrf_token": csrf_from(preview),
            "page_state": row_version_from(preview),
        },
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text
    assert admin_client.get(f"/q/{qr_id}/content", follow_redirects=True).content == b"published-v2"
    assert admin_client.get(f"/content/{old_revision_key}").content == b"published-v1"
    assert admin_client.get(f"/q/{fixed_token}/content", follow_redirects=True).content == b"published-v1"

    with admin_client.app.state.database.read() as connection:
        draft = connection.execute(
            "SELECT status, published_at FROM answer_revisions WHERE revision_key = ?",
            (draft_key,),
        ).fetchone()
        assert draft["status"] == "published"
        assert draft["published_at"]
        assert connection.execute(
            "SELECT COUNT(*) FROM audit_events WHERE event_type = 'publish_revision'"
        ).fetchone()[0] == 1


def test_missing_asset_blocks_publish_and_keeps_current(admin_client):
    binding = create_binding(admin_client, b"published-v1")
    qr_id = binding["qr_id"]
    draft_key = create_admin_draft(admin_client, qr_id, b"draft-v2")
    preview = admin_client.get(f"/admin/materials/{qr_id}/drafts/{draft_key}")
    draft = admin_client.app.state.binding_service.draft_details(qr_id, draft_key)
    with admin_client.app.state.database.read() as connection:
        storage_key = connection.execute(
            """SELECT a.storage_key FROM answer_revisions v
               JOIN assets a ON a.id = v.asset_id WHERE v.revision_key = ?""",
            (draft_key,),
        ).fetchone()["storage_key"]
    admin_client.app.state.storage.delete(storage_key)

    response = admin_client.post(
        f"/admin/materials/{qr_id}/drafts/{draft_key}/publish",
        data={
            "csrf_token": csrf_from(preview),
            "page_state": draft["row_version"],
        },
    )
    assert response.status_code == 503
    assert "答案文件不存在" in response.text
    assert admin_client.get(f"/q/{qr_id}/content", follow_redirects=True).content == b"published-v1"
    with admin_client.app.state.database.read() as connection:
        assert connection.execute(
            "SELECT status FROM answer_revisions WHERE revision_key = ?", (draft_key,)
        ).fetchone()["status"] == "draft"


def test_stale_concurrent_publish_returns_chinese_conflict(admin_client):
    binding = create_binding(admin_client, b"published-v1")
    qr_id = binding["qr_id"]
    first_key = create_admin_draft(admin_client, qr_id, b"draft-v2")
    second_key = create_admin_draft(admin_client, qr_id, b"draft-v3")
    first_page = admin_client.get(f"/admin/materials/{qr_id}/drafts/{first_key}")
    second_page = admin_client.get(f"/admin/materials/{qr_id}/drafts/{second_key}")
    expected = row_version_from(first_page)
    assert row_version_from(second_page) == expected

    first = admin_client.post(
        f"/admin/materials/{qr_id}/drafts/{first_key}/publish",
        data={"csrf_token": csrf_from(first_page), "page_state": expected},
        follow_redirects=False,
    )
    second = admin_client.post(
        f"/admin/materials/{qr_id}/drafts/{second_key}/publish",
        data={"csrf_token": csrf_from(second_page), "page_state": expected},
    )
    assert first.status_code == 303
    assert second.status_code == 409
    assert "刚刚被其他管理员更新" in second.text
    assert admin_client.get(f"/q/{qr_id}/content", follow_redirects=True).content == b"draft-v2"


def test_two_publish_threads_allow_only_one_winner(admin_client):
    binding = create_binding(admin_client, b"published-v1")
    qr_id = binding["qr_id"]
    first_key = create_admin_draft(admin_client, qr_id, b"draft-v2")
    second_key = create_admin_draft(admin_client, qr_id, b"draft-v3")
    with admin_client.app.state.database.read() as connection:
        resource = connection.execute(
            "SELECT id, row_version FROM answer_resources"
        ).fetchone()
        revisions = {
            row["revision_key"]: row["id"]
            for row in connection.execute(
                "SELECT id, revision_key FROM answer_revisions WHERE status = 'draft'"
            ).fetchall()
        }
    barrier = threading.Barrier(2)

    def publish(revision_key: str):
        barrier.wait()
        try:
            admin_client.app.state.revision_service.publish(
                resource["id"],
                revisions[revision_key],
                resource["row_version"],
                "concurrency-test",
            )
            return "published"
        except AppError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(publish, [first_key, second_key]))
    assert sorted(outcomes) == ["RESOURCE_CONFLICT", "published"]
    with admin_client.app.state.database.read() as connection:
        current = connection.execute(
            "SELECT current_published_revision_id, row_version FROM answer_resources"
        ).fetchone()
        assert current["current_published_revision_id"] in revisions.values()
        assert current["row_version"] == resource["row_version"] + 1


def test_republish_history_reuses_revision_and_keeps_pinned_answer(admin_client):
    binding = create_binding(admin_client, b"published-v1")
    qr_id = binding["qr_id"]
    first_id = binding["current_version"]["version_id"]
    first_key = admin_client.app.state.resolver_service.resolve_latest(
        qr_id
    ).revision["revision_key"]
    fixed_token = admin_client.app.state.binding_service.fixed_alias_token(qr_id, first_id)
    second_key = create_admin_draft(admin_client, qr_id, b"published-v2")
    second_page = admin_client.get(f"/admin/materials/{qr_id}/drafts/{second_key}")
    admin_client.post(
        f"/admin/materials/{qr_id}/drafts/{second_key}/publish",
        data={
            "csrf_token": csrf_from(second_page),
            "page_state": row_version_from(second_page),
        },
    )
    versions_page = admin_client.get(f"/admin/materials/{qr_id}/versions")
    with admin_client.app.state.database.read() as connection:
        before = (
            connection.execute("SELECT COUNT(*) FROM answer_revisions").fetchone()[0],
            connection.execute("SELECT COUNT(*) FROM assets").fetchone()[0],
        )

    response = admin_client.post(
        f"/admin/materials/{qr_id}/versions/{first_key}/republish",
        data={
            "csrf_token": csrf_from(versions_page),
            "page_state": row_version_from(versions_page),
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert admin_client.get(f"/q/{qr_id}/content", follow_redirects=True).content == b"published-v1"
    assert admin_client.get(f"/q/{fixed_token}/content", follow_redirects=True).content == b"published-v1"
    with admin_client.app.state.database.read() as connection:
        after = (
            connection.execute("SELECT COUNT(*) FROM answer_revisions").fetchone()[0],
            connection.execute("SELECT COUNT(*) FROM assets").fetchone()[0],
        )
        assert before == after
        assert connection.execute(
            "SELECT COUNT(*) FROM audit_events WHERE event_type = 'republish_revision'"
        ).fetchone()[0] == 1


def test_discard_draft_removes_orphan_asset_and_keeps_current(admin_client):
    binding = create_binding(admin_client, b"published-v1")
    qr_id = binding["qr_id"]
    draft_key = create_admin_draft(admin_client, qr_id, b"discard-me")
    page = admin_client.get(f"/admin/materials/{qr_id}/drafts/{draft_key}")
    with admin_client.app.state.database.read() as connection:
        candidate = connection.execute(
            """SELECT v.id, v.asset_id, a.storage_key FROM answer_revisions v
               JOIN assets a ON a.id = v.asset_id WHERE v.revision_key = ?""",
            (draft_key,),
        ).fetchone()

    response = admin_client.post(
        f"/admin/materials/{qr_id}/drafts/{draft_key}/discard",
        data={"csrf_token": csrf_from(page)},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert admin_client.get(f"/q/{qr_id}/content", follow_redirects=True).content == b"published-v1"
    assert not admin_client.app.state.storage.resolve(
        candidate["storage_key"], must_exist=False
    ).exists()
    with admin_client.app.state.database.read() as connection:
        assert connection.execute(
            "SELECT 1 FROM answer_revisions WHERE id = ?", (candidate["id"],)
        ).fetchone() is None
        assert connection.execute(
            "SELECT 1 FROM assets WHERE id = ?", (candidate["asset_id"],)
        ).fetchone() is None
        event = connection.execute(
            "SELECT revision_id FROM audit_events WHERE event_type = 'discard_draft'"
        ).fetchone()
        assert event is not None and event["revision_id"] is None


def test_discard_draft_keeps_asset_referenced_by_another_revision(admin_client):
    binding = create_binding(admin_client, b"published-v1")
    qr_id = binding["qr_id"]
    first_key = create_admin_draft(admin_client, qr_id, b"shared-content")
    second_key = create_admin_draft(admin_client, qr_id, b"temporary-content")
    with admin_client.app.state.database.transaction() as connection:
        first = connection.execute(
            """SELECT v.asset_id, a.storage_key FROM answer_revisions v
               JOIN assets a ON a.id = v.asset_id WHERE v.revision_key = ?""",
            (first_key,),
        ).fetchone()
        second = connection.execute(
            """SELECT v.asset_id, a.storage_key FROM answer_revisions v
               JOIN assets a ON a.id = v.asset_id WHERE v.revision_key = ?""",
            (second_key,),
        ).fetchone()
        connection.execute(
            "UPDATE answer_revisions SET asset_id = ? WHERE revision_key = ?",
            (first["asset_id"], second_key),
        )
        connection.execute("DELETE FROM assets WHERE id = ?", (second["asset_id"],))
    admin_client.app.state.storage.delete(second["storage_key"])
    page = admin_client.get(f"/admin/materials/{qr_id}/drafts/{first_key}")

    response = admin_client.post(
        f"/admin/materials/{qr_id}/drafts/{first_key}/discard",
        data={"csrf_token": csrf_from(page)},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert admin_client.app.state.storage.resolve(first["storage_key"]).is_file()
    with admin_client.app.state.database.read() as connection:
        assert connection.execute(
            "SELECT 1 FROM assets WHERE id = ?", (first["asset_id"],)
        ).fetchone() is not None
        assert connection.execute(
            "SELECT asset_id FROM answer_revisions WHERE revision_key = ?", (second_key,)
        ).fetchone()["asset_id"] == first["asset_id"]


def test_legacy_put_uses_draft_publish_audit_and_still_requires_auth(admin_settings):
    with TestClient(create_app(admin_settings)) as client:
        unauthorized = client.put(
            "/bindings/not-authorized/file",
            files={"file": ("v2.txt", b"v2", "text/plain")},
        )
        assert unauthorized.status_code == 401
        login_admin(client)
        binding = create_binding(client, b"v1")
        response = client.put(
            f"/bindings/{binding['qr_id']}/file",
            files={"file": ("v2.txt", b"v2", "text/plain")},
        )
        assert response.status_code == 200
        assert client.get(f"/q/{binding['qr_id']}/content", follow_redirects=True).content == b"v2"
        with client.app.state.database.read() as connection:
            events = {
                row["event_type"]
                for row in connection.execute(
                    "SELECT event_type FROM audit_events ORDER BY id"
                ).fetchall()
            }
        assert "create_draft" in events
        assert "legacy_immediate_publish" in events


def test_chinese_admin_pages_use_publish_terms(admin_client):
    binding = create_binding(admin_client, b"v1")
    detail = admin_client.get(f"/admin/materials/{binding['qr_id']}")
    assert "当前已发布答案" in detail.text
    assert "新建答案版本" in detail.text
    assert "草稿版本" in detail.text
    assert "历史已发布版本" in detail.text
    assert "rollback" not in detail.text
    assert "revision_id" not in detail.text
    assert "row_version" not in detail.text
