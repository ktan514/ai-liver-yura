const canvas = document.querySelector("#field");
const ctx = canvas.getContext("2d", { alpha: false });
const reduceMotion = matchMedia("(prefers-reduced-motion: reduce)").matches;
const helpDialog = document.querySelector("#helpDialog");

document.querySelector("#helpButton").addEventListener("click", () => helpDialog.showModal());
document.querySelector("#helpClose").addEventListener("click", () => helpDialog.close());
helpDialog.addEventListener("click", (event) => {
  if (event.target === helpDialog) helpDialog.close();
});

const state = {
  emotion: { mood: "unknown", arousal: 0, valence: 0, talkativeness: 0 },
  drive: { curiosity: 0, engagement: 0, boredom: 0, energy: 0 },
  activity: { type: null, active: false },
  attention: { engaged: false },
  observed_at: null,
};

const display = structuredClone(state);
let width = 0;
let height = 0;
let dpr = 1;
let lastFrame = performance.now();
let lastStateAt = 0;
let sourceAvailable = false;
let streamConnected = false;
let signalPresence = 0;
let nextBubbleAt = 0;
const bubbles = [];
const STATE_TIMEOUT_MS = 3000;

const particles = Array.from({ length: 820 }, (_, index) => {
  const golden = Math.PI * (3 - Math.sqrt(5));
  const y = 1 - (index / 819) * 2;
  const radius = Math.sqrt(1 - y * y);
  const theta = golden * index;
  return {
    x: Math.cos(theta) * radius,
    y,
    z: Math.sin(theta) * radius,
    seed: Math.random() * Math.PI * 2,
    weight: 0.35 + Math.random() * 0.9,
    scatterAngle: Math.random() * Math.PI * 2,
    scatterSpeed: .72 + Math.random() * .55,
  };
});

const dust = Array.from({ length: 150 }, () => ({
  x: Math.random(), y: Math.random(), z: Math.random(), phase: Math.random() * 9,
}));

const palettes = {
  neutral: [202, 84, 72],
  happy: [42, 92, 72],
  excited: [326, 88, 70],
  angry: [7, 92, 64],
  sad: [224, 76, 67],
  tired: [267, 46, 64],
};

const moodLabels = {
  unknown: "不明な状態",
  neutral: "静かなゆらぎ", happy: "ひらく光", excited: "弾むきらめき",
  angry: "鋭い熱", sad: "沈む青", tired: "ほどける輪郭",
};

function resize() {
  dpr = Math.min(devicePixelRatio || 1, 2);
  width = innerWidth;
  height = innerHeight;
  canvas.width = Math.floor(width * dpr);
  canvas.height = Math.floor(height * dpr);
  canvas.style.width = `${width}px`;
  canvas.style.height = `${height}px`;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
}

function mix(current, target, rate) { return current + (target - current) * rate; }
function clamp(value, min = 0, max = 1) { return Math.max(min, Math.min(max, value)); }

function smoothState(dt) {
  const rate = 1 - Math.exp(-dt * 2.2);
  for (const group of ["emotion", "drive"]) {
    for (const [key, value] of Object.entries(state[group])) {
      if (typeof value === "number") display[group][key] = mix(display[group][key], value, rate);
      else display[group][key] = value;
    }
  }
  display.activity = state.activity;
  display.attention = state.attention;
}

function palette() {
  const base = palettes[display.emotion.mood] || palettes.neutral;
  const emotionalHue = display.emotion.valence < 0
    ? 222 + display.emotion.valence * -20
    : 198 - display.emotion.valence * 156;
  return [mix(emotionalHue, base[0], 0.48), base[1], base[2]];
}

function rotate(point, ax, ay) {
  const cy = Math.cos(ay), sy = Math.sin(ay);
  const cx = Math.cos(ax), sx = Math.sin(ax);
  const x = point.x * cy - point.z * sy;
  const z1 = point.x * sy + point.z * cy;
  return { x, y: point.y * cx - z1 * sx, z: point.y * sx + z1 * cx };
}

function createBubble(now) {
  const radius = 1.8 + Math.random() * 4.7;
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
    tilt: (Math.random() - .5) * .38,
    stretch: 1.08 + Math.random() * .42,
    shape: Array.from({ length: 8 }, () => .78 + Math.random() * .38),
  });
}

