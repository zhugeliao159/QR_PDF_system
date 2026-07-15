# Stage 5A 预览衍生数据模型

Stage 5A 将原件与学生端将来使用的预览衍生数据分开保存。`Asset`、`AnswerResource`、`AnswerRevision`、`QrAlias`、草稿发布和二维码解析模型保持 Stage 4 语义不变；本阶段只新增 schema 4 的预览表。

## 表结构

### `preview_sets`

一行代表一个 `AnswerRevision` 在指定渲染器版本和渲染配置下的完整预览集合。它保存 `preview_key`、源 `Asset`、源 SHA-256、渲染版本、配置哈希、状态、页数、总大小、完成时间及安全的错误代码/摘要。

状态为 `pending`、`processing`、`completed`、`failed` 或 `superseded`。部分唯一索引保证同一 revision、renderer version 和配置最多只有一个 `completed` 集合；`completed` 必须有大于零的页数和完成时间。

### `preview_pages`

每个页面是一条独立的 WebP 元数据，记录连续的从 1 开始的页码、内部 storage key、宽高、大小和 SHA-256。`preview_set_id + page_number` 唯一。storage key 仅供服务端使用，不在管理员或学生页面展示。

### `preview_jobs`

任务记录保存不可预测的 `job_key`、revision、关联 PreviewSet、渲染器版本/配置、进度、领取时间、尝试次数和有限的错误摘要。活跃的 `pending`/`processing` 任务在同一 revision+配置上部分唯一，避免多个 worker 并发生成同一套预览。

## 存储与完整性

预览目录是 `data/pdf-worker/storage/previews/{preview_key}/`，只保存 `page-0001.webp` 等衍生页面和不含宿主机路径的 `manifest.json`。原始 Asset 仍留在现有绑定目录，绝不移动、重写或公开到 previews 目录。

Worker 先在 `previews/.tmp-{job_key}/` 完整渲染与逐页验证，再在同一文件系统中原子改名到最终目录；数据库页面记录、完成状态和目录移动在一个短事务流程内完成。任何失败都会删除临时目录，失败集合不会成为 `completed`，也不会被后续学生端使用。

启动时的 schema 3→4 迁移先使用 SQLite Backup API 在 `data/pdf-worker/db/backups/` 创建 `app-before-stage05a-v3-*.db`。迁移幂等，不修改既有二维码 token、revision key、Asset SHA-256 或 Stage 4 表。
