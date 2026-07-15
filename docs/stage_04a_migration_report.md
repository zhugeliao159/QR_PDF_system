# Stage 4A 迁移报告

## 结论

- 状态：**PASS**
- 正式迁移开始：2026-07-15 05:38:51 UTC
- 正式迁移完成：2026-07-15 05:39:05 UTC
- 中断范围：仅 PDF Worker；QuickDrop 未停止

## 备份

- 方式：SQLite Backup API
- 人工停机备份：`data/pdf-worker/db/backups/app-before-stage04a-manual-20260715T053851Z.db`
- migration 自动备份：`data/pdf-worker/db/backups/app-before-stage04a-v2-20260715T053859Z.db`
- 两份大小：69,632 bytes
- 可打开性：`PRAGMA integrity_check = ok`
- 备份 schema：2

## 副本预演

- 副本目录：`/tmp/stage04a-preflight.aaqsZP/`
- migration：v2 -> v3 成功
- 副本备份：`app-before-stage04a-v2-20260715T053818Z.db`
- 二次执行：schema 保持 3，备份数量保持 1，幂等通过
- 统一校验器：PASS

## 数据结果

| 项目 | 旧表 | 新表 | 结果 |
| --- | ---: | ---: | --- |
| 资料 | `bindings=2` | `answer_resources=2` | 一致 |
| 动态二维码 | `qr_id=2` | latest `qr_aliases=2` | 一致 |
| 版本 | `file_versions=4` | `answer_revisions=4` | 一致 |
| 文件资产 | 实际绑定文件 4 | `assets=4` | 一致 |
| 固定引用 | `version_references=0` | `revision_references=0` | 一致 |
| PDF job | `pdf_jobs=3` | `pdf_jobs_v2=3` | 一致 |

校验结果：文件缺失 0、SHA-256 不一致 0、size 不一致 0、resource/revision/asset 映射失败 0、current 映射失败 0、public token 映射失败 0、PDF job 映射失败 0、外键错误 0。

## 兼容性

HTTP 回放共 9 项，9 项通过：

- 原动态入口 2/2，返回哈希与原 current version 一致。
- 原固定版本入口 4/4，返回哈希与原版本一致。
- 原历史 PDF job 3/3，认证后下载大小与 SHA-256 一致。
- `/capabilities`：认证后 HTTP 200。
- `/admin`：签名会话下 HTTP 200。
- QuickDrop：healthy，数据库未修改。

正式库未执行创建、替换、回滚等测试写操作，避免污染业务数据；这些流程在隔离临时数据库自动化测试中通过。

## 自动化测试

- 基线：57 passed，0 failed，0 skipped，6.58 秒。
- Stage 4A：65 passed，0 failed，0 skipped，13.01 秒。
- 警告：5 条 PyMuPDF/SwigPy 弃用警告，与本次迁移无关。

## 资源与网络

- PDF Worker：healthy，`192.168.100.20:18081`。
- QuickDrop：healthy，`127.0.0.1:18080`。
- PDF Worker：1 CPU、512 MiB、128 PIDs、`appuser`、capabilities 全部丢弃。
- 端口绑定未扩大，局域网测试配置未改变。

## 回退

按 [迁移计划](stage_04a_migration_plan.md) 中的回退流程，保留失败库后，用人工停机 v2 备份恢复，并从 `stage-04-baseline` 构建旧镜像。严禁删除 `data/` 或覆盖唯一备份。

## 遗留风险

- 旧表与新表在过渡期同时存在，会增加数据库体积；旧表只读，不能手工修改。
- SQLite 不能单靠 CHECK 表达所有跨表约束，跨 resource 校验由 service、事务和测试共同保证。
- 当前局域网 IP 适合测试，不适合正式印刷；公网域名与 HTTPS 仍未完成。
- Stage 4B/C/D 尚未包含在本报告中。
