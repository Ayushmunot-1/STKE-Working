const API_BASE = "http://localhost:8000/api/v1";
let currentToken = null;

// ── Start ──────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", async () => {
  await loadToken();
  setupListeners();
});

async function loadToken() {
  const data = await chrome.storage.local.get("stke_token");
  currentToken = data.stke_token || null;
  showScreen(currentToken ? "main" : "auth");
}

// ── API ────────────────────────────────────────────────────────
async function api(endpoint, options = {}) {
  const res = await fetch(`${API_BASE}${endpoint}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(currentToken ? { Authorization: `Bearer ${currentToken}` } : {}),
      ...(options.headers || {}),
    },
  });
  if (res.status === 401) { await logout(); throw new Error("Session expired"); }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || `Error ${res.status}`);
  return data;
}

// ── Screens & Views ────────────────────────────────────────────
function showScreen(name) {
  document.querySelectorAll(".screen").forEach((s) => s.classList.add("hidden"));
  document.getElementById(`screen-${name}`).classList.remove("hidden");
  if (name === "main") showView("extract");
}

function showView(name) {
  document.querySelectorAll(".view").forEach((v) => v.classList.add("hidden"));
  document.getElementById(`view-${name}`).classList.remove("hidden");
  document.querySelectorAll(".nav-tab").forEach((t) => t.classList.toggle("active", t.dataset.view === name));
  if (name === "tasks") loadTasks();
  if (name === "history") loadHistory();
}

// ── Listeners ──────────────────────────────────────────────────
function setupListeners() {
  document.querySelectorAll(".tab-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".tab-btn").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      document.querySelectorAll(".tab-panel").forEach((p) => p.classList.add("hidden"));
      document.getElementById(`tab-${btn.dataset.tab}`).classList.remove("hidden");
      hideError();
    });
  });

  document.getElementById("btn-login").addEventListener("click", handleLogin);
  document.getElementById("btn-register").addEventListener("click", handleRegister);
  document.getElementById("login-password").addEventListener("keydown", (e) => { if (e.key === "Enter") handleLogin(); });
  document.querySelectorAll(".nav-tab").forEach((tab) => tab.addEventListener("click", () => showView(tab.dataset.view)));
  document.getElementById("btn-extract-page").addEventListener("click", extractFromPage);
  document.getElementById("btn-extract-selection").addEventListener("click", extractFromSelection);
  document.getElementById("btn-extract-paste").addEventListener("click", extractFromPaste);
  document.getElementById("btn-refresh-tasks").addEventListener("click", loadTasks);
  document.getElementById("filter-status").addEventListener("change", loadTasks);
  document.getElementById("filter-priority").addEventListener("change", loadTasks);
  document.getElementById("btn-logout").addEventListener("click", logout);
  document.getElementById("btn-open-dashboard").addEventListener("click", () => {
    chrome.tabs.create({ url: "http://localhost:8000/dashboard" });
  });
}

// ── Auth ───────────────────────────────────────────────────────
async function handleLogin() {
  const email = document.getElementById("login-email").value.trim();
  const password = document.getElementById("login-password").value;
  if (!email || !password) return showError("Please fill in all fields");
  setBtnLoading("btn-login", true, "Signing in…");
  try {
    const data = await api("/auth/login", { method: "POST", body: JSON.stringify({ email, password }) });
    currentToken = data.access_token;
    await chrome.storage.local.set({ stke_token: currentToken });
    showScreen("main");
  } catch (err) { showError(err.message); }
  finally { setBtnLoading("btn-login", false, "Sign In"); }
}

async function handleRegister() {
  const full_name = document.getElementById("reg-name").value.trim();
  const username = document.getElementById("reg-username").value.trim();
  const email = document.getElementById("reg-email").value.trim();
  const password = document.getElementById("reg-password").value;
  if (!username || !email || !password) return showError("Please fill in all fields");
  setBtnLoading("btn-register", true, "Creating…");
  try {
    const data = await api("/auth/register", { method: "POST", body: JSON.stringify({ full_name, username, email, password }) });
    currentToken = data.access_token;
    await chrome.storage.local.set({ stke_token: currentToken });
    showScreen("main");
  } catch (err) { showError(err.message); }
  finally { setBtnLoading("btn-register", false, "Create Account"); }
}

async function logout() {
  currentToken = null;
  await chrome.storage.local.remove("stke_token");
  showScreen("auth");
}

// ── Extraction ─────────────────────────────────────────────────
async function extractFromPage() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  chrome.tabs.sendMessage(tab.id, { action: "GET_PAGE_TEXT" });
  showExtractionLoading();
}

async function extractFromSelection() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  chrome.tabs.sendMessage(tab.id, { action: "GET_SELECTED_TEXT" });
  showExtractionLoading();
}

async function extractFromPaste() {
  const text = document.getElementById("paste-input").value.trim();
  if (!text) return;
  showExtractionLoading();
  try {
    const result = await api("/extract/", {
      method: "POST",
      body: JSON.stringify({ text, source_context: "auto", auto_create_tasks: true }),
    });
    renderResults(result);
  } catch (err) {
    hideExtractionLoading();
    showResultError(err.message);
  }
}

function showExtractionLoading() {
  document.getElementById("extract-loading").classList.remove("hidden");
  document.getElementById("extract-results").classList.add("hidden");
}

function hideExtractionLoading() {
  document.getElementById("extract-loading").classList.add("hidden");
}

function renderResults(result) {
  hideExtractionLoading();
  const container = document.getElementById("extract-results");
  const list = document.getElementById("results-list");
  const countEl = document.getElementById("results-count");
  const dupEl = document.getElementById("results-dup");

  const nonDup = (result.tasks || []).filter(t => !t.is_duplicate);
  const decisions = result.decisions || [];
  const dependencies = result.dependencies || [];

  countEl.textContent = `${nonDup.length} task${nonDup.length !== 1 ? "s" : ""} found`;

  if (result.duplicates_filtered > 0) {
    dupEl.textContent = `${result.duplicates_filtered} duplicate${result.duplicates_filtered !== 1 ? "s" : ""} filtered`;
    dupEl.classList.remove("hidden");
  } else {
    dupEl.classList.add("hidden");
  }

  list.innerHTML = "";

  // Tasks
  if (nonDup.length === 0 && decisions.length === 0 && dependencies.length === 0) {
    list.innerHTML = `<div class="empty-state"><p>No new tasks detected.</p></div>`;
  } else if (nonDup.length === 0) {
    list.innerHTML = `<div class="empty-state" style="margin-bottom:8px"><p>No new tasks — but found insights below.</p></div>`;
  } else {
    nonDup.forEach((task) => list.appendChild(buildTaskCard(task, true)));
  }

  // Decisions section
  if (decisions.length > 0) {
    const decDiv = document.createElement("div");
    decDiv.className = "section-block";
    decDiv.innerHTML = `
      <div class="section-header">⚖️ Decisions (${decisions.length})</div>
      ${decisions.map(d => `
        <div class="decision-item">
          <div class="decision-text">${escHtml(typeof d === 'string' ? d : d.decision || d.text || JSON.stringify(d))}</div>
        </div>`).join("")}`;
    list.appendChild(decDiv);
  }

  // Dependencies section
  if (dependencies.length > 0) {
    const depDiv = document.createElement("div");
    depDiv.className = "section-block";
    depDiv.innerHTML = `
      <div class="section-header">🔗 Dependencies (${dependencies.length})</div>
      ${dependencies.map(d => `
        <div class="dependency-item">
          <div class="dep-text">${escHtml(typeof d === 'string' ? d : d.dependency || d.text || d.description || JSON.stringify(d))}</div>
        </div>`).join("")}`;
    list.appendChild(depDiv);
  }

  container.classList.remove("hidden");
}

function showResultError(msg) {
  const container = document.getElementById("extract-results");
  document.getElementById("results-list").innerHTML = `<div class="error-msg">${escHtml(msg)}</div>`;
  document.getElementById("results-count").textContent = "Error";
  container.classList.remove("hidden");
}

// ── Tasks view ─────────────────────────────────────────────────
async function loadTasks() {
  const status = document.getElementById("filter-status").value;
  const priority = document.getElementById("filter-priority").value;
  const params = new URLSearchParams();
  if (status) params.set("status", status);
  if (priority) params.set("priority", priority);

  document.getElementById("tasks-loading").classList.remove("hidden");
  document.getElementById("tasks-list").innerHTML = "";
  document.getElementById("tasks-empty").classList.add("hidden");

  try {
    const data = await api(`/tasks/?${params}`);
    document.getElementById("tasks-loading").classList.add("hidden");
    if (!data.tasks || data.tasks.length === 0) {
      document.getElementById("tasks-empty").classList.remove("hidden");
      return;
    }
    const list = document.getElementById("tasks-list");
    data.tasks.forEach((task) => list.appendChild(buildTaskCard(task, false)));
  } catch (err) {
    document.getElementById("tasks-loading").classList.add("hidden");
    document.getElementById("tasks-list").innerHTML = `<div class="error-msg">${escHtml(err.message)}</div>`;
  }
}

async function markComplete(taskId, card) {
  try {
    await api(`/tasks/${taskId}/complete`, { method: "POST" });
    card.classList.add("completed");
    card.querySelector(".task-title")?.classList.add("done");
    const btn = card.querySelector(".task-complete-btn");
    if (btn) btn.textContent = "✓";
  } catch (err) { console.error(err); }
}

async function syncToCalendar(taskId, btn) {
  btn.textContent = "⏳";
  btn.disabled = true;
  try {
    await api(`/calendar/sync/${taskId}`, { method: "POST" });
    btn.textContent = "📅✓";
    btn.style.color = "#10b981";
    btn.title = "Synced to Calendar";
  } catch (err) {
    btn.textContent = "📅";
    btn.disabled = false;
    console.error(err);
  }
}

// ── History ────────────────────────────────────────────────────
async function loadHistory() {
  try {
    const data = await api("/tasks/?skip=0&limit=100");
    const tasks = data.tasks || [];
    document.getElementById("stat-total").textContent = tasks.length;
    document.getElementById("stat-pending").textContent = tasks.filter(t => t.status === "pending").length;
    document.getElementById("stat-done").textContent = tasks.filter(t => t.status === "completed").length;
    const list = document.getElementById("history-list");
    if (!tasks.length) { list.innerHTML = `<div class="empty-state"><p>No tasks yet</p></div>`; return; }
    list.innerHTML = tasks.slice(0, 15).map(t => `
      <div class="history-item">
        <div class="history-item-top">
          <span class="history-source">${escHtml(t.title.substring(0, 38))}${t.title.length > 38 ? "…" : ""}</span>
          <span class="history-time">${timeAgo(t.created_at)}</span>
        </div>
        <div class="history-chips">
          <span class="meta-chip">${priorityEmoji(t.priority)} ${t.priority}</span>
          <span class="meta-chip">${statusEmoji(t.status)} ${t.status.replace("_", " ")}</span>
          ${t.source_context ? `<span class="meta-chip">📍 ${t.source_context}</span>` : ""}
          ${t.calendar_event_id ? `<span class="meta-chip" style="color:#34d399">📅 Synced</span>` : ""}
        </div>
      </div>`).join("");
  } catch (err) { console.error(err); }
}

// ── Task card ──────────────────────────────────────────────────
function buildTaskCard(task, isPreview) {
  const card = document.createElement("div");
  card.className = `task-card${task.status === "completed" ? " completed" : ""}`;
  const isOverdue = task.deadline && new Date(task.deadline) < new Date() && task.status !== "completed";
  const isDueSoon = task.deadline && (new Date(task.deadline) - new Date()) < 86400000 && new Date(task.deadline) > new Date();

  card.innerHTML = `
    <div class="task-card-top">
      <div class="priority-dot dot-${task.priority || "medium"}"></div>
      <span class="task-title${task.status === "completed" ? " done" : ""}">${escHtml(task.title)}</span>
      ${!isPreview ? `
        <div class="task-actions">
          <button class="task-complete-btn task-btn" title="Complete">${task.status === "completed" ? "✓" : "○"}</button>
          <button class="task-cal-btn task-btn ${task.calendar_event_id ? 'synced' : ''}" title="${task.calendar_event_id ? 'Synced' : 'Sync to Calendar'}">
            ${task.calendar_event_id ? "📅✓" : "📅"}
          </button>
        </div>` : ""}
    </div>
    <div class="task-meta">
      ${task.assigned_to ? `<span class="meta-chip">👤 ${escHtml(task.assigned_to)}</span>` : ""}
      ${task.deadline_raw ? `<span class="meta-chip ${isOverdue ? "overdue" : isDueSoon ? "due-soon" : "deadline"}">📅 ${escHtml(task.deadline_raw)}</span>` : ""}
      ${task.source_context ? `<span class="meta-chip">📍 ${escHtml(task.source_context)}</span>` : ""}
      ${isPreview ? `<span class="meta-chip">✦ ${Math.round((task.confidence_score || 0) * 100)}%</span>` : ""}
    </div>`;

  if (!isPreview) {
    card.querySelector(".task-complete-btn").addEventListener("click", () => markComplete(task.id, card));
    const calBtn = card.querySelector(".task-cal-btn");
    if (!task.calendar_event_id) {
      calBtn.addEventListener("click", () => syncToCalendar(task.id, calBtn));
    }
  }
  return card;
}

// ── Utilities ──────────────────────────────────────────────────
function escHtml(t) { return String(t || "").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;"); }
function timeAgo(iso) {
  const d = Date.now() - new Date(iso).getTime();
  if (d < 60000) return "just now";
  if (d < 3600000) return `${Math.floor(d/60000)}m ago`;
  if (d < 86400000) return `${Math.floor(d/3600000)}h ago`;
  return `${Math.floor(d/86400000)}d ago`;
}
function priorityEmoji(p) { return {low:"🟢",medium:"🔵",high:"🟡",critical:"🔴"}[p]||"⚪"; }
function statusEmoji(s) { return {pending:"⏳",in_progress:"🔄",completed:"✅",cancelled:"❌"}[s]||"•"; }
function showError(msg) {
  const el = document.getElementById("auth-error");
  el.textContent = msg; el.classList.remove("hidden");
}
function hideError() { document.getElementById("auth-error").classList.add("hidden"); }
function setBtnLoading(id, loading, text) { const b = document.getElementById(id); if (!b) return; b.disabled = loading; b.textContent = text; }