# Stage 4D 交接

更新时间：2026-07-15

## 当前能力

- PDF：扫码后立即尝试内嵌显示，行为与 Stage 4B/4C 一致。
- 图片：PNG、JPEG、WebP 草稿可预览，发布后扫码立即显示。
- 外部网页：默认关闭；开启后先显示中文来源确认页，用户点击后临时跳转。
- 三种内容共用草稿、发布、历史重新发布、并发保护、固定二维码和审计流程。

## 管理员操作

1. 进入资料详情，点击“新建答案版本”。
2. 选择“上传 PDF”“上传图片”或已启用时的“使用外部网页”。
3. 保存草稿并预览。
4. 确认内容后发布；外部网页还必须勾选学生适用确认。
5. 历史版本可重新发布，锁定二维码不受影响。

## 外部网页开关

正式配置默认关闭。需要测试时，在不提交 Git 的 `.env` 中显式配置，设置 HTTPS 白名单后重建容器。关闭时设回：

```dotenv
ALLOW_EXTERNAL_URLS=false
```

不要为了测试修改防火墙、Tailscale 或当前 LAN 监听地址。私有 HTTP 开关只允许受控测试，不适合正式使用。

## 运维验证

```bash
cd /home/user/projects/qr-exercise-prototype
docker compose ps
curl -fsS http://192.168.100.20:18081/health
docker compose --profile test run --rm pdf-worker-tests
```

预期为 115 个测试全部通过。更新运行服务仍使用：

```bash
docker compose build pdf-worker
docker compose up -d --no-deps pdf-worker
```

## 安全边界

- 不得删除外链默认关闭设置。
- 不得把外部网页嵌入 iframe 或由服务端抓取。
- 不得绕过发布时和点击时的 URL 重新校验。
- 不得允许请求参数直接成为跳转目标。
- 不得把敏感 query 写入审计摘要或普通日志。
- 正式环境优先使用机构控制的 HTTPS 白名单。
