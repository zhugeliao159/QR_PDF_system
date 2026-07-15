# Stage 4D 外部地址安全

更新时间：2026-07-15

## 默认配置

外部网页默认关闭：

```dotenv
ALLOW_EXTERNAL_URLS=false
ALLOW_PRIVATE_HTTP_EXTERNAL_URLS=false
EXTERNAL_URL_REQUIRE_HTTPS=true
EXTERNAL_URL_ALLOWED_HOSTS=
EXTERNAL_URL_BLOCKED_HOSTS=
```

只有显式设置 `ALLOW_EXTERNAL_URLS=true` 后，管理员页面才显示“使用外部网页”。正式环境建议同时设置明确域名白名单，例如：

```dotenv
EXTERNAL_URL_ALLOWED_HOSTS=answers.example.edu,*.trusted.example.edu
```

精确条目只匹配该主机；`*.` 条目只匹配子域名。

## 校验

创建草稿、发布、重新发布、学生点击和旧 `/r` 跳转都会校验外部地址：

- 必须是绝对 HTTP(S) 地址，默认必须 HTTPS。
- 禁止用户名密码、非法端口、控制字符和响应头注入字符。
- 禁止 `file:`、`javascript:`、`data:`、`ftp:` 和自定义协议。
- 禁止 localhost、`.local`、回环、链路本地、组播、未指定、保留地址。
- 默认禁止私有 IPv4/IPv6 和 Tailscale `100.64.0.0/10`。
- 域名解析到多个 IP 时，任一地址受限就拒绝。
- 配置白名单后只允许白名单主机，黑名单始终优先拒绝。

DNS 查询只用于安全检查。服务端不发出 HTTP 请求，不下载、截图、解析或缓存外部网页。

## 私有 HTTP 测试

只有同时启用外部网页和 `ALLOW_PRIVATE_HTTP_EXTERNAL_URLS=true`，才允许 `http://` 私有地址。后台会显示局域网测试警告。该选项不允许 localhost、链路本地、Tailscale、危险协议、带凭据 URL 或非法端口，正式环境不应开启。

## 跳转

学生必须先看到中文确认页。点击 `/q/{token}/content` 后返回 307，不使用 301。跳转目标只来自已发布版本，不读取请求中的 `target`、`url` 等参数。响应包含 `no-store`、`nosniff` 和 `Referrer-Policy: no-referrer`。

## DNS Rebinding 残余风险

校验时 DNS 结果安全，不代表浏览器随后解析时仍指向同一 IP。攻击者可能通过短 TTL 或 DNS rebinding 改变解析结果。当前措施包括每次点击前重新校验、默认关闭、默认 HTTPS 和可选域名白名单，但无法完全消除浏览器侧再次解析的时间差。

高安全环境应只允许机构控制的 HTTPS 域名，并在反向代理、DNS 和网络出口层增加限制。不要把本功能当作服务端代理或外部内容长期存档。

## 审计与日志

审计可以记录目标域名，不记录带 query 的完整 URL。普通日志同样只记录域名，避免泄露访问 token。完整 URL 仅保存在版本业务数据中，并在管理员草稿页的折叠技术信息中显示。
