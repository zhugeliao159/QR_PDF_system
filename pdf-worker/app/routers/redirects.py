from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, RedirectResponse, Response

from app.responses import download_response


router = APIRouter(tags=["permanent redirect"])


def _legacy_answer(
    request: Request, resolved, cache_control: str
) -> FileResponse | RedirectResponse:
    if resolved.revision["target_type"] == "external_url":
        validated = request.app.state.external_url_validator.validate(
            resolved.revision["external_url"]
        )
        return RedirectResponse(
            validated.url,
            status_code=307,
            headers={"Cache-Control": "no-store, must-revalidate", "Referrer-Policy": "no-referrer"},
        )
    path = request.app.state.asset_service.path(resolved.asset)
    original_filename = resolved.asset["original_filename"]
    mime_type = resolved.asset["mime_type"]
    inline = mime_type == "application/pdf" or mime_type.startswith("image/")
    return download_response(
        path, original_filename, mime_type,
        "inline" if inline else "attachment",
        cache_control,
    )


@router.get("/r/{qr_id}")
def permanent_file(request: Request, qr_id: str) -> Response:
    return _legacy_answer(
        request,
        request.app.state.resolver_service.resolve_latest(qr_id),
        "no-cache, no-store, must-revalidate",
    )


@router.get("/r/{qr_id}/versions/{version_id}")
def fixed_version_file(
    request: Request, qr_id: str, version_id: int
) -> Response:
    return _legacy_answer(
        request,
        request.app.state.resolver_service.resolve_revision(qr_id, version_id),
        "public, max-age=3600, must-revalidate",
    )
