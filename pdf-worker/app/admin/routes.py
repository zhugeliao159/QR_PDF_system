from __future__ import annotations

import math
import time
from collections import defaultdict
from typing import Any

from fastapi import APIRouter, File, Form, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from app.admin.messages import chinese_error
from app.auth.password import verify_password
from app.errors import AppError
from app.network import classify_public_url
from app.responses import download_response
from app.services.binding_service import GRADES, SUBJECTS


router = APIRouter(prefix="/admin", tags=["管理员后台"])
LOGIN_ATTEMPTS: dict[str, list[float]] = defaultdict(list)


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


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    if getattr(request.state, "admin", None):
        return RedirectResponse("/admin", status_code=303)
    return _render(request, "login.html")


@router.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...)):
    host = request.client.host if request.client else "unknown"
    now = time.monotonic()
    LOGIN_ATTEMPTS[host] = [value for value in LOGIN_ATTEMPTS[host] if now - value < 300]
    settings = request.app.state.settings
    valid = (
        len(LOGIN_ATTEMPTS[host]) < 10
        and username == settings.admin_username
        and verify_password(password, settings.admin_password_hash)
    )
    if not valid:
        LOGIN_ATTEMPTS[host].append(now)
        return _render(
            request, "login.html", status_code=401, error="账号或密码不正确"
        )
    LOGIN_ATTEMPTS.pop(host, None)
    token, _ = request.app.state.session_manager.create(username)
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


@router.get("/materials", response_class=HTMLResponse)
def material_list(
    request: Request,
    q: str = "",
    grade: str = "",
    subject: str = "",
    status: str = "",
    page: int = Query(1, ge=1),
):
    materials, total = request.app.state.binding_service.list_materials(
        q, grade, subject, status, page, 20
    )
    return _render(
        request, "materials/list.html", materials=materials, total=total,
        pages=max(1, math.ceil(total / 20)), page=page, q=q, grade=grade,
        subject=subject, status=status,
    )


@router.get("/materials/new", response_class=HTMLResponse)
def material_create_page(request: Request):
    return _render(request, "materials/create.html", form={})


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
            file, note, title, grade, subject, textbook_version, chapter
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
    return _render(
        request, "materials/detail.html", material=material, versions=versions,
        success="创建成功" if created else ("资料已更新" if updated else ""),
    )


@router.get("/materials/{qr_id}/qr.png")
def admin_dynamic_qr(request: Request, qr_id: str):
    material = request.app.state.binding_service.get_binding(qr_id, allow_inactive=True)
    return Response(
        request.app.state.qr_service.png(qr_id), media_type="image/png",
        headers={"Content-Disposition": f'attachment; filename="{material["display_code"]}.png"'},
    )


@router.get("/materials/{qr_id}/versions/{version_id}/qr.png")
def admin_fixed_qr(request: Request, qr_id: str, version_id: int):
    material = request.app.state.binding_service.get_binding(qr_id, allow_inactive=True)
    request.app.state.binding_service.pin_version(qr_id, version_id, "qr_download")
    return Response(
        request.app.state.qr_service.fixed_png(qr_id, version_id), media_type="image/png",
        headers={"Content-Disposition": f'attachment; filename="{material["display_code"]}-V{version_id}.png"'},
    )


@router.get("/materials/{qr_id}/replace", response_class=HTMLResponse)
def replace_page(request: Request, qr_id: str):
    material = request.app.state.binding_service.get_binding(qr_id, allow_inactive=True)
    return _render(request, "materials/replace.html", material=material)


@router.post("/materials/{qr_id}/replace")
async def replace_file(
    request: Request, qr_id: str, csrf_token: str = Form(...),
    note: str = Form(""), file: UploadFile = File(...),
):
    _csrf(request, csrf_token)
    try:
        await request.app.state.binding_service.replace_file(qr_id, file, note)
    except AppError as exc:
        material = request.app.state.binding_service.get_binding(qr_id, allow_inactive=True)
        return _render(
            request, "materials/replace.html", status_code=exc.status_code,
            material=material, error=chinese_error(exc.code, exc.message),
        )
    return RedirectResponse(f"/admin/materials/{qr_id}?updated=1", status_code=303)


@router.get("/materials/{qr_id}/versions", response_class=HTMLResponse)
def versions_page(request: Request, qr_id: str):
    material = request.app.state.binding_service.get_binding(qr_id, allow_inactive=True)
    versions = request.app.state.binding_service.list_versions(qr_id, allow_inactive=True)
    return _render(request, "materials/versions.html", material=material, versions=versions)


@router.post("/materials/{qr_id}/restore/{version_id}")
def restore_version(
    request: Request, qr_id: str, version_id: int, csrf_token: str = Form(...)
):
    _csrf(request, csrf_token)
    request.app.state.binding_service.rollback(qr_id, version_id)
    return RedirectResponse(f"/admin/materials/{qr_id}?updated=1", status_code=303)


@router.get("/materials/{qr_id}/edit", response_class=HTMLResponse)
def edit_page(request: Request, qr_id: str):
    material = request.app.state.binding_service.get_binding(qr_id, allow_inactive=True)
    return _render(request, "materials/edit.html", material=material)


@router.post("/materials/{qr_id}/edit")
def edit_material(
    request: Request, qr_id: str, csrf_token: str = Form(...), title: str = Form(...),
    grade: str = Form(...), subject: str = Form(...), textbook_version: str = Form(""),
    chapter: str = Form(""), note: str = Form(""),
):
    _csrf(request, csrf_token)
    request.app.state.binding_service.update_metadata(
        qr_id, title, grade, subject, textbook_version, chapter, note
    )
    return RedirectResponse(f"/admin/materials/{qr_id}?updated=1", status_code=303)


@router.post("/materials/{qr_id}/status")
def change_status(
    request: Request, qr_id: str, csrf_token: str = Form(...), active: int = Form(...)
):
    _csrf(request, csrf_token)
    request.app.state.binding_service.set_active(qr_id, bool(active))
    return RedirectResponse(f"/admin/materials/{qr_id}", status_code=303)


@router.get("/pdf/new", response_class=HTMLResponse)
def pdf_create_page(request: Request, material: str = ""):
    materials, _ = request.app.state.binding_service.list_materials(status="active", page_size=100)
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
    network = classify_public_url(request.app.state.settings.public_base_url)
    if network.requires_test_confirmation and test_confirmed != "yes":
        materials, _ = request.app.state.binding_service.list_materials(status="active", page_size=100)
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
