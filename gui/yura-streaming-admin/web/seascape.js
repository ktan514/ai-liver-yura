const root = document.documentElement;
const topbar = document.querySelector(".topbar");
let frameRequested = false;
let expandedTopbarHeight = topbar ? topbar.offsetHeight : 0;

function updateViewportState() {
  frameRequested = false;

  const documentHeight = Math.max(
    document.documentElement.scrollHeight,
    document.body.scrollHeight,
    window.innerHeight
  );
  root.style.setProperty("--seascape-height", documentHeight + "px");

  if (topbar) {
    const shouldCompact = window.scrollY >= expandedTopbarHeight;
    topbar.classList.toggle("compact", shouldCompact);

    if (!shouldCompact) {
      expandedTopbarHeight = topbar.offsetHeight;
    }
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
  const bodyObserver = new ResizeObserver(requestViewportUpdate);
  bodyObserver.observe(document.body);

  if (topbar) {
    const headerObserver = new ResizeObserver(() => {
      if (!topbar.classList.contains("compact")) {
        expandedTopbarHeight = topbar.offsetHeight;
      }
      requestViewportUpdate();
    });
    headerObserver.observe(topbar);
  }
}

requestViewportUpdate();
