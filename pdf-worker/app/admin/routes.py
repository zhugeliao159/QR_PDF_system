from __future__ import annotations

import math
import io
import time
import zipfile
from collections import defaultdict
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, File, Form, Query, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response

from app.admin.messages import chinese_error
from app.auth.password import hash_password, verify_password
from app.errors import AppError
from app.models import utc_now_iso
from app.network import classify_public_url
from app.responses import download_response
from app.services.binding_service import GRADES, SUBJECTS
from app.services.credential_service import ADMIN_PASSWORD, DELETION_PASSWORD


router = APIRouter(prefix="/admin", tags=["管理员后台"])
LOGIN_ATTEMPTS: dict[str, list[float]] = defaultdict(list)
DELETION_ATTEMPTS: dict[str, list[float]] = defaultdict(list)
DELETION_LOCKED_UNTIL: dict[str, float] = {}
SECURITY_ATTEMPTS: dict[str, list[float]] = defaultdict(list)
SECURITY_LOCKED_UNTIL: dict[str, float] = {}
PREVIEW_STATUS_LABELS = {
    "not_generated": "尚未生成预览",
    "pending": "等待生成预览",
    "processing": "正在生成预览",
    "completed": "预览生成完成",
    "failed": "预览生成失败",
    "superseded": "预览已被新版本替代",
}


def _context(request: Request, **values: Any) -> dict[str, Any]:
    settings = request.app.state.settings
    context = {
        "request": request,
        "site_name": settings.site_name,
        "admin": getattr(request.state, "admin", None),
        "csrf_token": getattr(getattr(request.state, "admin", None), "csrf_token", ""),
        "network": classify_public_url(settings.public_base_url),
        "grades": sorted(GRADES, key=lambda item: (item != "未分类", item)),
        "subjects": sorted(SUBJECTS, key=lambda item: (item != "未分类", item)),
        "allow_external_urls": settings.allow_external_urls,
        "allow_private_http_external_urls": settings.allow_private_http_external_urls,
        "preview_status_labels": PREVIEW_STATUS_LABELS,
    }
    context.update(values)
    return context


def _render(request: Request, template: str, status_code: int = 200, **values: Any):
    return request.app.state.templates.TemplateResponse(
        request, template, _context(request, **values), status_code=status_code
    )


def _csrf(request: Request, token: str | None) -> None:
    session = getattr(request.state, "admin", None)
    if session is None or not request.app.state.session_manager.valid_csrf(session, token):
        raise AppError(403, "CSRF_FAILED", "页面已过期，请刷新后重新操作。")


def _actor(request: Request) -> str:
    session = getattr(request.state, "admin", None)
    return session.username if session is not None else "admin"


def _preview_revision(request: Request, qr_id: str, revision_key: str) -> tuple[dict, dict]:
    resolved = request.app.state.resolver_service.resolve_latest(
        qr_id, allow_inactive=True
    )
    revision = request.app.state.revision_service.get_by_key(
        resolved.resource["id"], revision_key
    )
    return request.app.state.binding_service.get_binding(qr_id, allow_inactive=True), revision


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request, password_changed: bool = False):
    if getattr(request.state, "admin", None):
        return RedirectResponse("/admin", status_code=303)
    return _render(
        request,
        "login.html",
        success=("管理员密码已修改，请使用新密码登录。" if password_changed else None),
    )


@router.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...)):
    host = request.client.host if request.client else "unknown"
    now = time.monotonic()
    LOGIN_ATTEMPTS[host] = [value for value in LOGIN_ATTEMPTS[host] if now - value < 300]
    settings = request.app.state.settings
    credentials = request.app.state.credential_service
    valid = (
        len(LOGIN_ATTEMPTS[host]) < 10
        and username == settings.admin_username
        and credentials.verify_admin(password)
    )
    if not valid:
        LOGIN_ATTEMPTS[host].append(now)
        return _render(
            request, "login.html", status_code=401, error="账号或密码不正确"
        )
    LOGIN_ATTEMPTS.pop(host, None)
    token, _ = request.app.state.session_manager.create(
        username, credentials.admin_revision()
    )
    response = RedirectResponse("/admin", status_code=303)
    request.app.state.session_manager.set_cookie(response, token)
    return response


@router.post("/logout")
def logout(request: Request, csrf_token: str = Form(...)):
    _csrf(request, csrf_token)
    response = RedirectResponse("/admin/login", status_code=303)
    request.app.state.session_manager.clear_cookie(response)
    return response


