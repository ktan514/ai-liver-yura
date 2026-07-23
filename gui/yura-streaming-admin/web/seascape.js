const root = document.documentElement;
const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
let frameRequested = false;

function updateSeaLevel() {
  frameRequested = false;
  if (reducedMotion.matches) {
    root.style.setProperty("--sea-rise", "0px");
    return;
  }

  const scrollable = Math.max(document.documentElement.scrollHeight - window.innerHeight, 1);
  const progress = Math.min(Math.max(window.scrollY / scrollable, 0), 1);
  const rise = Math.round(Math.min(260, progress * 340));
  root.style.setProperty("--sea-rise", `${rise}px`);
}

function requestSeaLevelUpdate() {
  if (frameRequested) return;
  frameRequested = true;
  window.requestAnimationFrame(updateSeaLevel);
}

window.addEventListener("scroll", requestSeaLevelUpdate, { passive: true });
window.addEventListener("resize", requestSeaLevelUpdate, { passive: true });
reducedMotion.addEventListener?.("change", requestSeaLevelUpdate);
requestSeaLevelUpdate();
