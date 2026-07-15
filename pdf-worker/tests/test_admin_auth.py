from dataclasses import replace

from fastapi.testclient import TestClient

from app.auth.session import COOKIE_NAME, SessionManager
from app.main import create_app
from conftest import csrf_from, login_admin


def test_admin_requires_login_and_login_is_chinese(admin_settings):
    with TestClient(create_app(admin_settings)) as client:
        redirect = client.get("/admin", follow_redirects=False)
        assert redirect.status_code == 303
        assert redirect.headers["location"] == "/admin/login"
        page = client.get("/admin/login")
        assert "管理员登录" in page.text
        assert "练习册二维码管理系统" in page.text
        failed = client.post(
            "/admin/login", data={"username": "admin", "password": "wrong"}
        )
        assert failed.status_code == 401
        assert "账号或密码不正确" in failed.text


def test_session_cookie_logout_and_csrf(admin_settings):
    with TestClient(create_app(admin_settings)) as client:
        response = login_admin(client)
        cookie = response.headers["set-cookie"]
        assert "HttpOnly" in cookie
        assert "SameSite=lax" in cookie
        assert "Max-Age=28800" in cookie
        dashboard = client.get("/admin")
        csrf = csrf_from(dashboard)
        rejected = client.post("/admin/logout", data={"csrf_token": "bad"})
        assert rejected.status_code == 403
        assert "页面已过期" in rejected.text
        logout = client.post(
            "/admin/logout", data={"csrf_token": csrf}, follow_redirects=False
        )
        assert logout.status_code == 303
        assert client.get("/admin", follow_redirects=False).status_code == 303


def test_csrf_is_bound_to_session(admin_settings):
    with TestClient(create_app(admin_settings)) as first, TestClient(
        create_app(admin_settings)
    ) as second:
        login_admin(first)
        login_admin(second)
        first_csrf = csrf_from(first.get("/admin"))
        response = second.post("/admin/logout", data={"csrf_token": first_csrf})
        assert response.status_code == 403


def test_management_api_is_protected_and_docs_hidden(admin_settings):
    with TestClient(create_app(admin_settings)) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/bindings/missing").status_code == 401
        assert client.get("/capabilities").status_code == 401
        assert client.get("/docs").status_code == 404
        assert client.get("/openapi.json").status_code == 404
        login_admin(client)
        assert client.get("/bindings/missing").status_code == 404
        assert client.get("/capabilities").status_code == 200


def test_expired_session_returns_to_login(admin_settings):
    expired_settings = replace(admin_settings, session_max_age_seconds=-1)
    manager = SessionManager(expired_settings)
    token, _ = manager.create("admin")
    with TestClient(create_app(expired_settings)) as client:
        client.cookies.set(COOKIE_NAME, token)
        response = client.get("/admin", follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/admin/login"