@router.get("", response_class=HTMLResponse)
def dashboard(request: Request):
    materials, total = request.app.state.binding_service.list_materials(page_size=6)
    jobs = request.app.state.pdf_service.list_recent(6)
    return _render(request, "dashboard.html", materials=materials, total=total, jobs=jobs)


def _security_attempt_key(request: Request) -> str:
    session = getattr(request.state, "admin", None)
    host = request.client.host if request.client else "unknown"
    session_id = session.session_id if session is not None else "unknown"
    return f"{session_id}@{host}"


def _security_locked(request: Request) -> bool:
    return SECURITY_LOCKED_UNTIL.get(_security_attempt_key(request), 0) > time.monotonic()


def _security_failure(request: Request) -> None:
    key = _security_attempt_key(request)
    now = time.monotonic()
    attempts = [value for value in SECURITY_ATTEMPTS[key] if now - value < 600]
    attempts.append(now)
    if len(attempts) >= 5:
        SECURITY_LOCKED_UNTIL[key] = now + 900
        SECURITY_ATTEMPTS.pop(key, None)
    else:
        SECURITY_ATTEMPTS[key] = attempts


def _security_clear_attempts(request: Request) -> None:
    key = _security_attempt_key(request)
    SECURITY_ATTEMPTS.pop(key, None)
    SECURITY_LOCKED_UNTIL.pop(key, None)


def _security_page(
    request: Request, *, status_code: int = 200, **values: Any
) -> HTMLResponse:
    return _render(
        request,
        "security.html",
        status_code=status_code,
        deletion_configured=(
            request.app.state.credential_service.deletion_password_configured()
        ),
        **values,
    )


@router.get("/security", response_class=HTMLResponse)
def security_page(request: Request):
    return _security_page(request)


@router.post("/security/admin-password", response_class=HTMLResponse)
def change_admin_password(
    request: Request,
    csrf_token: str = Form(...),
    current_admin_password: str = Form(...),
    new_admin_password: str = Form(...),
    confirm_admin_password: str = Form(...),
):
    _csrf(request, csrf_token)
    if _security_locked(request):
        return _security_page(
            request,
            status_code=429,
            error="验证失败次数过多，请 15 分钟后重试。",
        )
    credentials = request.app.state.credential_service
    if not credentials.verify_admin(current_admin_password):
        _security_failure(request)
        return _security_page(request, status_code=401, error="当前管理员密码不正确。")
    if new_admin_password != confirm_admin_password:
        return _security_page(request, status_code=422, error="两次输入的新管理员密码不一致。")
    if verify_password(new_admin_password, credentials.admin_password_hash()):
        return _security_page(request, status_code=422, error="新管理员密码不能与当前密码相同。")
    try:
        password_hash = hash_password(new_admin_password)
    except ValueError:
        return _security_page(request, status_code=422, error="新密码至少需要 16 个字符。")
    credentials.update(ADMIN_PASSWORD, password_hash, _actor(request))
    _security_clear_attempts(request)
    response = RedirectResponse("/admin/login?password_changed=1", status_code=303)
    request.app.state.session_manager.clear_cookie(response)
    return response


@router.post("/security/deletion-password", response_class=HTMLResponse)
def change_deletion_password(
    request: Request,
    csrf_token: str = Form(...),
    current_admin_password: str = Form(...),
    current_deletion_password: str = Form(""),
    new_deletion_password: str = Form(...),
    confirm_deletion_password: str = Form(...),
):
    _csrf(request, csrf_token)
    if _security_locked(request):
        return _security_page(
            request,
            status_code=429,
            error="验证失败次数过多，请 15 分钟后重试。",
        )
    credentials = request.app.state.credential_service
    if not credentials.verify_admin(current_admin_password):
        _security_failure(request)
        return _security_page(request, status_code=401, error="当前管理员密码不正确。")
    if (
        credentials.deletion_password_configured()
        and not credentials.verify_deletion(current_deletion_password)
    ):
        _security_failure(request)
        return _security_page(request, status_code=401, error="当前二级密码不正确。")
    if new_deletion_password != confirm_deletion_password:
        return _security_page(request, status_code=422, error="两次输入的新二级密码不一致。")
    if credentials.verify_admin(new_deletion_password):
        return _security_page(
            request, status_code=422, error="二级密码不能与管理员密码相同。"
        )
    current_deletion_hash = credentials.deletion_password_hash()
    if current_deletion_hash and verify_password(
        new_deletion_password, current_deletion_hash
    ):
        return _security_page(request, status_code=422, error="新二级密码不能与当前密码相同。")
    try:
        password_hash = hash_password(new_deletion_password)
    except ValueError:
        return _security_page(request, status_code=422, error="新密码至少需要 16 个字符。")
    credentials.update(DELETION_PASSWORD, password_hash, _actor(request))
    _security_clear_attempts(request)
    return _security_page(request, success="永久删除二级密码已修改。")


