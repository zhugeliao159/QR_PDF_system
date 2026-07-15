# 练习册二维码解析系统：当前环境、资源、进度与后续需求

更新时间：2026-07-15 10:40 CST

远端项目：`/home/user/projects/qr-exercise-prototype`

Windows 副本：`D:\codex_project\QRPDF_server\qr-exercise-prototype`

## 当前结论

第二阶段最小业务闭环已经完成并部署。系统目前可以创建永久二维码 ID、绑定和替换解析文件、保留最近 5 个版本、查询与回滚版本，并把二维码写入单个 PDF 的指定页和四角预设位置。自动化测试、真实 HTTP 端到端测试、容器重启和完整 `docker compose down/up` 持久化测试均已执行。

当前仍是仅通过 SSH 隧道访问的内部原型，不是公网生产系统。

## 环境与资源

| 项目 | 当前值 |
| --- | --- |
| 操作系统 | Ubuntu 22.04.2 LTS，x86_64 |
| CPU / 内存 | 24 逻辑 CPU / 30 GiB |
| 可用磁盘 | 约 299 GiB |
| Docker / Compose | 29.6.1 / v5.3.1 |
| QuickDrop | v1.5.3，healthy，`127.0.0.1:18080` |
| PDF Worker | healthy，`127.0.0.1:18081` |
| PDF Worker 限制 | 1 CPU、512 MiB、128 PIDs |
| PDF Worker 实测内存 | 约 50.76 MiB |
| 新业务数据占用 | 数据库约 60 KiB，存储约 52 KiB |

两个服务都仅发布到远端主机 `127.0.0.1`。PDF Worker 使用非 root `appuser`，启用 `no-new-privileges`、`cap_drop: ALL` 和 Docker 日志轮转。

## 已完成能力

- SQLite schema version 1：`bindings`、`file_versions`、`pdf_jobs`。
- `LocalStorageBackend`：流式上传、100 MiB 默认上限、SHA-256、临时文件和原子改名、路径限制和符号链接拒绝。
- 永久入口：`/r/{qr_id}`。
- 二维码 PNG：内容为 `{PUBLIC_BASE_URL}/r/{qr_id}`。
- 文件替换不改变 `qr_id` 和 `qr_url`。
- 每个绑定最多保留最近 5 个独立文件版本。
- 历史版本查询和回滚。
- PDF 指定页与四角预设位置写入，支持 `size_mm` 和 `margin_mm`。
- 输出 PDF 重开、页数、大小和 SHA-256 校验。
- 失败 PDF 作业保留明确错误状态，API 不暴露内部路径或 traceback。
- `/health` 与 `/capabilities` 检查数据库、存储和运行依赖。
- 生产镜像不包含测试依赖；测试 profile 不挂载真实业务数据。

详细接口见 `docs/stage_02_api.md`，实测证据见 `docs/stage_02_report.md`。

## 验证进度

- Python `compileall`：通过。
- Compose 配置校验：通过。
- 自动化测试：通过，最终数量以 `stage_02_report.md` 为准。
- 真实 E2E：创建绑定、二维码 PNG、2 页 PDF 右下角写入、下载、替换、版本列表、回滚全部通过。
- 人工图像检查：二维码清晰，页边距正确，无越界和裁切。
- PDF Worker 容器重启：绑定、永久入口、作业和输出仍存在。
- 完整 Compose down/up：上述数据仍存在，QuickDrop 恢复 healthy。
- QuickDrop 数据库未被直接编辑，已有上传文件未被本阶段操作。

## 使用入口

Windows PowerShell 保持以下隧道运行：

```powershell
ssh -L 18080:127.0.0.1:18080 -L 18081:127.0.0.1:18081 tx
```

- QuickDrop：<http://127.0.0.1:18080>
- PDF Worker API 文档：<http://127.0.0.1:18081/docs>
- 健康检查：<http://127.0.0.1:18081/health>
- 能力检查：<http://127.0.0.1:18081/capabilities>

注意：二维码中的 `127.0.0.1` 只对建立 SSH 隧道的 Windows 电脑有效。手机扫码时，`127.0.0.1` 指向手机自身，无法访问服务器。

## 下一阶段需求

进入真实用户试用前，优先需要确认和实现：

1. 决定手机可达地址：局域网、Tailscale 或正式域名与 HTTPS。
2. 增加认证、授权和审计，不能在公网直接暴露当前无鉴权接口。
3. 制定 SQLite 和业务文件的一致性备份、恢复演练与保留周期。
4. 根据实际操作流程决定是否增加管理界面。
5. 再评估批量上传、批量写入、ZIP 导出、多二维码和任意坐标。
6. 明确学生数据范围、隐私规则、文件保留和删除策略。

当前未实现：批量任务、PDF 合并、多二维码写入、拖拽或任意坐标、用户系统、扫码统计、公网域名、HTTPS、队列、外部数据库、Kubernetes 和正式生产备份系统。
