# Stage 5B 学生分页预览规范

动态与固定二维码都进入 `GET /q/{public_token}`。服务端每次按 alias 的 latest/pinned 语义重新解析 revision，只使用源 SHA-256 匹配且状态为 completed 的 PreviewSet；缺失、失败或损坏时返回中文错误，不回退原件。

学生页面立即请求第一页 WebP，使用 `loading="eager"` 与 `fetchpriority="high"`。后续页只有 `data-src`，由本地 JavaScript 的 IntersectionObserver 在接近视口时加载；无外部 CDN、PDF.js 或前端框架。页面显示资料名称、分类、版本、更新时间、总页数、页码、加载状态与返回顶部，不显示下载按钮、原文件名、内部 ID、storage key 或哈希。

接口：

- `GET /q/{token}/manifest`：仅返回 page_count、revision_display、content_kind、generated_at。
- `GET /q/{token}/pages/{n}`：返回 `image/webp`，每次重新解析 token。
- `GET /q/{token}/content`：文件版本只临时跳回分页预览；绝不返回原件。
- `GET /r/{token}`：307 到对应 `/q` 页面。
- 旧固定版本 `/r/{token}/versions/{id}`：307 到对应 pinned `/q` 页面。

学生 HTML 与 WebP 均使用 `private, no-store, max-age=0`、`Pragma: no-cache`、`nosniff` 与 `no-referrer`。HTML 还使用 DENY frame 与只允许本地资源的 CSP。

禁用图片拖拽、普通右键和页面中的下载操作只是交互阻碍。核心隔离是匿名接口不返回原始 Asset，只返回预览衍生图片。系统不能绝对阻止截图、录屏或保存浏览器已经接收的 WebP。
