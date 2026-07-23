const canvas = document.querySelector("#field");
const ctx = canvas.getContext("2d", { alpha: false });
const messages = document.querySelector("#messages");
const shell = document.querySelector(".conversation-shell");
const emptyState = document.querySelector("#emptyState");
const composer = document.querySelector("#composer");
const input = document.querySelector("#messageInput");
const sendButton = document.querySelector("#sendButton");
const inputStatus = document.querySelector("#inputStatus");
const audioButton = document.querySelector("#audioButton");
const audioLabel = document.querySelector("#audioLabel");
const reduceMotion = matchMedia("(prefers-reduced-motion: reduce)").matches;

let audioContext = null;
let audioPermissionInitialized = false;
let audioEnabled = false;
let audioBusy = false;
let currentAudioSource = null;
let playbackCancelled = false;
const audioQueue = [];
const seenMessages = new Set();
const seenAudio = new Set();

function addMessage(message, animate = true) {
  if (!message?.id || seenMessages.has(message.id)) return;
  seenMessages.add(message.id);
  const node = document.querySelector("#messageTemplate").content.firstElementChild.cloneNode(true);
  node.classList.add(message.role === "user" ? "user" : "yura");
  if (!animate) node.style.animation = "none";
  node.querySelector(".speaker").textContent = message.role === "user" ? "YOU" : "YURA";
  const date = new Date(message.observed_at);
  node.querySelector("time").textContent = Number.isNaN(date.valueOf())
    ? "" : date.toLocaleTimeString("ja-JP", { hour: "2-digit", minute: "2-digit", hour12: false });
  node.querySelector("p").textContent = message.text;
  messages.append(node);
  emptyState.classList.add("hidden");
  requestAnimationFrame(() => shell.scrollTo({ top: shell.scrollHeight, behavior: animate ? "smooth" : "auto" }));
}

function updateAudioButton() {
  audioButton.classList.toggle("enabled", audioEnabled);
  audioButton.setAttribute("aria-pressed", String(audioEnabled));
  audioLabel.textContent = audioEnabled ? "音声 ON" : "音声 OFF";
}

async function enableAudio() {
  try {
    audioContext ||= new AudioContext();
    await audioContext.resume();
    const buffer = audioContext.createBuffer(1, 1, audioContext.sampleRate);
    const source = audioContext.createBufferSource();
    source.buffer = buffer;
    source.connect(audioContext.destination);
    source.start();
    audioPermissionInitialized = true;
    audioEnabled = true;
    playbackCancelled = false;
    updateAudioButton();
    drainAudioQueue();
  } catch (error) {
    console.error("音声を有効にできませんでした。", error);
    audioPermissionInitialized = true;
    audioEnabled = false;
    audioLabel.textContent = "音声を有効にできません";
  }
}

async function disableAudio() {
  audioPermissionInitialized = true;
  audioEnabled = false;
  playbackCancelled = true;

  if (currentAudioSource) {
    try {
      currentAudioSource.stop();
    } catch { /* すでに再生終了している場合は何もしない */ }
  }

  const pending = audioQueue.splice(0);
  await Promise.all(pending.map((item) => acknowledge(item.audio_id, "skipped", "audio_disabled")));

  if (audioContext?.state === "running") {
    await audioContext.suspend();
  }
  updateAudioButton();
}

async function toggleAudio() {
  if (audioEnabled) {
    await disableAudio();
  } else {
    await enableAudio();
  }
}

async function acknowledge(audioId, status, reason = "") {
  try {
    await fetch(`/api/audio/${audioId}/complete`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status, reason }),
    });
  } catch (error) {
    console.warn("音声再生結果を通知できませんでした。", { audioId, status, reason, error });
  }
}

