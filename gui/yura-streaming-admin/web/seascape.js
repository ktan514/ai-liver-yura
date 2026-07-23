const root = document.documentElement;
const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
const SEA_RISE_PER_SCROLL_PIXEL = 0.42;
let frameRequested = false;

function seaBasePixels() {
  const value = getComputedStyle(root).getPropertyValue("--sea-base").trim();
  if (value.endsWith("vh")) return window.innerHeight * Number.parseFloat(value) / 100;
  if (value.endsWith("px")) return Number.parseFloat(value);
  return window.innerHeight * 0.4;
}

function updateSeaLevel() {
  frameRequested = false;
  if (reducedMotion.matches) {
    root.style.setProperty("--sea-rise", "0px");
    return;
  }

  const maximumRise = Math.max(seaBasePixels() - 8, 0);
  const rise = Math.min(maximumRise, Math.max(window.scrollY, 0) * SEA_RISE_PER_SCROLL_PIXEL);
  root.style.setProperty("--sea-rise", `${Math.round(rise)}px`);
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
