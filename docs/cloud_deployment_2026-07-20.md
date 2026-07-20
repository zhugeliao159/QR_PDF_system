# 云服务器公网部署记录

部署日期：2026-07-20（Asia/Shanghai）

## 当前拓扑

- 云服务器：Ubuntu 22.04.5 LTS，公网 IP `43.138.207.102`。
- 项目目录：`/home/ubuntu/qr-exercise-production`。
- 公网学生入口：`http://43.138.207.102`，由 Nginx 监听 80 后代理至 `127.0.0.1:18082`。
- 管理入口：`127.0.0.1:18081`，不直接暴露公网，只允许通过 SSH 隧道访问。
- 运行服务：`pdf-worker`、`preview-worker`、`student-public`；未部署 QuickDrop。
- 防火墙：UFW 默认拒绝入站，仅允许 OpenSSH 和 Nginx HTTP。
- SQLite：schema 6，首次部署数据库为空。

公网 Nginx 配置位于 `deploy/nginx/qrpdf-http.conf`。除应用自身的 public-only 路由隔离外，Nginx 还会直接阻断 `/admin`、`/bindings`、`/pdf/jobs`、`/capabilities` 和 `/content/*`。

## 管理员访问

在 Windows PowerShell 建立 SSH 隧道并保持窗口运行：

```powershell
ssh -i "C:\Users\ASUS\.ssh\id_ed25519_qrpdf_cloud" `
  -L 18081:127.0.0.1:18081 ubuntu@43.138.207.102
```

浏览器访问 `http://127.0.0.1:18081/admin`。初始管理员密码只保存在云机的 `/home/ubuntu/.qrpdf-initial-admin-password`，权限为 0600；用户应在自己的终端读取、妥善保存后删除该文件，不得把密码发到聊天或写入 Git。

## 二级删除密码

永久删除默认禁用。用户需要通过带 TTY 的 SSH 会话在云机上交互设置：

```bash
cd /home/ubuntu/qr-exercise-production
docker compose run --rm --no-deps -v "$PWD:/work" pdf-worker \
  python scripts/set_deletion_password.py /work/.env
docker compose up -d --force-recreate --no-deps pdf-worker
```

## 构建与更新

腾讯云 CVM 访问官方 PyPI 很慢。Dockerfile 支持可选 `PIP_INDEX_URL` 构建参数，默认仍使用官方 PyPI；本机部署使用腾讯云镜像：

```bash
docker buildx build --builder qrpdf-builder --load \
  --build-arg PIP_INDEX_URL=https://mirrors.cloud.tencent.com/pypi/simple \
  --target runtime -t qr-exercise-prototype-pdf-worker:local pdf-worker
docker compose up -d --no-build pdf-worker preview-worker student-public
```

更新前必须备份 `.env` 和 `data/`，核对目标提交，不要执行 `docker compose down -v`。

## 当前验收

- 全量自动化测试：`176 passed`。
- `PRAGMA integrity_check=ok`，schema 6。
- 公网 `/health` 返回 200。
- 公网后台、管理 API 和原件入口均返回 404；学生 CSS/JS 返回 200。
- 管理后台在回环地址返回 303 登录跳转，登录页返回 200。
- 三个核心容器健康，最近日志无 traceback/fatal。
- 正式库当前没有资料，因此原件泄露审计缺少 active 预览样本；上传首份测试资料后必须重新运行该审计。

## HTTPS 待办

当前仅完成公网 IP HTTP 验证，Viewer Cookie 因此暂时不能启用 `Secure`。正式使用前应提供一个域名，将 A 记录解析到 `43.138.207.102`，再配置 HTTPS、开放 443、把二维码基础地址切换为该 HTTPS 域名，并设置 `VIEWER_COOKIE_SECURE=true`。
