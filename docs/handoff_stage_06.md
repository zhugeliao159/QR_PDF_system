# Stage 6 交接

更新时间：2026-07-19（Asia/Shanghai）

## 当前事实

- 权威仓库：`/home/user/projects/qr-exercise-prototype`。
- 当前部署为纯 LAN：管理端 `192.168.100.20:18081`；学生公网占位入口 `127.0.0.1:18082`。
- Funnel 关闭，状态为 `No serve config`。
- SQLite schema 6，完整性检查通过；不要删除或重建正式 `data/`。
- 最终自动化基线为 `176 passed`，匿名原件泄露审计通过。
- Stage 6 已推送至 `agent/stage6-batch-management`，Draft PR：`https://github.com/zhugeliao159/QR_PDF_system/pull/1`；服务器日常工作区仍保持在 `main`。
- 二级删除密码尚未由用户设置，永久删除功能会安全地显示为禁用。

## 主要入口

- 管理后台：`http://192.168.100.20:18081/admin`
- 批量导入：`/admin/materials/import`
- 学生服务健康检查：`http://127.0.0.1:18082/health`
- 批量导入实现：`pdf-worker/app/services/batch_import_service.py`
- 永久删除实现：`pdf-worker/app/services/deletion_service.py`
- 详细行为：`docs/stage_06_batch_management.md`
- 验收记录：`docs/stage_06_final_report.md`

## 运维约束

- 不要把 `.env`、密码、哈希、Session secret 或 Viewer secret 写入 Git、文档或对话。
- 不要执行 `docker compose down -v`、递归删除 `data/` 或重建数据库。
- 未来启用公网时，Funnel 目标只能是 `http://127.0.0.1:18082`，不能代理完整管理服务。
- 设置二级密码必须由用户在服务器终端交互完成，之后只需重建 `pdf-worker`。
- 未获得用户明确授权前不要 push GitHub。
