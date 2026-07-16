from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.admin import routes as admin_routes
from app.admin.messages import chinese_error
from app.auth.password import verify_password
from app.auth.session import SessionManager
from app.config import Settings
from app.database import Database
from app.errors import AppError
from app.routers import bindings, health, pdf_jobs, redirects, student
from app.services.binding_service import BindingService
from app.services.decoupled import (
    AnswerResourceService,
    AnswerRevisionService,
    AssetService,
    QrResolverService,
)
from app.services.pdf_service import PdfService
from app.services.preview_service import PreviewService
from app.services.qr_service import QrService
from app.services.external_url import ExternalUrlValidator
from app.services.viewer_session import ViewerSessionService
from app.services.watermark import WatermarkService
from app.storage.local import LocalStorageBackend


logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    configured_settings = settings or Settings.from_env()
    docs_url = "/admin/api-docs" if configured_settings.enable_admin_api_docs else None
    openapi_url = (
        "/admin/openapi.json" if configured_settings.enable_admin_api_docs else None
    )

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        configured_settings.ensure_directories()
        database = Database(configured_settings.database_path)
        database.initialize()
        storage = LocalStorageBackend(configured_settings)
        storage.ensure_directories()
        qr_service = QrService(configured_settings.public_base_url)
        asset_service = AssetService(database, storage)
        resource_service = AnswerResourceService(database)
        external_url_validator = ExternalUrlValidator(configured_settings)
        preview_service = PreviewService(
            configured_settings, database, storage, asset_service
        )
        revision_service = AnswerRevisionService(
            database,
            asset_service,
            external_url_validator,
            configured_settings.require_preview_before_publish,
            preview_service,
        )
        resolver_service = QrResolverService(database)
        viewer_session_service = ViewerSessionService(configured_settings, database)
        watermark_service = WatermarkService(configured_settings)
        binding_service = BindingService(
            configured_settings,
            database,
            storage,
            qr_service,
            resource_service,
            revision_service,
            asset_service,
            resolver_service,
            external_url_validator,
            preview_service,
        )
        pdf_service = PdfService(
            configured_settings, database, storage, binding_service, qr_service
        )
        application.state.database = database
        application.state.storage = storage
        application.state.qr_service = qr_service
        application.state.asset_service = asset_service
        application.state.resource_service = resource_service
        application.state.revision_service = revision_service
        application.state.preview_service = preview_service
        application.state.external_url_validator = external_url_validator
        application.state.resolver_service = resolver_service
        application.state.viewer_session_service = viewer_session_service
        application.state.watermark_service = watermark_service
        application.state.binding_service = binding_service
        application.state.pdf_service = pdf_service
        yield

    application = FastAPI(
        title="QR Exercise PDF Worker",
        version="0.3.0",
        lifespan=lifespan,
        docs_url=docs_url,
        redoc_url=None,
        openapi_url=openapi_url,
    )
    application.state.settings = configured_settings
    application.state.session_manager = SessionManager(configured_settings)
    application.state.templates = Jinja2Templates(directory="app/templates")
    application.mount("/static", StaticFiles(directory="app/static"), name="static")

    @application.middleware("http")
    async def authentication_middleware(request: Request, call_next):
        path = request.url.path
        session = application.state.session_manager.load(request)
        request.state.admin = session
        if path.startswith("/admin"):
            public_admin = path == "/admin/login"
            if not public_admin and session is None:
                if path.startswith("/admin/api-docs") or path.startswith("/admin/openapi"):
                    return JSONResponse(
                        status_code=401,
                        content={"error": {"code": "ADMIN_AUTH_REQUIRED", "message": "authentication required", "details": {}}},
                    )
                return RedirectResponse("/admin/login", status_code=303)
        management_api = path.startswith("/bindings") or path.startswith("/pdf/jobs") or path == "/capabilities"
        if management_api and configured_settings.admin_password_hash:
            authorized = session is not None
            header = request.headers.get("authorization", "")
            if not authorized and header.startswith("Bearer ") and configured_settings.admin_api_token_hash:
                authorized = verify_password(
                    header.removeprefix("Bearer ").strip(),
                    configured_settings.admin_api_token_hash,
                )
            if not authorized:
                return JSONResponse(
                    status_code=401,
                    content={"error": {"code": "ADMIN_AUTH_REQUIRED", "message": "administrator authentication required", "details": {}}},
                )
        response = await call_next(request)
        if path.startswith(("/q/", "/r/", "/content/")):
            is_html = response.headers.get("content-type", "").startswith("text/html")
            response.headers.update(student.student_headers(csp=is_html))
        if path.startswith("/admin") and response.status_code == 404:
            return html_error(request, 404, "没有找到这个页面。")
        return response

    def html_error(request: Request, status: int, message: str) -> HTMLResponse:
        if request.url.path.startswith(("/q/", "/r/", "/content/")):
            headers = student.student_headers(csp=True)
            if status == 503:
                headers["Retry-After"] = "30"
            if status == 429:
                headers["Retry-After"] = "60"
            return application.state.templates.TemplateResponse(
                request,
                "student/error.html",
                {
                    "request": request,
                    "site_name": configured_settings.site_name,
                    "title": "解析暂时无法打开",
                    "message": message,
                },
                status_code=status,
                headers=headers,
            )
        title = "页面已过期" if status == 403 else "操作未完成"
        if request.url.path.startswith("/r/") and status == 410:
            title, message = "资料暂时不可用", "该解析资料暂时不可用。"
        return application.state.templates.TemplateResponse(
            request,
            "error.html",
            {
                "request": request,
                "site_name": configured_settings.site_name,
                "admin": getattr(request.state, "admin", None),
                "csrf_token": getattr(getattr(request.state, "admin", None), "csrf_token", ""),
                "title": title,
                "message": message,
            },
            status_code=status,
        )

    @application.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError):
        if request.url.path.startswith(("/admin", "/r/", "/q/", "/content/")):
            student_messages = {
                "BINDING_NOT_FOUND": "没有找到对应的解析资料，请确认二维码是否完整。",
                "BINDING_INACTIVE": "该解析资料暂时不可用。",
                "CURRENT_VERSION_MISSING": "这份解析暂未发布，请稍后再试。",
                "PUBLISHED_VERSION_MISSING": "这份解析暂未发布，请稍后再试。",
                "ASSET_MISSING": "解析文件暂时无法打开，请稍后重试。",
                "STORED_FILE_MISSING": "解析文件暂时无法打开，请稍后重试。",
                "PREVIEW_NOT_READY": "解析内容正在准备中，请稍后再试。",
                "PREVIEW_FAILED": "解析内容暂时无法显示，请联系资料提供方。",
                "PREVIEW_INCOMPLETE": "解析内容暂时不完整，请稍后再试。",
                "PREVIEW_PAGE_MISSING": "解析页面暂时缺失，请稍后再试。",
                "PREVIEW_PAGE_INVALID": "解析页面暂时无法显示，请稍后再试。",
                "PREVIEW_PAGE_HASH_MISMATCH": "解析页面完整性检查失败，请稍后再试。",
                "PREVIEW_PAGE_NOT_FOUND": "没有找到这一页解析内容。",
                "PREVIEW_EXTERNAL_DISABLED": "该内容暂不支持受控在线预览。",
                "PREVIEW_EXTERNAL_UNAVAILABLE": "该内容不属于受控在线预览。",
                "ORIGINAL_ADMIN_ONLY": "原始文件仅允许管理员登录后访问。",
                "VIEWER_SESSION_REQUIRED": "预览会话尚未建立，请刷新页面或重新扫码。",
                "VIEWER_SESSION_INVALID": "预览会话无效，请刷新页面或重新扫码。",
                "VIEWER_SESSION_ALIAS_MISMATCH": "该预览会话不属于这份资料，请重新扫码。",
                "VIEWER_SESSION_INACTIVE": "本次预览已失效，请刷新页面或重新扫码。",
                "VIEWER_SESSION_EXPIRED": "本次预览已过期，请刷新页面或重新扫码。",
                "VIEWER_RATE_LIMITED": "请求过于频繁，请稍候再试。",
            }
            message = student_messages.get(exc.code, chinese_error(exc.code, exc.message))
            status_code = 503 if exc.code in {"ASSET_MISSING", "STORED_FILE_MISSING"} else exc.status_code
            return html_error(request, status_code, message)
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": exc.code, "message": exc.message, "details": exc.details}},
        )

    @application.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError):
        if request.url.path.startswith("/admin"):
            return html_error(request, 422, "填写内容不完整或格式不正确，请检查后重试。")
        if request.url.path.startswith(("/q/", "/r/", "/content/")):
            return html_error(request, 422, "请求内容格式不正确，请检查后重试。")
        details = [
            {"location": list(item["loc"]), "message": item["msg"], "type": item["type"]}
            for item in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content={"error": {"code": "VALIDATION_ERROR", "message": "request validation failed", "details": {"errors": details}}},
        )

    @application.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, exc: Exception):
        logger.error("unhandled application error", exc_info=(type(exc), exc, exc.__traceback__))
        if request.url.path.startswith(("/admin", "/r/", "/q/", "/content/")):
            return html_error(
                request, 500,
                "系统处理失败，请稍后重试。如问题持续存在，请联系技术人员。",
            )
        return JSONResponse(
            status_code=500,
            content={"error": {"code": "INTERNAL_ERROR", "message": "internal service error", "details": {}}},
        )

    @application.exception_handler(StarletteHTTPException)
    async def http_error_handler(request: Request, exc: StarletteHTTPException):
        if request.url.path.startswith(("/admin", "/r/", "/q/", "/content/")):
            message = "没有找到这个页面。" if exc.status_code == 404 else "当前请求无法完成。"
            return html_error(request, exc.status_code, message)
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    @application.get("/", include_in_schema=False)
    def root():
        return RedirectResponse("/admin", status_code=303)

    application.include_router(health.router)
    application.include_router(bindings.router)
    application.include_router(redirects.router)
    application.include_router(student.router)
    application.include_router(pdf_jobs.router)
    application.include_router(admin_routes.router)
    return application


app = create_app()
