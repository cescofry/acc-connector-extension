/**
 * ACC Connector — Content Script
 *
 * Intercepts clicks on acc-connect:// links and forwards the URI to the
 * service worker instead of letting the browser attempt OS-level handling.
 * Works on any page; no site-specific logic needed.
 */

document.addEventListener("click", (event) => {
  const anchor = event.target.closest("a[href]");
  if (!anchor) return;

  const href = anchor.getAttribute("href") ?? "";
  if (!href.startsWith("acc-connect://")) return;

  event.preventDefault();
  event.stopImmediatePropagation();

  chrome.runtime.sendMessage({ type: "uri", uri: href }, (response) => {
    if (chrome.runtime.lastError) {
      console.warn("[ACC] Failed to send URI to background:", chrome.runtime.lastError.message);
    }
  });
}, /* capture */ true);
