# Discovery Protocol Investigation & Native Host Architecture Options

## Background

This document summarises the findings from a deep investigation into why the browser extension's LAN server discovery was not working, what the original Windows `acc-connector` project actually does under the hood, and what architectural options are available to fix it correctly.

---

## The Original Windows Project: How It Actually Works

The reference implementation ([lonemeow/acc-connector](https://github.com/lonemeow/acc-connector)) is a **DLL injection tool**, not a UDP server. This is the key insight that explains everything.

### Mechanism

The project ships a DLL that masquerades as `hid.dll` and is placed inside ACC's installation directory at `AC2/Binaries/Win64/hid.dll`. When ACC loads, it loads this DLL, which uses [MinHook](https://github.com/TsudaKageyu/minhook) to hook two Winsock functions inside the ACC process:

- `ws2_32!sendto` — to detect when ACC broadcasts a LAN discovery request
- `ws2_32!recvfrom` — to intercept the receive call and inject fake responses

### The Discovery Request

ACC broadcasts a 6-byte UDP packet to `255.255.255.255:8999`:

```
Offset  Size  Field         Value
0       1     Magic[0]      0xBF
1       1     Magic[1]      0x48
2-5     4     Discovery ID  uint32, little-endian
```

The hook on `sendto` detects this packet (checks destination port = 8999, length = 6, first two bytes = `0xBF 0x48`) and records the discovery ID.

### The Discovery Response Packet Format

The hook on `recvfrom` synthesises a fake response **without any real UDP packet being sent**. The response packet structure is:

```
Offset              Size          Field         Value / Encoding
0                   1             Header        0xC0
1                   1             Name length   character count (uint8)
2                   name_len × 4  Server name   UTF-32-LE (4 bytes per character)
2 + name_len×4      1             Constant[0]   0x00
3 + name_len×4      1             Constant[1]   0x01
4 + name_len×4      2             Port          big-endian uint16
6 + name_len×4      4             Discovery ID  little-endian uint32 (echoed from request)
10 + name_len×4     1             Footer        0xFA
```

**Important:** the server's IP address is NOT in the packet bytes.

### How the Server IP Is Communicated

This is the critical point. The `recvfrom` hook does two things simultaneously:

1. Writes the fake packet bytes into the buffer ACC provided.
2. **Writes the server's resolved IPv4 address directly into the `from` sockaddr** that `recvfrom` fills in — specifically `sin->sin_addr.S_un.S_addr = server->ip`.

ACC never receives a real UDP packet. Instead, the hook returns a fabricated result from inside the ACC process itself, with the `from` address set to the remote server's real IP. ACC then uses that IP (plus the port from the packet) to establish its game connection.

### IPC Between GUI and DLL

The Windows GUI component (`client-gui`, written in C#) maintains a named pipe server at `\\.\pipe\acc-connector-pipe`. When the injected DLL detects a discovery broadcast, it reads a `shared_memory` struct from the pipe containing up to 100 server entries. Each entry holds the server name (UTF-32, zero-padded to 1024 bytes), the resolved IPv4 address (uint32), and the TCP port. The DLL then synthesises one fake `recvfrom` response per entry.

### ACC's Connection Protocol

ACC uses a two-phase connection:

1. **TCP** — the client connects to `tcpPort` for the initial session handshake.
2. **UDP** — real-time car position streaming uses `udpPort`, which the server communicates to the client *over the established TCP connection*.

Both ports are configurable per server and often share the same number. The port stored in an `acc-connect://` URI is the TCP port.

---

## The Browser Extension's Fundamental Problem

The browser extension cannot use DLL injection. Instead, it sends **real UDP packets** from the native host process. When ACC calls `recvfrom` and receives one of these packets, the `from` address reflects the actual sender — the local machine running the native host (e.g. `192.168.1.137`), not the remote server.

ACC therefore sees every advertised server as residing at the local machine's IP. It then tries to establish a TCP connection to `192.168.1.137:port`. Since no game server is running there, the connection fails and the server either does not appear or appears but immediately fails to connect.

The packet format itself (UTF-32-LE name, `0x00 0x01` constant, big-endian port, little-endian discovery ID, no IP bytes) is **correct** per the reference implementation. The discovery packets are received by ACC. The problem is purely the source address.

---

## Options to Fix This

### Option A: TCP Proxy (Rejected)

The native host starts a local TCP proxy for each server. The discovery response advertises `192.168.1.137:localProxyPort`. When ACC connects, the proxy forwards the TCP stream to the real remote server.

**Why this is wrong for a racing tool:**

- The proxy stays in the middle of every byte of game data for the entire race session.
- If Firefox crashes, the native host dies, the proxy dies, and ACC loses its connection mid-race.
- Added latency on every packet, however small.
- The extension becomes a permanent dependency on live connection quality.
- The browser extension should have no involvement once the player is in a session.

This approach contradicts the fundamental design goal: **the extension's job ends at discovery**.

### Option B: Raw Socket IP Spoofing — C Helper (Short-term fix)

A small compiled C binary (~20 lines) opens a raw socket, constructs a UDP packet with the remote server's IP as the source address, and sends it. The Python native host calls this binary via `subprocess` whenever it needs to send a discovery response.

The C helper is compiled to a native ELF binary, so `setcap cap_net_raw+ep` applies to it cleanly. The Python host itself never needs elevated privileges.

**Why `setcap` cannot be applied to the Python entry point:**

`setcap` only works on ELF binaries. The `acc-connector-host` entry point installed by pip is a Python script starting with `#!/usr/bin/env python3`. The kernel ignores file capabilities on interpreter scripts, so `setcap` on that path has no effect.

**Pros:**
- Minimal code change to the existing Python host.
- Fixes the IP spoofing problem correctly.
- Extension is out of the picture after discovery.

**Cons:**
- Splits the codebase: Python host + C helper.
- Two build artifacts to compile and distribute.
- Subprocess call on every discovery response (minor overhead, acceptable).
- Adds a C build step to the install process.
- Accumulates technical debt if a Rust rewrite is planned anyway.

### Option C: Rewrite the Native Host in Rust (Recommended long-term)

Rewrite `host.py`, `discovery.py`, `models.py`, and `config.py` as a single compiled Rust binary. The binary opens a raw socket for IP-spoofed discovery responses directly, without any subprocess.

#### Why This Is the Clean Solution

- **`setcap` works directly on the binary.** `sudo setcap cap_net_raw+ep acc-connector-host` applies to the compiled Rust binary with no workarounds. The binary holds `CAP_NET_RAW` and uses raw sockets inline.
- **No Python runtime dependency.** Users do not need Python, pip, or a virtualenv. The install script goes from "create venv → pip install → register manifest" to "copy binary → setcap → register manifest".
- **Single artifact.** One binary replaces four Python modules and all their dependencies.
- **Flatpak still works.** The `flatpak-spawn --host` wrapper calls the host binary on the host system. Since `setcap` is applied to that binary on the host, the spawned process inherits `CAP_NET_RAW` transparently.
- **The codebase is small.** The Python native host is ~400 lines across 4 files. A Rust equivalent using `tokio` for async I/O (stdin/stdout native messaging + UDP listener task + raw socket sends) is a realistic and bounded rewrite.
- **Clean architecture.** The existing design — async event loop, message dispatch, UDP server — maps directly onto Rust/tokio idioms.

#### What GitHub Actions Provides

GitHub Actions has first-class Rust support via `dtolnay/rust-toolchain@stable`, the community standard action. For this project:

- **Linux, macOS, and Windows binaries** can be built natively using a matrix strategy (`ubuntu-latest`, `macos-latest`, `windows-latest`) — no cross-compilation needed.
- **Release artifacts** are attached automatically to GitHub Releases, so end users download a pre-built binary and never need the Rust toolchain installed.
- **`cargo test`** runs the full test suite in CI.
- The "Rust build toolchain" cost for end users is effectively zero.

#### Migration Path

The C helper (Option B) can be implemented first as a short-term fix if the raw socket behaviour is needed immediately. The Rust rewrite can proceed in parallel or as a follow-up, at which point the C helper is deleted and the Python host is replaced entirely. No changes to the browser extension are required in either case — the native messaging interface remains identical.

---

## Platform Scope and the Value of the Browser Extension Approach

The raw socket solution — whether implemented via a C helper or a Rust binary — only works cleanly on Linux. macOS requires a privileged helper daemon registered with `launchd`, which is a non-trivial installation burden involving code signing and macOS-specific tooling. Windows blocks IP spoofing at the Winsock layer entirely, meaning the correct solution there remains DLL injection as the original project implements it. These are not minor variations on a shared approach; they are fundamentally different mechanisms requiring separate implementation, separate installation logic, and separate maintenance paths for each platform.

This undermines one of the central arguments for the browser extension architecture: cross-platform reach from a single codebase. If the native host must be written differently per OS anyway — a Rust binary with `setcap` on Linux, a privileged daemon on macOS, a DLL injector on Windows — then the native messaging layer adds complexity without delivering on the multiplatform promise. The browser extension sits on top of that complexity and contributes its own: manifest installation, browser compatibility, native messaging protocol, and the fact that a browser crash can interrupt discovery.

It is worth questioning whether the browser extension is the right vehicle for this tool at all. The critical context here is how the tool is actually used in practice: virtually no user enters a server IP and port manually. The primary usage pattern is that league organisers publish `acc-connect://` URIs on their web sites, and drivers click them to join a server directly. The browser extension exists to intercept those clicks and translate them into ACC discovery responses. That interception capability is not a convenience feature — it is the entire point of the tool, and it is something a standalone GUI application cannot do without also installing a custom URI scheme handler at the OS level.

This changes the architectural question. The browser extension is justified by the URI interception use case. The problem is that URI scheme handling from a browser page can also be accomplished without an extension at all: registering a custom protocol handler (`acc-connect://`) at the OS level routes those clicks directly to a native application, bypassing the browser extension entirely. All major operating systems support this — `xdg-open` and `.desktop` files on Linux, `Info.plist` `CFBundleURLTypes` on macOS, registry keys on Windows. A native tray application registered as the `acc-connect://` handler would receive the URI, parse the server details, and inject the discovery response using the appropriate OS mechanism — no browser extension, no native messaging protocol, no browser lifecycle dependency. The user experience from the driver's perspective would be identical: click a link on a league site, ACC connects to the server.

---

## Summary

| | TCP Proxy | C Helper | Rust Rewrite |
|---|---|---|---|
| Extension stays in-loop after discovery | Yes — bad | No | No |
| Race connection risk | High | None | None |
| Privilege required | None | `setcap` at install | `setcap` at install |
| Python runtime required | Yes | Yes | No |
| Single binary | No | No | Yes |
| Build complexity | Low | Medium (C toolchain) | Low (GitHub Actions) |
| Long-term maintenance | Poor | Moderate | Good |
| Recommended | No | Short-term only | Yes |
