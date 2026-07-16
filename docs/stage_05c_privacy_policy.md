# Stage 05C 隐私策略

- 默认不保存完整 IP，`VIEWER_STORE_NETWORK_FINGERPRINT=false`。
- 不保存原始 User-Agent；启用时只保存以部署密钥计算的 HMAC。
- 不收集姓名、电话、学号；trace code 只能定位匿名会话，不能证明个人身份。
- 不做硬 IP 绑定，网络变化不会使合法会话立即失效。
- 原始 Viewer Token 只存在于 HttpOnly Cookie，不写数据库、HTML、JavaScript、URL、管理员页或访问事件。
- 访问事件默认保留 30 天，可通过 `cleanup_events()` 清理；详情只允许脱敏数据。
- 水印用于提高非授权传播成本，不宣称能阻止截图、录屏或识别真实个人。
