# Stage 05C Viewer Session 设计

## 生命周期与版本语义

- `GET /q/{token}` 解析当前可见版本后创建 32 字节随机令牌；Cookie 只保存原始令牌，SQLite 只保存独立密钥的 HMAC-SHA256。
- Cookie 为 `HttpOnly; SameSite=Lax; Path=/`，Max-Age 与 30 分钟绝对有效期一致，Secure 由部署配置控制。
- 会话固定 `qr_alias_id + revision_id`。动态码发布后旧会话仍读取原修订；重新进入主页面创建新会话并读取新修订。固定码锁定 pinned 修订。
- manifest 和 page 依次校验令牌、状态、绝对/空闲过期、别名、修订、页码、单会话总量、分钟速率和全局并发门。
- 失效、撤销、错别名和缺少 Cookie 均返回中文错误页；页面 URL 被转发时仍因缺少 Cookie 被拒绝。

## 数据与限速

`viewer_sessions` 保存令牌 HMAC、匿名 `trace_code`、别名、修订、时间、状态、可选 UA/网络 HMAC、页面与拒绝计数。`viewer_access_events` 只保存最小事件类型、页码、结果、时间与脱敏 JSON。

页面默认 120 次/分钟、manifest 30 次/分钟、单会话最多 1000 页。进程内滑动窗口限制单会话速率；全进程 `BoundedSemaphore(6)` 限制同时动态编码。超限返回 429、中文提示与 `Retry-After: 60`。这是资源保护和基础反滥用，不是完整防爬。

## 管理

`/admin/viewer-sessions` 可按 trace code、资料编号或名称查询并撤销会话，仅展示匿名运营字段，不展示 Cookie、令牌 HMAC、完整 IP 或原始 UA。