function particleFlowAt(bubble, projected, reach, centerX, centerY, baseRadius, rotationForce) {
  let flowX = 0;
  let flowY = 0;
  let totalWeight = 0;

  for (const particle of projected) {
    const distance = Math.hypot(bubble.x - particle.x, bubble.y - particle.y);
    if (distance >= reach) continue;
    const weight = (1 - distance / reach) ** 2 * particle.alpha;
    flowX += particle.vx * weight;
    flowY += particle.vy * weight;
    totalWeight += weight;
  }

  if (totalWeight) {
    flowX /= totalWeight;
    flowY /= totalWeight;
  }

  const dx = bubble.x - centerX;
  const dy = bubble.y - centerY;
  const centerDistance = Math.hypot(dx, dy);
  const coreInfluence = clamp(1 - centerDistance / (baseRadius * 1.65));
  if (centerDistance && coreInfluence) {
    // The projected velocities cancel when opposite sides of the sphere overlap.
    // Preserve the visible rotational current as a tangential force around the core.
    flowX += -dy / centerDistance * rotationForce * coreInfluence;
    flowY += dx / centerDistance * rotationForce * coreInfluence * .58;
  }

  return {
    x: flowX,
    y: flowY,
    influence: Math.max(coreInfluence, Math.min(1, totalWeight * .5)),
  };
}

function traceBubble(bubble, age) {
  const points = bubble.shape.map((shape, index) => {
    const angle = index / bubble.shape.length * Math.PI * 2;
    const wobble = shape + Math.sin(age * 1.8 + bubble.phase + index * 1.7) * .055;
    return {
      x: Math.cos(angle) * bubble.radius * wobble,
      y: Math.sin(angle) * bubble.radius * bubble.stretch * wobble,
    };
  });
  ctx.beginPath();
  for (let index = 0; index < points.length; index += 1) {
    const point = points[index];
    const next = points[(index + 1) % points.length];
    const midX = (point.x + next.x) * .5;
    const midY = (point.y + next.y) * .5;
    if (index === 0) ctx.moveTo(midX, midY);
    ctx.quadraticCurveTo(next.x, next.y, midX, midY);
  }
  ctx.closePath();
}

function drawBubble(bubble, x, age, alpha, hue, saturation) {
  ctx.save();
  ctx.translate(x, bubble.y);
  ctx.rotate(bubble.tilt + Math.sin(age * .7 + bubble.phase) * .08);
  traceBubble(bubble, age);
  ctx.fillStyle = `hsla(${hue}, ${Math.min(76, saturation)}%, 78%, ${alpha * .1})`;
  ctx.fill();
  ctx.strokeStyle = `hsla(${hue}, ${Math.min(82, saturation)}%, 86%, ${alpha * .72})`;
  ctx.lineWidth = .7;
  ctx.stroke();

  ctx.beginPath();
  ctx.moveTo(-bubble.radius * .55, -bubble.radius * .08);
  ctx.quadraticCurveTo(
    -bubble.radius * .42,
    -bubble.radius * bubble.stretch * .68,
    bubble.radius * .12,
    -bubble.radius * bubble.stretch * .72,
  );
  ctx.strokeStyle = `hsla(${hue}, ${Math.min(88, saturation)}%, 96%, ${alpha * 1.35})`;
  ctx.lineWidth = Math.max(.75, bubble.radius * .16);
  ctx.lineCap = "round";
  ctx.stroke();
  ctx.restore();
}

function renderBubbles(now, dt, projected, baseRadius, centerX, centerY, rotationForce, hue, saturation) {
  if (sourceAvailable && !reduceMotion && now >= nextBubbleAt) {
    createBubble(now);
    if (Math.random() < .2) createBubble(now);
    nextBubbleAt = now + 260 + Math.random() * 950;
  }

  const t = now / 1000;
  const reach = Math.max(30, baseRadius * .26);
  ctx.shadowBlur = 0;
  for (let index = bubbles.length - 1; index >= 0; index -= 1) {
    const bubble = bubbles[index];
    const age = (now - bubble.bornAt) / 1000;
    const flow = particleFlowAt(bubble, projected, reach, centerX, centerY, baseRadius, rotationForce);
    const response = 1 - Math.exp(-dt * (1.5 + flow.influence * 3));
    const ambient = Math.sin(t * .32 + bubble.phase) * 2.2;
    bubble.vx += (ambient + flow.x * .7 - bubble.vx) * response;
    bubble.vy += (flow.y * .45 - bubble.vy) * response;
    bubble.x += bubble.vx * dt;
    bubble.y += (-bubble.speed + bubble.vy) * dt;
    const x = bubble.x + Math.sin(age * 1.3 + bubble.phase) * bubble.sway;
    const fade = Math.min(1, age * 2) * Math.min(1, (bubble.y + 30) / 90);
    const alpha = bubble.opacity * Math.max(0, fade);

    drawBubble(bubble, x, age, alpha, hue, saturation);
    if (bubble.y < -bubble.radius - 8) bubbles.splice(index, 1);
  }
}

