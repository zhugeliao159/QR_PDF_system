# Stage 5A 预览渲染设计

## 渲染接口

`PreviewRenderer` 只接收私有原件路径、临时输出目录和渲染配置，返回逐页元数据；不发布版本、不修改资料当前指针、不解析二维码、不创建学生会话，也不负责数据库事务。

`PreviewService` 创建和原子领取任务、选择 renderer、保存 PreviewSet/PreviewPage、更新进度、处理重试与超时恢复，并清理失败临时目录。

## PDF

`PdfPreviewRenderer` 使用 PyMuPDF 逐页加载和 Pillow 重新编码，不会把所有页面同时放入内存。默认参数为 144 DPI、WebP quality 82、method 4、最大 500 页、最大渲染宽度 2000 px、renderer version `v1`。

每页流程：渲染无 alpha Pixmap、转换 RGB、按最大宽度缩小、写入四位页码 WebP、重新用 Pillow 打开、检查尺寸和非零大小、计算 SHA-256，然后释放 Page、Pixmap、Pillow Image 和 BytesIO。加密、损坏、空白或超页数 PDF 返回明确错误码。

## 图片

`ImagePreviewRenderer` 仅接受 PNG、JPEG、WebP 的真实 Pillow 格式。它应用 EXIF 方向、拒绝像素过大图片、对透明像素合成白底、转 RGB、按最大宽度缩小并重新编码为新的 WebP。输出不复制 EXIF 或其他原始识别元数据，也绝不把 PNG/JPEG/WebP 原件伪装成预览文件。

## 任务恢复

SQLite 使用 foreign keys、WAL 和 busy timeout。worker 单进程、一次只领取一个任务。超过 `PREVIEW_JOB_STALE_SECONDS` 的 processing 任务会清除临时目录；若还有尝试次数则回到 pending，否则显式 failed。无论重试次数如何，完成集合的唯一约束与任务领取事务都避免产生两份 completed PreviewSet。

Stage 5A 不添加动态水印、不创建 Viewer Session、不关闭 `/q/{token}/content` 或 `/content/{revision_key}`，也不改变学生页面。这些切换留给 Stage 5B 之后的阶段。
