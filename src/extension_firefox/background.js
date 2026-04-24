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
let connectAttempts = 0;

console.log("[ACC] background.js loaded, NATIVE_HOST_ID:", NATIVE_HOST_ID);

// ------------------------------------------------------------------
// Native Messaging
// ------------------------------------------------------------------

function connect() {
  console.log("[ACC] connect() called. Current port:", port, "connectAttempts:", ++connectAttempts);
  if (port) {
    console.log("[ACC] connect(): port already open, skipping");
    return;
  }
  console.log("[ACC] connect(): calling chrome.runtime.connectNative(" + NATIVE_HOST_ID + ")");
  try {
    port = chrome.runtime.connectNative(NATIVE_HOST_ID);
    console.log("[ACC] connect(): connectNative returned port:", port);
  } catch (err) {
    console.error("[ACC] connectNative threw synchronously:", err);
    saveState({ connected: false, error: err.message });
    return;
  }

  // Check lastError immediately after connectNative (Firefox bug 1330223 — lastError can be
  // set synchronously even though the call didn't throw).
  const immediateErr = chrome.runtime.lastError;
  if (immediateErr) {
    console.error("[ACC] lastError immediately after connectNative:", immediateErr);
  } else {
    console.log("[ACC] connect(): no immediate lastError — port appears open");
  }

  port.onMessage.addListener((msg) => {
    console.debug("[ACC] port.onMessage:", JSON.stringify(msg).slice(0, 300));
    if (msg.log !== undefined) {
      console.debug("[ACC] host.log:\n" + msg.log);
      return;
    }
    saveState({ connected: true, error: null, ...msg });
  });

  port.onDisconnect.addListener(() => {
    const lastErr = chrome.runtime.lastError;
    const err = lastErr?.message ?? "Native host disconnected (no lastError)";
    console.error("[ACC] port.onDisconnect fired. lastError:", lastErr,
                  " | lastError.message:", lastErr?.message,
                  " | constructed err:", err);
    console.error("[ACC] This usually means: (1) host binary not found/not executable, " +
                  "(2) manifest not found, (3) host crashed immediately, or " +
                  "(4) flatpak-spawn failed. Check ~/.config/acc-connector/wrapper.log and host.log");
    port = null;
    saveState({ connected: false, error: err });
  });

  console.log("[ACC] connect(): posting initial messages to port");
  // Fetch initial server list, request log for debugging, and restore discovery.
  port.postMessage({ action: "list" });
  console.debug("[ACC] connect(): posted {action: 'list'}");
  port.postMessage({ action: "get_log" });
  console.debug("[ACC] connect(): posted {action: 'get_log'}");
  chrome.storage.local.get(["discoveryEnabled"], ({ discoveryEnabled }) => {
    console.debug("[ACC] storage.local.get discoveryEnabled:", discoveryEnabled);
    if (discoveryEnabled && port) {
      port.postMessage({ action: "enable_discovery" });
      console.debug("[ACC] connect(): posted {action: 'enable_discovery'}");
    }
  });
}

function send(msg) {
  console.debug("[ACC] send():", JSON.stringify(msg));
  if (!port) {
    console.log("[ACC] send(): no port, calling connect() first");
    connect();
  }
  try {
    port.postMessage(msg);
    console.debug("[ACC] send(): postMessage succeeded");
  } catch (err) {
    console.error("[ACC] send(): postMessage failed:", err);
    port = null;
    saveState({ connected: false, error: err.message });
  }
}

// ------------------------------------------------------------------
// Storage helpers
// ------------------------------------------------------------------

function saveState(data) {
  console.debug("[ACC] saveState:", JSON.stringify(data));
  chrome.storage.local.set({ state: data });
}

// ------------------------------------------------------------------
// Message router (from content scripts and popup)
// ------------------------------------------------------------------

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  console.debug("[ACC] onMessage from extension:", JSON.stringify(msg));
  switch (msg.type) {
    case "uri":
      send({ action: "add", uri: msg.uri });
      try { chrome.action.openPopup(); } catch (_) {}
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

console.log("[ACC] background.js: calling connect() at startup");
connect();
