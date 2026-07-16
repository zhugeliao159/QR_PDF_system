# Stage 5B 原件访问策略

匿名学生不能通过 `/q`、`/r` 或 `/content/{revision_key}` 获得原始 PDF、PNG、JPEG 或 WebP。旧 `/content` 匿名请求返回中文 403，不生成磁盘路径、对象存储地址或签名 URL。

管理员登录后使用：

```text
GET /admin/revisions/{revision_key}/original
GET /admin/revisions/{revision_key}/original?download=true
```

接口要求管理员 Session，响应使用 private/no-store，支持 UTF-8 中文文件名，并记录 `view_original_asset` 审计事件。旧 `/content/{revision_key}` 仅保留管理员会话兼容访问，不属于学生接口。

`PROTECTED_PREVIEW_EXTERNAL_URL_POLICY` 默认 `disable`。外部网址不受本系统原件隔离控制；warn/allow 模式必须明确告知学生外部网站可能提供下载、复制或跳转功能。
