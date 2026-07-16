# Stage 05 工作交接

日期：2026-07-16。权威仓库 `/home/user/projects/qr-exercise-prototype`，分支 `main`；服务地址 `http://192.168.100.20:18081`。`pdf-worker` 与 `preview-worker` 运行，QuickDrop 保持停止且其数据库从未被本阶段读取或修改。

Stage 05A/05B/05C 提交为 `590c79b`、`195a208`、`bbac1e2`；Stage 05D 提交见当前 `git log -1`。schema 5，无 Stage 05D migration。最终自动化基线 168 passed，完整结论见 `stage_05_final_report.md`。

常规检查：

```bash
cd /home/user/projects/qr-exercise-prototype
docker compose ps
curl -fsS http://192.168.100.20:18081/health
docker compose exec -T pdf-worker python -m app.scripts.cleanup_storage --dry-run
docker compose --profile test run --rm pdf-worker-tests
```

备份/恢复使用 `scripts/backup_stage05.sh` 与 `scripts/restore_stage05.sh`，先读 `stage_05d_backup_restore_guide.md`。公开原件审计使用 `python -m app.scripts.audit_public_original_access`。不要 `docker compose down -v`，不要删除 `data/`，不要把真实 `.env` 或 Viewer secret 提交到 Git。

当前恢复演练归档位于 `/home/user/projects/qr-stage05-rehearsal-20260716.tar.gz`；它含真实配置，只能 0600 保管，验证后应转移到加密异机介质或由负责人安全销毁。临时恢复副本位于 `/tmp/stage05-restore-rehearsal-20260716`。

已知边界：实体手机扫码未验证；当前 LAN IP/HTTP 不适合正式印刷和公网；没有 HA、集中监控、告警、自动异机备份或管理员 MFA；外部 URL 默认禁用；水印提高传播成本但不阻止截图。下一阶段应先完成正式域名/HTTPS/网络隔离方案和机构隐私合规审批，再进行公网容量及实体设备验收。
