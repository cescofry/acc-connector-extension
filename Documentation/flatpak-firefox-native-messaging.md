# Flatpak Firefox — Native Messaging Investigation

## The Problem

On Linux distributions that ship Firefox as a **Flatpak** (e.g. Bazzite, Fedora Silverblue, and increasingly Ubuntu), the browser extension immediately shows:

```
[ACC] Native host disconnected: Native host disconnected
```

as soon as the popup is opened. The native host never connects.

---

## System Under Investigation

- **OS**: Bazzite (Fedora Silverblue base, immutable, uses rpm-ostree)
- **Firefox**: `org.mozilla.firefox 150.0`, installed as a **system Flatpak**
- **Native host**: Python script at `~/.local/share/acc-connector/venv/bin/acc-connector-host`
- **Manifest (at time of investigation)**: `~/.mozilla/native-messaging-hosts/com.acc_connector.host.json`

---

## Diagnostic Steps Taken

### 1. Initial filesystem check

```
~/.mozilla/native-messaging-hosts/com.acc_connector.host.json  ← exists, correct content
~/.var/app/org.mozilla.firefox/.mozilla/native-messaging-hosts/ ← did not exist
flatpak list | grep -i firefox → Firefox org.mozilla.firefox 150.0 stable system
which firefox → not found (Firefox is not in PATH; it is only available as a Flatpak)
```

The host binary ran correctly when invoked manually (blocked waiting for stdin as expected). The log file (`~/.config/acc-connector/host.log`) showed only a single line from the manual run — no entries from any Firefox-initiated connection.

### 2. JS-side error interpretation

The browser console showed:

```
[ACC] Native host disconnected. lastError: null  message: Native host disconnected (no lastError)
Background event page was not terminated on idle because a DevTools toolbox is attached to the extension.
```

`lastError: null` was initially interpreted as a clean host exit (code 0), leading to the MV3 event-page hypothesis (see below). This interpretation was later found to be wrong — see **Firefox Bug 1330223**.

---

## What Was Tried (and Why Each Was Abandoned)

### Attempt 1 — Flatpak manifest path (conditional)

**Hypothesis**: Flatpak Firefox looks for manifests in `~/.var/app/org.mozilla.firefox/.mozilla/native-messaging-hosts/` rather than `~/.mozilla/native-messaging-hosts/`.

**Change**: Added `_flatpak_installed()` check in `setup.py` that wrote to the Flatpak path only if `~/.var/app/org.mozilla.firefox` already existed.

**Why it failed**: On a system-installed Flatpak, `~/.var/app/org.mozilla.firefox` may not exist until the app has been run in a specific way. The check returned `False` and the Flatpak path was never written.

---

### Attempt 2 — Flatpak + Snap manifest paths (unconditional)

**Change**: Removed the existence check. `setup.py` now unconditionally writes the manifest to all candidate paths on Linux:

| Install method | Firefox path | Chrome / Chromium path |
|---|---|---|
| System package | `~/.mozilla/native-messaging-hosts/` | `~/.config/google-chrome/NativeMessagingHosts/` |
| Flatpak | `~/.var/app/org.mozilla.firefox/.mozilla/native-messaging-hosts/` | `~/.var/app/com.google.Chrome/.config/google-chrome/NativeMessagingHosts/` |
| Snap | `~/snap/firefox/common/.mozilla/native-messaging-hosts/` | `~/snap/chromium/common/.config/chromium/NativeMessagingHosts/` |

**Why it didn't fix the issue**: Writing to the Flatpak path is necessary but not sufficient. Flatpak Firefox cannot execute the binary referenced in the manifest due to sandbox restrictions (see Root Cause below). The manifest paths are now correct and should be kept.

---

### Attempt 3 — MV3 event page lifecycle (reverted)

**Hypothesis**: The `lastError: null` clean disconnect and the DevTools message ("Background event page was not terminated on idle") indicated Firefox MV3's non-persistent event page was being suspended, closing the native messaging port.

**Change**: Switched `src/extension_firefox/manifest.json` from MV3 to MV2 with `"persistent": true`.

**Why it was reverted**:
- **Firefox Bug 1770696** (fixed in Firefox 104): Firefox already resets the idle timer when a native messaging port is open. Firefox 150 has this fix.
- **Firefox Bug 1330223**: `lastError` is null even when `connectNative` *fails* — the null lastError does **not** mean the host connected and exited cleanly. The original interpretation was wrong.
- The manifest was reverted to MV3.

---

### Attempt 4 — Debug logging

**Changes kept** (these are useful regardless):
- `host.py`: Added `log.info("Native host starting")`, `log.info("Run loop started")`, `log.info("stdin closed — exiting")`, and a top-level `try/except` that logs fatal errors before re-raising.
- `background.js` (both Chrome and Firefox): `lastError` is now logged as a full object, not just `.message`, to expose Firefox Bug 1330223 cases.
- `host.py`: Added `get_log` action — the extension requests the last 100 lines of `~/.config/acc-connector/host.log` on every connect and prints them to the extension console via `console.debug("[ACC] host.log:\n" + msg.log)`.

---

## Root Cause

**Flatpak Firefox cannot spawn native messaging hosts.** This is an architectural sandbox limitation, not a configuration problem.

Flatpak confines Firefox and prevents it from executing arbitrary host-system binaries. The native messaging protocol requires the browser to `execve()` the binary referenced in the manifest — something the Flatpak sandbox explicitly forbids.

