# Stage 5B 交接

Stage 5B 将匿名学生交付从原始文件切换为分页 WebP。当前 schema 仍为 4；无需新增数据库表。current 文件 alias 5/5、pinned 文件 alias 1/1 均有完整预览。

关键入口：

- 学生：`/q/{token}`、`/q/{token}/manifest`、`/q/{token}/pages/{n}`。
- 旧二维码：`/r/{token}` 与旧固定版本入口使用 307 临时跳转。
- 管理员原件：`/admin/revisions/{revision_key}/original`。
- 库存审计：`python -m app.scripts.audit_preview_cutover`。

默认配置必须保持：

```text
REQUIRE_PREVIEW_BEFORE_PUBLISH=true
PROTECTED_PREVIEW_EXTERNAL_URL_POLICY=disable
```

Stage 5C 在现有 page 接口上增加 Viewer Session 和动态水印；不得重新开放匿名原件接口，也不得改变 latest/pinned alias 语义。继续禁止修改 QuickDrop、网络配置和既有 token。
