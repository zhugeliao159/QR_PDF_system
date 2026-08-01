const batchLabels = {
  waiting_upload: "等待上传",
  pending: "等待后台处理",
  processing: "正在校验 PDF",
  waiting_preview: "正在生成预览",
  completed: "已更新",
  failed: "失败",
};

document.addEventListener("submit", (event) => {
  const form = event.target;
  if (form.matches("[data-reserved-upload]")) return;
  const message = form.dataset.confirm;
  if (message && !window.confirm(message)) {
    event.preventDefault();
    return;
  }
  if (form.matches("[data-submit-lock]")) {
    const button = form.querySelector("button[type='submit'], button:not([type])");
    if (button) {
      button.disabled = true;
      button.textContent = button.dataset.loadingText || "正在处理……";
    }
  }
});

async function refreshBatch(panel) {
  if (!panel?.dataset.batchStatusUrl) return;
  try {
    const response = await fetch(panel.dataset.batchStatusUrl, {
      credentials: "same-origin",
      cache: "no-store",
      headers: { Accept: "application/json" },
    });
    if (!response.ok) throw new Error("status request failed");
    const data = await response.json();
    const done = data.counts.completed + data.counts.failed;
    panel.querySelector("[data-batch-done]").textContent = done;
    panel.querySelector("[data-batch-total]").textContent = data.total_items;
    panel.querySelector("[data-batch-success]").textContent = data.counts.completed;
    panel.querySelector("[data-batch-failed]").textContent = data.counts.failed;
    data.items.forEach((item) => {
      const row = panel.querySelector(`[data-item-number="${item.item_number}"]`);
      if (!row) return;
      row.querySelector("[data-item-title]").textContent = item.resolved_title || item.original_filename.replace(/\.pdf$/i, "");
      row.querySelector("[data-item-status]").textContent = batchLabels[item.status] || item.status;
      const result = row.querySelector("[data-item-result]");
      if (result) result.textContent = item.error_message || (item.status === "completed" ? "内容已切换" : "—");
    });
    const message = panel.querySelector("[data-batch-message]");
    if (data.status === "completed") {
      message.textContent = `任务完成：成功 ${data.counts.completed} 份，失败 ${data.counts.failed} 份。`;
      return;
    }
    message.textContent = "服务器正在校验、生成预览并自动更新二维码内容……";
    window.setTimeout(() => refreshBatch(panel), 2000);
  } catch (_error) {
    const message = panel.querySelector("[data-batch-message]");
    if (message) message.textContent = "暂时无法刷新进度，正在重试……";
    window.setTimeout(() => refreshBatch(panel), 5000);
  }
}

document.querySelectorAll("[data-batch-status-url]").forEach((panel) => {
  window.setTimeout(() => refreshBatch(panel), 500);
});

function uploadOne(item, file, csrfToken, row) {
  return new Promise((resolve) => {
    const request = new XMLHttpRequest();
    const progress = row.querySelector("[data-item-progress]");
    request.open("POST", item.upload_url);
    request.responseType = "json";
    request.upload.addEventListener("progress", (event) => {
      if (event.lengthComputable) {
        progress.textContent = `${Math.round((event.loaded / event.total) * 100)}%`;
      }
    });
    request.addEventListener("load", () => {
      if (request.status >= 200 && request.status < 300) {
        progress.textContent = "上传完成";
        row.querySelector("[data-item-status]").textContent = batchLabels.pending;
        resolve(true);
      } else {
        const detail = request.response?.error?.message || request.response?.detail || "上传失败";
        progress.textContent = detail;
        row.querySelector("[data-item-status]").textContent = batchLabels.failed;
        resolve(false);
      }
    });
    request.addEventListener("error", () => {
      progress.textContent = "网络错误，请重新上传本批次";
      row.querySelector("[data-item-status]").textContent = batchLabels.failed;
      resolve(false);
    });
    const body = new FormData();
    body.append("csrf_token", csrfToken);
    body.append("file", file, file.name);
    request.send(body);
  });
}

