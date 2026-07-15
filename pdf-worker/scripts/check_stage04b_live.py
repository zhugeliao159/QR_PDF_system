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

from itsdangerous import URLSafeTimedSerializer


def _admin_headers() -> dict[str, str]:
    secret = os.environ.get("SESSION_SECRET", "")
    if len(secret) < 32:
        raise RuntimeError("SESSION_SECRET is unavailable")
    token = URLSafeTimedSerializer(secret, salt="qr-admin-session-v1").dumps(
        {
            "u": os.environ.get("ADMIN_USERNAME", "admin"),
            "c": secrets.token_urlsafe(32),
            "s": secrets.token_hex(16),
        }
    )
    return {"Cookie": f"qr_admin_session={token}"}


def _request(
    url: str,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, str], bytes]:
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, request, fp, code, msg, headers, newurl):
            return None

    request = urllib.request.Request(url, headers=headers or {})
    opener = urllib.request.build_opener(NoRedirect)
    try:
        with opener.open(request, timeout=30) as response:
            return (
                response.status,
                {key.lower(): value for key, value in response.headers.items()},
                response.read(),
            )
    except urllib.error.HTTPError as exc:
        return (
            exc.code,
            {key.lower(): value for key, value in exc.headers.items()},
            exc.read(),
        )


def check(base_url: str, database_path: Path) -> dict[str, Any]:
    base_url = base_url.rstrip("/")
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    try:
        target = connection.execute(
            """
            SELECT q.public_token, r.id AS resource_id,
                   v.id AS revision_id, v.revision_key,
                   a.size_bytes, a.sha256
            FROM qr_aliases q
            JOIN answer_resources r ON r.id = q.resource_id
            JOIN answer_revisions v ON v.resource_id = r.id
            JOIN assets a ON a.id = v.asset_id
            WHERE q.resolve_mode = 'latest' AND q.status = 'active'
              AND r.status = 'active' AND v.status = 'published'
              AND a.mime_type = 'application/pdf'
              AND EXISTS (
                  SELECT 1
                  FROM answer_revisions cv
                  JOIN assets ca ON ca.id = cv.asset_id
                  WHERE cv.id = r.current_published_revision_id
                    AND ca.mime_type = 'application/pdf'
              )
            ORDER BY v.revision_number ASC
            LIMIT 1
            """
        ).fetchone()
        current = connection.execute(
            """
            SELECT v.revision_key, a.size_bytes, a.sha256
            FROM answer_resources r
            JOIN answer_revisions v ON v.id = r.current_published_revision_id
            JOIN assets a ON a.id = v.asset_id
            WHERE r.id = ?
            """,
            (target["resource_id"],),
        ).fetchone()
    finally:
        connection.close()
    if target is None or current is None:
        raise RuntimeError("no published live fixture is available")

    results: dict[str, Any] = {}
    token = target["public_token"]
    status, headers, body = _request(f"{base_url}/q/{token}")
    results["student_page"] = {
        "status": status,
        "cache_control": headers.get("cache-control"),
        "has_object": b"<object" in body,
        "has_chinese": "当前答案".encode() in body,
        "token_repeated_in_html": token.encode() in body,
    }

    status, headers, _ = _request(f"{base_url}/q/{token}/content")
    location = headers.get("location", "")
    status_current, current_headers, current_body = _request(base_url + location)
    results["latest_content"] = {
        "redirect_status": status,
        "redirect_cache": headers.get("cache-control"),
        "location": location,
        "content_status": status_current,
        "size_matches": len(current_body) == current["size_bytes"],
        "sha256_matches": hashlib.sha256(current_body).hexdigest() == current["sha256"],
        "immutable_cache": current_headers.get("cache-control"),
        "etag": current_headers.get("etag"),
    }
    etag = current_headers.get("etag", "")
    conditional_status, conditional_headers, conditional_body = _request(
        base_url + location, {"If-None-Match": etag}
    )
    results["conditional_get"] = {
        "status": conditional_status,
        "body_size": len(conditional_body),
        "etag": conditional_headers.get("etag"),
    }

    fixed_path = f"/bindings/{token}/versions/{target['revision_id']}/qr.png"
    fixed_status, fixed_headers, _ = _request(base_url + fixed_path, _admin_headers())
    fixed_url = fixed_headers.get("content-location", "")
    pinned_token = fixed_url.rsplit("/", 1)[-1]
    pinned_status, pinned_headers, _ = _request(
        f"{base_url}/q/{pinned_token}/content"
    )
    pinned_location = pinned_headers.get("location", "")
    pinned_file_status, _, pinned_body = _request(base_url + pinned_location)
    results["pinned_alias"] = {
        "qr_status": fixed_status,
        "uses_q": "/q/" in fixed_url,
        "token_is_independent": pinned_token != token,
        "redirect_status": pinned_status,
        "content_status": pinned_file_status,
        "revision_is_pinned": pinned_location
        == f"/content/{target['revision_key']}",
        "size_matches": len(pinned_body) == target["size_bytes"],
        "sha256_matches": hashlib.sha256(pinned_body).hexdigest() == target["sha256"],
    }

    legacy_status, _, legacy_body = _request(f"{base_url}/r/{token}")
    legacy_fixed_status, _, legacy_fixed_body = _request(
        f"{base_url}/r/{token}/versions/{target['revision_id']}"
    )
    results["legacy"] = {
        "dynamic_status": legacy_status,
        "dynamic_sha256_matches": hashlib.sha256(legacy_body).hexdigest()
        == current["sha256"],
        "fixed_status": legacy_fixed_status,
        "fixed_sha256_matches": hashlib.sha256(legacy_fixed_body).hexdigest()
        == target["sha256"],
    }

    passed = (
        results["student_page"]
        == {
            "status": 200,
            "cache_control": "no-store, must-revalidate",
            "has_object": True,
            "has_chinese": True,
            "token_repeated_in_html": False,
        }
        and results["latest_content"]["redirect_status"] == 307
        and results["latest_content"]["redirect_cache"]
        == "no-store, must-revalidate"
        and results["latest_content"]["size_matches"]
        and results["latest_content"]["sha256_matches"]
        and results["latest_content"]["immutable_cache"]
        == "public, max-age=31536000, immutable"
        and results["conditional_get"]["status"] == 304
        and results["conditional_get"]["body_size"] == 0
        and all(results["pinned_alias"].values())
        and results["legacy"]["dynamic_status"] == 200
        and results["legacy"]["dynamic_sha256_matches"]
        and results["legacy"]["fixed_status"] == 200
        and results["legacy"]["fixed_sha256_matches"]
    )
    return {"status": "PASS" if passed else "FAIL", "checks": results}


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Stage 4B against live data")
    parser.add_argument("base_url")
    parser.add_argument("database", type=Path)
    args = parser.parse_args()
    result = check(args.base_url, args.database)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
