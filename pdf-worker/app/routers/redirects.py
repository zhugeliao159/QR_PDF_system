from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse


router = APIRouter(tags=["permanent redirect"])


@router.get("/r/{qr_id}")
def permanent_file(request: Request, qr_id: str) -> FileResponse:
    path, original_filename, mime_type = request.app.state.binding_service.current_file(
        qr_id
    )
    inline = mime_type == "application/pdf" or mime_type.startswith("image/")
    return FileResponse(
        path,
        media_type=mime_type,
        filename=original_filename,
        content_disposition_type="inline" if inline else "attachment",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "X-Content-Type-Options": "nosniff",
        },
    )
