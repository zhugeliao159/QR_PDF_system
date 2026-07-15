# Stage 4A 迁移前数据清单

记录时间：2026-07-15  
数据库：`data/pdf-worker/db/app.db`  
当前 schema：2  
当前 Git 基线：`stage-04-baseline`，指向 `61957c7`

## 基线状态

- 分支：`main`
- Git 工作区：干净
- 自动化测试：`57 passed, 0 failed, 0 skipped`，耗时 6.58 秒
- QuickDrop：healthy，`127.0.0.1:18080`
- PDF Worker：healthy，`192.168.100.20:18081`
- PDF Worker 资源：1 CPU、512 MiB、128 PIDs，非 root `appuser`
- `/health`：HTTP 200
- `/capabilities`：匿名请求按安全设计返回 HTTP 401

## 数量

| 项目 | 迁移前数量 |
| --- | ---: |
| `bindings` | 2 |
| `file_versions` | 4 |
| `version_references` | 0 |
| `pdf_jobs` | 3 |
| `storage/bindings` 实际文件 | 4 |
| `storage` 全部业务文件 | 10 |

## Binding 与 current 映射

| legacy binding | qr_id | display_code | 名称 | current_version_id | 状态 |
| ---: | --- | --- | --- | ---: | --- |
| 1 | `6e69e5d0204542b39d19493a4f64cdea` | `QR-QZJK-6YXR` | answer-v1 | 1 | active |
| 2 | `df826233e31c4b98891d50aa7d6d4cc0` | `QR-Z8SF-ZU3Y` | 学术英语理工Unit 1 202409 | 4 | active |

## 文件版本

| version_id | binding_id | 版本 | 文件名 | 字节数 | SHA-256 | 文件存在 |
| ---: | ---: | ---: | --- | ---: | --- | --- |
| 1 | 1 | 1 | `answer-v1.txt` | 18 | `0e8282b3f2b593268bb8922bb387c58443702e37b9fa8f7518f8c7338d57316c` | 是 |
| 2 | 1 | 2 | `answer-v2.txt` | 18 | `5dd3626afff707ea138133eb2dba8cc50e8ac34420d1b20659c55251c7a60b87` | 是 |
| 3 | 2 | 1 | `学术英语理工Unit 1 202409.pdf` | 254738 | `bd4b3408f4986d4a41f5071c2d645328edf70882181438697be849331eb6f0fc` | 是 |
| 4 | 2 | 2 | `作业1.pdf` | 183211 | `bd0f1fdfb02b2c2155c2b24c008f3d86271a442c955ac4396a756acacafa9b0c` | 是 |

四个文件的实际字节数和重新计算的 SHA-256 均与数据库一致。

## 公开入口校验

| 入口 | 实际 SHA-256 | 结果 |
| --- | --- | --- |
| `/r/6e69e5d0204542b39d19493a4f64cdea` | `0e8282b3f2b593268bb8922bb387c58443702e37b9fa8f7518f8c7338d57316c` | 与 current version 1 一致 |
| `/r/df826233e31c4b98891d50aa7d6d4cc0` | `bd0f1fdfb02b2c2155c2b24c008f3d86271a442c955ac4396a756acacafa9b0c` | 与 current version 4 一致 |
| `/r/6e69.../versions/1` | `0e8282b3f2b593268bb8922bb387c58443702e37b9fa8f7518f8c7338d57316c` | 一致 |
| `/r/6e69.../versions/2` | `5dd3626afff707ea138133eb2dba8cc50e8ac34420d1b20659c55251c7a60b87` | 一致 |
| `/r/df82.../versions/3` | `bd4b3408f4986d4a41f5071c2d645328edf70882181438697be849331eb6f0fc` | 一致 |
| `/r/df82.../versions/4` | `bd0f1fdfb02b2c2155c2b24c008f3d86271a442c955ac4396a756acacafa9b0c` | 一致 |

## 引用与作业

- `version_references` 当前为 0，因此 Stage 4A 应迁移出 0 条 `revision_references`。
- `pdf_jobs` 当前为 3，Stage 4A 不修改或删除这些记录。
- 固定版本 URL 本身对四个版本都已验证；迁移后仍需逐一复验。

## 迁移通过条件

- `answer_resources=2`
- `answer_revisions=4`
- `assets=4`
- latest `qr_aliases=2`
- `revision_references=0`
- 文件缺失、大小不一致、SHA-256 不一致、current 映射失败、public token 映射失败均为 0
- 原动态和固定入口返回字节保持不变