const reservedUploadForm = document.querySelector("[data-reserved-upload]");
if (reservedUploadForm) {
  let transfersActive = false;
  window.addEventListener("beforeunload", (event) => {
    if (!transfersActive) return;
    event.preventDefault();
    event.returnValue = "";
  });
  reservedUploadForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const input = reservedUploadForm.querySelector("input[type='file']");
    const files = Array.from(input.files || []);
    if (!files.length) return;
    const button = reservedUploadForm.querySelector("button[type='submit']");
    button.disabled = true;
    button.textContent = "正在生成二维码……";
    try {
      const csrfToken = reservedUploadForm.querySelector("[name='csrf_token']").value;
      const response = await fetch(reservedUploadForm.dataset.reserveUrl, {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({
          csrf_token: csrfToken,
          files: files.map((file) => ({ filename: file.name, size: file.size })),
        }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error?.message || data.detail || "二维码生成失败");

      const panel = document.querySelector("[data-live-upload-panel]");
      panel.hidden = false;
      panel.dataset.batchStatusUrl = `${data.detail_url}/status`;
      panel.querySelector("[data-batch-total]").textContent = files.length;
      panel.querySelector("[data-batch-qr-zip]").href = data.qr_zip_url;
      const body = panel.querySelector("[data-batch-items]");
      body.replaceChildren();
      data.items.forEach((item) => {
        const row = document.createElement("tr");
        row.dataset.itemNumber = item.item_number;
        row.innerHTML = `<td>${item.item_number}</td><td data-item-title></td><td><a data-qr-link>下载二维码</a></td><td data-item-status>等待上传</td><td data-item-progress>0%</td>`;
        row.querySelector("[data-item-title]").textContent = item.name;
        row.querySelector("[data-qr-link]").href = item.qr_download_url;
        body.appendChild(row);
      });
      reservedUploadForm.hidden = true;
      history.replaceState({}, "", data.detail_url);
      transfersActive = true;
      const queue = data.items.map((item, index) => ({ item, file: files[index] }));
      const workers = Array.from({ length: Math.min(3, queue.length) }, async () => {
        while (queue.length) {
          const next = queue.shift();
          const row = panel.querySelector(`[data-item-number="${next.item.item_number}"]`);
          await uploadOne(next.item, next.file, csrfToken, row);
        }
      });
      await Promise.all(workers);
      transfersActive = false;
      panel.querySelector("[data-upload-message]").textContent = "文件传输已经结束，现在可以关闭本页；服务器会继续处理。";
      panel.setAttribute("data-batch-status-url", `${data.detail_url}/status`);
      window.setTimeout(() => refreshBatch(panel), 500);
    } catch (error) {
      window.alert(error.message || "上传任务创建失败");
      button.disabled = false;
      button.textContent = "生成二维码并开始上传";
    }
  });
}

const bulkDeleteForm = document.querySelector("[data-bulk-delete-form]");
if (bulkDeleteForm) {
  const boxes = Array.from(bulkDeleteForm.querySelectorAll("[data-material-checkbox]"));
  const all = bulkDeleteForm.querySelector("[data-select-all]");
  const count = bulkDeleteForm.querySelector("[data-selected-count]");
  const refreshSelection = () => {
    const selected = boxes.filter((box) => box.checked).length;
    count.textContent = `已选择 ${selected} 条`;
    all.checked = selected > 0 && selected === boxes.length;
    all.indeterminate = selected > 0 && selected < boxes.length;
  };
  all.addEventListener("change", () => {
    boxes.forEach((box) => { box.checked = all.checked; });
    refreshSelection();
  });
  boxes.forEach((box) => box.addEventListener("change", refreshSelection));
  bulkDeleteForm.addEventListener("submit", (event) => {
    if (!boxes.some((box) => box.checked)) {
      event.preventDefault();
      window.alert("请至少选择一条资料。");
    }
  });
  refreshSelection();
}
