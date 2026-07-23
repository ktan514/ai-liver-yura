// Standalone browser client for the Yura streaming control surface.
const state = { data: {}, diagnostics: [], loading: false, pending: false, timerKey: "", timers: [] };
const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];
const text = (value, fallback = "—") => value === null || value === undefined || value === "" ? fallback : String(value);
const esc = (value) => text(value).replace(/[&<>"']/g, (c) => ({ "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;" })[c]);

async function request(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.error?.message || `HTTP ${response.status}`);
  return payload;
}

function table(rows, columns) {
  if (!Array.isArray(rows) || !rows.length) return '<p class="empty">データはありません。</p>';
  return `<table><thead><tr>${columns.map(([, label]) => `<th>${label}</th>`).join("")}</tr></thead><tbody>${rows.map((row) =>
    `<tr>${columns.map(([key]) => `<td>${esc(row?.[key])}</td>`).join("")}</tr>`).join("")}</tbody></table>`;
}

function setOptions(element, items, valueKey, labelKey) {
  const selected = element.value;
  element.innerHTML = (items || []).map((item) => `<option value="${esc(item[valueKey])}">${esc(item[labelKey] || item.display_label || item.title || item[valueKey])}</option>`).join("");
  if ([...element.options].some((option) => option.value === selected)) element.value = selected;
}

function render() {
  const data = state.data, health = data.health || {}, consoleData = data.console || {};
  const session = data.session || {}, auth = data.auth || {}, modes = health.adapter_modes || session.adapter_modes || {};
  $("#currentState").textContent = text(consoleData.current_state || session.status, "待機中");
  $("#currentMessage").textContent = text(consoleData.current_message, "次の操作を選択してください。");
  $("#modeBadge").textContent = `${text(modes.youtube, "UNKNOWN").toUpperCase()} YOUTUBE / ${text(modes.obs, "UNKNOWN").toUpperCase()} OBS`;
  setOptions($("#broadcastSelect"), (data.broadcasts || []).filter((item) => item.selectable !== false), "broadcast_id", "display_label");
  setOptions($("#runOfShowSelect"), data.run_of_shows, "run_of_show_id", "title");

  const services = consoleData.services || [
    { name: "Core", status: health.status || "unknown", freshness: "unknown" },
    { name: "OBS", status: session.obs_status || "unknown", freshness: "unknown" },
    { name: "YouTube", status: auth.status || "unknown", freshness: "unknown" },
    { name: "配信進行", status: session.status || "idle", freshness: "unknown" },
  ];
  $("#serviceCards").innerHTML = services.map((item) => `<div class="service-card"><p class="label">${esc(item.name)}</p><div class="status">${esc(item.status)}</div><dl><dt>更新方式</dt><dd>${esc(item.update_mode)}</dd><dt>鮮度</dt><dd>${esc(item.freshness)}</dd><dt>最終更新</dt><dd>${esc(item.last_updated_at)}</dd></dl></div>`).join("");

  const operator = consoleData.operator_action || {};
  $("#operatorTitle").textContent = text(operator.title, "現在、必要な人間操作はありません。");
  $("#operatorDescription").textContent = text(operator.description, "");
  $("#studioLink").classList.toggle("hidden", !operator.studio_url);
  if (operator.studio_url) $("#studioLink").href = operator.studio_url;
  $("#responsibilities").innerHTML = table(consoleData.responsibilities, [["operation","操作"],["owner","担当"],["status","状態"]]);
  $("#steps").innerHTML = table(consoleData.lifecycle_steps, [["title","工程"],["status","状態"],["owner","担当"],["block_reason","ブロック理由"],["error_code","失敗理由"]]);

  const comments = data.comments || {}, moderation = data.moderation || {}, ranking = data.ranking || {}, response = data.comment_response || {};
  $("#commentMetrics").innerHTML = [
    ["ポーラー", comments.status], ["受信数", comments.received_count ?? comments.total_count],
    ["モデレーション", moderation.status], ["応答", response.status],
  ].map(([label, value]) => `<div class="metric"><span class="label">${label}</span><strong>${esc(value)}</strong></div>`).join("");
  const commentRows = [...(moderation.recent || moderation.queue || []), ...(ranking.top || [])].map((row) => ({
    ...row,
    author: row.author_display_name || row.author || row.author_name,
    comment: row.sanitized_text || row.text || row.comment,
    score: row.total_score ?? row.priority ?? row.score,
  }));
  $("#commentTable").innerHTML = table(commentRows, [["author","投稿者"],["comment","コメント"],["status","状態"],["score","スコア"]]);

  renderTimeline(consoleData.timeline || []);
  $("#diagnosticTable").innerHTML = table(state.diagnostics, [["observed_at","時刻"],["category","分類"],["event_name","イベント"],["result","結果"],["error_code","エラー"]]);
  applyButtonState(auth, session, health);
  configureTimers(consoleData.log_settings || {});
}

function renderTimeline(rows) {
  const filter = $("#timelineFilter").value;
  const filtered = filter === "all" ? rows : rows.filter((row) => row.category === filter);
  $("#timeline").innerHTML = filtered.length ? filtered.slice().reverse().map((row) =>
    `<div class="timeline-row ${row.result === "failed" ? "failed" : ""}"><time>${esc(row.observed_at)}</time><span class="category">${esc(row.category)}</span><span>${esc(row.event_name || row.message)}</span><span class="result">${esc(row.result)}</span></div>`
  ).join("") : '<p class="empty">イベントはありません。</p>';
}

function applyButtonState(auth, session, health) {
  const status = session.status, demo = health.runtime_mode === "streaming_demo";
  const modes = session.adapter_modes || health.adapter_modes || {};
  const realObs = modes.obs === "obs_websocket";
  const canStart = status === "ready" && (demo || realObs);
  const enabled = {
    authenticate: !["authenticated", "authentication_in_progress"].includes(auth.status),
    prepare: auth.status === "authenticated",
    start: canStart,
    end: ["live", "running"].includes(status),
    "emergency-stop": ["live", "running", "starting", "ending"].includes(status),
    "retry-opening": state.data.opening?.status === "failed" && state.data.opening?.retryable !== false,
    "retry-main": state.data.main_segment?.status === "failed" && Boolean(state.data.main_segment?.retryable),
    "retry-comment": Boolean(state.data.comment_response?.activity?.retryable),
  };
  $$("[data-action]").forEach((button) => {
    if (button.dataset.action in enabled) button.disabled = !enabled[button.dataset.action];
  });
  $("#demoForm").hidden = !demo;
}

async function load() {
  if (state.loading) {
    state.pending = true;
    return;
  }
  state.loading = true;
  try {
    state.data = await request("/api/bootstrap");
    setConnection(true);
    render();
  } catch (error) {
    setConnection(false);
    showNotice(error.message);
  } finally {
    state.loading = false;
    if (state.pending) {
      state.pending = false;
      queueMicrotask(load);
    }
  }
}

function configureTimers(settings) {
  const key = JSON.stringify([
    settings.obs_auto_refresh, settings.obs_refresh_interval,
    settings.youtube_auto_refresh, settings.youtube_refresh_interval,
  ]);
  if (key === state.timerKey) return;
  state.timerKey = key;
  state.timers.forEach(clearInterval);
  state.timers = [];
  if (settings.obs_auto_refresh) state.timers.push(setInterval(() => runAction("refresh-obs", true), Number(settings.obs_refresh_interval || 30) * 1000));
  if (settings.youtube_auto_refresh) state.timers.push(setInterval(() => runAction("refresh-youtube", true), Number(settings.youtube_refresh_interval || 30) * 1000));
}

function setConnection(online) {
  const node = $("#connection");
  node.className = `connection ${online ? "online" : "offline"}`;
  node.querySelector("b").textContent = online ? "CORE ONLINE" : "CORE OFFLINE";
}
function showNotice(message, success = false) {
  $("#notice").textContent = message;
  $("#notice").style.color = success ? "#64e0a1" : "";
}

async function runAction(name, quiet = false) {
  const session = state.data.session || {};
  const activity = name === "retry-opening" ? state.data.opening || {} :
    name === "retry-main" ? state.data.main_segment || {} :
    state.data.comment_response?.activity || {};
  const payload = {
    session_id: session.session_id, state_version: session.state_version,
    broadcast_id: $("#broadcastSelect").value, run_of_show_id: $("#runOfShowSelect").value,
    activity_id: activity.activity_id, activity_version: activity.version,
    selection_id: activity.selection_id,
  };
  if (name === "emergency-stop" && !confirm("配信を緊急停止します。この操作を実行しますか？")) return;
  if (name === "start" && !confirm("配信開始を承認しますか？")) return;
  if (name === "end" && !confirm("配信を通常終了しますか？")) return;
  try {
    if (!quiet) showNotice("操作を実行しています…");
    await request(`/api/actions/${name}`, { method: "POST", body: JSON.stringify(payload) });
    if (!quiet) showNotice("操作を受け付けました。", true);
    await load();
  } catch (error) { if (!quiet) showNotice(error.message); }
}

$$(".tabs button").forEach((button) => button.addEventListener("click", () => {
  $$(".tabs button").forEach((item) => item.classList.toggle("active", item === button));
  $$(".panel").forEach((panel) => panel.classList.toggle("active", panel.id === button.dataset.tab));
  if (button.dataset.tab === "diagnostics") loadDiagnostics();
  if (button.dataset.tab === "settings") loadSettings();
}));
$$("[data-action]").forEach((button) => button.addEventListener("click", () => runAction(button.dataset.action)));
$("#timelineFilter").addEventListener("change", () => renderTimeline(state.data.console?.timeline || []));
$("#diagnosticsRefresh").addEventListener("click", loadDiagnostics);
$("#diagnosticsClear").addEventListener("click", () => { state.diagnostics = []; render(); });

async function loadDiagnostics() {
  try {
    const data = await request("/api/diagnostics");
    state.diagnostics = data.recent_events || data.events || data.timeline || data.entries || [];
    render();
  } catch (error) { showNotice(error.message); }
}
async function loadSettings() {
  try {
    const values = await request("/api/settings"), form = $("#settingsForm");
    [...form.elements].forEach((field) => {
      if (!field.name || !(field.name in values)) return;
      if (field.type === "checkbox") field.checked = Boolean(values[field.name]);
      else field.value = values[field.name];
    });
  } catch (error) { showNotice(error.message); }
}
$("#settingsForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const payload = {};
  [...event.currentTarget.elements].forEach((field) => {
    if (!field.name) return;
    payload[field.name] = field.type === "checkbox" ? field.checked : field.type === "number" ? Number(field.value) : field.value;
  });
  try {
    await request("/api/settings", { method: "PATCH", body: JSON.stringify(payload) });
    showNotice("設定を適用しました。", true);
  } catch (error) { showNotice(error.message); }
});
$("#demoForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const preset = $("#demoPreset").value, value = $("#demoComment").value.trim();
  if (!value) return;
  try {
    await request("/api/actions/demo-comment", { method: "POST", body: JSON.stringify({ preset, text: value, author_name: "Demo Viewer", is_paid: preset === "Paid" }) });
    $("#demoComment").value = "";
    showNotice("Fakeコメントを投入しました。", true);
  } catch (error) { showNotice(error.message); }
});

const events = new EventSource("/events");
events.addEventListener("core-event", () => load());
events.onopen = () => setConnection(true);
events.onerror = () => setConnection(false);
load();
