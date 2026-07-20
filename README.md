# 练习册二维码管理系统

这是一个面向机构管理员的内部原型：上传答案或讲解资料，生成动态或固定版本二维码，并把二维码添加到练习册 PDF。Stage 6 新增后台批量 PDF 导入、名称自动去重、独立二级密码永久删除，以及只承载学生扫码路由的公网占位服务。

## 当前状态

- 管理后台：<http://192.168.100.20:18081/admin>
- 健康检查：<http://192.168.100.20:18081/health>
- QuickDrop：<http://127.0.0.1:18080>
- 学生公网占位服务：<http://127.0.0.1:18082>（仅本机监听，当前未启用 Funnel）
- 当前分支：`main`
- 数据库 schema：`6`
- 自动化测试：`175 passed, 0 failed, 0 skipped`

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
3. “管理已有解析资料”：搜索资料、新建答案草稿、预览并发布、重新发布历史版本、编辑信息或停用资料。

“批量上传答案”一次最多接收 100 份 PDF、总计 2 GiB。每个 PDF 独立创建资料并在后台生成预览后自动发布；名称取文件名去掉扩展名，重名时自动追加 `(1)`、`(2)`。进度页可关闭，后台 Worker 会继续处理。

资料列表支持按答案名称搜索、20/50/100 条分页和当前页批量选择。永久删除需要独立二级密码；有固定二维码、练习册任务或正在处理的资料会被跳过，其余资料逐条安全删除。

动态二维码只跟随“当前已发布答案”；保存草稿不会影响学生。固定二维码永久指向选定版本。详细步骤见 [管理员操作指南](docs/stage_03_admin_guide.md)。

PDF 和图片在学生页中以逐页 WebP 显示：第一页立即加载，后续页面按需加载。学生端不提供原始文件或下载按钮。外部网页默认不向学生开放，且不能宣称受到同等预览保护。

新生成的二维码使用 `/q/{token}`：扫码后直接进入中文分页预览。动态二维码跟随当前发布版本，固定二维码保持指定版本，旧 `/r` 二维码通过 307 临时跳转继续有效。

## 启动和更新

远端项目目录：`/home/user/projects/qr-exercise-prototype`。

```bash
cd ~/projects/qr-exercise-prototype
docker compose config --quiet
docker compose build pdf-worker
docker compose up -d pdf-worker preview-worker
docker compose ps
curl -fsS http://192.168.100.20:18081/health
```

独立学生服务仅监听回环地址，不包含 `/admin`、`/bindings` 或 `/pdf/jobs`：

```bash
docker compose up -d student-public
curl -fsS http://127.0.0.1:18082/health
```

只更新 PDF Worker，不重启 QuickDrop：

```bash
docker compose build pdf-worker
docker compose up -d --no-deps pdf-worker
```

首次运行或回填预览时，还需要启动无对外端口的 Preview Worker：

