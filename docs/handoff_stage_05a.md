# Stage 5A 交接

## 已完成

Stage 5A 已通过自动化与现场审核。schema 4 增加 PreviewSet、PreviewPage、PreviewJob；Preview Worker 与回填命令均已配置。正式库当前有 5 个 completed PreviewSet、70 个 WebP PreviewPage，Stage 4 映射和原件 SHA-256 校验为 PASS。

## 日常命令

```bash
cd /home/user/projects/qr-exercise-prototype
docker compose up -d --no-deps pdf-worker preview-worker
docker compose exec -T pdf-worker python -m app.scripts.backfill_previews --dry-run --only-current --limit 10
docker compose --profile test run --rm pdf-worker-tests
```

当前维护完成后应按用户要求保持服务停止：

```bash
docker compose stop pdf-worker preview-worker
```

不要删除 `data/`、原始 Asset、`previews/` 中 completed 集合、QuickDrop 数据库或 Stage 4 表；不要使用 `docker compose down -v`，不要 push。

## Stage 5B 前置条件

1. 只将具有 completed PreviewSet 的 PDF/PNG/JPEG/WebP 版本切换到学生预览；
2. 动态、固定和旧 `/r` 二维码语义必须保持；
3. 外部网页和非支持 MIME 类型不能假称受控预览；
4. 管理员仍可认证访问原件，学生接口的切换必须单独测试；
5. 继续使用 schema 4 的 source SHA-256、renderer version 和配置哈希，不能修改已有 token、revision key 或原件。
