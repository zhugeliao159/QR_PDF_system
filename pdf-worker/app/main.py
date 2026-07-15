from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.config import Settings
from app.database import Database
from app.errors import AppError
from app.routers import bindings, health, pdf_jobs, redirects
from app.services.binding_service import BindingService
from app.services.pdf_service import PdfService
from app.services.qr_service import QrService
from app.storage.local import LocalStorageBackend


logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    configured_settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        configured_settings.ensure_directories()
        database = Database(configured_settings.database_path)
        database.initialize()
        storage = LocalStorageBackend(configured_settings)
        storage.ensure_directories()
        qr_service = QrService(configured_settings.public_base_url)
        binding_service = BindingService(
            configured_settings, database, storage, qr_service
        )
        pdf_service = PdfService(
            configured_settings,
            database,
            storage,
            binding_service,
            qr_service,
        )

        application.state.settings = configured_settings
        application.state.database = database
        application.state.storage = storage
        application.state.qr_service = qr_service
        application.state.binding_service = binding_service
        application.state.pdf_service = pdf_service
        yield

    application = FastAPI(
        title="QR Exercise PDF Worker",
        version="0.2.0",
        lifespan=lifespan,
    )

    @application.exception_handler(AppError)
    async def app_error_handler(_request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "details": exc.details,
                }
            },
        )

    @application.exception_handler(RequestValidationError)
    async def validation_error_handler(
        _request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        details = [
            {"location": list(item["loc"]), "message": item["msg"], "type": item["type"]}
            for item in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "request validation failed",
                    "details": {"errors": details},
                }
            },
        )

    @application.exception_handler(Exception)
    async def unhandled_error_handler(_request: Request, exc: Exception) -> JSONResponse:
        logger.error(
            "unhandled application error",
            exc_info=(type(exc), exc, exc.__traceback__),
        )
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": "internal service error",
                    "details": {},
                }
            },
        )

    application.include_router(health.router)
    application.include_router(bindings.router)
    application.include_router(redirects.router)
    application.include_router(pdf_jobs.router)
    return application


app = create_app()
