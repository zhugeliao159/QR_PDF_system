# Stage 05C 动态水印设计

基础 WebP 保持只读。每次合法页面请求读取基础图，Pillow 在服务端把重复、倾斜、低透明度文字直接混入 RGB 像素，再编码为 WebP；浏览器没有可关闭的 CSS 水印层。

水印仅包括“在线预览”、资料编号、匿名 trace code 和当前日期时间，不含 Cookie、原始令牌、IP、姓名、电话或学号。不同会话使用不同 trace code，输出像素不同。

仓库不携带字体二进制。`WATERMARK_FONT_PATH` 指向且支持中文时使用配置模板；否则使用 `PREVIEW ONLY | trace | material | timestamp`。`/capabilities` 和管理员会话页明确显示中文字体或 ASCII 回退状态。

本阶段不写水印磁盘缓存，因此无需清理含 trace 的派生文件。实现直接在 RGB 基图上按 alpha mask 贴入旋转文字，避免整页 RGBA 叠加层；请求结束显式释放 Pillow 对象，全局最多同时编码 6 页。
