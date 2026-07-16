# Stage 05D 路由安全审计

审计日期：2026-07-16。结论：PASS。匿名学生只能进入受控预览、兼容跳转、静态资源和最小健康检查；没有匿名原件下载接口。生产配置中的管理 API 需要管理员 Session 或 Bearer，后台页面需要管理员 Session，写操作另有 CSRF。

| 路径 | 方法 | 匿名公开 | 管理员 Session | Viewer Session | 可返回原件/内部路径 | 限速与安全头 |
| --- | --- | --- | --- | --- | --- | --- |
| `/health` | GET | 是，最小状态 | 否 | 否 | 否 | 不返回环境、路径或数据库信息 |
| `/q/{public_token}` | GET | 是，用于创建会话 | 否 | 创建后写 HttpOnly Cookie | 否 | 登录式入口限速；完整 CSP、no-store 等学生头 |
| `/q/{public_token}/manifest` | GET | 否 | 否 | 是 | 仅页数和受控页地址 | 每会话限速；完整学生头 |
| `/q/{public_token}/pages/{page_number}` | GET | 否 | 否 | 是 | 仅服务端加水印的 WebP | 每会话、总请求和全局并发限制；完整学生头 |
| `/q/{public_token}/content` | GET | 兼容入口 | 否 | 是 | 否，307 到受控入口 | 完整学生头 |
| `/content/{revision_key}` | GET | 否 | 否 | 是 | 否，固定 revision 受控预览 | 完整学生头 |
| `/r/{qr_id}` | GET | 兼容入口 | 否 | 后续需要 | 否，307 到 `/q` | 完整学生头 |
| `/r/{qr_id}/versions/{version_id}` | GET | 兼容入口 | 否 | 后续需要 | 否，307 到固定 `/q` | 完整学生头 |
| `/static/css/student.css`、`/static/js/student.js` | GET | 是 | 否 | 否 | 否 | nosniff、no-referrer、same-origin CORP、Permissions-Policy |
| `/admin/login` | GET、POST | 仅登录页公开 | 登录后建立管理员会话 | 否 | 否 | POST 登录限速；不显示密钥 |
| `/admin/logout`、`/admin`、`/admin/viewer-sessions`、`/admin/viewer-sessions/{session_id}/revoke` | GET/POST | 否 | 是 | 否 | 否 | 写操作 CSRF；撤销写审计 |
| `/admin/materials`、`/admin/materials/new`、`/admin/materials/{qr_id}`、`/admin/materials/{qr_id}/edit`、`/admin/materials/{qr_id}/status` | GET/POST | 否 | 是 | 否 | 资料页不返回 storage_key；管理员操作可管理 Asset | 写操作 CSRF |
| `/admin/materials/{qr_id}/qr.png`、`/admin/materials/{qr_id}/versions/{version_id}/qr.png` | GET | 否 | 是 | 否 | 仅二维码 PNG | 管理员权限 |
| `/admin/materials/{qr_id}/replace`、`/admin/materials/{qr_id}/drafts/{revision_key}`、`.../drafts/{revision_key}/file`、`.../publish`、`.../discard` | GET/POST | 否 | 是 | 否 | draft file 可能返回管理员草稿原件 | 登录、CSRF、审计 |
| `/admin/materials/{qr_id}/versions`、`.../republish`、`.../open`、`/admin/revisions/{revision_key}/original`、`.../restore/{version_id}` | GET/POST | 否 | 是 | 否 | `original`/`open` 可向管理员返回原件 | 登录、CSRF、原件访问审计、private no-store |
| `/admin/materials/{qr_id}/versions/{revision_key}/previews`、`.../previews/pages/{page_number}` | GET/POST | 否 | 是 | 否 | 仅管理预览派生页 | 登录、CSRF |
| `/admin/pdf/new`、`/admin/pdf/jobs/{job_id}`、`.../preview`、`.../download` | GET/POST | 否 | 是 | 否 | download 可返回管理员生成的练习册 | 登录、CSRF |
| `/bindings`、`/bindings/{qr_id}`、`.../qr.png`、`.../file`、`.../versions`、`.../rollback/{version_id}`、`.../versions/{version_id}/qr.png` | GET/POST/PUT | 生产配置否 | Session 或 Bearer | 否 | 管理 API 可创建/更新资料；没有匿名原件出口 | 管理认证；写调用不属于学生接口 |
| `/pdf/jobs`、`/pdf/jobs/{job_id}`、`/pdf/jobs/{job_id}/download` | GET/POST | 生产配置否 | Session 或 Bearer | 否 | download 可返回生成 PDF | 管理认证 |
| `/capabilities` | GET | 生产配置否 | Session 或 Bearer | 否 | 否 | 管理认证 |
| `/admin/api-docs`、`/admin/openapi.json` | GET | 默认不存在 | 启用后仍需 Session | 否 | 可能描述内部 API | `ENABLE_ADMIN_API_DOCS=false` |

所有学生错误分支（不存在、停用、未发布、预览未完成/失败/缺页、Session 过期/撤销、429 和 500）都走中文脱敏页面并附相同学生安全头。自动扫描检查 HTML、JSON、响应头和响应体中的 PDF 类型、原图 SHA-256、`storage_key`、`asset_key`、revision 原件地址及宿主机绝对路径；实际远程扫描 11 个公开或越权请求，结果 PASS。
