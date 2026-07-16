(() => {
  const status = document.querySelector("[data-loading-status]");
  const images = Array.from(document.querySelectorAll(".preview-image"));

  const loadImage = (image) => {
    if (!image.src && image.dataset.src) {
      image.src = image.dataset.src;
    }
  };

  const markLoaded = (image) => {
    image.closest(".preview-frame")?.classList.add("is-loaded");
    image.closest(".preview-frame")?.querySelector(".page-error")?.setAttribute("hidden", "");
    if (status && image === images[0]) status.textContent = "第一页已显示，可向下滚动查看后续页面。";
  };

  const markFailed = (image) => {
    image.closest(".preview-frame")?.querySelector(".page-error")?.removeAttribute("hidden");
    if (status && image === images[0]) status.textContent = "第一页加载失败，请重试。";
  };

  images.forEach((image) => {
    image.addEventListener("load", () => markLoaded(image));
    image.addEventListener("error", () => markFailed(image));
    image.addEventListener("dragstart", (event) => event.preventDefault());
    image.addEventListener("contextmenu", (event) => event.preventDefault());
    if (image.complete && image.naturalWidth > 0) markLoaded(image);
  });

  document.querySelectorAll("[data-retry-page]").forEach((button) => {
    button.addEventListener("click", () => {
      const image = button.closest(".preview-frame")?.querySelector(".preview-image");
      if (!image) return;
      button.closest(".page-error")?.setAttribute("hidden", "");
      const target = image.dataset.src || image.src;
      image.removeAttribute("src");
      window.setTimeout(() => { image.src = target; }, 50);
    });
  });

  const deferred = images.filter((image) => image.dataset.src);
  if ("IntersectionObserver" in window) {
    const observer = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        loadImage(entry.target);
        observer.unobserve(entry.target);
      });
    }, { rootMargin: "600px 0px" });
    deferred.forEach((image) => observer.observe(image));
  } else {
    deferred.forEach(loadImage);
  }
})();
