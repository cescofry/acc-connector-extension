# Analysis: Browser Extension + Native Host Approach for ACC Connector

## Context

The current tool (`acc-connector`) handles `acc-connector://` URI links and broadcasts their contained server info as LAN servers via UDP on port 8999, so the ACC game can discover them. The core logic works well and is fully cross-platform. The pain point is **URI scheme registration**: Linux works seamlessly via `.desktop` files, but macOS requires a signed `.app` bundle and Windows requires registry edits — neither is currently implemented.

This document evaluates replacing the current architecture with a browser extension + native host approach.

---

## Current Architecture Summary

```
User clicks acc-connector:// link
    → OS looks up registered URI handler
    → Launches: acc-connector "acc-connect://..."     ← WORKS ON LINUX ONLY
    → main.py parses URI, adds server to list
    → TUI (Textual) runs, user enables discovery
    → UDP server on :8999 responds to ACC broadcasts
```

**Files:**
- `main.py` — entry point, URI parsing
- `models.py` — ServerInfo, packet protocol, URI parsing
- `discovery.py` — async UDP listener/responder on port 8999
- `config.py` — persistence to `~/.config/acc-connector/servers.json`
- `tui.py` — Textual TUI app
- `install.sh` — Linux-only `.desktop` registration

---

## Proposed Architecture

```
User clicks acc-connector:// link in browser
    → Content script intercepts the click
    → Service worker (background script) receives URI
    → Extension calls connectNative() → browser spawns native host on demand
    → Native host adds server, runs UDP broadcaster on :8999
    → Service worker holds the port open to keep host alive
    → Extension popup shows server list, toggle, add/remove controls
```

The **native host** is a regular Python executable — not a daemon, not a service. The browser spawns it when the extension first connects and keeps it alive as long as the port connection is held open. When the user closes the browser or the extension releases the port, the process can exit. This is exactly how 1Password's browser extension works with its desktop app.

---

## Analysis

### Does it solve the problem better?

**Yes, significantly on the URI interception front.**

The extension intercepts clicks *inside the browser* via a content script — no OS-level URI handler registration needed. This is inherently cross-platform (Chrome/Firefox on Linux, macOS, Windows) without any platform-specific installation steps for URI handling.

The extension popup also provides a far better UX than a terminal TUI: always accessible from the toolbar, no terminal needed, clear status indicator.

The user still needs to install the native host (pip install), but that's true of the current tool too. The key win is that no platform-specific URI registration is required afterward.

---

### Does it remove or add complexity?

| Aspect | Current | Extension + Native Host | Delta |
|--------|---------|------------------------|-------|
| URI interception (Linux) | .desktop file | Content script | Simpler |
| URI interception (macOS) | Not implemented | Content script | Simpler |
| URI interception (Windows) | Not implemented | Content script | Simpler |
| UI | Textual TUI (separate window) | Extension popup | Better UX |
| App install | pip install + install.sh | pip install + install script | Similar |
| Communication layer | None (direct) | Extension ↔ Native host protocol | Added complexity |
| Extension publishing | N/A | Chrome Web Store + Firefox AMO | Added complexity |
| UDP broadcaster | Same | Same | No change |
| Persistence | Same | Same | No change |

**Complexity removed:** Platform-specific URI handler registration (the hardest part).  
**Complexity added:** Communication protocol between extension and native host, extension publishing/signing, Native Messaging host manifest registration.

**Net result:** Simpler overall for users (especially macOS/Windows), slightly more components for developers to maintain.

---

### Holes in Feasibility

1. **Content script click interception**: A content script can intercept `<a href="acc-connector://...">` clicks via `addEventListener('click', ...)` and `preventDefault()`. This works reliably on static links. Dynamic links, JS-triggered navigation, or links in iframes may be missed. Sites like acc-status.jonatan.net, SimGrid, and LFM use standard anchor tags — this should be fine, but needs testing per site.

2. **Firefox protocol handler alternative**: Firefox extensions can declare `"protocol_handlers"` in `manifest.json`, which makes Firefox itself ask the user to open links with the extension — a slightly more native feel. Chrome does not support this; content script interception is the Chrome path.

3. **Native Messaging host manifest registration**: A one-time install step, but fully scriptable — no user interaction required:
   - **Linux/macOS**: Drop a JSON file in `~/.config/google-chrome/NativeMessagingHosts/` (Chrome) or `~/.mozilla/native-messaging-hosts/` (Firefox). No elevation needed — it's in the user's home directory.
   - **Windows**: Write a registry key under `HKCU\Software\Google\Chrome\NativeMessagingHosts\<name>`. `HKCU` does not require UAC elevation. A PowerShell one-liner handles it silently.
   - No browser restart needed after placement.
   - An `install.sh` / `install.ps1` can handle this entirely — the user just runs it once after `pip install`.

4. **Extension ↔ native host trust**: With a local HTTP server, any process on the machine can reach the host. Native Messaging is scoped to the registered extension ID — more secure. See communication options below.

---

### Extension Distribution

Three tiers of effort — no need to start with a store:

