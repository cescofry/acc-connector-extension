# Rewrite Plan: Native Rust Host with URI Interception

## Context

The browser extension approach has fundamental problems: the raw socket IP spoofing required for correct ACC discovery cannot be solved cleanly across platforms from a browser extension's native host, and the architecture adds browser lifecycle dependency and native messaging complexity for no benefit that cannot be achieved with a native URI scheme handler. This plan replaces the browser extension and Python host with a standalone Rust application.

---

## Phase 1: C `setcap` Hack (Validation Only)

**Goal:** Confirm that the end-to-end flow — URI interception → server list → spoofed UDP discovery response → ACC connects — works correctly before committing to a rewrite.

### What to build

A minimal C binary (`raw_send`) that:
- Accepts server IP, port, server name, and discovery ID as arguments.
- Opens a raw UDP socket.
- Constructs and sends a UDP packet with the remote server's IP as the source address and the correct ACC discovery response format.

The existing Python host calls this binary via `subprocess` when it needs to respond to a discovery broadcast.

### Installation

```sh
gcc -o raw_send raw_send.c
sudo setcap cap_net_raw+ep ./raw_send
```

`setcap` is applied to the ELF binary, not to the Python entry point (which is a script and is ignored by the kernel's capability loader).

### Success criteria

- ACC receives a discovery response with the correct source IP.
- ACC successfully establishes a TCP connection to the remote server.
- The server appears and is joinable from the ACC server list.

### Outcome

Once validated, this phase is complete and the C binary is deleted. It is a throwaway proof-of-concept, not a deliverable.

---

## Phase 2: Scrap the Current Implementation

Once Phase 1 confirms the approach works:

- Delete the browser extension (`browser-extension/`).
- Delete the Python native host (`src/native_host/`).
- Delete native messaging manifests and installer scripts.
- Archive or close the browser extension plan document.

The git history preserves the full implementation if any reference is needed.

---

## Phase 3: Rust Host Application

### Overview

A single compiled Rust binary that:
1. Registers as the `acc-connect://` URI scheme handler via a `.desktop` file (Linux).
2. Listens for ACC LAN discovery broadcasts on UDP port 8999.
3. Responds to discovery broadcasts with spoofed UDP packets (raw socket, `setcap cap_net_raw+ep` applied at install).
4. Manages an in-memory list of servers (with optional persistence to disk).
5. Runs an embedded web server for the management UI.

### URI scheme handling

A `.desktop` file is installed to `~/.local/share/applications/acc-connector.desktop`:

```ini
[Desktop Entry]
Name=ACC Connector
Exec=/usr/local/bin/acc-connector %u
MimeType=x-scheme-handler/acc-connect;
Type=Application
NoDisplay=true
```

`xdg-mime default acc-connector.desktop x-scheme-handler/acc-connect` registers it as the default handler. When a user clicks an `acc-connect://` URI on a league website, the browser hands it to the OS, which invokes the binary with the URI as an argument.

The binary parses the URI (name, IP, port), adds the server to the active list, and opens the management UI in the default browser.

### Discovery response

The binary listens on UDP port 8999. When ACC broadcasts a discovery packet (`0xBF 0x48` magic, 6 bytes, destination `255.255.255.255:8999`), it sends one spoofed UDP response per server in the active list. Each response is constructed using a raw socket, with the source address set to the server's real IP. `setcap cap_net_raw+ep` is applied to the binary at install time.

### Async runtime

`tokio` with three concurrent tasks:
- UDP listener (discovery broadcast handler).
- Raw socket sender (discovery response writer).
- HTTP server (management UI).

### Installation

```sh
sudo cp acc-connector /usr/local/bin/
sudo setcap cap_net_raw+ep /usr/local/bin/acc-connector
xdg-mime default acc-connector.desktop x-scheme-handler/acc-connect
```

---

## Phase 4: Embedded Web Server (Management UI)

### Behaviour

When a server is added via a clicked `acc-connect://` URI, the binary opens `http://localhost:<port>` in the default browser automatically. The same URL can be opened manually at any time.

The UI is served from memory (HTML/CSS/JS embedded in the binary at compile time via `include_str!` or similar). No external files are needed at runtime.

### Features

| Feature | Detail |
|---|---|
| Server list | Shows all currently active servers (name, IP, port, persist toggle) |
| Add server manually | Form: name, IP, port — for users who have server details but no URI link |
| Remove server | Removes from the active list; if persisted, removes from disk |
| Persist toggle | Per-server. Off by default. Persisted servers are reloaded on next launch |

### Persistence

Non-persisted servers exist only for the current session (cleared when the process exits). Persisted servers are written to `~/.config/acc-connector/servers.json` and loaded on startup.

### API

The web server exposes a minimal JSON API consumed by the UI:

| Method | Path | Action |
|---|---|---|
| `GET` | `/api/servers` | List active servers |
| `POST` | `/api/servers` | Add a server (`{name, ip, port, persist}`) |
| `DELETE` | `/api/servers/:id` | Remove a server |
| `PATCH` | `/api/servers/:id` | Update persist flag |

---

## Summary

| Phase | Status | Deliverable |
|---|---|---|
| 1 — C `setcap` hack | Throwaway | End-to-end validation only |
| 2 — Remove current codebase | Cleanup | Clean repo |
| 3 — Rust host binary | Core deliverable | URI handler + discovery responder |
| 4 — Embedded web UI | Core deliverable | Management interface |
