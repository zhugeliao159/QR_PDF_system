(() => {
  const basePath = window.location.pathname.replace(/\/$/, "");
  const contentUrl = `${basePath}/content`;
  document.querySelectorAll("[data-content-link]").forEach((link) => {
    link.href = contentUrl;
  });
  document.querySelectorAll("[data-download-link]").forEach((link) => {
    link.href = `${contentUrl}?download=true`;
  });
  const viewer = document.querySelector("[data-student-content]");
  if (viewer) viewer.data = contentUrl;
  const image = document.querySelector("[data-student-image]");
  if (image) image.src = contentUrl;
})();
