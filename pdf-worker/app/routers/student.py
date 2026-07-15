from __future__ import annotations

from fastapi import APIRouter, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response

from app.errors import AppError
from app.responses import download_response


router = APIRouter(tags=["student answers"])
DYNAMIC_CACHE = "no-store, must-revalidate"
IMMUTABLE_CACHE = "public, max-age=31536000, immutable"


def _student_view(resolved) -> dict:
    resource = resolved.resource
    revision = resolved.revision
    asset = resolved.asset
    return {
        "resource_name": resource["name"],
        "display_code": resource["display_code"],
        "grade": resource["grade"],
        "subject": resource["subject"],
        "chapter": resource["chapter"],
        "revision_number": revision["revision_number"],
        "updated_at": revision["published_at"] or revision["created_at"],
        "content_type": "pdf" if asset["mime_type"] == "application/pdf" else "file",
        "original_filename": asset["original_filename"],
        "mime_type": asset["mime_type"],
        "size_bytes": asset["size_bytes"],
    }


@router.get("/q/{public_token}", response_class=HTMLResponse)
def answer_page(request: Request, public_token: str):
    resolved = request.app.state.resolver_service.resolve_latest(public_token)
    response = request.app.state.templates.TemplateResponse(
        request,
        "student/answer.html",
        {
            "request": request,
            "site_name": request.app.state.settings.site_name,
            "answer": _student_view(resolved),
        },
    )
    response.headers["Cache-Control"] = DYNAMIC_CACHE
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@router.get("/q/{public_token}/content")
def answer_content(
    request: Request,
    public_token: str,
    download: bool = Query(False),
) -> RedirectResponse:
    resolved = request.app.state.resolver_service.resolve_latest(public_token)
    target = f"/content/{resolved.revision['revision_key']}"
    if download:
        target += "?download=true"
    return RedirectResponse(
        target,
        status_code=307,
        headers={"Cache-Control": DYNAMIC_CACHE, "X-Content-Type-Options": "nosniff"},
    )


def _etag_matches(header: str | None, etag: str) -> bool:
    if not header:
        return False
    candidates = {item.strip() for item in header.split(",")}
    return "*" in candidates or etag in candidates or f"W/{etag}" in candidates


@router.get("/content/{revision_key}")
def immutable_content(
    request: Request,
    revision_key: str,
    download: bool = Query(False),
) -> Response:
    resolved = request.app.state.resolver_service.resolve_content(revision_key)
    try:
        path = request.app.state.asset_service.path(resolved.asset)
    except AppError as exc:
        if exc.code == "STORED_FILE_MISSING":
            raise AppError(503, "ASSET_MISSING", "answer asset is unavailable") from exc
        raise
    etag = f'"{resolved.asset["sha256"]}"'
    headers = {
        "Cache-Control": IMMUTABLE_CACHE,
        "ETag": etag,
        "X-Content-Type-Options": "nosniff",
    }
    if _etag_matches(request.headers.get("if-none-match"), etag):
        return Response(status_code=304, headers=headers)
    inline = not download and (
        resolved.asset["mime_type"] == "application/pdf"
        or resolved.asset["mime_type"].startswith("image/")
    )
    response = download_response(
        path,
        resolved.asset["original_filename"],
        resolved.asset["mime_type"],
        "inline" if inline else "attachment",
        IMMUTABLE_CACHE,
    )
    response.headers["ETag"] = etag
    return response
