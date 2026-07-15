# Stage 5A 存量预览回填指南

回填只为 PDF、PNG、JPEG、WebP 文件版本生成衍生预览。外部网页和历史兼容的其他 MIME 类型不会被修改、删除或强行转换；它们会在命令候选列表中跳过，仍保持 Stage 4 的原有访问语义。

先让 Preview Worker 运行，并始终从 dry-run 开始：

```bash
cd /home/user/projects/qr-exercise-prototype
docker compose up -d --no-deps preview-worker
docker compose exec -T pdf-worker \
  python -m app.scripts.backfill_previews --dry-run --only-current --limit 10
```

确认候选版本后提交小批量任务：

```bash
docker compose exec -T pdf-worker \
  python -m app.scripts.backfill_previews --only-current --limit 10
```

重复执行不会重新生成同一 renderer version 与配置下已经 completed 的集合。可用参数：`--revision-key KEY`、`--only-current`、`--only-published`、`--include-history`、`--failed-only`、`--resume`、`--dry-run`。`--resume` 期间应确保没有其他 Preview Worker 同时处理同一批次；生产常规回填推荐只提交任务，并让单独的 worker 消费。

回填不会改变 revision 内容、current published 指针、二维码 token、固定二维码、Asset 字节或 SHA-256。验证可运行：

```bash
docker compose exec -T pdf-worker \
  python scripts/validate_stage04a_migration.py /data/db/app.db /data/storage
```
