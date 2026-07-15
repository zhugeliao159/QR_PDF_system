# Stage 4B 交接

## 当前状态

Stage 4B 已部署。新二维码进入统一中文学生答案页，动态与固定 alias 都通过 resolver 解析；不可变 revision 内容支持 ETag 与 304。旧 `/r` 和旧固定 URL 保持有效。

## 关键实现

- `app/routers/student.py`：学生页、动态 content、immutable content。
- `app/templates/student/`：中文答案页和独立错误页。
- `app/static/css/student.css`、`app/static/js/student.js`：本地移动端样式与自动加载。
- `QrResolverService.resolve_content`：按 revision key 解析 published 内容。
- `QrResolverService.get_or_create_pinned_alias`：固定二维码 alias。
- `QrService`：新二维码统一使用 `/q`。
- `scripts/check_stage04b_live.py`：真实数据回归。

## 验证

- 自动化：72 passed。
- live-check：PASS。
- 4A 数据校验和 9 个旧入口：PASS。
- 真实手机扫码：未验证，需用户在同一网络补测。

## Stage 4C 前置条件

1. 保留 `/q`、`/q/content` 和 immutable `/content` 的缓存语义。
2. draft 不得影响 `current_published_revision_id`。
3. 预览草稿必须仅管理员可见，不得通过学生 resolver 暴露。
4. 发布必须显式、原子并使用 `row_version` 乐观锁。
5. 旧 PUT API 保持“创建草稿并立即发布”的兼容行为。
6. 不在 Stage 4C 实现 external URL。

## 运维复核

```bash
docker compose exec -T pdf-worker \
  python scripts/check_stage04b_live.py http://127.0.0.1:8000 /data/db/app.db
docker compose --profile test run --rm pdf-worker-tests
```
