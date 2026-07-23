const root = document.documentElement;
const compactHeader = document.querySelector("#compactHeader");
const compactHeaderSentinel = document.querySelector("#compactHeaderSentinel");
const primaryConnection = document.querySelector("#connection");
const compactConnection = document.querySelector(".compact-connection");
const primarySettingsButton = document.querySelector("#settingsOpen");
const compactSettingsButton = document.querySelector(".compact-settings-open");
const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");

let frameRequested = false;

function updateSeascape() {
  frameRequested = false;

  if (reducedMotion.matches) {
    root.style.setProperty("--sea-rise", "0px");
    root.style.setProperty("--depth-progress", "0");
    return;
  }

  const scrollTop = Math.max(0, window.scrollY || document.documentElement.scrollTop || 0);
  const maxScroll = Math.max(0, document.documentElement.scrollHeight - window.innerHeight);
  const progress = maxScroll > 0 ? Math.min(1, scrollTop / maxScroll) : 0;

  // 海面はスクロール量に比例して一定速度で上昇し、画面上端で停止する。
  const seaBasePixels = window.innerHeight * 0.4;
  const seaRise = Math.min(seaBasePixels, scrollTop * 0.42);

  root.style.setProperty("--sea-rise", `${seaRise.toFixed(2)}px`);
  root.style.setProperty("--depth-progress", progress.toFixed(4));
}

function requestSeascapeUpdate() {
  if (frameRequested) return;
  frameRequested = true;
  window.requestAnimationFrame(updateSeascape);
}

function setCompactHeaderVisible(visible) {
  if (!compactHeader) return;
  compactHeader.classList.toggle("visible", visible);
  compactHeader.setAttribute("aria-hidden", String(!visible));
}

function syncCompactConnection() {
  if (!primaryConnection || !compactConnection) return;
  compactConnection.className = primaryConnection.className.replace(/\bcompact-connection\b/g, "").trim() + " compact-connection";
  const primaryLabel = primaryConnection.querySelector("b")?.textContent || "CORE 接続確認中";
  const compactLabel = compactConnection.querySelector("b");
  if (compactLabel && compactLabel.textContent !== primaryLabel) compactLabel.textContent = primaryLabel;
}

if (compactHeader && compactHeaderSentinel && "IntersectionObserver" in window) {
  const observer = new IntersectionObserver(
    ([entry]) => setCompactHeaderVisible(!entry.isIntersecting),
    { threshold: 0 }
  );
  observer.observe(compactHeaderSentinel);
} else if (compactHeader) {
  const updateCompactFallback = () => {
    const boundary = compactHeaderSentinel?.getBoundingClientRect().bottom ?? 0;
    setCompactHeaderVisible(boundary < 0);
  };
  window.addEventListener("scroll", updateCompactFallback, { passive: true });
  window.addEventListener("resize", updateCompactFallback, { passive: true });
  updateCompactFallback();
}

if (primaryConnection && compactConnection && "MutationObserver" in window) {
  const connectionObserver = new MutationObserver(syncCompactConnection);
  connectionObserver.observe(primaryConnection, {
    attributes: true,
    attributeFilter: ["class"],
    childList: true,
    characterData: true,
    subtree: true,
  });
  syncCompactConnection();
}

compactSettingsButton?.addEventListener("click", () => primarySettingsButton?.click());

window.addEventListener("scroll", requestSeascapeUpdate, { passive: true });
window.addEventListener("resize", requestSeascapeUpdate, { passive: true });
window.addEventListener("load", requestSeascapeUpdate, { once: true });
reducedMotion.addEventListener?.("change", requestSeascapeUpdate);

requestSeascapeUpdate();
