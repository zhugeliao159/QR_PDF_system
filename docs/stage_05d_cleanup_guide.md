# Stage 05D 安全清理指南

默认只生成计划：

```bash
docker compose exec -T pdf-worker python -m app.scripts.cleanup_storage --dry-run
```

确认每类数量、预计字节和跳过原因后才执行：

```bash
docker compose exec -T pdf-worker python -m app.scripts.cleanup_storage --apply
```

清理对象包括 stale processing job 与临时目录、superseded PreviewSet、无引用 Asset、过期水印缓存、过期 Viewer Session，以及超过保留期的 ViewerAccessEvent 和审计事件。每个实际删除动作都会重新查询引用，重复执行幂等。

绝不清理 current published revision、pinned/fixed alias、PDF job 固定引用、active draft、这些 revision 使用的 completed PreviewSet，以及仍被 revision 引用的 Asset。配置保留期为 Session 7 天、访问事件 30 天、管理审计 180 天；正式机构应在上线前确认隐私和合规要求。

2026-07-16 远程演练均先 dry-run 再 apply：分批把 1、69、65、71 个到达绝对或 idle 阈值的测试 Session 标记为过期。没有删除 Asset、PreviewSet 或 PreviewPage，预计/实际释放文件空间 0 字节。最终 dry-run 为 0 项；跳过并保护 current Asset 6、active draft Asset 3、completed PreviewSet 8、pinned/fixed revision 1。
