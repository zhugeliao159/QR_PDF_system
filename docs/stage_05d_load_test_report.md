# Stage 05D 负载与恢复测试报告

日期：2026-07-16；目标：远程 LAN 服务 `192.168.100.20:18081`。同时让 Preview Worker 生成 80 页中等 PDF；每个 Viewer Session 打开入口、manifest 并连续请求 10 页，另对同一页执行 126 次限速探测。资源限制未放宽。

| 场景 | 请求 | 200 | 成功率 | 429 | 5xx/传输错误 | P50 | P95 | P99 | 墙钟时间 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 20 并发 Session | 240 | 134 | 55.83% | 106 | 0 / 0 | 1376.64 ms | 1629.47 ms | 1829.78 ms | 15.45 s |
| 50 并发 Session | 600 | 229 | 38.17% | 371 | 0 / 0 | 2509.70 ms | 3334.31 ms | 3662.71 ms | 29.22 s |
| 单页限速探测 | 126 | 121 | 96.03% | 5 | 0 / 0 | — | — | — | — |

429 是全局页面生成并发上限 6 和每 Session 分钟限速的预期背压，不应通过取消资源限制提高“成功率”。pdf-worker 24 个采样的峰值 CPU 103.9%、内存 210.6 MiB/512 MiB（41.13%）；preview-worker 峰值 CPU 85.56%、内存 84.51 MiB/768 MiB（11.00%）。两容器测试前后 RestartCount 均为 0。数据目录测试前约 DB 1.4 MiB、storage 31.5 MB，测试后 DB 1.6 MiB、storage 31.5 MB；增长来自会话/访问事件，演练 Asset 与 Preview 已清理。

首轮测试真实发现 SQLite 会话审计写竞争：20 并发出现 6 个 5xx，50 并发出现 57 个 5xx，日志为 `sqlite3.OperationalError: database is locked`。修复为在 web 进程内串行化极短的 Viewer Session 写事务，页面水印仍按上限并发；增加 40 并发且 SQLite busy timeout 为 1 ms 的回归测试。相同参数复测为 0 个 5xx、0 个传输错误。

Worker 中断演练另用 120 页、inactive 且带专用标记的资源：任务 processing/attempts=1 时停止容器，人工把 claimed_at 推到 stale 阈值外，重启后完成为 attempts=2。最终只有 1 个 completed PreviewSet、120 个 PreviewPage，原始 Asset SHA-256 未变，临时目录和演练资源已清理。

结论：当前单机和限额适合小规模机构并发，系统会以 429 保护资源；不代表互联网高并发、HA 或容量承诺。