| Approach | Effort | Suitable for |
|----------|--------|-------------|
| **Sideloading (unpacked ZIP)** | Zero — share via GitHub releases | Developer/beta users comfortable with GitHub |
| **Firefox self-hosted XPI** | Low — host a signed file on any server | Power users; no Developer Mode required |
| **Chrome Web Store** | $5 one-time fee, 1–3 day review per update | Broad public distribution |
| **Firefox AMO** | Free, similar review timeline | Broad public distribution |

**Practical path**: Start with sideloading — users who find the tool on GitHub can enable Developer Mode and load an unpacked extension. Firefox is more permissive: a signed XPI hosted on GitHub can be installed with one click, no Developer Mode needed.

Store submission adds legitimacy and auto-updates but introduces review delays (code-only updates process in under an hour; manifest/permission changes take 1–7 days on Chrome). Maintenance burden is mostly Chrome's Manifest V3 requirements and the occasional re-review on permission changes.

---

### Extension ↔ Native Host Communication Options

#### Option A: Native Messaging (Recommended)

The browser's built-in IPC mechanism for extension ↔ native executable communication.

- **How it works**: Extension sends JSON objects to the native host via stdin/stdout pipes. The browser manages the process lifecycle — spawning it on the first `connectNative()` call and keeping it alive while the port is held open.
- **Chrome API**: `chrome.runtime.connectNative('com.yourname.acc_connector')` or `chrome.runtime.sendNativeMessage(...)`
- **Firefox API**: `browser.runtime.connectNative(...)` — same API shape
- **Message format**: Length-prefixed JSON (4-byte LE uint32 + JSON bytes)
- **Security**: Only the registered extension ID can communicate with the host — no other local process can reach it
- **Pros**: Secure, no open ports, browser spawns host on demand, well-documented, proven at scale (1Password, Bitwarden)
- **Cons**: Host manifest registration required (fully scriptable); host can only be reached by the extension — no CLI access

Example host manifest:
```json
{
  "name": "com.yourname.acc_connector",
  "description": "ACC Connector native host",
  "path": "/usr/local/bin/acc-connector",
  "type": "stdio",
  "allowed_origins": ["chrome-extension://EXTENSION_ID/"]
}
```

#### Option B: Local HTTP REST API

The native host exposes a small HTTP server (e.g., `http://localhost:9876`).

- **How it works**: Extension makes `fetch()` calls to localhost endpoints
- **Extension manifest**: Needs `"host_permissions": ["http://localhost:9876/*"]`
- **Endpoints**: `GET /servers`, `POST /servers`, `DELETE /servers/{id}`, `GET /status`
- **Pros**: Simple to implement (Flask/FastAPI), easy to test with curl, CLI tools can also integrate, not tied to a specific extension
- **Cons**: Open port (any local process can call it), CORS headers needed, port conflicts possible, host must already be running — browser cannot spawn it on demand

#### Option C: WebSocket

Same as HTTP but bidirectional — native host can push updates to the extension without polling.

- **Pros**: Real-time updates, single persistent connection
- **Cons**: More complex connection management, same security/port concerns as HTTP, host must already be running
- **Best for**: If the server list changes frequently and the extension popup needs live push updates

#### Recommendation

**Native Messaging** as the primary channel — secure, no open ports, and the browser handles process lifecycle automatically. If CLI access to the native host is also desirable (e.g., `acc-connector add hostname:9911`), that can coexist as a separate code path in the same executable, not requiring HTTP at all.

---

### Platform Differences Summary

| Task | Linux | macOS | Windows |
|------|-------|-------|---------|
| URI interception | Content script | Content script | Content script |
| Native host install | pip install | pip install | pip install |
| Native Messaging manifest | `~/.config/google-chrome/NativeMessagingHosts/` | `~/Library/Application Support/Google/Chrome/NativeMessagingHosts/` | `HKCU` registry key + JSON file |
| Manifest setup | install.sh (no elevation) | install.sh (no elevation) | install.ps1 (no elevation) |
| UDP broadcaster | asyncio (unchanged) | asyncio (unchanged) | asyncio (unchanged) |
| Extension install | Sideload or store | Sideload or store | Sideload or store |

No auto-start / service registration needed on any platform — the browser spawns the native host on demand via Native Messaging.

---

## Verdict

The browser extension + native host approach is a **meaningful architectural improvement**:

- Solves URI interception cleanly on all platforms (the current unsolved problem on macOS/Windows)
- Provides a much better UI (extension popup vs. terminal TUI)
- Eliminates the hardest per-platform complexity (URI handler registration, `.app` bundle signing)
- The remaining install step (Native Messaging manifest) is fully scriptable with no elevation required

The main tradeoff is two more artifacts to maintain (extension + headless native host instead of one TUI app), but the payoff is the tool actually working on macOS and Windows for the first time.

**Recommended communication**: Native Messaging — secure, no open ports, browser-managed process lifecycle.

---

## Next Steps (if approved)

1. Strip TUI from current app; make it a headless Native Messaging host (reads from stdin, runs UDP broadcaster, writes responses to stdout)
2. Write Native Messaging install scripts for Linux/macOS (`install.sh`) and Windows (`install.ps1`)
3. Build Chrome extension (Manifest V3: service worker, content script, popup)
4. Build Firefox extension (leverage `protocol_handlers` in manifest for cleaner integration)
5. Distribute via GitHub sideloading initially; submit to stores when ready
