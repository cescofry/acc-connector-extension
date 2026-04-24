# ACC Connector — Browser Extension

A browser extension + native messaging host that connects `acc-connect://` links to the ACC game's LAN server discovery system (UDP port 8999). Works on Linux, macOS, and Windows — no OS-level URI handler registration required.

## Architecture

```
Browser (Chrome/Firefox)
  └── Extension popup       — server list, discovery toggle, add/remove
  └── Content script        — intercepts acc-connect:// link clicks
  └── Service worker        — routes messages to/from native host
        ↕ Native Messaging (stdin/stdout JSON)
Native Host (Python)
  └── host.py               — message loop, action dispatch
  └── discovery.py          — async UDP broadcaster on :8999
  └── config.py             — persistence to ~/.config/acc-connector/
```

## Prerequisites

- Python 3.10+
- Chrome or Firefox

## Installation

### Quick install (Linux / macOS)

```bash
./install.sh
# Then load the extension (see step 2 below) and copy the Extension ID, then:
./install.sh --extension-id <YOUR_CHROME_EXTENSION_ID>
```

`install.sh` creates a dedicated venv at `~/.local/share/acc-connector/venv`, installs the package into it, and registers the native messaging manifests. No system-wide install or elevation needed. Firefox is registered automatically (no ID required); pass `--extension-id` only for Chrome.

### Manual install

#### 1 — Install the native host

```bash
pip install -e .
```

#### 2 — Load the extension in your browser

**Chrome / Chromium**
1. Go to `chrome://extensions`
2. Enable **Developer mode**
3. Click **Load unpacked** → select the `src/extension/` **directory**
4. Copy the **Extension ID** shown on the card

**Firefox (signed — recommended)**
1. Go to the [Releases page](https://github.com/cescofry/acc-connector-extension/releases/latest)
2. Download the `.xpi` file
3. Firefox will prompt you to install it

**Firefox (unpacked — dev only)**
1. Go to `about:debugging#/runtime/this-firefox`
2. Click **Load Temporary Add-on**
3. Select any file inside `src/extension_firefox/`

> **Why two directories?** Chrome and Firefox require different `manifest.json` fields (`service_worker` vs `scripts`), so they each need their own directory. The JS/HTML/CSS files are identical in both.

#### 3 — Register the native messaging manifest

```bash
# Chrome only (Firefox is registered automatically via its stable gecko ID)
acc-connector-setup --extension-id <YOUR_CHROME_EXTENSION_ID>

# Firefox only
acc-connector-setup --browser firefox

# Both at once (Chrome + Firefox)
acc-connector-setup --browser all --extension-id <YOUR_CHROME_EXTENSION_ID>
```

This places a JSON manifest in the correct browser-specific directory and requires no elevation.

Run `acc-connector-setup --help` for details and per-browser paths.

#### Linux — Flatpak and Snap browsers

On Linux, browsers can be installed in several ways, each with a different native messaging manifest location. `acc-connector-setup` writes to all of them unconditionally, so whichever installation method you use will be covered:

| Install method | Firefox path | Chrome / Chromium path |
|---|---|---|
| System package (apt, dnf, pacman, …) | `~/.mozilla/native-messaging-hosts/` | `~/.config/google-chrome/NativeMessagingHosts/` |
| Flatpak | `~/.var/app/org.mozilla.firefox/.mozilla/native-messaging-hosts/` | `~/.var/app/com.google.Chrome/.config/google-chrome/NativeMessagingHosts/` |
| Snap | `~/snap/firefox/common/.mozilla/native-messaging-hosts/` | `~/snap/chromium/common/.config/chromium/NativeMessagingHosts/` |

Writing to unused paths is harmless — each browser only reads from its own location.

## Usage

- Click any `acc-connect://` link on a supported site — the extension intercepts it, adds the server automatically, and opens the popup so you can confirm it worked.
- Open the extension popup from the toolbar to manage servers and toggle discovery.
- Use **+ Add Server** in the popup to add a server manually by hostname/IP, port, and optional name.

## Distribution

| Method | Instructions |
|--------|-------------|
| Sideload (unpacked) | Load unpacked via Developer mode (Chrome) or `about:debugging` (Firefox) |
| Firefox XPI | Download the signed `.xpi` from the [Releases page](https://github.com/cescofry/acc-connector-extension/releases/latest) |
| Chrome Web Store | Submit `src/extension/` as a ZIP; requires a $5 one-time fee |
| Firefox AMO | Signed automatically on each release tag via GitHub Actions (`web-ext sign`) |

## Development

```bash
pip install -e ".[dev]"
pytest
```