```bash
docker compose up -d --no-deps preview-worker
docker compose exec -T pdf-worker \
  python -m app.scripts.backfill_previews --dry-run --only-current --limit 10
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
| `DELETION_PASSWORD_HASH` | 空模板 | 永久删除独立二级密码的 scrypt 哈希；未设置时删除功能禁用 |
| `SESSION_SECRET` | 空模板 | Session 签名密钥，必须在部署前设置 |
| `SESSION_COOKIE_SECURE` | `false` | HTTPS 正式部署时改为 `true` |
| `SESSION_MAX_AGE_SECONDS` | `28800` | 管理员会话有效期 |
| `ENABLE_ADMIN_API_DOCS` | `false` | 是否启用受登录保护的 API 文档 |
| `MAX_UPLOAD_SIZE_MB` | `100` | 单文件大小限制 |
| `MAX_IMAGE_SIZE_MB` | `30` | 图片文件大小限制 |
| `MAX_IMAGE_PIXELS` | `40000000` | 图片最大像素数 |
| `MAX_PDF_PAGES` | `500` | PDF 页数限制 |
| `MAX_BINDING_VERSIONS` | `5` | 每份资料保留的普通历史版本数；固定版本另行保护 |
| `ALLOW_EXTERNAL_URLS` | `false` | 是否启用外部网页答案 |
| `ALLOW_PRIVATE_HTTP_EXTERNAL_URLS` | `false` | 是否允许受控局域网私有 HTTP 测试 |
| `EXTERNAL_URL_REQUIRE_HTTPS` | `true` | 是否要求外部网页使用 HTTPS |
| `EXTERNAL_URL_ALLOWED_HOSTS` | 空 | 逗号分隔的允许域名；正式环境建议配置 |
| `EXTERNAL_URL_BLOCKED_HOSTS` | 空 | 逗号分隔的禁止域名 |
| `PREVIEW_DPI` | `144` | PDF 预览渲染 DPI |
| `PREVIEW_WEBP_QUALITY` | `82` | 预览 WebP 质量 |
| `PREVIEW_MAX_PAGES` | `500` | 单个预览允许的最大 PDF 页数 |
| `PREVIEW_MAX_RENDER_WIDTH` | `2000` | 预览页最大宽度（像素） |
| `PREVIEW_RENDER_VERSION` | `v1` | 预览算法版本 |
| `PREVIEW_JOB_MAX_ATTEMPTS` | `2` | 预览任务最大尝试次数 |
| `PREVIEW_JOB_STALE_SECONDS` | `900` | processing 任务超时恢复时间 |
| `BATCH_UPLOAD_MAX_FILES` | `100` | 单批 PDF 数量上限 |
| `BATCH_UPLOAD_MAX_TOTAL_MB` | `2048` | 单批总大小上限 |
| `BATCH_IMPORT_STALE_SECONDS` | `900` | 批量 Worker 领取超时恢复时间 |
| `REQUIRE_PREVIEW_BEFORE_PUBLISH` | `true` | 发布文件版本前强制完整预览校验 |
| `PROTECTED_PREVIEW_EXTERNAL_URL_POLICY` | `disable` | 学生端外部网址策略：disable、warn 或 allow |
| `VIEWER_SESSION_SECRET` | 空模板 | 预览 Cookie 的 HMAC 密钥，必须至少 32 字节且不得提交真实值 |
| `VIEWER_SESSION_TTL_MINUTES` | `30` | 匿名预览绝对有效期 |
| `VIEWER_SESSION_IDLE_MINUTES` | `10` | 匿名预览空闲有效期 |
| `VIEWER_SESSION_MAX_PAGE_REQUESTS` | `1000` | 单会话页面请求上限 |
| `VIEWER_PAGE_RATE_LIMIT_PER_MINUTE` | `120` | 单会话页面分钟限速 |
| `VIEWER_MANIFEST_RATE_LIMIT_PER_MINUTE` | `30` | 单会话清单分钟限速 |
| `VIEWER_MAX_CONCURRENT_PAGE_REQUESTS` | `6` | 全进程同时生成水印页面上限 |
| `WATERMARK_FONT_PATH` | 空 | 可选中文字体路径；不可用时自动使用 ASCII 水印 |
| `WATERMARK_OPACITY` | `45` | 服务端像素水印透明度（1–255） |

初次部署可在构建好的容器中运行安全初始化脚本。脚本会拒绝覆盖已有配置，并把一次性初始密码写入明确指定、权限为 0600 的临时文件：

```bash
docker compose run --rm --no-deps -v "$PWD:/work" pdf-worker \
  python scripts/bootstrap_admin_env.py /work/.env /work/initial-password
```

当前服务器已完成初始化，不要重复执行。

## 设置永久删除二级密码

在服务器交互式终端执行；密码与哈希都不会输出：

```bash
cd ~/projects/qr-exercise-prototype
docker compose run --rm --no-deps -v "$PWD:/work" pdf-worker \
  python scripts/set_deletion_password.py /work/.env
