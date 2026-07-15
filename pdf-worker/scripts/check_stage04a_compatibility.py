from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import sqlite3
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


def _download_hash(url: str, headers: dict[str, str]) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=30) as response:
        while chunk := response.read(1024 * 1024):
            size += len(chunk)
            digest.update(chunk)
    return size, digest.hexdigest()


def _signed_admin_headers() -> dict[str, str]:
    from itsdangerous import URLSafeTimedSerializer

    secret = os.environ.get("SESSION_SECRET", "")
    if len(secret) < 32:
        raise RuntimeError("SESSION_SECRET is unavailable")
    serializer = URLSafeTimedSerializer(secret, salt="qr-admin-session-v1")
    token = serializer.dumps(
        {
            "u": os.environ.get("ADMIN_USERNAME", "admin"),
            "c": secrets.token_urlsafe(32),
            "s": secrets.token_hex(16),
        }
    )
    return {"Cookie": f"qr_admin_session={token}"}


def check(
    base_url: str,
    database_path: Path,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    base_url = base_url.rstrip("/")
    headers = headers or {}
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    checks: list[dict[str, Any]] = []

    def record(kind: str, identifier: str, path: str, size: int, digest: str) -> None:
        item: dict[str, Any] = {
            "kind": kind,
            "identifier": identifier,
            "path": path,
            "expected_size": size,
            "expected_sha256": digest,
        }
        try:
            actual_size, actual_hash = _download_hash(base_url + path, headers)
            item.update(
                {
                    "actual_size": actual_size,
                    "actual_sha256": actual_hash,
                    "status": (
                        "PASS"
                        if actual_size == size and actual_hash == digest
                        else "FAIL"
                    ),
                }
            )
        except (OSError, urllib.error.URLError) as exc:
            item.update({"status": "FAIL", "error": str(exc)})
        checks.append(item)

    try:
        bindings = connection.execute(
            """
            SELECT b.qr_id, v.size_bytes, v.sha256
            FROM bindings b
            JOIN file_versions v ON v.id = b.current_version_id
            ORDER BY b.id
            """
        ).fetchall()
        for binding in bindings:
            record(
                "legacy_dynamic",
                binding["qr_id"],
                f"/r/{binding['qr_id']}",
                binding["size_bytes"],
                binding["sha256"],
            )

        versions = connection.execute(
            """
            SELECT b.qr_id, v.id, v.size_bytes, v.sha256
            FROM file_versions v
            JOIN bindings b ON b.id = v.binding_id
            ORDER BY v.id
            """
        ).fetchall()
        for version in versions:
            record(
                "legacy_fixed_revision",
                str(version["id"]),
                f"/r/{version['qr_id']}/versions/{version['id']}",
                version["size_bytes"],
                version["sha256"],
            )

        jobs = connection.execute(
            """
            SELECT job_id, output_size_bytes, output_sha256
            FROM pdf_jobs
            WHERE status = 'completed' AND output_sha256 IS NOT NULL
            ORDER BY id
            """
        ).fetchall()
        for job in jobs:
            record(
                "legacy_pdf_job",
                job["job_id"],
                f"/pdf/jobs/{job['job_id']}/download",
                job["output_size_bytes"],
                job["output_sha256"],
            )
    finally:
        connection.close()

    management_checks: list[dict[str, Any]] = []
    for path in ("/capabilities", "/admin"):
        item: dict[str, Any] = {"path": path}
        try:
            request = urllib.request.Request(base_url + path, headers=headers)
            with urllib.request.urlopen(request, timeout=30) as response:
                item["http_status"] = response.status
                item["status"] = "PASS" if response.status == 200 else "FAIL"
        except (OSError, urllib.error.URLError) as exc:
            item.update({"status": "FAIL", "error": str(exc)})
        management_checks.append(item)

    failures = sum(item["status"] != "PASS" for item in checks)
    failures += sum(item["status"] != "PASS" for item in management_checks)
    return {
        "status": "PASS" if failures == 0 else "FAIL",
        "base_url": base_url,
        "total": len(checks),
        "passed": sum(item["status"] == "PASS" for item in checks),
        "failed": sum(item["status"] != "PASS" for item in checks),
        "management_checks": management_checks,
        "checks": checks,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Replay Stage 4A legacy downloads")
    parser.add_argument("base_url")
    parser.add_argument("database", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--signed-admin-session", action="store_true")
    args = parser.parse_args()
    headers = _signed_admin_headers() if args.signed_admin_session else {}
    result = check(args.base_url, args.database, headers)
    payload = json.dumps(result, ensure_ascii=False, indent=2)
    print(payload)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
