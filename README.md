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

### 1 — Install the native host

```bash
cd extension/
pip install -e .
```

### 2 — Load the extension in your browser

**Chrome / Chromium**
1. Go to `chrome://extensions`
2. Enable **Developer mode**
3. Click **Load unpacked** → select the `extension/src/extension/` **directory**
4. Copy the **Extension ID** shown on the card

**Firefox**
1. Go to `about:debugging#/runtime/this-firefox`
2. Click **Load Temporary Add-on**
3. Select any file inside `extension/src/extension_firefox/` — Firefox uses that directory's `manifest.json`
4. Copy the **Extension ID** shown

> **Why two directories?** Firefox's "Load Temporary Add-on" always reads `manifest.json` from whichever directory you pick. Chrome and Firefox require different `manifest.json` fields (`service_worker` vs `scripts`), so they each need their own directory. The JS/HTML/CSS files are identical in both.

### 3 — Register the native messaging manifest

```bash
# Linux / macOS
acc-connector-setup --extension-id <YOUR_EXTENSION_ID>

# Windows (PowerShell)
acc-connector-setup --extension-id <YOUR_EXTENSION_ID>
```

This places a JSON manifest in the correct browser-specific directory and requires no elevation.

Run `acc-connector-setup --help` for details and per-browser paths.

## Usage

- Click any `acc-connect://` link on a supported site — the extension intercepts it and adds the server automatically.
- Open the extension popup from the toolbar to manage servers and toggle discovery.

## Extension icons

The extension ships without custom icons (the browser shows its default). To add icons:

1. Create PNG files at `src/extension/icons/icon16.png`, `icon48.png`, `icon128.png`
2. Uncomment the `"icons"` block in both `manifest.json` and `manifest_firefox.json`

## Distribution

| Method | Instructions |
|--------|-------------|
| Sideload (unpacked) | Load unpacked via Developer mode (Chrome) or `about:debugging` (Firefox) |
| Firefox XPI | `web-ext build` → host the `.xpi` on any server |
| Chrome Web Store | Submit `src/extension/` as a ZIP; requires a $5 one-time fee |
| Firefox AMO | Submit via `web-ext sign` or the AMO developer hub |

## Development

```bash
cd extension/
pip install -e ".[dev]"
pytest
```
