#!/usr/bin/env python3
"""acc-connector-setup — installs the native messaging host manifest.

Usage:
  acc-connector-setup --extension-id <CHROME_EXTENSION_ID> [--browser chrome|firefox|all]
  acc-connector-setup --help

Firefox uses a stable gecko ID declared in the extension manifest, so
--extension-id is only required when configuring Chrome.
"""
from __future__ import annotations

import argparse
import json
import platform
import shutil
import sys
from pathlib import Path

HOST_NAME = "com.acc_connector.host"
# Stable gecko ID declared in src/extension_firefox/manifest.json.
# Firefox native messaging uses allowed_extensions with this string ID —
# no random UUID needed.
FIREFOX_GECKO_ID = "acc-connector@acc-connector"


def _host_executable() -> str:
    # Prefer the binary sitting next to this Python interpreter (venv case).
    bin_dir = Path(sys.executable).parent
    exe = bin_dir / ("acc-connector-host.exe" if platform.system() == "Windows" else "acc-connector-host")
    if exe.exists():
        return str(exe)
    # Fall back to PATH search (system-wide install).
    found = shutil.which("acc-connector-host")
    if found:
        return found
    sys.exit("Error: acc-connector-host not found. Run: pip install -e . inside your venv.")


def _chrome_manifest(host_path: str, extension_id: str) -> dict:
    return {
        "name": HOST_NAME,
        "description": "ACC Connector native messaging host",
        "path": host_path,
        "type": "stdio",
        "allowed_origins": [f"chrome-extension://{extension_id}/"],
    }


def _firefox_manifest(host_path: str) -> dict:
    # Firefox uses allowed_extensions with the gecko string ID, not allowed_origins.
    return {
        "name": HOST_NAME,
        "description": "ACC Connector native messaging host",
        "path": host_path,
        "type": "stdio",
        "allowed_extensions": [FIREFOX_GECKO_ID],
    }


def _chrome_dirs() -> list[Path]:
    os_name = platform.system()
    home = Path.home()
    if os_name == "Linux":
        return [
            home / ".config" / "google-chrome" / "NativeMessagingHosts",
            home / ".config" / "chromium" / "NativeMessagingHosts",
            # Flatpak (user or system install).
            home / ".var" / "app" / "com.google.Chrome" / ".config" / "google-chrome" / "NativeMessagingHosts",
            home / ".var" / "app" / "com.google.ChromeDev" / ".config" / "google-chrome" / "NativeMessagingHosts",
            home / ".var" / "app" / "org.chromium.Chromium" / ".config" / "chromium" / "NativeMessagingHosts",
            # Snap (Ubuntu and derivatives).
            home / "snap" / "chromium" / "common" / ".config" / "chromium" / "NativeMessagingHosts",
        ]
    if os_name == "Darwin":
        return [
            home / "Library" / "Application Support" / "Google" / "Chrome" / "NativeMessagingHosts",
            home / "Library" / "Application Support" / "Chromium" / "NativeMessagingHosts",
        ]
    if os_name == "Windows":
        return [Path.home() / "AppData" / "Local" / "Google" / "Chrome" / "NativeMessagingHosts"]
    return []


def _firefox_dirs() -> list[Path]:
    os_name = platform.system()
    home = Path.home()
    if os_name == "Linux":
        return [
            home / ".mozilla" / "native-messaging-hosts",
            # Flatpak (user or system install).
            home / ".var" / "app" / "org.mozilla.firefox" / ".mozilla" / "native-messaging-hosts",
            # Snap (Ubuntu and derivatives).
            home / "snap" / "firefox" / "common" / ".mozilla" / "native-messaging-hosts",
        ]
    if os_name == "Darwin":
        return [home / "Library" / "Application Support" / "Mozilla" / "NativeMessagingHosts"]
    if os_name == "Windows":
        return [home / "AppData" / "Roaming" / "Mozilla" / "NativeMessagingHosts"]
    return []


def _install_manifest(directory: Path, manifest: dict) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    dest = directory / f"{HOST_NAME}.json"
    dest.write_text(json.dumps(manifest, indent=2))
    print(f"  Wrote {dest}")


def _install_windows_registry(host_path: str, extension_id: str) -> None:
    """Write HKCU registry key for Chrome on Windows (no elevation required)."""
    import winreg  # type: ignore[import]

    manifest_path = (
        Path.home() / "AppData" / "Local" / "Google" / "Chrome" / "NativeMessagingHosts" / f"{HOST_NAME}.json"
    )
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(_chrome_manifest(host_path, extension_id), indent=2))

    reg_path = rf"Software\Google\Chrome\NativeMessagingHosts\{HOST_NAME}"
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, reg_path) as key:
        winreg.SetValueEx(key, "", 0, winreg.REG_SZ, str(manifest_path))
    print(f"  Registry key written: HKCU\\{reg_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Install the ACC Connector native messaging manifest.")
    parser.add_argument(
        "--extension-id",
        default="",
        help="Chrome extension ID (shown on chrome://extensions after loading the extension). Not needed for Firefox.",
    )
    parser.add_argument(
        "--browser",
        choices=["chrome", "firefox", "all"],
        default="all",
        help="Which browser(s) to configure (default: all)",
    )
    args = parser.parse_args()

    host_path = _host_executable()
    os_name = platform.system()

    print(f"Installing native messaging host: {HOST_NAME}")
    print(f"  Host executable: {host_path}")
    print()

    if args.browser in ("chrome", "all"):
        if not args.extension_id:
            print("Chrome/Chromium: skipped (pass --extension-id <ID> to configure Chrome)")
        else:
            print("Chrome/Chromium:")
            if os_name == "Windows":
                _install_windows_registry(host_path, args.extension_id)
            else:
                for d in _chrome_dirs():
                    _install_manifest(d, _chrome_manifest(host_path, args.extension_id))

    if args.browser in ("firefox", "all"):
        print(f"Firefox (gecko ID: {FIREFOX_GECKO_ID}):")
        for d in _firefox_dirs():
            _install_manifest(d, _firefox_manifest(host_path))

    print()
    print("Done. Reload your extension if it is already open.")


if __name__ == "__main__":
    main()
