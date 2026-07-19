# Stage 05D 备份与恢复指南

创建备份：

```bash
cd /home/user/projects/qr-exercise-prototype
scripts/backup_stage05.sh /home/user/projects/qr-stage05-$(date +%F).tar.gz
```

脚本通过 SQLite Backup API 取得一致数据库快照，并包含私有 Asset、基础 Preview、批量导入 Asset/暂存文件、source/generated PDF、`.env`、`compose.yaml` 和必要配置。归档含文件清单、逐文件 SHA-256 与数据库计数，权限设为 0600。真实 `.env` 含密钥，必须加密后异机保存并限制访问；不能只把备份留在同一磁盘。

只验证和演练到临时目录：

```bash
scripts/restore_stage05.sh /path/to/backup.tar.gz --dry-run
scripts/restore_stage05.sh /path/to/backup.tar.gz --target /tmp/stage05-restore-test
```

验证包括归档清单、所有 SHA-256、SQLite integrity、Resource/Revision/Asset/PreviewSet/PreviewPage 数量、每个 Asset 和 PreviewPage 实体哈希，以及 latest/pinned alias 语义。应用级检查时临时数据库必须可写，因为启动连接会启用 WAL。

正式覆盖恢复具有双重保护：先停止 `pdf-worker` 与 `preview-worker`，再显式设置 `STAGE05_RESTORE_CONFIRM=RESTORE_STAGE05` 并使用 `--apply`。恢复后先在本机健康检查、检查动态和固定二维码，再启动对外服务。禁止在服务仍写入时覆盖数据。

2026-07-16 实际演练归档：`/home/user/projects/qr-stage05-rehearsal-20260716.tar.gz`，29 MiB，SHA-256 `cfbe008b4f83088d940d81df331777ffdfd6edf96fe3d296f0b253e1627ed216`。恢复到 `/tmp/stage05-restore-rehearsal-20260716`，验证 Resource 6、Revision 13、Asset 13、completed PreviewSet 8、PreviewPage 186、动态 alias 6、固定 alias 1；所有文件 SHA-256、动态/固定语义均 PASS，未覆盖生产数据。
