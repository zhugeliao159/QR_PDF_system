from __future__ import annotations

import os
import platform
import tempfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse


router = APIRouter(tags=["health"])


def _directory_check(path: Path, mode: str) -> tuple[dict[str, bool], str | None]:
    exists = path.is_dir()
    access_mode = os.R_OK if mode == "read" else os.W_OK
    accessible = exists and os.access(path, access_mode)
    details = {"exists": exists, f"{mode}able": accessible}
    if not accessible:
        return details, f"{mode} access unavailable"
    if mode == "write":
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", prefix=".capability-", dir=path, delete=True
            ) as probe:
                probe.write("ok")
                probe.flush()
        except OSError:
            details["writeable"] = False
            return details, "write access unavailable"
    return details, None


def capability_payload(request: Request) -> tuple[dict[str, Any], list[str]]:
    settings = request.app.state.settings
    database = request.app.state.database
    storage = request.app.state.storage
    errors: list[str] = []
    dependencies: dict[str, dict[str, Any]] = {}

    try:
        import fitz

        dependencies["pymupdf"] = {
            "available": True,
            "version": getattr(fitz, "VersionBind", "unknown"),
        }
    except Exception as exc:
        dependencies["pymupdf"] = {"available": False, "error": str(exc)}
        errors.append("PyMuPDF import failed")
    try:
        import qrcode

        dependencies["qrcode"] = {
            "available": True,
            "version": getattr(qrcode, "__version__", "unknown"),
        }
    except Exception as exc:
        dependencies["qrcode"] = {"available": False, "error": str(exc)}
        errors.append("qrcode import failed")
    try:
        from PIL import Image

        dependencies["pillow"] = {
            "available": True,
            "version": getattr(Image, "__version__", "unknown"),
        }
    except Exception as exc:
        dependencies["pillow"] = {"available": False, "error": str(exc)}
        errors.append("Pillow import failed")

    input_dir, input_error = _directory_check(settings.input_dir, "read")
    output_dir, output_error = _directory_check(settings.output_dir, "write")
    if input_error:
        errors.append(f"input directory: {input_error}")
    if output_error:
        errors.append(f"output directory: {output_error}")

    database_status = {
        "exists": settings.database_path.is_file(),
        "readable": os.access(settings.database_path, os.R_OK),
        "writeable": os.access(settings.database_path, os.W_OK),
        "schema_version": 1,
    }
    try:
        database.check_read_write()
    except Exception:
        database_status["writeable"] = False
        errors.append("database is not readable and writeable")

    storage_status = storage.check_directories()
    if not all(storage_status.values()):
        errors.append("one or more storage directories are unavailable")

    payload = {
        "service": "pdf-worker",
        "python_version": platform.python_version(),
        "dependencies": dependencies,
        "input_directory": input_dir,
        "output_directory": output_dir,
        "database": database_status,
        "storage": storage_status,
        "configuration": {
            "public_base_url": settings.public_base_url,
            "max_upload_size_mb": settings.max_upload_size_mb,
            "max_pdf_pages": settings.max_pdf_pages,
            "max_binding_versions": settings.max_binding_versions,
            "default_qr_size_mm": settings.default_qr_size_mm,
            "default_qr_margin_mm": settings.default_qr_margin_mm,
        },
    }
    return payload, errors


@router.get("/health")
def health(request: Request) -> JSONResponse:
    _, errors = capability_payload(request)
    if errors:
        return JSONResponse(
            status_code=503,
            content={"status": "error", "service": "pdf-worker", "errors": errors},
        )
    return JSONResponse(content={"status": "ok", "service": "pdf-worker"})


@router.get("/capabilities")
def capabilities(request: Request) -> JSONResponse:
    payload, errors = capability_payload(request)
    if errors:
        payload["status"] = "error"
        payload["errors"] = errors
        return JSONResponse(status_code=503, content=payload)
    payload["status"] = "ok"
    return JSONResponse(content=payload)
