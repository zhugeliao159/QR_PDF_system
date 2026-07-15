# 练习册二维码管理系统

这是一个面向机构管理员的内部原型：上传答案或讲解资料，生成动态或固定版本二维码，并把二维码添加到练习册 PDF。Stage 4A 已完成后端解耦，Stage 4B 新增了统一中文学生答案页和不可变版本内容入口。

## 当前状态

- 管理后台：<http://192.168.100.20:18081/admin>
- 健康检查：<http://192.168.100.20:18081/health>
- QuickDrop：<http://127.0.0.1:18080>
- 当前分支：`main`
- 数据库 schema：`3`
- 自动化测试：`72 passed, 0 failed, 0 skipped`

仓库默认配置只监听服务器 `127.0.0.1`。经用户确认，当前部署已临时切换为 `192.168.100.20:18081` 局域网测试模式；同一机构 Wi-Fi 内的手机可以扫码测试，但地址依赖当前网络，不得用于正式印刷。

## Windows 访问

PDF Worker 当前可直接通过局域网访问，不需要 SSH 隧道。只有访问 QuickDrop 时才需要在 Windows PowerShell 中保持下面的命令运行：

```powershell
ssh -L 18080:127.0.0.1:18080 tx
```

在浏览器打开 <http://192.168.100.20:18081/admin>。管理员不需要使用 Swagger，也不需要复制 `qr_id`。

## 管理员操作

登录后有三个主要入口：

1. “新建解析二维码”：填写名称、年级和学科，上传答案或讲解文件。
2. “给练习册添加二维码”：选择已有资料，上传练习册 PDF，选择二维码方式、页码、大小和位置，预览后下载。
3. “管理已有解析资料”：搜索资料、替换文件、恢复历史版本、编辑信息或停用资料。

动态二维码会跟随当前版本；固定二维码永久指向选定版本。详细步骤见 [管理员操作指南](docs/stage_03_admin_guide.md)。

新生成的二维码使用 `/q/{token}`：扫码后直接进入中文答案页，PDF 会立即尝试内嵌显示。若手机浏览器不支持 PDF 预览，可使用页面上的“全屏打开”或“下载文件”。旧 `/r` 二维码仍然有效。

## 启动和更新

远端项目目录：`/home/user/projects/qr-exercise-prototype`。

```bash
cd ~/projects/qr-exercise-prototype
docker compose config --quiet
docker compose build pdf-worker
docker compose up -d
docker compose ps
curl -fsS http://192.168.100.20:18081/health
```

只更新 PDF Worker，不重启 QuickDrop：

```bash
docker compose build pdf-worker
docker compose up -d --no-deps pdf-worker
```

安全停止且保留数据：

```bash
docker compose down
```

不要使用 `docker compose down -v`，不要删除 `data/`，不要直接修改 QuickDrop 数据库。

## 配置

真实配置保存在不进入 Git 的 `.env`。`.env.example` 只提供字段模板。

| 变量 | 默认或示例 | 用途 |
| --- | --- | --- |
| `PDF_WORKER_BIND_ADDRESS` | `127.0.0.1` | Docker 在宿主机上的监听地址 |
| `PDF_WORKER_PORT` | `18081` | PDF Worker 端口 |
| `PUBLIC_QR_BASE_URL` | `http://127.0.0.1:18081` | 写进二维码的基础地址 |
| `SITE_NAME` | `练习册二维码管理系统` | 页面名称 |
| `ADMIN_USERNAME` | `admin` | 管理员账号 |
| `ADMIN_PASSWORD_HASH` | 空模板 | scrypt 密码哈希，必须在部署前设置 |
| `SESSION_SECRET` | 空模板 | Session 签名密钥，必须在部署前设置 |
| `SESSION_COOKIE_SECURE` | `false` | HTTPS 正式部署时改为 `true` |
| `SESSION_MAX_AGE_SECONDS` | `28800` | 管理员会话有效期 |
| `ENABLE_ADMIN_API_DOCS` | `false` | 是否启用受登录保护的 API 文档 |
| `MAX_UPLOAD_SIZE_MB` | `100` | 单文件大小限制 |
| `MAX_PDF_PAGES` | `500` | PDF 页数限制 |
| `MAX_BINDING_VERSIONS` | `5` | 每份资料保留的普通历史版本数；固定版本另行保护 |

