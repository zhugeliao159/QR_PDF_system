from __future__ import annotations

from fastapi import APIRouter, File, Form, Request, Response, UploadFile, status

from app.schemas import BindingOut, FileVersionOut


router = APIRouter(prefix="/bindings", tags=["bindings"])


@router.post("", response_model=BindingOut, status_code=status.HTTP_201_CREATED)
async def create_binding(
    request: Request,
    file: UploadFile = File(...),
    note: str | None = Form(None),
) -> dict:
    return await request.app.state.binding_service.create_binding(file, note)


@router.get("/{qr_id}", response_model=BindingOut)
def get_binding(request: Request, qr_id: str) -> dict:
    return request.app.state.binding_service.get_binding(qr_id)


@router.get("/{qr_id}/qr.png")
def get_qr_png(request: Request, qr_id: str) -> Response:
    request.app.state.binding_service.get_binding(qr_id)
    return Response(
        content=request.app.state.qr_service.png(qr_id),
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=3600", "X-Content-Type-Options": "nosniff"},
    )


@router.put("/{qr_id}/file", response_model=BindingOut)
async def replace_binding_file(
    request: Request,
    qr_id: str,
    file: UploadFile = File(...),
    note: str | None = Form(None),
) -> dict:
    return await request.app.state.binding_service.replace_file(qr_id, file, note)


@router.get("/{qr_id}/versions", response_model=list[FileVersionOut])
def list_binding_versions(request: Request, qr_id: str) -> list[dict]:
    return request.app.state.binding_service.list_versions(qr_id)


@router.post("/{qr_id}/rollback/{version_id}", response_model=BindingOut)
def rollback_binding(request: Request, qr_id: str, version_id: int) -> dict:
    return request.app.state.binding_service.rollback(qr_id, version_id)
