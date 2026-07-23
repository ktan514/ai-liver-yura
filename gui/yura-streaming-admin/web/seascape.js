const root = document.documentElement;
const topbar = document.querySelector(".topbar");
let frameRequested = false;

function updateViewportState() {
  frameRequested = false;

  const documentHeight = Math.max(
    document.documentElement.scrollHeight,
    document.body.scrollHeight,
    window.innerHeight
  );
  root.style.setProperty("--seascape-height", documentHeight + "px");

  if (topbar) {
    topbar.classList.toggle("compact", window.scrollY > 72);
  }
}

function requestViewportUpdate() {
  if (frameRequested) return;
  frameRequested = true;
  window.requestAnimationFrame(updateViewportState);
}

window.addEventListener("scroll", requestViewportUpdate, { passive: true });
window.addEventListener("resize", requestViewportUpdate, { passive: true });
window.addEventListener("load", requestViewportUpdate, { once: true });

if (window.ResizeObserver) {
  const observer = new ResizeObserver(requestViewportUpdate);
  observer.observe(document.body);
}

requestViewportUpdate();
