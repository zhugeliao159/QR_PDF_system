from __future__ import annotations

import argparse
import os
import secrets
import string
import sys
import tempfile
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.auth.password import hash_password  # noqa: E402


def parse_env(path: Path) -> tuple[list[str], dict[str, str]]:
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    values: dict[str, str] = {}
    for line in lines:
        if line and not line.lstrip().startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key] = value
    return lines, values


def update_lines(lines: list[str], updates: dict[str, str]) -> list[str]:
    output: list[str] = []
    remaining = dict(updates)
    for line in lines:
        if line and not line.lstrip().startswith("#") and "=" in line:
            key = line.split("=", 1)[0]
            if key in remaining:
                output.append(f"{key}={remaining.pop(key)}")
                continue
        output.append(line)
    output.extend(f"{key}={value}" for key, value in remaining.items())
    return output


def initial_password(length: int = 22) -> str:
    alphabet = string.ascii_letters + string.digits + "!@#%_-"
    while True:
        value = "".join(secrets.choice(alphabet) for _ in range(length))
        if any(char.islower() for char in value) and any(char.isupper() for char in value) \
                and any(char.isdigit() for char in value) and any(char in "!@#%_-" for char in value):
            return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("env_file", type=Path)
    parser.add_argument("password_output", type=Path)
    args = parser.parse_args()
    lines, values = parse_env(args.env_file)
    if values.get("ADMIN_PASSWORD_HASH") or values.get("SESSION_SECRET"):
        print("管理员安全配置已存在，未覆盖。")
        return 2
    if args.password_output.exists():
        print("密码临时文件已存在，拒绝覆盖。", file=sys.stderr)
        return 3
    password = initial_password()
    updates = {
        "SITE_NAME": values.get("SITE_NAME") or "练习册二维码管理系统",
        "PDF_WORKER_BIND_ADDRESS": values.get("PDF_WORKER_BIND_ADDRESS") or "127.0.0.1",
        "PUBLIC_QR_BASE_URL": values.get("PUBLIC_QR_BASE_URL") or values.get("PUBLIC_BASE_URL") or "http://127.0.0.1:18081",
        "ADMIN_USERNAME": values.get("ADMIN_USERNAME") or "admin",
        "ADMIN_PASSWORD_HASH": hash_password(password),
        "ADMIN_API_TOKEN_HASH": values.get("ADMIN_API_TOKEN_HASH") or "",
        "SESSION_SECRET": secrets.token_urlsafe(48),
        "SESSION_COOKIE_SECURE": values.get("SESSION_COOKIE_SECURE") or "false",
        "SESSION_MAX_AGE_SECONDS": values.get("SESSION_MAX_AGE_SECONDS") or "28800",
        "ENABLE_ADMIN_API_DOCS": values.get("ENABLE_ADMIN_API_DOCS") or "false",
    }
    args.env_file.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(prefix=".env-stage03-", dir=args.env_file.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write("\n".join(update_lines(lines, updates)) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temp_name, 0o600)
        os.replace(temp_name, args.env_file)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)
    descriptor = os.open(args.password_output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.write(password + "\n")
    print("管理员安全配置已初始化；明文密码未输出。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
