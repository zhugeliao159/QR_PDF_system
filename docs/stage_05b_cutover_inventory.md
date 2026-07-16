# Stage 5B 学生端切换库存

切换前使用 `python -m app.scripts.audit_preview_cutover` 检查所有启用的 latest 与 pinned alias。审计会核对源 Asset SHA-256、completed PreviewSet、连续页码、页面数量、文件大小、WebP 可打开性、尺寸和页面 SHA-256。

## 最终结果

- latest 文件版本：5/5 完整可预览。
- pinned 文件版本：1/1 完整可预览。
- 外部 URL：0。
- 缺失 PreviewSet：0。
- 缺页或损坏：0。

首次审计发现 pinned 历史版本 1 条缺预览，已通过 Stage 5A 幂等回填补齐；另有 1 条启用的 `text/plain` 测试资料。用户确认现有数据均为无用测试数据后，仅停用该不支持的测试资料及其 alias，没有删除数据库记录、revision 或原件。最终审计为 PASS。

复核命令：

```bash
docker compose run --rm --no-deps pdf-worker \
  python -m app.scripts.audit_preview_cutover
```
