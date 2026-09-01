/**
 * Personal OS — Active Tab Reporter
 *
 * Watches for active-tab changes (switching tabs, switching windows,
 * or a tab navigating to a new URL) and POSTs the current tab's
 * url/title to Personal OS's local extension server.
 *
 * Personal OS never sees anything except the currently active tab's
 * url/title, at the moment it changes. No browsing history, no
 * background tabs, nothing is read or stored beyond that.
 */

const REPORT_URL = "http://127.0.0.1:9333/tab";

// Identify which Chromium-based browser this is, best-effort.
function detectBrowserName() {
  const ua = navigator.userAgent;
  if (ua.includes("Edg/")) return "Microsoft Edge";
  if (ua.includes("Brave")) return "Brave";
  return "Google Chrome";
}

const BROWSER_NAME = detectBrowserName();

function isReportableUrl(url) {
  if (!url) return false;
  // Don't report internal browser pages, extension pages, etc.
  return /^https?:\/\//i.test(url);
}

async function reportTab(tab) {
  if (!tab || !isReportableUrl(tab.url)) {
    return;
  }

  const payload = {
    url: tab.url,
    title: tab.title || "",
    browser: BROWSER_NAME,
  };

  try {
    await fetch(REPORT_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  } catch (err) {
    // Personal OS isn't running / server unreachable — that's fine,
    // the Python side will simply fall back to CDP or page-title-only.
  }
}

async function reportActiveTabInFocusedWindow() {
  try {
    const [tab] = await chrome.tabs.query({
      active: true,
      lastFocusedWindow: true,
    });
    await reportTab(tab);
  } catch (err) {
    // Ignore — e.g. no windows focused.
  }
}

// Tab switched within a window.
chrome.tabs.onActivated.addListener(() => {
  reportActiveTabInFocusedWindow();
});

// Active tab navigated to a new URL, or finished loading.
chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  if (tab.active && (changeInfo.url || changeInfo.status === "complete")) {
    reportTab(tab);
  }
});

// User switched to a different browser window.
chrome.windows.onFocusChanged.addListener((windowId) => {
  if (windowId === chrome.windows.WINDOW_ID_NONE) {
    return;
  }
  reportActiveTabInFocusedWindow();
});