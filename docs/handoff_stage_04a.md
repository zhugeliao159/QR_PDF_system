# Stage 4A 交接

## 当前状态

Stage 4A 已完成并正式迁移到 schema 3。业务代码已切换到解耦 service 和新表，旧 API、旧二维码、固定版本及 PDF job 保持兼容。正式数据校验与 HTTP 回放均为 PASS。

## 环境

- 项目：`/home/user/projects/qr-exercise-prototype`
- 分支：`main`
- PDF Worker：<http://192.168.100.20:18081>
- QuickDrop：<http://127.0.0.1:18080>
- 当前为用户确认的局域网测试模式；不要修改网络绑定。
- 不要修改 QuickDrop 数据库，不要删除 `data/` 或旧表。

## 关键实现

- `app/database.py`：schema 3、v2->v3 安全备份与幂等 migration。
- `app/services/decoupled.py`：resource/revision/asset/resolver service。
- `app/services/binding_service.py`：旧 API 兼容 facade，仅使用新业务表。
- `app/services/pdf_service.py`：切换到 `pdf_jobs_v2` 和 revision 引用。
- `scripts/validate_stage04a_migration.py`：数据与物理文件双重校验。
- `scripts/check_stage04a_compatibility.py`：旧 HTTP 入口全量哈希回放。
- `scripts/backup_sqlite.py`：一致性 SQLite 备份。

## 已验证

- 自动化测试：65 passed。
- 正式迁移：PASS。
- 2 个动态入口、4 个固定版本、3 个 PDF job：全部哈希一致。
- 管理页和 capabilities：认证后 200。
- QuickDrop、资源限制、端口绑定：保持不变。

## Stage 4B 前置条件

1. 从本提交继续，不改写或删除 schema 3 迁移。
2. 新学生入口使用 `/q/{public_token}`，每次解析 current published revision。
3. 不改变旧 `/r` 和固定版本 URL。
4. immutable content URL 使用 `revision_key`，不可暴露存储路径。
5. 本阶段仍不实现 draft 或 external URL。
6. 完成后单独测试、部署、写文档并提交，不与 Stage 4C 混合。

## 运维复核

```bash
cd ~/projects/qr-exercise-prototype
docker compose ps
curl -fsS http://192.168.100.20:18081/health
docker compose exec -T pdf-worker \
  python scripts/validate_stage04a_migration.py /data/db/app.db /data/storage
```

迁移备份与回退步骤见 [Stage 4A 迁移报告](stage_04a_migration_report.md) 和 [迁移计划](stage_04a_migration_plan.md)。
