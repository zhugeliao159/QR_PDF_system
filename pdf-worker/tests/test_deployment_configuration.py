from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import pytest

from app.auth.password import verify_password


def load_configurator():
    path = Path(__file__).parents[2] / "scripts" / "configure_deployment.py"
    spec = importlib.util.spec_from_file_location("configure_deployment", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def parse_values(path: Path) -> dict[str, str]:
    return {
        key: value
        for line in path.read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#") and "=" in line
        for key, value in [line.split("=", 1)]
    }


def test_configurator_generates_secure_values_and_preserves_them(tmp_path, monkeypatch):
    module = load_configurator()
    template = Path(__file__).parents[2] / ".env.example"
    env_file = tmp_path / ".env"
    password_file = tmp_path / ".initial-admin-password"
    arguments = [
        "configure_deployment.py",
        str(env_file),
        "--template",
        str(template),
        "--password-output",
        str(password_file),
        "--public-url",
        "https://qr.example.com",
        "--admin-username",
        "maintainer",
        "--bind-address",
        "127.0.0.1",
        "--site-name",
        "QRPDF Test",
    ]
    monkeypatch.setattr(sys, "argv", arguments)
    assert module.main() == 0

    values = parse_values(env_file)
    password = password_file.read_text(encoding="utf-8").strip()
    assert verify_password(password, values["ADMIN_PASSWORD_HASH"])
    assert len(values["SESSION_SECRET"]) >= 32
    assert len(values["VIEWER_SESSION_SECRET"]) >= 32
    assert values["PUBLIC_BASE_URL"] == "https://qr.example.com"
    assert values["PUBLIC_QR_BASE_URL"] == "https://qr.example.com"
    assert values["SESSION_COOKIE_SECURE"] == "false"
    assert values["VIEWER_COOKIE_SECURE"] == "true"
    if os.name != "nt":
        assert env_file.stat().st_mode & 0o777 == 0o600
        assert password_file.stat().st_mode & 0o777 == 0o600

    original_hash = values["ADMIN_PASSWORD_HASH"]
    original_session_secret = values["SESSION_SECRET"]
    monkeypatch.setattr(sys, "argv", arguments)
    assert module.main() == 0
    values = parse_values(env_file)
    assert values["ADMIN_PASSWORD_HASH"] == original_hash
    assert values["SESSION_SECRET"] == original_session_secret


def test_configurator_rejects_public_url_with_credentials(tmp_path, monkeypatch):
    module = load_configurator()
    template = Path(__file__).parents[2] / ".env.example"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "configure_deployment.py",
            str(tmp_path / ".env"),
            "--template",
            str(template),
            "--password-output",
            str(tmp_path / "password"),
            "--public-url",
            "https://user:password@example.invalid",
        ],
    )
    with pytest.raises(SystemExit):
        module.main()
