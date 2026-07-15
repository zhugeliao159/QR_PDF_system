# Stage 4A 迁移计划

状态：已执行  
执行日期：2026-07-15

## 目标与边界

本次把业务读写从 `bindings -> file_versions` 切换为：

```text
qr_aliases -> answer_resources -> answer_revisions -> assets -> StorageBackend
```

旧表全部保留，只作为迁移凭据，不再承接新业务写入。旧 `/r`、固定版本地址、管理页面及 PDF job 的请求和响应语义保持不变。本阶段不引入草稿、显式发布、图片内容或外部 URL。

## 执行顺序

1. 记录旧表、文件、二维码入口与哈希清单。
2. 运行迁移前完整测试；失败则停止。
3. 使用 SQLite Backup API 创建正式库一致性副本。
4. 仅在 `/tmp` 副本执行 v2 到 v3 migration。
5. 用统一校验器比较旧表、新表、实际文件、current、token、引用和 PDF job。
6. 对副本再次执行 migration，确认幂等且不增加备份。
7. 构建新镜像，但不替换运行中的旧容器。
8. 只停止 PDF Worker，使用 Backup API 创建正式备份。
9. 启动新容器，由启动 migration 完成正式迁移。
10. 再次运行数据校验器和全部旧入口 HTTP 回放。
11. 检查健康、日志、端口、资源限制和 QuickDrop 状态。

## 命令

```bash
docker compose --profile test build pdf-worker-tests
docker compose --profile test run --rm pdf-worker-tests

python3 pdf-worker/scripts/backup_sqlite.py SOURCE.db COPY.db
docker compose --profile test run --rm --no-deps \
  -v /tmp/stage04a-preflight:/preflight \
  -v "$PWD/data/pdf-worker/storage:/data/storage:ro" \
  pdf-worker-tests python scripts/migrate_database.py /preflight/app-v2.db

docker compose exec -T pdf-worker \
  python scripts/validate_stage04a_migration.py /data/db/app.db /data/storage
docker compose exec -T pdf-worker \
  python scripts/check_stage04a_compatibility.py \
  http://127.0.0.1:8000 /data/db/app.db --signed-admin-session
```

## 通过标准

- 旧表与对应新表数量完全一致。
- 文件缺失、大小、SHA-256、current、public token、引用、PDF job 和外键错误均为 0。
- 所有原动态、固定版本和 PDF job 下载内容哈希一致。
- 自动化测试全部通过，服务和 QuickDrop healthy。
- 端口绑定与 1 CPU、512 MiB、128 PIDs 限制不变。

## 失败与回退

任何关键校验不为 0 时停止进入后续阶段。正式回退流程：

1. `docker compose stop pdf-worker`。
2. 将失败的 v3 `app.db` 改名保留，禁止直接覆盖或删除。
3. 使用 `backup_sqlite.py` 从已验证的 v2 备份恢复为新的 `app.db`。
4. 从 `stage-04-baseline` 工作树构建旧 PDF Worker 镜像。
5. `docker compose up -d --no-deps pdf-worker`。
6. 复验 `/health`、旧动态和固定入口、历史 PDF job。

不得删除 `data/`、旧表、QuickDrop 数据库或现有业务文件。
