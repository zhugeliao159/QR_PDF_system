# Stage 4C 交接

更新时间：2026-07-15

## 当前版本

Stage 4C 已完成并部署。管理员上传新答案后先得到草稿，学生二维码保持旧答案；管理员预览并点击“发布此版本”后，动态二维码才切换。锁定版本二维码始终保持原版本。

## 日常操作

1. 打开 <http://192.168.100.20:18081/admin> 并登录。
2. 在“管理已有解析资料”中进入资料详情。
3. 点击“新建答案版本”，上传文件并保存草稿。
4. 在草稿页预览或下载核对。
5. 点击“发布此版本”并二次确认。
6. 需要切回旧答案时，在“历史已发布版本”中点击“重新发布此版本”。

## 运维检查

```bash
cd /home/user/projects/qr-exercise-prototype
docker compose ps
curl -fsS http://192.168.100.20:18081/health
docker compose --profile test run --rm pdf-worker-tests
```

更新 PDF Worker 时不要重启或修改 QuickDrop：

```bash
docker compose build pdf-worker
docker compose up -d --no-deps pdf-worker
```

## 关键边界

- 不要把草稿改为公开 `/content` 可访问。
- 不要绕过发布服务直接修改当前答案。
- 不要删除被锁定二维码引用的已发布版本。
- 不要把旧 PUT 恢复成匿名写接口。
- 不要修改 `.env` 的 LAN 绑定、QuickDrop 数据或防火墙配置。

## 下一阶段前置条件

Stage 4D 必须建立在当前 83 个测试全部通过的基础上。新增图片或受控外部 URL 时，需要复用草稿、发布、并发保护和审计流程，并保持旧文件版本与固定二维码可用。