async function drainAudioQueue() {
  if (audioBusy || !audioEnabled || audioQueue.length === 0) return;
  audioBusy = true;
  playbackCancelled = false;
  const item = audioQueue.shift();
  try {
    const response = await fetch(item.url, { cache: "no-store" });
    if (!response.ok) throw new Error(`audio fetch failed: ${response.status}`);
    const buffer = await audioContext.decodeAudioData(await response.arrayBuffer());
    if (!audioEnabled || playbackCancelled) {
      await acknowledge(item.audio_id, "skipped", "audio_disabled");
      return;
    }

    const source = audioContext.createBufferSource();
    currentAudioSource = source;
    source.buffer = buffer;
    source.connect(audioContext.destination);
    await new Promise((resolve) => {
      source.addEventListener("ended", resolve, { once: true });
      source.start();
    });

    if (!audioEnabled || playbackCancelled) {
      await acknowledge(item.audio_id, "skipped", "audio_disabled");
    } else {
      await acknowledge(item.audio_id, "completed");
    }
  } catch (error) {
    const disabled = !audioEnabled || playbackCancelled;
    console.error("ブラウザで音声を再生できませんでした。", { audioId: item.audio_id, error });
    await acknowledge(
      item.audio_id,
      disabled ? "skipped" : "failed",
      disabled ? "audio_disabled" : String(error?.message || error),
    );
  } finally {
    currentAudioSource = null;
    audioBusy = false;
    playbackCancelled = false;
    drainAudioQueue();
  }
}

async function queueAudio(event) {
  if (!event?.audio_id || seenAudio.has(event.audio_id)) return;
  seenAudio.add(event.audio_id);

  if (audioPermissionInitialized && !audioEnabled) {
    await acknowledge(event.audio_id, "skipped", "audio_disabled");
    return;
  }

  audioQueue.push(event);
  if (!audioPermissionInitialized) audioLabel.textContent = "音声を有効にする（待機中）";
  drainAudioQueue();
}

const stream = new EventSource("/events");
stream.addEventListener("open", () => {
  document.querySelector("#connection").classList.add("live");
  document.querySelector("#connectionText").textContent = "LOCAL LINK";
});
stream.addEventListener("snapshot", (event) => {
  const snapshot = JSON.parse(event.data);
  for (const message of snapshot.messages || []) addMessage(message, false);
  for (const audio of snapshot.audio || []) queueAudio(audio);
});
stream.addEventListener("message", (event) => addMessage(JSON.parse(event.data)));
stream.addEventListener("audio", (event) => queueAudio(JSON.parse(event.data)));
stream.onerror = () => {
  document.querySelector("#connection").classList.remove("live");
  document.querySelector("#connectionText").textContent = "再接続しています";
};

async function submitMessage() {
  const text = input.value.trim();
  if (!text || sendButton.disabled) return;
  if (!audioPermissionInitialized) enableAudio();
  sendButton.disabled = true;
  inputStatus.textContent = "送信しています…";
  try {
    const response = await fetch("/api/input", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });
    if (!response.ok) throw new Error("send failed");
    input.value = "";
    input.style.height = "auto";
    inputStatus.textContent = "ゆらに届きました";
  } catch {
    inputStatus.textContent = "送信できませんでした。接続を確認してください。";
  } finally {
    sendButton.disabled = false;
    input.focus();
  }
}

composer.addEventListener("submit", (event) => { event.preventDefault(); submitMessage(); });
input.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && event.ctrlKey && !event.isComposing) {
    event.preventDefault();
    submitMessage();
  }
});
input.addEventListener("input", () => {
  input.style.height = "auto";
  input.style.height = `${Math.min(input.scrollHeight, 130)}px`;
});
audioButton.addEventListener("click", toggleAudio);

let width = 0, height = 0, dpr = 1;
const motes = Array.from({ length: 120 }, () => ({ x: Math.random(), y: Math.random(), z: Math.random(), phase: Math.random() * 8 }));
const bubbles = [];
let nextBubbleAt = 0;
let previousFrameAt = 0;

function createBubble(now) {
  const radius = 1.2 + Math.random() * 3.6;
  bubbles.push({
    x: width * (.06 + Math.random() * .88),
    y: height + radius + Math.random() * 20,
    radius,
    speed: 13 + Math.random() * 25,
    sway: 4 + Math.random() * 13,
    phase: Math.random() * Math.PI * 2,
    bornAt: now,
    opacity: .16 + Math.random() * .25,
    vx: 0,
    vy: 0,
  });
}

