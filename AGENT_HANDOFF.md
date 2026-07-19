# QR PDF System Agent 交接文档

更新时间：2026-07-19（Asia/Shanghai）

## 0. 接手时先看这里

这是“练习册二维码解析系统”的当前总交接。Stage 1 至 Stage 5D 已完成，远程权威仓库已提交并推送 GitHub；下一位 Agent 不需要重新部署或重做 Stage 5。

当前最重要的事实：

- **唯一权威代码和 Git 工作区**：Linux 远程机 `/home/user/projects/qr-exercise-prototype`。
- **Stage 5 业务代码基线**：`ce4a367`；本交接文档的独立提交位于其后。实际 HEAD 以 `git log -1` 为准。
- **最终自动化基线**：`168 passed, 0 failed, 0 skipped`。
- **当前运行**：`pdf-worker`、`preview-worker`、`quickdrop` 三个容器都在运行；PDF Worker 健康。
- **局域网管理入口**：`http://192.168.100.20:18081/admin`。
- **当前公网 Funnel 已关闭**：`tailscale funnel status` 返回 `No serve config`，`https://tx.tailfacd1a.ts.net` 当前不可达。
- **但 `.env` 仍是公网模式**：二维码基址仍为 `https://tx.tailfacd1a.ts.net`，`VIEWER_COOKIE_SECURE=true`。因此接手后必须先选择“重新开启 Funnel”或“恢复 LAN 配置”，不要误以为当前学生扫码链路可用。
- 用户明确说明：当前放入系统的数据都是测试数据，没有业务保留价值。但未经用户明确授权仍不要自行删除数据库、文件或容器数据。
- 不记录也不要索取管理员密码、Session secret、Viewer secret、GitHub Token 或 Linux sudo 密码。

接手后第一组命令：

```powershell
ssh tx "cd /home/user/projects/qr-exercise-prototype && git status -sb && git log --oneline -8 && docker compose ps -a && curl -fsS http://192.168.100.20:18081/health"
ssh tx "tailscale funnel status"
```

预期 Git 状态：

```text
## main...origin/main
```

## 1. 环境与权威边界

### Windows 操作机

- 系统：Windows 11 家庭中文版，64 位。
- Shell：Windows PowerShell 5.1。
- 当前工作区：`D:\codex_project\QRPDF_server`。
- SSH 别名：`tx`。
- 本文件：`D:\codex_project\QRPDF_server\AGENT_HANDOFF.md`。

PowerShell 5 读取 UTF-8 中文文件时要显式指定编码：

```powershell
Get-Content -Raw -Encoding UTF8 D:\codex_project\QRPDF_server\AGENT_HANDOFF.md
```

本机有两个容易误导的代码目录：

- `D:\codex_project\QRPDF_server\qr-exercise-prototype`：无 `.git` 的旧文件镜像，主要停留在 Stage 4。
- `D:\codex_project\QRPDF_server\qr-exercise-prototype-git`：旧的 Stage 5 WIP Git 副本，当前在 `stage5d-wip`，有大量未提交修改，`origin/main` 也停留在旧提交。

**这两个目录都不是权威提交源。不要在其中提交、清理、reset 或覆盖文件。** 如需本地 Git 工作区，应从 GitHub 另行克隆到新目录，或直接在远程权威仓库操作。

### Linux 远程机

- SSH：`ssh tx`。
- 主机名：`tx`。
- 系统：Ubuntu 22.04.2 LTS，`x86_64`。
- LAN 地址：`192.168.100.20/23`。
- Tailscale 地址：`100.110.246.123/32`。
- Tailscale：1.98.8。
- 权威项目：`/home/user/projects/qr-exercise-prototype`。
- Docker：29.6.1。
- Docker Compose：v5.3.1。
- 宿主 Python：3.10.12。
- 当前 `data/`：约 35 MiB。