function render(now) {
  const dt = Math.min((now - lastFrame) / 1000, 0.05);
  lastFrame = now;
  if (sourceAvailable && now - lastStateAt > STATE_TIMEOUT_MS) {
    markUnavailable(streamConnected ? "ゆらを待っています" : "再接続しています");
  }
  const presenceRate = 1 - Math.exp(-dt * (sourceAvailable ? 1.8 : .72));
  signalPresence += ((sourceAvailable ? 1 : 0) - signalPresence) * presenceRate;
  smoothState(dt);
  const t = now / 1000;
  const [hue, saturation, lightness] = palette();
  document.documentElement.style.setProperty("--accent", `hsl(${hue} ${saturation}% ${lightness}%)`);
  document.documentElement.style.setProperty("--accent-soft", `hsla(${hue} ${saturation}% ${lightness}% / .2)`);

  const bg = ctx.createRadialGradient(width * .5, height * .48, 0, width * .5, height * .48, Math.max(width, height) * .72);
  bg.addColorStop(0, `hsla(${hue}, 42%, 10%, .96)`);
  bg.addColorStop(.45, "#070a14");
  bg.addColorStop(1, "#020309");
  ctx.fillStyle = bg;
  ctx.fillRect(0, 0, width, height);

  const surfaceGlow = ctx.createLinearGradient(0, 0, 0, height * .28);
  surfaceGlow.addColorStop(0, `hsla(${hue}, 72%, 72%, .07)`);
  surfaceGlow.addColorStop(1, `hsla(${hue}, 72%, 72%, 0)`);
  ctx.fillStyle = surfaceGlow;
  ctx.fillRect(0, 0, width, height * .28);

  for (const mote of dust) {
    const alpha = .05 + .08 * (Math.sin(t * .25 + mote.phase) + 1);
    ctx.fillStyle = `hsla(${hue}, 70%, 76%, ${alpha})`;
    ctx.fillRect(mote.x * width, mote.y * height, mote.z * 1.5 + .25, mote.z * 1.5 + .25);
  }

  const arousal = display.emotion.arousal;
  const energy = display.drive.energy;
  const curiosity = display.drive.curiosity;
  const engagement = display.drive.engagement;
  const boredom = display.drive.boredom;
  const talking = display.emotion.talkativeness;
  const baseRadius = Math.min(width, height) * (.18 + curiosity * .09 + energy * .025);
  const speed = reduceMotion ? .025 : .045 + arousal * .23;
  const rotationY = t * speed;
  const rotationX = Math.sin(t * .12) * (.08 + arousal * .08);
  const flatten = 1 - boredom * .24;
  const pulse = 1 + Math.sin(t * (0.6 + arousal * 2.4)) * (.008 + arousal * .022);
  const centerX = width * .5;
  const centerY = height * .49;

  const projected = particles.map((particle) => {
    const wave = Math.sin(t * (0.35 + arousal * 1.4) + particle.seed + particle.y * 4.5);
    const curl = Math.cos(t * .42 + particle.seed * 1.7 + particle.z * 5);
    const looseness = (1 - engagement) * .14 + boredom * .08;
    const radial = pulse * (1 + wave * (.016 + arousal * .05) + looseness * curl);
    const source = {
      x: particle.x * radial,
      y: particle.y * radial * flatten,
      z: particle.z * radial,
    };
    const p = rotate(source, rotationX, rotationY + particle.seed * talking * .015);
    const perspective = 1 / (2.7 - p.z * .75);
    const dispersion = (1 - signalPresence) ** 1.35;
    const scatterDistance = Math.max(width, height) * 1.15 * particle.scatterSpeed * dispersion;
    const x = centerX + p.x * baseRadius * perspective * 2.2
      + Math.cos(particle.scatterAngle) * scatterDistance;
    const y = centerY + p.y * baseRadius * perspective * 2.2
      + Math.sin(particle.scatterAngle) * scatterDistance;
    const vx = dt && particle.screenX !== undefined ? (x - particle.screenX) / dt : 0;
    const vy = dt && particle.screenY !== undefined ? (y - particle.screenY) / dt : 0;
    particle.screenX = x;
    particle.screenY = y;
    return {
      x,
      y,
      vx: clamp(vx, -180, 180),
      vy: clamp(vy, -180, 180),
      z: p.z,
      size: (.55 + perspective * 1.8) * particle.weight * (.75 + energy * .7),
      alpha: clamp(.12 + perspective * .48 + p.z * .1) * clamp(signalPresence * 1.6),
    };
  }).sort((a, b) => a.z - b.z);

  ctx.globalCompositeOperation = "lighter";
  for (const p of projected) {
    ctx.beginPath();
    ctx.fillStyle = `hsla(${hue + p.z * 18}, ${saturation}%, ${lightness + p.z * 8}%, ${p.alpha})`;
    ctx.shadowColor = `hsla(${hue}, ${saturation}%, ${lightness}%, .65)`;
    ctx.shadowBlur = 4 + arousal * 9;
    ctx.arc(p.x, p.y, p.size, 0, Math.PI * 2);
    ctx.fill();
  }

  const halo = ctx.createRadialGradient(centerX, centerY, 0, centerX, centerY, baseRadius * 1.55);
  halo.addColorStop(0, `hsla(${hue}, ${saturation}%, 72%, ${(0.075 + energy * .06) * signalPresence})`);
  halo.addColorStop(.35, `hsla(${hue}, ${saturation}%, 50%, ${(0.035 + engagement * .045) * signalPresence})`);
  halo.addColorStop(1, "transparent");
  ctx.fillStyle = halo;
  ctx.fillRect(centerX - baseRadius * 1.6, centerY - baseRadius * 1.6, baseRadius * 3.2, baseRadius * 3.2);
  ctx.globalCompositeOperation = "source-over";

  const rotationForce = (28 + arousal * 88 + talking * 18) * signalPresence;
  renderBubbles(now, dt, projected, baseRadius, centerX, centerY, rotationForce, hue, saturation);

  updateLabels();
  requestAnimationFrame(render);
}

