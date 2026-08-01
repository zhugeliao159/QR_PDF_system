from __future__ import annotations

import argparse
import ipaddress
import os
import re
import secrets
import string
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlsplit


PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR / "pdf-worker"))

from app.auth.password import hash_password  # noqa: E402


ADMIN_USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")


def parse_env(path: Path) -> tuple[list[str], dict[str, str]]:
    lines = path.read_text(encoding="utf-8").splitlines()
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


def validate_public_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("public URL must use http:// or https:// and include a host")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("public URL must not contain credentials, query, or fragment")
    if parsed.path not in {"", "/"}:
        raise ValueError("public URL must not contain a path")
    return value.strip().rstrip("/")


def initial_password(length: int = 24) -> str:
    alphabet = string.ascii_letters + string.digits + "!@#%_-"
    while True:
        value = "".join(secrets.choice(alphabet) for _ in range(length))
        if (
            any(char.islower() for char in value)
            and any(char.isupper() for char in value)
            and any(char.isdigit() for char in value)
            and any(char in "!@#%_-" for char in value)
        ):
            return value


def atomic_write(path: Path, content: str, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def create_password_file(path: Path, password: str) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
        stream.write(password + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create or safely complete QRPDF deployment configuration."
    )
    parser.add_argument("env_file", type=Path)
    parser.add_argument("--template", type=Path, required=True)
    parser.add_argument("--password-output", type=Path, required=True)
    parser.add_argument("--public-url", required=True)
    parser.add_argument("--admin-username", default="admin")
    parser.add_argument("--bind-address", default="127.0.0.1")
    parser.add_argument("--site-name", default="练习册二维码管理系统")
    args = parser.parse_args()

    try:
        public_url = validate_public_url(args.public_url)
        ipaddress.ip_address(args.bind_address)
    except ValueError as exc:
        parser.error(str(exc))
    if not ADMIN_USERNAME_PATTERN.fullmatch(args.admin_username):
        parser.error("admin username may contain only letters, digits, dot, dash, underscore")
    if not args.site_name.strip() or any(char in args.site_name for char in "\r\n="):
        parser.error("site name must be one non-empty line without '='")
    if not args.template.is_file():
        parser.error(f"template not found: {args.template}")

    source = args.env_file if args.env_file.exists() else args.template
    lines, values = parse_env(source)
    password: str | None = None
    admin_hash = values.get("ADMIN_PASSWORD_HASH", "").strip()
    if not admin_hash:
        if args.password_output.exists():
            parser.error(
                f"password output already exists while ADMIN_PASSWORD_HASH is empty: "
                f"{args.password_output}"
            )
        password = initial_password()
        admin_hash = hash_password(password)

    secure = "true" if urlsplit(public_url).scheme == "https" else "false"
    updates = {
        "PUBLIC_BASE_URL": public_url,
        "PUBLIC_QR_BASE_URL": public_url,
        "PDF_WORKER_BIND_ADDRESS": args.bind_address,
        "SITE_NAME": args.site_name.strip(),
        "ADMIN_USERNAME": args.admin_username,
        "ADMIN_PASSWORD_HASH": admin_hash,
        "SESSION_SECRET": values.get("SESSION_SECRET", "").strip()
        or secrets.token_urlsafe(48),
        "VIEWER_SESSION_SECRET": values.get("VIEWER_SESSION_SECRET", "").strip()
        or secrets.token_urlsafe(48),
        "SESSION_COOKIE_SECURE": values.get("SESSION_COOKIE_SECURE", "").strip()
        or "false",
        "VIEWER_COOKIE_SECURE": secure,
    }

    if password is not None:
        create_password_file(args.password_output, password)
    try:
        atomic_write(args.env_file, "\n".join(update_lines(lines, updates)) + "\n")
    except Exception:
        if password is not None:
            print(
                f"configuration write failed; securely remove {args.password_output} "
                "before retrying",
                file=sys.stderr,
            )
        raise

    print(f"Configuration ready: {args.env_file}")
    if password is not None:
        print(f"One-time admin password file created: {args.password_output}")
    else:
        print("Existing administrator credential preserved; no password file created.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
