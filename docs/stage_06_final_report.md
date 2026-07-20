# Stage 6 最终验收报告

验收日期：2026-07-19（Asia/Shanghai）

## 已交付

- 恢复 LAN 运行：后台和当前二维码基础地址均为 `http://192.168.100.20:18081`。
- 新增 `student-public`，仅监听 `127.0.0.1:18082`，只提供 `/q`、兼容 `/r`、学生静态资源和健康检查。
- 新增 PDF 批量导入、后台持久队列、逐项进度、自动预览与自动发布；支持最多 100 份、总计 2 GiB、单份 100 MiB。
- 新增 Unicode 规范化和最小可用 `(n)` 名称去重规则。
- 资料列表支持名称搜索、20/50/100 分页、当前页全选和批量删除预检。
- 新增独立二级密码、失败锁定、逐项部分成功、引用保护、文件 trash 回滚和全局安全审计。
- SQLite schema 已迁移至 6，新增批次及批次明细表。

## 验收结果

- 自动化测试：`176 passed, 0 failed, 0 skipped`。
- 数据库：schema 6，`PRAGMA integrity_check=ok`。
- 匿名原件泄露审计：PASS，11 个公开/越权请求均未泄露原始 Asset。
- LAN 现有二维码链路：HTTP 200、HTML 正常返回。
- `student-public`：`/admin`、`/admin/login`、`/bindings`、`/pdf/jobs`、`/capabilities`、`/content/*` 均直接返回 404；学生 CSS/JS 返回 200。
- 容器：`pdf-worker`、`preview-worker`、`student-public`、`quickdrop` 正常运行，两个 HTTP 服务健康。
- `tailscale funnel status`：`No serve config`。

## 备份与迁移

- 实施前 Stage 5 完整备份：`/home/user/projects/qr-stage06-preimplementation-20260719.tar.gz`，权限 0600。
- 5→6 自动迁移备份：`data/pdf-worker/db/backups/app-before-stage06-v5-20260719T132953Z.db`。
- 批量导入目录已纳入 `scripts/backup_stage05.sh` 的备份范围。

## 待用户完成

服务器尚未设置 `DELETION_PASSWORD_HASH`，因此永久删除按钮保持禁用。用户需在服务器终端交互式执行：

```bash
cd ~/projects/qr-exercise-prototype
docker compose run --rm --no-deps -v "$PWD:/work" pdf-worker \
  python scripts/set_deletion_password.py /work/.env
docker compose up -d --force-recreate --no-deps pdf-worker
```

不要在聊天、日志或 Git 中发送密码或哈希。未来如启用公网，只允许 Funnel 代理 `127.0.0.1:18082`，并需同步切换公网二维码基础地址和 Secure Viewer Cookie。