初次部署可在构建好的容器中运行安全初始化脚本。脚本会拒绝覆盖已有配置，并把一次性初始密码写入明确指定、权限为 0600 的临时文件：

```bash
docker compose run --rm --no-deps -v "$PWD:/work" pdf-worker \
  python scripts/bootstrap_admin_env.py /work/.env /work/initial-password
```

当前服务器已完成初始化，不要重复执行。

## 修改管理员密码

在服务器终端运行：

```bash
cd ~/projects/qr-exercise-prototype
docker compose run --rm --no-deps pdf-worker python scripts/set_admin_password.py
```

按提示输入至少 16 个字符的新密码，把输出的整行哈希写入 `.env` 的 `ADMIN_PASSWORD_HASH`，然后执行：

```bash
docker compose up -d --force-recreate --no-deps pdf-worker
```

新密码和输出哈希不要发给学生，也不要提交到 Git。

## 数据和迁移

- SQLite：`data/pdf-worker/db/app.db`
- 数据库迁移备份：`data/pdf-worker/db/backups/`
- 绑定文件：`data/pdf-worker/storage/bindings/`
- 上传的练习册：`data/pdf-worker/storage/source-pdfs/`
- 生成的练习册：`data/pdf-worker/storage/generated-pdfs/`

数据库启动时执行幂等 migration。版本 1 升级到版本 2、版本 2 升级到版本 3 前都会使用 SQLite Backup API 生成备份。schema 3 新增解耦业务表，旧表保留只读，原有二维码、版本、文件和 PDF job 不会被删除。

一致性整库备份建议先停止服务：

```bash
cd ~/projects/qr-exercise-prototype
docker compose down
tar -czf ../qr-exercise-data-$(date +%F).tar.gz data/
docker compose up -d
```

## 测试

测试容器不挂载正式数据，也不发布主机端口：

```bash
docker compose --profile test build pdf-worker-tests
docker compose --profile test run --rm pdf-worker-tests
```

Stage 4B 最终结果为 `72 passed, 0 failed, 0 skipped`。

## 安全边界

- 管理页面需要签名 Session，状态修改表单有 CSRF 防护。
- 管理 API 在生产配置中需要管理员会话或可选 Bearer 令牌。
- 学生动态和固定版本入口保持公开只读。
- Swagger/OpenAPI 默认关闭。
- PDF Worker 以非 root 用户运行，丢弃全部 Linux capabilities，启用 `no-new-privileges`，限制为 1 CPU、512 MiB 和 128 PIDs，并启用日志轮转。
- QuickDrop 独立运行，PDF Worker 不读取或修改其数据库。

## 文档

- [产品说明](docs/stage_03_product_spec.md)
- [管理员操作指南](docs/stage_03_admin_guide.md)
- [网络模式指南](docs/stage_03_network_guide.md)
- [第三阶段报告](docs/stage_03_report.md)
- [第三阶段交接](docs/handoff_stage_03.md)
- [Stage 4A 迁移报告](docs/stage_04a_migration_report.md)
- [Stage 4A 数据映射](docs/stage_04a_data_mapping.md)
- [Stage 4A 交接](docs/handoff_stage_04a.md)
- [Stage 4B 学生页规范](docs/stage_04b_student_page_spec.md)
- [Stage 4B 缓存设计](docs/stage_04b_cache_design.md)
- [Stage 4B 报告](docs/stage_04b_report.md)
- [Stage 4B 交接](docs/handoff_stage_04b.md)
- [第二阶段 API 说明](docs/stage_02_api.md)

## 当前未实现

Stage 4C 的草稿发布、Stage 4D 的图片与受控外部 URL 尚未完成。多管理员和角色、审计查询界面、批量处理、扫码统计、学生账号、公网域名和 HTTPS、自动恢复、监控告警及高可用也仍未实现。
