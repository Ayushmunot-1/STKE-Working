const API_BASE = "http://localhost:8000/api/v1";

// ── Setup ──────────────────────────────────────────────────────
chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({ id: "stke-extract-selection", title: "🔍 Extract tasks from selection", contexts: ["selection"] });
  chrome.contextMenus.create({ id: "stke-extract-page", title: "📄 Extract tasks from page", contexts: ["page"] });
  chrome.alarms.create("stke-reminder-check", { periodInMinutes: 5 });
  console.log("[STKE] Ready.");
});

// ── Context menu ───────────────────────────────────────────────
chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  if (info.menuItemId === "stke-extract-selection" && info.selectionText) {
    await handleExtraction(info.selectionText, tab.url, "selection");
  } else if (info.menuItemId === "stke-extract-page") {
    chrome.tabs.sendMessage(tab.id, { action: "GET_PAGE_TEXT" });
  }
});

// ── Keyboard shortcut ──────────────────────────────────────────
chrome.commands.onCommand.addListener((command, tab) => {
  if (command === "extract-selection") {
    chrome.tabs.sendMessage(tab.id, { action: "GET_SELECTED_TEXT" });
  }
});

// ── Messages ───────────────────────────────────────────────────
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.action === "EXTRACT_TEXT") {
    handleExtraction(message.text, message.sourceUrl, message.context).then(sendResponse).catch(err => sendResponse({ error: err.message }));
    return true;
  }
  if (message.action === "GET_TASKS") {
    fetchTasks(message.filters).then(sendResponse).catch(err => sendResponse({ error: err.message }));
    return true;
  }
  if (message.action === "COMPLETE_TASK") {
    completeTask(message.taskId).then(sendResponse).catch(err => sendResponse({ error: err.message }));
    return true;
  }
});

// ── API ────────────────────────────────────────────────────────
async function getToken() {
  const data = await chrome.storage.local.get("stke_token");
  return data.stke_token || null;
}

async function apiRequest(endpoint, options = {}) {
  const token = await getToken();
  const response = await fetch(`${API_BASE}${endpoint}`, {
    ...options,
    headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}), ...(options.headers || {}) },
  });
  if (!response.ok) {
    const err = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(err.detail || `HTTP ${response.status}`);
  }
  return response.json();
}

async function handleExtraction(text, sourceUrl, context) {
  if (!text || text.trim().length < 10) return { error: "Text too short" };
  chrome.action.setBadgeText({ text: "..." });
  chrome.action.setBadgeBackgroundColor({ color: "#6366f1" });
  try {
    const result = await apiRequest("/extract/", {
      method: "POST",
      body: JSON.stringify({ text: text.trim(), source_url: sourceUrl, source_context: context || "auto", auto_create_tasks: true }),
    });
    const count = result.tasks_found || 0;
    chrome.action.setBadgeText({ text: count > 0 ? String(count) : "" });
    chrome.action.setBadgeBackgroundColor({ color: count > 0 ? "#10b981" : "#6b7280" });
    if (count > 0) {
      chrome.notifications.create({
        type: "basic", iconUrl: "icons/icon48.png",
        title: "STKE — Tasks Found!", message: `Extracted ${count} task${count !== 1 ? "s" : ""}`,
      });
    }
    return result;
  } catch (err) {
    chrome.action.setBadgeText({ text: "!" });
    chrome.action.setBadgeBackgroundColor({ color: "#ef4444" });
    throw err;
  }
}

async function fetchTasks(filters = {}) {
  const params = new URLSearchParams(filters).toString();
  return apiRequest(`/tasks/${params ? "?" + params : ""}`);
}

async function completeTask(taskId) {
  return apiRequest(`/tasks/${taskId}/complete`, { method: "POST" });
}

// ── Reminder checker ───────────────────────────────────────────
chrome.alarms.onAlarm.addListener(async (alarm) => {
  if (alarm.name !== "stke-reminder-check") return;
  const token = await getToken();
  if (!token) return;
  try {
    const data = await fetchTasks({ status: "pending" });
    const now = new Date();
    (data.tasks || []).forEach((task) => {
      if (!task.deadline) return;
      const deadline = new Date(task.deadline);
      const diff = deadline - now;
      const notifKey = `notif_${task.id}`;
      if (diff > 0 && diff < 60 * 60 * 1000) {
        chrome.storage.session.get(notifKey).then(result => {
          if (!result[notifKey]) {
            chrome.notifications.create({
              type: "basic", iconUrl: "icons/icon48.png",
              title: "⏰ Task Due Soon!",
              message: `"${task.title}" is due in less than 1 hour!`,
            });
            chrome.storage.session.set({ [notifKey]: true });
          }
        }).catch(() => {
          chrome.notifications.create({
            type: "basic", iconUrl: "icons/icon48.png",
            title: "⏰ Task Due Soon!",
            message: `"${task.title}" is due in less than 1 hour!`,
          });
        });
      }
    });
  } catch (e) { /* not logged in */ }
});