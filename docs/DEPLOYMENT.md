# QRPDF 从零部署文档 / Deployment Guide

[中文](#中文) | [English](#english)

## 中文

### 1. 部署目标

推荐拓扑：

- `pdf-worker` 只监听服务器 `127.0.0.1:18081`，通过 SSH 隧道管理；
- `student-public` 只监听服务器 `127.0.0.1:18082`；
- Nginx 在公网监听 80/443，只代理 `student-public`；
- `preview-worker` 不开放端口；
- SQLite 和业务文件保存在项目目录的 `data/`，不进入 Git。

不要把 `pdf-worker`、SQLite、原始文件目录或 Docker Socket 暴露到公网。

### 2. 前置条件

准备一台 Linux 服务器和一个域名。建议：

- Ubuntu 22.04/24.04 或同类发行版；
- 2 CPU、2 GiB 内存、10 GiB 可用磁盘；
- Docker Engine 24+；
- Docker Compose v2；
- Git、Python 3.11+、curl、Nginx；
- 域名 A/AAAA 记录指向服务器；
- 所在地区和平台要求的域名备案、许可或安全审核已经完成。

Ubuntu 安装基础工具的示例：

```bash
sudo apt update
sudo apt install -y git python3 curl nginx certbot python3-certbot-nginx
```

Docker 请按 Docker 官方文档安装。确认：

```bash
docker version
docker compose version
python3 --version
```

建议让日常部署用户可以运行 Docker，但不要把不可信用户加入 `docker` 组。

### 3. 一键初始化应用

```bash
git clone <repository-url> qrpdf
cd qrpdf
chmod +x scripts/deploy.sh
./scripts/deploy.sh --public-url https://qr.example.com
```

可选参数：

```text
--public-url URL       写入新二维码的公开基础地址
--admin-username NAME  初始管理员用户名，默认 admin
--bind-address IP      管理服务宿主机监听地址，默认 127.0.0.1
--site-name TEXT       页面名称
--pip-index-url URL    Docker 构建时使用的 Python 包索引
--skip-build           已有正确镜像时跳过构建
```

脚本执行内容：

1. 检查 Docker、Compose 和 Python；
2. 从 `.env.example` 生成权限为 0600 的 `.env`；
3. 生成管理员 scrypt 密码哈希、Session 密钥和 Viewer 密钥；
4. 把一次性管理员明文密码写入权限为 0600 的 `.initial-admin-password`；
5. 创建数据目录并构建运行镜像；
6. 启动 `pdf-worker`、`preview-worker`、`student-public`；
7. 等待健康检查并输出服务状态。

脚本不会自动配置 DNS、Nginx、防火墙、TLS 或备案。它默认不启动可选的 QuickDrop。

读取一次性密码并确认登录后删除文件：

```bash
cat .initial-admin-password
rm .initial-admin-password
```

不要把该文件、密码、`.env` 或密码哈希发到聊天、邮件或 Git。

### 4. 配置 Nginx

编辑模板，将 `qr.example.com` 替换为真实域名：

```bash
cp deploy/nginx/qrpdf-http.conf /tmp/qrpdf.conf
sed -i 's/qr\.example\.com/你的域名/g' /tmp/qrpdf.conf
sudo cp /tmp/qrpdf.conf /etc/nginx/sites-available/qrpdf.conf
sudo ln -s /etc/nginx/sites-available/qrpdf.conf /etc/nginx/sites-enabled/qrpdf.conf
sudo nginx -t
sudo systemctl reload nginx
```

若 `/etc/nginx/sites-enabled/default` 与该站点冲突，应先确认它没有承载其他业务，再由维护人员决定是否禁用；不要盲目删除。

模板在 Nginx 层直接拒绝：

- `/admin`
- `/bindings`
- `/pdf/jobs`
- `/capabilities`
- `/content/`

其余请求代理到 `127.0.0.1:18082`，因此公网只能访问学生应用。

### 5. 配置 HTTPS

确认 DNS 已生效，80/443 端口可从公网访问，然后执行：

```bash
sudo certbot --nginx -d qr.example.com
```

检查证书自动续期：

```bash
sudo certbot renew --dry-run
```

`.env` 中应保持：

```text
PUBLIC_BASE_URL=https://qr.example.com
PUBLIC_QR_BASE_URL=https://qr.example.com
SESSION_COOKIE_SECURE=false
VIEWER_COOKIE_SECURE=true
```

这里管理员通过本机 HTTP SSH 隧道访问，所以管理员 Session Cookie 保持 `false`；若维护人员另外为管理入口配置了可信 HTTPS，才将其改为 `true`。

若一键部署时使用了 HTTP 地址，必须在上传正式资料前更新以上配置并重建三个核心服务；已经生成的二维码 PNG 也应按维护流程重新生成和验证。

### 6. 防火墙

仅开放 SSH、HTTP 和 HTTPS。示例：

```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow OpenSSH
sudo ufw allow 'Nginx Full'
sudo ufw enable
sudo ufw status
```

不要开放 18081、18082 或 SQLite 文件。

### 7. 管理员访问

在管理员电脑上运行：

```bash
ssh -i /path/to/private_key -L 18081:127.0.0.1:18081 <server-user>@<server-host>
```

浏览器打开 `http://127.0.0.1:18081/admin`。公网访问 `/admin` 返回 404 是预期安全行为。

### 8. 部署验收

```bash
docker compose ps
curl -fsS http://127.0.0.1:18081/health
curl -fsS http://127.0.0.1:18082/health
curl -fsS https://qr.example.com/health
```

数据库检查：

```bash
docker compose exec -T pdf-worker python - <<'PY'
import os
import sqlite3

connection = sqlite3.connect(os.environ["PDF_WORKER_DATABASE_PATH"])
print("schema", connection.execute("PRAGMA user_version").fetchone()[0])
print("integrity", connection.execute("PRAGMA integrity_check").fetchone()[0])
connection.close()
PY
```

期望 Schema 8、`integrity ok`。同时确认：

- 公网 `/admin`、管理 API 和 `/content/` 返回 404；
- SSH 隧道中的后台可登录；
- 上传测试 PDF 后可生成预览和二维码；
- 手机使用真实网络扫描二维码可以打开；
- 三个核心容器没有持续重启或 traceback。

### 9. 更新

更新前先备份：

```bash
chmod +x scripts/backup_stage05.sh
scripts/backup_stage05.sh ../qrpdf-backup-$(date -u +%Y%m%dT%H%M%SZ).tar.gz
```

验证备份：

```bash
scripts/restore_stage05.sh ../qrpdf-backup-<timestamp>.tar.gz
```

然后更新代码和镜像：

```bash
git fetch --all --prune
git checkout <reviewed-commit-or-tag>
docker compose config --quiet
docker compose build pdf-worker
docker compose up -d --force-recreate --no-deps pdf-worker
docker compose up -d --force-recreate --no-deps preview-worker student-public
docker compose ps
```

先确认 `pdf-worker` 健康和数据库迁移成功，再更新另外两个容器。

### 10. 备份、恢复与回滚

备份应异机、加密、限制权限，并定期做恢复演练。正式恢复前先阅读 `scripts/restore_stage05.sh` 和 `docs/stage_05d_backup_restore_guide.md`。

镜像回滚与数据库回滚必须匹配。若新版本已把 Schema 7 升到 Schema 8，旧镜像可能拒绝启动；此时不能只切镜像，必须停止写入并恢复升级前数据库和对应文件快照。

永远不要运行：

```bash
docker compose down -v
```

### 11. 故障排查

```bash
docker compose ps -a
docker compose logs --tail=200 pdf-worker
docker compose logs --tail=200 preview-worker
docker compose logs --tail=200 student-public
sudo nginx -t
sudo journalctl -u nginx --since "30 minutes ago"
```

常见原因：

- 构建下载超时：使用可信的 `--pip-index-url` 或预先缓存依赖；
- `ADMIN_PASSWORD_HASH`/密钥为空：重新运行初始化脚本，不要手工填写明文密码；
- 数据目录权限错误：确认宿主目录可由容器 UID 1000 读写；
- 域名能解析但被平台拦截：检查备案、域名审核、服务器提供商策略和 HTTPS；
- 学生服务健康但二维码 404：资料可能已删除/停用，或 token 不存在；
- Schema 比镜像新：使用支持该 Schema 的镜像，或按备份恢复匹配版本。

---

## English

### 1. Target topology

Keep `pdf-worker` on `127.0.0.1:18081`, keep `student-public` on `127.0.0.1:18082`, and expose only `student-public` through Nginx on HTTPS. `preview-worker` has no published port. SQLite and private files remain under `data/` and must not be committed.

### 2. Prerequisites

Use a Linux server with Docker Engine 24+, Docker Compose v2, Git, Python 3.11+, curl, Nginx, and a domain. Recommended minimum resources are 2 CPUs, 2 GiB RAM, and 10 GiB free disk. Complete any registration, filing, or platform review required by the server location and QR-scanning platforms.

### 3. One-command application initialization

```bash
git clone <repository-url> qrpdf
cd qrpdf
chmod +x scripts/deploy.sh
./scripts/deploy.sh --public-url https://qr.example.com
```

The script validates prerequisites, creates `.env`, generates scrypt credentials and random secrets, writes the one-time administrator password to `.initial-admin-password`, builds the image, starts the three core services, and waits for health checks. It does not configure DNS, Nginx, firewall rules, certificates, or domain compliance.

Read the password locally, verify login through an SSH tunnel, and delete the password file.

### 4. Public HTTPS endpoint

Replace `qr.example.com` in `deploy/nginx/qrpdf-http.conf`, install the file as an Nginx site, run `nginx -t`, and reload Nginx. Then obtain a certificate:

```bash
sudo certbot --nginx -d qr.example.com
sudo certbot renew --dry-run
```

The committed template blocks admin, management API, capability, and original-content paths before proxying other requests to `127.0.0.1:18082`.

### 5. Admin access

```bash
ssh -i /path/to/private_key -L 18081:127.0.0.1:18081 <server-user>@<server-host>
```

Browse to `http://127.0.0.1:18081/admin`. A public 404 for `/admin` is expected.

### 6. Validation

Check both loopback health endpoints, the public HTTPS health endpoint, Schema 8, SQLite `integrity_check=ok`, admin login through the tunnel, a real phone scan, and recent container logs. Public admin/API/original-content paths must remain unavailable.

### 7. Updates and rollback

Create and validate a backup before changing code or images. Recreate `pdf-worker` first, confirm health and migration success, and only then recreate `preview-worker` and `student-public`. A rollback image must match the database schema; restoring an older image may also require restoring its pre-upgrade database and file snapshot.

Never run `docker compose down -v` on an installation that contains data.