SSH 用户的 `sudo` 不是免密。需要修改 Tailscale Funnel 等 root 配置时，必须请用户在远程终端亲自执行 sudo 命令，不得要求用户把密码发到对话里。

### GitHub

- 仓库：[zhugeliao159/QR_PDF_system](https://github.com/zhugeliao159/QR_PDF_system)
- 可见性：Public。
- 默认分支：`main`。
- 远端：`https://github.com/zhugeliao159/QR_PDF_system.git`。
- Git 作者：`zhugeliao159 <519512600@qq.com>`。
- 当前 GitHub 业务代码基线：`ce4a367`；交接文档若尚未 push，本地 `main` 会比 `origin/main` 多一个提交。

历史上使用过的 GitHub PAT 不得复用、打印、写入远端 URL 或文档。推送前检查 `git remote -v`，确保 URL 不含凭据。

## 2. 当前 Git 与阶段进度

| 阶段 | 提交 | 状态 | 核心内容 |
| --- | --- | --- | --- |
| 4A | `cf50cc1` | PASS | schema 3、业务数据解耦、迁移兼容 |
| 4B | `9d3f708` | PASS | 中文学生入口、动态/固定二维码、不可变版本 |
| 4C | `92d2ccc` | PASS | 草稿、预览、发布、历史重发、并发保护、审计 |
| 4D | `3bf4f24` | PASS | PDF/PNG/JPEG/WebP、受控外部 URL |
| 5A | `590c79b` | PASS，124 tests | 私有预览数据模型、渲染、回填、Preview Worker |
| 5B | `195a208` | PASS，130 tests | 学生端切换到逐页私有 WebP，发布前强制预览 |
| 5C | `bbac1e2` | PASS，154 tests | Viewer Session、匿名水印、限速、吊销与隐私边界 |
| 5D | `556b831` | PASS，168 tests | 安全审计、清理、备份恢复、Worker 恢复、负载测试 |
| 5D 收尾 | `ce4a367` | PASS | 记录最终清理验证 |

已有标签：

- `stage-03-baseline`
- `stage-04-baseline`，指向 Stage 4 实施前设计基线 `61957c7`

不要 force push，不要改写 Stage 4/5 历史，不要对用户文件执行 `git reset --hard` 或 `git clean -fd`。

## 3. 项目架构

```text
管理员浏览器 / 学生扫码
          |
          v
pdf-worker（FastAPI，宿主 192.168.100.20:18081 -> 容器 8000）
  |-- 管理后台、登录 Session、CSRF、审计
  |-- 二维码、资料、草稿、发布、固定版本、练习册 PDF 生成
  |-- 学生 Viewer Session、manifest、动态水印 WebP、限速
  |-- SQLite app.db
  `-- bind-mounted 私有存储

preview-worker（同一镜像，无对外端口）
  |-- 领取 preview_jobs
  |-- PDF 逐页渲染 WebP
  |-- PNG/JPEG/WebP 解码、去元数据、重编码 WebP
  `-- 与 pdf-worker 共用 SQLite 和 storage

quickdrop（独立第三方服务，127.0.0.1:18080）
  `-- 独立数据目录；PDF Worker 不读取或修改其数据库

可选公网入口：Tailscale Funnel
  https://tx.tailfacd1a.ts.net -> http://192.168.100.20:18081
  当前关闭
```

### 代码结构

- `pdf-worker/app/main.py`：FastAPI 应用、启动生命周期、中间件和安全响应头。
- `pdf-worker/app/config.py`：环境变量解析和安全校验。
- `pdf-worker/app/database.py`：SQLite schema 与幂等迁移，当前 schema 5。
- `pdf-worker/app/admin/routes.py`：中文管理员页面与写操作。
- `pdf-worker/app/routers/student.py`：`/q` 学生预览、manifest、分页图片。
- `pdf-worker/app/routers/redirects.py`：旧 `/r` 和兼容入口。
- `pdf-worker/app/services/decoupled.py`：QrAlias、Resource、Revision、Asset 等业务解耦逻辑。
- `pdf-worker/app/services/preview_service.py`：PreviewSet/Page/Job 的状态与完整性。
- `pdf-worker/app/services/preview_renderers.py`：PDF/图片转 WebP。
- `pdf-worker/app/preview_worker.py`：单进程预览任务循环。
- `pdf-worker/app/services/viewer_session.py`：匿名 Viewer Session、固定 revision、限速与事件。
- `pdf-worker/app/services/watermark.py`：服务端像素级匿名水印。
- `pdf-worker/app/services/cleanup_service.py`：引用安全的清理计划和执行。
- `pdf-worker/app/services/backup_service.py`：备份清单与哈希验证。
- `pdf-worker/app/storage/`：存储后端抽象与本地实现。
- `scripts/backup_stage05.sh`、`scripts/restore_stage05.sh`：Stage 5 备份恢复。

## 4. 已实现业务能力

### 管理员端

- 中文登录、签名 Session、CSRF 防护；Swagger/OpenAPI 默认关闭。
- 新建解析资料，上传 PDF、PNG、JPEG 或 WebP 答案。
- 保存草稿、生成预览、管理员预览、发布、重新发布历史版本、停用资料。
- 生成动态二维码或固定版本二维码。
- 上传练习册 PDF，设置页码、位置和大小，预览并下载带二维码练习册。
- 管理 Viewer Session 并吊销访问。
- 发布、停用、原件访问等关键动作进入审计。

### 学生端

- 新入口：`GET /q/{public_token}`。
- 旧 `/r/{qr_id}` 和旧固定版本入口通过兼容跳转继续可用。
- PDF/图片只以逐页 WebP 预览；第一页立即加载，后续懒加载。
- 不提供原始 PDF/PNG/JPEG/WebP 下载入口，也不显示下载按钮。
- `/manifest` 和 `/pages/{n}` 需要有效 Viewer Session Cookie。
- 动态二维码创建 Session 时固定当时已发布 revision；旧 Session 继续看旧版，重新扫码建立的新 Session 看新版。
- 固定二维码始终指向指定 revision。
- 每个 Session 有匿名 `trace_code`，水印烧录在返回图片像素中，不包含真实身份。
- Session 默认 TTL 30 分钟、空闲 10 分钟；页面限速 120/分钟，manifest 30/分钟；全局水印并发 6。
- 学生响应使用 `private, no-store`、CSP、nosniff、DENY 等安全头。
- 外部 URL 默认禁用，且不属于“受控预览”保护范围。

### 必须如实表述的产品边界

可以表述：

> 学生端不提供原始文件下载，内容采用在线分页预览，并通过访问控制和追踪水印降低复制与传播风险。

不得承诺“绝对无法下载、截图或传播”。系统无法阻止截图、录屏、OCR、另一台设备拍摄，或技术用户保存浏览器已经接收的派生 WebP。

## 5. 数据模型与持久化

当前 SQLite schema 为 5。核心业务关系：

- `QrAlias`：稳定的动态或固定二维码身份。
- `AnswerResource`：资料业务身份。
- `AnswerRevision`：不可变答案版本，包含草稿/发布语义。
- `Asset`：私有原始 PDF 或图片。
- `PreviewSet`：某 revision、渲染版本和配置的一套完整衍生预览。
- `PreviewPage`：连续编号的 WebP 页面。
- `PreviewJob`：可恢复、可重试的预览任务。
- `ViewerSession`：只存 HMAC 后的 Token 信息，固定访问 revision。
- `ViewerAccessEvent`：最小化访问事件，不默认存完整 IP。

重要路径：

| 内容 | 远程路径 |
| --- | --- |
| SQLite 主库 | `data/pdf-worker/db/app.db` |
| migration 备份 | `data/pdf-worker/db/backups/` |
| 原件/业务存储根 | `data/pdf-worker/storage/` |
| 私有预览 | `data/pdf-worker/storage/previews/` |
| 绑定文件 | `data/pdf-worker/storage/bindings/` |
| 上传练习册 | `data/pdf-worker/storage/source-pdfs/` |
| 生成练习册 | `data/pdf-worker/storage/generated-pdfs/` |
| QuickDrop | `data/quickdrop/` |

`.env` 和 `data/` 均不进入 Git。不要直接编辑 `app.db`，不要手工移动 storage 文件，不要修改 QuickDrop 数据库。

## 6. 当前运行态与配置陷阱

2026-07-19 最后核验：

- `pdf-worker`：运行且 healthy，绑定 `192.168.100.20:18081`。
- `preview-worker`：运行，无宿主端口。
- `quickdrop`：运行且 healthy，只绑定 `127.0.0.1:18080`。
- 最近核验未发现 PDF/Preview 服务 5xx。
- `git status` 干净。
- `tailscale funnel status`：`No serve config`。
- 公网健康检查：连接失败。

当前 `.env` 非敏感相关值：

```dotenv
QUICKDROP_PORT=18080
PDF_WORKER_PORT=18081
PDF_WORKER_BIND_ADDRESS=192.168.100.20
PUBLIC_BASE_URL=https://tx.tailfacd1a.ts.net
PUBLIC_QR_BASE_URL=https://tx.tailfacd1a.ts.net
SESSION_COOKIE_SECURE=false
VIEWER_COOKIE_SECURE=true
ENABLE_ADMIN_API_DOCS=false
```

`ALLOW_EXTERNAL_URLS` 未显式设置，使用安全默认 `false`。`SESSION_COOKIE_SECURE=false` 是为了 LAN HTTP 管理后台；公网学生 Cookie 已设置为 Secure。

### 选择 A：继续临时公网双人测试

请用户在 `tx` 终端执行：

```bash
sudo tailscale funnel --bg --yes http://192.168.100.20:18081
```

然后 Agent 验证：

```powershell
ssh tx "tailscale funnel status"
curl.exe -fsS --max-time 20 https://tx.tailfacd1a.ts.net/health
```

启用后，新下载的二维码使用公网 HTTPS。应用 `.env` 已经是公网模式，一般不需要重启；若修改过配置，再只重建 `pdf-worker`。

### 选择 B：恢复纯局域网测试

公网切换前的 `.env` 备份：

```text
/home/user/.qr-exercise-env-before-funnel-20260719T093643Z
```

该文件权限为 0600，已确认存在。恢复会把公网地址和 Viewer Secure Cookie 一并恢复到 LAN 模式：

```bash
cd /home/user/projects/qr-exercise-prototype
cp /home/user/.qr-exercise-env-before-funnel-20260719T093643Z .env
chmod 600 .env
docker compose up -d --force-recreate --no-deps pdf-worker
curl -fsS http://192.168.100.20:18081/health
```

执行恢复前必须先取得用户确认，因为它会改变新二维码的基础地址。

### 关闭 Funnel

需用户在远程终端执行：

```bash
sudo tailscale funnel --https=443 off
```

关闭 Funnel 不会自动还原 `.env`。

## 7. 常用运维命令

### 查看状态

```bash
cd /home/user/projects/qr-exercise-prototype
git status -sb
docker compose ps -a
docker compose logs --tail=200 pdf-worker preview-worker quickdrop
curl -fsS http://192.168.100.20:18081/health
```

`/capabilities` 需要管理员认证，匿名请求返回 401 是正常安全行为。

### 启动/更新服务

```bash
cd /home/user/projects/qr-exercise-prototype
docker compose config --quiet
docker compose build pdf-worker
docker compose up -d pdf-worker preview-worker
docker compose ps
```

只重建 PDF Worker，不动 QuickDrop/Preview Worker：

```bash
docker compose up -d --force-recreate --no-deps pdf-worker
```

安全停止并保留 bind-mounted 数据：

```bash
docker compose stop
```

不要执行 `docker compose down -v`、`docker system prune -a`、递归删除 `data/` 或 `chmod -R 777`。

### QuickDrop

QuickDrop 只监听远程回环地址。Windows 访问时建立 SSH 隧道：

```powershell
ssh -L 18080:127.0.0.1:18080 tx
```

保持窗口运行，浏览器访问 `http://127.0.0.1:18080`。不要为方便测试把 QuickDrop 暴露公网。

## 8. 测试、审计、回填与清理

### 全量自动化测试

```bash
cd /home/user/projects/qr-exercise-prototype
docker compose --profile test build pdf-worker-tests
docker compose --profile test run --rm pdf-worker-tests
```

最后通过结果：

```text
168 passed, 0 failed, 0 skipped
```

测试容器不挂载正式 `data/`，也不发布宿主端口。

### 原件泄露审计

```bash
docker compose exec -T pdf-worker python -m app.scripts.audit_public_original_access
```

最终审计的 11 个公开/越权请求未暴露原始 PDF、原图 SHA、Asset/storage/revision 下载地址或绝对路径。

### 预览回填

默认先 dry-run 和小批量：

```bash
docker compose exec -T pdf-worker \
  python -m app.scripts.backfill_previews --dry-run --only-current --limit 10
```

不要修改 public token、revision key、发布指针或原件 SHA-256。

### 安全清理

默认只能 dry-run：

```bash
docker compose exec -T pdf-worker python -m app.scripts.cleanup_storage --dry-run
```

只有用户明确批准删除计划后才运行：

```bash
docker compose exec -T pdf-worker python -m app.scripts.cleanup_storage --apply
```

清理逻辑会复核 current、pinned、PDF job、active draft 等引用；仍须先看 dry-run 输出。

### 备份与恢复

先阅读 `docs/stage_05d_backup_restore_guide.md`，使用：

```bash
scripts/backup_stage05.sh
scripts/restore_stage05.sh
```

已完成的恢复演练归档：

```text
/home/user/projects/qr-stage05-rehearsal-20260716.tar.gz
```

该文件约 29 MiB、权限 0600，包含真实配置，只能安全保管、转移到加密异机介质或经用户确认销毁。临时恢复副本仍位于：

```text
/tmp/stage05-restore-rehearsal-20260716
```

不要在未确认时覆盖正式数据。

## 9. Stage 5 已验证结果

- 最终样本：Resource 6、Revision 13、Asset 13、completed PreviewSet 8、PreviewPage 186。
- 当前发布覆盖 5/5，固定引用覆盖 1/1，无预览缺失或失败。
- Worker 中断后 stale 任务以 `attempts=2` 重领，无重复 completed set/page，不修改原件。
- 20 并发：240 请求；50 并发：600 请求；预期限速 429 分别 106/371，复测意外 5xx 为 0。
- pdf-worker 峰值约 210.6 MiB；preview-worker 峰值约 84.51 MiB；RestartCount 均为 0。
- 资源限制保持：pdf-worker 1 CPU/512 MiB/128 PIDs；preview-worker 1 CPU/768 MiB/64 PIDs。
- 备份归档和内部逐文件 SHA-256 通过；临时恢复后的数据库数量、动态/固定 alias 和文件哈希一致。

这些数量来自 Stage 5 最终验收时的测试样本，不是业务生产数据；后续测试操作可能改变当前数量。

## 10. 文档索引

Windows 根目录任务书：

- `task.txt`、`task2.txt`、`task3.txt`
- `Task4A.txt`、`Task4B.txt`、`Task4C.txt`、`Task4D.txt`
- `Task5A.txt`、`Task5B.txt`、`Task5C.txt`、`Task5D.txt`

远程权威仓库中优先阅读：

- `README.md`
- `docs/handoff_stage_05.md`
- `docs/stage_05_final_report.md`
- `docs/stage_05_security_boundary.md`
- `docs/stage_05d_route_audit.md`
- `docs/stage_05d_cache_policy.md`
- `docs/stage_05d_cleanup_guide.md`
- `docs/stage_05d_backup_restore_guide.md`
- `docs/stage_05d_load_test_report.md`
- `docs/handoff_stage_05a.md`
- `docs/handoff_stage_05b.md`
- `docs/handoff_stage_05c.md`
- Stage 4 对应 handoff 和 report。

根目录的 `stage5*-wip*.patch` 是历史中间补丁，不是当前事实来源，不要重新套用。

## 11. Git 工作方式

所有新业务改动应从远程权威仓库的干净 `main` 开始：

1. 阅读新任务书和相关设计。
2. 检查 `git status -sb`、最近提交、Compose 状态。
3. 先做基线测试；失败时停止，不修改正式数据。
4. 补测试并实现，保持 schema migration 幂等并先备份。
5. 运行目标测试、全量回归、运行态健康检查和真实扫码链路。
6. 更新 README、阶段报告和本交接文档。
7. 每个用户要求的小阶段单独审核、提交。
8. 只有用户授权时才 push；不要重写历史或 force push。

部署态 `.env` 变化不进入 Git。不要为“提交配置”而把秘密加入仓库。

## 12. 当前未实现与下一步方向

当前没有新的 Task 6 任务书。以下仅是 backlog，不代表用户已经批准：

- 正式公网域名、稳定 HTTPS、反向代理及长期运行方案。
- 云服务器或本地服务器的生产部署、自动续期证书和公网防护。
- 管理后台与学生入口的网络隔离；当前 Funnel 会转发整个 PDF Worker。
- 管理员 MFA、多管理员、角色权限。
- 自动异机加密备份、集中日志、监控、告警和高可用。
- 全局审计检索/导出、扫码统计、批量处理、学生账号。
- 隐私合规、数据保留周期和机构审批。

临时 Tailscale Funnel 只适合少量功能验证，不应当作正式全国公网方案。正式公网前至少需要：稳定域名、HTTPS、入口隔离、最小暴露端口、防火墙/反代策略、备份、监控、容量测试和隐私合规确认。

## 13. 禁止事项与高风险操作

- 不要删除或重建 `app.db`。
- 不要删除 Asset 原件、PreviewSet、二维码 token、revision key 或发布指针。
- 不要直接修改 QuickDrop 数据库。
- 不要修改路由器、防火墙、Docker daemon 或 Tailscale，除非用户明确授权。
- 不要把管理员后台、QuickDrop 或数据库端口直接暴露公网。
- 不要在文档、日志或对话中输出 `.env` 全文和任何 secret/hash/token。
- 不要清理本机旧 WIP 目录；其中的改动归用户所有。
- 不要因为当前数据是测试数据就擅自执行删除；先给出 dry-run 或删除清单并取得用户确认。

## 14. 下一位 Agent 的前 15 分钟

1. 完整阅读本文件、远程 `README.md`、`docs/handoff_stage_05.md` 和最终报告。
2. 连接 `tx`，确认远程 Git 工作区干净，并确认 `ce4a367` 仍在最近历史中；实际 HEAD 以 `git log -1` 为准。
3. 检查三个容器、健康检查、最近日志和磁盘空间。
4. 检查 `tailscale funnel status`，不要根据 `.env` 猜测公网是否开启。
5. 向用户确认下一步是继续临时公网测试、恢复 LAN，还是开始正式部署设计。
6. 若继续公网，请用户亲自执行 sudo Funnel 命令，再做蜂窝网络实体手机验证。
7. 若恢复 LAN，先取得确认，再使用已记录的 `.env` 备份并只重建 pdf-worker。
8. 新开发开始前运行 168 项基线测试，按小阶段审核、提交和推送。

项目当前不是“未完成原型地基”，而是一套完成 Stage 5 安全预览闭环、已有完整测试和恢复演练的可运行原型。接手重点是先校正当前网络模式，再从用户批准的新目标继续。
