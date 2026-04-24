# ACC Connector — Browser Extension

A browser extension + native messaging host that connects `acc-connect://` links to the ACC game's LAN server discovery system (UDP port 8999). Works on Linux, macOS, and Windows — no OS-level URI handler registration required.

## Installation

### Step 1 — Install the native host

The extension alone is not enough. A small Python process runs on your machine and handles the actual ACC communication. The extension talks to it via the browser's Native Messaging protocol.

**Linux / macOS**

```bash
# Download and extract the release archive, then run:
./install.sh
```

`install.sh` creates a dedicated Python venv at `~/.local/share/acc-connector/venv`, installs the host into it, and registers the native messaging manifests for Firefox (and optionally Chrome). No system-wide install or elevation needed.

**Windows**

Manual steps for now — see [Manual install](#manual-install) below.

---

### Step 2 — Install the browser extension

**Firefox**

1. Go to the [Releases page](https://github.com/cescofry/acc-connector-extension/releases)
2. Download the `.xpi` file from the latest release
3. Open Firefox and navigate to `about:addons`
4. Click the gear icon → **Install Add-on From File…** → select the `.xpi`
5. Firefox will prompt you to confirm — click **Add**

> Firefox may also prompt you automatically if you open the `.xpi` directly in the browser.

**Chrome / Chromium**

1. Go to `chrome://extensions`
2. Enable **Developer mode**
3. Click **Load unpacked** → select the `src/extension/` directory from the release archive
4. Copy the **Extension ID** shown on the card — you will need it in the next step

---

### Step 3 — Register the native messaging manifest

> **Firefox**: `install.sh` already does this automatically. You can skip this step unless Firefox was installed as a Flatpak or Snap (see note below).

**Chrome / Chromium only** — run once after loading the extension:

```bash
~/.local/share/acc-connector/venv/bin/acc-connector-setup --extension-id <YOUR_CHROME_EXTENSION_ID>
```

**Firefox only** (if you need to re-run it):

```bash
~/.local/share/acc-connector/venv/bin/acc-connector-setup --browser firefox
```

> **Flatpak / Snap Firefox users**: `acc-connector-setup` detects a Flatpak or Snap Firefox automatically and sets up the required wrapper. See `Documentation/flatpak-firefox-native-messaging.md` for details if something goes wrong.

---

## Usage

- Click any `acc-connect://` link on a supported site — the extension intercepts it, adds the server automatically, and opens the popup to confirm.
- Open the extension popup from the toolbar to manage servers and toggle LAN discovery.
- Use **+ Add Server** in the popup to add a server manually by hostname/IP, port, and optional name.

---

## Manual install

Use this if `install.sh` is not available (e.g. Windows, or if you prefer to manage the venv yourself).

#### 1 — Install the native host

```bash
pip install -e .
```

#### 2 — Load the extension

See [Step 2](#step-2--install-the-browser-extension) above.

#### 3 — Register the native messaging manifest

```bash
# Firefox only
acc-connector-setup --browser firefox

# Chrome only
acc-connector-setup --extension-id <YOUR_CHROME_EXTENSION_ID>

# Both at once
acc-connector-setup --browser all --extension-id <YOUR_CHROME_EXTENSION_ID>
```

Run `acc-connector-setup --help` for per-browser manifest paths and options.

---

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

## Development

```bash
pip install -e ".[dev]"
pytest
```

