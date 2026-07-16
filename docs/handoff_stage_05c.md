# Stage 05C 交接

## 运行配置

部署必须提供独立的 `VIEWER_SESSION_SECRET`（至少 32 字节）。默认 TTL 30 分钟、空闲 10 分钟、页面 120/分钟、manifest 30/分钟、总页数 1000、全局动态编码并发 6。未配置中文字体时自动显示 ASCII 水印并在 capabilities 报告回退。

## 运维检查

1. `/health` 为 ok，`/capabilities` schema_version 为 5。
2. 扫码主入口响应包含 HttpOnly Cookie 和匿名 trace；直接访问 manifest/page 无 Cookie 应被拒绝。
3. 管理员在 `/admin/viewer-sessions` 可查询和撤销，不应看到 token/HMAC/IP/原始 UA。
4. 原始文件仍只走管理员认证路由。
5. 如需定期清理访问事件，调用 `ViewerSessionService.cleanup_events()`；当前没有水印磁盘缓存。

## 回滚关注

迁移前数据库自动备份到 `data/pdf-worker/db/backups/app-before-stage05c-v4-*.db`。回滚应用前必须同时回滚数据库副本；不要只降级代码后继续使用 schema 5 写入。QuickDrop 保持停止且未修改。
