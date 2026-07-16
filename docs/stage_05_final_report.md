# Stage 05 最终报告

## 结论

Stage 05A–05D：PASS（远程权威环境）。Stage 4 历史回归、Stage 05 最终全量 168 项自动化测试均通过；没有跳过和失败。实体手机扫码仍未在本阶段实测，不能写成已验证。

## 分阶段结果

- 05A：schema 4、PreviewSet/PreviewPage/PreviewJob、私有 PDF/PNG/JPEG/WebP 渲染、回填和 Worker；124 passed。
- 05B：学生端完全切到私有逐页 WebP，发布前强制完整 Preview，旧 `/r` 兼容；130 passed。
- 05C：schema 5、HMAC-only Viewer Session、动态版本固定、服务端匿名水印、撤销与限速；154 passed。基准原始编码 A4 86.20 ms、公式 100.94 ms、彩色 71.91 ms，水印并发上限设为 6。
- 05D：公开路由/原件扫描、安全头、清理、备份恢复、Worker 中断、20/50 并发负载和运维文档；168 passed。

## 验收证据

- 生产样本共 Resource 6、Revision 13、Asset 13、completed PreviewSet 8、PreviewPage 186；当前发布覆盖 5/5，固定引用覆盖 1/1，无缺失或失败。
- 匿名扫描 11 个公开/越权请求，不含原始 PDF、原始图片 SHA、Asset/storage/revision 下载地址或绝对路径；PDF 和图片自动化样本均 PASS。
- Viewer TTL 30 分钟、idle 10 分钟；Cookie HttpOnly、服务端不存原始 Token；trace_code 不含身份；全局动态水印并发 6，页面限速 120/分钟，manifest 30/分钟。
- 清理默认 dry-run、逐项复核引用且幂等；演练分批把 1、69、65、71 个到期/idle 测试 Session 标记过期，最终 dry-run 为 0，未删除任何受保护 Asset/Preview。
- 备份归档 29 MiB，归档 SHA-256 与内部逐文件 SHA 全部通过；临时恢复的数据库数量、动态/固定 alias 和文件哈希一致。
- Preview Worker 在处理中停止后 stale 重领为 attempts=2，无重复 completed set/页面，不修改原件。
- 20/50 并发分别 240/600 请求，预期 429 为 106/371，复测 5xx 均为 0；pdf-worker 峰值 103.9% CPU、210.6 MiB，preview-worker 峰值 85.56% CPU、84.51 MiB，RestartCount 均 0。
- 当前目录约 DB 1.6 MiB、storage 31 MiB（bindings 15 MiB、previews 15 MiB、source 696 KiB、generated 768 KiB）。限制维持 pdf-worker 1 CPU/512 MiB/128 PIDs，preview-worker 1 CPU/768 MiB/64 PIDs。

## 边界与后续

学生端不提供原件或下载按钮，但无法阻止截图、录屏、OCR 或保存已接收派生图；外部 URL 默认禁用且不在保护范围。当前是固定 LAN IP 的 HTTP 测试部署，不是正式公网。公网前置条件见 `stage_05_security_boundary.md`。未修改 QuickDrop 数据库、网络、防火墙、Tailscale 或路由，未 push。
