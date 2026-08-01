# QRPDF 用户使用手册 / User Guide

[中文](#中文) | [English](#english)

## 中文

### 1. 访问管理后台

生产环境默认不把管理端口开放到公网。先在自己的电脑建立 SSH 隧道：

```bash
ssh -i /path/to/private_key -L 18081:127.0.0.1:18081 <server-user>@<server-host>
```

保持终端窗口运行，在浏览器打开：

```text
http://127.0.0.1:18081/admin
```

使用部署时生成的管理员账号和密码登录。不要把账号、密码或 SSH 私钥发给学生。

### 2. 上传一份或多份解析 PDF

1. 点击顶部“上传 PDF”。
2. 选择一份或多份 PDF。
3. 确认文件名。系统将 PDF 文件名去掉扩展名后作为资料名。
4. 点击“生成二维码并开始上传”。
5. 系统先为新资料预留永久二维码，然后逐个上传和处理文件。
6. 等待页面显示“文件传输已经结束”。之后可以关闭页面，后台 Worker 会继续校验、生成预览并发布。

上传规则：

- 只支持 PDF。
- 同名判断忽略 `.pdf` 扩展名大小写。
- 新名称会创建新资料和永久二维码。
- 已有名称会更新原资料，二维码保持不变。
- 替换失败时，学生继续看到上一次成功发布的内容。

批量页面可以单独下载二维码，也可以下载包含全部二维码 PNG 的 ZIP。二维码图片名与资料名一致。

### 3. 查看文件与二维码

点击“文件与二维码”可以搜索资料、查看状态、打开详情或下载二维码。

常见状态：

| 状态 | 含义 |
| --- | --- |
| 等待上传 | 二维码已经创建，但文件传输尚未完成 |
| 处理中 | 后台正在校验 PDF 或生成预览 |
| 已发布 | 学生扫码可查看当前内容 |
| 失败 | 新文件处理失败；若以前发布过内容，旧内容仍可使用 |
| 已停用 | 二维码暂时不可用，但资料没有被永久删除 |

资料处理完成前，扫码会显示“正在处理”；发布后同一个二维码会自动显示最新内容。

### 4. 给练习册添加二维码

1. 点击“添加到练习册”。
2. 选择已有资料。
3. 上传练习册 PDF。
4. 选择页码、位置、二维码大小和页边距。
5. 提交后检查预览。
6. 下载生成后的练习册 PDF。

系统统一使用资料的永久二维码。后续更新同名解析 PDF 时，不需要重新制作练习册。

### 5. 学生扫码体验

学生扫描二维码后进入 `/q/<token>`：

- 未处理完成时显示等待页面；
- 发布完成后显示逐页预览；
- 页面按需加载，并带有服务端生成的追踪水印；
- 学生端不提供原始 PDF 或下载按钮；
- 会话过期或请求过多时需要重新扫码。

水印和网页限制不能阻止所有截图、录屏或已接收内容的保存，不能把它们当作绝对 DRM。

### 6. 修改管理员密码和二级密码

点击顶部“安全设置”。

修改管理员登录密码：

1. 输入当前管理员密码。
2. 输入两次新密码。
3. 提交后所有旧后台会话失效。
4. 使用新密码重新登录。

修改永久删除二级密码：

- 尚未配置时，需要验证当前管理员密码；
- 已配置时，需要同时验证管理员密码和当前二级密码；
- 新二级密码不能与管理员密码相同。

两类新密码都至少需要 16 个字符。系统只保存 scrypt 哈希，不保存明文。

### 7. 停用与永久删除

停用是可恢复操作：二维码暂时不可访问，但资料和历史内容仍保留。

永久删除会移除资料、二维码、文件和预览，不能通过后台撤销。操作前请确认：

- 已有可用备份；
- 选择的是正确资料；
- 没有仍需使用的练习册或印刷二维码；
- 已取得永久删除二级密码。

永久删除时必须输入二级密码和指定确认文字。连续验证失败 5 次会锁定 15 分钟。

### 8. 常见问题

| 问题 | 处理方法 |
| --- | --- |
| 后台打不开 | 确认 SSH 隧道仍在运行，并检查 `http://127.0.0.1:18081/health` |
| 学生扫码打不开 | 检查域名 DNS、HTTPS 证书、Nginx 和 `student-public` 健康状态 |
| 微信提示域名或备案问题 | 这是域名/服务器合规和平台风控问题，不是 PDF 上传或二维码生成故障 |
| 新二维码显示处理中 | 在批量进度页查看上传、校验和预览状态，并检查 `preview-worker` 日志 |
| 同名上传没有新二维码 | 这是预期行为；同名文件更新原资料并复用永久二维码 |
| 忘记管理员密码 | 联系服务器维护人员按备份和恢复流程处理，网页不能绕过当前密码验证 |
| 永久删除被拒绝 | 检查二级密码、引用关系、处理中任务和 15 分钟锁定状态 |

---

## English

### 1. Open the admin application

The admin port should not be public. Create an SSH tunnel from your computer:

```bash
ssh -i /path/to/private_key -L 18081:127.0.0.1:18081 <server-user>@<server-host>
```

Keep the terminal open and browse to `http://127.0.0.1:18081/admin`. Sign in with the administrator credentials created during deployment.

### 2. Upload solution PDFs

1. Select **Upload PDF**.
2. Choose one or more PDF files.
3. The filename without `.pdf` becomes the resource name.
4. Select **Create QR codes and start upload**.
5. Wait until the browser confirms that file transfer has finished. Server-side validation and preview generation continue in the background.

A new name creates a new resource and permanent QR code. Uploading the same name updates the existing resource and keeps the QR code unchanged. A failed replacement does not remove the previous published content.

### 3. Manage resources and QR codes

Use **Files and QR Codes** to search resources, inspect processing status, open details, and download QR images. A newly reserved QR code shows a processing page until publication succeeds; the same QR code then begins serving the current content automatically.

### 4. Add a QR code to a workbook

Open **Add to Workbook**, select a resource, upload the workbook PDF, choose page/position/size/margin, review the result, and download the generated PDF. The permanent QR remains valid when the solution PDF is later replaced.

### 5. Student experience

Students enter `/q/<token>`. They see a processing page before publication and a paginated, watermarked preview afterward. The public application does not expose the original PDF or a download button. Session and rate limits may require a rescan. Watermarks are a deterrent, not absolute DRM.

### 6. Passwords

Open **Security Settings** to change the administrator password or the permanent-deletion password. New passwords require at least 16 characters. Changing the administrator password invalidates all existing admin sessions. If a deletion password already exists, both the current admin password and current deletion password are required.

### 7. Disable or permanently delete

Disabling is reversible. Permanent deletion removes the resource, QR code, files, and previews and cannot be undone from the UI. Confirm a valid backup first. Five failed secondary-password attempts trigger a 15-minute lockout.

### 8. Troubleshooting

- Admin unavailable: verify the SSH tunnel and the loopback health endpoint.
- Student QR unavailable: verify DNS, TLS, Nginx, and `student-public` health.
- QR still processing: inspect the batch page and `preview-worker` logs.
- No new QR after same-name upload: expected; permanent QR reuse is the core behavior.
- Forgotten admin password: a server maintainer must use the documented recovery procedure; the web UI cannot bypass current-password verification.
