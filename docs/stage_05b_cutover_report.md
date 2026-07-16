# Stage 5B 切换报告

## 切换条件

- Stage 5A 基线：PASS。
- current 文件预览覆盖：5/5。
- pinned 文件预览覆盖：1/1。
- 缺失或损坏：0。
- 不支持的启用测试资料：0；原 `text/plain` 测试资料已按用户确认停用。

## 行为变化

- 学生 PDF/图片由原件直出切换为逐页 WebP。
- 第一页立即显示，后续页懒加载。
- `/q/.../content` 与旧 `/r` 不再返回原件。
- 匿名 `/content/{revision_key}` 返回 403。
- 管理员原件改走受 Session 保护的专用接口并记审计。
- 发布门禁默认开启，并验证 PreviewSet、页数、文件存在、WebP 可打开与 SHA-256。
- 外部 URL 受控预览策略默认 disable。

## 现场 HTTP 验证

- 学生 HTML：200，包含第一页 eager URL 和第二页 lazy `data-src`，不含原件地址或下载按钮。
- manifest：200，只返回四个允许字段。
- 第一页：200 `image/webp`、inline、private/no-store。
- 文件 `/q/.../content`：307 返回对应预览页。
- 匿名 `/content/{revision_key}`：403 中文页。
- 旧 `/r`：307 返回对应 `/q`。
- 未登录管理员原件接口：303 到登录页。
- 服务日志显示学生页、CSS、JavaScript 和第一页 WebP 均被实际请求且无 5xx。

应用内浏览器控制未能完成完整的视觉滚动检查；物理手机和真实浏览器懒加载滚动仍标记为未验证。

回退到 Stage 5A 行为只允许作为故障处置：停止新服务容器，恢复 Stage 5A 提交及对应 Compose 配置；不得通过重新开放匿名 `/content` 临时绕过安全控制。回退前仍保留 schema 4、原件和预览数据。
