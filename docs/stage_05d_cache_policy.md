# Stage 05D 缓存策略

- 学生 HTML、manifest、错误页和动态水印 WebP 均返回 `Cache-Control: private, no-store, max-age=0` 与 `Pragma: no-cache`。
- 管理员原件响应为 `private, no-store, max-age=0`，避免共享代理和浏览器持久缓存敏感原件。
- 基础 PreviewPage 仅位于服务端私有 storage，不存在匿名直出路由；学生收到的是按 Viewer Session 临时生成的水印派生页。
- 静态 CSS/JS 可由浏览器按普通静态策略加载，但必须带 nosniff、no-referrer、same-origin CORP 和禁用相机/麦克风/定位的 Permissions-Policy。
- 当前不使用 CDN。以后如接入 CDN，不得缓存携带 Viewer Cookie 的响应，不得把 Cookie 从缓存键中忽略，也不得跨 Session 复用动态水印页。
- 水印缓存只允许短期、按 Session 隔离，过期后由清理 CLI 删除；它不是备份对象。

CSP 固定为同源脚本、样式、图片、字体和连接，禁止 object、frame、frame ancestor，禁止修改 base URI 和提交到外域；不使用 `unsafe-eval` 或 `unsafe-inline`。
