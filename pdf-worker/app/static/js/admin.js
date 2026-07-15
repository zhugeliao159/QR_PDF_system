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
