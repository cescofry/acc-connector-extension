/**
 * ACC Connector — Service Worker (Chrome MV3) / Background Script (Firefox MV2)
 *
 * Maintains a persistent Native Messaging port to the Python host.
 * The port connection keeps the service worker alive in MV3.
 *
 * State is written to chrome.storage.local after every host response so the
 * popup can read it without a round-trip through the service worker.
 */

const NATIVE_HOST_ID = "com.acc_connector.host";

let port = null;

// ------------------------------------------------------------------
// Native Messaging
// ------------------------------------------------------------------

function connect() {
  if (port) return;
  try {
    port = chrome.runtime.connectNative(NATIVE_HOST_ID);
  } catch (err) {
    console.error("[ACC] connectNative failed:", err);
    saveState({ connected: false, error: err.message });
    return;
  }

  port.onMessage.addListener((msg) => {
    saveState({ connected: true, error: null, ...msg });
  });

  port.onDisconnect.addListener(() => {
    const err = chrome.runtime.lastError?.message ?? "Native host disconnected";
    console.warn("[ACC] Native host disconnected:", err);
    port = null;
    saveState({ connected: false, error: err });
  });

  // Fetch initial server list and restore discovery if it was running before.
  port.postMessage({ action: "list" });
  chrome.storage.local.get(["discoveryEnabled"], ({ discoveryEnabled }) => {
    if (discoveryEnabled && port) {
      port.postMessage({ action: "enable_discovery" });
    }
  });
}

function send(msg) {
  if (!port) connect();
  try {
    port.postMessage(msg);
  } catch (err) {
    console.error("[ACC] postMessage failed:", err);
    port = null;
    saveState({ connected: false, error: err.message });
  }
}

// ------------------------------------------------------------------
// Storage helpers
// ------------------------------------------------------------------

function saveState(data) {
  chrome.storage.local.set({ state: data });
}

// ------------------------------------------------------------------
// Message router (from content scripts and popup)
// ------------------------------------------------------------------

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  switch (msg.type) {
    case "uri":
      send({ action: "add", uri: msg.uri });
      break;
    case "list":
      send({ action: "list" });
      break;
    case "enable_discovery":
      chrome.storage.local.set({ discoveryEnabled: true });
      send({ action: "enable_discovery" });
      break;
    case "disable_discovery":
      chrome.storage.local.set({ discoveryEnabled: false });
      send({ action: "disable_discovery" });
      break;
    case "remove":
      send({ action: "remove", host: msg.host, port: msg.port });
      break;
    case "add":
      send({ action: "add", uri: msg.uri });
      break;
    default:
      console.warn("[ACC] Unknown message type:", msg.type);
  }
  sendResponse({ ok: true });
  return false;
});

// ------------------------------------------------------------------
// Startup
// ------------------------------------------------------------------

connect();
