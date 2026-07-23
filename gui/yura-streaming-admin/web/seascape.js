const root = document.documentElement;
const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
let frameRequested = false;

function seaBasePixels() {
  const value = getComputedStyle(root).getPropertyValue("--sea-base").trim();
  if (value.endsWith("vh")) return window.innerHeight * Number.parseFloat(value) / 100;
  if (value.endsWith("px")) return Number.parseFloat(value);
  return window.innerHeight * 0.52;
}

function updateSeaLevel() {
  frameRequested = false;
  if (reducedMotion.matches) {
    root.style.setProperty("--sea-rise", "0px");
    return;
  }

  const scrollable = Math.max(document.documentElement.scrollHeight - window.innerHeight, 1);
  const progress = Math.min(Math.max(window.scrollY / scrollable, 0), 1);
  const maximumRise = Math.max(seaBasePixels() - 8, 0);
  const eased = 1 - Math.pow(1 - progress, 1.35);
  root.style.setProperty("--sea-rise", `${Math.round(maximumRise * eased)}px`);
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
