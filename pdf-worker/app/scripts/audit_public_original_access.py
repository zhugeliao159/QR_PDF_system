from __future__ import annotations

import hashlib
import http.cookiejar
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from app.config import Settings
from app.database import Database


@dataclass(frozen=True)
class HttpResult:
    status_code: int
    content: bytes
    headers: dict[str, str]
    url: str


class UrlClient:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
        )

    def get(self, path: str, **_: Any) -> HttpResult:
        request = urllib.request.Request(self.base_url + path, method="GET")
        try:
            response = self.opener.open(request, timeout=20)
        except urllib.error.HTTPError as error:
            return HttpResult(
                error.code,
                error.read(),
                {key.lower(): value for key, value in error.headers.items()},
                error.geturl(),
            )
        with response:
            return HttpResult(
                response.status,
                response.read(),
                {key.lower(): value for key, value in response.headers.items()},
                response.geturl(),
            )


def public_get_routes(application) -> list[str]:
    routes: list[str] = []
    for route in application.routes:
        methods = getattr(route, "methods", set()) or set()
        path = getattr(route, "path", "")
        if "GET" in methods and not path.startswith(("/admin", "/bindings", "/pdf/jobs", "/capabilities")):
            routes.append(path)
    return sorted(set(routes))


def active_test_target(database: Database) -> dict[str, Any]:
    with database.read() as connection:
        row = connection.execute(
            """
            SELECT q.public_token, q.resolve_mode, v.revision_key, v.id AS revision_id,
                   a.asset_key, a.storage_key, a.sha256, a.mime_type, a.size_bytes
            FROM qr_aliases q
            JOIN answer_resources r ON r.id = q.resource_id
            JOIN answer_revisions v ON v.id = CASE
                WHEN q.resolve_mode = 'pinned' THEN q.pinned_revision_id
                ELSE r.current_published_revision_id
            END
            JOIN assets a ON a.id = v.asset_id
            JOIN preview_sets s ON s.revision_id = v.id AND s.source_asset_id = a.id
                AND s.source_sha256 = a.sha256 AND s.status = 'completed'
            WHERE q.status = 'active' AND r.status = 'active'
              AND a.mime_type IN ('application/pdf', 'image/png', 'image/jpeg', 'image/webp')
            ORDER BY q.resolve_mode, q.id LIMIT 1
            """
        ).fetchone()
    if row is None:
        raise RuntimeError("没有可用于公开原件审计的 active 预览版本")
    return dict(row)


def _result(response) -> HttpResult:
    return HttpResult(
        response.status_code,
        response.content,
        {key.lower(): value for key, value in response.headers.items()},
        str(response.url),
    )


def audit_client(client, target: dict[str, Any], storage_root: str) -> tuple[bool, list[str]]:
    token = target["public_token"]
    paths = [
        f"/q/{token}/manifest",
        f"/q/{token}/pages/1",
        f"/q/{token}",
        f"/q/{token}/manifest",
        f"/q/{token}/pages/1",
        f"/q/{token}/content",
        f"/content/{target['revision_key']}",
        f"/admin/revisions/{target['revision_key']}/original",
        f"/r/{token}",
        "/static/css/student.css",
        "/static/js/student.js",
    ]
    responses: list[tuple[str, HttpResult]] = []
    for path in paths:
        responses.append((path, _result(client.get(path))))

    failures: list[str] = []
    direct_manifest, direct_page = responses[0][1], responses[1][1]
    if direct_manifest.status_code != 401 or direct_page.status_code != 401:
        failures.append("无 Viewer Session 的 manifest/page 未被拒绝")
    if responses[2][1].status_code != 200:
        failures.append("学生主入口不可用")
    if responses[3][1].status_code != 200 or responses[4][1].status_code != 200:
        failures.append("合法 Viewer Session 无法读取预览")
    if responses[6][1].status_code != 403:
        failures.append("匿名 /content 未返回 403")

    forbidden = [
        target["sha256"],
        target["storage_key"],
        target["asset_key"],
        storage_root,
        f"/admin/revisions/{target['revision_key']}/original",
    ]
    original_sha = target["sha256"]
    for path, response in responses:
        combined = response.content + "\n".join(
            f"{key}: {value}" for key, value in response.headers.items()
        ).encode("utf-8", errors="replace")
        text = combined.decode("utf-8", errors="replace")
        for marker in forbidden:
            if marker and marker in text:
                failures.append(f"{path} 泄露内部标识：{marker[:24]}")
        content_type = response.headers.get("content-type", "").lower()
        if content_type.startswith("application/pdf"):
            failures.append(f"{path} 匿名返回 application/pdf")
        if response.content and hashlib.sha256(response.content).hexdigest() == original_sha:
            failures.append(f"{path} 匿名返回原始 Asset 字节")
        if path.endswith("/pages/1") and response.status_code == 200:
            if not content_type.startswith("image/webp"):
                failures.append("预览页不是 WebP 衍生内容")
    lines = [f"检查 {len(responses)} 个公开/越权请求"]
    lines.extend(failures)
    if not failures:
        lines.append("匿名响应未发现原始 PDF、原始图片、内部路径或原件下载地址")
    return not failures, lines


def main() -> int:
    from app.main import app

    settings = Settings.from_env()
    target = active_test_target(Database(settings.database_path))
    print("公开 GET 路由：")
    for path in public_get_routes(app):
        print(f"- {path}")
    ok, lines = audit_client(
        UrlClient(settings.public_base_url), target, str(settings.storage_root)
    )
    for line in lines:
        print(line)
    print("PASS：匿名学生无法获得原始 Asset。" if ok else "FAIL：公开响应存在原件泄露风险。")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
