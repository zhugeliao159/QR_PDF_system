from __future__ import annotations

from urllib.parse import urlsplit

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from app.errors import AppError
from app.responses import download_response


router = APIRouter(tags=["student answers"])
STUDENT_CACHE = "private, no-store, max-age=0"
STUDENT_CSP = (
    "default-src 'self'; img-src 'self' blob:; style-src 'self'; "
    "script-src 'self'; connect-src 'self'; frame-ancestors 'none'; "
    "object-src 'none'; base-uri 'none'"
)


def student_headers(*, csp: bool = False) -> dict[str, str]:
    headers = {
        "Cache-Control": STUDENT_CACHE,
        "Pragma": "no-cache",
        "Referrer-Policy": "no-referrer",
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
    }
    if csp:
        headers["Content-Security-Policy"] = STUDENT_CSP
    return headers


def _student_view(
    resolved, public_token: str, bundle: dict | None = None, trace_code: str = ""
) -> dict:
    resource = resolved.resource
    revision = resolved.revision
    view = {
        "public_token": public_token,
        "resource_name": resource["name"],
        "display_code": resource["display_code"],
        "grade": resource["grade"],
        "subject": resource["subject"],
        "chapter": resource["chapter"],
        "revision_number": revision["revision_number"],
        "updated_at": revision["published_at"] or revision["created_at"],
        "content_type": revision["content_kind"],
        "page_count": 0,
        "pages": [],
        "trace_code": trace_code,
    }
    if bundle is not None:
        view["page_count"] = bundle["preview"]["page_count"]
        view["pages"] = [
            {
                "page_number": page["page_number"],
                "width": page["width"],
                "height": page["height"],
            }
            for page in bundle["pages"]
        ]
    if revision["target_type"] == "external_url":
        view["external_host"] = urlsplit(revision["external_url"]).hostname or "外部网站"
    return view


def _session_preview(request: Request, public_token: str):
    raw_token = request.cookies.get(request.app.state.settings.viewer_cookie_name)
    session = request.app.state.viewer_session_service.validate(public_token, raw_token)
    resolved = request.app.state.resolver_service.resolve_revision(
        public_token, session["revision_id"]
    )
    if resolved.revision["target_type"] != "file" or resolved.asset is None:
        raise AppError(
            403,
            "PREVIEW_EXTERNAL_UNAVAILABLE",
            "external content is not a private preview",
        )
    bundle = request.app.state.preview_service.completed_preview(
        resolved.revision["id"],
        resolved.asset["id"],
        resolved.asset["sha256"],
    )
    return session, resolved, bundle


@router.get("/q/{public_token}", response_class=HTMLResponse)
def answer_page(request: Request, public_token: str):
    resolved = request.app.state.resolver_service.resolve_latest(public_token)
    bundle = None
    external_policy = request.app.state.settings.protected_preview_external_url_policy
    if resolved.revision["target_type"] == "file":
        if resolved.asset is None:
            raise AppError(503, "ASSET_MISSING", "answer asset is unavailable")
        bundle = request.app.state.preview_service.completed_preview(
            resolved.revision["id"],
            resolved.asset["id"],
            resolved.asset["sha256"],
        )
    raw_session, viewer = request.app.state.viewer_session_service.create(
        resolved,
        request.headers.get("user-agent"),
        request.client.host if request.client else None,
    )
    response = request.app.state.templates.TemplateResponse(
        request,
        "student/answer.html",
        {
            "request": request,
            "site_name": request.app.state.settings.site_name,
            "answer": _student_view(resolved, public_token, bundle, viewer["trace_code"]),
            "external_policy": external_policy,
        },
    )
    response.headers.update(student_headers(csp=True))
    response.set_cookie(
        key=request.app.state.settings.viewer_cookie_name,
        value=raw_session,
        max_age=request.app.state.settings.viewer_session_ttl_minutes * 60,
        httponly=True,
        secure=request.app.state.settings.viewer_cookie_secure,
        samesite="lax",
        path="/",
    )
    return response


@router.get("/q/{public_token}/manifest")
def answer_manifest(request: Request, public_token: str) -> JSONResponse:
    session, resolved, bundle = _session_preview(request, public_token)
    request.app.state.viewer_session_service.manifest_access(session)
    return JSONResponse(
        {
            "page_count": bundle["preview"]["page_count"],
            "revision_display": f"第 {resolved.revision['revision_number']} 版",
            "content_kind": resolved.revision["content_kind"],
            "generated_at": bundle["preview"]["completed_at"],
        },
        headers=student_headers(),
    )


@router.get("/q/{public_token}/pages/{page_number}")
def answer_preview_page(
    request: Request,
    public_token: str,
    page_number: int,
) -> Response:
    session, resolved, _ = _session_preview(request, public_token)
    if resolved.revision["target_type"] != "file" or resolved.asset is None:
        raise AppError(404, "PREVIEW_PAGE_NOT_FOUND", "preview page does not exist")
    path, _ = request.app.state.preview_service.student_page(
        resolved.revision["id"],
        resolved.asset["id"],
        resolved.asset["sha256"],
        page_number,
    )
    with request.app.state.viewer_session_service.page_access(session, page_number):
        content = request.app.state.watermark_service.render(
            path, resolved.resource["display_code"], session["trace_code"]
        )
    return Response(
        content=content,
        media_type="image/webp",
        headers={**student_headers(), "Content-Disposition": "inline"},
    )


@router.get("/q/{public_token}/content")
def answer_content(request: Request, public_token: str) -> RedirectResponse:
    resolved = request.app.state.resolver_service.resolve_latest(public_token)
    if resolved.revision["target_type"] == "external_url":
        policy = request.app.state.settings.protected_preview_external_url_policy
        if policy == "disable":
            raise AppError(
                403,
                "PREVIEW_EXTERNAL_DISABLED",
                "external content is disabled for protected preview",
            )
        validated = request.app.state.external_url_validator.validate(
            resolved.revision["external_url"]
        )
        return RedirectResponse(validated.url, status_code=307, headers=student_headers())
    return RedirectResponse(
        f"/q/{public_token}",
        status_code=307,
        headers=student_headers(),
    )


@router.get("/content/{revision_key}")
def immutable_content(
    request: Request,
    revision_key: str,
    download: bool = Query(False),
) -> Response:
    if getattr(request.state, "admin", None) is None:
        raise AppError(
            403,
            "ORIGINAL_ADMIN_ONLY",
            "original files are available only to administrators",
        )
    resolved = request.app.state.resolver_service.resolve_content(revision_key)
    try:
        path = request.app.state.asset_service.path(resolved.asset)
    except AppError as exc:
        if exc.code == "STORED_FILE_MISSING":
            raise AppError(503, "ASSET_MISSING", "answer asset is unavailable") from exc
        raise
    response = download_response(
        path,
        resolved.asset["original_filename"],
        resolved.asset["mime_type"],
        "attachment" if download else "inline",
        STUDENT_CACHE,
    )
    response.headers.update(student_headers())
    return response