docker compose up -d --force-recreate --no-deps pdf-worker
```

二级密码至少 16 个字符，必须与管理员登录密码分开保管。每次永久删除都要重新输入；10 分钟内连续错误 5 次会锁定 15 分钟。

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
- 私有预览衍生页：`data/pdf-worker/storage/previews/`

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

Stage 6 当前结果为 `176 passed, 0 failed, 0 skipped`。

## 安全边界

- 管理页面需要签名 Session，状态修改表单有 CSRF 防护。
- 管理 API 在生产配置中需要管理员会话或可选 Bearer 令牌。
- 学生动态和固定版本入口保持公开只读。
- Swagger/OpenAPI 默认关闭。
- PDF Worker 以非 root 用户运行，丢弃全部 Linux capabilities，启用 `no-new-privileges`，限制为 1 CPU、512 MiB 和 128 PIDs，并启用日志轮转。
- Preview Worker 不开放端口，同样以非 root 运行，限制为 1 CPU、768 MiB 和 64 PIDs。它把支持的私有 PDF/图片重新编码为内部 WebP 页面；本阶段不承诺阻止截图、录屏或保存已收到的预览图片。
- 匿名 `/q`、`/r` 与 `/content` 不返回原始 PDF/图片；管理员原件接口要求登录并记录审计。
- QuickDrop 独立运行，PDF Worker 不读取或修改其数据库。
- `student-public` 只暴露学生扫码路由、学生静态文件和健康检查，监听 `127.0.0.1:18082`。当前 Funnel 关闭；未来公网测试只允许 Funnel 代理该端口，不再代理完整 PDF Worker。

## 文档

- [Stage 6 批量管理设计与运维说明](docs/stage_06_batch_management.md)
- [Stage 6 最终验收报告](docs/stage_06_final_report.md)
- [Stage 6 交接](docs/handoff_stage_06.md)
- [云服务器公网部署记录](docs/cloud_deployment_2026-07-20.md)

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
- [Stage 4C 草稿与发布流程](docs/stage_04c_publish_workflow.md)
- [Stage 4C 并发设计](docs/stage_04c_concurrency_design.md)
- [Stage 4C 审计设计](docs/stage_04c_audit_design.md)
- [Stage 4C 报告](docs/stage_04c_report.md)
- [Stage 4C 交接](docs/handoff_stage_04c.md)
- [Stage 4D 内容类型](docs/stage_04d_content_types.md)
- [Stage 4D 外部地址安全](docs/stage_04d_external_url_security.md)
- [Stage 4D 报告](docs/stage_04d_report.md)
- [Stage 4D 交接](docs/handoff_stage_04d.md)
- [Stage 5A 预览模型](docs/stage_05a_preview_model.md)
- [Stage 5A 渲染设计](docs/stage_05a_renderer_design.md)
- [Stage 5A 回填指南](docs/stage_05a_backfill_guide.md)
- [Stage 5A 报告](docs/stage_05a_report.md)
- [Stage 5A 交接](docs/handoff_stage_05a.md)
- [Stage 5B 学生预览规范](docs/stage_05b_student_viewer_spec.md)
- [Stage 5B 原件访问策略](docs/stage_05b_original_access_policy.md)
- [Stage 5B 切换库存](docs/stage_05b_cutover_inventory.md)
- [Stage 5B 切换报告](docs/stage_05b_cutover_report.md)
- [Stage 5B 报告](docs/stage_05b_report.md)
- [Stage 5B 交接](docs/handoff_stage_05b.md)
- [Stage 5C Viewer Session 设计](docs/stage_05c_viewer_session_design.md)
- [Stage 5C 水印设计](docs/stage_05c_watermark_design.md)
- [Stage 5C 性能报告](docs/stage_05c_performance_report.md)
- [Stage 5D 路由审计](docs/stage_05d_route_audit.md)
- [Stage 5D 清理指南](docs/stage_05d_cleanup_guide.md)
- [Stage 5D 备份恢复指南](docs/stage_05d_backup_restore_guide.md)
- [Stage 5D 负载报告](docs/stage_05d_load_test_report.md)
- [Stage 05 安全边界](docs/stage_05_security_boundary.md)
- [Stage 05 最终报告](docs/stage_05_final_report.md)
- [Stage 05 交接](docs/handoff_stage_05.md)
- [第二阶段 API 说明](docs/stage_02_api.md)

## 当前未实现

多管理员和角色、全局审计检索、外链定期失效检查、图片缩略图、批量处理、扫码统计、学生账号、公网域名和 HTTPS、自动恢复、监控告警及高可用仍未实现。
