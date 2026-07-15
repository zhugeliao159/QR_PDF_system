# Stage 4B 缓存设计

## 动态页面

`/q/{token}` 使用：

```http
Cache-Control: no-store, must-revalidate
```

页面每次访问都重新解析 alias/resource/revision，防止替换答案后继续使用旧页面。

## 动态内容解析

`/q/{token}/content` 返回 307 到当前 revision：

```http
Cache-Control: no-store, must-revalidate
Location: /content/{revision_key}
```

latest alias 会随 current 更新；pinned alias 始终得到固定 revision。动态解析不用 301。

## 不可变内容

`/content/{revision_key}` 使用：

```http
Cache-Control: public, max-age=31536000, immutable
ETag: "{asset_sha256}"
```

revision key 创建后不修改目标内容。`If-None-Match` 与 ETag 匹配时返回 304 和空响应体。旧 revision URL 在 current 更新后仍返回旧文件。

`?download=true` 只改变 Content-Disposition，不改变 revision 或 ETag。PDF 和图片默认 inline；其他文件默认 attachment。中文文件名同时使用 ASCII fallback 与 RFC 5987 `filename*`。

## 安全边界

- `/content` 不接受存储键或文件路径。
- resolver 仅返回结构化 resource/revision/asset。
- 文件路径只由 `AssetService` 与 `StorageBackend` 解析。
- 当前阶段不允许 external URL，也不发生用户可控跳转。
