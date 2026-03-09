// ── Detect what kind of page we are on ────────────────────────

function detectContext() {
  const host = window.location.hostname;
  if (host.includes("mail.google.com")) return "email";
  if (host.includes("outlook")) return "email";
  if (host.includes("slack.com")) return "chat";
  if (host.includes("teams.microsoft.com")) return "chat";
  if (host.includes("discord.com")) return "chat";
  if (host.includes("docs.google.com")) return "document";
  if (host.includes("notion.so")) return "document";
  if (host.includes("github.com")) return "code";
  return "webpage";
}

// ── Extract text based on page type ───────────────────────────

function extractPageText() {
  const context = detectContext();

  // Gmail
  if (context === "email") {
    const gmail = document.querySelector(".a3s.aiL");
    if (gmail) return { text: gmail.innerText, context };
    const outlook = document.querySelector('[role="main"]');
    if (outlook) return { text: outlook.innerText, context };
  }

  // Slack / Discord / Teams
  if (context === "chat") {
    const slack = document.querySelectorAll(".c-message__body");
    if (slack.length) {
      return {
        text: Array.from(slack).map((m) => m.innerText).join("\n"),
        context,
      };
    }
    const discord = document.querySelectorAll('[class*="messageContent"]');
    if (discord.length) {
      return {
        text: Array.from(discord).map((m) => m.innerText).join("\n"),
        context,
      };
    }
  }

  // Google Docs / Notion
  if (context === "document") {
    const gdoc = document.querySelector(".kix-page-content-block");
    if (gdoc) return { text: gdoc.innerText, context };
    const notion = document.querySelector(".notion-page-content");
    if (notion) return { text: notion.innerText, context };
  }

  // GitHub
  if (context === "code") {
    const body = document.querySelector(".comment-body, .markdown-body");
    if (body) return { text: body.innerText, context };
  }

  // Generic webpage fallback
  const main =
    document.querySelector("main, article, [role='main'], .content") ||
    document.body;
  const clone = main.cloneNode(true);
  ["nav", "header", "footer", "script", "style"].forEach((tag) => {
    clone.querySelectorAll(tag).forEach((el) => el.remove());
  });
  return {
    text: clone.innerText.substring(0, 8000),
    context: "webpage",
  };
}

// ── Listen for messages from background ───────────────────────

chrome.runtime.onMessage.addListener((message) => {
  if (message.action === "GET_PAGE_TEXT") {
    const { text, context } = extractPageText();
    if (text.length > 10) {
      chrome.runtime.sendMessage({
        action: "EXTRACT_TEXT",
        text,
        sourceUrl: window.location.href,
        context,
      });
      showToast("🔍 Extracting tasks from page...");
    } else {
      showToast("⚠️ Not enough text found on this page.");
    }
  }

  if (message.action === "GET_SELECTED_TEXT") {
    const text = window.getSelection()?.toString()?.trim() || "";
    if (text.length > 10) {
      chrome.runtime.sendMessage({
        action: "EXTRACT_TEXT",
        text,
        sourceUrl: window.location.href,
        context: "selection",
      });
      showToast("🔍 Extracting tasks from selection...");
    } else {
      showToast("⚠️ Please select some text first.");
    }
  }
});

// ── Toast notification on page ─────────────────────────────────

function showToast(message) {
  const existing = document.getElementById("stke-toast");
  if (existing) existing.remove();

  const toast = document.createElement("div");
  toast.id = "stke-toast";
  toast.textContent = message;
  document.body.appendChild(toast);
  setTimeout(() => toast.remove(), 3000);
}
