/**
 * ACC Connector — Popup script
 *
 * Reads state from chrome.storage.local (written by the service worker on
 * every native host response) and sends action messages to the service worker.
 */

// ------------------------------------------------------------------
// Helpers
// ------------------------------------------------------------------

function esc(str) {
  return String(str ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function sendAction(type, extra = {}) {
  chrome.runtime.sendMessage({ type, ...extra }, () => {
    // Ignore errors when the service worker is restarting
    void chrome.runtime.lastError;
  });
}

// ------------------------------------------------------------------
// Rendering
// ------------------------------------------------------------------

function renderServers(servers) {
  const list = document.getElementById("server-list");
  list.innerHTML = "";

  if (!servers || servers.length === 0) {
    const li = document.createElement("li");
    li.className = "empty";
    li.textContent = "No servers configured";
    list.appendChild(li);
    return;
  }

  for (const srv of servers) {
    const li = document.createElement("li");
    li.className = "server-item";
    li.innerHTML = `
      <div class="server-info">
        <span class="server-name">${esc(srv.display_name)}</span>
        <span class="server-addr">${esc(srv.host)}:${srv.port}</span>
        ${srv.persistent ? '<span class="badge">saved</span>' : ""}
      </div>
      <button class="btn-remove"
              data-host="${esc(srv.host)}"
              data-port="${srv.port}"
              title="Remove">✕</button>
    `;
    list.appendChild(li);
  }
}

function renderState(state = {}) {
  const { servers = [], discovery = false, connected = true, error = null } = state;

  renderServers(servers);

  const btn = document.getElementById("btn-toggle");
  const statusBar = document.getElementById("status-bar");

  if (!connected) {
    btn.textContent = "Discovery: —";
    btn.className = "";
    statusBar.textContent = error ? `Error: ${error}` : "Native host not connected";
    statusBar.className = "status-bar error";
    return;
  }

  if (discovery) {
    btn.textContent = "Discovery: ON";
    btn.className = "active";
    statusBar.textContent = `Broadcasting ${servers.length} server(s) on UDP :8999`;
    statusBar.className = "status-bar active";
  } else {
    btn.textContent = "Discovery: OFF";
    btn.className = "";
    statusBar.textContent = "Discovery paused — click to start";
    statusBar.className = "status-bar";
  }
}

// ------------------------------------------------------------------
// Load state
// ------------------------------------------------------------------

function loadAndRender() {
  chrome.storage.local.get(["state"], ({ state }) => {
    renderState(state);
  });
}

// ------------------------------------------------------------------
// Event wiring
// ------------------------------------------------------------------

document.addEventListener("DOMContentLoaded", () => {
  loadAndRender();

  // Ask the service worker to refresh (handles the case where the worker just
  // restarted and storage is stale).
  sendAction("list");

  // Live updates while the popup is open.
  chrome.storage.onChanged.addListener((changes) => {
    if (changes.state) {
      renderState(changes.state.newValue);
    }
  });

  // Toggle discovery.
  document.getElementById("btn-toggle").addEventListener("click", () => {
    chrome.storage.local.get(["state"], ({ state = {} }) => {
      if (state.discovery) {
        sendAction("disable_discovery");
      } else {
        sendAction("enable_discovery");
      }
    });
  });

  // Remove server via delegated click on list.
  document.getElementById("server-list").addEventListener("click", (e) => {
    const btn = e.target.closest(".btn-remove");
    if (!btn) return;
    sendAction("remove", {
      host: btn.dataset.host,
      port: parseInt(btn.dataset.port, 10),
    });
  });

  // Toggle add-server form.
  document.getElementById("btn-add-toggle").addEventListener("click", () => {
    const form = document.getElementById("add-form");
    form.hidden = !form.hidden;
    if (!form.hidden) document.getElementById("input-host").focus();
  });

  document.getElementById("btn-cancel").addEventListener("click", () => {
    document.getElementById("add-form").hidden = true;
    document.getElementById("add-form").reset();
  });

  // Submit add-server form.
  document.getElementById("add-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const host = document.getElementById("input-host").value.trim();
    if (!host) return;

    const port = parseInt(document.getElementById("input-port").value, 10) || 9911;
    const name = document.getElementById("input-name").value.trim();
    const persistent = document.getElementById("input-persistent").checked;

    const params = new URLSearchParams({ persistent: String(persistent) });
    if (name) params.set("name", name);
    const uri = `acc-connect://${host}:${port}?${params}`;

    sendAction("add", { uri });
    document.getElementById("add-form").hidden = true;
    document.getElementById("add-form").reset();
  });
});
