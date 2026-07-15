# Stage 4B 学生答案页规范

## 入口

- 新二维码入口：`GET /q/{public_token}`。
- 动态解析：`GET /q/{public_token}/content`。
- 不可变文件：`GET /content/{revision_key}`。
- 旧 `/r/{qr_id}` 与 `/r/{qr_id}/versions/{version_id}` 保持兼容。

二维码只包含不可猜的 public token，不包含文件名、存储路径或数据库自增 ID。页面正文不展示 token、revision key、SHA-256、API JSON 或管理员入口。

## 页面内容

学生页面为简体中文，面向手机竖屏，显示资料名称、可选年级/学科/章节、当前版本、更新时间和内容区域。PDF 页面加载后由本地 `student.js` 立即把 object 指向当前路径的 `/content`，不要求学生先点击。

页面同时提供“全屏打开”和“下载文件”。object 内置中文备用提示，浏览器不支持内嵌 PDF 时可以直接打开。页面不加载外部 CDN、PDF.js 或大型前端框架，也不在服务端把 PDF 转成图片。

## 解析语义

- `latest` alias 每次请求读取 `current_published_revision_id`。
- `pinned` alias 每次请求读取 `pinned_revision_id`。
- `/q/.../content` 使用 307 跳转，不使用永久 301。
- `/content/{revision_key}` 只解析确定的 published revision，不查询最新版。
- resource 或 alias 停用时返回 410；文件丢失返回 503。

## 错误文案

- 不存在：“没有找到对应的解析资料，请确认二维码是否完整。”
- 停用：“该解析资料暂时不可用。”
- 未发布：“这份解析暂未发布，请稍后再试。”
- 文件丢失：“解析文件暂时无法打开，请稍后重试。”
- 系统异常：“系统暂时无法处理请求，请稍后再试。”

错误页不展示 traceback、数据库、存储路径或管理员入口。
