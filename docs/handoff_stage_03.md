# 第三阶段交接文档

更新时间：2026-07-15

远端项目：`/home/user/projects/qr-exercise-prototype`

Windows 工作副本：`D:\codex_project\QRPDF_server\qr-exercise-prototype`

## 当前结论

第三阶段已经实现并部署。当前可以完全通过中文后台完成：新建解析资料、下载动态或固定二维码、给练习册 PDF 加二维码、查看目标页预览、下载结果、搜索资料、替换文件和恢复历史版本。

QuickDrop 与 PDF Worker 均为 `healthy`。服务继续只监听 `127.0.0.1`；没有开放局域网或公网，没有执行 Git push。

## 立即使用

在 Windows PowerShell 中保持以下命令运行：

```powershell
ssh -L 18080:127.0.0.1:18080 -L 18081:127.0.0.1:18081 tx
```

浏览器打开 <http://127.0.0.1:18081/admin>。管理员用户名为 `admin`，一次性初始密码只在最终交付消息中显示，不写入本文档。

详细操作见 `docs/stage_03_admin_guide.md`。

## 重要业务语义

动态二维码：`/r/{qr_id}`，始终打开当前版本。替换或恢复资料后，已印刷二维码会跟随变化。

固定二维码：`/r/{qr_id}/versions/{version_id}`，永远打开指定版本。固定引用会保护版本，自动历史清理不会删除它。

正式定稿内容建议使用固定二维码；持续维护内容可使用动态二维码。当前二维码基础地址是 `127.0.0.1`，两种二维码都只能做本机流程测试，不能正式印刷。

## 原数据状态

- 数据库 schema 已从 1 幂等迁移到 2。
- 原有 2 条资料、3 个文件版本和 3 个 PDF job 均保留。
- 原绑定 `df826233e31c4b98891d50aa7d6d4cc0` 继续可访问。
- 原 PDF SHA-256：`bd4b3408f4986d4a41f5071c2d645328edf70882181438697be849331eb6f0fc`，迁移后重新下载核对一致。
- 历史中文文件名现在显示为 `学术英语理工Unit 1 202409.pdf`。
- 迁移前备份在 `data/pdf-worker/db/backups/`，共两份，单份约 52 KiB。
- QuickDrop 数据目录约 1.2 MiB，未被 PDF Worker 读取或修改。

## 安全状态

- 管理页面必须登录，状态修改表单校验 CSRF。
- 管理 API 不再允许匿名访问。
- Swagger 和 OpenAPI 默认关闭。
- Session Cookie 为签名、`HttpOnly`、`SameSite=Lax`，默认有效 8 小时。
- 密码使用 scrypt 哈希；`.env` 与一次性凭据不进入 Git。
- 端口仍为 `127.0.0.1:18080` 和 `127.0.0.1:18081`。
- PDF Worker 保持非 root、`cap_drop: ALL`、`no-new-privileges`、1 CPU、512 MiB、128 PIDs 和日志轮转。

首次登录后应尽快按 README 的“修改管理员密码”步骤更换密码。

## 验证结果

隔离自动化测试：`57 passed, 0 failed, 0 skipped`。

浏览器手工检查：

- 中文登录页、工作台和三个主要入口。
- 资料列表、搜索筛选控件、真实中文资料详情和版本入口。
- PDF 向导的动态/固定、页码、大小和四角位置控件。
- 真实 PDF job 结果页、目标页预览和右下角二维码。
- 390x844 手机视口和 1440x900 桌面视口，无页面级横向溢出。

## 运维命令

```bash
cd ~/projects/qr-exercise-prototype
docker compose ps
docker compose logs --tail=200 pdf-worker
curl -fsS http://127.0.0.1:18081/health
docker compose --profile test run --rm pdf-worker-tests
```

只重建 PDF Worker：

```bash
docker compose build pdf-worker
docker compose up -d --no-deps pdf-worker
```

不要使用 `docker compose down -v`，不要删除 `data/`，不要修改 `data/quickdrop/db/`。

## 需要共同决定的下一阶段需求

1. **手机访问方式**：机构局域网小范围试用，还是正式公网域名和 HTTPS。当前不建议直接绑定 `0.0.0.0`。
2. **二维码使用规范**：哪些资料必须锁定版本，哪些允许自动更新；正式印刷前由谁复核。
3. **管理员体系**：是否增加多个账号、角色、后台改密、忘记密码和审计日志。
4. **备份恢复**：备份频率、保留周期、异地副本和恢复演练负责人。
5. **批量能力**：是否需要批量建资料、批量给 PDF 盖码、ZIP 导出或一个 PDF 多个二维码。
6. **版本治理**：是否需要管理员查看固定引用来源、取消保护、归档或删除资料。
7. **公网安全**：学生入口与管理员后台是否使用不同域名，以及反向代理、访问控制、监控和告警方案。

网络四种模式、风险和恢复方法见 `docs/stage_03_network_guide.md`。第三阶段详细验收数据见 `docs/stage_03_report.md`。

## Git 状态

- 分支：`main`
- 第三阶段基线标签：`stage-03-baseline`
- 已有第三阶段提交：`1d23d45`、`006e301`
- 文档、最终样式和补充测试已整理到本地提交，准确提交号以 `git log --oneline stage-03-baseline..HEAD` 为准。
- 未执行 `git push`。
