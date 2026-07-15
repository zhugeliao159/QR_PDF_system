# Stage 4A 数据映射

## 主映射

| 旧数据 | 新数据 | 关键规则 |
| --- | --- | --- |
| `bindings` | `answer_resources` | 保留业务字段、状态、时间；`legacy_binding_id` 保留来源 ID |
| `bindings.qr_id` | `qr_aliases.public_token` | 字节级保持不变；迁移为 `latest` alias |
| `bindings.current_version_id` | `answer_resources.current_published_revision_id` | 保留原版本 ID 与 current 语义 |
| `file_versions` | `answer_revisions` | 保留 ID、版本号、时间和 note；统一为 `published/file` |
| `file_versions` | `assets` | 保留 ID、存储键、文件名、MIME、大小和 SHA-256 |
| `version_references` | `revision_references` | 保留版本保护语义和 `source_job_id` |
| `pdf_jobs` | `pdf_jobs_v2` | 保留 job ID、输入输出路径、状态、哈希和二维码模式 |

## 身份策略

- 迁移记录沿用旧数值 ID，方便核对和兼容旧固定版本 URL。
- 新建记录使用新表自增 ID；公开身份使用随机的 `resource_key`、`revision_key`、`asset_key` 和 `public_token`。
- 名称、文件名和数据库自增 ID 都不参与新二维码解析。
- `QrResolverService` 返回 alias/resource/revision/asset 结构，不返回主机绝对路径。
- 实际路径只由 `AssetService` 与 `StorageBackend` 解析。

## 引用映射

| 旧 `reference_type` | 新 `reference_type` |
| --- | --- |
| `pdf_job`、`pdf_job_fixed` | `pdf_job_fixed` |
| `manual_pin` | `manual_pin` |
| 其他旧固定引用 | `legacy_fixed_link` |

current revision、固定引用、固定 PDF job 引用都禁止被自动清理。审计事件保留；若普通历史 revision 因保留数量策略被清理，审计记录的 `revision_id` 可置空，事件本身不删除。

## 兼容层

`BindingService` 继续向旧路由输出原字段，但内部只调用新 service 和新表。`PdfService` 使用 `pdf_jobs_v2`、`answer_resources`、`qr_aliases` 与 `revision_references`。旧表保留用于核对和回退，不接收新写入。

## Stage 4A 限制

- 实际启用的 revision 仅允许本地文件。
- `external_url` 必须为空。
- 所有迁移版本均为 `published`；尚无 draft/publish 工作流。
- 尚未启用图片答案与外部 URL。
- 新学生入口 `/q/{token}` 留到 Stage 4B。
