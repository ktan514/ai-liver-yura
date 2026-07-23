// Standalone browser client for the Yura streaming control surface.
const state = {
  data: {}, diagnostics: [], loading: false, pending: false,
  timerKey: "", timers: [], optionKeys: {}, serviceNodes: new Map(),
};
const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];
const text = (value, fallback = "—") => value === null || value === undefined || value === "" ? fallback : String(value);
const esc = (value) => text(value).replace(/[&<>"']/g, (c) => ({ "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;" })[c]);

async function request(path, options = {}) {
  const response = await fetch(path, { ...options, headers: { "Content-Type": "application/json", ...(options.headers || {}) } });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.error?.message || `HTTP ${response.status}`);
  return payload;
}

function setText(selector, value, fallback = "—") {
  const node = typeof selector === "string" ? $(selector) : selector;
  const next = text(value, fallback);
  if (node && node.textContent !== next) node.textContent = next;
}
function setHtmlIfChanged(selector, html) {
  const node = typeof selector === "string" ? $(selector) : selector;
  if (node && node.innerHTML !== html) node.innerHTML = html;
}
function table(rows, columns) {
  if (!Array.isArray(rows) || !rows.length) return '<p class="empty">データはありません。</p>';
  return `<table><thead><tr>${columns.map(([, label]) => `<th>${label}</th>`).join("")}</tr></thead><tbody>${rows.map((row) =>
    `<tr>${columns.map(([key]) => `<td>${esc(row?.[key])}</td>`).join("")}</tr>`).join("")}</tbody></table>`;
}

function setOptions(element, items, valueKey, labelKey, cacheKey) {
  const normalized = items || [];
  const signature = JSON.stringify(normalized.map((item) => [item[valueKey], item[labelKey] || item.display_label || item.title]));
  if (state.optionKeys[cacheKey] === signature) return;
  state.optionKeys[cacheKey] = signature;
  const selected = element.value;
  element.replaceChildren(...normalized.map((item) => {
    const option = document.createElement("option");
    option.value = text(item[valueKey], "");
    option.textContent = text(item[labelKey] || item.display_label || item.title || item[valueKey]);
    return option;
  }));
  if ([...element.options].some((option) => option.value === selected)) element.value = selected;
}

function getActionState(auth, session, health) {
  const status = session.status;
  const demo = health.runtime_mode === "streaming_demo";
  const modes = session.adapter_modes || health.adapter_modes || {};
  return {
    authenticate: !["authenticated", "authentication_in_progress"].includes(auth.status),
    prepare: auth.status === "authenticated",
    start: status === "ready" && (demo || modes.obs === "obs_websocket"),
    end: ["live", "running"].includes(status),
    "emergency-stop": ["live", "running", "starting", "ending"].includes(status),
    "retry-opening": state.data.opening?.status === "failed" && state.data.opening?.retryable !== false,
    "retry-main": state.data.main_segment?.status === "failed" && Boolean(state.data.main_segment?.retryable),
    "retry-comment": Boolean(state.data.comment_response?.activity?.retryable),
  };
}
function resolveNextAction(auth, session, health, enabled) {
  if (enabled.end) return { action: "end", label: "配信を通常終了", description: "配信中です。終了時は通常終了を実行してください。" };
  if (enabled.start) return { action: "start", label: "配信開始", description: "準備が完了しています。確認後に配信を開始できます。" };
  if (enabled.prepare) return { action: "prepare", label: "配信準備を開始", description: "配信枠と進行表を確認して準備を開始してください。" };
  if (enabled.authenticate) return { action: "authenticate", label: "YouTube認証", description: "最初にYouTube認証を完了してください。" };
  return { action: "prepare", label: "操作待ち", description: `${text(session.status || health.status, "待機中")}。Coreから次の操作が有効になるのを待っています。`, disabled: true };
}

function createServiceCard(name) {
  const card = document.createElement("div");
  card.className = "service-card";
  card.dataset.service = name;
  const action = { OBS: "refresh-obs", YouTube: "refresh-youtube" }[name];
  card.innerHTML = `<p class="label"></p><div class="status"></div><dl><dt>更新方式</dt><dd data-field="update"></dd><dt>鮮度</dt><dd data-field="freshness"></dd><dt>最終更新</dt><dd data-field="updated"></dd></dl>${action ? `<button data-action="${action}" class="compact-button">状態を更新</button>` : ""}`;
  card.querySelector(".label").textContent = name;
  return card;
}
function renderServiceCards(services) {
  const area = $("#serviceCards");
  const names = new Set((services || []).map((item) => item.name));
  for (const [name, node] of state.serviceNodes) {
    if (!names.has(name)) { node.remove(); state.serviceNodes.delete(name); }
  }
  (services || []).forEach((item) => {
    let card = state.serviceNodes.get(item.name);
    if (!card) {
      card = createServiceCard(item.name);
      state.serviceNodes.set(item.name, card);
      area.append(card);
    }
    setText(card.querySelector(".status"), item.status);
    setText(card.querySelector('[data-field="update"]'), item.update_mode);
    setText(card.querySelector('[data-field="freshness"]'), item.freshness);
    setText(card.querySelector('[data-field="updated"]'), item.last_updated_at);
  });
}

function renderRecoveryCards(enabled) {
  const items = [
    { key: "retry-opening", title: "Openingの実行に失敗しました", source: state.data.opening, label: "Openingを再試行" },
    { key: "retry-main", title: "Mainの実行に失敗しました", source: state.data.main_segment, label: "Mainを再試行" },
    { key: "retry-comment", title: "コメント応答に失敗しました", source: state.data.comment_response?.activity, label: "コメント応答を再試行" },
  ].filter((item) => enabled[item.key]);
  const area = $("#recoveryArea");
  const html = items.map((item) => `<article class="recovery-card"><p class="label">RECOVERY REQUIRED</p><h3>${esc(item.title)}</h3><p>${esc(item.source?.error_message || item.source?.error_code || "再試行可能な失敗を検出しました。")}</p><button data-action="${item.key}">${esc(item.label)}</button></article>`).join("");
  setHtmlIfChanged(area, html);
  area.classList.toggle("hidden", items.length === 0);
}

function renderTimeline(rows) {
  const filter = $("#timelineFilter").value;
  const filtered = filter === "all" ? rows : rows.filter((row) => row.category === filter);
  const html = filtered.length ? filtered.slice().reverse().map((row) =>
    `<div class="timeline-row ${row.result === "failed" ? "failed" : ""}"><time>${esc(row.observed_at)}</time><span class="category">${esc(row.category)}</span><span>${esc(row.event_name || row.message)}</span><span class="result">${esc(row.result)}</span></div>`
  ).join("") : '<p class="empty">イベントはありません。</p>';
  setHtmlIfChanged("#timeline", html);
}
function renderDiagnostics() {
  setHtmlIfChanged("#diagnosticTable", table(state.diagnostics, [["observed_at","時刻"],["category","分類"],["event_name","イベント"],["result","結果"],["error_code","エラー"]]));
}

function render() {
  const data = state.data, health = data.health || {}, consoleData = data.console || {};
  const session = data.session || {}, auth = data.auth || {}, modes = health.adapter_modes || session.adapter_modes || {};
  setText("#currentState", consoleData.current_state || session.status, "待機中");
  setText("#currentMessage", consoleData.current_message, "次の操作を選択してください。");
  setText("#modeBadge", `${text(modes.youtube, "UNKNOWN").toUpperCase()} YOUTUBE / ${text(modes.obs, "UNKNOWN").toUpperCase()} OBS`);
  setOptions($("#broadcastSelect"), (data.broadcasts || []).filter((item) => item.selectable !== false), "broadcast_id", "display_label", "broadcasts");
  setOptions($("#runOfShowSelect"), data.run_of_shows, "run_of_show_id", "title", "runOfShows");

  renderServiceCards(consoleData.services || [
    { name: "Core", status: health.status || "unknown", freshness: "unknown" },
    { name: "OBS", status: session.obs_status || "unknown", freshness: "unknown" },
    { name: "YouTube", status: auth.status || "unknown", freshness: "unknown" },
  ]);

  const operator = consoleData.operator_action || {};
  setText("#operatorTitle", operator.title, "現在、必要な人間操作はありません。");
  setText("#operatorDescription", operator.description, "");
  const studio = $("#studioLink");
  studio.classList.toggle("hidden", !operator.studio_url);
  if (operator.studio_url && studio.href !== operator.studio_url) studio.href = operator.studio_url;

  setHtmlIfChanged("#responsibilities", table(consoleData.responsibilities, [["operation","操作"],["owner","担当"],["status","状態"]]));
  setHtmlIfChanged("#steps", table(consoleData.lifecycle_steps, [["title","工程"],["status","状態"],["owner","担当"],["block_reason","ブロック理由"],["error_code","失敗理由"]]));

  const comments = data.comments || {}, moderation = data.moderation || {}, ranking = data.ranking || {}, response = data.comment_response || {};
  setHtmlIfChanged("#commentMetrics", [
    ["ポーラー", comments.status], ["受信数", comments.received_count ?? comments.total_count],
    ["モデレーション", moderation.status], ["応答", response.status],
  ].map(([label, value]) => `<div class="metric"><span class="label">${label}</span><strong>${esc(value)}</strong></div>`).join(""));
  const commentRows = [...(moderation.recent || moderation.queue || []), ...(ranking.top || [])].map((row) => ({
    ...row, author: row.author_display_name || row.author || row.author_name,
    comment: row.sanitized_text || row.text || row.comment,
    score: row.total_score ?? row.priority ?? row.score,
  }));
  setHtmlIfChanged("#commentTable", table(commentRows, [["author","投稿者"],["comment","コメント"],["status","状態"],["score","スコア"]]));
  renderTimeline(consoleData.timeline || []);
  renderDiagnostics();
  applyButtonState(auth, session, health);
  configureTimers(consoleData.log_settings || {});
}

function applyButtonState(auth, session, health) {
  const enabled = getActionState(auth, session, health);
  $$('[data-action]').forEach((button) => {
    if (button.dataset.action in enabled) {
      const disabled = !enabled[button.dataset.action];
      if (button.disabled !== disabled) button.disabled = disabled;
    }
  });
  const next = resolveNextAction(auth, session, health, enabled);
  const nextButton = $("#nextActionButton");
  if (nextButton.dataset.action !== next.action) nextButton.dataset.action = next.action;
  setText(nextButton, next.label);
  const disabled = Boolean(next.disabled) || !enabled[next.action];
  if (nextButton.disabled !== disabled) nextButton.disabled = disabled;
  setText("#nextActionDescription", next.description);
  renderRecoveryCards(enabled);
  $("#demoForm").hidden = health.runtime_mode !== "streaming_demo";
}

async function load() {
  if (state.loading) { state.pending = true; return; }
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
    if (state.pending) { state.pending = false; queueMicrotask(load); }
  }
}
function configureTimers(settings) {
  const key = JSON.stringify([settings.obs_auto_refresh, settings.obs_refresh_interval, settings.youtube_auto_refresh, settings.youtube_refresh_interval]);
  if (key === state.timerKey) return;
  state.timerKey = key;
  state.timers.forEach(clearInterval);
  state.timers = [];
  if (settings.obs_auto_refresh) state.timers.push(setInterval(() => runAction("refresh-obs", true), Number(settings.obs_refresh_interval || 30) * 1000));
  if (settings.youtube_auto_refresh) state.timers.push(setInterval(() => runAction("refresh-youtube", true), Number(settings.youtube_refresh_interval || 30) * 1000));
}
function setConnection(online) {
  const node = $("#connection");
  const className = `connection ${online ? "online" : "offline"}`;
  if (node.className !== className) node.className = className;
  setText(node.querySelector("b"), online ? "CORE ONLINE" : "CORE OFFLINE");
}
function showNotice(message, success = false) {
  setText("#notice", message, "");
  $("#notice").style.color = success ? "#8ef0c2" : "";
}

