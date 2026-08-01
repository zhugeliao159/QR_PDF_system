# Stage 07：按文件名绑定的永久二维码上传

## 行为

- 仅接受 PDF；文件名（去掉 `.pdf`）就是名称，不再填写年级、学科、教材、章节或备注。
- 名称按 Unicode NFC + 不区分大小写匹配。新名称创建一个永久二维码；同名上传始终复用原二维码。
- 二维码 PNG 持久化在 `data/pdf-worker/storage/qr-codes/`，下载文件名为 `<PDF名称>.png`。
- 选择文件后，浏览器先提交文件清单并获得全部二维码，再以最多 3 个并发请求逐份传输 PDF。
- 文件传输结束后可关闭上传页；`preview-worker` 在后台校验、生成 WebP 预览并发布。
- 替换期间学生继续看到旧内容；新预览成功后原子切换。失败时旧内容保持不变。
- 新名称在内容就绪前扫码返回“处理中”页面。旧的固定版本二维码继续解析，但后台不再创建新的固定版本二维码。

## 数据与接口

- Schema 7 为 `answer_resources` 增加唯一 `name_key`，迁移时以当前 PDF 文件名回填名称并清空旧详细元数据。
- `POST /admin/materials/import/reserve`：提交 `{csrf_token, files:[{filename,size}]}`，立即返回批次、二维码和逐文件上传地址。
- `POST /admin/materials/imports/{batch_key}/items/{item_number}/file`：传输单个已预留 PDF。
- `GET /admin/materials/imports/{batch_key}/status`：查询上传、处理和失败状态。
- `GET /admin/materials/imports/{batch_key}/qrs.zip`：下载本批次全部同名二维码。

## 运维注意

- 升级会在数据库目录的 `backups/` 中自动生成 v6 迁移备份；生产部署前仍需额外做完整数据备份。
- 上传页面只有在 PDF 字节传完前需要保持打开；传完后后台任务与浏览器解耦。
- 不得清理 `storage/qr-codes/`。永久删除资料时，服务会连同对应二维码文件一起删除。