**Relevant bugs**:
- **Mozilla Bug 1621763** — "[flatpak] Support native messaging" — open for years, resolved as duplicate of Bug 1955255
- **Mozilla Bug 1955255** — "[flatpak] [snap] Implement xdg-native-messaging-proxy frontend" (covers both Flatpak and Snap) — status **NEW**, active as of April 2026; patch actively under review

**Affected projects**: KeePassXC, 1Password, GNOME Shell integration, KDE Plasma Browser integration, PWAsForFirefox — all have the same open issue with Flatpak Firefox.

---

## What Should Be Tried Next

> **Current approach (under validation):** Option B — `flatpak-spawn --host` wrapper has been implemented in `acc-connector-setup` and is being tested in production. Options A and C are kept below for reference until the result is confirmed.

### Option A — System (non-Flatpak) Firefox [simplest, recommended for now]

On Bazzite/Fedora Silverblue, install Firefox as a layered system package:

```bash
rpm-ostree install firefox
# reboot
```

Then run `acc-connector-setup --browser firefox` normally. The manifest at `~/.mozilla/native-messaging-hosts/` will be found and the host will be spawned without sandbox restrictions.

---

### Option B — `flatpak-spawn --host` wrapper script *(current approach — under validation)*

This is a known workaround used by 1Password and KeePassXC. It works but partially defeats the Flatpak sandbox.

**How it works**: A small shell script placed inside Firefox's Flatpak data directory calls `flatpak-spawn --host <actual-binary> "$@"`, which asks the Flatpak DBus service to spawn the process *outside* the sandbox with stdin/stdout piped back in.

**Steps**:

1. Create the wrapper:
```bash
mkdir -p ~/.var/app/org.mozilla.firefox/data/bin
cat > ~/.var/app/org.mozilla.firefox/data/bin/acc-connector-wrapper.sh << 'EOF'
#!/bin/bash
flatpak-spawn --host "$HOME/.local/share/acc-connector/venv/bin/acc-connector-host" "$@"
EOF
chmod +x ~/.var/app/org.mozilla.firefox/data/bin/acc-connector-wrapper.sh
```

2. Grant Firefox session bus access (required for `flatpak-spawn`):
```bash
flatpak override --user --socket=session-bus org.mozilla.firefox
flatpak override --user --talk-name=org.freedesktop.Flatpak org.mozilla.firefox
```
`--socket=session-bus` alone is not sufficient — `--talk-name=org.freedesktop.Flatpak` is also required. Without it `flatpak-spawn --host` fails immediately with "ServiceUnknown: --host only works when the Flatpak is allowed to talk to org.freedesktop.Flatpak".

3. Update the manifest to point to the wrapper instead of the Python binary directly. Either manually edit `~/.var/app/org.mozilla.firefox/.mozilla/native-messaging-hosts/com.acc_connector.host.json` and set `"path"` to the wrapper path, or extend `acc-connector-setup` to generate a wrapper automatically when Flatpak Firefox is detected.

**Security implications**: If Firefox is compromised via a browser exploit, `flatpak-spawn --host` can be used to execute arbitrary binaries as the user — negating the sandbox protection. The risk is comparable to non-Flatpak Firefox, but you are not getting the isolation you pay for. Considered acceptable short-term if Firefox is kept updated.

**What was built**: `acc-connector-setup` now detects Flatpak Firefox via `flatpak list`, generates the wrapper script at `~/.var/app/org.mozilla.firefox/data/bin/acc-connector-wrapper.sh`, grants session-bus access via `flatpak override --user --socket=session-bus org.mozilla.firefox`, and writes the Flatpak manifest pointing to the wrapper. Non-Flatpak manifest paths continue to point directly to the Python binary.

---

### Option C — `xdg-native-messaging-proxy` [proper long-term fix]

`xdg-native-messaging-proxy` is a small DBus service that runs outside the sandbox and proxies native messaging calls from sandboxed browsers. It is the official upstream solution.

**Current status** (as of April 2026):
- v0.1.0 released March 26, 2025 — only one release to date
- Available in: Arch AUR, Debian unstable + bookworm-backports
- Ubuntu ships native messaging proxy functionality as a **patch to `xdg-desktop-portal`** (not yet as the standalone package); Ubuntu Bug [#2144020](http://www.mail-archive.com/desktop-bugs@lists.ubuntu.com/msg830235.html) tracks the transition to the standalone package
- **Not packaged for Fedora or Bazzite**
- RHEL 10 has committed to shipping it
- Mozilla Bug 1955255 (Firefox frontend support) is open and actively reviewed

**What needs to happen**: Wait for Fedora/Bazzite to package `xdg-native-messaging-proxy` and for Firefox to ship the frontend support. No code changes needed on this project's side once the infrastructure exists — the manifest files already written to the correct paths will be picked up automatically.

**Track**: [Mozilla Bug 1955255](https://bugzilla.mozilla.org/show_bug.cgi?id=1955255) and [xdg-native-messaging-proxy](https://github.com/flatpak/xdg-native-messaging-proxy).

---

## Files Changed During This Investigation

| File | Change | Status |
|---|---|---|
| `src/native_host/setup.py` | Unconditional Flatpak + Snap paths for all Linux browsers | **Keep** |
| `src/native_host/host.py` | Added startup/shutdown/error logging; added `get_log` action | **Keep** |
| `src/extension_firefox/background.js` | Full `lastError` object logged on disconnect; `get_log` requested on connect | **Keep** |
| `src/extension/background.js` | Same logging improvements as Firefox version | **Keep** |
| `src/extension_firefox/manifest.json` | Temporarily changed to MV2, then reverted back to MV3 | **Reverted to MV3** |
| `README.md` | Flatpak/Snap path table moved to this document | **Removed from README** |
