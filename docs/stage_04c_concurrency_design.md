# Stage 4C 并发发布设计

更新时间：2026-07-15

## 目标

两个管理员从同一资料状态打开页面后，不允许后提交者静默覆盖先提交者的发布结果。

## 实现

`answer_resources.row_version` 是内部状态编号。管理员页面只提交不透明的 `page_state`，不显示数据库术语或数值含义。

发布事务使用条件更新：

```sql
UPDATE answer_resources
SET current_published_revision_id = ?,
    row_version = row_version + 1,
    updated_at = ?
WHERE id = ? AND row_version = ?;
```

更新行数不是 1 时，事务回滚并返回 HTTP 409。后台显示：

> 这份资料刚刚被其他管理员更新，请刷新页面，确认当前发布版本后再重试。

冲突请求不会改变当前答案、草稿状态或审计记录。

## SQLite 行为

项目事务使用 `BEGIN IMMEDIATE`。并发写入会依次取得写锁；第二个事务取得锁后读取到新的状态编号，并按业务冲突返回 409。数据库忙等待为 5 秒。

## 验证

- 顺序提交两个过期页面：一个成功，一个 409。
- 两个线程同时发布不同草稿：一个成功，一个 `RESOURCE_CONFLICT`。
- 成功后状态编号只增加 1，当前答案等于唯一成功版本。
