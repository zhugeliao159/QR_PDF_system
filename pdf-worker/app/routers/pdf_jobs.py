from __future__ import annotations

from fastapi import APIRouter, File, Form, Request, UploadFile, status
from fastapi.responses import FileResponse

from app.schemas import PdfJobOut
from app.responses import download_response


router = APIRouter(prefix="/pdf/jobs", tags=["PDF jobs"])


@router.post("", response_model=PdfJobOut, status_code=status.HTTP_201_CREATED)
async def create_pdf_job(
    request: Request,
    file: UploadFile = File(...),
    qr_id: str = Form(...),
    page: int = Form(1),
    position: str = Form("bottom-right"),
    size_mm: float | None = Form(None),
    margin_mm: float | None = Form(None),
    qr_mode: str = Form("dynamic"),
) -> dict:
    settings = request.app.state.settings
    return await request.app.state.pdf_service.create_job(
        file,
        qr_id,
        page,
        position,
        settings.default_qr_size_mm if size_mm is None else size_mm,
        settings.default_qr_margin_mm if margin_mm is None else margin_mm,
        qr_mode,
    )


@router.get("/{job_id}", response_model=PdfJobOut)
def get_pdf_job(request: Request, job_id: str) -> dict:
    return request.app.state.pdf_service.get_job(job_id)


@router.get("/{job_id}/download")
def download_pdf_job(request: Request, job_id: str) -> FileResponse:
    path, filename = request.app.state.pdf_service.download(job_id)
    return download_response(path, filename, "application/pdf")
