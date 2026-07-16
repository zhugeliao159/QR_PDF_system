# Stage 4B 学生答案页规范

## 入口

- 新二维码入口：`GET /q/{public_token}`。
- 动态解析：`GET /q/{public_token}/content`。
- 不可变文件：`GET /content/{revision_key}`。
- 旧 `/r/{qr_id}` 与 `/r/{qr_id}/versions/{version_id}` 保持兼容。

二维码只包含不可猜的 public token，不包含文件名、存储路径或数据库自增 ID。页面正文不展示 token、revision key、SHA-256、API JSON 或管理员入口。外部网页正文只展示域名，不展示完整 URL 或敏感 query。

## 页面内容

学生页面为简体中文，面向手机竖屏，显示资料名称、可选年级/学科/章节、当前版本、更新时间和内容区域。PDF 页面加载后由本地 `student.js` 立即把 object 指向当前路径的 `/content`；图片立即用自适应 `<img>` 按原比例显示，两者都不要求学生先点击。

Stage 5 起，PDF 和图片统一使用私有基础 Preview 派生的逐页 WebP；页面不提供全屏原件、查看原图或下载按钮。第一页面立即加载，后续页由本地脚本懒加载。页面不加载外部 CDN、PDF.js 或大型前端框架。

进入 `/q/{public_token}` 时服务端创建短期 HttpOnly Viewer Session 并固定本次访问的 revision；manifest 和页面接口都需要该 Cookie。每一页由服务端加入匿名 trace_code 水印，返回 `private, no-store`，不把原件 SHA、路径、Token 或完整 IP 暴露给学生。

外部网页不自动打开、不嵌入 iframe。学生先看到“此解析内容由外部网站提供”、目标域名和风险提示，明确点击“打开外部解析”后才使用 307 临时跳转。服务端只重新校验 URL、DNS 和目标 IP，不抓取第三方网页。

## 解析语义

- `latest` alias 每次请求读取 `current_published_revision_id`。
- `pinned` alias 每次请求读取 `pinned_revision_id`。
- `/q/.../content` 使用 307 跳转，不使用永久 301。
- `/content/{revision_key}` 只解析确定的 published revision，不查询最新版。
- 外部跳转目标只来自已发布版本，不能被请求 query 参数覆盖。
- resource 或 alias 停用时返回 410；文件丢失返回 503。

## 错误文案

- 不存在：“没有找到对应的解析资料，请确认二维码是否完整。”
- 停用：“该解析资料暂时不可用。”
- 未发布：“这份解析暂未发布，请稍后再试。”
- 文件丢失：“解析文件暂时无法打开，请稍后重试。”
- 系统异常：“系统暂时无法处理请求，请稍后再试。”

错误页不展示 traceback、数据库、存储路径或管理员入口。