function moteFlowAt(bubble, t) {
  let flowX = 0;
  let flowY = 0;
  let totalWeight = 0;
  const reach = Math.min(width, height) * .16;

  for (const mote of motes) {
    const moteX = mote.x * width + Math.sin(t * .16 + mote.phase) * 9;
    const moteY = mote.y * height;
    const dx = bubble.x - moteX;
    const dy = bubble.y - moteY;
    const distance = Math.hypot(dx, dy);
    if (!distance || distance >= reach) continue;
    const weight = (1 - distance / reach) ** 2 * (.3 + mote.z);
    const driftVelocity = Math.cos(t * .16 + mote.phase) * 1.44;
    flowX += (driftVelocity - dy / distance * 4) * weight;
    flowY += (dx / distance * 2.4) * weight;
    totalWeight += weight;
  }

  return totalWeight
    ? { x: flowX / totalWeight, y: flowY / totalWeight }
    : { x: 0, y: 0 };
}

function resize() {
  dpr = Math.min(devicePixelRatio || 1, 2); width = innerWidth; height = innerHeight;
  canvas.width = width * dpr; canvas.height = height * dpr; ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
}
function render(now) {
  const t = now / 1000;
  const frameSeconds = previousFrameAt ? Math.min((now - previousFrameAt) / 1000, .05) : 0;
  previousFrameAt = now;
  const bg = ctx.createRadialGradient(width * .5, height * .1, 0, width * .5, height * .28, Math.max(width, height) * .92);
  bg.addColorStop(0, "#142b43"); bg.addColorStop(.24, "#101b30"); bg.addColorStop(.58, "#070a14"); bg.addColorStop(1, "#020309");
  ctx.fillStyle = bg; ctx.fillRect(0, 0, width, height);

  const surfaceGlow = ctx.createLinearGradient(0, 0, 0, height * .28);
  surfaceGlow.addColorStop(0, "rgba(139, 220, 255, .09)");
  surfaceGlow.addColorStop(1, "rgba(139, 220, 255, 0)");
  ctx.fillStyle = surfaceGlow; ctx.fillRect(0, 0, width, height * .28);

  for (const mote of motes) {
    const drift = reduceMotion ? 0 : Math.sin(t * .16 + mote.phase) * 9;
    const alpha = .035 + mote.z * .11;
    ctx.fillStyle = `rgba(139, 220, 255, ${alpha})`;
    ctx.shadowColor = "rgba(139, 220, 255, .3)"; ctx.shadowBlur = 5;
    ctx.beginPath(); ctx.arc(mote.x * width + drift, mote.y * height, .35 + mote.z * 1.2, 0, Math.PI * 2); ctx.fill();
  }

  if (!reduceMotion && now >= nextBubbleAt) {
    createBubble(now);
    if (Math.random() < .2) createBubble(now);
    nextBubbleAt = now + 260 + Math.random() * 950;
  }

  ctx.shadowBlur = 0;
  for (let index = bubbles.length - 1; index >= 0; index -= 1) {
    const bubble = bubbles[index];
    const age = (now - bubble.bornAt) / 1000;
    const flow = moteFlowAt(bubble, t);
    const response = 1 - Math.exp(-frameSeconds * 1.8);
    bubble.vx += (flow.x - bubble.vx) * response;
    bubble.vy += (flow.y - bubble.vy) * response;
    bubble.x += bubble.vx * frameSeconds;
    bubble.y += (-bubble.speed + bubble.vy) * frameSeconds;
    const x = bubble.x + Math.sin(age * 1.3 + bubble.phase) * bubble.sway;
    const fade = Math.min(1, age * 2) * Math.min(1, (bubble.y + 30) / 90);
    ctx.strokeStyle = `rgba(179, 232, 255, ${bubble.opacity * Math.max(0, fade)})`;
    ctx.lineWidth = .65;
    ctx.beginPath(); ctx.arc(x, bubble.y, bubble.radius, 0, Math.PI * 2); ctx.stroke();
    ctx.fillStyle = `rgba(225, 248, 255, ${bubble.opacity * .55 * Math.max(0, fade)})`;
    ctx.beginPath();
    ctx.arc(x - bubble.radius * .35, bubble.y - bubble.radius * .35, Math.max(.4, bubble.radius * .18), 0, Math.PI * 2);
    ctx.fill();
    if (bubble.y < -bubble.radius - 8) bubbles.splice(index, 1);
  }
  requestAnimationFrame(render);
}
addEventListener("resize", resize);
resize(); input.focus(); requestAnimationFrame(render);
