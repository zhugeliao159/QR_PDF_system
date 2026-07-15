# Stage 5A 实施与审核报告

## 结论

状态：PASS。

本阶段建立了私有原件与 WebP 预览衍生数据的 schema 4、PDF/图片 renderer、可恢复 Preview Worker、管理员预览状态和存量回填命令；学生端仍保持 Stage 4 行为。

## 基线与迁移

- 实施前 Stage 4 自动化：115 passed，5 条第三方 SWIG 弃用警告。
- 实施后隔离容器自动化：124 passed，5 条相同警告。
- 正式库由 schema 3 成功迁移到 schema 4；迁移前自动创建 Stage 5A SQLite Backup API 备份。
- Stage 4A 数据映射校验在迁移后为 PASS：数据库完整性正常，legacy 原件缺失、大小和 SHA-256 不一致均为 0，二维码 token 映射不变。

## 预览与回填

- `preview_sets`、`preview_pages`、`preview_jobs` 已创建。
- 正式环境先 dry-run，再对 5 个可渲染的当前发布版本提交小批量回填。
- Preview Worker 完成 5 个 PreviewSet、70 个 PreviewPage，任务均为 completed。
- 另有 1 个历史兼容 `text/plain` 当前版本不属于本阶段支持的 PDF/PNG/JPEG/WebP 类型，回填命令明确跳过它；未修改其 Asset、revision 或二维码。
- PDF 使用 144 DPI、WebP quality 82、method 4、最大 500 页、最大宽度 2000 px。

## Worker 与资源

新增 `preview-worker`：单进程、无对外端口、1 CPU、768 MiB、64 PIDs、非 root、capability drop、`no-new-privileges`、日志轮转和 `restart: unless-stopped`。任务领取、失败清理、超时恢复、幂等 completed 集合和原件 SHA-256 校验均有自动化覆盖。

## 已知边界与 Stage 5B 前置条件

- 预览页仍是可由已获授权页面保存的浏览器资源；系统不能保证阻止截图、录屏或保存网页收到的预览图片。
- Stage 5A 不切换学生端、不关闭原始内容入口、不添加水印或 Viewer Session。
- Stage 5B 只能针对具有 completed PreviewSet 的受支持已发布版本切换学生端；外部网页和非支持 MIME 类型必须保留明确的产品分流策略。
