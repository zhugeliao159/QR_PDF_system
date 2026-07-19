document.addEventListener("submit", (event) => {
  const form = event.target;
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

const search = document.querySelector("[data-material-search]");
if (search) {
  search.addEventListener("input", () => {
    const query = search.value.trim().toLowerCase();
    document.querySelectorAll("[data-material-text]").forEach((item) => {
      item.hidden = !item.dataset.materialText.toLowerCase().includes(query);
    });
  });
}

const contentForm = document.querySelector("[data-content-form]");
if (contentForm) {
  const refreshContentFields = () => {
    const selected = contentForm.querySelector("[data-content-choice]:checked")?.value || "pdf";
    contentForm.querySelectorAll("[data-content-panel]").forEach((panel) => {
      panel.hidden = panel.dataset.contentPanel === "external_url" ? selected !== "external_url" : selected === "external_url";
    });
    const prompt = contentForm.querySelector("[data-file-prompt]");
    const help = contentForm.querySelector("[data-file-help]");
    const file = contentForm.querySelector("[data-answer-file]");
    if (prompt) prompt.textContent = selected === "image" ? "选择 PNG、JPEG 或 WebP 图片" : "选择 PDF 文件";
    if (help) help.textContent = selected === "image" ? "图片会保持原比例并在学生页面中立即显示。" : "PDF 会在学生页面中立即尝试显示。";
    if (file) file.accept = selected === "image" ? "image/png,image/jpeg,image/webp" : "application/pdf";
  };
  contentForm.querySelectorAll("[data-content-choice]").forEach((choice) => choice.addEventListener("change", refreshContentFields));
  refreshContentFields();
}

const batchPanel = document.querySelector("[data-batch-status-url]");
if (batchPanel) {
  const labels = {
    pending: "等待处理",
    processing: "正在校验",
    waiting_preview: "正在生成预览",
    completed: "已发布",
    failed: "失败",
  };
  const refreshBatch = async () => {
    try {
      const response = await fetch(batchPanel.dataset.batchStatusUrl, {
        credentials: "same-origin",
        cache: "no-store",
        headers: { Accept: "application/json" },
      });
      if (!response.ok) throw new Error("status request failed");
      const data = await response.json();
      const done = data.counts.completed + data.counts.failed;
      batchPanel.querySelector("[data-batch-done]").textContent = done;
      batchPanel.querySelector("[data-batch-success]").textContent = data.counts.completed;
      batchPanel.querySelector("[data-batch-failed]").textContent = data.counts.failed;
      data.items.forEach((item) => {
        const row = batchPanel.querySelector(`[data-item-number="${item.item_number}"]`);
        if (!row) return;
        row.querySelector("[data-item-title]").textContent = item.resolved_title || item.original_filename.replace(/\.pdf$/i, "");
        row.querySelector("[data-item-status]").textContent = labels[item.status] || item.status;
        const result = row.querySelector("[data-item-result]");
        result.replaceChildren();
        if (item.qr_id) {
          const link = document.createElement("a");
          link.href = `/admin/materials/${encodeURIComponent(item.qr_id)}`;
          link.textContent = "查看资料";
          result.appendChild(link);
        } else {
          result.textContent = item.error_message || "—";
        }
      });
      const message = batchPanel.querySelector("[data-batch-message]");
      if (data.status === "completed") {
        message.textContent = `批量任务已完成：成功 ${data.counts.completed} 份，失败 ${data.counts.failed} 份。`;
        return;
      }
      message.textContent = "后台正在逐份校验、生成预览并发布……";
      window.setTimeout(refreshBatch, 2000);
    } catch (_error) {
      batchPanel.querySelector("[data-batch-message]").textContent = "暂时无法刷新进度，正在重试……";
      window.setTimeout(refreshBatch, 5000);
    }
  };
  window.setTimeout(refreshBatch, 500);
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
  const selectAll = (checked) => {
    boxes.forEach((box) => { box.checked = checked; });
    refreshSelection();
  };
  all.addEventListener("change", () => selectAll(all.checked));
  bulkDeleteForm.querySelector("[data-select-current-page]").addEventListener("click", () => selectAll(true));
  boxes.forEach((box) => box.addEventListener("change", refreshSelection));
  bulkDeleteForm.addEventListener("submit", (event) => {
    if (!boxes.some((box) => box.checked)) {
      event.preventDefault();
      window.alert("请至少选择一条资料。");
    }
  });
  refreshSelection();
}
