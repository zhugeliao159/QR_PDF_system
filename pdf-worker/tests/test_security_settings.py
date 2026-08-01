from dataclasses import replace

from fastapi.testclient import TestClient

from app.auth.password import hash_password, verify_password
from app.auth.session import COOKIE_NAME
from app.database import Database
from app.main import create_app
from conftest import csrf_from, login_admin


def test_admin_password_can_be_changed_in_web_and_invalidates_old_session(admin_settings):
    app = create_app(admin_settings)
    with TestClient(app) as client:
        login_admin(client)
        old_cookie = client.cookies.get(COOKIE_NAME)
        page = client.get("/admin/security")
        assert page.status_code == 200
        assert "安全设置" in page.text

        response = client.post(
            "/admin/security/admin-password",
            data={
                "csrf_token": csrf_from(page),
                "current_admin_password": "Stage03TestPassword!",
                "new_admin_password": "NewAdminPassword!2026",
                "confirm_admin_password": "NewAdminPassword!2026",
            },
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert response.headers["location"] == "/admin/login?password_changed=1"

        client.cookies.set(COOKIE_NAME, old_cookie)
        stale = client.get("/admin", follow_redirects=False)
        assert stale.status_code == 303
        assert stale.headers["location"] == "/admin/login"

        old_login = client.post(
            "/admin/login",
            data={"username": "admin", "password": "Stage03TestPassword!"},
        )
        assert old_login.status_code == 401
        new_login = client.post(
            "/admin/login",
            data={"username": "admin", "password": "NewAdminPassword!2026"},
            follow_redirects=False,
        )
        assert new_login.status_code == 303

        with app.state.database.read() as connection:
            stored = connection.execute(
                """
                SELECT password_hash, revision
                FROM security_credentials
                WHERE credential_key = 'admin_password'
                """
            ).fetchone()
            audit_count = connection.execute(
                "SELECT COUNT(*) FROM audit_events WHERE event_type = 'admin_password_changed'"
            ).fetchone()[0]
        assert stored["revision"] == 1
        assert "NewAdminPassword!2026" not in stored["password_hash"]
        assert verify_password("NewAdminPassword!2026", stored["password_hash"])
        assert audit_count == 1

    with TestClient(create_app(admin_settings)) as restarted:
        persisted = restarted.post(
            "/admin/login",
            data={"username": "admin", "password": "NewAdminPassword!2026"},
            follow_redirects=False,
        )
        assert persisted.status_code == 303


def test_deletion_password_change_requires_both_current_passwords(admin_settings):
    settings = replace(
        admin_settings,
        deletion_password_hash=hash_password("OldDeletionPassword!2026"),
    )
    app = create_app(settings)
    with TestClient(app) as client:
        login_admin(client)
        page = client.get("/admin/security")
        csrf = csrf_from(page)
        rejected = client.post(
            "/admin/security/deletion-password",
            data={
                "csrf_token": csrf,
                "current_admin_password": "Stage03TestPassword!",
                "current_deletion_password": "wrong",
                "new_deletion_password": "NewDeletionPassword!2026",
                "confirm_deletion_password": "NewDeletionPassword!2026",
            },
        )
        assert rejected.status_code == 401

        page = client.get("/admin/security")
        changed = client.post(
            "/admin/security/deletion-password",
            data={
                "csrf_token": csrf_from(page),
                "current_admin_password": "Stage03TestPassword!",
                "current_deletion_password": "OldDeletionPassword!2026",
                "new_deletion_password": "NewDeletionPassword!2026",
                "confirm_deletion_password": "NewDeletionPassword!2026",
            },
        )
        assert changed.status_code == 200
        assert "永久删除二级密码已修改" in changed.text
        assert app.state.credential_service.verify_deletion("NewDeletionPassword!2026")
        assert not app.state.credential_service.verify_deletion("OldDeletionPassword!2026")


def test_security_settings_rejects_csrf_and_short_password(admin_settings):
    with TestClient(create_app(admin_settings)) as client:
        login_admin(client)
        csrf_rejected = client.post(
            "/admin/security/admin-password",
            data={
                "csrf_token": "bad",
                "current_admin_password": "Stage03TestPassword!",
                "new_admin_password": "NewAdminPassword!2026",
                "confirm_admin_password": "NewAdminPassword!2026",
            },
        )
        assert csrf_rejected.status_code == 403

        page = client.get("/admin/security")
        short = client.post(
            "/admin/security/admin-password",
            data={
                "csrf_token": csrf_from(page),
                "current_admin_password": "Stage03TestPassword!",
                "new_admin_password": "too-short",
                "confirm_admin_password": "too-short",
            },
        )
        assert short.status_code == 422
        assert "至少需要 16 个字符" in short.text


def test_v7_database_migrates_security_credentials_with_backup(tmp_path):
    path = tmp_path / "db" / "app.db"
    database = Database(path)
    database.initialize()
    with database.connect() as connection:
        connection.execute("DROP TABLE security_credentials")
        connection.execute("PRAGMA user_version = 7")
        connection.commit()

    migrated = Database(path)
    migrated.initialize()
    assert migrated.last_backup_path is not None
    assert "web-password-settings-v7" in migrated.last_backup_path.name
    with migrated.read() as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 8
        columns = {
            row["name"]
            for row in connection.execute(
                "PRAGMA table_info(security_credentials)"
            ).fetchall()
        }
    assert {"credential_key", "password_hash", "revision"} <= columns
