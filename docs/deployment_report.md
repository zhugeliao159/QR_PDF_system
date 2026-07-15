# 练习册二维码解析系统 - 部署报告

部署时间：2026-07-15（Asia/Shanghai）
状态：第一阶段原型已完成并通过基础验证。

## 实际机器与 Docker 环境

| 项目 | 实际值 |
| --- | --- |
| Ubuntu | 22.04.2 LTS |
| 内核 | 6.8.0-101-generic |
| CPU | Intel(R) Core(TM) Ultra 9 275HX，24 个在线逻辑 CPU |
| 架构 | x86_64 / linux/amd64 |
| 总内存 / 最终可用内存 | 30 GiB / 约 22 GiB |
| 总磁盘 / 最终可用磁盘 | 347 GiB / 约 300 GiB |
| Docker | 29.6.1（build `8900f1d`） |
| Docker Compose | v5.3.1 |
| Docker 服务 | enabled、active |

项目目录：`/home/user/projects/qr-exercise-prototype`

## 镜像与服务

| 服务 | 镜像与版本 | 宿主机 -> 容器端口 | 资源限制 | pids_limit |
| --- | --- | --- | --- | --- |
| QuickDrop | 官方 `roastslav/quickdrop:v1.5.3`，经 `dockerproxy.net` 代理；`sha256:f47e2bd7ec0fc5f3dc984f17f83fc7fd4361093bff0f15b4357553ed16bf159b` | `127.0.0.1:18080` -> `8080` | 1 CPU，1 GiB | 256 |
| PDF Worker | 自建镜像；基础为官方 `python:3.11.14-slim`，经 `dockerproxy.net` 代理；`sha256:c8271b1f627d0068857dce5b53e14a9558603b527e46f1f901722f935b786a39` | `127.0.0.1:18081` -> `8000` | 1 CPU，512 MiB | 128 |

QuickDrop 官方仓库：<https://github.com/RoastSlav/quickdrop>

QuickDrop 数据目录按官方要求挂载：

- `data/quickdrop/db` -> `/app/db`
- `data/quickdrop/files` -> `/app/files`
- `data/quickdrop/logs` -> `/app/log`
- `data/pdf-worker/input` -> `/data/input`（只读）
- `data/pdf-worker/output` -> `/data/output`

两个服务都连接到独立的 `qr-prototype-network`，仅发布必要端口，启用 `restart: unless-stopped`，移除全部 Linux capabilities，并启用 `no-new-privileges`。QuickDrop 与 PDF Worker 都以非 root 用户运行；QuickDrop 使用 `1000:1000` 以匹配项目数据目录权限。

## 已创建文件

- `compose.yaml`、`.env`、`.env.example`、`.gitignore`、`README.md`
- `pdf-worker/Dockerfile`、`pdf-worker/requirements.txt`、`pdf-worker/app/main.py`
- `docs/environment_audit.md`、`docs/deployment_report.md`
- 项目内 `data/` 持久化目录结构

`.env` 与 `data/` 均已被 Git 忽略；`.env` 权限为 600。PDF Worker 固定依赖：FastAPI 0.115.12、Uvicorn 0.34.3、python-multipart 0.0.20、PyMuPDF 1.26.1、qrcode 8.2、Pillow 11.2.1。

## 验证结果

1. `docker compose config` 已成功渲染，确认 bind mount、127.0.0.1 端口、资源限制、日志限制、独立网络、无 privileged、无 Docker Socket 挂载。
2. `docker compose build --pull pdf-worker` 成功；全部 Python 依赖安装成功。
3. QuickDrop 固定镜像已成功拉取；镜像摘要和官方摘要一致。
4. 两个容器均处于 `healthy`：
   - QuickDrop 根路径跟随重定向后为 HTTP 200。
   - `GET /health` 返回 HTTP 200：`{"status":"ok","service":"pdf-worker"}`。
   - `GET /capabilities` 返回 HTTP 200；Python 3.11.14、PyMuPDF 1.26.1、qrcode、Pillow 11.2.1 均导入成功，input 可读、output 可写。
5. 日志检查无启动失败：QuickDrop 完成 SQLite 迁移并启动 Tomcat；PDF Worker 的 Uvicorn 正常监听 8000。
6. 在 `data/pdf-worker/output` 写入小型验证文件后，`docker compose restart pdf-worker` 后该文件仍存在；随后执行不带 `-v` 的 `docker compose down`，验证文件与 `data/quickdrop/db/quickdrop.db` 仍存在；再次 `docker compose up -d` 后两个服务恢复并再次健康。
7. `docker inspect` 已确认实际限制：
   - QuickDrop：`NanoCpus=1000000000`、`Memory=1073741824`、`PidsLimit=256`
   - PDF Worker：`NanoCpus=1000000000`、`Memory=536870912`、`PidsLimit=128`
8. `docker inspect` 已确认两个容器均使用 `json-file`，`max-size=10m`、`max-file=3`。未人为生成 10 MiB 日志来触发轮转，故这里验证的是 Docker 已实际加载轮转配置。
9. 最终 `docker stats --no-stream` 抽样：QuickDrop 约 378.7 MiB、33 个 PIDs；PDF Worker 约 51.82 MiB、3 个 PIDs。
10. 最终项目 `data/` 约 116 KiB；Docker 镜像占用约 683.4 MB；未创建 Docker 卷。

## Windows 访问

在 Windows 保持以下 SSH 会话：

```powershell
ssh -L 18080:127.0.0.1:18080 -L 18081:127.0.0.1:18081 tx
```

- QuickDrop：<http://127.0.0.1:18080>
- PDF Worker health：<http://127.0.0.1:18081/health>
- PDF Worker capabilities：<http://127.0.0.1:18081/capabilities>

## 已发现并解决的问题

首次启动时 QuickDrop 无法创建 SQLite 数据库：在移除所有 capabilities 后，镜像内默认 root 进程无法访问宿主用户 `1000:1000` 所有、权限 750 的 bind mount。已验证镜像运行文件可被 UID 1000 读取，并将 QuickDrop 以 `1000:1000` 运行；不恢复任何 capability。修正后数据库迁移、HTTP 访问与健康检查均成功。

## 遗留风险与下一阶段建议

- Docker Hub 和 `download.docker.com` 在当前网络中直连不可用。Docker CE 使用清华镜像安装，应用镜像使用 `dockerproxy.net` 代理；最终镜像均按摘要固定，但生产环境应使用组织可控的镜像缓存或允许的官方网络出口。
- QuickDrop 是首次初始化状态，浏览器首次访问会进入其初始化/设置流程；本阶段没有配置真实敏感资料、公开域名或 HTTPS。
- 当前未实现文件与永久二维码 ID 绑定、二维码写入或解析 PDF、批量上传导出、PDF 合并、二维码位置设置、用户认证、扫码统计、生产备份和正式权限控制。
- 后续可在确认业务流程后实现 PDF 上传处理和二维码写入接口，并针对实际 PDF 大小重新评估 512 MiB Worker 内存限制。

## 对现有服务的影响

未发现对已有容器或已有服务的影响。唯一系统级变更是安装 Docker、启用 Docker 服务、添加 Docker 官方签名 APT 源（经清华镜像）及把当前用户加入 docker 组；未修改 SSH、防火墙、系统代理、Docker daemon 配置或任何已有 Docker 数据。