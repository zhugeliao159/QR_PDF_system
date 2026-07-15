from conftest import csrf_from, pdf_bytes


def test_dashboard_has_three_primary_actions(admin_client):
    page = admin_client.get("/admin")
    assert page.status_code == 200
    assert "新建解析二维码" in page.text
    assert "给练习册添加二维码" in page.text
    assert "管理已有解析资料" in page.text
    assert "cdn" not in page.text.lower()
    assert admin_client.get("/static/css/admin.css").status_code == 200
    assert admin_client.get("/static/js/admin.js").status_code == 200


def test_create_search_edit_and_status_material(admin_client):
    csrf = csrf_from(admin_client.get("/admin/materials/new"))
    created = admin_client.post(
        "/admin/materials/new",
        data={
            "csrf_token": csrf,
            "title": "高一数学第一章解析",
            "grade": "高一",
            "subject": "数学",
            "textbook_version": "人教A版必修一",
            "chapter": "第一章 集合与常用逻辑用语",
            "note": "首版",
        },
        files={"file": ("高一数学第一章解析.pdf", pdf_bytes(), "application/pdf")},
        follow_redirects=False,
    )
    assert created.status_code == 303, created.text
    detail_url = created.headers["location"].split("?")[0]
    detail = admin_client.get(created.headers["location"])
    assert "创建成功" in detail.text
    assert "高一数学第一章解析.pdf" in detail.text
    assert "QR-" in detail.text
    assert "技术信息" in detail.text

    listing = admin_client.get("/admin/materials", params={"q": "第一章", "grade": "高一", "subject": "数学"})
    assert "高一数学第一章解析" in listing.text
    qr_id = detail_url.rsplit("/", 1)[-1]
    csrf = csrf_from(detail)
    edit = admin_client.post(
        f"/admin/materials/{qr_id}/edit",
        data={
            "csrf_token": csrf, "title": "高一数学集合解析", "grade": "高一",
            "subject": "数学", "textbook_version": "人教A版必修一",
            "chapter": "集合", "note": "已编辑",
        },
        follow_redirects=False,
    )
    assert edit.status_code == 303
    assert "高一数学集合解析" in admin_client.get(detail_url).text
    stopped = admin_client.post(
        f"/admin/materials/{qr_id}/status",
        data={"csrf_token": csrf, "active": "0"},
        follow_redirects=False,
    )
    assert stopped.status_code == 303
    assert "已停用" in admin_client.get(detail_url).text
    public = admin_client.get(f"/r/{qr_id}")
    assert public.status_code == 410
    assert "暂时不可用" in public.text


def test_create_requires_csrf(admin_client):
    response = admin_client.post(
        "/admin/materials/new",
        data={"title": "缺少令牌", "grade": "高一", "subject": "数学"},
        files={"file": ("answer.pdf", pdf_bytes(), "application/pdf")},
    )
    assert response.status_code == 422 or response.status_code == 403
    assert "Traceback" not in response.text
