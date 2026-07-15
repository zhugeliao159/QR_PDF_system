# 第三阶段网络模式指南

更新时间：2026-07-15

## 当前检测结果

| 项目 | 结果 |
| --- | --- |
| PDF Worker 监听 | `127.0.0.1:18081` |
| QuickDrop 监听 | `127.0.0.1:18080` |
| 二维码基础地址 | `http://127.0.0.1:18081` |
| 机构局域网候选地址 | `192.168.100.20/23`，网关 `192.168.100.1` |
| Tailscale 地址 | `100.110.246.123`，服务已运行 |
| UFW | 未启用 |
| 当前模式 | A：安全开发模式 |

Tailscale 当前报告 DNS 服务器不可达警告。该警告不影响本阶段的本机隧道访问，但在选择 Tailscale 方案前需要单独排查。

本阶段没有修改监听地址、防火墙、路由、Tailscale Serve 或 ACL。

## 模式 A：SSH 隧道安全开发模式

适合开发、运维和单台 Windows 管理电脑。服务仅监听服务器回环地址，外部设备不能直接连接。

在 Windows PowerShell 中运行并保持窗口开启：

```powershell
ssh -L 18080:127.0.0.1:18080 -L 18081:127.0.0.1:18081 tx
```

然后打开：

- 管理后台：<http://127.0.0.1:18081/admin>
- 健康检查：<http://127.0.0.1:18081/health>
- QuickDrop：<http://127.0.0.1:18080>

风险和限制：手机扫描 `127.0.0.1` 会访问手机自身，因此无法打开解析文件；其他管理员也不能直接访问。此模式生成的二维码不得正式印刷。

## 模式 B：机构局域网试用

适合管理员电脑、测试手机和服务器都连接同一个可信机构路由器或 Wi-Fi 的小范围试用。不适合跨网络访问或公开发行。

先在服务器确认地址：

```bash
ip -4 addr
ip route
hostname -I
```

在路由器中为服务器设置 DHCP 地址保留，避免 IP 变化。当前候选配置示例为：

```dotenv
PDF_WORKER_BIND_ADDRESS=192.168.100.20
PUBLIC_QR_BASE_URL=http://192.168.100.20:18081
```

重建服务后，在 Windows 和手机浏览器中分别访问：

```text
http://192.168.100.20:18081/health
http://192.168.100.20:18081/r/一个测试资料编号
```

只有两个设备都能访问，并确认网络是可信机构网络后，才能做局域网试印。不要默认绑定 `0.0.0.0`，因为它会让服务监听所有网络接口。

如果以后启用 UFW，应仅允许实际局域网网段，例如当前 `/23` 网段可由技术人员核准后使用：

```bash
sudo ufw allow from 192.168.100.0/23 to any port 18081 proto tcp
```

不要使用不限制来源的 `sudo ufw allow 18081/tcp`。本项目没有自动执行任何防火墙命令。

主要风险：

- 局域网中的其他设备可能访问学生入口或尝试管理员登录。
- HTTP 没有传输加密，不能跨不可信网络使用。
- 服务器 IP 一旦改变，已印刷二维码会失效，因此必须做 DHCP 地址保留或使用稳定域名。

## 模式 C：Tailscale 测试和远程维护

适合开发人员、少量固定管理员和手机临时扫码测试。所有访问设备都必须安装 Tailscale、登录同一 Tailnet，并受 ACL 控制。

检查命令：

```bash
tailscale status
tailscale ip -4
systemctl status tailscaled --no-pager
```

当前服务器 Tailscale IP 是 `100.110.246.123`。若要试用，应先解决当前 DNS 警告，评审 ACL，再显式配置监听地址和二维码基础地址。手机也必须安装并登录 Tailscale。

此模式不适合所有学生、普通公众或正式大规模发行。学生不应被要求安装 Tailscale。本阶段不执行 `tailscale serve`，也不修改 Tailscale ACL。

主要风险：错误的 ACL 或 Serve 配置可能扩大访问范围；账号或设备离开 Tailnet 后二维码失效；Tailscale 地址不等于公开互联网地址。

## 模式 D：未来正式公网模式

正式学生扫码需要单独设计和实施：

- 稳定正式域名和 HTTPS 证书。
- 反向代理、安全更新、监控和备份恢复。
- 公开只读学生入口，例如 `https://q.example.com/r/...`。
- 与学生入口分离的管理员后台，例如 `https://admin.example.com/`。
- 管理员登录，以及机构 IP、VPN、Tailscale 或其他访问控制。
- 管理操作审计、告警和定期恢复演练。

风险：公网会持续受到扫描、暴力登录和漏洞利用；错误配置可能泄露管理接口或文件。当前单机原型未达到公网生产要求，本阶段不实施此模式。

## 恢复默认配置

无论从局域网还是 Tailscale 测试返回安全开发模式，都应把 `.env` 恢复为：

```dotenv
PDF_WORKER_BIND_ADDRESS=127.0.0.1
PUBLIC_QR_BASE_URL=http://127.0.0.1:18081
```

然后执行：

```bash
cd ~/projects/qr-exercise-prototype
docker compose config --quiet
docker compose up -d --force-recreate --no-deps pdf-worker
docker compose ps
ss -lntp | grep 18081
```

最终应看到 `127.0.0.1:18081`，而不是 `0.0.0.0:18081` 或局域网地址。若曾添加 UFW 规则，应由技术人员按当时的准确规则编号或完整规则撤销，不能盲目删除其他服务规则。

## 配置原则

网络开放必须由负责人选择模式后手工执行、验证和记录。应用只检测 `PUBLIC_QR_BASE_URL` 并显示中文提示，不会自动修改 `.env`、Docker 绑定、防火墙、路由或 Tailscale 配置。
