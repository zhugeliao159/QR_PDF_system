# Stage 4C 审计设计

更新时间：2026-07-15

## 记录内容

每条审计事件包含事件类型、管理员账号、资料关联、可选版本或二维码入口关联、简短中文摘要和 UTC 时间。

Stage 4C 使用的关键事件：

- `create_resource`
- `create_qr_alias`
- `create_draft`
- `publish_revision`
- `republish_revision`
- `discard_draft`
- `activate_resource`
- `deactivate_resource`
- `create_pinned_alias`
- `legacy_immediate_publish`

管理员资料详情页按时间倒序显示与该资料相关的中文操作记录。

## 安全边界

审计摘要不记录密码、Session、CSRF、API token、文件内容、存储绝对路径或异常二进制内容。放弃草稿后，数据库外键会把已删除版本关联置空，审计事件本身继续保留。

## 原子性

创建草稿、发布、重新发布、启停资料的审计记录与业务状态在同一事务提交。事务失败时两者一起回滚。孤立文件清理失败会写服务器错误日志，不伪装成审计成功。
