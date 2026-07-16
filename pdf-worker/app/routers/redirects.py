from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from app.routers.student import student_headers


router = APIRouter(tags=["legacy preview redirects"])


@router.get("/r/{qr_id}")
def permanent_file(request: Request, qr_id: str) -> RedirectResponse:
    request.app.state.resolver_service.resolve_latest(qr_id)
    return RedirectResponse(
        f"/q/{qr_id}",
        status_code=307,
        headers=student_headers(),
    )


@router.get("/r/{qr_id}/versions/{version_id}")
def fixed_version_file(
    request: Request,
    qr_id: str,
    version_id: int,
) -> RedirectResponse:
    token = request.app.state.binding_service.fixed_alias_token(qr_id, version_id)
    return RedirectResponse(
        f"/q/{token}",
        status_code=307,
        headers=student_headers(),
    )
