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
