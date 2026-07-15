# Stage 4B 报告

## 结论

- 状态：**PASS**
- 新学生入口、动态解析、不可变内容、pinned alias 与旧入口兼容均已部署。
- 草稿发布和外部 URL 未实现，管理员上传仍立即生效。

## 新学生入口

- `/q/{token}`：中文 HTML，`no-store`，页面不重复输出 token 或 SHA-256。
- `/q/{token}/content`：307 到每次重新解析的 revision，`no-store`。
- `/content/{revision_key}`：确定版本内容，1 年 immutable 缓存。
- PDF：object 在本地脚本执行后立即设置 content URL；无需额外点击。
- 备用：object 内中文提示，同时保留全屏打开和下载按钮。

## 二维码

- 新动态二维码：`{PUBLIC_QR_BASE_URL}/q/{public_token}`。
- 新固定二维码：幂等创建独立 pinned alias，不暴露 revision ID。
- PDF 动态/固定写码都使用新的 `/q` 地址。
- 旧 `/r` 与旧固定版本入口继续直接返回原文件。

## 缓存实测

- `/q`：HTTP 200，`no-store, must-revalidate`。
- `/q/content`：HTTP 307，`no-store, must-revalidate`。
- `/content`：HTTP 200，`public, max-age=31536000, immutable`。
- ETag：当前 asset SHA-256（带双引号）。
- If-None-Match：HTTP 304，body 0 bytes。

正式数据 current PDF 的返回大小与 SHA-256 一致；旧固定版本与 pinned alias 返回历史 PDF 的大小与 SHA-256 一致。

## 验证结果

- 自动化：72 passed，0 failed，0 skipped；5 条既有 SwigPy 弃用警告。
- Stage 4B live-check：PASS。
- Stage 4A 迁移校验：PASS；2 个迁移 latest alias，新增 1 个合法 pinned alias。
- Stage 4A 旧入口回放：9/9 PASS。
- 桌面浏览器 1280x800：无横向溢出，操作按钮不重叠。
- 手机 CSS：390px 断点由自动化和静态规则覆盖。
- 真实手机扫码：**未验证**。代理无法操作用户手机；当前 LAN 地址从 Windows 可达。

## 网络与资源

- PDF Worker：healthy，`192.168.100.20:18081`。
- QuickDrop：healthy，`127.0.0.1:18080`。
- 网络绑定、1 CPU、512 MiB、128 PIDs 限制未改变。

## 遗留风险

- 不同手机内置浏览器对 PDF object 的支持不同；不支持时使用“全屏打开”。
- 当前 IP 仅适合局域网测试，不适合正式印刷。
- 真实手机需在同一 Wi-Fi 扫一次新 `/q` 二维码完成最终体验复核。
