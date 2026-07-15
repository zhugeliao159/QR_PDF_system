from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse

from app.responses import download_response


router = APIRouter(tags=["permanent redirect"])


@router.get("/r/{qr_id}")
def permanent_file(request: Request, qr_id: str) -> FileResponse:
    path, original_filename, mime_type = request.app.state.binding_service.current_file(
        qr_id
    )
    inline = mime_type == "application/pdf" or mime_type.startswith("image/")
    return download_response(
        path, original_filename, mime_type,
        "inline" if inline else "attachment",
        "no-cache, no-store, must-revalidate",
    )


@router.get("/r/{qr_id}/versions/{version_id}")
def fixed_version_file(
    request: Request, qr_id: str, version_id: int
) -> FileResponse:
    path, original_filename, mime_type = request.app.state.binding_service.version_file(
        qr_id, version_id
    )
    inline = mime_type == "application/pdf" or mime_type.startswith("image/")
    return download_response(
        path, original_filename, mime_type,
        "inline" if inline else "attachment",
        "public, max-age=3600, must-revalidate",
    )
