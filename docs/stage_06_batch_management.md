# Stage 06 批量资料管理与独立学生入口

## 批量上传

管理员从 `/admin/materials/import` 选择最多 100 份 PDF，单文件沿用 100 MiB 限制，单批总量不超过 2 GiB。请求只完成安全落盘和任务入队；`preview-worker` 依次校验 PDF、创建资料、生成私有 WebP 预览并发布。

资料名称取 NFC 规范化后的 PDF 文件名（不含扩展名）。若名称已存在，使用最小可用的 `(n)` 后缀。每个文件独立成功或失败，批次进度持久保存在 schema 6 的 `batch_imports` 与 `batch_import_items`。

成功资料的 Asset 可以保存在私有 `storage/batch-imports/`；因此备份脚本必须包含该目录。失败项删除暂存文件，若已经创建未发布资源，则同时回滚资源、版本、预览和 Asset。

## 永久删除

永久删除需要管理员 Session、CSRF、独立 `DELETION_PASSWORD_HASH` 和文字确认。二级密码不进入 Session，每次操作都重新验证；10 分钟内失败 5 次后锁定 15 分钟。

删除前后都重新检查引用。固定二维码、revision reference、任何练习册 PDF 任务，以及 processing/pending 的预览或批量任务都会阻止对应资料删除。批次采用部分成功语义。

可删除资料的 Asset 先原子移动到 `.trash`，Preview 目录整体移动到私有 trash，再在 SQLite `BEGIN IMMEDIATE` 事务中删除 Viewer 事件、Session、Preview、Alias、Revision、Asset 和 Resource。事务失败时文件原路恢复；提交后才清除 trash。旧 Stage 3 映射数据在无引用时同步清除。

## 局域网与公网占位

- 管理和当前二维码：`http://192.168.100.20:18081`。
- 学生公网占位：`http://127.0.0.1:18082`，Docker 服务名 `student-public`。
- 当前不启用 Tailscale Funnel。

`student-public` 只注册 `/q`、兼容 `/r`、两项学生静态资源和 `/health`；后台、管理 API、原件接口和管理员静态资源均不可用。

未来临时公网测试前，先把 `PUBLIC_QR_BASE_URL` 改为公网 HTTPS、把 `VIEWER_COOKIE_SECURE` 改为 `true`，重建 `pdf-worker` 和 `student-public`，再由负责人在服务器执行：

```bash
sudo tailscale funnel --bg --yes http://127.0.0.1:18082
```

恢复公网不会改变已经印刷在旧二维码中的 LAN 地址，因此用于公网的二维码必须重新生成。