@router.get("/viewer-sessions", response_class=HTMLResponse)
def viewer_sessions(request: Request, q: str = ""):
    sessions = request.app.state.viewer_session_service.list_sessions(q)
    return _render(
        request,
        "viewer_sessions.html",
        sessions=sessions,
        q=q,
        watermark_chinese=request.app.state.watermark_service.chinese_watermark_available,
    )


@router.post("/viewer-sessions/{session_id}/revoke")
def revoke_viewer_session(
    request: Request, session_id: int, csrf_token: str = Form(...)
):
    _csrf(request, csrf_token)
    if not request.app.state.viewer_session_service.revoke(session_id):
        raise AppError(404, "VIEWER_SESSION_NOT_FOUND", "viewer session does not exist")
    return RedirectResponse("/admin/viewer-sessions?revoked=1", status_code=303)


@router.get("/materials", response_class=HTMLResponse)
def material_list(
    request: Request,
    q: str = "",
    grade: str = "",
    subject: str = "",
    status: str = "",
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    if page_size not in {20, 50, 100}:
        page_size = 20
    materials, total = request.app.state.binding_service.list_materials(
        q, grade, subject, status, page, page_size
    )
    return _render(
        request, "materials/list.html", materials=materials, total=total,
        pages=max(1, math.ceil(total / page_size)), page=page, page_size=page_size,
        q=q, grade=grade, subject=subject, status=status,
        deletion_enabled=(
            request.app.state.credential_service.deletion_password_configured()
        ),
    )


@router.get("/materials/new", response_class=HTMLResponse)
def material_create_page(request: Request):
    return RedirectResponse("/admin/materials/import", status_code=303)


@router.get("/materials/import", response_class=HTMLResponse)
def material_import_page(request: Request):
    settings = request.app.state.settings
    return _render(
        request,
        "materials/import.html",
        form={},
        max_files=settings.batch_upload_max_files,
        max_total_mb=settings.batch_upload_max_total_mb,
        max_file_mb=settings.max_upload_size_mb,
    )


@router.post("/materials/import")
async def material_import(
    request: Request,
    csrf_token: str = Form(...),
    grade: str = Form("未分类"),
    subject: str = Form("未分类"),
    files: list[UploadFile] = File(...),
):
    _csrf(request, csrf_token)
    settings = request.app.state.settings
    try:
        batch = await request.app.state.batch_import_service.create_batch(
            files, grade, subject, _actor(request)
        )
    except AppError as exc:
        return _render(
            request,
            "materials/import.html",
            status_code=exc.status_code,
            form={"grade": grade, "subject": subject},
            max_files=settings.batch_upload_max_files,
            max_total_mb=settings.batch_upload_max_total_mb,
            max_file_mb=settings.max_upload_size_mb,
            error=chinese_error(exc.code, exc.message),
        )
    return RedirectResponse(
        f"/admin/materials/imports/{batch['batch_key']}", status_code=303
    )


@router.post("/materials/import/reserve")
async def material_import_reserve(request: Request):
    payload = await request.json()
    _csrf(request, str(payload.get("csrf_token") or ""))
    raw_files = payload.get("files")
    if not isinstance(raw_files, list):
        raise AppError(422, "BATCH_FILES_REQUIRED", "请至少选择一份 PDF。")
    try:
        batch = request.app.state.batch_import_service.reserve_batch(
            raw_files, _actor(request)
        )
    except AppError as exc:
        return JSONResponse(
            {"error": {"code": exc.code, "message": chinese_error(exc.code, exc.message)}},
            status_code=exc.status_code,
        )
    return JSONResponse(
        {
            "batch_key": batch["batch_key"],
            "detail_url": f"/admin/materials/imports/{batch['batch_key']}",
            "qr_zip_url": f"/admin/materials/imports/{batch['batch_key']}/qrs.zip",
            "items": [
                {
                    "item_number": item["item_number"],
                    "filename": item["original_filename"],
                    "name": item["resolved_title"],
                    "qr_id": item["qr_id"],
                    "qr_download_url": f"/admin/materials/{item['qr_id']}/qr.png",
                    "upload_url": (
                        f"/admin/materials/imports/{batch['batch_key']}"
                        f"/items/{item['item_number']}/file"
                    ),
                }
                for item in batch["items"]
            ],
        },
        status_code=201,
    )


@router.post("/materials/imports/{batch_key}/items/{item_number}/file")
async def material_import_item_upload(
    request: Request,
    batch_key: str,
    item_number: int,
    csrf_token: str = Form(...),
    file: UploadFile = File(...),
):
    _csrf(request, csrf_token)
    try:
        batch = await request.app.state.batch_import_service.store_item_upload(
            batch_key, item_number, file
        )
    except AppError as exc:
        return JSONResponse(
            {"error": {"code": exc.code, "message": chinese_error(exc.code, exc.message)}},
            status_code=exc.status_code,
        )
    item = next(
        (entry for entry in batch["items"] if entry["item_number"] == item_number),
        None,
    )
    return JSONResponse({"ok": True, "item": item})


@router.get("/materials/imports/{batch_key}/qrs.zip")
def material_import_qr_zip(request: Request, batch_key: str):
    batch = request.app.state.batch_import_service.get_batch(batch_key)
    output = io.BytesIO()
    used: set[str] = set()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for item in batch["items"]:
            if not item["qr_id"]:
                continue
            base = str(item["resolved_title"] or item["requested_title"])
            filename = f"{base}.png"
            counter = 2
            while filename.casefold() in used:
                filename = f"{base}-{counter}.png"
                counter += 1
            used.add(filename.casefold())
            archive.writestr(
                filename, request.app.state.qr_service.png(item["qr_id"])
            )
    return Response(
        output.getvalue(),
        media_type="application/zip",
        headers={
            "Content-Disposition": (
                f'attachment; filename="qr-{batch_key[:8]}.zip"'
            ),
            "Cache-Control": "private, no-store",
        },
    )


@router.get("/materials/imports/{batch_key}", response_class=HTMLResponse)
def material_import_details(request: Request, batch_key: str):
    batch = request.app.state.batch_import_service.get_batch(batch_key)
    return _render(request, "materials/import_detail.html", batch=batch)


@router.get("/materials/imports/{batch_key}/status")
def material_import_status(request: Request, batch_key: str):
    batch = request.app.state.batch_import_service.get_batch(batch_key)
    return JSONResponse(
        {
            "batch_key": batch["batch_key"],
            "status": batch["status"],
            "total_items": batch["total_items"],
            "counts": batch["counts"],
            "items": [
                {
                    "item_number": item["item_number"],
                    "original_filename": item["original_filename"],
                    "resolved_title": item["resolved_title"],
                    "status": item["status"],
                    "error_message": item["error_message"],
                    "qr_id": item["qr_id"],
                    "qr_download_url": (
                        f"/admin/materials/{item['qr_id']}/qr.png"
                        if item["qr_id"] else None
                    ),
                }
                for item in batch["items"]
            ],
        },
        headers={"Cache-Control": "private, no-store"},
    )


@router.post("/materials/delete/confirm", response_class=HTMLResponse)
def material_delete_confirm(
    request: Request,
    csrf_token: str = Form(...),
    qr_ids: list[str] = Form(...),
):
    _csrf(request, csrf_token)
    if not request.app.state.credential_service.deletion_password_configured():
        raise AppError(503, "DELETION_PASSWORD_NOT_CONFIGURED", "永久删除二级密码尚未配置。")
    items = request.app.state.deletion_service.preflight(qr_ids)
    return _render(request, "materials/delete_confirm.html", items=items)


def _deletion_attempt_key(request: Request) -> str:
    host = request.client.host if request.client else "unknown"
    return f"{_actor(request)}@{host}"


@router.post("/materials/delete/apply", response_class=HTMLResponse)
def material_delete_apply(
    request: Request,
    csrf_token: str = Form(...),
    qr_ids: list[str] = Form(...),
    deletion_password: str = Form(...),
    confirmation: str = Form(...),
):
    _csrf(request, csrf_token)
    items = request.app.state.deletion_service.preflight(qr_ids)
    credentials = request.app.state.credential_service
    if not credentials.deletion_password_configured():
        return _render(
            request,
            "materials/delete_confirm.html",
            status_code=503,
            items=items,
            error="永久删除二级密码尚未配置。",
        )
    key = _deletion_attempt_key(request)
    now = time.monotonic()
    locked_until = DELETION_LOCKED_UNTIL.get(key, 0)
    if locked_until > now:
        return _render(
            request,
            "materials/delete_confirm.html",
            status_code=429,
            items=items,
            error="二级密码错误次数过多，请 15 分钟后重试。",
        )
    attempts = [value for value in DELETION_ATTEMPTS[key] if now - value < 600]
    DELETION_ATTEMPTS[key] = attempts
    if not credentials.verify_deletion(deletion_password):
        attempts.append(now)
        if len(attempts) >= 5:
            DELETION_LOCKED_UNTIL[key] = now + 900
            DELETION_ATTEMPTS.pop(key, None)
        with request.app.state.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO audit_events (event_type, actor, summary, created_at)
                VALUES ('permanent_delete_auth_failed', ?, ?, ?)
                """,
                (
                    _actor(request),
                    "永久删除二级密码验证失败",
                    utc_now_iso(),
                ),
            )
        return _render(
            request,
            "materials/delete_confirm.html",
            status_code=401,
            items=items,
            error="二级密码不正确，未删除任何资料。",
        )
    if confirmation.strip() != "永久删除":
        return _render(
            request,
            "materials/delete_confirm.html",
            status_code=422,
            items=items,
            error="请输入“永久删除”完成确认。",
        )
    DELETION_ATTEMPTS.pop(key, None)
    DELETION_LOCKED_UNTIL.pop(key, None)
    results = request.app.state.deletion_service.delete_many(qr_ids, _actor(request))
    return _render(request, "materials/delete_result.html", results=results)


@router.post("/materials/new")
async def material_create(
    request: Request,
    csrf_token: str = Form(...),
    title: str = Form(...),
    grade: str = Form("未分类"),
    subject: str = Form("未分类"),
    textbook_version: str = Form(""),
    chapter: str = Form(""),
    note: str = Form(""),
    file: UploadFile = File(...),
):
    _csrf(request, csrf_token)
    form = locals().copy()
    try:
        material = await request.app.state.binding_service.create_binding(
            file, note, title, grade, subject, textbook_version, chapter, _actor(request)
        )
    except AppError as exc:
        return _render(
            request, "materials/create.html", status_code=exc.status_code,
            form=form, error=chinese_error(exc.code, exc.message),
        )
    return RedirectResponse(
        f"/admin/materials/{material['qr_id']}?created=1", status_code=303
    )


@router.get("/materials/{qr_id}", response_class=HTMLResponse)
def material_detail(request: Request, qr_id: str, created: int = 0, updated: int = 0):
    material = request.app.state.binding_service.get_binding(qr_id, allow_inactive=True)
    versions = request.app.state.binding_service.list_versions(qr_id, allow_inactive=True)
    drafts = [item for item in versions if item["status"] == "draft"]
    history = [
        item for item in versions
        if item["status"] == "published" and not item["is_current"]
    ]
    events = request.app.state.binding_service.audit_events(qr_id)
    return _render(
        request, "materials/detail.html", material=material, drafts=drafts,
        history=history, events=events,
        success="创建成功" if created else ("资料已更新" if updated else ""),
    )


@router.get("/materials/{qr_id}/qr.png")
def admin_dynamic_qr(request: Request, qr_id: str):
    material = request.app.state.binding_service.get_identity(qr_id)
    encoded_name = quote(f"{material['name']}.png", safe="")
    return Response(
        request.app.state.qr_service.png(qr_id), media_type="image/png",
        headers={
            "Content-Disposition": (
                f"attachment; filename=qr.png; filename*=UTF-8''{encoded_name}"
            ),
            "Cache-Control": "private, no-store",
        },
    )


@router.get("/materials/{qr_id}/versions/{version_id}/qr.png")
def admin_fixed_qr(request: Request, qr_id: str, version_id: int):
    material = request.app.state.binding_service.get_binding(qr_id, allow_inactive=True)
    public_token = request.app.state.binding_service.existing_fixed_alias_token(
        qr_id, version_id
    )
    return Response(
        request.app.state.qr_service.fixed_png(public_token), media_type="image/png",
        headers={
            "Content-Disposition": f'attachment; filename="{material["display_code"]}-V{version_id}.png"',
            "Content-Location": request.app.state.qr_service.fixed_url(public_token),
        },
    )


@router.get("/materials/{qr_id}/replace", response_class=HTMLResponse)
def replace_page(request: Request, qr_id: str):
    return RedirectResponse("/admin/materials/import", status_code=303)


@router.post("/materials/{qr_id}/replace")
async def replace_file(
    request: Request, qr_id: str, csrf_token: str = Form(...),
    note: str = Form(""), content_type: str = Form("file"),
    external_url: str = Form(""), file: UploadFile | None = File(None),
):
    del qr_id, note, content_type, external_url, file
    _csrf(request, csrf_token)
    raise AppError(
        410,
        "LEGACY_REPLACE_DISABLED",
        "请在上传页面用同名 PDF 自动更新永久二维码。",
    )


@router.get("/materials/{qr_id}/drafts/{revision_key}", response_class=HTMLResponse)
def draft_preview(
    request: Request, qr_id: str, revision_key: str, created: int = 0
):
    material = request.app.state.binding_service.get_binding(qr_id, allow_inactive=True)
    draft = request.app.state.binding_service.draft_details(qr_id, revision_key)
    return _render(
        request,
        "materials/draft.html",
        material=material,
        draft=draft,
        success="草稿已保存，学生目前仍然看到原来的已发布版本。" if created else "",
    )


@router.get("/materials/{qr_id}/drafts/{revision_key}/file")
def draft_preview_file(
    request: Request,
    qr_id: str,
    revision_key: str,
    download: bool = Query(False),
):
    path, filename, mime_type = request.app.state.binding_service.draft_file(
        qr_id, revision_key
    )
    inline = not download and (
        mime_type == "application/pdf" or mime_type.startswith("image/")
    )
    return download_response(
        path,
        filename,
        mime_type,
        "inline" if inline else "attachment",
        "no-store, must-revalidate",
    )


@router.post("/materials/{qr_id}/drafts/{revision_key}/publish")
def publish_draft(
    request: Request,
    qr_id: str,
    revision_key: str,
    csrf_token: str = Form(...),
    page_state: int = Form(...),
    external_confirm: str = Form(""),
):
    _csrf(request, csrf_token)
    try:
        draft = request.app.state.binding_service.draft_details(qr_id, revision_key)
        if draft["target_type"] == "external_url" and external_confirm != "yes":
            raise AppError(
                422,
                "EXTERNAL_URL_CONFIRM_REQUIRED",
                "请确认该网址内容适合学生访问。",
            )
        request.app.state.binding_service.publish_draft(
            qr_id, revision_key, page_state, _actor(request)
        )
    except AppError as exc:
        material = request.app.state.binding_service.get_binding(
            qr_id, allow_inactive=True
        )
        draft = request.app.state.binding_service.draft_details(qr_id, revision_key)
        return _render(
            request,
            "materials/draft.html",
            status_code=exc.status_code,
            material=material,
            draft=draft,
            error=chinese_error(exc.code, exc.message),
        )
    return RedirectResponse(f"/admin/materials/{qr_id}?updated=1", status_code=303)


@router.post("/materials/{qr_id}/drafts/{revision_key}/discard")
def discard_draft(
    request: Request,
    qr_id: str,
    revision_key: str,
    csrf_token: str = Form(...),
):
    _csrf(request, csrf_token)
    request.app.state.binding_service.discard_draft(
        qr_id, revision_key, _actor(request)
    )
    return RedirectResponse(f"/admin/materials/{qr_id}?updated=1", status_code=303)


@router.get("/materials/{qr_id}/versions", response_class=HTMLResponse)
def versions_page(request: Request, qr_id: str):
    material = request.app.state.binding_service.get_binding(qr_id, allow_inactive=True)
    versions = request.app.state.binding_service.list_versions(qr_id, allow_inactive=True)
    return _render(request, "materials/versions.html", material=material, versions=versions)


@router.post("/materials/{qr_id}/versions/{revision_key}/republish")
def republish_version(
    request: Request,
    qr_id: str,
    revision_key: str,
    csrf_token: str = Form(...),
    page_state: int = Form(...),
    external_confirm: str = Form(""),
):
    _csrf(request, csrf_token)
    try:
        version = request.app.state.binding_service.published_revision(
            qr_id, revision_key
        )
        if version["target_type"] == "external_url" and external_confirm != "yes":
            raise AppError(
                422,
                "EXTERNAL_URL_CONFIRM_REQUIRED",
                "请确认该网址内容适合学生访问。",
            )
        request.app.state.binding_service.republish_revision(
            qr_id, revision_key, page_state, _actor(request)
        )
    except AppError as exc:
        material = request.app.state.binding_service.get_binding(
            qr_id, allow_inactive=True
        )
        versions = request.app.state.binding_service.list_versions(
            qr_id, allow_inactive=True
        )
        return _render(
            request,
            "materials/versions.html",
            status_code=exc.status_code,
            material=material,
            versions=versions,
            error=chinese_error(exc.code, exc.message),
        )
    return RedirectResponse(f"/admin/materials/{qr_id}?updated=1", status_code=303)


@router.get("/materials/{qr_id}/versions/{revision_key}/open")
def open_published_version(request: Request, qr_id: str, revision_key: str):
    version = request.app.state.binding_service.published_revision(
        qr_id, revision_key
    )
    if version["target_type"] == "external_url":
        validated = request.app.state.external_url_validator.validate(
            version["external_url"]
        )
        target = validated.url
    else:
        target = f"/admin/revisions/{revision_key}/original"
    return RedirectResponse(
        target,
        status_code=307,
        headers={"Cache-Control": "no-store, must-revalidate", "Referrer-Policy": "no-referrer"},
    )


@router.get("/revisions/{revision_key}/original")
def admin_revision_original(
    request: Request,
    revision_key: str,
    download: bool = Query(False),
):
    resolved = request.app.state.resolver_service.resolve_content(revision_key)
    path = request.app.state.asset_service.path(resolved.asset)
    with request.app.state.database.transaction() as connection:
        connection.execute(
            """
            INSERT INTO audit_events
                (event_type, resource_id, revision_id, actor, summary, created_at)
            VALUES ('view_original_asset', ?, ?, ?, ?, ?)
            """,
            (
                resolved.resource["id"],
                resolved.revision["id"],
                _actor(request),
                "管理员访问原始文件",
                utc_now_iso(),
            ),
        )
    response = download_response(
        path,
        resolved.asset["original_filename"],
        resolved.asset["mime_type"],
        "attachment" if download else "inline",
        "private, no-store, max-age=0",
    )
    response.headers["Pragma"] = "no-cache"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


@router.get(
    "/materials/{qr_id}/versions/{revision_key}/previews", response_class=HTMLResponse
)
def preview_pages(request: Request, qr_id: str, revision_key: str, queued: int = 0):
    material, revision = _preview_revision(request, qr_id, revision_key)
    status = request.app.state.preview_service.status_for_revision(revision["id"])
    pages = (
        request.app.state.preview_service.list_pages(revision["id"])
        if status and status["status"] == "completed"
        else []
    )
    return _render(
        request,
        "materials/preview.html",
        material=material,
        version=revision,
        preview=status or {"status": "not_generated"},
        pages=pages,
        success="已提交预览生成任务。" if queued else "",
    )


@router.post("/materials/{qr_id}/versions/{revision_key}/previews")
def generate_preview(
    request: Request,
    qr_id: str,
    revision_key: str,
    csrf_token: str = Form(...),
    force: str = Form(""),
):
    _csrf(request, csrf_token)
    material, revision = _preview_revision(request, qr_id, revision_key)
    try:
        request.app.state.preview_service.request_preview(
            revision["id"], force=force == "yes"
        )
    except AppError as exc:
        status = request.app.state.preview_service.status_for_revision(revision["id"])
        pages = (
            request.app.state.preview_service.list_pages(revision["id"])
            if status and status["status"] == "completed"
            else []
        )
        return _render(
            request,
            "materials/preview.html",
            status_code=exc.status_code,
            material=material,
            version=revision,
            preview=status or {"status": "not_generated"},
            pages=pages,
            error=chinese_error(exc.code, "预览生成任务未能创建。"),
        )
    return RedirectResponse(
        f"/admin/materials/{qr_id}/versions/{revision_key}/previews?queued=1",
        status_code=303,
    )


@router.get("/materials/{qr_id}/versions/{revision_key}/previews/pages/{page_number}")
def preview_page_file(
    request: Request, qr_id: str, revision_key: str, page_number: int
):
    _, revision = _preview_revision(request, qr_id, revision_key)
    path, _ = request.app.state.preview_service.page_path(revision["id"], page_number)
    return FileResponse(
        path,
        media_type="image/webp",
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )


@router.post("/materials/{qr_id}/restore/{version_id}")
def restore_version(
    request: Request, qr_id: str, version_id: int, csrf_token: str = Form(...)
):
    _csrf(request, csrf_token)
    request.app.state.binding_service.rollback(qr_id, version_id)
    return RedirectResponse(f"/admin/materials/{qr_id}?updated=1", status_code=303)


@router.get("/materials/{qr_id}/edit", response_class=HTMLResponse)
def edit_page(request: Request, qr_id: str):
    return RedirectResponse("/admin/materials", status_code=303)


@router.post("/materials/{qr_id}/edit")
def edit_material(
    request: Request, qr_id: str, csrf_token: str = Form(...), title: str = Form(...),
    grade: str = Form(...), subject: str = Form(...), textbook_version: str = Form(""),
    chapter: str = Form(""), note: str = Form(""),
):
    del qr_id, title, grade, subject, textbook_version, chapter, note
    _csrf(request, csrf_token)
    raise AppError(
        410,
        "METADATA_EDIT_DISABLED",
        "名称由 PDF 文件名绑定，不能手工修改。",
    )


@router.post("/materials/{qr_id}/status")
def change_status(
    request: Request, qr_id: str, csrf_token: str = Form(...), active: int = Form(...)
):
    _csrf(request, csrf_token)
    request.app.state.binding_service.set_active(qr_id, bool(active), _actor(request))
    return RedirectResponse(f"/admin/materials/{qr_id}", status_code=303)


@router.get("/pdf/new", response_class=HTMLResponse)
def pdf_create_page(request: Request, material: str = ""):
    materials, _ = request.app.state.binding_service.list_materials(status="active", page_size=100)
    materials = [item for item in materials if item.get("original_filename")]
    return _render(request, "pdf/create.html", materials=materials, selected=material)


@router.post("/pdf/new")
async def pdf_create(
    request: Request, csrf_token: str = Form(...), qr_id: str = Form(...),
    qr_mode: str = Form("dynamic"), page: int = Form(1),
    position: str = Form("bottom-right"), size_mm: float = Form(20),
    margin_mm: float = Form(10), test_confirmed: str = Form(""),
    file: UploadFile = File(...),
):
    _csrf(request, csrf_token)
    qr_mode = "dynamic"
    network = classify_public_url(request.app.state.settings.public_base_url)
    if network.requires_test_confirmation and test_confirmed != "yes":
        materials, _ = request.app.state.binding_service.list_materials(status="active", page_size=100)
        materials = [item for item in materials if item.get("original_filename")]
        return _render(
            request, "pdf/create.html", status_code=422, materials=materials,
            selected=qr_id, error="请确认当前二维码仅用于测试后再生成。",
        )
    try:
        job = await request.app.state.pdf_service.create_job(
            file, qr_id, page, position, size_mm, margin_mm, qr_mode
        )
    except AppError as exc:
        materials, _ = request.app.state.binding_service.list_materials(status="active", page_size=100)
        materials = [item for item in materials if item.get("original_filename")]
        return _render(
            request, "pdf/create.html", status_code=exc.status_code,
            materials=materials, selected=qr_id,
            error=chinese_error(exc.code, exc.message),
        )
    return RedirectResponse(f"/admin/pdf/jobs/{job['job_id']}", status_code=303)


@router.get("/pdf/jobs/{job_id}", response_class=HTMLResponse)
def pdf_result(request: Request, job_id: str):
    job = request.app.state.pdf_service.get_job(job_id)
    material = request.app.state.binding_service.get_binding(job["qr_id"], allow_inactive=True)
    return _render(request, "pdf/result.html", job=job, material=material)


@router.get("/pdf/jobs/{job_id}/preview")
def pdf_preview(request: Request, job_id: str):
    return Response(
        request.app.state.pdf_service.preview_png(job_id), media_type="image/png",
        headers={"Cache-Control": "private, no-store"},
    )


@router.get("/pdf/jobs/{job_id}/download")
def admin_pdf_download(request: Request, job_id: str):
    path, filename = request.app.state.pdf_service.download(job_id)
    return download_response(path, filename, "application/pdf")