function updateMetric(id, value, signed = false) {
  const node = document.querySelector(`#${id}`);
  node.textContent = `${sourceAvailable && value >= 0 && signed ? "+" : ""}${value.toFixed(2)}`;
  const normalized = sourceAvailable ? (signed ? (value + 1) / 2 : value) : 0;
  node.parentElement.querySelector("i").style.setProperty("--level", `${clamp(normalized) * 100}%`);
}

function updateLabels() {
  updateMetric("valence", display.emotion.valence, true);
  updateMetric("arousal", display.emotion.arousal);
  updateMetric("talkativeness", display.emotion.talkativeness);
  updateMetric("curiosity", display.drive.curiosity);
  updateMetric("energy", display.drive.energy);
  document.querySelector("#moodLabel").textContent = moodLabels[display.emotion.mood] || display.emotion.mood;
  const activity = display.activity?.type || (sourceAvailable ? "IDLE" : "UNKNOWN");
  document.querySelector("#activity").textContent = activity.replaceAll("_", " ").toUpperCase();
}

function markUnavailable(connectionText) {
  sourceAvailable = false;
  Object.assign(state.emotion, { mood: "unknown", arousal: 0, valence: 0, talkativeness: 0 });
  Object.assign(state.drive, { curiosity: 0, engagement: 0, boredom: 0, energy: 0 });
  Object.assign(display.emotion, state.emotion);
  Object.assign(display.drive, state.drive);
  state.activity = { type: null, active: false };
  state.attention = { engaged: false };
  display.activity = state.activity;
  display.attention = state.attention;
  document.querySelector("#connection").classList.remove("live");
  document.querySelector("#connectionText").textContent = connectionText;
  document.querySelector("#observedAt").textContent = "--:--:--";
}

function receive(next) {
  if (!next?.emotion || !next?.drive) return;
  Object.assign(state.emotion, next.emotion);
  Object.assign(state.drive, next.drive);
  state.activity = next.activity || state.activity;
  state.attention = next.attention || state.attention;
  state.observed_at = next.observed_at;
  lastStateAt = performance.now();
  sourceAvailable = true;
  const connection = document.querySelector("#connection");
  connection.classList.add("live");
  document.querySelector("#connectionText").textContent = "LIVE STATE";
  const date = new Date(next.observed_at);
  document.querySelector("#observedAt").textContent = Number.isNaN(date.valueOf())
    ? "--:--:--" : date.toLocaleTimeString("ja-JP", { hour12: false });
}

const stream = new EventSource("/events");
stream.addEventListener("open", () => {
  streamConnected = true;
  if (!sourceAvailable) document.querySelector("#connectionText").textContent = "ゆらを待っています";
});
stream.addEventListener("state", (event) => receive(JSON.parse(event.data)));
stream.onerror = () => {
  streamConnected = false;
  markUnavailable("再接続しています");
};

addEventListener("resize", resize);
resize();
requestAnimationFrame(render);
