# 练习册二维码解析系统 - 环境审计

审计时间：2026-07-15（Asia/Shanghai）

## 机器配置摘要

- 操作系统：Ubuntu 22.04.2 LTS
- Linux 内核：6.8.0-101-generic
- CPU：Intel(R) Core(TM) Ultra 9 275HX，24 个在线逻辑 CPU
- 架构：x86_64（Docker 镜像使用 linux/amd64）
- 内存：30 GiB；本次最终复核时约 22 GiB 可用
- Swap：2.0 GiB；最终复核时未使用
- 根分区及项目分区：`/dev/nvme0n1p5`（ext4），347 GiB 总量、约 300 GiB 可用
- 项目目录：`/home/user/projects/qr-exercise-prototype`；位于可写的根分区
- systemd：存在，版本 249
- IP：局域网 `192.168.100.20/23`；Tailscale `100.110.246.123/32`

未发现只读文件系统。`dmesg` 对当前用户不可读，未提升权限强行读取；没有观察到其他明显的磁盘 I/O 异常。

## Docker 状态

安装前 Docker、Docker Compose v2、Docker 服务和现有 Docker 容器均不存在。安装后状态如下：

- Docker Engine：29.6.1（build `8900f1d`）
- Docker Compose：v5.3.1
- Docker 服务：`enabled` 且 `active`
- 当前用户已加入 `docker` 组；重新登录后的 SSH 会话已验证可免 sudo 使用 Docker
- 当前项目运行 2 个容器、0 个 Docker 卷；所有项目持久化数据使用 bind mount
- Docker 镜像占用：683.4 MB；构建缓存：177 MB；没有清理或删除任何既有 Docker 数据

Docker 使用清华大学 Docker CE 软件源镜像安装。该源提供 Docker 官方签名 key，安装前已核对其指纹为 `9DC858229FC7DD38854AE2D88D81803C0EBFCD88`。

## 端口与已有服务

部署前 `18080` 与 `18081` 均未监听。现已由本项目独占，并仅绑定回环地址：

- `127.0.0.1:18080` -> QuickDrop 容器 `8080`
- `127.0.0.1:18081` -> PDF Worker 容器 `8000`

部署前已存在 SSH `22`、本地打印服务、DNS、Tailscale 和开发工具的本地监听端口；本项目未占用或修改它们。

## 网络连通性

- GitHub：HTTP 200
- Ubuntu APT 源：可访问
- PyPI：可访问
- `registry-1.docker.io`：直连解析镜像清单超时
- `download.docker.com`：连接被重置
- 可访问的 Docker 镜像代理：`dockerproxy.net`

因此，本项目不修改 `/etc/docker/daemon.json`，而是在镜像引用中显式使用 `dockerproxy.net` 代理官方镜像路径。QuickDrop 的最终摘要与官方发布摘要一致，Python 基础镜像亦按摘要固定。该代理依赖应在后续生产方案中重新评估。

## QuickDrop 官方信息核实

- 官方仓库：<https://github.com/RoastSlav/quickdrop>
- 官方镜像：`roastslav/quickdrop`
- 固定版本：`v1.5.3`
- 固定摘要：`sha256:f47e2bd7ec0fc5f3dc984f17f83fc7fd4361093bff0f15b4357553ed16bf159b`
- 默认端口：`8080`
- 官方持久化目录：`/app/db`、`/app/files`、`/app/log`
- 许可证：MIT
- 架构：官方镜像支持 linux/amd64，和本机 x86_64 兼容
- 官方文档未要求为最小启动配置设置额外环境变量，故没有添加无法确认含义的变量

## 推荐资源与数据容量

30 GiB 内存和约 300 GiB 空闲磁盘足以运行原型；仍按节制原则限制：

- QuickDrop：1 CPU、1 GiB 内存、256 PIDs
- PDF Worker：1 CPU、512 MiB 内存、128 PIDs
- 初期上传数据建议限制在 2 GiB 至 5 GiB，单个 PDF 默认不超过 100 MB
- 每个容器使用 json-file 日志驱动；单日志文件 10 MiB，最多保留 3 个

## 风险与结论

项目目录安全可写、磁盘和内存余量充足、端口不冲突，适合继续部署。主要风险是 Docker Hub 直连不可用，当前只能经 `dockerproxy.net` 获取经摘要固定的官方镜像；该网络限制和代理供应链风险已在部署报告中记录。