async function runAction(name, quiet = false) {
  const session = state.data.session || {};
  const activity = name === "retry-opening" ? state.data.opening || {} : name === "retry-main" ? state.data.main_segment || {} : state.data.comment_response?.activity || {};
  const payload = {
    session_id: session.session_id, state_version: session.state_version,
    broadcast_id: $("#broadcastSelect").value, run_of_show_id: $("#runOfShowSelect").value,
    activity_id: activity.activity_id, activity_version: activity.version, selection_id: activity.selection_id,
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

function activatePanel(name) {
  $$('.header-nav [data-tab]').forEach((button) => button.classList.toggle("active", button.dataset.tab === name));
  $$('.panel').forEach((panel) => panel.classList.toggle("active", panel.id === name));
  if (name === "diagnostics") loadDiagnostics();
}
function openSettings() {
  $("#settingsOverlay").classList.remove("hidden");
  document.body.classList.add("overlay-open");
  loadSettings();
  $("#settingsClose").focus();
}
function closeSettings() {
  $("#settingsOverlay").classList.add("hidden");
  document.body.classList.remove("overlay-open");
  $("#settingsOpen").focus();
}

// Stable event delegation: dynamically-added buttons do not need rebinding.
document.addEventListener("click", (event) => {
  const actionButton = event.target.closest("[data-action]");
  if (actionButton) runAction(actionButton.dataset.action);
  const tabButton = event.target.closest(".header-nav [data-tab]");
  if (tabButton) activatePanel(tabButton.dataset.tab);
});
$("#settingsOpen").addEventListener("click", openSettings);
$("#settingsClose").addEventListener("click", closeSettings);
$("#settingsOverlay").addEventListener("click", (event) => { if (event.target === event.currentTarget) closeSettings(); });
document.addEventListener("keydown", (event) => { if (event.key === "Escape" && !$("#settingsOverlay").classList.contains("hidden")) closeSettings(); });
$("#timelineFilter").addEventListener("change", () => renderTimeline(state.data.console?.timeline || []));
$("#diagnosticsRefresh").addEventListener("click", loadDiagnostics);
$("#diagnosticsClear").addEventListener("click", () => { state.diagnostics = []; renderDiagnostics(); });

async function loadDiagnostics() {
  try {
    const data = await request("/api/diagnostics");
    state.diagnostics = data.recent_events || data.events || data.timeline || data.entries || [];
    renderDiagnostics();
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
    if (field.name) payload[field.name] = field.type === "checkbox" ? field.checked : field.type === "number" ? Number(field.value) : field.value;
  });
  try {
    await request("/api/settings", { method: "PATCH", body: JSON.stringify(payload) });
    showNotice("設定を適用しました。", true);
    closeSettings();
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
